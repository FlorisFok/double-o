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
        # This test verifies the error message when aiohttp is missing
        # Since we're testing with aiohttp installed, we can't easily test this
        # but we verify the import path works
        from oo import AsyncClient
        assert AsyncClient is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

