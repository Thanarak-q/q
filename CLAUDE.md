# CLAUDE.md — Q CTF Agent

## What is this?

Q is an AI-powered CTF solver with a conversational CLI.

Current architecture is single-agent with:
- adaptive turn routing (no hard CHAT/TASK/CHALLENGE classifier)
- full CTF solve pipeline (`classify -> plan -> solve`) when challenge-like input is detected
- lightweight chat/tool turns for normal troubleshooting tasks

## Quick start

```bash
python3 main.py
# or
agentq
```

## Core architecture

### Adaptive input handling

`ui/chat.py` routes non-command input through one adaptive loop:
- challenge-like input -> `run_solve()` -> `Orchestrator.solve()`
- normal task/chat input -> `run_chat_turn()` -> `Orchestrator.chat_turn()`

### Orchestrator

`agent/orchestrator.py` is the core engine:
- `solve(...)`: classify intent/category, plan, then shared ReAct loop
- `chat_turn(...)`: short tool-enabled conversational loop
- `_react_loop(...)`: shared execution core for both

### Dynamic behavior (Phase 2)

- Missing-info detection (password/key/token) asks early before wasting steps
- Dynamic micro-planning:
  - short plan first
  - plan refresh prompt after tool results
- Response style control:
  - quick vs balanced vs deep based on intent/user cues/confidence
- Shell non-interactive policy:
  - blocks obvious interactive TUI commands
  - rewrites common commands to non-interactive flags
  - detects timeout/prompt patterns and retries with recovery command

## Guardrails (Phase 3)

Configured in `~/.q/settings.json`:
- `max_cost_per_challenge`
- `max_cost_per_turn`
- `max_tokens_per_turn`
- `max_cost_per_session`

Interactive flow enforces:
- per-turn warning if token/cost limits exceeded
- hard block when session cost limit is reached

## Testing

```bash
python -m unittest discover -s tests -v
```

Key test files:
- `tests/test_phase3_regressions.py`
- `tests/test_guardrails.py`

E2E transcript docs:
- `transcripts/interactive-troubleshooting.md`
- `transcripts/ctf-solve.md`

## Providers and tools

### Providers

Prefix-based routing in `agent/providers/router.py`:
- `gpt-`, `o3`, `o4` -> OpenAI
- `claude-` -> Anthropic
- `gemini-` -> Google

### Tools

Tool registry: `tools/registry.py`  
Common chat subset: `shell`, `file_manager`, `python_exec`, `network`, `answer_user`

## Key files

- `agent/orchestrator.py` — solve/chat_turn + shared ReAct loop
- `ui/chat.py` — adaptive turn router + run_solve/run_chat_turn + guardrails
- `ui/commands.py` — slash commands (`/model`, `/config`, etc.)
- `tools/shell.py` — non-interactive policy + recovery
- `tools/file_manager.py` — safe workspace-bounded path resolution
- `config_yaml/loader.py` — safe YAML overlay via dataclass replace
- `config.py` — AppConfig + guardrail settings
