"""Distributed tracing foundation — correlation ID propagation across async boundaries.

G3 Implementation: Establishes the observability foundation layer that enables:
- Correlation ID propagation across async task boundaries
- OpenTelemetry integration for distributed tracing
- Structlog processor injection for enhanced logging
- Span recording at key execution points

Architecture:
    Signal Generation (trace_id)
        ↓
    Feature Engineering (context propagation)
        ↓
    Strategy Decision (structured log entry)
        ↓
    Order Submission (span recording)
        ↓
    Gateway Execution (metrics emission)
        ↓
    Event Bus Publish (audit log write)

Usage:
    from quantflow.common.tracing import get_correlation_id, traced
    
    @traced("order.submission")
    async def submit_order(order: Order):
        # Correlation ID automatically propagated
        logger.info("Submitting order", extra={"correlation_id": get_correlation_id()})
        ...
"""

from __future__ import annotations

import contextvars
import functools
import logging
import uuid
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

# Context variable for correlation ID propagation
CORRELATION_ID_VAR: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id",
    default=None
)

# Context variable for trace ID (OpenTelemetry integration)
TRACE_ID_VAR: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id",
    default=None
)

# Context variable for span ID
SPAN_ID_VAR: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "span_id",
    default=None
)


def get_correlation_id() -> str | None:
    """Get current correlation ID from context.
    
    Returns:
        Correlation ID if set, None otherwise
    """
    return CORRELATION_ID_VAR.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set correlation ID in current context.
    
    Args:
        correlation_id: Correlation ID to set
    """
    CORRELATION_ID_VAR.set(correlation_id)


def get_or_create_correlation_id() -> str:
    """Get existing correlation ID or create new one.
    
    Returns:
        Existing or newly created correlation ID
    """
    corr_id = CORRELATION_ID_VAR.get()
    if corr_id is None:
        corr_id = uuid.uuid4().hex[:12]
        CORRELATION_ID_VAR.set(corr_id)
    return corr_id


def clear_correlation_id() -> None:
    """Clear correlation ID from current context."""
    CORRELATION_ID_VAR.set(None)


# Type variable for decorated functions
F = TypeVar("F", bound=Callable[..., Any])


def traced(operation_name: str) -> Callable[[F], F]:
    """Decorator to add tracing to async functions.
    
    Creates a span for the operation and propagates correlation ID.
    
    Args:
        operation_name: Name of the operation (e.g., "order.submission")
        
    Returns:
        Decorated function with tracing
        
    Usage:
        @traced("signal.generation")
        async def generate_signal(ctx: Context, bar: Bar):
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Ensure correlation ID exists
            corr_id = get_or_create_correlation_id()
            
            # Generate span ID for this operation
            span_id = uuid.uuid4().hex[:16]
            SPAN_ID_VAR.set(span_id)
            
            # Log span start
            logger.debug(
                "SPAN START: %s",
                operation_name,
                extra={
                    "correlation_id": corr_id,
                    "span_id": span_id,
                    "operation": operation_name,
                }
            )
            
            try:
                # Execute wrapped function
                result = await func(*args, **kwargs)
                
                # Log span completion
                logger.debug(
                    "SPAN END: %s (success)",
                    operation_name,
                    extra={
                        "correlation_id": corr_id,
                        "span_id": span_id,
                        "operation": operation_name,
                    }
                )
                
                return result
                
            except Exception as e:
                # Log span failure
                logger.error(
                    "SPAN END: %s (error: %s)",
                    operation_name,
                    str(e),
                    extra={
                        "correlation_id": corr_id,
                        "span_id": span_id,
                        "operation": operation_name,
                        "error": str(e),
                    }
                )
                raise
        
        return wrapper  # type: ignore[return-value]
    
    return decorator


class CorrelationIdProcessor:
    """Structlog processor to inject correlation ID into log entries.
    
    Integrates with structlog's processor chain to automatically add
    correlation_id, trace_id, and span_id to all log entries.
    
    Usage:
        import structlog
        
        structlog.configure(
            processors=[
                CorrelationIdProcessor(),
                structlog.processors.JSONRenderer(),
            ]
        )
    """
    
    def __call__(
        self,
        logger: Any,
        method_name: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        """Process log event and inject correlation context.
        
        Args:
            logger: Logger instance
            method_name: Log method name (info, warning, etc.)
            event_dict: Event dictionary to process
            
        Returns:
            Modified event dictionary with correlation context
        """
        # Inject correlation ID
        corr_id = get_correlation_id()
        if corr_id:
            event_dict["correlation_id"] = corr_id
        
        # Inject trace ID (if OpenTelemetry is active)
        trace_id = TRACE_ID_VAR.get()
        if trace_id:
            event_dict["trace_id"] = trace_id
        
        # Inject span ID
        span_id = SPAN_ID_VAR.get()
        if span_id:
            event_dict["span_id"] = span_id
        
        return event_dict


class TracingContext:
    """Context manager for explicit tracing scope.
    
    Useful when you need to create a new correlation context or
    propagate tracing across manual async boundaries.
    
    Usage:
        async with TracingContext("batch_processing") as ctx:
            # All operations within this block share correlation ID
            await process_item(item1)
            await process_item(item2)
    """
    
    def __init__(self, operation_name: str, correlation_id: str | None = None):
        """Initialize tracing context.
        
        Args:
            operation_name: Name of the operation
            correlation_id: Optional existing correlation ID (creates new if None)
        """
        self.operation_name = operation_name
        self.correlation_id = correlation_id or uuid.uuid4().hex[:12]
        self._token: contextvars.Token | None = None
    
    async def __aenter__(self) -> TracingContext:
        """Enter tracing context."""
        # Set correlation ID
        self._token = CORRELATION_ID_VAR.set(self.correlation_id)
        
        logger.debug(
            "TRACE CONTEXT ENTER: %s",
            self.operation_name,
            extra={"correlation_id": self.correlation_id}
        )
        
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit tracing context."""
        # Restore previous correlation ID
        if self._token:
            CORRELATION_ID_VAR.reset(self._token)
        
        if exc_type:
            logger.error(
                "TRACE CONTEXT EXIT: %s (error: %s)",
                self.operation_name,
                str(exc_val),
                extra={"correlation_id": self.correlation_id}
            )
        else:
            logger.debug(
                "TRACE CONTEXT EXIT: %s (success)",
                self.operation_name,
                extra={"correlation_id": self.correlation_id}
            )


# OpenTelemetry integration (optional - only if opentelemetry is installed)
try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
    
    OTEL_AVAILABLE = True
    
    def init_otel_tracer(service_name: str = "quantflow") -> None:
        """Initialize OpenTelemetry tracer provider.
        
        Args:
            service_name: Service name for tracing backend
        """
        try:
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.jaeger.thrift import JaegerExporter
            
            # Create tracer provider
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
            
            # Configure Jaeger exporter (can be replaced with other backends)
            jaeger_exporter = JaegerExporter(
                agent_host_name="localhost",
                agent_port=6831,
            )
            
            # Add span processor
            provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
            
            logger.info("OpenTelemetry tracer initialized for service: %s", service_name)
            
        except ImportError as e:
            logger.warning("OpenTelemetry dependencies not available: %s", e)
        except Exception as e:
            logger.error("Failed to initialize OpenTelemetry: %s", e)
    
    def create_otel_span(operation_name: str) -> Any:
        """Create OpenTelemetry span for an operation.
        
        Args:
            operation_name: Name of the operation
            
        Returns:
            OpenTelemetry span context manager
        """
        tracer = trace.get_tracer(__name__)
        return tracer.start_as_current_span(operation_name)
    
except ImportError:
    OTEL_AVAILABLE = False
    
    def init_otel_tracer(service_name: str = "quantflow") -> None:
        """Stub function when OpenTelemetry is not available."""
        logger.debug("OpenTelemetry not installed, tracing disabled")
    
    def create_otel_span(operation_name: str) -> Any:
        """Stub function when OpenTelemetry is not available."""
        return None


# Export public API
__all__ = [
    "get_correlation_id",
    "set_correlation_id",
    "get_or_create_correlation_id",
    "clear_correlation_id",
    "traced",
    "CorrelationIdProcessor",
    "TracingContext",
    "init_otel_tracer",
    "create_otel_span",
    "OTEL_AVAILABLE",
]
