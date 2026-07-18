import sys
from unittest.mock import MagicMock

# Mock the mcp package so interface.server can be imported without it installed
mock_mcp = MagicMock()
mock_fastmcp = MagicMock()

# FastMCP.tool() should return a decorator that returns the original function
class MockFastMCP:
    def __init__(self, *args, **kwargs):
        pass

    def tool(self):
        def decorator(func):
            return func
        return decorator

    def run(self):
        pass

mock_fastmcp.FastMCP = MockFastMCP
mock_mcp.server = MagicMock()
mock_mcp.server.fastmcp = mock_fastmcp

sys.modules["mcp"] = mock_mcp
sys.modules["mcp.server"] = mock_mcp.server
sys.modules["mcp.server.fastmcp"] = mock_fastmcp
