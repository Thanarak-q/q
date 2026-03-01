# CLAUDE.md — Q CTF Agent

## Q คืออะไร

Q เป็น AI agent ที่ solve CTF (Capture The Flag) challenges อัตโนมัติ
CLI interface สไตล์ Claude Code มี mascot เป็น capybara สีเขียว
สร้างโดย q (CS student @ Chiang Mai University, AI Engineer)

Multi-provider: OpenAI, Anthropic (Claude), Google (Gemini)

---

## สถานะปัจจุบัน — v0.9.0

### Features ที่ทำงานได้แล้ว

**Core**
- Single agent ReAct loop — classify → plan → solve
- 7 categories: web, crypto, pwn, reverse, forensics, osint, misc
- Skill files (skills/*.md) — category cheat sheets
- Checkpoint & rewind (`/rewind`)
- Anti-soliloquy guard
- Reflection loop (every 3 iterations)
- Hypothesis-driven pivoting (5 FailureType)

**Plan Mode (v0.9.0)**
- Classify + create attack plan before solve
- Show plan in Rich panel, pause for user approval
- User can approve (Enter), add notes, or skip
- `/plan on|off` toggle, `--no-plan` flag, `plan_mode` in settings.json

**Multi-Provider (v0.8.0)**
- OpenAI: gpt-4o, gpt-4o-mini, o3 (prefix: `gpt-`, `o3`, `o4`)
- Anthropic: claude-* (prefix: `claude-`)
- Google: gemini-* (prefix: `gemini-`) — fully implemented
- `ProviderRouter` — prefix-based routing
- `LLMProvider` ABC — all providers implement same interface

**Team Mode (v0.8.0+)**
- `--team` flag or `/team on` to enable
- Specialized role presets per category (web: recon+exploit, pwn: analyst+exploit, etc.)
- Tasks pre-assigned to specific agents (no work-stealing)
- Truly parallel: phase 2 starts immediately, waits on `first_discovery_event`
- Monitor loop sets event on first discovery from phase 1
- MessageBus for inter-agent communication
- TaskBoard with `assignee` field + `list_available(for_agent=)`

**Hooks (v0.8.0)**
- YAML-configured pre/post hooks
- `pre_tool_call`: regex pattern blocking
- `post_flag`, `post_solve`: shell commands
- `--hooks` flag or auto-load from `configs/hooks.yaml`

**Tools (12 registered)**
- shell, python_exec, file_manager, network, browser (Playwright)
- debugger (GDB/pexpect IAT), pwntools_session IAT, netcat_session IAT
- recon (nmap/gobuster/nikto/whatweb), code_analyzer, symbolic (angr/z3/ropper/checksec)
- **web_search** — DuckDuckGo (no key) + Brave Search API (optional `brave_api_key`)
- answer_user

**Intelligence**
- RAG over writeups (ChromaDB + sentence-transformers, optional)
- Procedural memory — learns success chains + anti-patterns
- ErrorAnalyzer — pattern matching, failure tracking, suggestions
- EvidenceTracker — anti-hallucination
- ContextManager — auto-summary at 80% window

**UI**
- PhaseSpinner (15 phase verbs)
- Watch mode (`--watch`) — Rich Live 2x2 dashboard
- Streaming output (token-by-token)
- `/rewind [n|list]` command
- Persistent input history (`~/.q/history`)
- TaskTree ANSI renderer

---

## Architecture

```
User Input
    │
    ▼
Input Filter (greetings/typos/clarify)
    │
    ▼ [plan_mode=True]
Plan Phase ──→ classify_challenge() + create_plan()
    │          Show Rich panel, prompt user approval
    │          User: Enter / notes / skip
    ▼
run_solve()
    │
    ├─[team_mode] TeamLeader.solve_with_team()
    │               ├── Phase 1 agent thread (starts immediately)
    │               ├── Phase 2 agent thread (waits first_discovery_event)
    │               ├── Monitor loop (flag detection, event signalling)
    │               └── MessageBus + TaskBoard coordination
    │
    └─[single]  Orchestrator.solve()
                    ├── Phase 1: Classify (fast model)
                    ├── Phase 2: Plan (forced_plan if user approved)
                    ├── Phase 3: Build system prompt + skill file
                    └── ReAct Loop:
                            Think → Act → Observe
                            │
                            ├── Anti-soliloquy guard
                            ├── Checkpoint (before each tool call)
                            ├── ErrorAnalyzer (diagnose failures)
                            ├── Every 3 iters: Reflection
                            ├── Low confidence → Hypothesis pivot
                            └── Flag found → answer_user()
```

---

## Project Structure

```
ctf-agent/
├── main.py                      # CLI entry point
├── config.py                    # AppConfig + all sub-configs
├── install.sh                   # One-line installer (runtime Python detection)
├── requirements.txt
│
├── agent/
│   ├── orchestrator.py          # CORE — ReAct loop, checkpoints, reflection
│   ├── classifier.py            # Category + intent classification
│   ├── planner.py               # Attack planning + FailureType pivoting
│   ├── context_manager.py       # Context window management
│   ├── parallel.py              # Parallel approach solving
│   ├── hooks.py                 # HookEngine (pre/post hooks)
│   ├── providers/
│   │   ├── base.py              # LLMProvider ABC + SimpleUsage
│   │   ├── openai_provider.py   # OpenAI (pass-through)
│   │   ├── anthropic_provider.py# Anthropic (format translation)
│   │   ├── google_provider.py   # Google Gemini (format translation)
│   │   └── router.py            # ProviderRouter (prefix routing)
│   └── team/
│       ├── leader.py            # TeamLeader — coordinates agents
│       ├── manager.py           # TeamManager
│       ├── taskboard.py         # Thread-safe TaskBoard (assignee field)
│       ├── messages.py          # MessageBus (per-agent queues)
│       ├── roles.py             # TEAM_PRESETS per category
│       └── callbacks.py         # TeamCallbacks (forwards to lead)
│
├── tools/
│   ├── registry.py              # ToolRegistry — register + dispatch
│   ├── base.py                  # BaseTool + ToolParameter + ToolResult
│   ├── shell.py                 # Shell execution
│   ├── python_exec.py           # Python execution
│   ├── file_manager.py          # File ops + auto-OCR
│   ├── network.py               # HTTP + TCP
│   ├── browser.py               # Playwright browser
│   ├── debugger.py              # GDB via pexpect (IAT)
│   ├── pwntools_session.py      # Persistent pwntools (IAT)
│   ├── netcat_session.py        # Raw TCP/UDP (IAT)
│   ├── recon.py                 # nmap/gobuster/nikto/whatweb/subfinder
│   ├── symbolic.py              # checksec/ropper/angr/z3 (lazy imports)
│   ├── web_search.py            # DuckDuckGo + Brave Search
│   ├── code_analyzer.py         # White-box static analysis
│   ├── error_analyzer.py        # Error detection + suggestions
│   ├── evidence_tracker.py      # Anti-hallucination
│   └── answer_user.py           # Final answer + flag submission
│
├── skills/                      # Category cheat sheets (read by agent)
│   ├── SKILL.md                 # Core rules + thinking protocol
│   ├── web.md / crypto.md / pwn.md / reverse.md
│   └── forensics.md / osint.md / misc.md
│
├── ui/
│   ├── chat.py                  # Chat loop + ChatState + run_solve()
│   ├── display.py               # Rich display (show_plan, show_flag, etc.)
│   ├── commands.py              # Slash handlers (/plan, /team, /rewind, ...)
│   ├── watch.py                 # WatchDisplay — Rich Live 2x2 dashboard
│   ├── spinner.py               # PhaseSpinner (15 verbs)
│   ├── input_handler.py         # prompt_toolkit + ~/.q/history
│   ├── input_filter.py          # Greeting/exit/clarify filter
│   ├── tree.py                  # TaskTree ANSI renderer
│   └── mascot.py                # Capybara ASCII art
│
├── knowledge/
│   ├── base.py                  # KnowledgeBase (JSON + keyword)
│   ├── embeddings.py            # RAG via ChromaDB + sentence-transformers
│   ├── procedural.py            # Procedural memory (success chains)
│   └── extractor.py             # Auto-extract techniques from solves
│
├── prompts/
│   ├── system.py                # System prompt builder + scope lock
│   └── strategies.py            # Pivot prompts
│
├── utils/
│   ├── cost_tracker.py          # Token/cost tracking + budget cap
│   ├── session_manager.py       # Session save/load/resume
│   ├── audit_log.py             # Structured audit logging (JSONL)
│   ├── flag_extractor.py        # Flag pattern matching + false-positive filter
│   ├── ocr.py                   # GPT vision auto-OCR
│   └── logger.py                # Logging setup
│
├── benchmark/                   # runner.py, check.py, challenges.json
├── report/generator.py          # Markdown report generation
├── stats/tracker.py             # Performance stats
├── sandbox/                     # docker_manager.py + Dockerfile
├── configs/                     # example.yaml, hooks.yaml
└── config_yaml/loader.py        # YAML config loader
```

---

## Config — ~/.q/settings.json

All settings live in `~/.q/settings.json`:

```json
{
  "openai_api_key": "sk-...",
  "anthropic_api_key": "sk-ant-...",
  "google_api_key": "AIza...",
  "brave_api_key": "BSA...",

  "default_model": "gpt-4o",
  "fast_model": "gpt-4o-mini",
  "reasoning_model": "o3",
  "fallback_model": "",

  "plan_mode": true,
  "team_enabled": false,
  "team_max_agents": 2,
  "team_task_timeout": 300,

  "max_iterations": 15,
  "max_cost_per_challenge": 2.00,
  "streaming": true,
  "sandbox_mode": "docker",
  "log_level": "INFO"
}
```

---

## Key Design Principles

**Be Lazy** — solve in 3-6 steps, not 20+
- Run 1-2 commands → form hypothesis → verify → answer
- Never run a command "just to see what happens"

**Thinking Protocol** — `<think>` tags before every action
- First step: GOAL, PLAN, SCOPE, DONE WHEN
- Every step: LEARNED, HYPOTHESIS, NEXT, DONE?
- DONE? = yes → stop immediately

**No Evidence, No Answer** — every claim must trace to tool output

**Observe → Hypothesize → Test**

---

## When Making Changes

- **Add tool** → implement `BaseTool`, register in `ToolRegistry.__init__()`, update `web_search.py` pattern if it's a search-like tool
- **Add slash command** → add to `COMMANDS` dict and handler function in `commands.py`, add to help string
- **Add provider** → implement `LLMProvider` ABC in `agent/providers/`, add prefix in `router.py`
- **Add team preset** → add to `TEAM_PRESETS` dict in `agent/team/roles.py`
- **Change skill** → test against real challenge — agent reads skill files verbatim
- **Change orchestrator** → verify messages array: every tool_call must have a matching tool response
- **Before commit** → `python3 -m py_compile <changed files>` + `python3 main.py --tools`

---

## CLI Reference

```bash
agentq                          # Interactive mode (default)
agentq --verbose                # Full LLM output
agentq --watch                  # Live 2x2 dashboard
agentq --team                   # Team mode (multi-agent)
agentq --no-plan                # Skip plan approval step
agentq --repo /path/to/src      # White-box mode
agentq --config config.yaml     # YAML config override
agentq --hooks hooks.yaml       # Load hooks config
agentq --batch challenges.json  # Batch solve
agentq --benchmark bench.json   # Benchmark suite
agentq --sessions               # List sessions
agentq --resume ID              # Resume session
agentq --replay ID              # Replay session
agentq --writeup ID             # Export Markdown writeup
agentq --tools                  # List tools
agentq --build                  # Build Docker sandbox
agentq --reindex                # Rebuild RAG vector store
agentq update                   # Pull latest + reinstall deps
```

## Slash Commands

```
/help                    All commands
/plan [on|off]           Toggle plan-before-solve (default: on)
/team [on|off]           Toggle team mode
/team tasks              Show task board
/team messages           Show message log
/model [name]            Show or switch model
/settings [key value]    View/update settings.json
/config [load file]      Show or load YAML config
/repo <path>             Set source code for white-box
/file <path>             Load challenge file
/url <url>               Set target URL
/category [cat]          Force category
/rewind [n|list]         Rewind to checkpoint N
/resume [id|latest]      Resume session
/stats                   Performance dashboard
/cost                    Session token/cost summary
/history                 Solve history
/knowledge [search X]    Knowledge base
/verbose [on|off]        Toggle verbose
/clear                   Clear screen
/exit                    Quit
```

---

## Performance History

| Version | Steps | Tokens | Cost | Result |
|---------|-------|--------|------|--------|
| v0.1 single agent | 34 | 258k | $0.67 | wrong |
| v0.2 bug fixes | ~15 | 21k | $0.05 | correct |
| v0.3 multi-agent | 19 | 73k | $0.19 | wrong |
| v0.4 skill-based | **3** | **13.6k** | **$0.04** | correct |

**Key lesson**: Multi-agent pipeline made Q WORSE.
Single agent + good skill prompts = best results.
Team mode is for parallelism on hard challenges, not default.

---

## Tech Stack

- Python 3.10+
- OpenAI SDK, Anthropic SDK, google-generativeai
- Playwright (browser automation)
- pexpect (IAT: persistent gdb/pwntools)
- prompt_toolkit (CLI input + history)
- Rich (terminal UI)
- PyYAML (config)
- ChromaDB + sentence-transformers (optional RAG)
- angr, z3-solver, ropper (optional symbolic)
- requests (web_search)
