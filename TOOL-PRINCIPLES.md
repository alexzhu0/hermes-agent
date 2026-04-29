# TOOL-PRINCIPLES.md

Architectural invariants for how Hermes core exposes runtime context to the
agent and tools. These are **durable decisions** — PRs that reintroduce the
inverse shape should be rejected even if otherwise functional.

Each principle links to the originating issue/PR discussion. Principles are
added by PR only; delete only when superseded, and link the successor.

---

## 1. Runtime time is advisory, not enforcement

**Decision (2026-04-29, from #17459 / #17475):**

Runtime time, timezone, and contact-window facts are surfaced to the agent
and to tool results as **context**. Hermes core **does not silently enforce
quiet-hours or availability policy in the control plane** by default.

### Why

Quiet-hours-as-enforcement is a policy decision that belongs to the agent
holding the goal, not to a background subsystem. When Hermes silently
withholds or delays a contact, the agent cannot reason about the delay,
users cannot see why a message didn't land, and the behavior is
undetectable from either side of the loop. This was the failure mode that
#4711 (`feat: Add profile-scoped gateway autonomy runtime`) and #7402
(`feat: drain Ockham outbox notifications via Hermes scheduler`) both ran
into; both were closed un-merged for this reason.

The correct shape is the one in #10421 and #15872: **inject `Current time`
+ timezone into the user-message / ephemeral context path** so the agent
sees it, preserves prompt-cache stability, and makes the
"defer / proceed / ask" decision explicitly with visible reasoning.

### What this means in practice

For PR reviewers, the following shapes should be **rejected** unless they
are opt-in (off by default, per-session or per-deployment flag, and
observable in the agent's turn context):

- A scheduler / control-plane subsystem that delays, suppresses, or drops
  agent actions based on a clock / calendar / quiet-hours config that the
  agent never sees.
- A middleware that rewrites or withholds tool results based on time of
  day without emitting a tool-visible marker explaining the redaction.
- Gateway delivery queues that silently hold outbound messages during
  declared quiet hours without surfacing the held state to the agent.

The following shapes are **encouraged**:

- Tool outputs that include runtime time context (e.g.
  `context: {"utc_now": "...", "user_tz": "America/Los_Angeles"}`) so
  time-sensitive tools can decide for themselves.
- Per-turn ephemeral system context carrying `Current time` + timezone so
  the agent can reason about "is now a reasonable time to send this."
- Agent-accessible advisory hints (`"user is in quiet hours; ask before
  sending"`) — visible, overridable, loggable.

### Related history

- **Closed, not merged — do not revive as-is**:
  - #4711 gateway autonomy w/ quiet-hours in control plane
  - #7402 Ockham outbox draining held approvals during quiet hours
- **Open / preferred direction**:
  - #10421 turn-level live current-time awareness (core need)
  - #15872 inject `Current time` + timezone into ephemeral context
    (preferred implementation shape)
  - #10448, #5241 related time-awareness bugs
- **Follow-up**:
  - #17474 surface tool-runtime time advisory context for time-sensitive
    tools (opt-in per tool)

---

## Appending principles

New principles should follow the same shape:

1. **Title** — one-line statement of the invariant
2. **Decision** — date + originating issue/PR references
3. **Why** — the failure mode the inverse produces
4. **What this means in practice** — rejected vs encouraged PR shapes
5. **Related history** — the closed PRs demonstrating the wrong shape and
   the open ones implementing the right one

Keep entries **specific**: "don't do X; do Y instead; here is a diff
shape you can reject/approve quickly."
