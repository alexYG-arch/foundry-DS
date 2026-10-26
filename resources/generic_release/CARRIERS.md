# Carriers

Foundry is carrier-neutral. No carrier is the default; select one in the
Scope/Plan and record the instruction files it actually reads.

| Carrier | Instruction discovery | Runtime path | Status |
|---|---|---|---|
| Codex (legacy only) | `AGENTS.override.md`, `AGENTS.md` | legacy `agents/codex.py` (1.0–1.2 compatibility) | legacy |
| DSH | `AGENTS.override.md`, `AGENTS.md` | `agents/dsh.py` (`dsh --profile headless --json`) | first-class |
| Claude-style | `CLAUDE.md` | declarative/adapter path | instruction discovery supported; adapter not certified |
| Generic CLI | `AGENTS.override.md`, `AGENTS.md` by default; profile may declare another | declarative profile | contract only |

`instruction_read_preflight(..., carrier="codex"|"dsh"|"claude")` checks the
selected file chain against declared reads. Unknown carriers fail closed.
Compatibility names such as `CODEX_GLOBAL_DEFAULTS` and
`CODEX_NATIVE_LOOPBACK_TCP` are machine-protocol aliases, not default-carrier
claims.

The codex legacy path remains readable for 1.0–1.2 plans; it is not the
default for new 1.3 plans. DSH and the DeepSeek API are the certified execution
paths in this runtime. GUI Desktop `standard` sessions are not attachable;
headless-compatible sessions only.
