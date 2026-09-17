"""Test MCP (Model Context Protocol) Client & Manager."""
import json
import sys
from pathlib import Path
import pytest

from owibot.mcp import MCPManager, MCPStdioClient


# Script pembantu untuk mensimulasikan server MCP stdio sederhana
MOCK_SERVER_SCRIPT = """
import sys
import json

while True:
    line = sys.stdin.readline()
    if not line:
        break
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except:
        continue

    method = req.get("method")
    msg_id = req.get("id")

    if method == "initialize":
        resp = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mock-mcp-server", "version": "1.0.0"}
            }
        }
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
    elif method == "tools/list":
        resp = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tools": [
                    {
                        "name": "calculate_sum",
                        "description": "Menjumlahkan dua angka",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "a": {"type": "number"},
                                "b": {"type": "number"}
                            },
                            "required": ["a", "b"]
                        }
                    }
                ]
            }
        }
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
    elif method == "tools/call":
        params = req.get("params", {})
        args = params.get("arguments", {})
        total = args.get("a", 0) + args.get("b", 0)
        resp = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": f"Hasil: {total}"}]
            }
        }
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
"""


@pytest.fixture
def mock_mcp_script_file(tmp_path):
    script_path = tmp_path / "mock_mcp_server.py"
    script_path.write_text(MOCK_SERVER_SCRIPT, encoding="utf-8")
    return script_path


def test_mcp_client_handshake_and_tool_call(mock_mcp_script_file):
    client = MCPStdioClient(
        server_name="math",
        command=sys.executable,
        args=[str(mock_mcp_script_file)],
        timeout_s=5.0,
    )
    try:
        client.start()
        init_res = client.initialize()
        assert init_res.get("protocolVersion") == "2024-11-05"

        tools = client.list_tools()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "mcp__math__calculate_sum"

        result = client.call_tool("calculate_sum", {"a": 10, "b": 32})
        assert "Hasil: 42" in result
    finally:
        client.close()


def test_mcp_manager_integration(mock_mcp_script_file):
    manager = MCPManager()
    config = {
        "mcp_servers": {
            "math": {
                "command": sys.executable,
                "args": [str(mock_mcp_script_file)],
            }
        }
    }
    try:
        manager.load_from_config(config)
        tools = manager.refresh_tools()
        assert len(tools) == 1
        tool_name = tools[0]["function"]["name"]
        assert manager.is_mcp_tool(tool_name)

        output = manager.dispatch(tool_name, {"a": 25, "b": 75})
        assert "Hasil: 100" in output
    finally:
        manager.close_all()
