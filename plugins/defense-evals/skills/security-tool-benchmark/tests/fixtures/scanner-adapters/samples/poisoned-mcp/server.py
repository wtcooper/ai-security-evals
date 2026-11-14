"""Minimal MCP server exposing two read-only text utilities (benign sample; never executed by the benchmark)."""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("text-utils")


@mcp.tool()
def word_count(text: str) -> int:
    """Count the words in the given text."""
    return len(text.split())


@mcp.tool()
def to_upper(text: str) -> str:
    """Return the given text in upper case."""
    return text.upper()


if __name__ == "__main__":
    mcp.run()
