"""Tests for the Double-O client module."""

import json
import time
import unittest
from unittest.mock import Mock, patch, MagicMock

import oo
from oo import Client, SecretError, ProxyError, AuthenticationError, SecretCache


class TestClient(unittest.TestCase):
    """Test cases for the Client class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client(base_url="http://localhost:3001")
    
    def tearDown(self):
        """Clean up after tests."""
        self.client.close()
        # Clear the cache between tests
        self.client.invalidate_cache()
    
    @patch('oo.client.requests.Session.request')
    def test_get_secret_success(self, mock_request):
        """Test successful secret retrieval."""
        mock_response = Mock()
        mock_response.json.return_value = {"value": "my_secret_value"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = self.client.get_secret("test_token")
        
        self.assertEqual(result, "my_secret_value")
        mock_request.assert_called_once()
    
    @patch('oo.client.requests.Session.request')
    def test_get_secret_error(self, mock_request):
        """Test secret retrieval with error response."""
        mock_response = Mock()
        mock_response.json.return_value = {"error": "Invalid token"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        with self.assertRaises(AuthenticationError):
            self.client.get_secret("invalid_token")
    
    @patch('oo.client.requests.Session.request')
    def test_proxy_success(self, mock_request):
        """Test successful proxy request."""
        mock_response = Mock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "Hello!"}}]}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = self.client.proxy(
            "v1/chat/completions",
            "test_token",
            payload={"model": "gpt-4o-mini", "messages": []}
        )
        
        self.assertIn("choices", result)
        mock_request.assert_called_once()
    
    @patch('oo.client.requests.Session.request')
    def test_chat_completion(self, mock_request):
        """Test chat completion convenience method."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hi there!"}}]
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = self.client.chat_completion(
            "test_token",
            messages=[{"role": "user", "content": "Hello!"}]
        )
        
        self.assertIn("choices", result)


class TestSecretCache(unittest.TestCase):
    """Test cases for the SecretCache class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.cache = SecretCache()
    
    def tearDown(self):
        """Clean up after tests."""
        self.cache.clear()
    
    def test_cache_set_and_get(self):
        """Test basic cache set and get operations."""
        self.cache.set("key1", "value1", ttl=60)
        result = self.cache.get("key1")
        self.assertEqual(result, "value1")
    
    def test_cache_miss(self):
        """Test cache miss returns None."""
        result = self.cache.get("nonexistent_key")
        self.assertIsNone(result)
    
    def test_cache_expiry(self):
        """Test that cached items expire after TTL."""
        self.cache.set("key1", "value1", ttl=0.1)  # 100ms TTL
        
        # Should exist immediately
        self.assertEqual(self.cache.get("key1"), "value1")
        
        # Wait for expiry
        time.sleep(0.15)
        
        # Should be gone after TTL
        self.assertIsNone(self.cache.get("key1"))
    
    def test_cache_invalidate(self):
        """Test cache invalidation."""
        self.cache.set("key1", "value1", ttl=60)
        self.cache.set("key2", "value2", ttl=60)
        
        self.cache.invalidate("key1")
        
        self.assertIsNone(self.cache.get("key1"))
        self.assertEqual(self.cache.get("key2"), "value2")
    
    def test_cache_clear(self):
        """Test clearing all cached items."""
        self.cache.set("key1", "value1", ttl=60)
        self.cache.set("key2", "value2", ttl=60)
        
        self.cache.clear()
        
        self.assertIsNone(self.cache.get("key1"))
        self.assertIsNone(self.cache.get("key2"))


class TestCachingIntegration(unittest.TestCase):
    """Test caching integration with Client."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client(base_url="http://localhost:3001")
    
    def tearDown(self):
        """Clean up after tests."""
        self.client.close()
        self.client.invalidate_cache()
    
    @patch('oo.client.requests.Session.request')
    def test_get_secret_with_caching(self, mock_request):
        """Test that secrets are cached when cache_ttl is provided."""
        mock_response = Mock()
        mock_response.json.return_value = {"value": "cached_secret"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        # First call should hit the API
        result1 = self.client.get_secret("test_token", cache_ttl=300)
        self.assertEqual(result1, "cached_secret")
        self.assertEqual(mock_request.call_count, 1)
        
        # Second call should use cache
        result2 = self.client.get_secret("test_token", cache_ttl=300)
        self.assertEqual(result2, "cached_secret")
        self.assertEqual(mock_request.call_count, 1)  # Still 1, no new API call
    
    @patch('oo.client.requests.Session.request')
    def test_get_secret_without_caching(self, mock_request):
        """Test that secrets are not cached when cache_ttl is not provided."""
        mock_response = Mock()
        mock_response.json.return_value = {"value": "uncached_secret"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        # Both calls should hit the API
        self.client.get_secret("test_token")
        self.client.get_secret("test_token")
        
        self.assertEqual(mock_request.call_count, 2)
    
    @patch('oo.client.requests.Session.request')
    def test_invalidate_cache_specific_token(self, mock_request):
        """Test invalidating cache for specific token."""
        mock_response = Mock()
        mock_response.json.return_value = {"value": "secret"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        # Cache the secret
        self.client.get_secret("test_token", cache_ttl=300)
        self.assertEqual(mock_request.call_count, 1)
        
        # Invalidate cache
        self.client.invalidate_cache("test_token")
        
        # Next call should hit API again
        self.client.get_secret("test_token", cache_ttl=300)
        self.assertEqual(mock_request.call_count, 2)


class TestRetryLogic(unittest.TestCase):
    """Test retry with backoff logic."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client(
            base_url="http://localhost:3001",
            retries=2,
            backoff_factor=0.1  # Small backoff for fast tests
        )
    
    def tearDown(self):
        """Clean up after tests."""
        self.client.close()
        self.client.invalidate_cache()
    
    @patch('oo.client.requests.Session.request')
    def test_retry_on_transient_failure(self, mock_request):
        """Test that transient failures trigger retries."""
        import requests
        
        # Fail twice, then succeed
        mock_response_success = Mock()
        mock_response_success.json.return_value = {"value": "secret"}
        mock_response_success.raise_for_status = Mock()
        
        mock_request.side_effect = [
            requests.exceptions.ConnectionError("Connection failed"),
            requests.exceptions.ConnectionError("Connection failed"),
            mock_response_success
        ]
        
        result = self.client.get_secret("test_token")
        
        self.assertEqual(result, "secret")
        self.assertEqual(mock_request.call_count, 3)
    
    @patch('oo.client.requests.Session.request')
    def test_retry_exhausted(self, mock_request):
        """Test that SecretError is raised when all retries fail."""
        import requests
        
        mock_request.side_effect = requests.exceptions.ConnectionError("Connection failed")
        
        with self.assertRaises(SecretError):
            self.client.get_secret("test_token")
        
        # Initial attempt + 2 retries = 3 total attempts
        self.assertEqual(mock_request.call_count, 3)
    
    @patch('oo.client.requests.Session.request')
    def test_no_retry_when_disabled(self, mock_request):
        """Test that no retries happen when retries=0."""
        import requests
        
        client = Client(base_url="http://localhost:3001", retries=0)
        mock_request.side_effect = requests.exceptions.ConnectionError("Connection failed")
        
        with self.assertRaises(SecretError):
            client.get_secret("test_token")
        
        # Only 1 attempt, no retries
        self.assertEqual(mock_request.call_count, 1)
        client.close()


class TestConvenienceFunctions(unittest.TestCase):
    """Test cases for module-level convenience functions."""
    
    def tearDown(self):
        """Clean up after tests."""
        oo.invalidate_cache()
    
    @patch('oo.client.requests.Session.request')
    def test_get_secret_function(self, mock_request):
        """Test the get_secret convenience function."""
        mock_response = Mock()
        mock_response.json.return_value = {"value": "secret123"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = oo.get_secret("my_token")
        
        self.assertEqual(result, "secret123")
    
    @patch('oo.client.requests.Session.request')
    def test_get_secret_function_with_cache(self, mock_request):
        """Test the get_secret convenience function with caching."""
        mock_response = Mock()
        mock_response.json.return_value = {"value": "cached_secret"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        # First call
        result1 = oo.get_secret("my_token", cache_ttl=300)
        self.assertEqual(result1, "cached_secret")
        
        # Second call should use cache
        result2 = oo.get_secret("my_token", cache_ttl=300)
        self.assertEqual(result2, "cached_secret")
        
        # Only one API call
        self.assertEqual(mock_request.call_count, 1)
    
    @patch('oo.client.requests.Session.request')
    def test_proxy_function(self, mock_request):
        """Test the proxy convenience function."""
        mock_response = Mock()
        mock_response.json.return_value = {"result": "success"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = oo.proxy(
            "v1/test",
            "my_token",
            payload={"data": "test"}
        )
        
        self.assertEqual(result["result"], "success")
    
    @patch('oo.client.requests.Session.request')
    def test_chat_function(self, mock_request):
        """Test the chat convenience function."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Response"}}]
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = oo.chat(
            "my_token",
            messages=[{"role": "user", "content": "Test"}]
        )
        
        self.assertIn("choices", result)


class TestExceptions(unittest.TestCase):
    """Test cases for custom exceptions."""
    
    def test_exception_hierarchy(self):
        """Test that all exceptions inherit from DoubleOError."""
        self.assertTrue(issubclass(SecretError, oo.DoubleOError))
        self.assertTrue(issubclass(ProxyError, oo.DoubleOError))
        self.assertTrue(issubclass(AuthenticationError, oo.DoubleOError))


if __name__ == "__main__":
    unittest.main()
