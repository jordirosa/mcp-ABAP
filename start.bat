@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if "%ABAP_MCP_PORT%"=="" set "ABAP_MCP_PORT=8081"
if "%ABAP_MCP_HOST%"=="" set "ABAP_MCP_HOST=127.0.0.1"
if "%ABAP_MCP_PATH%"=="" set "ABAP_MCP_PATH=/mcp/abap"
if "%ABAP_MCP_LOG_LEVEL%"=="" set "ABAP_MCP_LOG_LEVEL=info"

python server.py --transport http --host %ABAP_MCP_HOST% --port %ABAP_MCP_PORT% --path %ABAP_MCP_PATH% --log-level %ABAP_MCP_LOG_LEVEL%
