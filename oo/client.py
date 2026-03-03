"""Double-O client module for secret fetching and proxy API calls."""

import json
import os
import random
import time
from threading import Lock
from typing import Any, Callable, Dict, Optional, TypeVar, Union

import requests

from .exceptions import AuthenticationError, EnvError, ProxyError, SecretError


BASE_URL = "https://double-o-539191849800.europe-west1.run.app"

T = TypeVar("T")


class SecretCache:
    """
    Thread-safe cache for secrets with TTL (time-to-live) support.
    
    This cache stores secrets locally to reduce API calls. Each cached entry
    expires after the specified TTL.
    """
    
    def __init__(self) -> None:
        self._cache: Dict[str, tuple[str, float]] = {}  # (value, expiry_time)
        self._lock = Lock()
    
    def get(self, key: str) -> Optional[str]:
        """
        Get a cached secret if it exists and hasn't expired.
        
        Args:
            key: The cache key (typically the token).
            
        Returns:
            The cached secret value, or None if not found or expired.
        """
        with self._lock:
            if key in self._cache:
                value, expiry_time = self._cache[key]
                if time.time() < expiry_time:
                    return value
                # Expired, remove from cache
                del self._cache[key]
            return None
    
    def set(self, key: str, value: str, ttl: float) -> None:
        """
        Cache a secret with a TTL.
        
        Args:
            key: The cache key (typically the token).
            value: The secret value to cache.
            ttl: Time-to-live in seconds.
        """
        with self._lock:
            expiry_time = time.time() + ttl
            self._cache[key] = (value, expiry_time)
    
    def invalidate(self, key: str) -> None:
        """
        Remove a specific key from the cache.
        
        Args:
            key: The cache key to remove.
        """
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self) -> None:
        """Clear all cached secrets."""
        with self._lock:
            self._cache.clear()


# Global cache instance
_secret_cache = SecretCache()


def _retry_with_backoff(
    func: Callable[[], T],
    retries: int = 3,
    backoff_factor: float = 0.5,
    retryable_exceptions: tuple = (requests.exceptions.RequestException,),
) -> T:
    """
    Execute a function with retry logic and exponential backoff.
    
    Args:
        func: The function to execute.
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
            return func()
        except retryable_exceptions as e:
            last_exception = e
            if attempt < retries:
                # Exponential backoff with jitter
                sleep_time = backoff_factor * (2 ** attempt) + random.uniform(0, 0.1)
                time.sleep(sleep_time)
    
    raise last_exception  # type: ignore


class Client:
    """
    Double-O Client for interacting with secret management and proxy services.
    
    Args:
        base_url: Base URL for the API server (default: BASE_URL)
        timeout: Request timeout in seconds (default: 30)
        retries: Number of retry attempts for transient failures (default: 0, no retries)
        backoff_factor: Multiplier for exponential backoff between retries (default: 0.5)
    
    Example:
        >>> # Basic usage
        >>> client = Client()
        >>> secret = client.get_secret("TOKEN")
        
        >>> # With retry logic
        >>> client = Client(retries=3, backoff_factor=0.5)
        >>> secret = client.get_secret("TOKEN")  # Will retry up to 3 times
        
        >>> # With caching
        >>> secret = client.get_secret("TOKEN", cache_ttl=300)  # Cache for 5 minutes
    """
    
    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: int = 30,
        retries: int = 0,
        backoff_factor: float = 0.5,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff_factor = backoff_factor
        self._session = requests.Session()
        self._cache = _secret_cache
    
    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> requests.Response:
        """Make a request with optional retry logic."""
        def do_request() -> requests.Response:
            return self._session.request(method, url, **kwargs)
        
        if self.retries > 0:
            return _retry_with_backoff(
                do_request,
                retries=self.retries,
                backoff_factor=self.backoff_factor,
            )
        return do_request()
    
    def get_secret(self, token: str, cache_ttl: Optional[float] = None) -> str:
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
            >>> client = Client()
            >>> # No caching
            >>> secret = client.get_secret("TOKEN")
            >>> 
            >>> # Cache for 5 minutes (300 seconds)
            >>> secret = client.get_secret("TOKEN", cache_ttl=300)
        """
        # Check cache first
        if cache_ttl is not None:
            cached_value = self._cache.get(token)
            if cached_value is not None:
                return cached_value
        
        url = f"{self.base_url}/api/secret"
        
        try:
            response = self._request_with_retry(
                "GET",
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            if "value" in data:
                value = data["value"]
                # Cache the value if TTL is specified
                if cache_ttl is not None:
                    self._cache.set(token, value, cache_ttl)
                return value
            elif "error" in data:
                error_msg = data["error"]
                if "auth" in error_msg.lower() or "token" in error_msg.lower():
                    raise AuthenticationError(error_msg)
                raise SecretError(error_msg)
            else:
                raise SecretError("Unknown error: no value returned")
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid token") from e
            raise SecretError(f"HTTP error: {e}") from e
        except requests.exceptions.RequestException as e:
            raise SecretError(f"Request failed: {e}") from e
    
    def invalidate_cache(self, token: Optional[str] = None) -> None:
        """
        Invalidate cached secrets.
        
        Args:
            token: If provided, only invalidate the cache for this token.
                   If None, clear the entire cache.
        """
        if token is not None:
            self._cache.invalidate(token)
        else:
            self._cache.clear()
    
    def proxy(
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
            response = self._request_with_retry(
                method.upper(),
                url,
                headers=request_headers,
                data=json.dumps(payload) if payload else None,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid proxy token") from e
            raise ProxyError(f"Proxy request failed: {e}") from e
        except requests.exceptions.RequestException as e:
            raise ProxyError(f"Request failed: {e}") from e
    
    def chat_completion(
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
        return self.proxy("v1/chat/completions", token, payload=payload)
    
    def get_env(self, token: str, cache_ttl: Optional[float] = None) -> Dict[str, str]:
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
            cached_value = self._cache.get(cache_key)
            if cached_value is not None:
                return json.loads(cached_value)
        
        url = f"{self.base_url}/api/env"
        
        try:
            response = self._request_with_retry(
                "GET",
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            if "secrets" in data:
                secrets = data["secrets"]
                if cache_ttl is not None:
                    self._cache.set(cache_key, json.dumps(secrets), cache_ttl)
                return secrets
            elif "error" in data:
                error_msg = data["error"]
                if "auth" in error_msg.lower() or "token" in error_msg.lower():
                    raise AuthenticationError(error_msg)
                raise EnvError(error_msg)
            else:
                raise EnvError("Unknown error: no secrets returned")
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid token") from e
            raise EnvError(f"HTTP error: {e}") from e
        except requests.exceptions.RequestException as e:
            raise EnvError(f"Request failed: {e}") from e
    
    def load_env(self, token: str, cache_ttl: Optional[float] = None) -> Dict[str, str]:
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
        secrets = self.get_env(token, cache_ttl=cache_ttl)
        for key, value in secrets.items():
            os.environ[key] = value
        return secrets
    
    def export_env(
        self,
        token: str,
        path: str = ".env",
        overwrite: bool = True,
        cache_ttl: Optional[float] = None
    ) -> Dict[str, str]:
        """
        Fetch environment variables and write them to a .env file.
        
        Args:
            token: The virtual environment token.
            path: Path to the .env file (default: ".env").
            overwrite: If True, overwrite existing file. If False, append.
            cache_ttl: Optional TTL in seconds to cache the environment.
            
        Returns:
            A dictionary of environment variable names to their values.
            
        Raises:
            EnvError: If the environment variables cannot be retrieved.
            AuthenticationError: If the token is invalid.
            
        Example:
            >>> client = Client()
            >>> client.export_env("TOKEN", path=".env")
            {"OPENAI_API_KEY": "sk-xxx", "DB_URL": "..."}
        """
        secrets = self.get_env(token, cache_ttl=cache_ttl)
        
        mode = "w" if overwrite else "a"
        with open(path, mode) as f:
            if not overwrite:
                f.write("\n")  # Add newline before appending
            for key, value in secrets.items():
                # Escape special characters in value
                escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
                f.write(f'{key}="{escaped_value}"\n')
        
        return secrets
    
    def embed(
        self,
        token: str,
        texts: list,
        model: str = "text-embedding-3-small",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate embeddings for the given texts through the proxy.
        
        Args:
            token: The proxy authentication token.
            texts: List of text strings to generate embeddings for.
            model: The embedding model to use (default: text-embedding-3-small).
            **kwargs: Additional parameters to pass to the API.
            
        Returns:
            The embeddings response containing vector representations.
            
        Example:
            >>> client = Client()
            >>> result = client.embed("TOKEN", texts=["hello", "world"])
            >>> embeddings = [item["embedding"] for item in result["data"]]
        """
        payload = {
            "model": model,
            "input": texts,
            **kwargs
        }
        return self.proxy("v1/embeddings", token, payload=payload)
    
    def image(
        self,
        token: str,
        prompt: str,
        model: str = "dall-e-3",
        n: int = 1,
        size: str = "1024x1024",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate images from a text prompt through the proxy.
        
        Args:
            token: The proxy authentication token.
            prompt: Text description of the desired image.
            model: The image generation model (default: dall-e-3).
            n: Number of images to generate (default: 1).
            size: Image size (default: 1024x1024).
            **kwargs: Additional parameters to pass to the API.
            
        Returns:
            The image generation response containing URLs or base64 data.
            
        Example:
            >>> client = Client()
            >>> result = client.image("TOKEN", prompt="A cat on the moon")
            >>> image_url = result["data"][0]["url"]
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "size": size,
            **kwargs
        }
        return self.proxy("v1/images/generations", token, payload=payload)
    
    def health(self) -> bool:
        """
        Check if the Double-O service is available.
        
        Returns:
            True if the service is healthy and reachable.
            
        Raises:
            ProxyError: If the service is unreachable or unhealthy.
            
        Example:
            >>> client = Client()
            >>> if client.health():
            ...     print("Service is up!")
        """
        url = f"{self.base_url}/health"
        
        try:
            response = self._request_with_retry(
                "GET",
                url,
                timeout=self.timeout
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            raise ProxyError(f"Health check failed: {e}") from e
    
    def close(self):
        """Close the underlying session."""
        self._session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Default client instance for simple usage
_default_client: Optional[Client] = None


def _get_default_client(
    base_url: str = BASE_URL,
    retries: int = 0,
    backoff_factor: float = 0.5,
) -> Client:
    """Get or create the default client instance."""
    global _default_client
    if _default_client is None:
        _default_client = Client(
            base_url=base_url,
            retries=retries,
            backoff_factor=backoff_factor,
        )
    return _default_client


def get_secret(
    token: str,
    base_url: str = BASE_URL,
    cache_ttl: Optional[float] = None,
) -> str:
    """
    Fetch a secret value using a token.
    
    This is a convenience function that uses a default client instance.
    
    Args:
        token: The authentication token for fetching the secret.
        base_url: Base URL for the API server (default: BASE_URL)
        cache_ttl: Optional TTL in seconds to cache the secret locally.
        
    Returns:
        The secret value as a string.
        
    Example:
        >>> import oo
        >>> secret = oo.get_secret("YOUR_TOKEN_HERE")
        >>> 
        >>> # With caching (5 minutes)
        >>> secret = oo.get_secret("YOUR_TOKEN_HERE", cache_ttl=300)
    """
    client = _get_default_client(base_url)
    return client.get_secret(token, cache_ttl=cache_ttl)


def proxy(
    path: str,
    token: str,
    method: str = "POST",
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    base_url: str = BASE_URL
) -> Dict[str, Any]:
    """
    Make an API call through the proxy.
    
    This is a convenience function that uses a default client instance.
    
    Args:
        path: The API path to call (e.g., 'v1/chat/completions').
        token: The proxy authentication token.
        method: HTTP method (default: POST).
        payload: Request payload as a dictionary (optional).
        headers: Additional headers to include (optional).
        base_url: Base URL for the API server (default: BASE_URL)
        
    Returns:
        The JSON response as a dictionary.
        
    Example:
        >>> import oo
        >>> result = oo.proxy(
        ...     "v1/chat/completions",
        ...     token="YOUR_TOKEN",
        ...     payload={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hello!"}]}
        ... )
    """
    client = _get_default_client(base_url)
    return client.proxy(path, token, method, payload, headers)


def chat(
    token: str,
    messages: list,
    model: str = "gpt-4o-mini",
    base_url: str = BASE_URL,
    **kwargs
) -> Dict[str, Any]:
    """
    Convenience function for OpenAI chat completions through the proxy.
    
    Args:
        token: The proxy authentication token.
        messages: List of message dictionaries with 'role' and 'content'.
        model: The model to use (default: gpt-4o-mini).
        base_url: Base URL for the API server (default: BASE_URL)
        **kwargs: Additional parameters to pass to the API.
        
    Returns:
        The chat completion response.
        
    Example:
        >>> import oo
        >>> result = oo.chat(
        ...     token="YOUR_TOKEN",
        ...     messages=[{"role": "user", "content": "Hello!"}]
        ... )
        >>> print(result)
    """
    client = _get_default_client(base_url)
    return client.chat_completion(token, messages, model, **kwargs)


def get_env(
    token: str,
    base_url: str = BASE_URL,
    cache_ttl: Optional[float] = None,
) -> Dict[str, str]:
    """
    Fetch environment variables/secrets using a virtual env token.
    
    This is a convenience function that uses a default client instance.
    
    Args:
        token: The virtual environment token.
        base_url: Base URL for the API server (default: BASE_URL)
        cache_ttl: Optional TTL in seconds to cache the environment.
        
    Returns:
        A dictionary of environment variable names to their values.
        
    Example:
        >>> import oo
        >>> env = oo.get_env("YOUR_VIRTUAL_ENV_TOKEN")
        >>> print(env)
        {"OPENAI_API_KEY": "sk-xxx", "DB_URL": "..."}
    """
    client = _get_default_client(base_url)
    return client.get_env(token, cache_ttl=cache_ttl)


def load_env(
    token: str,
    base_url: str = BASE_URL,
    cache_ttl: Optional[float] = None,
) -> Dict[str, str]:
    """
    Fetch environment variables and set them in os.environ.
    
    This is a convenience function that uses a default client instance.
    
    Args:
        token: The virtual environment token.
        base_url: Base URL for the API server (default: BASE_URL)
        cache_ttl: Optional TTL in seconds to cache the environment.
        
    Returns:
        A dictionary of environment variable names to their values.
        
    Example:
        >>> import oo
        >>> oo.load_env("YOUR_VIRTUAL_ENV_TOKEN")
        >>> import os
        >>> print(os.environ["OPENAI_API_KEY"])
        sk-xxx
    """
    client = _get_default_client(base_url)
    return client.load_env(token, cache_ttl=cache_ttl)


def invalidate_cache(token: Optional[str] = None) -> None:
    """
    Invalidate cached secrets.
    
    Args:
        token: If provided, only invalidate the cache for this token.
               If None, clear the entire cache.
    """
    _secret_cache.invalidate(token) if token else _secret_cache.clear()


def export_env(
    token: str,
    path: str = ".env",
    overwrite: bool = True,
    base_url: str = BASE_URL,
    cache_ttl: Optional[float] = None,
) -> Dict[str, str]:
    """
    Fetch environment variables and write them to a .env file.
    
    This is a convenience function that uses a default client instance.
    
    Args:
        token: The virtual environment token.
        path: Path to the .env file (default: ".env").
        overwrite: If True, overwrite existing file. If False, append.
        base_url: Base URL for the API server (default: BASE_URL)
        cache_ttl: Optional TTL in seconds to cache the environment.
        
    Returns:
        A dictionary of environment variable names to their values.
        
    Example:
        >>> import oo
        >>> oo.export_env("TOKEN", path=".env")
        {"OPENAI_API_KEY": "sk-xxx", "DB_URL": "..."}
    """
    client = _get_default_client(base_url)
    return client.export_env(token, path=path, overwrite=overwrite, cache_ttl=cache_ttl)


def embed(
    token: str,
    texts: list,
    model: str = "text-embedding-3-small",
    base_url: str = BASE_URL,
    **kwargs
) -> Dict[str, Any]:
    """
    Generate embeddings for the given texts through the proxy.
    
    This is a convenience function that uses a default client instance.
    
    Args:
        token: The proxy authentication token.
        texts: List of text strings to generate embeddings for.
        model: The embedding model to use (default: text-embedding-3-small).
        base_url: Base URL for the API server (default: BASE_URL)
        **kwargs: Additional parameters to pass to the API.
        
    Returns:
        The embeddings response containing vector representations.
        
    Example:
        >>> import oo
        >>> result = oo.embed("TOKEN", texts=["hello", "world"])
        >>> embeddings = [item["embedding"] for item in result["data"]]
    """
    client = _get_default_client(base_url)
    return client.embed(token, texts, model, **kwargs)


def image(
    token: str,
    prompt: str,
    model: str = "dall-e-3",
    n: int = 1,
    size: str = "1024x1024",
    base_url: str = BASE_URL,
    **kwargs
) -> Dict[str, Any]:
    """
    Generate images from a text prompt through the proxy.
    
    This is a convenience function that uses a default client instance.
    
    Args:
        token: The proxy authentication token.
        prompt: Text description of the desired image.
        model: The image generation model (default: dall-e-3).
        n: Number of images to generate (default: 1).
        size: Image size (default: 1024x1024).
        base_url: Base URL for the API server (default: BASE_URL)
        **kwargs: Additional parameters to pass to the API.
        
    Returns:
        The image generation response containing URLs or base64 data.
        
    Example:
        >>> import oo
        >>> result = oo.image("TOKEN", prompt="A cat on the moon")
        >>> image_url = result["data"][0]["url"]
    """
    client = _get_default_client(base_url)
    return client.image(token, prompt, model, n, size, **kwargs)


def health(base_url: str = BASE_URL) -> bool:
    """
    Check if the Double-O service is available.
    
    This is a convenience function that uses a default client instance.
    
    Args:
        base_url: Base URL for the API server (default: BASE_URL)
        
    Returns:
        True if the service is healthy and reachable.
        
    Raises:
        ProxyError: If the service is unreachable or unhealthy.
        
    Example:
        >>> import oo
        >>> if oo.health():
        ...     print("Service is up!")
    """
    client = _get_default_client(base_url)
    return client.health()
