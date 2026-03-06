# CLAUDE.md — Q CTF Agent

## What is this?

Q is an AI-powered CTF solver with a conversational CLI.

Current architecture is single-agent with:
- adaptive turn routing (no hard CHAT/TASK/CHALLENGE classifier)
- full CTF solve pipeline (`classify -> plan -> solve`) when challenge-like input is detected
- lightweight chat/tool turns for normal troubleshooting tasks
- team mode (multi-agent) for hard challenges via `--team` or `/team on`

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

### Team system

`agent/team/` provides multi-agent parallel solving:
- `leader.py` — TeamLeader: reactive coordinator with task DAG
- `taskboard.py` — Thread-safe TaskBoard with dependency edges and assignees
- `messages.py` — MessageBus: per-agent queues + shutdown protocol
- `roles.py` — TeammateConfig + TEAM_PRESETS per category (web, pwn, crypto, forensics, reverse, osint, misc)
- `callbacks.py` — TeamCallbacks: forwards flags/discoveries to MessageBus
- `manager.py` — TeamManager: persistence to `~/.q/teams/`

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

## Categories

8 supported categories: `web`, `pwn`, `crypto`, `reverse`, `forensics`, `osint`, `ai`, `misc`

The `ai` category handles: prompt injection, jailbreaking, secret extraction, AI filter bypass, LLM security, chatbot exploitation.

## AI CTF features

- `tools/llm_interact.py` — 9 actions: send_prompt, multi_turn, spray, auto_attack, chat_web, analyze_response, export_history, reset_session, show_history
- `tools/ai_payloads.py` — 40+ categorized prompt injection payloads (direct, override, roleplay, encoding, indirect, sidechannel, context, multiturn)
- `skills/ai.md` — comprehensive AI security skill file
- Deep-scan: auto-detects flags in base64, hex, ROT13, reversed text
- `/flag` command — set flag format for competition (e.g. NCSA{}, custom regex)
- NCSA{} and ncsa{} in default flag extractor patterns

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
- `tests/test_phase3_regressions.py` — core pipeline regressions
- `tests/test_guardrails.py` — cost/token guardrails
- `tests/test_input_handler.py` — input handling
- `tests/test_ai_ctf.py` — AI payloads, category, flag extractor
- `tests/test_ai_e2e.py` — E2E with live HTTP chatbot server

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
Registered tools: `shell`, `python_exec`, `file_manager`, `network`, `recon`, `web_search`, `llm_interact`, `answer_user`, `browser`, `debugger`, `pwntools_session`, `netcat_session`, `symbolic`

Common chat subset: `shell`, `file_manager`, `python_exec`, `network`, `answer_user`

## Key files

- `agent/orchestrator.py` — solve/chat_turn + shared ReAct loop
- `agent/classifier.py` — Category enum (web/pwn/crypto/reverse/forensics/osint/ai/misc)
- `agent/planner.py` — attack planner + hypothesis-driven pivoting
- `agent/team/leader.py` — TeamLeader reactive coordinator
- `agent/team/taskboard.py` — thread-safe TaskBoard with DAG
- `agent/team/roles.py` — TEAM_PRESETS per category
- `ui/chat.py` — adaptive turn router + run_solve/run_chat_turn + guardrails
- `ui/commands.py` — slash commands (`/model`, `/config`, `/flag`, `/team`, etc.)
- `ui/selector.py` — interactive arrow-key selectors
- `tools/shell.py` — non-interactive policy + recovery
- `tools/llm_interact.py` — AI target interaction (9 actions + deep-scan)
- `tools/ai_payloads.py` — 40+ prompt injection payloads
- `tools/file_manager.py` — safe workspace-bounded path resolution
- `tools/registry.py` — tool registration + smart truncation
- `config_yaml/loader.py` — safe YAML overlay via dataclass replace
- `config.py` — AppConfig + guardrail settings
- `utils/flag_extractor.py` — flag pattern matching (incl. NCSA{})
- `prompts/system.py` — system prompt builder (incl. AI category guidance)
- `skills/ai.md` — AI security skill reference
