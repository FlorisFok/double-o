"""
Double-O: A Python library for secret management and API proxy calls.

Simple usage:
    >>> import oo
    >>> secret = oo.get_secret("YOUR_TOKEN")
    >>> result = oo.proxy("v1/chat/completions", token="TOKEN", payload={...})

Advanced usage with Client:
    >>> from oo import Client
    >>> with Client(base_url="http://localhost:3001") as client:
    ...     secret = client.get_secret("TOKEN")
    ...     result = client.proxy("v1/chat/completions", "TOKEN", payload={...})
"""

from .client import (
    Client,
    get_secret,
    proxy,
    chat,
)
from .exceptions import (
    DoubleOError,
    SecretError,
    ProxyError,
    AuthenticationError,
)

__version__ = "0.1.0"
__author__ = "Double-O Contributors"
__all__ = [
    # Main client
    "Client",
    # Convenience functions
    "get_secret",
    "proxy",
    "chat",
    # Exceptions
    "DoubleOError",
    "SecretError",
    "ProxyError",
    "AuthenticationError",
    # Metadata
    "__version__",
]
