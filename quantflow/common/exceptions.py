"""Custom exceptions for QuantFlow."""


class QuantFlowError(Exception):
    """Base exception for QuantFlow."""


class DataError(QuantFlowError):
    """Data layer errors."""


class DataNotFoundError(DataError):
    """Requested data not found."""


class DataValidationError(DataError):
    """Data validation failed."""


class StrategyError(QuantFlowError):
    """Strategy layer errors."""


class StrategyConfigError(StrategyError):
    """Strategy configuration error."""


class SignalError(QuantFlowError):
    """Signal/risk layer errors."""


class RiskBreachError(SignalError):
    """Risk limit breached."""

    def __init__(self, reason: str, severity: str = "warn") -> None:
        self.reason = reason
        self.severity = severity
        super().__init__(f"Risk breach: {reason} (severity={severity})")


class KillSwitchActivatedError(SignalError):
    """Kill switch has been activated."""


class ExecutionError(QuantFlowError):
    """Execution layer errors."""


class OrderError(ExecutionError):
    """Order submission/management error."""


class OrderTimeoutError(OrderError):
    """Order timed out."""


class GatewayConnectionError(ExecutionError):
    """Gateway connection error."""


class ConfigError(QuantFlowError):
    """Configuration error."""
