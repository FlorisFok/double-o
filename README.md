# Double-O

A Python library for secret management and API proxy calls.

## Installation

```bash
pip install double-o
```

## Quick Start

### Fetching Secrets

```python
import oo

# Simple one-liner to fetch a secret
secret = oo.get_secret("YOUR_TOKEN_HERE")
print(f"Secret: {secret}")
```

### Making Proxy API Calls

```python
import oo

# Make an API call through the proxy
result = oo.proxy(
    "v1/chat/completions",
    token="YOUR_PROXY_TOKEN",
    payload={
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Hello!"}]
    }
)
print(result)
```

### Chat Completions (Convenience Method)

```python
import oo

# Even simpler for chat completions
result = oo.chat(
    token="YOUR_PROXY_TOKEN",
    messages=[{"role": "user", "content": "Hello!"}],
    model="gpt-4o-mini"
)
print(result)
```

## Advanced Usage

### Using the Client Class

For more control, use the `Client` class directly:

```python
from oo import Client

# Create a client with custom settings
client = Client(
    base_url="http://localhost:3001",
    timeout=60
)

# Fetch a secret
secret = client.get_secret("YOUR_TOKEN")

# Make proxy calls
result = client.proxy(
    "v1/chat/completions",
    token="YOUR_PROXY_TOKEN",
    payload={"model": "gpt-4o-mini", "messages": []}
)

# Don't forget to close when done
client.close()
```

### Context Manager

The client supports context managers for automatic cleanup:

```python
from oo import Client

with Client(base_url="http://localhost:3001") as client:
    secret = client.get_secret("YOUR_TOKEN")
    # Client is automatically closed when exiting the block
```

### Custom Base URL

All functions accept a `base_url` parameter:

```python
import oo

# Use a different server
secret = oo.get_secret(
    "YOUR_TOKEN",
    base_url="http://your-server:8080"
)
```

## Error Handling

The library provides custom exceptions for different error scenarios:

```python
import oo
from oo import SecretError, ProxyError, AuthenticationError

try:
    secret = oo.get_secret("invalid_token")
except AuthenticationError as e:
    print(f"Authentication failed: {e}")
except SecretError as e:
    print(f"Failed to fetch secret: {e}")

try:
    result = oo.proxy("v1/endpoint", "invalid_token", payload={})
except AuthenticationError as e:
    print(f"Proxy authentication failed: {e}")
except ProxyError as e:
    print(f"Proxy request failed: {e}")
```

### Exception Hierarchy

- `DoubleOError` - Base exception for all Double-O errors
  - `SecretError` - Raised when fetching a secret fails
  - `ProxyError` - Raised when a proxy request fails
  - `AuthenticationError` - Raised when authentication fails

## API Reference

### Functions

#### `oo.get_secret(token, base_url="http://localhost:3001")`

Fetch a secret value using a token.

- **token** (str): The authentication token
- **base_url** (str): API server URL (default: http://localhost:3001)
- **Returns**: The secret value as a string
- **Raises**: `SecretError`, `AuthenticationError`

#### `oo.proxy(path, token, method="POST", payload=None, headers=None, base_url="http://localhost:3001")`

Make an API call through the proxy.

- **path** (str): API path (e.g., 'v1/chat/completions')
- **token** (str): Proxy authentication token
- **method** (str): HTTP method (default: POST)
- **payload** (dict): Request payload (optional)
- **headers** (dict): Additional headers (optional)
- **base_url** (str): API server URL (default: http://localhost:3001)
- **Returns**: JSON response as a dictionary
- **Raises**: `ProxyError`, `AuthenticationError`

#### `oo.chat(token, messages, model="gpt-4o-mini", base_url="http://localhost:3001", **kwargs)`

Convenience function for OpenAI chat completions.

- **token** (str): Proxy authentication token
- **messages** (list): List of message dicts with 'role' and 'content'
- **model** (str): Model to use (default: gpt-4o-mini)
- **base_url** (str): API server URL (default: http://localhost:3001)
- **kwargs**: Additional parameters for the API
- **Returns**: Chat completion response

### Client Class

#### `Client(base_url="http://localhost:3001", timeout=30)`

Create a new Double-O client.

- **base_url** (str): API server URL
- **timeout** (int): Request timeout in seconds

**Methods:**

- `get_secret(token)` - Fetch a secret
- `proxy(path, token, method="POST", payload=None, headers=None)` - Make proxy call
- `chat_completion(token, messages, model="gpt-4o-mini", **kwargs)` - Chat completion
- `close()` - Close the client session

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/double-o.git
cd double-o

# Install development dependencies
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest
```

### Code Formatting

```bash
black oo tests
isort oo tests
```

### Type Checking

```bash
mypy oo
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
