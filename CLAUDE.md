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
- `roles.py` — TeammateConfig + TEAM_PRESETS per category (web, pwn, crypto, forensics, reverse, osint, ai, misc)
- `callbacks.py` — TeamCallbacks: forwards flags/discoveries to MessageBus
- `manager.py` — TeamManager: persistence to `~/.q/teams/`

### Config and safety

- `config.py` — `AppConfig` dataclass (mutable), sub-configs (`ModelConfig`, `AgentConfig`, `ToolConfig`, `PipelineConfig`) are frozen
- `_KNOWN_SETTINGS_KEYS` whitelist validates `~/.q/settings.json` keys at load time — warns on typos
- Provider fallback has infinite-recursion guard (`_is_fallback` parameter in `router.py`)
- Context summarization uses `fast_model` to avoid expensive model for housekeeping

### Tool registry

- `tools/registry.py` — tool registration, dispatch, smart output truncation
- `from_subset()` uses lazy factories — only instantiates requested tools (not all 17)
- `max_output_chars` injected at construction, not re-read from config on every call
- Heavy tools (browser, symbolic) use deferred imports

### Agent handoffs (CAI pattern)

- `agent/handoffs.py` — `HandoffTool`: LLM-invocable agent handoffs
- `agent/flag_discriminator.py` — `FlagDiscriminator`: validates candidate flags before submission
- Handoff targets: `flag_discriminator`, `recon`, `exploit`
- Flag discriminator runs automatically on `answer_user` for FIND_FLAG intent
- Two-tier validation: fast heuristic (no LLM) + optional LLM verification

### MCP integration

- `tools/mcp_client.py` — MCP JSON-RPC 2.0 client for stdio-based servers
- `MCPBridgeTool` wraps external MCP tools into the ToolRegistry
- Configure servers in `~/.q/settings.json` via `mcp_servers`

### Stop hooks (pre-answer verification)

- `agent/hooks.py` — `pre_answer` hook type validates before returning
- Check types: `flag_format` (regex), `flag_discriminator` (heuristic), `shell` (exit code)
- If a stop hook rejects, the agent continues solving instead of returning

### UI/UX layer

- `ui/display.py` — Rich-based rendering (banner with pixel-art capybara, answer/flag display, tables)
- `ui/tree.py` — `TaskTree`: ANSI-based streaming tree renderer (Claude Code-style output)
- `ui/spinner.py` — `LiveSpinner` (ANSI, coexists with tree) + `PhaseSpinner` (Rich Status)
  - `set_phase_detail()` shows live token count during LLM generation in minimal mode
- `ui/watch.py` — `WatchDisplay`: 2x2 Rich Live dashboard (thinking, tool output, tree, stats)
- `ui/mascot.py` — Pixel-art capybara rendered with ANSI true-color half-blocks (4 expressions)
- `ui/chat.py` — `ChatCallbacks`: routes orchestrator events to tree/display/spinner
  - Elapsed time tracking: `_solve_start_time` → passed to `show_done()` for all solve paths
- `ui/selector.py` — Arrow-key interactive selectors for commands
- `ui/input_handler.py` — prompt_toolkit REPL with completion, history, multi-line
- `ui/input_filter.py` — Adaptive routing: challenge vs chat turn detection
- `ui/commands.py` — `/tools` command lists all registered tools with descriptions
- Streaming: `on_thinking_delta` increments token counter; updates spinner detail every 5 tokens
- Phase verbs: `PHASE_VERBS` map tool/phase names to human-friendly display text

### Dynamic behavior

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

## Guardrails

Configured in `~/.q/settings.json`:
- `max_cost_per_challenge`
- `max_cost_per_turn`
- `max_tokens_per_turn`
- `max_cost_per_session`

Interactive flow enforces:
- per-turn warning if token/cost limits exceeded
- hard block when session cost limit is reached

## Exception handling policy

- Cleanup/destructor paths: broad `except Exception` is OK (never crash on teardown)
- File I/O: use `except OSError` (covers PermissionError, FileNotFoundError, etc.)
- JSON parsing: use `except (OSError, json.JSONDecodeError)`
- Decode operations: use `except (ValueError, UnicodeDecodeError)`
- UI rendering: broad catch OK but must log with `debug(... exc_info=True)`
- Never use silent `except Exception: pass` — always log at minimum

## Testing

```bash
python -m unittest discover -s tests -v
```

Key test files (113 tests):
- `tests/test_phase3_regressions.py` — core pipeline regressions
- `tests/test_guardrails.py` — cost/token guardrails
- `tests/test_input_handler.py` — input handling
- `tests/test_ai_ctf.py` — AI payloads, category, flag extractor
- `tests/test_ai_e2e.py` — E2E with live HTTP chatbot server
- `tests/test_team.py` — team system (TaskBoard, MessageBus, presets, isolation)
- `tests/test_handoffs.py` — agent handoffs, flag discriminator, MCP client, stop hooks

E2E transcript docs:
- `transcripts/interactive-troubleshooting.md`
- `transcripts/ctf-solve.md`

## Providers and tools

### Providers

Prefix-based routing in `agent/providers/router.py`:
- `gpt-`, `o3`, `o4` -> OpenAI
- `claude-` -> Anthropic
- `gemini-` -> Google
- `glm-` -> Zhipu AI GLM

Per-category model overrides via `category_models` in `~/.q/settings.json`:
```json
{"category_models": {"crypto": "o3", "web": "claude-sonnet-4-5", "pwn": "claude-sonnet-4-6"}}
```

Fallback: if primary model fails and `fallback_model` is set, retries once (guarded against infinite recursion).

### Tools

Tool registry: `tools/registry.py`
Registered tools (17): `shell`, `python_exec`, `file_manager`, `network`, `recon`, `web_search`, `llm_interact`, `answer_user`, `browser`, `debugger`, `pwntools_session`, `netcat_session`, `symbolic`, `code_analyzer`, `agent_handoff`, `mcp`

Common chat subset: `shell`, `file_manager`, `python_exec`, `network`, `answer_user`

### Team system

- `taskboard.py` has deadlock detection via DFS cycle detection + automatic breaking
- Leader monitor loop checks for deadlocks every iteration
- `/suggest` command provides procedural memory hints per category
- `/compare` command shows team member solve approach comparison

## Key files

- `agent/orchestrator.py` — solve/chat_turn + shared ReAct loop
- `agent/classifier.py` — Category enum (web/pwn/crypto/reverse/forensics/osint/ai/misc)
- `agent/planner.py` — attack planner + hypothesis-driven pivoting
- `agent/context_manager.py` — context window management + summarization (uses fast_model)
- `agent/providers/router.py` — prefix-based provider routing + fallback with recursion guard
- `agent/team/leader.py` — TeamLeader reactive coordinator
- `agent/team/taskboard.py` — thread-safe TaskBoard with DAG
- `agent/team/roles.py` — TEAM_PRESETS per category (all 8 categories)
- `ui/chat.py` — adaptive turn router + run_solve/run_chat_turn + guardrails
- `ui/commands.py` — slash commands (`/model`, `/config`, `/flag`, `/team`, `/tools`, etc.)
- `ui/selector.py` — interactive arrow-key selectors
- `tools/shell.py` — non-interactive policy + recovery
- `tools/llm_interact.py` — AI target interaction (9 actions + deep-scan)
- `tools/ai_payloads.py` — 40+ prompt injection payloads
- `tools/file_manager.py` — safe workspace-bounded path resolution
- `tools/registry.py` — tool registration + lazy factories + smart truncation
- `tools/code_analyzer_tool.py` — BaseTool wrapper for static vuln scanner
- `tools/mcp_client.py` — MCP client + MCPBridgeTool for external tool servers
- `config_yaml/loader.py` — safe YAML overlay via dataclass replace
- `config.py` — AppConfig (mutable) + frozen sub-configs + settings key validation
- `utils/flag_extractor.py` — flag pattern matching (incl. NCSA{})
- `utils/notify.py` — cross-platform desktop notifications (notify-send / osascript)
- `prompts/system.py` — system prompt builder (incl. AI category guidance)
- `skills/ai.md` — AI security skill reference
- `skills/osint.md` — comprehensive OSINT skill (700+ lines)
- `agent/providers/glm_provider.py` — Zhipu AI GLM provider (OpenAI-compatible)
- `agent/handoffs.py` — CAI-inspired agent handoff tool (flag_discriminator, recon, exploit)
- `agent/flag_discriminator.py` — two-tier flag validation (heuristic + LLM)
- `agent/hooks.py` — hook engine with pre_answer stop hooks
