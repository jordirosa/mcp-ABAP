from fastmcp import FastMCP
from pydantic import Field

from connection.connection import *

mcp = FastMCP(name="ABAP Tools - MCP Server", version="1.0.0")
print("FastMCP server object created.")

#region Login/Logout
@mcp.tool()
def login() -> LoginResponse:
    """Perform login to SAP server and fetch CSRF token.

    Required action to start working with other tools."""
    return call_login()

@mcp.tool()
def logout() -> LogoutResponse:
    """Perform logout from SAP server and clear CSRF token."""
    return call_logout()
#endregion

if __name__ == "__main__":
    print("\n--- Initiating FastMCP server through __main__ ---")
    mcp.run()
