"""
Double-O: A Python library for secret management and API proxy calls.

Simple usage:
    >>> import oo
    >>> secret = oo.get_secret("YOUR_TOKEN")
    >>> result = oo.proxy("v1/chat/completions", token="TOKEN", payload={...})

With caching:
    >>> secret = oo.get_secret("YOUR_TOKEN", cache_ttl=300)  # Cache for 5 minutes

Environment variables:
    >>> import oo
    >>> env = oo.get_env("YOUR_VIRTUAL_ENV_TOKEN")  # Returns dict of secrets
    >>> oo.load_env("YOUR_VIRTUAL_ENV_TOKEN")  # Sets os.environ automatically

Advanced usage with Client:
    >>> from oo import Client
    >>> with Client(base_url="http://localhost:3001", retries=3) as client:
    ...     secret = client.get_secret("TOKEN", cache_ttl=300)
    ...     result = client.proxy("v1/chat/completions", "TOKEN", payload={...})

Async usage (requires 'async' extra: pip install double-o[async]):
    >>> import asyncio
    >>> from oo import AsyncClient
    >>> 
    >>> async def main():
    ...     async with AsyncClient(retries=3) as client:
    ...         secret = await client.get_secret("TOKEN", cache_ttl=300)
    ...         result = await client.proxy("v1/chat/completions", "TOKEN", payload={...})
    >>> 
    >>> asyncio.run(main())
"""

from .client import (
    Client,
    SecretCache,
    get_secret,
    proxy,
    chat,
    get_env,
    load_env,
    invalidate_cache,
)
from .exceptions import (
    DoubleOError,
    SecretError,
    ProxyError,
    AuthenticationError,
    EnvError,
)

# Lazy import for AsyncClient to avoid requiring aiohttp for sync-only users
def __getattr__(name: str):
    if name == "AsyncClient":
        from .async_client import AsyncClient
        return AsyncClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__version__ = "0.2.0"
__author__ = "Double-O Contributors"
__all__ = [
    # Main clients
    "Client",
    "AsyncClient",
    # Caching
    "SecretCache",
    "invalidate_cache",
    # Convenience functions
    "get_secret",
    "proxy",
    "chat",
    "get_env",
    "load_env",
    # Exceptions
    "DoubleOError",
    "SecretError",
    "ProxyError",
    "AuthenticationError",
    "EnvError",
    # Metadata
    "__version__",
]
