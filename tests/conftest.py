import sys
from unittest.mock import MagicMock

# Mock the mcp package so interface.server can be imported without it installed
mock_mcp = MagicMock()
mock_fastmcp = MagicMock()

# FastMCP.tool() should return a decorator that returns the original function
class MockSettings:
    def __init__(self):
        self.port = 8000
        self.host = "127.0.0.1"


class MockFastMCP:
    def __init__(self, *args, **kwargs):
        self.settings = MockSettings()
        self.tools = []

    def tool(self):
        def decorator(func):
            self.tools.append(func.__name__)
            return func
        return decorator

    def run(self, *args, **kwargs):
        pass

mock_fastmcp.FastMCP = MockFastMCP
mock_mcp.server = MagicMock()
mock_mcp.server.fastmcp = mock_fastmcp

sys.modules["mcp"] = mock_mcp
sys.modules["mcp.server"] = mock_mcp.server
sys.modules["mcp.server.fastmcp"] = mock_fastmcp
