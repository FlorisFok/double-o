"""Async Double-O client module for non-blocking secret fetching and proxy API calls."""

import asyncio
import json
import os
import random
import time
from typing import Any, Callable, Coroutine, Dict, Optional, TypeVar

from .exceptions import AuthenticationError, EnvError, ProxyError, SecretError

try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore


BASE_URL = "https://double-o-539191849800.europe-west1.run.app"

T = TypeVar("T")


class AsyncSecretCache:
    """
    Async-safe cache for secrets with TTL (time-to-live) support.
    
    This cache stores secrets locally to reduce API calls. Each cached entry
    expires after the specified TTL. Uses asyncio.Lock for thread safety.
    """
    
    def __init__(self) -> None:
        self._cache: Dict[str, tuple[str, float]] = {}  # (value, expiry_time)
        self._lock: Optional[asyncio.Lock] = None
    
    def _get_lock(self) -> asyncio.Lock:
        """Lazily create lock in the current event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock
    
    async def get(self, key: str) -> Optional[str]:
        """
        Get a cached secret if it exists and hasn't expired.
        
        Args:
            key: The cache key (typically the token).
            
        Returns:
            The cached secret value, or None if not found or expired.
        """
        async with self._get_lock():
            if key in self._cache:
                value, expiry_time = self._cache[key]
                if time.time() < expiry_time:
                    return value
                # Expired, remove from cache
                del self._cache[key]
            return None
    
    async def set(self, key: str, value: str, ttl: float) -> None:
        """
        Cache a secret with a TTL.
        
        Args:
            key: The cache key (typically the token).
            value: The secret value to cache.
            ttl: Time-to-live in seconds.
        """
        async with self._get_lock():
            expiry_time = time.time() + ttl
            self._cache[key] = (value, expiry_time)
    
    async def invalidate(self, key: str) -> None:
        """
        Remove a specific key from the cache.
        
        Args:
            key: The cache key to remove.
        """
        async with self._get_lock():
            self._cache.pop(key, None)
    
    async def clear(self) -> None:
        """Clear all cached secrets."""
        async with self._get_lock():
            self._cache.clear()


# Global async cache instance
_async_secret_cache = AsyncSecretCache()


async def _async_retry_with_backoff(
    func: Callable[[], Coroutine[Any, Any, T]],
    retries: int = 3,
    backoff_factor: float = 0.5,
    retryable_exceptions: tuple = (),
) -> T:
    """
    Execute an async function with retry logic and exponential backoff.
    
    Args:
        func: The async function to execute.
        retries: Maximum number of retry attempts (default: 3).
        backoff_factor: Multiplier for exponential backoff (default: 0.5).
        retryable_exceptions: Tuple of exception types to retry on.
        
    Returns:
        The result of the function.
        
    Raises:
        The last exception if all retries fail.
    """
    last_exception = None
    
    for attempt in range(retries + 1):
        try:
            return await func()
        except retryable_exceptions as e:
            last_exception = e
            if attempt < retries:
                # Exponential backoff with jitter
                sleep_time = backoff_factor * (2 ** attempt) + random.uniform(0, 0.1)
                await asyncio.sleep(sleep_time)
    
    raise last_exception  # type: ignore


class AsyncClient:
    """
    Async Double-O Client for non-blocking secret management and proxy services.
    
    This client uses aiohttp for async HTTP requests, making it ideal for
    FastAPI, asyncio-based applications, and high-concurrency scenarios.
    
    Args:
        base_url: Base URL for the API server (default: BASE_URL)
        timeout: Request timeout in seconds (default: 30)
        retries: Number of retry attempts for transient failures (default: 0, no retries)
        backoff_factor: Multiplier for exponential backoff between retries (default: 0.5)
    
    Example:
        >>> import asyncio
        >>> from oo import AsyncClient
        >>> 
        >>> async def main():
        ...     async with AsyncClient() as client:
        ...         secret = await client.get_secret("TOKEN")
        ...         print(secret)
        >>> 
        >>> asyncio.run(main())
        
        >>> # With retry logic
        >>> async with AsyncClient(retries=3, backoff_factor=0.5) as client:
        ...     secret = await client.get_secret("TOKEN")
        
        >>> # With caching
        >>> secret = await client.get_secret("TOKEN", cache_ttl=300)  # Cache for 5 minutes
    
    Note:
        Requires the 'async' extra: pip install double-o[async]
    """
    
    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: int = 30,
        retries: int = 0,
        backoff_factor: float = 0.5,
    ):
        if aiohttp is None:
            raise ImportError(
                "aiohttp is required for AsyncClient. "
                "Install it with: pip install double-o[async]"
            )
        
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.retries = retries
        self.backoff_factor = backoff_factor
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache = _async_secret_cache
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session
    
    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> aiohttp.ClientResponse:
        """Make a request with optional retry logic."""
        session = await self._get_session()
        
        async def do_request() -> aiohttp.ClientResponse:
            response = await session.request(method, url, **kwargs)
            return response
        
        if self.retries > 0:
            return await _async_retry_with_backoff(
                do_request,
                retries=self.retries,
                backoff_factor=self.backoff_factor,
                retryable_exceptions=(aiohttp.ClientError, asyncio.TimeoutError),
            )
        return await do_request()
    
    async def get_secret(self, token: str, cache_ttl: Optional[float] = None) -> str:
        """
        Fetch a secret value using a token.
        
        Args:
            token: The authentication token for fetching the secret.
            cache_ttl: Optional TTL in seconds to cache the secret locally.
                       If provided, the secret will be cached and subsequent
                       calls within the TTL will return the cached value.
            
        Returns:
            The secret value as a string.
            
        Raises:
            SecretError: If the secret cannot be retrieved.
            AuthenticationError: If the token is invalid.
            
        Example:
            >>> async with AsyncClient() as client:
            ...     # No caching
            ...     secret = await client.get_secret("TOKEN")
            ...     
            ...     # Cache for 5 minutes (300 seconds)
            ...     secret = await client.get_secret("TOKEN", cache_ttl=300)
        """
        # Check cache first
        if cache_ttl is not None:
            cached_value = await self._cache.get(token)
            if cached_value is not None:
                return cached_value
        
        url = f"{self.base_url}/api/secret"
        
        try:
            response = await self._request_with_retry(
                "GET",
                url,
                params={"token": token},
            )
            
            if response.status == 401:
                raise AuthenticationError("Invalid token")
            
            response.raise_for_status()
            data = await response.json()
            
            if "value" in data:
                value = data["value"]
                # Cache the value if TTL is specified
                if cache_ttl is not None:
                    await self._cache.set(token, value, cache_ttl)
                return value
            elif "error" in data:
                error_msg = data["error"]
                if "auth" in error_msg.lower() or "token" in error_msg.lower():
                    raise AuthenticationError(error_msg)
                raise SecretError(error_msg)
            else:
                raise SecretError("Unknown error: no value returned")
                
        except aiohttp.ClientResponseError as e:
            if e.status == 401:
                raise AuthenticationError("Invalid token") from e
            raise SecretError(f"HTTP error: {e}") from e
        except aiohttp.ClientError as e:
            raise SecretError(f"Request failed: {e}") from e
    
    async def invalidate_cache(self, token: Optional[str] = None) -> None:
        """
        Invalidate cached secrets.
        
        Args:
            token: If provided, only invalidate the cache for this token.
                   If None, clear the entire cache.
        """
        if token is not None:
            await self._cache.invalidate(token)
        else:
            await self._cache.clear()
    
    async def proxy(
        self,
        path: str,
        token: str,
        method: str = "POST",
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Make an API call through the proxy.
        
        Args:
            path: The API path to call (e.g., 'v1/chat/completions').
            token: The proxy authentication token.
            method: HTTP method (default: POST).
            payload: Request payload as a dictionary (optional).
            headers: Additional headers to include (optional).
            
        Returns:
            The JSON response as a dictionary.
            
        Raises:
            ProxyError: If the proxy request fails.
            AuthenticationError: If the token is invalid.
        """
        url = f"{self.base_url}/api/proxy/{path.lstrip('/')}"
        
        request_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        if headers:
            request_headers.update(headers)
        
        try:
            response = await self._request_with_retry(
                method.upper(),
                url,
                headers=request_headers,
                data=json.dumps(payload) if payload else None,
            )
            
            if response.status == 401:
                raise AuthenticationError("Invalid proxy token")
            
            response.raise_for_status()
            return await response.json()
            
        except aiohttp.ClientResponseError as e:
            if e.status == 401:
                raise AuthenticationError("Invalid proxy token") from e
            raise ProxyError(f"Proxy request failed: {e}") from e
        except aiohttp.ClientError as e:
            raise ProxyError(f"Request failed: {e}") from e
    
    async def chat_completion(
        self,
        token: str,
        messages: list,
        model: str = "gpt-4o-mini",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Convenience method for OpenAI chat completions through the proxy.
        
        Args:
            token: The proxy authentication token.
            messages: List of message dictionaries with 'role' and 'content'.
            model: The model to use (default: gpt-4o-mini).
            **kwargs: Additional parameters to pass to the API.
            
        Returns:
            The chat completion response.
        """
        payload = {
            "model": model,
            "messages": messages,
            **kwargs
        }
        return await self.proxy("v1/chat/completions", token, payload=payload)
    
    async def get_env(
        self,
        token: str,
        cache_ttl: Optional[float] = None
    ) -> Dict[str, str]:
        """
        Fetch environment variables/secrets using a virtual env token.
        
        Args:
            token: The virtual environment token.
            cache_ttl: Optional TTL in seconds to cache the environment.
            
        Returns:
            A dictionary of environment variable names to their values.
            
        Raises:
            EnvError: If the environment variables cannot be retrieved.
            AuthenticationError: If the token is invalid.
        """
        # For env, we use a different cache key prefix
        cache_key = f"env:{token}"
        
        if cache_ttl is not None:
            cached_value = await self._cache.get(cache_key)
            if cached_value is not None:
                return json.loads(cached_value)
        
        url = f"{self.base_url}/api/env"
        
        try:
            response = await self._request_with_retry(
                "GET",
                url,
                params={"token": token},
            )
            
            if response.status == 401:
                raise AuthenticationError("Invalid token")
            
            response.raise_for_status()
            data = await response.json()
            
            if "secrets" in data:
                secrets = data["secrets"]
                if cache_ttl is not None:
                    await self._cache.set(cache_key, json.dumps(secrets), cache_ttl)
                return secrets
            elif "error" in data:
                error_msg = data["error"]
                if "auth" in error_msg.lower() or "token" in error_msg.lower():
                    raise AuthenticationError(error_msg)
                raise EnvError(error_msg)
            else:
                raise EnvError("Unknown error: no secrets returned")
                
        except aiohttp.ClientResponseError as e:
            if e.status == 401:
                raise AuthenticationError("Invalid token") from e
            raise EnvError(f"HTTP error: {e}") from e
        except aiohttp.ClientError as e:
            raise EnvError(f"Request failed: {e}") from e
    
    async def load_env(
        self,
        token: str,
        cache_ttl: Optional[float] = None
    ) -> Dict[str, str]:
        """
        Fetch environment variables and set them in os.environ.
        
        Args:
            token: The virtual environment token.
            cache_ttl: Optional TTL in seconds to cache the environment.
            
        Returns:
            A dictionary of environment variable names to their values.
            
        Raises:
            EnvError: If the environment variables cannot be retrieved.
            AuthenticationError: If the token is invalid.
        """
        secrets = await self.get_env(token, cache_ttl=cache_ttl)
        for key, value in secrets.items():
            os.environ[key] = value
        return secrets
    
    async def close(self) -> None:
        """Close the underlying aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

