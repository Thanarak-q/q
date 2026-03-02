# Q — AI CTF Challenge Solver

Q is a green capybara that solves CTF challenges using AI.

Single-agent architecture with skill-based prompts, multi-provider LLM support,
plan mode, browser automation, knowledge base learning, hooks system, and performance tracking.

## Setup Guide

### Step 1 — Prerequisites

Make sure you have these installed:

- **Python 3.10+** — [python.org](https://python.org)
- **git** — [git-scm.com](https://git-scm.com)

Check with:

```bash
python3 --version
git --version
```

---

### Step 2 — Install

Run the one-line installer:

```bash
curl -sSL https://raw.githubusercontent.com/Thanarak-q/q/main/install.sh | bash
```

This will:
- Clone the repo to `~/.local/share/agentq/`
- Install all Python dependencies
- Create `~/.q/` for your data and config
- Register the `agentq` command globally

If `agentq` is not found after install, reload your shell:

```bash
source ~/.zshrc   # zsh
source ~/.bashrc  # bash
```

---

### Step 3 — Add your API key

Open `~/.q/settings.json` in any editor:

```bash
nano ~/.q/settings.json
```

Add at least one API key:

```json
{
  "openai_api_key": "sk-...",
  "anthropic_api_key": "sk-ant-...",
  "google_api_key": "",
  "brave_api_key": ""
}
```

> You only need one key. OpenAI is the default provider. See [Multi-Provider Support](#multi-provider-support) to use Claude or Gemini.
> `brave_api_key` is optional — enables Brave Search for the web_search tool (falls back to DuckDuckGo if not set).

**Where to get keys:**
- OpenAI → [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- Anthropic → [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)
- Google → [aistudio.google.com/apikey](https://aistudio.google.com/apikey)

---

### Step 4 — Run

```bash
agentq
```

Talk to Q like a normal assistant — or paste a CTF challenge to solve it.

---

### Step 5 — Optional: Browser Tool

Required for web challenges that need JavaScript rendering:

```bash
playwright install chromium
```

---

### Step 6 — Optional: Docker Sandbox

For safer isolated tool execution:

```bash
# Install Docker: https://docs.docker.com/get-docker/
agentq --build    # builds the sandbox image
```

Then set in `~/.q/settings.json`:

```json
{
  "sandbox_mode": "docker"
}
```

---

### Step 7 — Optional: RAG (Semantic Search)

Enables semantic search over past CTF writeups for better hints:

```bash
pip install chromadb sentence-transformers --user
agentq --reindex
```

---

### Verify everything works

```bash
agentq --version    # should print version
agentq --tools      # should list all available tools
```

---

## Update

```bash
agentq update
```

Pulls latest code from GitHub and reinstalls dependencies automatically.

## Usage

### Interactive Mode (default)

```bash
agentq
```

Q automatically routes your input through a 3-way classifier:

| You type | Route | What happens |
|----------|-------|-------------|
| `"hi"`, `"thanks"`, `"how are you"` | **CHAT** | Quick LLM response, no tools (~$0.001) |
| `"list files here"`, `"read scenario.txt"` | **TASK** | Lightweight tool loop, 5 steps max (~$0.01) |
| CTF challenge description | **CHALLENGE** | Full pipeline: classify → plan → solve (~$0.12+) |

Simple tasks skip the entire CTF pipeline — no classification, no attack plan, no scope lock. Just runs the tool and tells you what it found.

| Input | Behaviour |
|-------|-----------|
| Arrow keys | Cursor navigation, command history |
| Tab | Autocomplete slash commands |
| Ctrl+R | Reverse history search |
| Ctrl+C | Interrupt solve (double-tap to quit) |
| Ctrl+D | Exit |

### CLI Flags

```bash
agentq --verbose                    # Show full LLM thinking and tool output
agentq --watch                      # Live 2x2 dashboard (thinking/tools/tree/stats)
agentq --team                       # Team mode (multi-agent parallel solving)
agentq --no-plan                    # Skip plan approval step
agentq --repo /path/to/src          # White-box analysis mode
agentq --config config.yaml         # Load YAML config override
agentq --hooks hooks.yaml           # Load hooks config
agentq --batch challenges.json      # Batch solve from JSON file
agentq --benchmark bench.json       # Run benchmark suite
agentq --sessions                   # List saved sessions
agentq --resume ID                  # Resume a paused/failed session
agentq --replay ID                  # Replay session step-by-step
agentq --writeup ID                 # Export session as Markdown writeup
agentq --tools                      # List available tools
agentq --build                      # Build Docker sandbox image
agentq --reindex                    # Rebuild RAG vector store
agentq update                       # Update to latest version
```

### Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/plan [on\|off]` | Toggle plan-before-solve (default: on) |
| `/team [on\|off]` | Toggle team mode (multi-agent) |
| `/team tasks` | Show task board |
| `/team messages` | Show inter-agent message log |
| `/model [name]` | Show or switch model |
| `/settings` | Show all settings from `~/.q/settings.json` |
| `/settings <key> <value>` | Update a setting (e.g. `/settings openai_api_key sk-...`) |
| `/config` | Show current config |
| `/config load file.yaml` | Load YAML config |
| `/repo <path>` | Set source code for white-box analysis |
| `/file <path>` | Load challenge file |
| `/url <url>` | Set target URL |
| `/category [cat]` | Force category |
| `/resume [id\|latest]` | Resume interrupted session |
| `/rewind [n\|list]` | Rewind agent to checkpoint N |
| `/stats` | Performance dashboard |
| `/cost` | Show session cost |
| `/history` | Show solve history |
| `/knowledge` | Knowledge base stats |
| `/knowledge search X` | Find similar past solves |
| `/verbose [on\|off]` | Toggle verbose output |
| `/clear` | Clear screen |
| `/exit` | Quit |

## Configuration

All settings live in `~/.q/settings.json` — created automatically on install.

```json
{
  "openai_api_key": "",
  "anthropic_api_key": "",
  "google_api_key": "",
  "brave_api_key": "",

  "default_model": "gpt-4o",
  "fast_model": "gpt-4o-mini",
  "reasoning_model": "o3",
  "fallback_model": "",

  "temperature": 0.2,
  "max_tokens": 4096,
  "streaming": true,

  "plan_mode": true,
  "team_enabled": false,
  "team_max_agents": 2,
  "team_task_timeout": 300,

  "max_iterations": 15,
  "max_cost_per_challenge": 2.00,

  "shell_timeout": 30,
  "python_timeout": 60,
  "network_timeout": 30,

  "sandbox_mode": "docker",
  "log_level": "INFO"
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `openai_api_key` | *(required)* | OpenAI API key |
| `anthropic_api_key` | | Anthropic API key (for Claude models) |
| `google_api_key` | | Google API key (for Gemini models) |
| `brave_api_key` | | Brave Search API key (optional, web_search tool) |
| `default_model` | `gpt-4o` | Default solving model |
| `fast_model` | `gpt-4o-mini` | Fast model for classification |
| `reasoning_model` | `o3` | Reasoning model for hard challenges |
| `plan_mode` | `true` | Show attack plan and wait for approval before solving |
| `team_enabled` | `false` | Enable multi-agent team mode |
| `team_max_agents` | `2` | Number of parallel agents in team mode |
| `team_task_timeout` | `300` | Seconds before a team task times out |
| `max_iterations` | `15` | Max agent iterations per solve |
| `max_cost_per_challenge` | `2.00` | Budget cap per challenge (USD) |
| `sandbox_mode` | `docker` | Execution mode: `docker` or `local` |
| `streaming` | `true` | Stream LLM output token by token |

YAML config is also supported for per-target overrides:

```bash
agentq --config target.yaml
```

## Multi-Provider Support

Q routes to different LLM providers based on model name prefix:

| Prefix | Provider | Example models |
|--------|----------|----------------|
| `gpt-`, `o3`, `o4` | OpenAI | `gpt-4o`, `gpt-4o-mini`, `o3` |
| `claude-` | Anthropic | `claude-sonnet-4-5`, `claude-opus-4` |
| `gemini-` | Google | `gemini-2.0-flash`, `gemini-2.5-pro` |

Switch model mid-solve: `/model claude-sonnet-4-5`

All three providers are fully implemented with OpenAI-compatible tool calling.

## Hooks

Run shell commands on events via a YAML config:

```yaml
# configs/hooks.yaml
hooks:
  pre_tool_call:
    - pattern: "rm -rf"
      action: block
  post_flag:
    - command: "notify-send 'Flag found!'"
  post_solve:
    - command: "echo '${flag}' >> ~/flags.txt"
```

```bash
agentq --hooks configs/hooks.yaml
```

## Plan Mode

Before solving, Q classifies the challenge category and generates a step-by-step attack plan. The plan is displayed in a Rich panel and Q pauses for your input:

```
╭─ Attack Plan  web ───────────────────────────────────────────────╮
│   1. Inspect login form — look for SQL injection entry points     │
│   2. Test ' OR 1=1 -- in username field                          │
│   3. If blocked, try time-based blind SQLi                        │
│   4. Extract flag from database response                          │
╰──────────────────────────────────────────────────────────────────╯
  Enter to solve · type to add notes · 'skip' to skip plan
  plan>
```

- **Enter** — approve and solve
- **Type notes** — notes are appended to the plan before solving
- **`skip`** — skip the plan, solve immediately without it

Toggle plan mode:

```bash
agentq --no-plan              # disable for this run
/plan off                     # disable in session
/plan on                      # re-enable
```

Or set permanently in `~/.q/settings.json`: `"plan_mode": false`

## Team Mode

Team mode spawns specialized parallel agents for hard challenges:

```bash
agentq --team
/team on
```

Each category gets a preset team:

| Category | Phase 1 Agent | Phase 2 Agent |
|----------|--------------|---------------|
| Web | Recon (enumerate) | Exploit (attack) |
| Pwn | Analyst (disassemble) | Exploit (rop/shellcode) |
| Crypto | Analyst (identify) | Solver (implement) |
| Reverse | Static analyst | Dynamic analyst |

Phase 1 starts immediately. Phase 2 starts as soon as Phase 1 makes a discovery — not after Phase 1 finishes. Agents communicate via a shared TaskBoard and MessageBus.

```bash
/team tasks      # view task board
/team messages   # view inter-agent messages
```

> **Note**: Team mode uses 2× more tokens. Best for genuinely hard challenges where parallel exploration helps. Single-agent mode is faster and cheaper for most challenges.

## Features

- **Conversational mode** — CHAT/TASK/CHALLENGE 3-way router; simple tasks use lightweight tool loop, only CTF challenges trigger full pipeline
- **Plan mode** — classify challenge, generate attack plan, pause for user approval before solving
- **Multi-provider LLM** — OpenAI, Anthropic, Google with prefix-based routing (all fully implemented)
- **Team mode** — parallel specialized agents (recon + exploit) with event-based phase sync
- **Web search** — DuckDuckGo (no key) + Brave Search API (optional) for live intelligence
- **Skill-based solving** — category cheat sheets guide the agent (web, crypto, pwn, rev, forensics, osint, misc)
- **Checkpoint & rewind** — `/rewind` to any previous agent state (up to 20 checkpoints)
- **Reflection loop** — agent self-critiques every 3 iterations, auto-pivots on low confidence
- **Hypothesis-driven pivoting** — 5 failure types with targeted recovery strategies
- **Streaming output** — live token-by-token LLM output
- **Watch mode** — Rich live dashboard with 2x2 panel layout
- **RAG over writeups** — semantic search over past CTF writeups (ChromaDB + sentence-transformers)
- **Procedural memory** — records successful solve chains and failure anti-patterns, persists across sessions
- **Browser automation** — Playwright headful Chromium for JS-heavy web challenges
- **Auto-OCR** — GPT vision analyzes screenshots and images autonomously
- **Symbolic verification** — checksec, ropper, angr, z3 for binary analysis
- **Hooks system** — YAML-configured pre/post hooks with regex blocking and shell commands
- **IATs** — persistent GDB, pwntools, netcat sessions for binary exploitation
- **Flag auto-stop** — detects flags in tool output and stops immediately
- **Anti-soliloquy guard** — prevents agent from describing output without running tools
- **Scope lock** — prevents agent from drifting to unrelated challenges
- **Evidence tracking** — anti-hallucination, rejects claims not backed by tool output
- **Session persistence** — save/load/resume with atomic writes
- **Cost tracking** — per-call token counting with budget limits and warnings
- **Benchmark system** — measure solve rate, cost, and steps per category
- **Auto reports** — Markdown report generated after every solve

## Supported Categories

| Category | Examples |
|----------|---------|
| Web | SQLi, XSS, SSTI, LFI, SSRF, auth bypass, browser automation |
| Crypto | RSA, AES, classical ciphers, encoding chains |
| Pwn | Buffer overflow, ROP, format string, heap exploitation |
| Reverse | Binary analysis, decompilation, keygen, anti-debug bypass |
| Forensics | PCAP analysis, memory dumps, disk images, steganography |
| OSINT | Username lookup, geolocation, domain recon |
| Misc | Encoding, scripting, jail escape, esoteric languages |

## Tools

| Tool | Description |
|------|-------------|
| `shell` | Execute shell commands (strings, binwalk, checksec, etc.) |
| `python_exec` | Run Python scripts (pwntools, crypto, z3, etc.) |
| `file_manager` | Read/write/list files; auto-OCRs image files |
| `network` | HTTP requests and raw TCP socket connections |
| `browser` | Headful Chromium via Playwright (navigate, click, JS, cookies) |
| `debugger` | Persistent GDB session via pexpect |
| `pwntools_session` | Persistent pwntools connection (send/recv/ROP) |
| `netcat_session` | Raw TCP/UDP persistent sessions |
| `symbolic` | Formal analysis: checksec, ropper, angr, z3 |
| `recon` | Web recon, directory brute-force, header analysis |
| `web_search` | DuckDuckGo (no key) + Brave Search API (optional) |
| `code_analyzer` | Static code analysis for vulnerabilities |
| `answer_user` | Provide answers with confidence scores and flags |

## Benchmarks

```bash
agentq --benchmark benchmark/challenges.json
```

Add challenges to `benchmark/challenges.json`:

```json
[{
  "id": "crypto_001",
  "name": "Base64 Chain",
  "category": "crypto",
  "description": "Decode: Wm14aFozdGlZWE5...",
  "expected_answer": "flag{base64_chain}",
  "match_type": "contains",
  "max_steps": 4,
  "max_cost": 0.05
}]
```

## Data

All user data is stored in `~/.q/` — never in the install directory:

```
~/.q/
├── settings.json       # Your config and API keys
├── sessions/           # Saved solve sessions
│   └── screenshots/    # Browser screenshots
├── logs/               # Application logs
└── reports/            # Markdown solve reports
```

## Project Structure

```
ctf-agent/
├── main.py                     # CLI entry point
├── config.py                   # Config loader (reads ~/.q/settings.json)
├── install.sh                  # One-line installer
├── requirements.txt            # Python dependencies
├── agent/
│   ├── orchestrator.py         # ReAct loop, chat_turn(), checkpoints, reflection
│   ├── classifier.py           # Intent & category classification
│   ├── planner.py              # Attack planner + hypothesis-driven pivoting
│   ├── context_manager.py      # Context window management
│   ├── hooks.py                # HookEngine (pre/post hooks)
│   ├── parallel.py             # Parallel approach solving
│   ├── providers/
│   │   ├── base.py             # LLMProvider ABC
│   │   ├── openai_provider.py  # OpenAI provider
│   │   ├── anthropic_provider.py # Anthropic provider
│   │   ├── google_provider.py  # Google Gemini provider
│   │   └── router.py           # ProviderRouter (prefix-based routing)
│   └── team/
│       ├── leader.py           # TeamLeader — coordinates agents
│       ├── manager.py          # TeamManager
│       ├── taskboard.py        # Thread-safe TaskBoard (assignee field)
│       ├── messages.py         # MessageBus (per-agent queues)
│       ├── roles.py            # TEAM_PRESETS per category
│       └── callbacks.py        # TeamCallbacks
├── tools/
│   ├── shell.py                # Shell execution
│   ├── python_exec.py          # Python execution
│   ├── file_manager.py         # File operations
│   ├── network.py              # HTTP + TCP
│   ├── browser.py              # Playwright browser
│   ├── debugger.py             # GDB via pexpect
│   ├── pwntools_session.py     # Persistent pwntools
│   ├── netcat_session.py       # Raw TCP/UDP sessions
│   ├── symbolic.py             # checksec / ropper / angr / z3
│   ├── recon.py                # Web recon
│   ├── web_search.py           # DuckDuckGo + Brave Search
│   ├── code_analyzer.py        # Static analysis
│   ├── answer_user.py          # Answer + flag submission
│   └── registry.py             # Tool registry + dispatch
├── skills/                     # Category cheat sheets
│   ├── SKILL.md                # Core agent rules
│   ├── web.md / crypto.md / pwn.md / reverse.md
│   ├── forensics.md / osint.md / misc.md
├── knowledge/
│   ├── base.py                 # KnowledgeBase (JSON + keyword matching)
│   ├── embeddings.py           # RAG via ChromaDB + sentence-transformers
│   ├── procedural.py           # Procedural memory (success chains + anti-patterns)
│   └── extractor.py            # Auto-extract techniques from solves
├── ui/
│   ├── chat.py                 # Chat loop + 3-way router + plan approval
│   ├── display.py              # Rich display + plan panel
│   ├── commands.py             # Slash command handlers (/plan, /team, /rewind, ...)
│   ├── watch.py                # Live 2x2 Rich dashboard
│   ├── spinner.py              # PhaseSpinner (context-aware verbs)
│   ├── input_handler.py        # prompt_toolkit input
│   ├── input_filter.py         # Pre-filter (greetings, exit, clarify)
│   ├── tree.py                 # Task tree renderer
│   └── mascot.py               # Capybara mascot
├── prompts/
│   ├── system.py               # System prompt builder (CTF + conversational)
│   └── strategies.py           # Pivot prompts
├── utils/
│   ├── session_manager.py      # Session persistence
│   ├── cost_tracker.py         # Token/cost tracking
│   ├── audit_log.py            # Audit logging
│   ├── flag_extractor.py       # Flag pattern matching
│   ├── ocr.py                  # Auto-OCR via GPT vision
│   └── logger.py               # Structured logging
├── benchmark/
│   ├── runner.py               # BenchmarkRunner
│   └── challenges.json         # Test challenge definitions
├── report/
│   └── generator.py            # Markdown report generator
├── configs/
│   ├── example.yaml            # Example YAML config
│   └── hooks.yaml              # Example hooks config
└── sandbox/
    ├── docker_manager.py       # Docker sandbox manager
    └── Dockerfile              # Sandbox image
```

## Requirements

- Python 3.10+
- OpenAI API key (or Anthropic / Google)
- git
- Docker *(optional — sandboxed execution)*
- Playwright + Chromium *(optional — browser tool)*
- chromadb + sentence-transformers *(optional — RAG)*

## License

MIT
