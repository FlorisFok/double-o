# Double-O

A Python library for secret management and API proxy calls.

## Installation

```bash
pip install double-o
```

### Optional Dependencies

```bash
# For async support (AsyncClient with aiohttp)
pip install double-o[async]

# For retry with backoff (using tenacity)
pip install double-o[retry]

# Install all optional dependencies
pip install double-o[all]
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

## Features

### Secret Caching with TTL

Reduce API calls by caching secrets locally with a configurable TTL (time-to-live):

```python
import oo

# Cache the secret for 5 minutes (300 seconds)
secret = oo.get_secret("YOUR_TOKEN", cache_ttl=300)

# Subsequent calls within 5 minutes will use the cached value
secret = oo.get_secret("YOUR_TOKEN", cache_ttl=300)  # No API call!

# Manually invalidate the cache
oo.invalidate_cache("YOUR_TOKEN")  # Invalidate specific token
oo.invalidate_cache()  # Clear all cached secrets
```

### Retry with Backoff

Handle transient failures automatically with exponential backoff:

```python
from oo import Client

# Configure retries when creating the client
client = Client(
    retries=3,           # Retry up to 3 times
    backoff_factor=0.5   # Exponential backoff: 0.5s, 1s, 2s
)

# All requests will automatically retry on transient failures
secret = client.get_secret("YOUR_TOKEN")
```

### Async Support

For async/await applications (FastAPI, asyncio):

```python
import asyncio
from oo import AsyncClient

async def main():
    async with AsyncClient(retries=3, backoff_factor=0.5) as client:
        # Fetch secrets asynchronously
        secret = await client.get_secret("YOUR_TOKEN", cache_ttl=300)
        
        # Make async proxy calls
        result = await client.proxy(
            "v1/chat/completions",
            token="YOUR_PROXY_TOKEN",
            payload={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hello!"}]}
        )
        print(result)

asyncio.run(main())
```

#### FastAPI Example

```python
from fastapi import FastAPI
from oo import AsyncClient

app = FastAPI()
client = AsyncClient(retries=3, backoff_factor=0.5)

@app.on_event("shutdown")
async def shutdown():
    await client.close()

@app.get("/secret/{token}")
async def get_secret(token: str):
    secret = await client.get_secret(token, cache_ttl=300)
    return {"secret": secret}
```

## Advanced Usage

### Using the Client Class

For more control, use the `Client` class directly:

```python
from oo import Client

# Create a client with custom settings
client = Client(
    base_url="http://localhost:3001",
    timeout=60,
    retries=3,
    backoff_factor=0.5
)

# Fetch a secret with caching
secret = client.get_secret("YOUR_TOKEN", cache_ttl=300)

# Make proxy calls
result = client.proxy(
    "v1/chat/completions",
    token="YOUR_PROXY_TOKEN",
    payload={"model": "gpt-4o-mini", "messages": []}
)

# Invalidate cache when needed
client.invalidate_cache("YOUR_TOKEN")

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
  - `EnvError` - Raised when fetching environment variables fails

## API Reference

### Functions

#### `oo.get_secret(token, base_url=..., cache_ttl=None)`

Fetch a secret value using a token.

- **token** (str): The authentication token
- **base_url** (str): API server URL
- **cache_ttl** (float, optional): TTL in seconds to cache the secret
- **Returns**: The secret value as a string
- **Raises**: `SecretError`, `AuthenticationError`

#### `oo.proxy(path, token, method="POST", payload=None, headers=None, base_url=...)`

Make an API call through the proxy.

- **path** (str): API path (e.g., 'v1/chat/completions')
- **token** (str): Proxy authentication token
- **method** (str): HTTP method (default: POST)
- **payload** (dict): Request payload (optional)
- **headers** (dict): Additional headers (optional)
- **base_url** (str): API server URL
- **Returns**: JSON response as a dictionary
- **Raises**: `ProxyError`, `AuthenticationError`

#### `oo.chat(token, messages, model="gpt-4o-mini", base_url=..., **kwargs)`

Convenience function for OpenAI chat completions.

- **token** (str): Proxy authentication token
- **messages** (list): List of message dicts with 'role' and 'content'
- **model** (str): Model to use (default: gpt-4o-mini)
- **base_url** (str): API server URL
- **kwargs**: Additional parameters for the API
- **Returns**: Chat completion response

#### `oo.invalidate_cache(token=None)`

Invalidate cached secrets.

- **token** (str, optional): Specific token to invalidate. If None, clears all cached secrets.

### Client Class

#### `Client(base_url=..., timeout=30, retries=0, backoff_factor=0.5)`

Create a new Double-O client.

- **base_url** (str): API server URL
- **timeout** (int): Request timeout in seconds
- **retries** (int): Number of retry attempts for transient failures (default: 0)
- **backoff_factor** (float): Multiplier for exponential backoff (default: 0.5)

**Methods:**

- `get_secret(token, cache_ttl=None)` - Fetch a secret with optional caching
- `proxy(path, token, method="POST", payload=None, headers=None)` - Make proxy call
- `chat_completion(token, messages, model="gpt-4o-mini", **kwargs)` - Chat completion
- `get_env(token, cache_ttl=None)` - Fetch environment variables
- `load_env(token, cache_ttl=None)` - Fetch and set environment variables in os.environ
- `invalidate_cache(token=None)` - Invalidate cached secrets
- `close()` - Close the client session

### AsyncClient Class

#### `AsyncClient(base_url=..., timeout=30, retries=0, backoff_factor=0.5)`

Create a new async Double-O client. Requires `pip install double-o[async]`.

- **base_url** (str): API server URL
- **timeout** (int): Request timeout in seconds
- **retries** (int): Number of retry attempts for transient failures (default: 0)
- **backoff_factor** (float): Multiplier for exponential backoff (default: 0.5)

**Async Methods:**

- `await get_secret(token, cache_ttl=None)` - Fetch a secret with optional caching
- `await proxy(path, token, method="POST", payload=None, headers=None)` - Make proxy call
- `await chat_completion(token, messages, model="gpt-4o-mini", **kwargs)` - Chat completion
- `await get_env(token, cache_ttl=None)` - Fetch environment variables
- `await load_env(token, cache_ttl=None)` - Fetch and set environment variables
- `await invalidate_cache(token=None)` - Invalidate cached secrets
- `await close()` - Close the client session

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
