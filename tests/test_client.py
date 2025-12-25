"""Tests for the Double-O client module."""

import json
import unittest
from unittest.mock import Mock, patch

import oo
from oo import Client, SecretError, ProxyError, AuthenticationError


class TestClient(unittest.TestCase):
    """Test cases for the Client class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = Client(base_url="http://localhost:3001")
    
    def tearDown(self):
        """Clean up after tests."""
        self.client.close()
    
    @patch('oo.client.requests.Session.get')
    def test_get_secret_success(self, mock_get):
        """Test successful secret retrieval."""
        mock_response = Mock()
        mock_response.json.return_value = {"value": "my_secret_value"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        result = self.client.get_secret("test_token")
        
        self.assertEqual(result, "my_secret_value")
        mock_get.assert_called_once()
    
    @patch('oo.client.requests.Session.get')
    def test_get_secret_error(self, mock_get):
        """Test secret retrieval with error response."""
        mock_response = Mock()
        mock_response.json.return_value = {"error": "Invalid token"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
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


class TestConvenienceFunctions(unittest.TestCase):
    """Test cases for module-level convenience functions."""
    
    @patch('oo.client.requests.Session.get')
    def test_get_secret_function(self, mock_get):
        """Test the get_secret convenience function."""
        mock_response = Mock()
        mock_response.json.return_value = {"value": "secret123"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        result = oo.get_secret("my_token")
        
        self.assertEqual(result, "secret123")
    
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
