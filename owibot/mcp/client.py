from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from typing import Any, Optional

logger = logging.getLogger("owibot.mcp")


class MCPError(Exception):
    pass


class MCPStdioClient:
    def __init__(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_s: float = 30.0,
    ):
        self.server_name = server_name
        self.command = command
        self.args = args or []
        self.env = env
        self.cwd = cwd
        self.timeout_s = timeout_s

        self.process: subprocess.Popen | None = None
        self._next_id = 1
        self._lock = threading.Lock()
        self._pending_requests: dict[int, Any] = {}
        self._read_thread: threading.Thread | None = None
        self._is_active = False

    def start(self) -> None:
        merged_env = os.environ.copy()
        if self.env:
            merged_env.update(self.env)

        full_cmd = [self.command] + self.args
        try:
            self.process = subprocess.Popen(
                full_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=merged_env,
                cwd=self.cwd,
                bufsize=1,
            )
            self._is_active = True
        except FileNotFoundError as err:
            raise MCPError(f"Server command '{self.command}' tidak ditemukan.") from err
        except Exception as err:
            raise MCPError(f"Gagal menjalankan server MCP '{self.server_name}': {err}") from err

        self._read_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._read_thread.start()

    def _reader_loop(self) -> None:
        while self._is_active and self.process and self.process.stdout:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue

                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_id = payload.get("id")
                if msg_id is not None and msg_id in self._pending_requests:
                    event, result_box = self._pending_requests[msg_id]
                    result_box.append(payload)
                    event.set()

            except Exception as err:
                logger.warning("Error reading from MCP server %s: %s", self.server_name, err)
                break

    def send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._is_active or not self.process or not self.process.stdin:
            raise MCPError(f"Server MCP '{self.server_name}' tidak aktif.")

        with self._lock:
            msg_id = self._next_id
            self._next_id += 1

        request_body = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
        }
        if params is not None:
            request_body["params"] = params

        event = threading.Event()
        result_box: list[dict] = []
        self._pending_requests[msg_id] = (event, result_box)

        serialized = json.dumps(request_body, ensure_ascii=False) + "\n"
        try:
            self.process.stdin.write(serialized)
            self.process.stdin.flush()
        except Exception as err:
            self._pending_requests.pop(msg_id, None)
            raise MCPError(f"Gagal menulis ke server MCP '{self.server_name}': {err}") from err

        signaled = event.wait(timeout=self.timeout_s)
        self._pending_requests.pop(msg_id, None)

        if not signaled or not result_box:
            raise MCPError(f"Timeout menunggu respons MCP '{self.server_name}' untuk method '{method}'.")

        response = result_box[0]
        if "error" in response:
            err_data = response["error"]
            raise MCPError(f"Error MCP [{err_data.get('code')}]: {err_data.get('message')}")

        return response.get("result", {})

    def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        if not self._is_active or not self.process or not self.process.stdin:
            return

        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params

        serialized = json.dumps(body, ensure_ascii=False) + "\n"
        try:
            self.process.stdin.write(serialized)
            self.process.stdin.flush()
        except Exception:
            pass

    def initialize(self) -> dict[str, Any]:
        """Melakukan handshake inisialisasi protokol MCP."""
        init_result = self.send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "owibot", "version": "0.6.0"},
            },
        )
        self.send_notification("notifications/initialized")
        return init_result

    def list_tools(self) -> list[dict[str, Any]]:
        """Mengambil daftar tool dari MCP server dan mengubahnya ke schema OpenAI function."""
        result = self.send_request("tools/list")
        raw_tools = result.get("tools", [])

        schema_tools = []
        for tool in raw_tools:
            raw_name = tool.get("name", "")
            prefixed_name = f"mcp__{self.server_name}__{raw_name}"
            description = f"[MCP {self.server_name}] {tool.get('description', '')}".strip()
            input_schema = tool.get("inputSchema", {"type": "object", "properties": {}})

            schema_tools.append({
                "type": "function",
                "function": {
                    "name": prefixed_name,
                    "description": description,
                    "parameters": input_schema,
                },
                "_mcp_server": self.server_name,
                "_mcp_raw_name": raw_name,
            })

        return schema_tools

    def call_tool(self, tool_raw_name: str, arguments: dict[str, Any]) -> str:
        """Mengeksekusi tool pada server MCP dan mengembalikan konten respons."""
        result = self.send_request(
            "tools/call",
            {"name": tool_raw_name, "arguments": arguments},
        )
        content_items = result.get("content", [])

        text_outputs = []
        for item in content_items:
            if isinstance(item, dict) and item.get("type") == "text":
                text_outputs.append(item.get("text", ""))

        if text_outputs:
            return "\n".join(text_outputs)
        return json.dumps(result, ensure_ascii=False)

    def close(self) -> None:
        self._is_active = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
