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
        call_kwargs = mock_request.call_args
        self.assertEqual(
            call_kwargs.kwargs.get("headers"),
            {"Authorization": "Bearer test_token"}
        )
        self.assertNotIn("params", call_kwargs.kwargs)
    
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


class TestGetSecretErrorPaths(unittest.TestCase):
    """Test error paths in Client.get_secret."""

    def setUp(self):
        self.client = Client(base_url="http://localhost:3001")

    def tearDown(self):
        self.client.close()
        self.client.invalidate_cache()

    @patch('oo.client.requests.Session.request')
    def test_get_secret_non_auth_error(self, mock_request):
        """Test get_secret with a non-auth error in the response body."""
        mock_response = Mock()
        mock_response.json.return_value = {"error": "rate limit exceeded"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        with self.assertRaises(SecretError) as ctx:
            self.client.get_secret("test_token")
        self.assertIn("rate limit exceeded", str(ctx.exception))

    @patch('oo.client.requests.Session.request')
    def test_get_secret_unknown_error(self, mock_request):
        """Test get_secret when response has neither value nor error."""
        mock_response = Mock()
        mock_response.json.return_value = {"unexpected": "data"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        with self.assertRaises(SecretError) as ctx:
            self.client.get_secret("test_token")
        self.assertIn("Unknown error", str(ctx.exception))

    @patch('oo.client.requests.Session.request')
    def test_get_secret_http_401(self, mock_request):
        """Test get_secret raises AuthenticationError on HTTP 401."""
        import requests
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_request.return_value = mock_response

        with self.assertRaises(AuthenticationError):
            self.client.get_secret("bad_token")

    @patch('oo.client.requests.Session.request')
    def test_get_secret_http_non_401(self, mock_request):
        """Test get_secret raises SecretError on non-401 HTTP errors."""
        import requests
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_request.return_value = mock_response

        with self.assertRaises(SecretError) as ctx:
            self.client.get_secret("test_token")
        self.assertIn("HTTP error", str(ctx.exception))


class TestProxyErrorPaths(unittest.TestCase):
    """Test error and edge-case paths in Client.proxy."""

    def setUp(self):
        self.client = Client(base_url="http://localhost:3001")

    def tearDown(self):
        self.client.close()

    @patch('oo.client.requests.Session.request')
    def test_proxy_with_custom_headers(self, mock_request):
        """Test proxy merges custom headers."""
        mock_response = Mock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        self.client.proxy(
            "v1/test", "token",
            headers={"X-Custom": "value"}
        )

        call_kwargs = mock_request.call_args
        sent_headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        self.assertEqual(sent_headers["X-Custom"], "value")
        self.assertIn("Authorization", sent_headers)

    @patch('oo.client.requests.Session.request')
    def test_proxy_http_401(self, mock_request):
        """Test proxy raises AuthenticationError on HTTP 401."""
        import requests
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_request.return_value = mock_response

        with self.assertRaises(AuthenticationError):
            self.client.proxy("v1/test", "bad_token")

    @patch('oo.client.requests.Session.request')
    def test_proxy_http_non_401(self, mock_request):
        """Test proxy raises ProxyError on non-401 HTTP errors."""
        import requests
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_request.return_value = mock_response

        with self.assertRaises(ProxyError):
            self.client.proxy("v1/test", "token")

    @patch('oo.client.requests.Session.request')
    def test_proxy_request_exception(self, mock_request):
        """Test proxy raises ProxyError on RequestException."""
        import requests
        mock_request.side_effect = requests.exceptions.ConnectionError("Connection refused")

        with self.assertRaises(ProxyError) as ctx:
            self.client.proxy("v1/test", "token")
        self.assertIn("Request failed", str(ctx.exception))


class TestGetEnv(unittest.TestCase):
    """Test cases for get_env functionality."""

    def setUp(self):
        self.client = Client(base_url="http://localhost:3001")

    def tearDown(self):
        self.client.close()
        self.client.invalidate_cache()

    @patch('oo.client.requests.Session.request')
    def test_get_env_success(self, mock_request):
        """Test successful env retrieval."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "secrets": {"API_KEY": "sk-123", "DB_URL": "postgres://localhost"}
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        result = self.client.get_env("test_token")
        self.assertEqual(result, {"API_KEY": "sk-123", "DB_URL": "postgres://localhost"})

    @patch('oo.client.requests.Session.request')
    def test_get_env_with_caching(self, mock_request):
        """Test get_env caches results and returns from cache."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "secrets": {"KEY": "val"}
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        result1 = self.client.get_env("test_token", cache_ttl=300)
        self.assertEqual(result1, {"KEY": "val"})
        self.assertEqual(mock_request.call_count, 1)

        result2 = self.client.get_env("test_token", cache_ttl=300)
        self.assertEqual(result2, {"KEY": "val"})
        self.assertEqual(mock_request.call_count, 1)

    @patch('oo.client.requests.Session.request')
    def test_get_env_auth_error(self, mock_request):
        """Test get_env raises AuthenticationError on auth error response."""
        mock_response = Mock()
        mock_response.json.return_value = {"error": "Invalid token"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        with self.assertRaises(AuthenticationError):
            self.client.get_env("bad_token")

    @patch('oo.client.requests.Session.request')
    def test_get_env_non_auth_error(self, mock_request):
        """Test get_env raises EnvError on non-auth error response."""
        mock_response = Mock()
        mock_response.json.return_value = {"error": "rate limit exceeded"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        with self.assertRaises(oo.EnvError):
            self.client.get_env("token")

    @patch('oo.client.requests.Session.request')
    def test_get_env_unknown_error(self, mock_request):
        """Test get_env raises EnvError when response has no secrets or error."""
        mock_response = Mock()
        mock_response.json.return_value = {"unexpected": "data"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        with self.assertRaises(oo.EnvError) as ctx:
            self.client.get_env("token")
        self.assertIn("Unknown error", str(ctx.exception))

    @patch('oo.client.requests.Session.request')
    def test_get_env_http_401(self, mock_request):
        """Test get_env raises AuthenticationError on HTTP 401."""
        import requests
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_request.return_value = mock_response

        with self.assertRaises(AuthenticationError):
            self.client.get_env("bad_token")

    @patch('oo.client.requests.Session.request')
    def test_get_env_http_non_401(self, mock_request):
        """Test get_env raises EnvError on non-401 HTTP errors."""
        import requests
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=mock_response
        )
        mock_request.return_value = mock_response

        with self.assertRaises(oo.EnvError):
            self.client.get_env("token")

    @patch('oo.client.requests.Session.request')
    def test_get_env_request_exception(self, mock_request):
        """Test get_env raises EnvError on RequestException."""
        import requests
        mock_request.side_effect = requests.exceptions.ConnectionError("Connection refused")

        with self.assertRaises(oo.EnvError) as ctx:
            self.client.get_env("token")
        self.assertIn("Request failed", str(ctx.exception))


class TestLoadEnv(unittest.TestCase):
    """Test cases for load_env functionality."""

    def setUp(self):
        self.client = Client(base_url="http://localhost:3001")

    def tearDown(self):
        self.client.close()
        self.client.invalidate_cache()
        import os
        os.environ.pop("TEST_KEY_1", None)
        os.environ.pop("TEST_KEY_2", None)

    @patch('oo.client.requests.Session.request')
    def test_load_env_sets_environ(self, mock_request):
        """Test load_env sets environment variables."""
        import os
        mock_response = Mock()
        mock_response.json.return_value = {
            "secrets": {"TEST_KEY_1": "value1", "TEST_KEY_2": "value2"}
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        result = self.client.load_env("test_token")

        self.assertEqual(result, {"TEST_KEY_1": "value1", "TEST_KEY_2": "value2"})
        self.assertEqual(os.environ["TEST_KEY_1"], "value1")
        self.assertEqual(os.environ["TEST_KEY_2"], "value2")


class TestContextManager(unittest.TestCase):
    """Test the Client context manager."""

    @patch('oo.client.requests.Session.request')
    def test_context_manager(self, mock_request):
        """Test Client works as a context manager."""
        mock_response = Mock()
        mock_response.json.return_value = {"value": "secret"}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        with Client(base_url="http://localhost:3001") as client:
            result = client.get_secret("token")
            self.assertEqual(result, "secret")


class TestExceptions(unittest.TestCase):
    """Test cases for custom exceptions."""
    
    def test_exception_hierarchy(self):
        """Test that all exceptions inherit from DoubleOError."""
        self.assertTrue(issubclass(SecretError, oo.DoubleOError))
        self.assertTrue(issubclass(ProxyError, oo.DoubleOError))
        self.assertTrue(issubclass(AuthenticationError, oo.DoubleOError))


class TestExportEnv(unittest.TestCase):
    """Test cases for export_env functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client(base_url="http://localhost:3001")
        self.test_env_path = "/tmp/test_export.env"
    
    def tearDown(self):
        """Clean up after tests."""
        self.client.close()
        self.client.invalidate_cache()
        # Clean up test file
        import os
        if os.path.exists(self.test_env_path):
            os.remove(self.test_env_path)
    
    @patch('oo.client.requests.Session.request')
    def test_export_env_success(self, mock_request):
        """Test successful env export to file."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "secrets": {"API_KEY": "sk-123", "DB_URL": "postgres://localhost"}
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = self.client.export_env("test_token", path=self.test_env_path)
        
        self.assertEqual(result, {"API_KEY": "sk-123", "DB_URL": "postgres://localhost"})
        call_kwargs = mock_request.call_args
        self.assertEqual(
            call_kwargs.kwargs.get("headers"),
            {"Authorization": "Bearer test_token"}
        )
        
        # Verify file was written correctly
        with open(self.test_env_path, "r") as f:
            content = f.read()
        
        self.assertIn('API_KEY="sk-123"', content)
        self.assertIn('DB_URL="postgres://localhost"', content)
    
    @patch('oo.client.requests.Session.request')
    def test_export_env_escapes_special_chars(self, mock_request):
        """Test that special characters are properly escaped."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "secrets": {"PASSWORD": 'pass"word\\test'}
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        self.client.export_env("test_token", path=self.test_env_path)
        
        with open(self.test_env_path, "r") as f:
            content = f.read()
        
        self.assertIn('PASSWORD="pass\\"word\\\\test"', content)
    
    @patch('oo.client.requests.Session.request')
    def test_export_env_append_mode(self, mock_request):
        """Test appending to existing .env file."""
        # Create initial file
        with open(self.test_env_path, "w") as f:
            f.write('EXISTING_VAR="value"\n')
        
        mock_response = Mock()
        mock_response.json.return_value = {
            "secrets": {"NEW_VAR": "new_value"}
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        self.client.export_env("test_token", path=self.test_env_path, overwrite=False)
        
        with open(self.test_env_path, "r") as f:
            content = f.read()
        
        self.assertIn('EXISTING_VAR="value"', content)
        self.assertIn('NEW_VAR="new_value"', content)
    
    @patch('oo.client.requests.Session.request')
    def test_export_env_convenience_function(self, mock_request):
        """Test the export_env convenience function."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "secrets": {"KEY": "value"}
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = oo.export_env("test_token", path=self.test_env_path)
        
        self.assertEqual(result, {"KEY": "value"})
        
        # Clean up
        import os
        if os.path.exists(self.test_env_path):
            os.remove(self.test_env_path)


class TestEmbed(unittest.TestCase):
    """Test cases for embed functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client(base_url="http://localhost:3001")
    
    def tearDown(self):
        """Clean up after tests."""
        self.client.close()
    
    @patch('oo.client.requests.Session.request')
    def test_embed_success(self, mock_request):
        """Test successful embeddings generation."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "object": "list",
            "data": [
                {"object": "embedding", "embedding": [0.1, 0.2, 0.3], "index": 0},
                {"object": "embedding", "embedding": [0.4, 0.5, 0.6], "index": 1}
            ],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 4, "total_tokens": 4}
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = self.client.embed("test_token", texts=["hello", "world"])
        
        self.assertIn("data", result)
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][0]["embedding"], [0.1, 0.2, 0.3])
    
    @patch('oo.client.requests.Session.request')
    def test_embed_custom_model(self, mock_request):
        """Test embeddings with custom model."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        self.client.embed("test_token", texts=["test"], model="text-embedding-ada-002")
        
        # Verify the request was made with correct payload
        call_args = mock_request.call_args
        self.assertIn("text-embedding-ada-002", str(call_args))
    
    @patch('oo.client.requests.Session.request')
    def test_embed_convenience_function(self, mock_request):
        """Test the embed convenience function."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1, 0.2]}]
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = oo.embed("test_token", texts=["hello"])
        
        self.assertIn("data", result)


class TestImage(unittest.TestCase):
    """Test cases for image generation functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client(base_url="http://localhost:3001")
    
    def tearDown(self):
        """Clean up after tests."""
        self.client.close()
    
    @patch('oo.client.requests.Session.request')
    def test_image_success(self, mock_request):
        """Test successful image generation."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "created": 1700000000,
            "data": [
                {"url": "https://example.com/image.png", "revised_prompt": "A cat on the moon"}
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = self.client.image("test_token", prompt="A cat on the moon")
        
        self.assertIn("data", result)
        self.assertEqual(result["data"][0]["url"], "https://example.com/image.png")
    
    @patch('oo.client.requests.Session.request')
    def test_image_custom_params(self, mock_request):
        """Test image generation with custom parameters."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        self.client.image(
            "test_token",
            prompt="A cat",
            model="dall-e-2",
            n=2,
            size="512x512"
        )
        
        # Verify the request was made with correct payload
        call_args = mock_request.call_args
        self.assertIn("dall-e-2", str(call_args))
        self.assertIn("512x512", str(call_args))
    
    @patch('oo.client.requests.Session.request')
    def test_image_convenience_function(self, mock_request):
        """Test the image convenience function."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": [{"url": "https://example.com/img.png"}]
        }
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = oo.image("test_token", prompt="A sunset")
        
        self.assertIn("data", result)


class TestHealth(unittest.TestCase):
    """Test cases for health check functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client(base_url="http://localhost:3001")
    
    def tearDown(self):
        """Clean up after tests."""
        self.client.close()
    
    @patch('oo.client.requests.Session.request')
    def test_health_success(self, mock_request):
        """Test successful health check."""
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = self.client.health()
        
        self.assertTrue(result)
        mock_request.assert_called_once()
        # Verify it called the /health endpoint
        call_args = mock_request.call_args
        self.assertIn("/health", str(call_args))
    
    @patch('oo.client.requests.Session.request')
    def test_health_failure(self, mock_request):
        """Test health check when service is down."""
        import requests
        mock_request.side_effect = requests.exceptions.ConnectionError("Service unavailable")
        
        with self.assertRaises(oo.ProxyError):
            self.client.health()
    
    @patch('oo.client.requests.Session.request')
    def test_health_convenience_function(self, mock_request):
        """Test the health convenience function."""
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response
        
        result = oo.health()
        
        self.assertTrue(result)


class TestConvenienceEnvFunctions(unittest.TestCase):
    """Test module-level get_env and load_env convenience functions."""

    def tearDown(self):
        oo.invalidate_cache()
        import os
        os.environ.pop("CONV_KEY", None)

    @patch('oo.client.requests.Session.request')
    def test_get_env_function(self, mock_request):
        """Test the get_env convenience function."""
        mock_response = Mock()
        mock_response.json.return_value = {"secrets": {"CONV_KEY": "conv_val"}}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        result = oo.get_env("my_token")
        self.assertEqual(result, {"CONV_KEY": "conv_val"})

    @patch('oo.client.requests.Session.request')
    def test_load_env_function(self, mock_request):
        """Test the load_env convenience function."""
        import os
        mock_response = Mock()
        mock_response.json.return_value = {"secrets": {"CONV_KEY": "conv_val"}}
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        result = oo.load_env("my_token")
        self.assertEqual(result, {"CONV_KEY": "conv_val"})
        self.assertEqual(os.environ["CONV_KEY"], "conv_val")


if __name__ == "__main__":
    unittest.main()
