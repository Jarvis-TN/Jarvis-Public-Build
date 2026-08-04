"""Jarvis MCP client - the integration multiplier.

Connects Jarvis to any number of Model Context Protocol servers (Slack, GitHub,
Notion, Google Drive, filesystem, databases, ...) and exposes THEIR tools to
Jarvis's brain alongside his native tools - with no bespoke code per service. One
integration unlocks the whole MCP ecosystem.

The MCP SDK is async; Jarvis's agentic loop is sync. This manager runs a single
background asyncio loop, keeps each server's session alive on it, and offers sync
`tools()` / `call()` methods the engine can use directly.

Config (config.json):
    "mcp_enabled": true,
    "mcp_servers": [
        {"name": "filesystem", "command": "npx",
         "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users/you/Documents"]},
        {"name": "github", "transport": "http", "url": "https://.../mcp"}
    ]

Tool names are namespaced  mcp__<server>__<tool>  to avoid collisions.
"""

import asyncio
import threading

PREFIX = "mcp__"


def is_mcp_tool(name):
    return isinstance(name, str) and name.startswith(PREFIX)


def _content_to_text(result):
    """Flatten an MCP CallToolResult into a string for the tool_result."""
    try:
        parts = []
        for block in (result.content or []):
            t = getattr(block, "type", None)
            if t == "text":
                parts.append(block.text)
            elif t == "image":
                parts.append("[image returned]")
            else:
                parts.append(str(getattr(block, "text", block)))
        text = "\n".join(p for p in parts if p).strip()
        if getattr(result, "isError", False):
            return f"(tool error) {text}" if text else "(the MCP tool reported an error)"
        return text or "(the tool returned no content)"
    except Exception as e:
        return f"(couldn't read MCP result: {e})"


class MCPManager:
    def __init__(self, servers, status_cb=None):
        self.servers = servers or []
        self.status_cb = status_cb or (lambda m: None)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._sessions = {}     # name -> ClientSession
        self._tools = []        # merged Anthropic-format tool schemas
        self._stops = {}        # name -> asyncio.Event (keep-alive control)

    # ---- public sync API ------------------------------------------------ #
    def start(self, per_server_timeout=30):
        """Connect to every configured server and gather their tools. Blocking
        (waits up to per_server_timeout for each); failures are logged, not fatal."""
        for srv in self.servers:
            name = srv.get("name") or "server"
            ready = threading.Event()
            errbox = {}
            asyncio.run_coroutine_threadsafe(self._serve(srv, ready, errbox), self._loop)
            if not ready.wait(per_server_timeout):
                self.status_cb(f"(MCP '{name}' timed out connecting)")
            elif errbox.get("err"):
                self.status_cb(f"(MCP '{name}' failed: {errbox['err']})")
            else:
                n = sum(1 for t in self._tools if t["name"].startswith(f"{PREFIX}{name}__"))
                self.status_cb(f"MCP '{name}' connected ({n} tools).")

    def tools(self):
        return list(self._tools)

    def call(self, full_name, args, timeout=120):
        rest = full_name[len(PREFIX):]
        server, _, tool = rest.partition("__")
        session = self._sessions.get(server)
        if session is None:
            return f"(MCP server '{server}' is not connected)"
        try:
            fut = asyncio.run_coroutine_threadsafe(
                session.call_tool(tool, args or {}), self._loop)
            return _content_to_text(fut.result(timeout=timeout))
        except Exception as e:
            return f"(MCP tool '{tool}' failed: {e})"

    def stop(self):
        for ev in list(self._stops.values()):
            try:
                self._loop.call_soon_threadsafe(ev.set)
            except Exception:
                pass

    # ---- async internals ------------------------------------------------ #
    async def _open(self, srv):
        """Return an (read, write) transport context manager for the server."""
        transport = (srv.get("transport") or ("http" if srv.get("url") else "stdio")).lower()
        if transport in ("http", "streamable-http", "streamable_http"):
            from mcp.client.streamable_http import streamablehttp_client
            return streamablehttp_client(srv["url"])
        if transport == "sse":
            from mcp.client.sse import sse_client
            return sse_client(srv["url"])
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(
            command=srv["command"], args=srv.get("args", []), env=srv.get("env"))
        return stdio_client(params)

    async def _serve(self, srv, ready, errbox):
        """Long-lived task: connect, register tools, then hold the session open
        until stop() is called."""
        from mcp import ClientSession
        name = srv.get("name") or "server"
        stop = asyncio.Event()
        self._stops[name] = stop
        try:
            transport_cm = await self._open(srv)
            async with transport_cm as streams:
                read, write = streams[0], streams[1]      # 3rd item (if any) ignored
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self._sessions[name] = session
                    for t in listed.tools:
                        self._tools.append({
                            "name": f"{PREFIX}{name}__{t.name}",
                            "description": (t.description or "")[:1000],
                            "input_schema": t.inputSchema or {"type": "object", "properties": {}},
                        })
                    ready.set()
                    await stop.wait()                      # keep the connection alive
        except Exception as e:
            errbox["err"] = str(e)
            ready.set()
        finally:
            self._sessions.pop(name, None)
