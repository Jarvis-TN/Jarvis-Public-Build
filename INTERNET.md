# Jarvis Internet Integration

Two capabilities: **reading the live web**, and **reaching Jarvis from anywhere**.

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

## 2. Reach Jarvis remotely (`jarvis_remote.py`)

The phone bridge (`jarvis_phone.py`) normally binds only the LAN. Remote access
puts a free **Cloudflare quick tunnel** (`cloudflared`) in front of it, giving a
public `https://<random>.trycloudflare.com` URL reachable from anywhere — no
router port-forwarding, no account, no inbound firewall holes (cloudflared dials
*out* to Cloudflare, which proxies traffic back).

- **Enable:** `remote_access_enabled: true` in `config.json`, then launch Jarvis.
  On start he brings the phone bridge up, downloads `cloudflared` once into
  `./bin`, opens the tunnel, and announces the public link.
- **Tool:** `get_remote_link` — "how do I reach you remotely?" puts a QR + the URL
  on the display.
- **Config:** `remote_access_enabled` (false by default), `remote_access_provider`
  (`cloudflare`).

### Stable hostname — named tunnel (optional upgrade)

The quick tunnel's URL changes every run. For a permanent address like
`jarvis.yourdomain.com`, use a **named tunnel**. Requirement: a **domain on your
Cloudflare account** (the account alone doesn't grant a fixed hostname).

One-time setup in the Cloudflare **Zero Trust** dashboard:

1. **Networks → Tunnels → Create a tunnel** → *Cloudflared* → name it (e.g. `jarvis`).
2. On the install screen, copy the **connector token** (the long string after
   `--token` in the shown command). You do **not** need to run the command
   yourself — Jarvis runs the connector.
3. **Public Hostname → Add**: choose a subdomain (e.g. `jarvis`) on your domain,
   **Service = HTTP**, **URL = `localhost:8770`** (your `phone_bridge_port`).
4. Put these in `config.json` and restart Jarvis:
   ```json
   "remote_access_enabled": true,
   "remote_access_provider": "cloudflare-named",
   "cloudflare_tunnel_token": "<the connector token>",
   "cloudflare_hostname": "jarvis.yourdomain.com"
   ```

Jarvis (or `serve_remote.py`) then runs `cloudflared tunnel run --token …` and
your phone link is always `https://jarvis.yourdomain.com/phone.html?token=…`.

No domain yet? Either register one (Cloudflare Registrar sells at cost, ~$10/yr)
and add it to your account, or stick with the free quick tunnel
(`remote_access_provider: cloudflare`).

### Security posture (internet-facing — read this)

- **Only the phone port is tunnelled.** The HUD WebSocket bridge (which can
  trigger Claude turns and control the PC) is **never** exposed.
- The expensive endpoint (`/scan` → a Claude vision call) is **token-gated**, and
  when remote access is on the token is auto-upgraded to a **strong 16-byte
  secret**. The page-serving GET routes are static files only (no secrets).
- The trycloudflare URL is **random and ephemeral** — a fresh one each run.
- **Treat the link + token like a password.** This is right-sized for a
  single-user personal assistant, not hardened multi-user infrastructure. To shut
  it off: set `remote_access_enabled: false` and restart.

Tunnel-URL parsing covered by `tests/test_remote.py`.

## Dependencies

`requests` + `beautifulsoup4` (web reader; `trafilatura` optional for better
extraction). `cloudflared` is a single static binary auto-downloaded to `./bin`
(not a pip package). `.gitignore` already excludes `bin/`-style binaries — keep
the binary and any tokens off shared media.
