# Q — AI CTF Challenge Solver

Q is a green capybara that solves CTF challenges using AI.

Single-agent architecture with skill-based prompts, smart input handling,
browser automation, knowledge base learning, and performance tracking.

## Quick Start

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=your_key
python3 main.py
```

For browser-based web challenges:
```bash
playwright install chromium
```

## Features

- **Smart input handling** — prompt_toolkit with arrow keys, command autocomplete, persistent history
- **Skill-based solving** — category-specific cheat sheets guide the agent
- **Flag auto-stop** — detects flags in tool output and stops immediately
- **Scope lock** — prevents agent from drifting to unrelated challenges
- **Browser automation** — Playwright headless browser for JS-heavy web challenges
- **Auto-OCR** — GPT vision analyzes screenshots and images, deciding autonomously whether to extract text (flags, CAPTCHAs, challenge content)
- **Benchmark system** — measure solve rate, cost, and steps per category
- **Knowledge base** — learns from past solves, suggests techniques for similar challenges
- **Stats dashboard** — track performance, win streaks, and cost over time
- **Crash recovery** — resume interrupted sessions with workflow state tracking
- **Auto reports** — Markdown report generated after every solve
- **Session persistence** — save/load/resume with atomic writes
- **Cost tracking** — per-call token counting with budget limits
- **Multi-model strategy** — fast (gpt-4o-mini), default (gpt-4o), reasoning (o3)

## Supported Categories

| Category | Examples |
|----------|---------|
| Forensics | PCAP analysis, memory dumps, disk images, steganography |
| Web | SQLi, XSS, SSTI, LFI, SSRF, auth bypass, browser automation |
| Crypto | RSA, AES, classical ciphers, encoding chains |
| Pwn | Buffer overflow, ROP, format string, heap exploitation |
| Reverse | Binary analysis, decompilation, keygen, anti-debug bypass |
| OSINT | Username lookup, geolocation, domain recon |
| Misc | Encoding, scripting, jail escape, esoteric languages |

## Usage

### Interactive Mode (default)

```bash
python3 main.py
```

Type a challenge description to start solving. The input supports:

- **Arrow keys** — cursor navigation, command history (up/down)
- **Tab autocomplete** — type `/` then Tab for command dropdown
- **Ctrl+R** — reverse history search
- **Ctrl+C** — interrupt solve (double-tap to quit)
- **Ctrl+D** — exit
- **Greetings** — "hi", "hello" get a friendly response, not a solve attempt
- **Exit words** — "exit", "quit", "q", "bye" all quit the program

### CLI Flags

```bash
python3 main.py --verbose                    # Verbose output
python3 main.py --repo /path/to/src          # White-box analysis mode
python3 main.py --config config.yaml         # Load YAML config
python3 main.py --batch challenges.json      # Batch solve from JSON
python3 main.py --benchmark bench.json       # Run benchmark suite
python3 main.py --sessions                   # List saved sessions
python3 main.py --resume ID                  # Resume a paused session
python3 main.py --replay ID                  # Replay session step-by-step
python3 main.py --writeup ID                 # Export session as writeup
python3 main.py --tools                      # List available tools
python3 main.py --build                      # Build Docker sandbox
```

### Interactive Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/stats` | Performance dashboard |
| `/knowledge` | Knowledge base stats |
| `/knowledge search X` | Find similar past solves |
| `/benchmark file.json` | Run benchmark suite |
| `/resume [id\|latest]` | Resume interrupted session |
| `/report [id]` | View solve report |
| `/audit [id]` | View audit log |
| `/workflow [id]` | Show workflow state history |
| `/model [name]` | Switch model |
| `/config` | Show config |
| `/config load file.yaml` | Load YAML config |
| `/repo <path>` | Set source code for white-box analysis |
| `/file <path>` | Load challenge file |
| `/url <url>` | Set target URL |
| `/category [cat]` | Force category |
| `/verbose [on\|off]` | Toggle verbose output |
| `/cost` | Show session cost |
| `/history` | Show solve history |
| `/sessions` | List saved sessions |
| `/clear` | Clear screen |
| `/exit` | Quit |

## Architecture

```
User Input -> Input Filter -> Classifier -> Single Agent (with skill prompts) -> Answer
                                               |
                                         Knowledge Base (learns from past solves)
                                               |
                                         Auto Report + Stats
```

### Pipeline Flow

1. **Input filtering** — greetings, exit words, short ambiguous input caught before classify
2. **Intent classification** — detect what the user wants (find flag, answer question, analyze)
3. **Category classification** — detect challenge type (web, crypto, forensics, etc.)
4. **Knowledge lookup** — search past solves for similar challenges
5. **Planning** — generate attack plan using category skill sheet
6. **Scope lock** — inject challenge scope into system prompt to prevent drift
7. **ReAct loop** — reason-act-observe cycle with tool dispatch
8. **Flag auto-stop** — detect flag patterns in tool output, inject stop nudge
9. **Auto-save** — knowledge base entry + stats record + markdown report

### Agent Safeguards

- **Flag detection** — regex-based extraction with validation (rejects false positives from code context)
- **Stop nudge** — when a flag is detected, a message is injected telling the agent to call `answer_user` immediately
- **Scope lock** — system prompt includes challenge scope (files, category, goal) to prevent the agent from wandering
- **Evidence tracking** — anti-hallucination system rejects claims not backed by tool output
- **Budget limits** — per-challenge cost cap with warnings
- **Graduated pivots** — strategy changes when the agent is stuck (prompt change -> model escalation -> ask user)

## Tools

| Tool | Description |
|------|-------------|
| `shell` | Execute shell commands (strings, binwalk, checksec, etc.) |
| `python_exec` | Run Python scripts (pwntools, crypto, z3, etc.) |
| `file_manager` | Read/write/list files; auto-OCRs image files via GPT vision |
| `network` | HTTP requests and raw TCP socket connections |
| `browser` | Headful Chromium via Playwright (navigate, click, JS, cookies); auto-OCRs screenshots and downloaded images |
| `debugger` | Persistent GDB/pwndbg session via pexpect |
| `pwntools_session` | Persistent pwntools connection (send/recv/ROP gadgets) |
| `netcat_session` | Raw TCP/UDP persistent sessions |
| `answer_user` | Provide answers with confidence scores and flags |

## Benchmarks

Run the built-in benchmark suite:

```bash
python3 main.py --benchmark benchmark/challenges.json
```

Add custom challenges to `benchmark/challenges.json`:

```json
[{
  "id": "crypto_001",
  "name": "Base64 Chain",
  "category": "crypto",
  "description": "Decode: Wm14aFozdGlZWE5...",
  "expected_answer": "flag{base64_ci",
  "match_type": "contains",
  "max_steps": 4,
  "max_cost": 0.05
}]
```

CI integration via `.github/workflows/benchmark.yml` runs benchmarks on every push.

## Configuration

All settings via environment variables or `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | *(required)* | OpenAI API key |
| `DEFAULT_MODEL` | `gpt-4o` | Default model for solving |
| `FAST_MODEL` | `gpt-4o-mini` | Fast model for classification |
| `REASONING_MODEL` | `o3` | Reasoning model for hard challenges |
| `MAX_ITERATIONS` | `15` | Max iterations per solve |
| `MAX_COST_PER_CHALLENGE` | `2.00` | Budget limit per challenge (USD) |
| `SANDBOX_MODE` | `docker` | Execution mode (`docker` or `local`) |
| `TOOL_TIMEOUT_BROWSER_MS` | `30000` | Browser action timeout (ms) |
| `OCR_ENABLED` | `true` | Enable auto-OCR on screenshots/images |
| `OCR_MODEL` | `gpt-4o-mini` | Vision model for OCR decisions |
| `OCR_MAX_TOKENS` | `500` | Max tokens for OCR response |

YAML config is also supported for per-target settings:

```bash
python3 main.py --config target.yaml
```

## Project Structure

```
q/
├── main.py                     # CLI entry point
├── config.py                   # Configuration + model pricing
├── requirements.txt            # Python dependencies
├── agent/
│   ├── orchestrator.py         # ReAct loop + flag auto-stop + scope lock
│   ├── classifier.py           # Intent & category classification
│   ├── planner.py              # Attack planner + model selection
│   └── context_manager.py      # Context window management
├── tools/
│   ├── base.py                 # BaseTool ABC + ToolResult
│   ├── shell.py                # Shell command execution
│   ├── python_exec.py          # Python code execution
│   ├── file_manager.py         # File read/write/list
│   ├── network.py              # HTTP + TCP networking
│   ├── browser.py              # Headless Chromium via Playwright
│   ├── answer_user.py          # Answer tool with confidence
│   └── registry.py             # Tool registry + dispatch
├── skills/                     # Skill cheat sheets (md)
│   ├── SKILL.md                # Core rules (efficiency, stop-when-done, etc.)
│   ├── web.md                  # Web exploitation guide
│   ├── crypto.md               # Cryptography guide
│   ├── forensics.md            # Forensics guide
│   ├── pwn.md                  # Binary exploitation guide
│   ├── reverse.md              # Reverse engineering guide
│   ├── osint.md                # OSINT guide
│   └── misc.md                 # Miscellaneous guide
├── knowledge/
│   ├── base.py                 # KnowledgeBase (JSON + keyword matching)
│   └── extractor.py            # Auto-extract techniques from solves
├── stats/
│   └── tracker.py              # StatsTracker (performance history)
├── benchmark/
│   ├── runner.py               # BenchmarkRunner + ChallengeResult
│   ├── challenges.json         # Test challenge definitions
│   ├── check.py                # CI quality gate
│   └── results/                # Benchmark output
├── report/
│   └── generator.py            # Markdown report generator
├── ui/
│   ├── display.py              # Rich display + welcome screen
│   ├── chat.py                 # Interactive chat loop + callbacks
│   ├── commands.py             # Slash command handlers
│   ├── input_handler.py        # prompt_toolkit input (autocomplete, history)
│   ├── input_filter.py         # Pre-filter (greetings, exit, clarify)
│   ├── tree.py                 # Task tree UI renderer
│   └── mascot.py               # Capybara mascot
├── prompts/
│   ├── system.py               # System prompt builder (+ scope lock)
│   └── strategies.py           # Graduated pivot prompts
├── utils/
│   ├── session_manager.py      # Session persistence + WorkflowState
│   ├── cost_tracker.py         # Token/cost tracking
│   ├── audit_log.py            # Audit logging
│   ├── flag_extractor.py       # Flag pattern matching + validation
│   ├── ocr.py                  # Auto-OCR via GPT vision (analyze_image)
│   └── logger.py               # Structured logging
└── .github/
    └── workflows/
        └── benchmark.yml       # CI benchmark pipeline
```

## Requirements

- Python 3.11+
- OpenAI API key
- Docker (optional, for sandboxed execution)
- Playwright + Chromium (optional, for browser tool)

## License

MIT
