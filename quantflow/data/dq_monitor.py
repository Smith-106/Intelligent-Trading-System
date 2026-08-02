"""Real-time data quality monitor — prevent stale/corrupt data feeds.

G4 Implementation: Deploys runtime data validation to prevent silent acceptance
of stale or corrupt market data that could lead to incorrect trading decisions.

Features:
- Real-time bar validation before publishing
- Freshness checks (staleness detection)
- Price continuity validation (spike detection)
- Volume anomaly detection
- Prometheus metrics and alarms
- Data quality scoring (0-1 scale)

Architecture:
    WebSocket Feed → DataQualityMonitor.validate_bar() → EventBus.publish()
                              ↓
                    Prometheus Metrics (dq_monitor_violations_total)
                              ↓
                    Alert Classification (G5) → Notification Channels

Usage:
    monitor = DataQualityMonitor(redis_cache=redis)
    
    async def on_bar(bar: Bar):
        result = await monitor.validate_bar(bar)
        if result.valid:
            await event_bus.publish(EventType.BAR, bar)
        else:
            logger.warning("Bar rejected: %s", result.violations)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DataQualityScore:
    """Composite data quality score (0-1 scale).
    
    Higher scores indicate better data quality.
    """
    
    freshness_score: float = 1.0  # 0-1 based on staleness
    continuity_score: float = 1.0  # 0-1 based on gap detection
    anomaly_score: float = 1.0  # 0-1 (inverted) based on spike detection
    overall_score: float = 1.0  # weighted average
    
    def __post_init__(self) -> None:
        """Calculate overall score as weighted average."""
        # Weights: freshness 40%, continuity 30%, anomaly 30%
        self.overall_score = (
            self.freshness_score * 0.4 +
            self.continuity_score * 0.3 +
            self.anomaly_score * 0.3
        )
    
    @property
    def is_acceptable(self) -> bool:
        """Check if quality score meets minimum threshold."""
        return self.overall_score >= 0.7  # 70% minimum quality


@dataclass
class ValidationResult:
    """Result of bar validation.
    
    Contains pass/fail status, violations, and quality score.
    """
    
    valid: bool
    violations: list[dict[str, Any]] = field(default_factory=list)
    score: DataQualityScore = field(default_factory=DataQualityScore)
    validated_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "valid": self.valid,
            "violations": self.violations,
            "score": {
                "freshness": self.score.freshness_score,
                "continuity": self.score.continuity_score,
                "anomaly": self.score.anomaly_score,
                "overall": self.score.overall_score,
            },
            "validated_at": self.validated_at.isoformat(),
        }


class DataQualityMonitor:
    """Real-time data quality monitoring and validation.
    
    This monitor addresses the gap identified in swarm exploration:
    - Batch-only cleaning in cleaner.py (no runtime validation)
    - Silent acceptance of stale/corrupt data feeds
    - No freshness checks or anomaly detection
    
    Thread Safety:
    - All operations are async
    - Uses Redis for shared state across processes
    """
    
    # Configuration constants
    MAX_STALENESS_SECONDS = 60.0  # 1 minute max staleness
    PRICE_SPIKE_THRESHOLD = 0.05  # 5% price change threshold
    VOLUME_MULTIPLIER = 10.0  # 10x average volume threshold
    MIN_QUALITY_SCORE = 0.7  # 70% minimum quality
    
    def __init__(
        self,
        redis_cache: Any,  # RedisCache from quantflow.data
        enable_prometheus: bool = True,
    ) -> None:
        """Initialize data quality monitor.
        
        Args:
            redis_cache: Redis cache for storing last bar timestamps
            enable_prometheus: Whether to export Prometheus metrics
        """
        self._redis = redis_cache
        self._enable_prometheus = enable_prometheus
        
        # Initialize Prometheus metrics if enabled
        if self._enable_prometheus:
            self._init_prometheus_metrics()
    
    def _init_prometheus_metrics(self) -> None:
        """Initialize Prometheus metrics for data quality monitoring."""
        try:
            from prometheus_client import Counter, Gauge, Histogram
            
            self.dq_counter = Counter(
                "dq_monitor_violations_total",
                "Count of data quality violations by type",
                ["violation_type", "symbol"]
            )
            
            self.staleness_gauge = Gauge(
                "dq_data_staleness_seconds",
                "Seconds since last valid bar update",
                ["symbol"]
            )
            
            self.quality_histogram = Histogram(
                "dq_quality_score",
                "Data quality score distribution",
                ["symbol"],
                buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
            )
            
            logger.info("Prometheus metrics initialized for DataQualityMonitor")
            
        except ImportError:
            logger.warning("prometheus_client not available, metrics disabled")
            self._enable_prometheus = False
    
    async def validate_bar(self, bar: Any) -> ValidationResult:
        """Validate incoming bar before publishing.
        
        This is the main entry point for real-time data quality checks.
        
        Args:
            bar: Bar object with symbol, timestamp, open, high, low, close, volume
            
        Returns:
            ValidationResult with pass/fail status and violations
        """
        violations = []
        
        # 1. Freshness check
        freshness_score = await self._check_freshness(bar)
        if freshness_score < 0.5:  # Very stale
            violations.append({
                "type": "staleness_exceeded",
                "symbol": bar.symbol,
                "severity": "HIGH",
                "details": {
                    "freshness_score": freshness_score,
                    "threshold": 0.5,
                }
            })
            
            if self._enable_prometheus:
                self.dq_counter.labels(
                    violation_type="staleness",
                    symbol=bar.symbol
                ).inc()
        
        # 2. Price continuity check
        continuity_score = await self._check_price_continuity(bar)
        if continuity_score < 0.5:  # Large spike
            violations.append({
                "type": "price_spike_anomaly",
                "symbol": bar.symbol,
                "severity": "MEDIUM",
                "details": {
                    "continuity_score": continuity_score,
                    "threshold": 0.5,
                }
            })
            
            if self._enable_prometheus:
                self.dq_counter.labels(
                    violation_type="price_spike",
                    symbol=bar.symbol
                ).inc()
        
        # 3. Volume sanity check
        anomaly_score = await self._check_volume_anomaly(bar)
        if anomaly_score < 0.5:  # Volume anomaly
            violations.append({
                "type": "volume_anomaly",
                "symbol": bar.symbol,
                "severity": "LOW",
                "details": {
                    "anomaly_score": anomaly_score,
                    "threshold": 0.5,
                }
            })
            
            if self._enable_prometheus:
                self.dq_counter.labels(
                    violation_type="volume_anomaly",
                    symbol=bar.symbol
                ).inc()
        
        # Calculate overall quality score
        score = DataQualityScore(
            freshness_score=freshness_score,
            continuity_score=continuity_score,
            anomaly_score=anomaly_score,
        )
        
        # Update Prometheus metrics
        if self._enable_prometheus:
            self.quality_histogram.labels(symbol=bar.symbol).observe(score.overall_score)
        
        # Determine validity
        valid = len(violations) == 0 and score.is_acceptable
        
        result = ValidationResult(
            valid=valid,
            violations=violations,
            score=score,
        )
        
        if not valid:
            logger.warning(
                "Bar validation failed for %s: %d violations, score=%.2f",
                bar.symbol,
                len(violations),
                score.overall_score
            )
        
        return result
    
    async def _check_freshness(self, bar: Any) -> float:
        """Check data freshness (staleness detection).
        
        Args:
            bar: Bar object
            
        Returns:
            Freshness score (0-1, higher is better)
        """
        try:
            # Get last bar timestamp from Redis
            last_bar_key = f"dq:last_bar:{bar.symbol}"
            last_timestamp = await self._redis.get(last_bar_key)
            
            if last_timestamp is None:
                # First bar for this symbol - assume fresh
                await self._redis.set(last_bar_key, bar.timestamp)
                return 1.0
            
            # Calculate staleness
            last_ts = float(last_timestamp)
            current_ts = bar.timestamp if hasattr(bar, 'timestamp') else time.time()
            staleness = current_ts - last_ts
            
            # Update Prometheus gauge
            if self._enable_prometheus:
                self.staleness_gauge.labels(symbol=bar.symbol).set(staleness)
            
            # Calculate freshness score (exponential decay)
            if staleness <= 0:
                freshness = 1.0
            elif staleness <= self.MAX_STALENESS_SECONDS:
                freshness = 1.0 - (staleness / self.MAX_STALENESS_SECONDS)
            else:
                freshness = 0.0
            
            # Update last bar timestamp
            await self._redis.set(last_bar_key, current_ts)
            
            return freshness
            
        except Exception as e:
            logger.error("Freshness check failed: %s", e)
            return 0.5  # Neutral score on error
    
    async def _check_price_continuity(self, bar: Any) -> float:
        """Check price continuity (spike detection).
        
        Args:
            bar: Bar object
            
        Returns:
            Continuity score (0-1, higher is better)
        """
        try:
            # Get last close price from Redis
            last_close_key = f"dq:last_close:{bar.symbol}"
            last_close = await self._redis.get(last_close_key)
            
            if last_close is None:
                # First bar - assume continuous
                await self._redis.set(last_close_key, bar.close)
                return 1.0
            
            last_close = float(last_close)
            
            # Calculate price change percentage
            if last_close == 0:
                return 0.0  # Invalid last close
            
            price_change_pct = abs(bar.close - last_close) / last_close
            
            # Update last close
            await self._redis.set(last_close_key, bar.close)
            
            # Calculate continuity score
            if price_change_pct <= self.PRICE_SPIKE_THRESHOLD:
                continuity = 1.0
            elif price_change_pct <= self.PRICE_SPIKE_THRESHOLD * 2:
                continuity = 1.0 - (
                    (price_change_pct - self.PRICE_SPIKE_THRESHOLD) /
                    self.PRICE_SPIKE_THRESHOLD
                )
            else:
                continuity = 0.0
            
            return continuity
            
        except Exception as e:
            logger.error("Price continuity check failed: %s", e)
            return 0.5
    
    async def _check_volume_anomaly(self, bar: Any) -> float:
        """Check volume anomaly (unusual volume detection).
        
        Args:
            bar: Bar object
            
        Returns:
            Anomaly score (0-1, higher is better / less anomalous)
        """
        try:
            # Get average volume from Redis (20-day window)
            avg_volume_key = f"dq:avg_volume:{bar.symbol}"
            avg_volume = await self._redis.get(avg_volume_key)
            
            if avg_volume is None:
                # Initialize with current volume
                await self._redis.set(avg_volume_key, bar.volume)
                return 1.0
            
            avg_volume = float(avg_volume)
            
            if avg_volume == 0:
                return 1.0 if bar.volume == 0 else 0.0
            
            # Calculate volume ratio
            volume_ratio = bar.volume / avg_volume
            
            # Update average volume (exponential moving average)
            alpha = 0.05  # 5% weight for new observation
            new_avg = avg_volume * (1 - alpha) + bar.volume * alpha
            await self._redis.set(avg_volume_key, new_avg)
            
            # Calculate anomaly score
            if volume_ratio <= self.VOLUME_MULTIPLIER:
                anomaly_score = 1.0
            elif volume_ratio <= self.VOLUME_MULTIPLIER * 2:
                anomaly_score = 1.0 - (
                    (volume_ratio - self.VOLUME_MULTIPLIER) /
                    self.VOLUME_MULTIPLIER
                )
            else:
                anomaly_score = 0.0
            
            return anomaly_score
            
        except Exception as e:
            logger.error("Volume anomaly check failed: %s", e)
            return 0.5
    
    async def get_quality_report(self, symbol: str) -> dict[str, Any]:
        """Get current data quality report for a symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Dictionary with quality metrics
        """
        try:
            # Get metrics from Redis
            last_bar = await self._redis.get(f"dq:last_bar:{symbol}")
            last_close = await self._redis.get(f"dq:last_close:{symbol}")
            avg_volume = await self._redis.get(f"dq:avg_volume:{symbol}")
            
            return {
                "symbol": symbol,
                "last_bar_timestamp": last_bar,
                "last_close_price": last_close,
                "average_volume": avg_volume,
                "report_generated_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error("Failed to get quality report: %s", e)
            return {"error": str(e)}
