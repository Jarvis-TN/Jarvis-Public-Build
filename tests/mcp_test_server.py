"""A tiny stdio MCP server used only to test Jarvis's MCP client end-to-end.
Exposes one tool, `ping`, that echoes its message back. Run automatically by
test_mcp.py via stdio."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("jarvis-test")


@mcp.tool()
def ping(message: str = "hi") -> str:
    """Echo the message back, prefixed with pong."""
    return f"pong: {message}"


if __name__ == "__main__":
    mcp.run()
