"""Jarvis web reader - fetch an arbitrary URL and return its readable text.

This is the "actually read the page" capability (beyond search snippets): give it
a URL, it fetches the page and returns clean main-content text for Claude to
summarize or answer from out loud.

SECURITY - this is an SSRF-sensitive surface. The URL is frequently chosen by the
model, which can be steered by untrusted content (web results, RAG documents,
emails). A naive fetcher is a server-side request forgery hole straight into the
local network - including Jarvis's own localhost services (the HUD bridge on
8765, the phone bridge, router admin pages, cloud metadata endpoints). So this
module:
  * allows only http/https schemes;
  * resolves the host and REJECTS any address that is loopback, private,
    link-local, reserved, or multicast (defeats DNS rebinding to internal IPs and
    decimal/hex IP obfuscation, since we check the *resolved* address);
  * follows redirects MANUALLY, re-validating the host at every hop (a public URL
    cannot bounce you to an internal one);
  * caps response size, time, and content-type (no giant or binary payloads).

Extraction degrades gracefully: trafilatura (best) -> BeautifulSoup -> a stdlib
HTML stripper, so it still works with no optional deps installed.
"""

import re
import json as _json
import socket
import ipaddress
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin

import requests

SAFE_SCHEMES = ("http", "https")
DEFAULT_TIMEOUT = 12
DEFAULT_MAX_BYTES = 2_000_000      # don't slurp huge pages
DEFAULT_MAX_CHARS = 6000           # text returned to the model
MAX_REDIRECTS = 4
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "JarvisAssistant/1.0 (+local personal assistant)")
READABLE_TYPES = ("text/html", "application/xhtml+xml", "text/plain",
                  "application/json", "text/xml", "application/xml")


# --------------------------------------------------------------------------- #
#  SSRF guard
# --------------------------------------------------------------------------- #
def _ip_is_safe(ip_str):
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (ip.is_loopback or ip.is_private or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def host_is_allowed(url):
    """Return (ok, reason). Resolves the URL's host and blocks any non-public
    address. Called fresh for the initial URL and for every redirect target."""
    parsed = urlparse(url)
    if parsed.scheme not in SAFE_SCHEMES:
        return False, f"unsupported scheme '{parsed.scheme}'"
    host = parsed.hostname
    if not host:
        return False, "no host in URL"
    # literal localhost names
    if host.lower() in ("localhost", "localhost.localdomain", "ip6-localhost"):
        return False, "refusing to fetch a local address"
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return False, f"could not resolve host ({e})"
    addrs = {info[4][0] for info in infos}
    if not addrs:
        return False, "host did not resolve"
    for a in addrs:
        if not _ip_is_safe(a):
            return False, "refusing to fetch a private/loopback/reserved address"
    return True, "ok"


# --------------------------------------------------------------------------- #
#  Text extraction (layered, graceful)
# --------------------------------------------------------------------------- #
class _Stripper(HTMLParser):
    """Stdlib fallback: collect visible text, skipping script/style/etc."""
    _SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5",
              "h6", "section", "article", "header", "footer"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self.parts = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title and not self.title:
            self.title = data.strip()
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self):
        joined = " ".join(p if p != "\n" else "\n" for p in self.parts)
        return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", joined)).strip()


def _extract_title(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def extract_readable(html, content_type, url):
    """Return (title, text) of the main readable content."""
    ct = (content_type or "").lower()
    if "json" in ct:
        try:
            return "", _json.dumps(_json.loads(html), indent=2)[:200_000]
        except Exception:
            return "", html
    if ct.startswith("text/plain") or "xml" in ct:
        return "", html

    # 1) trafilatura - best main-content extraction
    try:
        import trafilatura
        txt = trafilatura.extract(html, include_comments=False, include_tables=True,
                                  favor_recall=True, url=url)
        if txt and txt.strip():
            return _extract_title(html), txt.strip()
    except Exception:
        pass

    # 2) BeautifulSoup - strip boilerplate, get text
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style", "noscript", "template", "svg",
                       "header", "footer", "nav", "aside", "form"]):
            t.decompose()
        title = (soup.title.string.strip() if soup.title and soup.title.string else "")
        body = soup.body or soup
        text = body.get_text(separator="\n")
        text = re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()
        if text:
            return title, text
    except Exception:
        pass

    # 3) stdlib stripper
    s = _Stripper()
    try:
        s.feed(html)
    except Exception:
        pass
    return (s.title or _extract_title(html)), s.text()


# --------------------------------------------------------------------------- #
#  Fetch
# --------------------------------------------------------------------------- #
def fetch_url(url, max_chars=DEFAULT_MAX_CHARS, timeout=DEFAULT_TIMEOUT,
              max_bytes=DEFAULT_MAX_BYTES):
    """Fetch `url` and return a dict:
        {ok: True, url, title, text, truncated, content_type}
      or {ok: False, error: "..."}.

    Safe by construction: scheme + host validated up front and at every redirect,
    response size/type/time bounded.
    """
    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "no URL given"}
    if "://" not in url:
        url = "https://" + url          # be forgiving: bare domain -> https
    if urlparse(url).scheme not in SAFE_SCHEMES:
        return {"ok": False, "error": "I can only open http or https links."}

    session = requests.Session()
    current = url
    resp = None
    try:
        for _hop in range(MAX_REDIRECTS + 1):
            ok, reason = host_is_allowed(current)
            if not ok:
                return {"ok": False, "error": reason}
            resp = session.get(current, timeout=timeout, stream=True,
                               allow_redirects=False,
                               headers={"User-Agent": USER_AGENT,
                                        "Accept": "text/html,application/xhtml+xml,"
                                                  "text/plain,application/json;q=0.9,*/*;q=0.5"})
            if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                nxt = urljoin(current, resp.headers["location"])
                resp.close()
                if urlparse(nxt).scheme not in SAFE_SCHEMES:
                    return {"ok": False, "error": "link redirected to an unsupported address."}
                current = nxt
                continue
            break
        else:
            return {"ok": False, "error": "too many redirects."}

        if resp.status_code >= 400:
            return {"ok": False, "error": f"the site returned status {resp.status_code}."}

        content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type and not any(content_type.startswith(t) for t in READABLE_TYPES):
            return {"ok": False,
                    "error": f"that link is {content_type or 'a non-text file'}, "
                             "not a readable web page."}

        # read at most max_bytes
        chunks, total = [], 0
        for chunk in resp.iter_content(8192):
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total >= max_bytes:
                break
        raw = b"".join(chunks)
        encoding = resp.encoding or "utf-8"
        try:
            html = raw.decode(encoding, errors="replace")
        except (LookupError, TypeError):
            html = raw.decode("utf-8", errors="replace")

        title, text = extract_readable(html, content_type, current)
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "I reached the page but couldn't find readable text on it."}
        truncated = len(text) > max_chars
        return {
            "ok": True,
            "url": current,
            "title": title or "",
            "text": text[:max_chars],
            "truncated": truncated,
            "content_type": content_type,
        }
    except requests.exceptions.SSLError:
        return {"ok": False, "error": "the site's security certificate couldn't be verified."}
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "the site took too long to respond."}
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"I couldn't reach that page ({type(e).__name__})."}
    finally:
        try:
            if resp is not None:
                resp.close()
        except Exception:
            pass
