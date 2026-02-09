# q

Your friendly AI-powered CTF companion  — an interactive terminal agent that solves
Capture The Flag challenges through conversation. Features a ReAct reasoning loop,
50+ security tools in a Docker sandbox, and a cute capybara mascot cheering you on.

## Features

### Core

- **Automatic classification** — detects challenge category (web, pwn, crypto, reverse, forensics, misc) using fast model
- **User intent classification** — intelligently classifies user messages to determine when to stop, continue, or provide answers
- **Expert-level playbooks** — deep, pro-level strategies for each category with real-world techniques
- **ReAct agent loop** — iterative reason-act-observe cycle with tool dispatch
- **Docker sandbox** — isolated execution with 50+ pre-installed CTF tools (sqlmap, gobuster, john, steghide, angr, z3, pwntools, etc.)
- **Context management** — automatic summarization when approaching token limits

### Advanced

- **Task tree UI** — real-time progress visualization with hierarchical task tracking and status indicators
- **Answer with confidence** — `answer_user` tool displays solutions with confidence scores and optional flags
- **Graduated pivot system** — 6-level escalation when stuck: basic pivot -> step back -> approach swap -> reclassify -> model escalation -> ask user for hint
- **Multi-model strategy** — 3-tier model system: fast (gpt-4o-mini) for classification/planning, default (gpt-4o) for solving, reasoning (o3) for hard problems
- **Session persistence** — save/load/resume sessions as JSON; auto-saves every iteration with resume functionality
- **Batch mode** — solve multiple challenges from a JSON file with summary report
- **Cost tracking** — per-call token counting, per-model breakdown, budget limits with warnings
- **Rich interactive UI** — beautiful terminal interface with tool call visualization and live status display
- **Replay & writeup** — replay any session step by step; export as Markdown writeup

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set up environment

```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### 3. Build Docker sandbox (optional but recommended)

```bash
python main.py build-sandbox
```

### 4. Solve a challenge

```bash
python main.py solve "This RSA challenge uses a small public exponent e=3"
```

## CLI Commands

### solve

Solve a single CTF challenge.

```bash
# Basic usage
python main.py solve "RSA challenge with small e"

# With files and target URL
python main.py solve --file chall.zip --url http://target:8080 "Web login bypass"

# Interactive mode
python main.py solve --interactive

# With live dashboard and budget limit
python main.py solve --dashboard --budget 5.00 "Heap exploitation challenge"

# Resume a paused session
python main.py solve --resume 20250101_120000_abc123

# Override model and iterations
python main.py solve --model gpt-4-turbo --max-iter 50 "Complex forensics"

# Without Docker sandbox
python main.py solve --no-docker "Simple XOR cipher"
```

**Options:**

| Flag | Description |
|------|-------------|
| `-f, --file PATH` | Challenge file(s) to analyse (repeatable) |
| `-u, --url TEXT` | Target service URL |
| `--flag-format TEXT` | Custom flag regex pattern |
| `--model TEXT` | Override default LLM model |
| `--no-docker` | Run tools locally without Docker |
| `-i, --interactive` | Interactive setup mode |
| `--max-iter INT` | Override max iterations |
| `--dashboard` | Enable Rich live dashboard |
| `--budget FLOAT` | Max cost per challenge in USD |
| `--resume ID` | Resume a paused session |

### batch

Solve multiple challenges from a JSON file.

```bash
python main.py batch challenges.json
python main.py batch challenges.json --budget 3.00 --no-docker
```

**JSON format:**

```json
[
  {
    "description": "RSA with small e=3",
    "files": ["challenge/rsa.py", "challenge/output.txt"],
    "flag_format": "CTF\\{[^}]+\\}"
  },
  {
    "description": "Web login bypass",
    "url": "http://target:8080"
  }
]
```

Outputs a summary table with solve status, category, flags, iterations, and cost per challenge.

### sessions

List all saved sessions.

```bash
python main.py sessions
```

Displays a table with session ID, status (solved/failed/paused), category, description, iterations, flags, and creation date.

### replay

Replay a saved session step by step with Rich formatting.

```bash
python main.py replay 20250101_120000_abc123
python main.py replay 20250101_120000_abc123 --speed 0    # instant
python main.py replay 20250101_120000_abc123 --speed 2.0  # slow
```

### writeup

Export a session as a Markdown CTF writeup.

```bash
python main.py writeup 20250101_120000_abc123
python main.py writeup 20250101_120000_abc123 -o writeup.md
```

### build-sandbox

Build the Docker sandbox image with all CTF tools.

```bash
python main.py build-sandbox
```

### list-tools

Show all available agent tools.

```bash
python main.py list-tools
```

## Architecture

```
User Input
    |
    v
┌─────────────────────────────────────────────────────────────┐
│  UI Layer (Rich Terminal)                                   │
│  ├── Task Tree UI (progress visualization)                  │
│  ├── Chat Interface (interactive input/output)              │
│  └── Display Components (tool calls, status, mascot)        │
└─────────────────────────────────────────────────────────────┘
    |
    v
Intent Classifier --> Determine: solve / question / continue / stop
    |
    v
Category Classifier (fast model) --> web/pwn/crypto/rev/forensics/misc
    |
    v
Planner (fast model) --> Attack Plan
    |
    v
Model Selector --> Pick model based on category + escalation
    |
    v
ReAct Loop:
    LLM (think) --> Tool Call --> Execute in Sandbox --> Observe
         ^                                                 |
         |_________________________________________________|
         |
    answer_user?   --> Display answer with confidence + flag
    Flag Found?    --> Done (save session, report cost)
    Budget Limit?  --> Stop
    Stalled?       --> Graduated Pivot (6 levels)
    Near Limit?    --> Summarize Context
    Each Iteration --> Save session + update task tree
```

### Pivot Escalation Levels

| Level | Name | Action |
|-------|------|--------|
| 1 | `BASIC_PIVOT` | Try different approach within same category |
| 2 | `STEP_BACK` | Full re-evaluation from scratch |
| 3 | `APPROACH_SWAP` | Switch static<->dynamic, manual<->automated |
| 4 | `RECLASSIFY` | Reconsider challenge category entirely |
| 5 | `MODEL_ESCALATION` | Upgrade to reasoning model (o3) |
| 6 | `ASK_USER` | Request hint from user |

### Multi-Model Strategy

| Tier | Model | Used For |
|------|-------|----------|
| Fast | `gpt-4o-mini` | Classification, planning |
| Default | `gpt-4o` | Main solving loop |
| Reasoning | `o3` | Escalated hard problems |

## Tools

| Tool | Description |
|------|-------------|
| `shell` | Execute shell commands (strings, binwalk, checksec, file, objdump, etc.) |
| `python_exec` | Run Python scripts (pwntools, crypto, angr, z3, data processing) |
| `file_manager` | Read/write/list files, detect file types via magic bytes |
| `network` | HTTP requests (GET/POST) and raw TCP socket connections |
| `answer_user` | Provide answers with confidence scores and optional flags |
| `capybara_generator` | Generate capybara ASCII art for fun 🦫 |

## Category Playbooks

Each category has a deep, expert-level playbook covering pro techniques:

- **Web** — SQLi, XSS, SSTI, SSRF, deserialization, auth bypass, JWT attacks, race conditions
- **Pwn** — Buffer overflow, format string, heap exploitation (UAF, tcache, fastbin), ROP chains, SROP, kernel exploits
- **Crypto** — RSA attacks (Wiener, Hastad, Franklin-Reiter), AES (ECB/CBC/padding oracle), elliptic curves, lattice, PRNG
- **Reverse** — Static + dynamic analysis, anti-debug bypass, VM/obfuscation, Go/Rust binaries, .NET/Java/Python decompilation
- **Forensics** — Disk/memory/network forensics, steganography (LSB, DCT, audio), file carving, log analysis, registry hives
- **Misc** — Jail escapes, OSINT, encoding puzzles, QR codes, esoteric languages, side-channel analysis

## Configuration

All settings via environment variables or `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | *(required)* | OpenAI API key |
| `FAST_MODEL` | `gpt-4o-mini` | Fast model for classification/planning |
| `DEFAULT_MODEL` | `gpt-4o` | Default model for solving |
| `REASONING_MODEL` | `o3` | Reasoning model for escalation |
| `MAX_ITERATIONS` | `30` | Max agent loop iterations |
| `STALL_THRESHOLD` | `5` | Iterations before pivot triggers |
| `CONTEXT_LIMIT_PERCENT` | `80` | Context usage % before summarization |
| `TOOL_OUTPUT_MAX_CHARS` | `4000` | Truncate tool output at this length |
| `MAX_COST_PER_CHALLENGE` | `2.00` | Budget limit per challenge (USD) |
| `TOOL_TIMEOUT_SHELL` | `30` | Shell command timeout (seconds) |
| `TOOL_TIMEOUT_PYTHON` | `60` | Python script timeout (seconds) |
| `TOOL_TIMEOUT_NETWORK` | `30` | Network request timeout (seconds) |
| `SANDBOX_MODE` | `docker` | Execution mode (`docker` or `local`) |
| `DOCKER_IMAGE` | `q-sandbox` | Docker image name |
| `DOCKER_MEM` | `512m` | Container memory limit |
| `DOCKER_CPU_QUOTA` | `50000` | Container CPU quota |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_DIR` | `logs` | Log file directory |
| `SESSION_DIR` | `sessions` | Session file directory |

## Project Structure

```
q/
├── main.py                       # CLI entry point (solve, batch, replay, writeup, sessions)
├── config.py                     # Configuration + model pricing
├── .env.example                  # Environment variable template
├── requirements.txt              # Python dependencies
├── agent/
│   ├── orchestrator.py           # Main ReAct loop + all feature integration
│   ├── classifier.py             # Challenge category + user intent classifier
│   ├── planner.py                # Attack planner + PivotManager + model selection
│   └── context_manager.py        # Message history + auto-summarization
├── tools/
│   ├── base.py                   # BaseTool ABC + ToolResult + OpenAI schema gen
│   ├── shell.py                  # Shell command execution
│   ├── python_exec.py            # Python code execution
│   ├── file_manager.py           # File read/write/list operations
│   ├── network.py                # HTTP + TCP networking
│   ├── answer_user.py            # Answer tool with confidence scoring
│   ├── capybara_generator.py     # Capybara ASCII art generator
│   └── registry.py               # Tool registry + dispatch
├── ui/
│   ├── tree.py                   # Task tree UI for progress visualization
│   ├── display.py                # Rich display components + formatting
│   ├── chat.py                   # Interactive chat interface
│   ├── commands.py               # CLI command handlers
│   ├── spinner.py                # Loading spinner animations
│   └── mascot.py                 # Capybara mascot display
├── prompts/
│   ├── system.py                 # System prompt builder
│   ├── strategies.py             # Graduated pivot prompts (6 levels)
│   └── categories/               # Expert playbooks
│       ├── web.py                # Web exploitation playbook
│       ├── pwn.py                # Binary exploitation playbook
│       ├── crypto.py             # Cryptography playbook
│       ├── reverse.py            # Reverse engineering playbook
│       ├── forensics.py          # Forensics + stego playbook
│       └── misc.py               # Misc challenges playbook
├── sandbox/
│   ├── docker_manager.py         # Docker container lifecycle + file copy
│   └── Dockerfile                # Sandbox image (50+ CTF tools)
└── utils/
    ├── cost_tracker.py           # Token/cost tracking + budget limits
    ├── session_manager.py        # Session save/load/resume/export
    ├── dashboard.py              # Rich Live 4-panel dashboard
    ├── flag_extractor.py         # Flag pattern matching
    ├── file_detector.py          # File type detection (magic bytes)
    ├── logger.py                 # Structured logging + Rich console
    └── token_counter.py          # Token counting (tiktoken)
```

**Total: 40+ source files across 6 modules.**

## Requirements

- Python 3.11+
- OpenAI API key with access to gpt-4o (and optionally o3 for escalation)
- Docker (optional, for sandboxed execution)

## License

MIT
