"""Strategy and pivot prompts.

Provides a graduated set of prompts injected when the agent stalls,
from gentle nudges to full strategy overhauls.
"""

# --- Level 1: First stall (5 iterations) ---
STALL_PIVOT_PROMPT = """\
## Strategy Pivot Required

You have been working on this challenge for several iterations without
finding the flag. It's time to reconsider your approach.

Please:
1. **Summarize** what you have discovered so far
2. **List** approaches you have already tried and why they failed
3. **Identify** at least 2 alternative strategies you haven't tried
4. **Choose** the most promising alternative and explain why
5. **Execute** the new strategy

Common pivots to consider:
- If stuck on crypto: try a different attack (e.g., padding oracle, known-plaintext)
- If stuck on web: check for different injection points, try different HTTP methods
- If stuck on reversing: try dynamic analysis instead of static (or vice versa)
- If stuck on pwn: check for different vulnerability types (format string, use-after-free)
- If stuck on forensics: try different layers (network, file system, memory)
- Look for hints in challenge name, description, or source code comments
"""

# --- Level 2: Second stall (10 iterations) — step back ---
STEP_BACK_PROMPT = """\
## Step Back and Re-Evaluate

You have been stuck for a long time. Stop all current work and do a
full review.

### Step-back Protocol:
1. **Forget your current hypothesis** — it may be wrong.
2. **Re-read** the original challenge description word by word.
   - Is there a pun or wordplay in the name?
   - Does the description hint at something you missed?
3. **Re-examine** all data you've collected so far:
   - Are there files you haven't fully analyzed?
   - Did any tool output contain data you overlooked?
   - Could the flag be in an encoding you didn't try?
4. **Consider mis-classification**: Maybe this isn't the challenge type
   you assumed. A "crypto" challenge might actually be steganography.
   A "web" challenge might require reversing a client-side binary.
5. **Try the simplest possible approaches**:
   - `strings <file> | grep -i flag`
   - Decode as base64, hex, rot13
   - Check file metadata with exiftool
   - Look at every file as raw hex

Think completely fresh. What would a beginner try first?
"""

# --- Level 3: Approach swap (static ↔ dynamic) ---
APPROACH_SWAP_PROMPT = """\
## Approach Swap

Your current approach (static/manual analysis) is not working.
Switch to the opposite methodology:

- **Were you doing static analysis?** → Try dynamic analysis:
  - Run the binary with different inputs
  - Use ltrace/strace to observe behavior
  - Attach a debugger and step through
  - Fuzz with random inputs

- **Were you doing manual analysis?** → Try automated tools:
  - Use angr for symbolic execution
  - Use Z3/SAT solver for constraints
  - Use sqlmap for SQL injection
  - Use automated fuzzing

- **Were you using automated tools?** → Try manual analysis:
  - Read the source code line by line
  - Manually trace the logic
  - Hand-craft specific test inputs
  - Look for logic bugs that tools miss

Pick the opposite of what you've been doing and try it immediately.
"""

# --- Level 4: Re-classification prompt ---
RECLASSIFY_PROMPT = """\
## Re-Classification Required

The initial classification of this challenge may have been wrong.
Consider these possibilities:

- What you thought was **crypto** might actually be:
  → Encoding (base64/hex layers, not real crypto)
  → Steganography (hidden data, not encryption)

- What you thought was **web** might actually be:
  → Binary exploitation (WebAssembly, client-side binary)
  → Crypto (JWT, session tokens, custom encryption)

- What you thought was **reverse** might actually be:
  → Pwn (the binary has an exploitable vulnerability)
  → Forensics (the binary is a container for hidden data)

- What you thought was **forensics** might actually be:
  → Steganography (the image IS the challenge)
  → Crypto (encoded data that needs a specific cipher)

Re-examine the challenge with fresh eyes. What category does it
ACTUALLY belong to? Adjust your strategy accordingly.
"""

# --- Level 5: Model escalation hint ---
MODEL_ESCALATION_PROMPT = """\
## Deep Reasoning Mode

This challenge requires deeper reasoning. A more powerful model has
been engaged. Take advantage of this by:

1. **Think through the full problem** from first principles
2. **Write out the math** if this involves crypto or binary analysis
3. **Consider edge cases** you may have missed
4. **Build a complete exploit** rather than testing fragments

You have more reasoning power now. Use it to solve the challenge
in one focused attempt.
"""

# --- Final attempt ---
FINAL_ATTEMPT_PROMPT = """\
## Final Attempts

You are approaching the maximum iteration limit. Focus on:
1. Re-examine any data you've already collected for missed flags
2. Try simple approaches: strings, grep for flag patterns, base64 decode
3. Check if the flag is hidden in metadata, comments, or alternate data streams
4. Consider if the challenge has multiple stages and you missed one

This is your last chance — prioritize quick wins.
"""

# --- Context summary ---
CONTEXT_SUMMARY_REQUEST = """\
The conversation is getting long. Please provide a concise summary of:
1. **Challenge description**: What is the challenge about?
2. **Key discoveries**: What have you found so far?
3. **Current hypothesis**: What are you currently investigating?
4. **Dead ends**: What approaches didn't work and why?
5. **Next steps**: What should be tried next?

Be concise but include all important technical details like addresses,
ports, offsets, keys, or partial flag data.
"""

# --- Ordered pivot sequence ---
PIVOT_SEQUENCE: list[str] = [
    STALL_PIVOT_PROMPT,       # Level 1: basic pivot
    STEP_BACK_PROMPT,         # Level 2: full re-evaluation
    APPROACH_SWAP_PROMPT,     # Level 3: flip methodology
    RECLASSIFY_PROMPT,        # Level 4: maybe wrong category
]
