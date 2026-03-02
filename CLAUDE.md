# CLAUDE.md — Q CTF Agent

## What is this?

Q is an AI-powered CTF challenge solver with a conversational interface. Single-agent architecture with skill-based prompts, multi-provider LLM support, and a 3-way input router.

## Quick start

```bash
# Run from ctf-agent/ directory
python3 main.py

# Or via installed command
agentq
```

## Architecture

### Input routing (3-way)

All user input goes through an LLM classifier in `ui/chat.py`:

- **CHAT** — greetings, meta questions → single LLM call, no tools
- **TASK** — "list files", "read X" → `Orchestrator.chat_turn()` (5-step ReAct, restricted tools, no classify/plan)
- **CHALLENGE** — CTF descriptions → `Orchestrator.solve()` (full pipeline: classify → plan → solve)

### Core loop

`agent/orchestrator.py` is the main file. Two public entry points:

- `solve(description, ...)` — full CTF pipeline (classify → plan → ReAct loop)
- `chat_turn(user_message)` — lightweight conversational turn (5 steps, no classify/plan)

Both reuse `_react_loop()` internally.

### Providers

`agent/providers/` — multi-provider LLM support. Router uses model name prefix:
- `gpt-` / `o3` / `o4` → OpenAI
- `claude-` → Anthropic
- `gemini-` → Google (stub)

### Tools

11 tools in `tools/registry.py`. Chat turn uses a subset: `shell`, `file_manager`, `python_exec`, `network`, `answer_user`.

### Prompts

`prompts/system.py` has two builders:
- `build_system_prompt()` — full CTF prompt with skills, scope lock, category guides
- `build_chat_prompt()` — lightweight conversational prompt (no CTF overhead)

## Key conventions

- Single agent only. Multi-agent was tried (v0.3-v0.4) and abandoned.
- Agent MUST call `answer_user` tool to deliver its response.
- `_react_loop()` is the shared core — never duplicate loop logic.
- All tool deps are lazy-imported (angr, z3, pwntools, chromadb, etc.).
- Config lives in `~/.q/settings.json`. YAML overrides via `--config`.
- User data in `~/.q/` — never in the install directory.

## Testing

```bash
python3 -c "from prompts.system import build_chat_prompt; print(build_chat_prompt())"
python3 -c "from tools.registry import ToolRegistry; r = ToolRegistry(); print(r.tool_names)"
```

## File layout

```
agent/orchestrator.py    — Main agent loop (solve, chat_turn, _react_loop)
agent/classifier.py      — Category + intent classification
agent/planner.py         — Attack planning + pivoting
agent/providers/         — LLM provider abstraction
prompts/system.py        — System prompt builders
tools/registry.py        — Tool registry + dispatch
ui/chat.py               — Chat loop, 3-way router, run_solve, run_chat_turn
ui/display.py            — Rich display helpers
ui/commands.py           — Slash command handlers
config.py                — AppConfig loader
```
