# Jarvis Internet Integration

Reading the live web.

## 1. Browse & read web pages (`jarvis_web.py`)

Jarvis can open a specific URL and read its real content — going beyond the short
snippets `web_search` returns.

- **Tool:** `read_webpage(url)` — "read this link", "what does this page say", or
  after a `web_search` when the full article is needed to answer accurately.
- **Extraction** degrades gracefully: `trafilatura` (best) → `BeautifulSoup` →
  a stdlib HTML stripper, so it works even with no optional deps.
- **Config:** `web_read_max_chars` (default 6000) caps how much page text is
  handed to the model.

### Security — SSRF guard (the important part)

A tool that fetches a model-chosen URL is the classic *server-side request
forgery* vector: untrusted content (search results, RAG docs, emails) could steer
Jarvis into fetching `http://127.0.0.1:8765` (his own HUD control bridge), the
router admin page, or cloud-metadata endpoints. So `jarvis_web`:

- allows only `http`/`https`;
- **resolves the host and blocks any loopback / private / link-local / reserved /
  multicast address** — this defeats DNS rebinding and decimal/hex IP obfuscation
  because the *resolved* IP is what's checked;
- **follows redirects manually, re-validating the host at every hop** (a public
  URL can't bounce you to an internal one);
- caps response **size** (2 MB), **time** (12 s), and **content-type** (text/HTML/
  JSON only — no binaries).

Covered by `tests/test_web.py` (13 tests).

## Dependencies

`requests` + `beautifulsoup4` (web reader; `trafilatura` optional for better
extraction).
