"""Custom exceptions for Mira."""


class MiraError(Exception):
    """Base exception for all Mira errors."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.message = message
        self.code = code


class NetworkError(MiraError):
    """Network-related failures (DNS, timeout, connection)."""

    def __init__(self, message: str = "Network error"):
        super().__init__(message, code=2)


class ValidationError(MiraError):
    """Invalid data, schema, or configuration."""

    def __init__(self, message: str = "Validation error"):
        super().__init__(message, code=3)


class PermissionError(MiraError):
    """Insufficient privileges for the requested operation."""

    def __init__(self, message: str = "Permission denied"):
        super().__init__(message, code=4)


class ConfigError(MiraError):
    """Configuration read/write or format problems."""

    def __init__(self, message: str = "Configuration error"):
        super().__init__(message, code=5)


class ProviderError(MiraError):
    """Provider-specific failures."""

    def __init__(self, message: str = "Provider error"):
        super().__init__(message, code=6)


class NoHealthyMirrorError(MiraError):
    """No healthy mirror found for the provider."""

    def __init__(self, provider: str = ""):
        msg = f"No healthy mirror found for {provider}" if provider else "No healthy mirror found"
        super().__init__(msg, code=7)


class UpdateError(MiraError):
    """Mirror database or application update failure."""

    def __init__(self, message: str = "Update failed"):
        super().__init__(message, code=8)


class IntegrityError(MiraError):
    """Checksum or integrity verification failed."""

    def __init__(self, message: str = "Integrity check failed"):
        super().__init__(message, code=9)