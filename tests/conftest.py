import os

# Must be set before server.py is imported (module-level globals read env at import time).
os.environ.setdefault("VAULT_PATH", "/tmp/vault-test")
os.environ.setdefault("DEX_ISSUER", "https://dex.example.com")
os.environ.setdefault("MCP_CLIENT_ID", "test-client")
os.environ.setdefault("MCP_BASE_URL", "http://localhost:8000")
