"""Double-O client module for secret fetching and proxy API calls."""

import json
from typing import Any, Dict, Optional, Union

import requests

from .exceptions import AuthenticationError, ProxyError, SecretError


BASE_URL = "https://double-o-539191849800.europe-west1.run.app"

class Client:
    """
    Double-O Client for interacting with secret management and proxy services.
    
    Args:
        base_url: Base URL for the API server (default: BASE_URL)
        timeout: Request timeout in seconds (default: 30)
    """
    
    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: int = 30
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
    
    def get_secret(self, token: str) -> str:
        """
        Fetch a secret value using a token.
        
        Args:
            token: The authentication token for fetching the secret.
            
        Returns:
            The secret value as a string.
            
        Raises:
            SecretError: If the secret cannot be retrieved.
            AuthenticationError: If the token is invalid.
        """
        url = f"{self.base_url}/api/secret"
        
        try:
            response = self._session.get(
                url,
                params={"token": token},
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            
            if "value" in data:
                return data["value"]
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
            response = self._session.request(
                method=method.upper(),
                url=url,
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
    
    def close(self):
        """Close the underlying session."""
        self._session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Default client instance for simple usage
_default_client: Optional[Client] = None


def _get_default_client(base_url: str = BASE_URL) -> Client:
    """Get or create the default client instance."""
    global _default_client
    if _default_client is None:
        _default_client = Client(base_url=base_url)
    return _default_client


def get_secret(token: str, base_url: str = BASE_URL) -> str:
    """
    Fetch a secret value using a token.
    
    This is a convenience function that uses a default client instance.
    
    Args:
        token: The authentication token for fetching the secret.
        base_url: Base URL for the API server (default: BASE_URL)
        
    Returns:
        The secret value as a string.
        
    Example:
        >>> import oo
        >>> secret = oo.get_secret("YOUR_TOKEN_HERE")
        >>> print(secret)
    """
    client = _get_default_client(base_url)
    return client.get_secret(token)


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
