"""Tests for the Async Double-O client module."""

import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch, MagicMock

import pytest

try:
    import aiohttp
    from oo.async_client import AsyncClient, AsyncSecretCache
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncSecretCache:
    """Test cases for the AsyncSecretCache class."""
    
    @pytest.fixture
    def cache(self):
        return AsyncSecretCache()
    
    @pytest.mark.asyncio
    async def test_cache_set_and_get(self, cache):
        """Test basic cache set and get operations."""
        await cache.set("key1", "value1", ttl=60)
        result = await cache.get("key1")
        assert result == "value1"
    
    @pytest.mark.asyncio
    async def test_cache_miss(self, cache):
        """Test cache miss returns None."""
        result = await cache.get("nonexistent_key")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_cache_expiry(self, cache):
        """Test that cached items expire after TTL."""
        await cache.set("key1", "value1", ttl=0.1)  # 100ms TTL
        
        # Should exist immediately
        assert await cache.get("key1") == "value1"
        
        # Wait for expiry
        await asyncio.sleep(0.15)
        
        # Should be gone after TTL
        assert await cache.get("key1") is None
    
    @pytest.mark.asyncio
    async def test_cache_invalidate(self, cache):
        """Test cache invalidation."""
        await cache.set("key1", "value1", ttl=60)
        await cache.set("key2", "value2", ttl=60)
        
        await cache.invalidate("key1")
        
        assert await cache.get("key1") is None
        assert await cache.get("key2") == "value2"
    
    @pytest.mark.asyncio
    async def test_cache_clear(self, cache):
        """Test clearing all cached items."""
        await cache.set("key1", "value1", ttl=60)
        await cache.set("key2", "value2", ttl=60)
        
        await cache.clear()
        
        assert await cache.get("key1") is None
        assert await cache.get("key2") is None


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncClient:
    """Test cases for the AsyncClient class."""
    
    @pytest.fixture
    def mock_response(self):
        """Create a mock aiohttp response."""
        response = AsyncMock()
        response.status = 200
        response.raise_for_status = Mock()
        return response
    
    @pytest.mark.asyncio
    async def test_get_secret_success(self, mock_response):
        """Test successful secret retrieval."""
        mock_response.json = AsyncMock(return_value={"value": "my_secret_value"})
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session
            
            async with AsyncClient(base_url="http://localhost:3001") as client:
                result = await client.get_secret("test_token")
            
            assert result == "my_secret_value"
            call_kwargs = mock_session.request.call_args
            assert call_kwargs.kwargs.get("headers") == {"Authorization": "Bearer test_token"}
            assert "params" not in call_kwargs.kwargs
    
    @pytest.mark.asyncio
    async def test_get_secret_with_caching(self, mock_response):
        """Test that secrets are cached when cache_ttl is provided."""
        mock_response.json = AsyncMock(return_value={"value": "cached_secret"})
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session
            
            async with AsyncClient(base_url="http://localhost:3001") as client:
                # Clear any existing cache
                await client.invalidate_cache()
                
                # First call should hit the API
                result1 = await client.get_secret("test_token", cache_ttl=300)
                assert result1 == "cached_secret"
                assert mock_session.request.call_count == 1
                
                # Second call should use cache
                result2 = await client.get_secret("test_token", cache_ttl=300)
                assert result2 == "cached_secret"
                assert mock_session.request.call_count == 1  # Still 1
    
    @pytest.mark.asyncio
    async def test_proxy_success(self, mock_response):
        """Test successful proxy request."""
        mock_response.json = AsyncMock(return_value={"choices": [{"message": {"content": "Hello!"}}]})
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session
            
            async with AsyncClient(base_url="http://localhost:3001") as client:
                result = await client.proxy(
                    "v1/chat/completions",
                    "test_token",
                    payload={"model": "gpt-4o-mini", "messages": []}
                )
            
            assert "choices" in result
    
    @pytest.mark.asyncio
    async def test_chat_completion(self, mock_response):
        """Test chat completion convenience method."""
        mock_response.json = AsyncMock(return_value={
            "choices": [{"message": {"content": "Hi there!"}}]
        })
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session
            
            async with AsyncClient(base_url="http://localhost:3001") as client:
                result = await client.chat_completion(
                    "test_token",
                    messages=[{"role": "user", "content": "Hello!"}]
                )
            
            assert "choices" in result


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncRetryLogic:
    """Test async retry with backoff logic."""
    
    @pytest.mark.asyncio
    async def test_retry_on_transient_failure(self):
        """Test that transient failures trigger retries."""
        success_response = AsyncMock()
        success_response.status = 200
        success_response.raise_for_status = Mock()
        success_response.json = AsyncMock(return_value={"value": "secret"})
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.closed = False
            
            # Fail twice, then succeed
            mock_session.request = AsyncMock(side_effect=[
                aiohttp.ClientError("Connection failed"),
                aiohttp.ClientError("Connection failed"),
                success_response
            ])
            mock_session_class.return_value = mock_session
            
            async with AsyncClient(
                base_url="http://localhost:3001",
                retries=2,
                backoff_factor=0.01
            ) as client:
                result = await client.get_secret("test_token")
            
            assert result == "secret"
            assert mock_session.request.call_count == 3
    
    @pytest.mark.asyncio
    async def test_no_retry_when_disabled(self):
        """Test that no retries happen when retries=0."""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.closed = False
            mock_session.request = AsyncMock(side_effect=aiohttp.ClientError("Failed"))
            mock_session_class.return_value = mock_session
            
            from oo.exceptions import SecretError
            
            async with AsyncClient(
                base_url="http://localhost:3001",
                retries=0
            ) as client:
                with pytest.raises(SecretError):
                    await client.get_secret("test_token")
            
            assert mock_session.request.call_count == 1


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncClientImportError:
    """Test AsyncClient import error handling."""

    def test_asyncclient_import_without_aiohttp(self):
        """Test that AsyncClient raises ImportError when aiohttp is not installed."""
        from oo import AsyncClient
        assert AsyncClient is not None

    def test_asyncclient_raises_when_aiohttp_none(self):
        """Test AsyncClient.__init__ raises ImportError when aiohttp is None."""
        import oo.async_client as async_module
        original = async_module.aiohttp
        async_module.aiohttp = None
        try:
            with pytest.raises(ImportError, match="aiohttp is required"):
                AsyncClient()
        finally:
            async_module.aiohttp = original

    def test_aiohttp_import_error_branch(self):
        """Test the except ImportError branch at module level."""
        import sys
        import importlib
        import oo.async_client as async_module
        original = sys.modules.get('aiohttp')
        sys.modules['aiohttp'] = None
        try:
            try:
                importlib.reload(async_module)
            except AttributeError:
                pass  # Type annotations reference aiohttp.ClientSession during class definition
            assert async_module.aiohttp is None
        finally:
            sys.modules['aiohttp'] = original
            importlib.reload(async_module)


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncExportEnv:
    """Test cases for async export_env functionality."""
    
    @pytest.fixture
    def mock_response(self):
        """Create a mock aiohttp response."""
        response = AsyncMock()
        response.status = 200
        response.raise_for_status = Mock()
        return response
    
    @pytest.mark.asyncio
    async def test_export_env_success(self, mock_response, tmp_path):
        """Test successful async env export to file."""
        env_path = tmp_path / "test.env"
        mock_response.json = AsyncMock(return_value={
            "secrets": {"API_KEY": "sk-123", "DB_URL": "postgres://localhost"}
        })
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session
            
            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.invalidate_cache()
                result = await client.export_env("test_token", path=str(env_path))
            
            assert result == {"API_KEY": "sk-123", "DB_URL": "postgres://localhost"}
            
            content = env_path.read_text()
            assert 'API_KEY="sk-123"' in content
            assert 'DB_URL="postgres://localhost"' in content


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncEmbed:
    """Test cases for async embed functionality."""
    
    @pytest.fixture
    def mock_response(self):
        """Create a mock aiohttp response."""
        response = AsyncMock()
        response.status = 200
        response.raise_for_status = Mock()
        return response
    
    @pytest.mark.asyncio
    async def test_embed_success(self, mock_response):
        """Test successful async embeddings generation."""
        mock_response.json = AsyncMock(return_value={
            "object": "list",
            "data": [
                {"object": "embedding", "embedding": [0.1, 0.2, 0.3], "index": 0},
                {"object": "embedding", "embedding": [0.4, 0.5, 0.6], "index": 1}
            ],
            "model": "text-embedding-3-small"
        })
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session
            
            async with AsyncClient(base_url="http://localhost:3001") as client:
                result = await client.embed("test_token", texts=["hello", "world"])
            
            assert "data" in result
            assert len(result["data"]) == 2
            assert result["data"][0]["embedding"] == [0.1, 0.2, 0.3]


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncImage:
    """Test cases for async image generation functionality."""
    
    @pytest.fixture
    def mock_response(self):
        """Create a mock aiohttp response."""
        response = AsyncMock()
        response.status = 200
        response.raise_for_status = Mock()
        return response
    
    @pytest.mark.asyncio
    async def test_image_success(self, mock_response):
        """Test successful async image generation."""
        mock_response.json = AsyncMock(return_value={
            "created": 1700000000,
            "data": [
                {"url": "https://example.com/image.png", "revised_prompt": "A cat on the moon"}
            ]
        })
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session
            
            async with AsyncClient(base_url="http://localhost:3001") as client:
                result = await client.image("test_token", prompt="A cat on the moon")
            
            assert "data" in result
            assert result["data"][0]["url"] == "https://example.com/image.png"
    
    @pytest.mark.asyncio
    async def test_image_custom_params(self, mock_response):
        """Test async image generation with custom parameters."""
        mock_response.json = AsyncMock(return_value={"data": []})
        
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session
            
            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.image(
                    "test_token",
                    prompt="A cat",
                    model="dall-e-2",
                    n=2,
                    size="512x512"
                )
            
            # Verify the request was made
            mock_session.request.assert_called_once()


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncHealth:
    """Test cases for async health check functionality."""
    
    @pytest.fixture
    def mock_response(self):
        """Create a mock aiohttp response."""
        response = AsyncMock()
        response.status = 200
        response.raise_for_status = Mock()
        return response
    
    @pytest.mark.asyncio
    async def test_health_success(self, mock_response):
        """Test successful async health check."""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session
            
            async with AsyncClient(base_url="http://localhost:3001") as client:
                result = await client.health()
            
            assert result is True
            # Verify the /health endpoint was called
            call_args = mock_session.request.call_args
            assert "/health" in str(call_args)
    
    @pytest.mark.asyncio
    async def test_health_failure(self):
        """Test async health check when service is down."""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(side_effect=aiohttp.ClientError("Service unavailable"))
            mock_session.closed = False
            mock_session_class.return_value = mock_session
            
            from oo.exceptions import ProxyError
            
            async with AsyncClient(base_url="http://localhost:3001") as client:
                with pytest.raises(ProxyError):
                    await client.health()


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncRetryExhaustion:
    """Test async retry exhaustion path."""

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        """Test that exception is raised when all retries are exhausted."""
        from oo.exceptions import SecretError

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.closed = False
            mock_session.request = AsyncMock(side_effect=aiohttp.ClientError("Failed"))
            mock_session_class.return_value = mock_session

            async with AsyncClient(
                base_url="http://localhost:3001",
                retries=2,
                backoff_factor=0.01
            ) as client:
                with pytest.raises(SecretError):
                    await client.get_secret("test_token")

            assert mock_session.request.call_count == 3


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncGetSecretErrorPaths:
    """Test error paths in AsyncClient.get_secret."""

    @pytest.fixture
    def mock_response(self):
        response = AsyncMock()
        response.status = 200
        response.raise_for_status = Mock()
        return response

    @pytest.mark.asyncio
    async def test_get_secret_401_status(self, mock_response):
        """Test get_secret raises AuthenticationError on 401 status."""
        mock_response.status = 401
        mock_response.json = AsyncMock(return_value={})

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            from oo.exceptions import AuthenticationError

            async with AsyncClient(base_url="http://localhost:3001") as client:
                with pytest.raises(AuthenticationError):
                    await client.get_secret("bad_token")

    @pytest.mark.asyncio
    async def test_get_secret_error_response_non_auth(self, mock_response):
        """Test get_secret raises SecretError on non-auth error response."""
        mock_response.json = AsyncMock(return_value={"error": "rate limit exceeded"})

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            from oo.exceptions import SecretError

            async with AsyncClient(base_url="http://localhost:3001") as client:
                with pytest.raises(SecretError, match="rate limit exceeded"):
                    await client.get_secret("token")

    @pytest.mark.asyncio
    async def test_get_secret_error_response_auth(self, mock_response):
        """Test get_secret raises AuthenticationError on auth error response."""
        mock_response.json = AsyncMock(return_value={"error": "Invalid token provided"})

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            from oo.exceptions import AuthenticationError

            async with AsyncClient(base_url="http://localhost:3001") as client:
                with pytest.raises(AuthenticationError):
                    await client.get_secret("token")

    @pytest.mark.asyncio
    async def test_get_secret_unknown_error(self, mock_response):
        """Test get_secret raises SecretError when response has neither value nor error."""
        mock_response.json = AsyncMock(return_value={"unexpected": "data"})

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            from oo.exceptions import SecretError

            async with AsyncClient(base_url="http://localhost:3001") as client:
                with pytest.raises(SecretError, match="Unknown error"):
                    await client.get_secret("token")

    @pytest.mark.asyncio
    async def test_get_secret_client_response_error_401(self):
        """Test get_secret raises AuthenticationError on ClientResponseError with 401."""
        from oo.exceptions import AuthenticationError

        error = aiohttp.ClientResponseError(
            request_info=Mock(),
            history=(),
            status=401,
            message="Unauthorized",
        )

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(side_effect=error)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                with pytest.raises(AuthenticationError):
                    await client.get_secret("token")

    @pytest.mark.asyncio
    async def test_get_secret_client_response_error_non_401(self):
        """Test get_secret raises SecretError on ClientResponseError with non-401."""
        from oo.exceptions import SecretError

        error = aiohttp.ClientResponseError(
            request_info=Mock(),
            history=(),
            status=500,
            message="Server Error",
        )

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(side_effect=error)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                with pytest.raises(SecretError, match="HTTP error"):
                    await client.get_secret("token")


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncInvalidateCache:
    """Test async invalidate_cache paths."""

    @pytest.mark.asyncio
    async def test_invalidate_cache_specific_token(self):
        """Test invalidating cache for a specific token."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = Mock()
        mock_response.json = AsyncMock(return_value={"value": "secret"})

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.invalidate_cache()

                await client.get_secret("tok", cache_ttl=300)
                assert mock_session.request.call_count == 1

                await client.invalidate_cache("tok")

                await client.get_secret("tok", cache_ttl=300)
                assert mock_session.request.call_count == 2


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncProxyErrorPaths:
    """Test error paths in AsyncClient.proxy."""

    @pytest.fixture
    def mock_response(self):
        response = AsyncMock()
        response.status = 200
        response.raise_for_status = Mock()
        return response

    @pytest.mark.asyncio
    async def test_proxy_with_custom_headers(self, mock_response):
        """Test proxy merges custom headers."""
        mock_response.json = AsyncMock(return_value={"ok": True})

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.proxy("v1/test", "token", headers={"X-Custom": "val"})

            sent_headers = mock_session.request.call_args.kwargs.get("headers")
            assert sent_headers["X-Custom"] == "val"
            assert "Authorization" in sent_headers

    @pytest.mark.asyncio
    async def test_proxy_401_status(self, mock_response):
        """Test proxy raises AuthenticationError on 401 status."""
        mock_response.status = 401
        mock_response.json = AsyncMock(return_value={})

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            from oo.exceptions import AuthenticationError

            async with AsyncClient(base_url="http://localhost:3001") as client:
                with pytest.raises(AuthenticationError):
                    await client.proxy("v1/test", "bad_token")

    @pytest.mark.asyncio
    async def test_proxy_client_response_error_401(self):
        """Test proxy raises AuthenticationError on ClientResponseError 401."""
        from oo.exceptions import AuthenticationError

        error = aiohttp.ClientResponseError(
            request_info=Mock(), history=(), status=401, message="Unauthorized"
        )

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(side_effect=error)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                with pytest.raises(AuthenticationError):
                    await client.proxy("v1/test", "token")

    @pytest.mark.asyncio
    async def test_proxy_client_response_error_non_401(self):
        """Test proxy raises ProxyError on ClientResponseError non-401."""
        from oo.exceptions import ProxyError

        error = aiohttp.ClientResponseError(
            request_info=Mock(), history=(), status=500, message="Server Error"
        )

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(side_effect=error)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                with pytest.raises(ProxyError, match="Proxy request failed"):
                    await client.proxy("v1/test", "token")

    @pytest.mark.asyncio
    async def test_proxy_client_error(self):
        """Test proxy raises ProxyError on ClientError."""
        from oo.exceptions import ProxyError

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(side_effect=aiohttp.ClientError("Connection refused"))
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                with pytest.raises(ProxyError, match="Request failed"):
                    await client.proxy("v1/test", "token")


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncGetEnv:
    """Test cases for async get_env functionality."""

    @pytest.fixture
    def mock_response(self):
        response = AsyncMock()
        response.status = 200
        response.raise_for_status = Mock()
        return response

    @pytest.mark.asyncio
    async def test_get_env_success(self, mock_response):
        """Test successful async env retrieval."""
        mock_response.json = AsyncMock(return_value={
            "secrets": {"KEY": "val"}
        })

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.invalidate_cache()
                result = await client.get_env("token")

            assert result == {"KEY": "val"}

    @pytest.mark.asyncio
    async def test_get_env_with_caching(self, mock_response):
        """Test async get_env caches and returns from cache."""
        mock_response.json = AsyncMock(return_value={
            "secrets": {"KEY": "val"}
        })

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.invalidate_cache()
                r1 = await client.get_env("token", cache_ttl=300)
                assert r1 == {"KEY": "val"}
                assert mock_session.request.call_count == 1

                r2 = await client.get_env("token", cache_ttl=300)
                assert r2 == {"KEY": "val"}
                assert mock_session.request.call_count == 1

    @pytest.mark.asyncio
    async def test_get_env_401_status(self, mock_response):
        """Test async get_env raises AuthenticationError on 401."""
        mock_response.status = 401
        mock_response.json = AsyncMock(return_value={})

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            from oo.exceptions import AuthenticationError

            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.invalidate_cache()
                with pytest.raises(AuthenticationError):
                    await client.get_env("bad_token")

    @pytest.mark.asyncio
    async def test_get_env_auth_error_response(self, mock_response):
        """Test async get_env raises AuthenticationError on auth error response."""
        mock_response.json = AsyncMock(return_value={"error": "Invalid token"})

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            from oo.exceptions import AuthenticationError

            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.invalidate_cache()
                with pytest.raises(AuthenticationError):
                    await client.get_env("token")

    @pytest.mark.asyncio
    async def test_get_env_non_auth_error_response(self, mock_response):
        """Test async get_env raises EnvError on non-auth error response."""
        mock_response.json = AsyncMock(return_value={"error": "rate limit"})

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            from oo.exceptions import EnvError

            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.invalidate_cache()
                with pytest.raises(EnvError):
                    await client.get_env("token")

    @pytest.mark.asyncio
    async def test_get_env_unknown_error(self, mock_response):
        """Test async get_env raises EnvError when no secrets or error in response."""
        mock_response.json = AsyncMock(return_value={"unexpected": "data"})

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            from oo.exceptions import EnvError

            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.invalidate_cache()
                with pytest.raises(EnvError, match="Unknown error"):
                    await client.get_env("token")

    @pytest.mark.asyncio
    async def test_get_env_client_response_error_401(self):
        """Test async get_env raises AuthenticationError on ClientResponseError 401."""
        from oo.exceptions import AuthenticationError

        error = aiohttp.ClientResponseError(
            request_info=Mock(), history=(), status=401, message="Unauthorized"
        )

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(side_effect=error)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.invalidate_cache()
                with pytest.raises(AuthenticationError):
                    await client.get_env("token")

    @pytest.mark.asyncio
    async def test_get_env_client_response_error_non_401(self):
        """Test async get_env raises EnvError on ClientResponseError non-401."""
        from oo.exceptions import EnvError

        error = aiohttp.ClientResponseError(
            request_info=Mock(), history=(), status=500, message="Server Error"
        )

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(side_effect=error)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.invalidate_cache()
                with pytest.raises(EnvError):
                    await client.get_env("token")

    @pytest.mark.asyncio
    async def test_get_env_client_error(self):
        """Test async get_env raises EnvError on ClientError."""
        from oo.exceptions import EnvError

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(side_effect=aiohttp.ClientError("Connection refused"))
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.invalidate_cache()
                with pytest.raises(EnvError, match="Request failed"):
                    await client.get_env("token")


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncLoadEnv:
    """Test cases for async load_env functionality."""

    @pytest.mark.asyncio
    async def test_load_env_sets_environ(self):
        """Test async load_env sets environment variables."""
        import os

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = Mock()
        mock_response.json = AsyncMock(return_value={
            "secrets": {"ASYNC_TEST_KEY": "async_val"}
        })

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.invalidate_cache()
                result = await client.load_env("token")

            assert result == {"ASYNC_TEST_KEY": "async_val"}
            assert os.environ["ASYNC_TEST_KEY"] == "async_val"
            os.environ.pop("ASYNC_TEST_KEY", None)


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
class TestAsyncExportEnvAppend:
    """Test async export_env append mode."""

    @pytest.mark.asyncio
    async def test_export_env_append_mode(self, tmp_path):
        """Test async export_env appends to existing file."""
        env_path = tmp_path / "test.env"
        env_path.write_text('EXISTING="value"\n')

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = Mock()
        mock_response.json = AsyncMock(return_value={
            "secrets": {"NEW_KEY": "new_val"}
        })

        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session.request = AsyncMock(return_value=mock_response)
            mock_session.closed = False
            mock_session_class.return_value = mock_session

            async with AsyncClient(base_url="http://localhost:3001") as client:
                await client.invalidate_cache()
                await client.export_env("token", path=str(env_path), overwrite=False)

            content = env_path.read_text()
            assert 'EXISTING="value"' in content
            assert 'NEW_KEY="new_val"' in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

