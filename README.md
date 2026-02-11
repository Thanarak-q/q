# q

**The Autonomous CTF Operative.**

`q` is an elite multi-agent system designed to dismantle Capture The Flag challenges through coordinated AI warfare. Orchestrating a specialized team of **Recon**, **Analyst**, **Solver**, and **Reporter** agents, it leverages advanced ReAct reasoning and a military-grade Docker arsenal to detect, exploit, and document vulnerabilities in real-time.

All while a supportive Capybara mascot ensures your morale never drops below 100%.

## Features

### Core

- **Multi-Agent Pipeline** — specialized agents for Recon, Analysis, Solving, and Reporting working in concert
- **Parallel Solving** — concurrently test multiple hypotheses to speed up solving
- **Automatic classification** — detects challenge category (web, pwn, crypto, reverse, forensics, misc)
- **User intent classification** — intelligently determines when to stop, continue, or answer questions
- **Docker sandbox** — isolated execution with 50+ pre-installed CTF tools (sqlmap, gobuster, john, steghide, angr, z3, pwntools, etc.)

### Advanced

- **Comprehensive Reporting** — auto-generates professional Markdown reports with evidence and steps
- **Task tree UI** — real-time progress visualization with hierarchical task tracking
- **Answer with confidence** — `answer_user` tool displays solutions with confidence scores
- **Multi-model strategy** — optimized usage of fast (gpt-4o-mini), default (gpt-4o), and reasoning (o3) models across agents
- **Session persistence** — save/load/resume sessions as JSON; auto-saves every iteration
- **Batch mode** — solve multiple challenges from a JSON file with summary report
- **Cost tracking** — detailed per-call token counting and budget limits
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
Orchestrator (Route: Auto/Multi/Single)
    |
    v
[Multi-Agent Pipeline]
    |
    +---> 1. Classification (Intent + Category) [Fast Model]
    |
    +---> 2. Recon Agent [Fast Model]
    |       (Quick information gathering & difficulty assessment)
    |
    +---> 3. Analyst Agent [Default Model] (Optional - skipped if Easy)
    |       (Deep analysis & hypothesis generation)
    |
    +---> 4. Solver Agent(s) [Default/Reasoning Model]
    |       (Parallel execution of hypotheses)
    |
    +---> 5. Reporter Agent [Fast Model]
            (Generates structured Markdown report)
```

### Multi-Agent Interaction

The pipeline coordinates specialized agents, each with a distinct role:

1.  **Recon Agent**: Quickly lists files, detects types, and runs basic checks (strings, checksec).
2.  **Analyst Agent**: Reviews recon data to formulate ranked hypotheses.
3.  **Solver Agent**: Executes the ReAct loop to solve the challenge. **Runs in parallel** if multiple valid hypotheses are found.
4.  **Reporter Agent**: Compiles all findings into a clean `report.md`.

### Model Strategy

| Agent/Task | Model | Role |
|------------|-------|------|
| Classify/Recon | `gpt-4o-mini` | Speed & low cost |
| Analyst | `gpt-4o` | Reasoning & planning |
| Solver | `gpt-4o` / `o3` | Execution (escalates to `o3` for Hard tasks) |
| Reporter | `gpt-4o-mini` | Summarization |

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
| `FAST_MODEL` | `gpt-4o-mini` | Fast model for classification/recon/report |
| `DEFAULT_MODEL` | `gpt-4o` | Default model for analyst/solver |
| `REASONING_MODEL` | `o3` | Reasoning model for hard challenges |
| `MAX_PARALLEL_SOLVERS` | `3` | Max concurrent solver agents |
| `PIPELINE_MODE` | `auto` | Pipeline mode (`auto`, `multi`, `single`) |
| `FAST_PATH_ENABLED` | `true` | Skip analyst for easy challenges |
| `MAX_ITERATIONS` | `30` | Max total iterations (per agent roughly) |
| `MAX_COST_PER_CHALLENGE` | `2.00` | Budget limit per challenge (USD) |
| `SANDBOX_MODE` | `docker` | Execution mode (`docker` or `local`) |
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
│   ├── orchestrator.py           # Main ReAct loop + feature integration
│   ├── pipeline.py               # Multi-agent pipeline coordinator
│   ├── base_agent.py             # Abstract base agent
│   ├── agents/                   # Specialized agents (recon, analyst, solver, reporter)
│   ├── classifier.py             # Intent & category classification
│   ├── planner.py                # Attack planner + model selection
│   └── context_manager.py        # Context window management
├── report/
│   └── generator.py              # Markdown report generator
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
