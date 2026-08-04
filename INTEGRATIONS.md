# Jarvis Integrations: MCP, Telegram, Media

Three integrations that extend Jarvis outward. All opt-in via `config.json`.

## 1. MCP client — the multiplier (`jarvis_mcp.py`)

Connects Jarvis to any **Model Context Protocol** server, exposing its tools to
Jarvis's brain alongside the native ones — no per-service code. One integration
unlocks the whole MCP ecosystem (Slack, GitHub, Notion, Google Drive, filesystem,
databases, Gmail, …).

```json
"mcp_enabled": true,
"mcp_servers": [
  {"name": "filesystem", "command": "npx",
   "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:/Users/you/Documents"]},
  {"name": "github", "transport": "http", "url": "https://your-github-mcp/endpoint"}
]
```

- **stdio** servers (launched locally) or **http/sse** servers (remote) are both
  supported. Each server's tools appear to Jarvis as `mcp__<server>__<tool>`.
- The MCP SDK is async; Jarvis runs it on a background event loop and bridges to
  the sync agentic loop, keeping sessions alive. Works for the Claude brain *and*
  the local-LLM brain.
- Verified end-to-end against a real in-repo MCP server (`tests/test_mcp.py`).

Needs `mcp` (added to requirements); stdio servers like the official ones need
Node/`npx` available.

## 2. Telegram front-end (`jarvis_telegram.py`)

Talk to Jarvis from any device via a Telegram bot, and let him push proactive
pings to you — no port forwarding (Telegram relays it).

1. Create a bot with **@BotFather**, copy the token.
2. `config.json`: `"telegram_enabled": true`, `"telegram_bot_token": "…"`.
3. Message the bot once — the **first sender is paired as owner** (saved to
   `telegram_allowed_chat_ids`); afterwards only allowed chats are answered.

- Replies are **text-only** (no voice in an empty room) via `engine.text_reply()`,
  which runs the full tool-using brain (online) or the offline handler.
- Set `"telegram_notify_proactive": true` to also receive proactive interruptions
  (reminders, alerts) in Telegram.
- Swappable: the same pattern works for other chat platforms later.

## 3. Media control (native tools)

Control whatever is playing, no API keys:

- **`media_control`** — play/pause, next, previous, stop, volume up/down, mute
  via the Windows media keys (works with Spotify, YouTube, any player).
- **`play_media`** — "play X" opens the song/artist/album in Spotify (app or web)
  or YouTube Music.

Say "pause", "skip", "turn it up", "play some Miles Davis", etc. For full
library/playlist control (auto-play a specific track), a Spotify Web API
integration could be added later — say the word.
