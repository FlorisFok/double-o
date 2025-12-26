"""Custom exceptions for the Double-O library."""


class DoubleOError(Exception):
    """Base exception for Double-O library."""
    pass


class SecretError(DoubleOError):
    """Exception raised when fetching a secret fails."""
    pass


class ProxyError(DoubleOError):
    """Exception raised when a proxy request fails."""
    pass


class AuthenticationError(DoubleOError):
    """Exception raised when authentication fails."""
    pass


class EnvError(DoubleOError):
    """Exception raised when fetching environment variables fails."""
    pass
