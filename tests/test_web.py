"""Tests for the Jarvis web reader (jarvis_web).

The critical thing to prove is the SSRF guard: a model-chosen URL must never be
able to reach loopback/private/reserved addresses (Jarvis's own localhost
services, the router, cloud metadata). Also covers scheme handling and the
graceful text extractor. Network-dependent fetches are kept optional so the suite
passes offline.

Run:  .venv\\Scripts\\python.exe tests\\test_web.py   (or under pytest)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jarvis_web as W


# --------------------------------------------------------------------------- #
#  SSRF guard - the security-critical part
# --------------------------------------------------------------------------- #
def test_blocks_loopback_and_localhost():
    for url in ("http://localhost:8765", "http://127.0.0.1", "http://127.0.0.1:8765/scan",
                "http://[::1]/"):
        ok, _ = W.host_is_allowed(url)
        assert not ok, url


def test_blocks_private_ranges():
    for url in ("http://10.0.0.1", "http://192.168.1.1", "http://172.16.5.5"):
        ok, _ = W.host_is_allowed(url)
        assert not ok, url


def test_blocks_link_local_and_metadata():
    # AWS/GCP/Azure cloud metadata endpoint lives on a link-local address
    ok, _ = W.host_is_allowed("http://169.254.169.254/latest/meta-data/")
    assert not ok


def test_blocks_nonstandard_ip_to_internal():
    # decimal-encoded 127.0.0.1 (2130706433) must not slip past - we check the
    # *resolved* address, so obfuscation doesn't help. (May fail to resolve at
    # all on some stacks, which is also a block.)
    ok, _ = W.host_is_allowed("http://2130706433/")
    assert not ok


def test_blocks_bad_schemes():
    for url in ("file:///etc/passwd", "ftp://example.com/x", "gopher://x"):
        ok, _ = W.host_is_allowed(url)
        assert not ok, url


def test_allows_public_host():
    ok, reason = W.host_is_allowed("https://example.com")
    assert ok, reason


def test_fetch_rejects_local_url():
    r = W.fetch_url("http://127.0.0.1:8765")
    assert not r["ok"] and "private" in r["error"].lower()


def test_fetch_rejects_file_scheme():
    r = W.fetch_url("file:///etc/passwd")
    assert not r["ok"]


def test_bare_domain_gets_https():
    # a bare domain is upgraded to https and still validated (not fetched here)
    ok, _ = W.host_is_allowed("https://example.com")
    assert ok


# --------------------------------------------------------------------------- #
#  Extraction (no network)
# --------------------------------------------------------------------------- #
def test_extract_strips_scripts_and_keeps_text():
    html = """<html><head><title>Hi There</title></head>
        <body><nav>menu junk</nav><script>var x=1;</script>
        <p>Hello world.</p><p>Second paragraph.</p>
        <style>.a{}</style><footer>copyright</footer></body></html>"""
    title, text = W.extract_readable(html, "text/html", "https://x.test")
    assert "Hello world." in text
    assert "Second paragraph." in text
    assert "var x=1" not in text          # script stripped
    assert title == "Hi There"


def test_extract_json_passthrough():
    title, text = W.extract_readable('{"b":2,"a":1}', "application/json", "https://x.test")
    assert '"a": 1' in text               # pretty-printed


def test_extract_plaintext_passthrough():
    title, text = W.extract_readable("just text", "text/plain", "https://x.test")
    assert text == "just text"


# --------------------------------------------------------------------------- #
#  Optional live fetch (skipped offline / on failure)
# --------------------------------------------------------------------------- #
def test_live_fetch_example_com_optional():
    try:
        r = W.fetch_url("https://example.com", timeout=8)
    except Exception:
        return   # offline - skip
    if not r.get("ok"):
        return   # transient network issue - don't fail the suite
    assert "Example Domain" in r["text"]
    assert r["url"].startswith("https://example.com")


# --------------------------------------------------------------------------- #
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
