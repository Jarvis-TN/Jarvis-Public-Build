"""Tests for the remote-access tunnel manager (jarvis_remote).

No network or subprocess here - we test the pure bits: parsing the public URL out
of cloudflared's log stream, and that the QuickTunnel wires its callback. The
actual tunnel is exercised live (see the launch path), not in unit tests.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jarvis_remote as R


def test_url_regex_matches_quick_tunnel_line():
    line = ("2026-06-13T16:00:00Z INF |  https://calm-river-1234-words.trycloudflare.com  |")
    m = R.TUNNEL_RE.search(line)
    assert m and m.group(0) == "https://calm-river-1234-words.trycloudflare.com"


def test_url_regex_ignores_non_tunnel_urls():
    assert R.TUNNEL_RE.search("connecting to https://api.cloudflare.com/foo") is None
    assert R.TUNNEL_RE.search("no url here at all") is None


def test_quick_tunnel_emits_url_via_watch():
    # drive _watch() directly with a fake process whose stdout yields a URL line
    t = R.QuickTunnel("http://127.0.0.1:8770", on_url=lambda u: seen.append(u))
    seen = []

    class _FakeProc:
        stdout = iter([
            "INF Thank you for trying Cloudflare Tunnel.\n",
            "INF Your quick Tunnel has been created! Visit it at:\n",
            "INF https://happy-meadow-42.trycloudflare.com\n",
            "INF Registered tunnel connection\n",
        ])
    t._proc = _FakeProc()
    t._watch()
    assert t.url == "https://happy-meadow-42.trycloudflare.com"
    assert seen == ["https://happy-meadow-42.trycloudflare.com"]


def test_paths_are_sane():
    assert R.CF_PATH.endswith("cloudflared.exe")
    assert "trycloudflare.com" in R.CF_DOWNLOAD or "cloudflared" in R.CF_DOWNLOAD


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
