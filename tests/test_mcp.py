"""End-to-end test of Jarvis's MCP client against a real (in-repo) MCP server.

Launches tests/mcp_test_server.py over stdio, connects via jarvis_mcp.MCPManager,
verifies tool discovery (namespaced), tool invocation, and the engine's routing
helpers. Proves the async->sync bridge works.

Run:  .venv\\Scripts\\python.exe tests\\test_mcp.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import jarvis_mcp


def _server_cfg():
    return [{
        "name": "test",
        "command": sys.executable,                       # this venv's python
        "args": [os.path.join(HERE, "mcp_test_server.py")],
    }]


def test_is_mcp_tool():
    assert jarvis_mcp.is_mcp_tool("mcp__test__ping")
    assert not jarvis_mcp.is_mcp_tool("get_weather")


def test_connect_list_and_call():
    mgr = jarvis_mcp.MCPManager(_server_cfg(), status_cb=lambda m: None)
    mgr.start(per_server_timeout=40)
    try:
        names = [t["name"] for t in mgr.tools()]
        assert "mcp__test__ping" in names, names
        # schema carried through
        ping = next(t for t in mgr.tools() if t["name"] == "mcp__test__ping")
        assert ping["input_schema"].get("type") == "object"
        # invoke it
        out = mgr.call("mcp__test__ping", {"message": "jarvis"})
        assert "pong: jarvis" in out, out
        # unknown server degrades gracefully
        assert "not connected" in mgr.call("mcp__nope__x", {})
    finally:
        mgr.stop()


def test_engine_routing_helpers():
    # _dispatch_tool / _all_tools without booting the full engine
    import jarvis
    import jarvis_tools
    eng = jarvis.JarvisEngine.__new__(jarvis.JarvisEngine)
    eng.cfg = {"mcp_enabled": True, "mcp_servers": _server_cfg()}
    eng.mcp = None
    eng.status_cb = lambda m: None
    eng.transcript_cb = lambda *a: None
    try:
        allt = eng._all_tools()
        names = [t["name"] for t in allt]
        assert "mcp__test__ping" in names
        assert any(t["name"] == "get_weather" for t in allt)   # native tools still present
        # routes an MCP tool to the manager, native tool to dispatch
        assert "pong: routed" in eng._dispatch_tool("mcp__test__ping", {"message": "routed"})
    finally:
        if getattr(eng, "mcp", None):
            eng.mcp.stop()


def _run():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
