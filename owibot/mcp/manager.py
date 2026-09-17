from __future__ import annotations

import logging
from typing import Any

from .client import MCPError, MCPStdioClient

logger = logging.getLogger("owibot.mcp")


class MCPManager:
    def __init__(self):
        self.clients: dict[str, MCPStdioClient] = {}
        self.cached_tools: list[dict[str, Any]] = []
        self._tool_routing: dict[str, tuple[str, str]] = {}  # prefixed_name -> (server_name, raw_name)

    def register_server(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> bool:
        try:
            client = MCPStdioClient(
                server_name=name,
                command=command,
                args=args,
                env=env,
                cwd=cwd,
            )
            client.start()
            client.initialize()
            self.clients[name] = client
            logger.info("Berhasil menghubungkan MCP server '%s'", name)
            return True
        except Exception as exc:
            logger.warning("Gagal menghubungkan MCP server '%s': %s", name, exc)
            return False

    def load_from_config(self, config: dict, cwd: str | None = None) -> None:
        servers_config = config.get("mcp_servers", {})
        if not isinstance(servers_config, dict):
            return

        for name, spec in servers_config.items():
            if not isinstance(spec, dict) or not spec.get("command"):
                continue
            self.register_server(
                name=str(name),
                command=str(spec["command"]),
                args=spec.get("args"),
                env=spec.get("env"),
                cwd=cwd,
            )

        self.refresh_tools()

    def refresh_tools(self) -> list[dict[str, Any]]:
        aggregated: list[dict[str, Any]] = []
        routing: dict[str, tuple[str, str]] = {}

        for server_name, client in self.clients.items():
            try:
                server_tools = client.list_tools()
                for tool in server_tools:
                    tool_func = tool.get("function", {})
                    p_name = tool_func.get("name", "")
                    raw_name = tool.get("_mcp_raw_name", "")
                    if p_name and raw_name:
                        routing[p_name] = (server_name, raw_name)
                    aggregated.append(tool)
            except Exception as exc:
                logger.warning("Gagal mengambil tool dari MCP server '%s': %s", server_name, exc)

        self.cached_tools = aggregated
        self._tool_routing = routing
        return aggregated

    def is_mcp_tool(self, name: str) -> bool:
        return name in self._tool_routing

    def dispatch(self, prefixed_name: str, arguments: dict[str, Any]) -> str:
        route = self._tool_routing.get(prefixed_name)
        if not route:
            return f"ERROR: Tool MCP '{prefixed_name}' tidak terdaftar."

        server_name, raw_name = route
        client = self.clients.get(server_name)
        if not client:
            return f"ERROR: Server MCP '{server_name}' tidak aktif."

        try:
            return client.call_tool(raw_name, arguments)
        except Exception as exc:
            return f"ERROR [MCP {server_name}]: {exc}"

    def close_all(self) -> None:
        for client in self.clients.values():
            try:
                client.close()
            except Exception:
                pass
        self.clients.clear()
        self.cached_tools.clear()
        self._tool_routing.clear()
