# Q Roadmap

> Last updated: 2026-03-06

## The Big Picture

Q v0.5.0 is solid — the "be lazy" philosophy with skill-based prompts works (3 steps, $0.04/challenge). But compared to 2026 state-of-the-art CTF agents (EnIGMA/NYU, ATLANTIS/DARPA, Buttercup/Trail of Bits) and CLI agents (Claude Code), there are clear gaps in **intelligence**, **UX**, and **reliability**.

References:
- [EnIGMA](https://arxiv.org/abs/2409.16165) — NYU, ICML 2025, 13.5% solve rate on 200 challenges
- [ATLANTIS](https://www.darpa.mil/news/2025/ai-cyber-challenge-winners-def-con-33) — DARPA AIxCC 1st place ($4M)
- [Buttercup](https://blog.trailofbits.com/2025/08/09/trail-of-bits-buttercup-wins-2nd-place-in-aixcc-challenge/) — Trail of Bits, 2nd place, open source, runs on a laptop
- [Byte Breach autonomous pwning](https://bytebreach.com/posts/autonomous-pwning/) — Claude Sonnet 4.5 scores 74% vs GPT 58%
- [Claude Code architecture](https://newsletter.pragmaticengineer.com/p/how-claude-code-is-built)

---

## Tier 1: Quick Wins (1-2 days each)

### 1. Checkpoint & Rewind System
**Inspired by:** Claude Code's killer UX feature

Before every major action (tool call, pivot, model escalation), snapshot the agent state. Let user `/rewind` to try a different approach.

**Why it matters for CTF:** User sees agent going down wrong path (e.g. trying SQLi when it's actually SSTI) → rewind → hint "try template injection" → saves tokens + cost.

```
Implementation:
- Save (messages, scratchpad, iteration, cost) before each tool call
- /rewind [n] — roll back n steps
- /rewind list — show checkpoints with 1-line summaries
- Store in sessions/{sid}/checkpoints/

Files to change:
- agent/orchestrator.py — snapshot before tool execution
- ui/commands.py — /rewind command
- utils/session_manager.py — checkpoint storage
```

### 2. Anti-Soliloquy Guard
**Inspired by:** EnIGMA (NYU, ICML 2025) finding that agents hallucinate observations

Agents claim to see output without actually running a command. Q's evidence tracker catches false claims, but not this pattern.

```
Implementation:
- In orchestrator, after each LLM response:
  if assistant says "I can see..." or "the output shows..."
  but no tool was called since last response → inject warning:
  "You haven't run any command yet. Run a tool first."
- Track last_tool_iteration vs current_iteration

Files to change:
- agent/orchestrator.py — add guard in _react_loop()
```

### 3. Context-Aware Spinner Verbs
**Inspired by:** Claude Code's custom spinner verbs

Instead of generic "Thinking...", show phase-specific status:

```
Classifying challenge...  → Forensics detected
Planning attack...        → 3-step plan ready
Analyzing pcap...         → Found 847 packets
Crafting exploit...       → Building ROP chain
Verifying flag...         → Flag confirmed!

Implementation:
- Map tool names → verb phrases
- Agent already reports phases via callbacks — make spinner reflect them

Files to change:
- ui/spinner.py — phase-aware verb mapping
- ui/chat.py — pass phase info to spinner
```

### 4. Desktop Notification on Completion
CTF solves can take minutes. User switches to another terminal.

```
Implementation:
- After solve completes: notify-send (Linux) / osascript (macOS)
- "Q solved it! Flag: HTB{...}" or "Q failed after 12 steps ($0.08)"
- Optional sound

Files to change:
- ui/chat.py — add notification after solve
- New: utils/notify.py — cross-platform notification
```

### 5. Persistent History Across Sessions
prompt_toolkit supports `FileHistory`. Currently Q loses input history on restart.

```
Implementation:
- FileHistory(~/.q/history) in prompt_toolkit session
- Ctrl+R to search previous challenge descriptions

Files to change:
- ui/input_handler.py — add FileHistory (3 lines)
```

---

## Tier 2: Intelligence Upgrades (3-5 days each)

### 6. Interactive Agent Tools (IATs)
**Inspired by:** EnIGMA's core innovation — the biggest technical gap in Q

Currently Q runs `gdb` as one-shot shell commands. But real CTF solving needs **interactive sessions** — set breakpoints, step, inspect memory, all while the shell stays open.

```
New tools:

tools/debugger.py — Wraps gdb/pwndbg via pexpect
  Actions: start, breakpoint, run, step, next, continue,
           print, backtrace, examine, info_registers, raw_command

tools/pwntools_session.py — Persistent pwntools connection
  Actions: connect, send, sendline, recv, recvuntil,
           interactive, close, elf_info, rop_gadgets

tools/netcat_session.py — Persistent TCP/UDP session
  Actions: connect, send, recv, recv_until, close

Key design:
- Each tool maintains a persistent subprocess (pexpect)
- Persists across agent iterations
- Agent can switch between debugger and shell freely
- Just like a human CTF player

Files to create:
- tools/debugger.py
- tools/pwntools_session.py
- tools/netcat_session.py
- Update tools/registry.py to register them
```

**Impact:** Unlocks pwn/reverse challenges that are currently impossible for Q.

### 7. RAG over CTF Writeups
**Inspired by:** Byte Breach's results showing RAG materially improves solve rates

Q's current knowledge base is keyword-only search. Replace with vector embeddings.

```
Implementation:

knowledge/embeddings.py — Chroma DB with sentence-transformers
- Index: 1000+ CTF writeups (CTFTime, picoCTF, HackTheBox)
- Schema: {category, technique, difficulty, steps, writeup_text}
- On classify → retrieve top 3 similar past solves
- Inject as "Reference Solves" section in system prompt
- Auto-index Q's own past solves (from sessions/)

Scraping pipeline:
- CTFTime API for writeup URLs
- Markdown extraction → chunk → embed

Cost: sentence-transformers runs locally (no API cost). Chroma is pure Python.

Dependencies: chromadb, sentence-transformers
Files to create: knowledge/embeddings.py, knowledge/scraper.py
Files to change: knowledge/base.py, prompts/system.py, agent/orchestrator.py
```

### 8. Reflection Loop (Self-Critique)
**Inspired by:** Reflection pattern from agentic AI design patterns

Currently Q acts → observes → acts. Add a **critique step** between observe and next action:

```
Current:  Think → Act → Observe → Think → Act → ...
Proposed: Think → Act → Observe → Critique → Think → Act → ...

Critique prompt (injected after every 3rd iteration):
"Review your last 3 steps. What worked? What didn't?
 Are you making progress or going in circles?
 Rate your confidence: low/medium/high.
 If low, what would you do differently?"

If confidence == "low" for 2 consecutive critiques → trigger pivot early

Why every 3rd step? Cost. Catches stalls without doubling token usage.

Files to change:
- agent/orchestrator.py — inject critique message every 3 iterations
- prompts/system.py — critique prompt template
```

### 9. Hypothesis-Driven Pivoting
Current pivot system is **generic** — always follows the same 7-level escalation regardless of WHY the agent is stuck.

```
Current:  stuck → "try different approach" → "step back" → ...
Proposed: stuck → analyze failure type → targeted pivot

Failure types:
- TOOL_ERROR:       Command failed → suggest alternative tool
- NO_OUTPUT:        Command succeeded but empty → broaden search
- WRONG_CATEGORY:   Nothing works → reclassify immediately (skip levels)
- PARTIAL_PROGRESS: Found something but stuck → focus deeper
- REPEATED_ACTION:  Doing same thing → force different technique

Implementation:
- Use fast model to classify failure type from last 3 tool outputs
- Select pivot strategy based on failure type (not escalation level)

Files to change:
- agent/planner.py — failure classification + targeted pivot prompts
- agent/orchestrator.py — pass failure context to pivot manager
```

### 10. Procedural Memory (Learned Techniques)
**Inspired by:** MIRIX multi-agent memory architecture

Beyond remembering facts (semantic), Q should learn **how to solve** from experience:

```
knowledge/procedural.py

After each SUCCESSFUL solve:
1. Extract technique chain: ["file analysis", "strings grep", "base64 decode"]
2. Store as procedure: {trigger, steps, success_rate}
3. On similar future challenges, inject as "Suggested Approach"

After each FAILED solve:
1. Extract what was tried and why it failed
2. Store as anti-pattern: {trigger, outcome, lesson}

Over time, Q builds an INSTINCT — it doesn't deliberate on common patterns.

Files to create: knowledge/procedural.py
Files to change: agent/orchestrator.py, prompts/system.py
```

---

## Tier 3: Architecture Upgrades (1-2 weeks each)

### 11. Streaming Output
Q currently waits for full LLM response before displaying. Claude Code streams token-by-token. **Huge** perceived performance difference.

```
Implementation:
- Use OpenAI streaming API (stream=True)
- orchestrator._call_llm() yields chunks
- UI renders incrementally
- Verbose mode: stream everything
- Minimal mode: spinner until tool_call, then show result

Files to change:
- agent/orchestrator.py — streaming _call_llm()
- ui/chat.py — incremental rendering
- ui/display.py — streaming text support
```

### 12. Multi-Provider Support
Q is locked to OpenAI. Claude Sonnet 4.5 scores **74% on autonomous pwning** vs GPT's 58%.

```
Model routing strategy:
- Classification: haiku/flash (cheapest)
- Easy challenges: gpt-4o-mini or haiku
- Hard pwn/reverse: claude-sonnet-4-5 (best at binary exploitation)
- Crypto/math: o3 (best at reasoning)
- Fallback: if one provider is down, auto-switch

Implementation:
- Abstract LLM client interface
- Provider implementations: OpenAI, Anthropic, Google
- Config-driven model routing per category + difficulty

Files to create: agent/providers/{openai,anthropic,google}.py, agent/providers/base.py
Files to change: config.py, agent/orchestrator.py
```

### 13. Hooks System (Safety + Extensibility)
**Inspired by:** Claude Code's hooks system

Let users define pre/post actions for safety and integration:

```yaml
# configs/hooks.yaml
hooks:
  pre_tool_call:
    - match: "shell"
      block_if: "rm -rf|mkfs|dd if="
      message: "Blocked: destructive command"

  post_solve:
    - run: "notify-send 'Q finished! {status}'"
    - run: "curl -X POST https://discord.webhook/... -d '{result}'"

  post_flag:
    - run: "python3 submit_to_ctfd.py {flag}"
```

**Use cases:**
- Auto-submit flags to CTFd/CTFTime
- Discord/Slack notifications
- Block dangerous commands
- Custom logging/metrics

```
Files to create: agent/hooks.py, configs/hooks.yaml
Files to change: agent/orchestrator.py, tools/registry.py
```

### 14. Watch Mode (Live Exploitation Viewer)
Make Q's work **visible and cinematic**:

```
python3 main.py --watch

Opens a Rich Live display with panels:
┌─ Agent Thinking ──────────────┬─ Tool Output ─────────────────┐
│ <think>                       │ $ strings binary | grep flag   │
│ LEARNED: Binary is x86_64 ELF│ flag{not_the_real_flag}        │
│ HYPOTHESIS: Stack overflow    │ possible_flag_here             │
│ NEXT: Check protections       │                                │
│ </think>                      │                                │
├─ Progress ────────────────────┼─ Evidence ────────────────────┤
│ ■ Classified: pwn             │ IP: 10.10.10.1                │
│ ■ Plan: 3 steps               │ Flag pattern: HTB{...}         │
│ ├ checksec → NX disabled      │ File: vuln_binary              │
│ ├ find overflow offset        │ Vuln: buffer overflow (0x48)   │
│ └ craft exploit               │                                │
│ ◆ Step 2/3 — $0.02           │                                │
└───────────────────────────────┴───────────────────────────────┘

Files to create: ui/watch.py
Files to change: ui/chat.py, main.py (--watch flag already exists)
```

### 15. Symbolic Verification Layer
**Inspired by:** DARPA AIxCC winner ATLANTIS — hybrid symbolic + neural

Pair LLM reasoning with formal analysis tools:

```
tools/symbolic.py

Actions:
- angr_analyze: Load binary in angr, find paths to target
- z3_solve: Solve constraint systems (crypto challenges)
- checksec: Binary protection analysis
- ropper_gadgets: Find ROP gadgets

Pattern:
1. LLM hypothesizes: "There's a buffer overflow at offset 0x48"
2. Symbolic tool verifies: angr confirms reachable path
3. LLM crafts exploit with verified constraints
4. Evidence tracker records both LLM claim AND symbolic proof

Files to create: tools/symbolic.py
Dependencies: angr, z3-solver, ropper
```

---

## Priority Matrix

| # | Feature | Impact | Effort | Priority |
|---|---------|--------|--------|----------|
| 1 | Checkpoint & Rewind | Huge (trust + UX) | 1 day | **P0** |
| 2 | Anti-Soliloquy Guard | High (correctness) | 0.5 day | **P0** |
| 6 | Interactive Agent Tools | Huge (unlocks pwn/rev) | 5 days | **P0** |
| 3 | Context-Aware Spinner | Medium (UX polish) | 0.5 day | **P1** |
| 5 | Persistent History | Medium (QoL) | 0.5 day | **P1** |
| 8 | Reflection Loop | High (intelligence) | 2 days | **P1** |
| 9 | Hypothesis-Driven Pivoting | High (intelligence) | 2 days | **P1** |
| 7 | RAG over Writeups | High (solve rate) | 3 days | **P1** |
| 10 | Procedural Memory | High (learning) | 3 days | **P2** |
| 11 | Streaming Output | Medium (UX) | 2 days | **P2** |
| 14 | Watch Mode | High (demo + UX) | 3 days | **P2** |
| 4 | Desktop Notifications | Low (QoL) | 0.5 day | **P2** |
| 12 | Multi-Provider | Medium (flexibility) | 5 days | **P3** |
| 13 | Hooks System | Medium (extensibility) | 3 days | **P3** |
| 15 | Symbolic Verification | High (correctness) | 1 week | **P3** |

---

## v0.6.0 Release Scope

Ship as **v0.6.0 — "The Intelligence Update"**:

- [x] Checkpoint & Rewind (P0)
- [x] Anti-Soliloquy Guard (P0)
- [x] Interactive Agent Tools — gdb + pwntools + netcat (P0)
- [x] Context-Aware Spinner (P1)
- [x] Persistent History (P1)
- [x] Reflection Loop every 3 iterations (P1)
- [x] Hypothesis-Driven Pivoting (P1)

### v0.7.0 — "The Memory Update":

- [x] RAG over CTF Writeups
- [x] Procedural Memory
- [x] Streaming Output
- [x] Watch Mode

### v0.8.0 — "The Platform Update":

- [x] Multi-Provider Support
- [x] Hooks System
- [x] Symbolic Verification Layer

### v0.9.0 — "The AI Security Update":

- [x] AI category (`ai`) in classifier + skills
- [x] `llm_interact` tool (9 actions: send_prompt, multi_turn, spray, auto_attack, chat_web, analyze_response, export_history, reset_session, show_history)
- [x] Payload library (40+ prompt injection payloads across 8 categories)
- [x] Deep-scan (auto-detect flags in base64, hex, ROT13, reversed text)
- [x] `/flag` command (interactive flag format selector, custom regex)
- [x] NCSA{} flag pattern support
- [x] Team system — reactive leader, task DAG, MessageBus, presets for 7 categories
- [x] E2E tests with live HTTP chatbot server

### v1.0.0 — "Competition Ready" (planned):

- [x] AI team preset in TEAM_PRESETS
- [x] Team mode tests (30 tests in test_team.py)
- [x] Config validation (settings key whitelist, typo warnings)
- [x] Lazy tool loading (from_subset uses factories, not full instantiation)
- [x] Provider fallback recursion guard
- [x] Summarization cost optimization (uses fast_model)
- [x] Exception handling audit (narrowed ~20 broad catches, eliminated silent passes)
- [ ] Streaming/SSE support for `llm_interact`
- [ ] Rate-limit tracking per target
- [ ] Benchmark suite for AI challenges

---

## Performance Targets

| Metric | v0.5.0 | v0.8.0 | v0.9.0 (current) |
|--------|--------|--------|-------------------|
| Easy challenges | 3 steps, $0.04 | 3 steps, $0.04 | 2 steps, $0.02 |
| Medium challenges | ~10 steps, ~$0.15 | 6 steps, $0.08 | 5 steps, $0.06 |
| Hard pwn/reverse | Mostly fails | 50% solve rate | 65% solve rate |
| Interactive exploits | Not supported | Supported (IATs) | + symbolic verify |
| AI security | Not supported | Not supported | Supported (llm_interact + payloads) |

---

## Key Lessons from Research

1. **Simple > Complex** — Q v0.3 multi-agent was worse than v0.4 single-agent. Don't repeat this mistake. Add complexity only where it's proven to help (IATs, RAG).

2. **EnIGMA's IATs are the #1 gap** — Interactive tool sessions (gdb, pwntools, netcat) are what separate toy CTF agents from real ones.

3. **RAG works** — Byte Breach proved it. Models without writeup context underperform significantly.

4. **Checkpoints build trust** — Claude Code's most loved feature. Users will let Q try ambitious things if they can rewind.

5. **Claude > GPT for binary exploitation** — 74% vs 58%. Multi-provider support is worth building.

6. **$181/point is achievable** — Buttercup (Trail of Bits) proved competitive CTF AI doesn't need expensive models. Smart tool use > raw model power.
