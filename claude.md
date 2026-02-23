# CLAUDE.md — Q CTF Agent

## Q คืออะไร

Q เป็น AI agent ที่ solve CTF (Capture The Flag) challenges อัตโนมัติ ใช้ OpenAI API เป็น reasoning engine มี CLI interface สไตล์ Claude Code มี mascot เป็น capybara สีเขียว

สร้างโดย q (CS student @ Chiang Mai University, AI Engineer)

## สถานะปัจจุบัน (v0.5.0)

### ทำงานได้แล้ว
- Single agent + skill-based prompts (3 steps, $0.04/challenge)
- 7 categories: forensics, web, crypto, pwn, reverse, osint, misc
- Skill files (.md) ใน skills/ — cheat sheets สำหรับแต่ละ category
- Auto report generation (markdown)
- Session save/resume
- Structured audit log (JSONL)
- Intent classification (find_flag vs answer_question)
- Flag detection + auto-stop
- Knowledge base (จำ solves เก่า)
- Stats dashboard
- YAML config
- Benchmark system
- Green theme CLI + capybara mascot
- Slash command autocomplete (prompt_toolkit)
- Input filter (greeting/exit/typo detection)
- Batch mode, session replay, writeup export
- Docker sandbox support

### Known Bugs ที่ต้องแก้

**Bug 1: tool_calls response ไม่ครบ (แก้แล้ว?)**
- OpenAI API error: "tool_calls must be followed by tool messages responding to each tool_call_id"
- สาเหตุ: model ส่ง parallel tool_calls แต่ code ไม่ตอบกลับทุก tool_call_id
- ต้องตรวจสอบว่าแก้แล้วจริงหรือยัง

**Bug 2: Ctrl+C ไม่หยุดจริง (ยังไม่แก้)**
- กด Ctrl+C แล้ว agent ยังรันต่อ
- มีหลาย threads ที่ไม่ถูก kill
- ต้องใช้ global shutdown flag + signal handler ที่ครอบคลุมทุก thread
- Ctrl+C 1 ครั้ง → graceful stop
- Ctrl+C 2 ครั้ง → force stop
- Ctrl+C 3 ครั้ง → os._exit(1)

**Bug 3: Agent spawn ซ้อนกัน (ยังไม่แก้)**
- Agent รัน 3 instances ซ้อน — เห็น 3 plans, 3 solve loops พร้อมกัน
- สาเหตุ: Ctrl+C ไม่หยุด agent เดิม → input loop สร้างใหม่ทับ
- ต้องเพิ่ม solve lock — ห้าม spawn agent ใหม่ถ้ายัง solve อยู่

### วิธีหา root cause ของ Bug 2+3
```bash
grep -rn "Thread\|ThreadPool\|executor\|asyncio.gather\|asyncio.create_task\|concurrent" agent/ --include="*.py"
grep -rn "signal\|SIGINT\|KeyboardInterrupt" agent/ --include="*.py"
grep -rn "Orchestrator\|solve(" agent/ --include="*.py"
```

## Architecture

```
User Input → Input Filter → Classifier (category + intent)
                                ↓
                          Single Agent (orchestrator.py)
                                ↓
                          Reads skill .md file
                          (skills/forensics.md, web.md, etc.)
                                ↓
                          Tool execution (shell, python, file, network, browser)
                                ↓
                          Evidence Tracker (anti-hallucination)
                                ↓
                          Knowledge Base (learns from past solves)
                                ↓
                          Auto Report + Stats + Audit Log
```

## Project Structure

```
ctf-agent/
├── agent/
│   ├── orchestrator.py      # Main agent loop — CORE FILE
│   ├── parallel.py          # Parallel approach solving
│   ├── classifier.py        # Category + intent classification
│   ├── planner.py           # Attack planning + pivot system
│   └── context_manager.py   # Context window management
├── skills/                  # Skill files — category cheat sheets
│   ├── SKILL.md             # Core rules + thinking protocol
│   ├── forensics.md         # PCAP, stego, memory, disk
│   ├── web.md               # SQLi, XSS, SSTI, LFI, SSRF, JWT
│   ├── crypto.md            # RSA, AES, classical ciphers
│   ├── pwn.md               # Buffer overflow, ROP, format string
│   ├── reverse.md           # Ghidra, Z3, decompilers
│   ├── osint.md             # Username, image, domain recon
│   └── misc.md              # Encoding, jail escape, scripting
├── tools/
│   ├── registry.py          # ToolRegistry with function calling schemas
│   ├── shell.py             # Shell command execution
│   ├── python_exec.py       # Python code execution
│   ├── file_manager.py      # File read/write/list
│   ├── network.py           # Network tools
│   ├── browser.py           # Playwright browser automation
│   ├── recon.py             # nmap, whatweb, gobuster, nikto
│   ├── code_analyzer.py     # White-box source code analysis
│   ├── error_analyzer.py    # Error detection + adaptation
│   ├── output_summarizer.py # Summarize long outputs
│   ├── evidence_tracker.py  # Track what data came from tools
│   ├── response_parser.py   # Parse LLM responses
│   ├── web_state.py         # Web session state tracking
│   ├── answer_user.py       # User answer submission
│   ├── submit_deliverable.py # Pipeline agent completion signal
│   ├── capybara_generator.py # Mascot generation
│   └── base.py              # Base tool class
├── prompts/
│   ├── system.py            # System prompt builder
│   └── strategies.py        # Strategy/approach prompts
├── knowledge/
│   ├── base.py              # Knowledge base (past solves)
│   ├── extractor.py         # Auto-extract techniques from solves
│   └── exploit_templates.py # Pre-built exploit payloads
├── config_yaml/
│   └── loader.py            # YAML config loader
├── configs/
│   └── example.yaml         # Example config file
├── utils/
│   ├── token_counter.py     # Token counting
│   ├── cost_tracker.py      # API cost tracking
│   ├── session_manager.py   # Session save/load/resume
│   ├── audit_log.py         # Structured audit logging
│   ├── logger.py            # Logging setup
│   ├── flag_extractor.py    # Flag pattern extraction
│   ├── file_detector.py     # File type detection
│   └── dashboard.py         # Stats dashboard display
├── stats/
│   └── tracker.py           # Performance stats
├── benchmark/
│   ├── runner.py            # Benchmark runner
│   ├── check.py             # CI quality gates
│   └── challenges.json      # Test challenges
├── sandbox/
│   ├── docker_manager.py    # Docker sandbox management
│   └── Dockerfile           # Sandbox image definition
├── report/
│   └── generator.py         # Markdown report generator
├── ui/
│   ├── chat.py              # Chat loop + callbacks
│   ├── display.py           # Output formatting, VERSION
│   ├── commands.py          # Slash command handlers
│   ├── input_handler.py     # prompt_toolkit input
│   ├── input_filter.py      # Greeting/exit/typo filter
│   ├── tree.py              # TaskTree renderer (ANSI)
│   ├── mascot.py            # Capybara ASCII art
│   └── spinner.py           # Loading spinner
├── logs/                    # Session logs
├── reports/                 # Generated solve reports
├── sessions/                # Saved sessions
├── main.py                  # Entry point
├── config.py                # App config/constants
└── requirements.txt
```

## Key Design Principles

### "Be Lazy" Philosophy
Q ออกแบบมาให้ solve ใน 3-6 steps ไม่ใช่ 20+ steps
- Run 1-2 commands → form hypothesis → verify → answer
- ห้ามรัน command "just to see what happens"
- Wrong answer is worse than no answer

### Thinking Protocol
Agent ต้องใช้ <think> tags ก่อนทุก action:
- First step: GOAL, PLAN, SCOPE, DONE WHEN
- Every step: LEARNED, HYPOTHESIS, NEXT, DONE?
- ถ้า DONE? = yes → stop immediately

### No Evidence, No Answer
ห้ามตอบสิ่งที่ไม่มี evidence จาก tool output
ทุก claim ต้อง trace กลับไปหา tool output ได้

### Observe → Hypothesize → Test
ทุก step ต้องตาม cycle:
OBSERVE (output) → HYPOTHESIZE (vulnerability) → TEST (command) → CONCLUDE

## Model Configuration

Default models (configurable via env vars):
- `FAST_MODEL`: gpt-4o-mini (classification, reports)
- `DEFAULT_MODEL`: gpt-4o (main solving)
- `REASONING_MODEL`: o3 (hard challenges)

Pricing tracked for: gpt-4o, gpt-4o-mini, o3, o3-mini, gpt-4-turbo

## Performance History

| Version | Steps | Tokens | Cost | Accuracy |
|---------|-------|--------|------|----------|
| v0.1 single agent | 34 | 258k | $0.67 | wrong |
| v0.2 bug fixes | ~15 | 21k | $0.05 | correct |
| v0.3 multi-agent | 19 | 73k | $0.19 | wrong (agents didn't share data) |
| v0.4 skill-based | **3** | **13.6k** | **$0.04** | correct |

**Key lesson: Simple > Complex.** Multi-agent pipeline made Q WORSE. Single agent + good skill prompts = best results.

## Roadmap / TODO

### Priority: Bug Fixes
1. ~~tool_calls response ไม่ครบ~~ (ตรวจสอบว่าแก้แล้ว)
2. Ctrl+C ไม่หยุดจริง + agent spawn ซ้อน
3. Output ซ้ำหลายบรรทัดหลัง Ctrl+C

### Priority: Intelligence Upgrades
1. Self-reflection (think before act) — แก้ SKILL.md
2. Error recovery & adaptation — tools/error_analyzer.py
3. Context summarization — tools/output_summarizer.py
4. Chain-of-thought via <think> tags

### Priority: Features
1. Browser vision mode — screenshot + GPT vision สำหรับ flag ในรูป
2. Watch mode — เปิด browser ให้ดู Q ทำงาน (--watch flag)
3. Multi-provider support — เพิ่ม Claude API, Gemini

### Priority: GitHub Release
1. Professional README + GIF demo
2. Benchmark กับ real CTF platforms (picoCTF, HackTheBox)
3. Sample solve reports

## Commands Reference

```
/help          All commands
/stats         Performance dashboard
/benchmark     Run benchmark
/config        Show/edit config
/model         Switch AI model
/knowledge     Knowledge base
/resume        Resume session
/report        View report
/audit         Audit log
/repo <path>   Set source code for white-box
/verbose       Toggle verbose
/cost          Session cost
/exit          Quit
```

## Running

```bash
cd ctf-agent
pip install -r requirements.txt

# Set API key
export OPENAI_API_KEY=your_key

# Run (interactive chat mode — default)
python3 main.py

# With options
python3 main.py --verbose          # Full LLM thinking + tool output
python3 main.py --config configs/my-config.yaml
python3 main.py --repo /path/to/app # White-box analysis

# Batch/utility commands
python3 main.py --batch challenges.json     # Solve multiple challenges
python3 main.py --benchmark bench.json      # Run benchmark
python3 main.py --sessions                  # List saved sessions
python3 main.py --replay SESSION_ID         # Replay session
python3 main.py --resume SESSION_ID         # Resume paused/failed session
python3 main.py --writeup SESSION_ID -o out.md  # Export writeup
python3 main.py --build                     # Build Docker sandbox
python3 main.py --tools                     # List available tools
```

## Style Guide

- Mascot: Green capybara (ASCII art in welcome screen)
- Tone: Casual, bro-style ("bro help me find the flag")
- Language: Code in English, comments can be Thai
- Agent output: Clean, minimal — show step progress with tree-style

## When Making Changes

- **แก้ skill files** → test กับ challenge จริงว่า agent ยัง solve ได้
- **แก้ orchestrator** → ตรวจสอบ messages array ว่า tool_calls มี response ครบ
- **เพิ่ม tool ใหม่** → register ใน ToolRegistry (tools/registry.py)
- **แก้ UI** → test ทั้ง normal flow, Ctrl+C, error cases
- **Benchmark** → รัน python3 main.py --benchmark benchmark/challenges.json ก่อน commit

## Tech Stack

- Python 3.11+
- OpenAI API (gpt-4o / gpt-4o-mini / o3)
- Playwright (browser automation)
- prompt_toolkit (CLI input)
- PyYAML (config)
- Rich (terminal output)

## Context from Development Sessions

Q ถูกพัฒนาผ่าน 3 sessions หลัก:
1. Initial build — architecture, basic agent, UI
2. Refactor — multi-agent (failed) → single agent + skills (success)
3. Polish — features (benchmark, knowledge base, stats, browser, config)

Core insight: **ให้ model ทำงานน้อยที่สุดแต่ฉลาดที่สุด** ผ่าน skill files ที่บอกตรงๆ ว่า "เจอ pcap → tshark -q -z conv,ip ก่อน" ไม่ต้องคิดเอง
