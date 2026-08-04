"""Jarvis Telegram front-end - talk to Jarvis from any device via a Telegram bot.

Lets you message Jarvis from your phone/desktop Telegram and get text replies, and
lets Jarvis push proactive notifications to you. Reach him from anywhere, no port
forwarding (Telegram's servers relay everything).

Setup: create a bot with @BotFather, paste the token into config (telegram_bot_token),
set telegram_enabled true. The FIRST chat to message the bot is paired as the owner
(persisted to telegram_allowed_chat_ids); after that only allowed chats are answered.

Dependency-light: long-polls the Bot API over plain `requests`.
"""

import time
import requests

API = "https://api.telegram.org/bot{token}/{method}"


def _call(token, method, timeout=70, **params):
    r = requests.post(API.format(token=token, method=method), json=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def send_message(token, chat_id, text):
    """Send a message to a chat (used for replies and proactive pings)."""
    # Telegram caps messages at 4096 chars.
    return _call(token, "sendMessage", chat_id=chat_id, text=text[:4096], timeout=30)


def run_bridge(token, allowed, on_message, status_cb=None,
               is_running=lambda: True, on_pair=None):
    """Long-poll for messages and dispatch them.

    `allowed` is a set of authorized chat ids (may be empty to enable first-sender
    pairing). `on_message(text, chat_id) -> reply_text`. `on_pair(chat_id)` is
    called when a new owner is paired. Blocking - run in a daemon thread."""
    def _log(m):
        if status_cb:
            try:
                status_cb(m)
            except Exception:
                pass

    offset = None
    _log("Telegram bridge online - message your bot to pair.")
    while is_running():
        try:
            data = _call(token, "getUpdates", offset=offset, timeout=60)
        except Exception:
            time.sleep(3)
            continue
        for upd in data.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message") or {}
            chat = msg.get("chat", {})
            cid = chat.get("id")
            text = (msg.get("text") or "").strip()
            if cid is None or not text:
                continue
            # authorization / first-sender pairing
            if allowed and cid not in allowed:
                try:
                    send_message(token, cid, "You're not authorized to use this assistant.")
                except Exception:
                    pass
                continue
            if not allowed:
                allowed.add(cid)
                if on_pair:
                    try:
                        on_pair(cid)
                    except Exception:
                        pass
                try:
                    send_message(token, cid, "Paired. At your service, sir.")
                except Exception:
                    pass
                continue
            try:
                reply = on_message(text, cid)
            except Exception as e:
                reply = f"I hit an error, sir: {e}"
            if reply:
                try:
                    send_message(token, cid, reply)
                except Exception:
                    pass
