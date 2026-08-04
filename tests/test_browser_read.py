"""Tests for read_browser_page: reads the live Playwright page via the MCP tools,
falling back from browser_evaluate to browser_snapshot.
Run: .venv\\Scripts\\python.exe tests\\test_browser_read.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jarvis_tools as tools

_passed = _failed = 0


def check(name, fn):
    global _passed, _failed
    try:
        fn()
        print(f"  PASS  {name}")
        _passed += 1
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        _failed += 1


class FakeMCP:
    def __init__(self, responses):
        self.responses = responses         # tool_name -> str or Exception
        self.calls = []

    def call(self, name, args, timeout=120):
        self.calls.append((name, args))
        r = self.responses.get(name, "")
        if isinstance(r, Exception):
            raise r
        return r


class FakeEngine:
    def __init__(self, mcp):
        self._mcp = mcp

    def _get_mcp(self):
        return self._mcp


def test_registered():
    assert "read_browser_page" in [t["name"] for t in tools.TOOLS]


def test_reads_via_evaluate():
    mcp = FakeMCP({"mcp__playwright__browser_evaluate": "TITLE: Example\n\nHello world body"})
    out = tools.dispatch("read_browser_page", {}, FakeEngine(mcp))
    assert "Hello world body" in out
    assert mcp.calls and mcp.calls[0][0] == "mcp__playwright__browser_evaluate"


def test_falls_back_to_snapshot_on_error():
    mcp = FakeMCP({
        "mcp__playwright__browser_evaluate": "(MCP tool 'browser_evaluate' failed: nope)",
        "mcp__playwright__browser_snapshot": "- heading: Page\n- text: snapshot content"})
    out = tools._read_browser_page(FakeEngine(mcp))
    assert "snapshot content" in out
    assert any(c[0].endswith("browser_snapshot") for c in mcp.calls)


def test_falls_back_when_evaluate_raises():
    mcp = FakeMCP({
        "mcp__playwright__browser_evaluate": RuntimeError("boom"),
        "mcp__playwright__browser_snapshot": "snapshot fallback text"})
    out = tools._read_browser_page(FakeEngine(mcp))
    assert "snapshot fallback text" in out


def test_no_mcp_connected():
    class NoMCP:
        def _get_mcp(self):
            return None
    out = tools._read_browser_page(NoMCP())
    assert "isn't connected" in out


def test_both_unavailable():
    mcp = FakeMCP({
        "mcp__playwright__browser_evaluate": "(failed)",
        "mcp__playwright__browser_snapshot": "(also failed)"})
    out = tools._read_browser_page(FakeEngine(mcp))
    assert "couldn't read the page" in out


def test_truncation():
    mcp = FakeMCP({"mcp__playwright__browser_evaluate": "x" * 40000})
    out = tools._read_browser_page(FakeEngine(mcp), max_chars=18000)
    assert "[...page truncated...]" in out and len(out) < 20000


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    total = _passed + _failed
    print(f"\n{_passed} passed, {_failed} failed, {total} total")
    sys.exit(1 if _failed else 0)
