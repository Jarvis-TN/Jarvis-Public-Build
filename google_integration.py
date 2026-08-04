"""Google Calendar + Gmail integration for Jarvis.

Reads Calendar + Gmail, and WRITES Gmail (create drafts, send messages). Actual
sends are gated behind a spoken confirmation up in the engine - this module just
performs the API call it's told to.

OAuth: on first connect, a browser opens for you to grant access; the resulting
token is saved to token.json so it's silent afterwards. credentials.json is the
Desktop-app OAuth client downloaded from Google Cloud Console.

NOTE: the SCOPES list below now includes gmail.compose (drafts + send). Because
the scope set changed, an existing token.json authorized for the old read-only
scopes is INSUFFICIENT - you must re-run the consent flow (connect_google.py or
the tray's 'Connect Google account') once to mint a token with send permission.
"""

import os
import json
import base64
import datetime
from email.message import EmailMessage

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(APP_DIR, "credentials.json")
TOKEN_PATH = os.path.join(APP_DIR, "token.json")

# Read Calendar + Gmail; compose/send Gmail. gmail.compose covers creating drafts
# AND sending, without granting label/delete powers - least privilege for "write".
# Changing this list means the saved token.json must be refreshed (re-consent).
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


def credentials_present():
    return os.path.exists(CREDENTIALS_PATH)


def _load_creds():
    """Return valid Credentials, refreshing if needed, or None if not yet authorized."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    if not os.path.exists(TOKEN_PATH):
        return None
    # Load with the token's OWN granted scopes (no SCOPES arg): passing the wider
    # requested SCOPES here makes creds.scopes echo them back even when the user
    # never consented, and a subsequent refresh would write those unearned scopes
    # into token.json. Reading the file's real scopes keeps has_send_scope honest.
    creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_PATH, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            return creds
        except Exception:
            return None
    return None


def is_connected():
    try:
        return _load_creds() is not None
    except Exception:
        return False


def authorize_interactive():
    """Run the one-time browser consent flow and save token.json. Blocking."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not credentials_present():
        raise FileNotFoundError("credentials.json not found in the Jarvis folder.")
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    return True


def _service(api, version):
    from googleapiclient.discovery import build
    creds = _load_creds()
    if creds is None:
        raise RuntimeError("Google account not connected.")
    return build(api, version, credentials=creds, cache_discovery=False)


# --------------------------------------------------------------------------- #
#  Calendar
# --------------------------------------------------------------------------- #
def _fmt_event_time(start):
    """start is the event 'start' dict: {'dateTime': ...} or {'date': ...}."""
    if "date" in start:           # all-day event
        return "all day"
    dt = start.get("dateTime")
    if not dt:
        return ""
    try:
        return datetime.datetime.fromisoformat(dt).strftime("%-I:%M %p")
    except Exception:
        try:
            # Windows strftime has no %-I; fall back to %I and strip leading zero.
            return datetime.datetime.fromisoformat(dt).strftime("%I:%M %p").lstrip("0")
        except Exception:
            return dt


def upcoming_events_raw(hours=2, max_results=15):
    """Structured timed events in the next `hours` for the reminder watcher.
    Returns [{id, title, start(datetime, tz-aware)}], skipping all-day events."""
    service = _service("calendar", "v3")
    now = datetime.datetime.now(datetime.timezone.utc)
    end = now + datetime.timedelta(hours=hours)
    result = service.events().list(
        calendarId="primary", timeMin=now.isoformat(), timeMax=end.isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=max_results,
    ).execute()
    out = []
    for ev in result.get("items", []):
        dt = ev.get("start", {}).get("dateTime")
        if not dt:
            continue  # all-day events don't get meeting reminders
        try:
            when = datetime.datetime.fromisoformat(dt)
        except Exception:
            continue
        out.append({"id": ev.get("id"), "title": ev.get("summary", "(untitled)"),
                    "start": when})
    return out


def upcoming_events(days=1, max_results=10):
    service = _service("calendar", "v3")
    now = datetime.datetime.now(datetime.timezone.utc)
    end = now + datetime.timedelta(days=days)
    result = service.events().list(
        calendarId="primary", timeMin=now.isoformat(), timeMax=end.isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=max_results,
    ).execute()
    items = result.get("items", [])
    if not items:
        span = "today" if days <= 1 else f"the next {days} days"
        return f"No events on your calendar for {span}."
    lines = []
    for ev in items:
        when = _fmt_event_time(ev.get("start", {}))
        title = ev.get("summary", "(no title)")
        lines.append(f"{when}: {title}")
    return "Upcoming events:\n" + "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Gmail
# --------------------------------------------------------------------------- #
def recent_emails(max_results=5, unread_only=True):
    service = _service("gmail", "v1")
    query = "is:unread in:inbox" if unread_only else "in:inbox"
    listing = service.users().messages().list(
        userId="me", q=query, maxResults=max_results,
    ).execute()
    msgs = listing.get("messages", [])
    count = listing.get("resultSizeEstimate", len(msgs))
    if not msgs:
        return "No unread emails in your inbox." if unread_only else "No emails found."
    lines = []
    for m in msgs:
        full = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject"],
        ).execute()
        headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
        sender = headers.get("From", "")
        # Trim "Name <addr>" to just the friendly name when present.
        if "<" in sender:
            sender = sender.split("<")[0].strip().strip('"') or sender
        subject = headers.get("Subject", "(no subject)")
        lines.append(f"From {sender}: {subject}")
    label = f"{count} unread email" + ("s" if count != 1 else "")
    return f"{label} in your inbox:\n" + "\n".join(lines)


# ---- Gmail: write (compose / send) --------------------------------------- #
_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.compose"


def has_send_scope():
    """True only if the token ACTUALLY granted the compose/send scope. Reads the
    scopes recorded in token.json directly (the source of truth for what the user
    consented to), so it can tell 'not connected' apart from 'connected but
    read-only, needs re-consent'. Best-effort: any failure returns False."""
    try:
        if not os.path.exists(TOKEN_PATH):
            return False
        with open(TOKEN_PATH, "r", encoding="utf-8") as f:
            granted = set(json.load(f).get("scopes") or [])
        return _SEND_SCOPE in granted
    except Exception:
        return False


def _build_raw(to, subject, body):
    msg = EmailMessage()
    msg["To"] = to
    if subject:
        msg["Subject"] = subject
    msg.set_content(body or "")
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def create_draft(to, subject, body):
    """Save a Gmail draft (nothing is sent). Returns the draft id."""
    service = _service("gmail", "v1")
    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": _build_raw(to, subject, body)}},
    ).execute()
    return draft.get("id")


def send_email(to, subject, body):
    """Send a Gmail message immediately. Returns the sent message id. Callers must
    apply their own confirmation gate BEFORE calling this - it sends unconditionally."""
    service = _service("gmail", "v1")
    sent = service.users().messages().send(
        userId="me", body={"raw": _build_raw(to, subject, body)},
    ).execute()
    return sent.get("id")
