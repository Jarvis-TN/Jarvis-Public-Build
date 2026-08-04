# Jarvis Autonomy Layer

Makes Jarvis more **proactive, context-aware, and autonomous** without becoming
reckless. The prime directive: *anticipate needs and reduce manual steps — do the
useful low-impact thing and report it, but **ask first** for anything
consequential, irreversible, or money-related.* Default to the safe choice on
ambiguity, and never fabricate a result from a tool that didn't actually run.

It is built from a cold, fully-tested core (`jarvis_autonomy.py`) that the live
engine (`jarvis.py`) wires into voice, the attention broker, and the turn loop.

## Pieces

| Piece | Where | What it does |
|---|---|---|
| **Decision rule** | `jarvis_autonomy.decide()` | Pure function: `act` / `ask` / `skip` for a candidate action. |
| **Candidate action** | `jarvis_autonomy.CandidateAction` | A proactive idea + its confidence, impact, reversibility. |
| **Approval gate** | `interpret_confirmation()`, `requires_approval()` + engine `_resolve_pending_approval()` | Consequential actions are spoken as a yes/no question; the next reply is the answer. |
| **Open loops** | `jarvis_autonomy.OpenLoopStore` (`memory/open_loops.json`) | Standing goals & multi-step tasks that persist across sessions, with follow-up scheduling. |
| **Action log** | `jarvis_autonomy.ActionLog` (`memory/action_log.json`) | Audit trail of every autonomous action + an undo path. |
| **Proactive triggers** | engine `_openloop_watcher`, `_submit_candidate` | Feed candidates through the decision rule and the attention broker. |

## The decision rule

`decide(candidate, confidence_threshold, auto_impacts=("low",))` returns
`act` / `ask` / `skip`:

1. **Consequential or irreversible → always ask.** A hard guardrail — confidence
   can never override it. (sends / deletes / posts / spends money / affects others)
2. **Confidence below threshold → ask.** When in doubt, ask, don't act.
3. **High-confidence AND low-impact AND reversible → act**, then report it.
4. **Anything else** (e.g. confident but medium/high impact) **→ ask.**

`auto_impacts` is the set of impact levels eligible for autonomous action
(default low only). Widen it to `["low","medium"]` to opt into more aggressive
autonomy.

## How a proactive idea flows

```
source builds a CandidateAction
        │
        ▼
engine._submit_candidate(cand)  ──► decide()
        │                              │
   act  │                              │  ask
        ▼                              ▼
attention broker (timing) ──► do it + speak it ──► ActionLog.record(decision="act")
        │
   ask  ▼
attention broker (timing) ──► speak the yes/no question, arm a pending approval
                                        │
                          user's next turn → _resolve_pending_approval()
                              confirm → fire + log "ask-approved"
                              cancel  → drop  + log "ask-denied"
                              unclear → leave pending (passes through to Claude)
                              timeout → lapse + log "ask-lapsed"
```

The **attention broker** (pre-existing) owns *timing* — it never lets Jarvis talk
over you, during quiet hours, or twice in quick succession. The **decision rule**
owns *act-vs-ask*. The **approval gate** owns *confirmation*. Only one approval is
ever in flight at a time.

Any future write-tool can force the gate via `engine.request_consequential(summary, fulfill, impact=…, undo=…)`.

## Standing goals & open loops

Each loop has: `title`, `next_step`, `owner` (`user`/`jarvis`), `status`
(`open`/`waiting`/`done`/`dropped`), `due` (YYYY-MM-DD or blank), `history`, and a
`last_nudged` throttle. Open loops are injected into the system prompt so Jarvis
stays loop-aware, and `due_for_followup()` surfaces overdue ones for proactive
nudges. Managed by voice through these tools:

- `add_open_loop(title, next_step, owner, due)` — "remind me to…", "my goal is…"
- `list_open_loops()` — "what am I working on?"
- `advance_open_loop(id, note, next_step)` — record progress
- `close_open_loop(id, note, status)` — finished or abandoned

## Action log & undo

Every autonomous action is logged with timestamp, trigger, confidence, decision,
impact, reversibility, and outcome. Reversible actions carry an `undo` hint.

- `review_actions(count)` — "what did you do?"
- `undo_last_action()` — "undo that" (honest if nothing is reversible)

## Failure handling

On any tool error Jarvis gives a brief **spoken** explanation and a fallback —
never a silent failure and never an invented result. Autonomous failures are
recorded to the action log with `outcome="failed: …"`.

## Config values

Added to `config.json` / `config.example.json` (all have safe defaults):

| Key | Default | Meaning |
|---|---|---|
| `autonomy_enabled` | `true` | Master switch for the proactive task engine. |
| `autonomy_confidence_threshold` | `0.7` | At/above this **and** low-impact + reversible → act; otherwise ask. |
| `autonomy_auto_impacts` | `["low"]` | Impact levels allowed to act without asking. Add `"medium"` for more autonomy. |
| `approval_timeout_seconds` | `180` | A pending spoken approval lapses (no action) after this with no clear answer. |
| `openloop_followups_enabled` | `true` | Proactively follow up on due standing goals / open loops. |
| `openloop_poll_seconds` | `300` | How often the follow-up watcher checks for due loops. |
| `openloop_min_nudge_hours` | `20` | Minimum gap between nudges of the *same* loop. |

It also reuses the existing attention-broker dials: `proactive_min_gap_seconds`
(min gap between *any* two proactive interruptions) and
`proactive_quiet_before_hour` (suppress proactive talk before this hour).

## Guardrails (non-negotiable)

- Money/trading actions are **always** gated.
- No autonomous sending, posting, deleting, or purchasing without confirmation.
- Below-threshold confidence → ask, never act.
- Everything autonomous is logged and, where feasible, reversible.

## Tests

`tests/test_autonomy.py` — 21 tests covering the decision rule (incl. the hard
guardrails), the approval gate (parsing + the live engine fire/cancel/ambiguous/
lapse/single-in-flight paths), the open-loop follow-up scheduling/throttle, and
the action log + undo.

```
.venv\Scripts\python.exe tests\test_autonomy.py      # standalone runner
.venv\Scripts\python.exe -m pytest tests\test_autonomy.py   # or under pytest
```
