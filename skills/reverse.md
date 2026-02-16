# CTF Reverse Engineering Skill

Quick reference. Identify binary type, decompile, find logic, extract flag.

> **How to Use This Skill File:** This is a REFERENCE, not a script.
> Do NOT follow it top to bottom. Read the relevant section for YOUR
> challenge, understand the technique, adapt to THIS specific target,
> and form a hypothesis FIRST, then pick the right tool. Pick tools
> based on what you OBSERVE, not based on the order listed here.

---

## Recon (ALWAYS first)

```bash
file binary                      # ELF? PE? .NET? Java? Python?
strings -n 8 binary | head -50   # Quick flag/password check
strings binary | grep -i flag
strings binary | grep -i pass
```

**Branch by file type:**

| file output | Type | Next step |
|---|---|---|
| ELF 64-bit | Linux binary | Ghidra / r2 / GDB |
| PE32 | Windows binary | Ghidra / x64dbg |
| .class / .jar | Java | `jd-gui` or `cfr` decompiler |
| .pyc | Python bytecode | `uncompyle6` or `decompyle3` |
| .NET / Mono | C# binary | `dnSpy` or `ILSpy` |
| APK | Android | `jadx` or `apktool` |

---

## Static Analysis

### Ghidra (primary tool)
```bash
ghidra                           # GUI — import binary, auto-analyze
# Focus on:
# 1. main() function
# 2. Functions that compare strings or check conditions
# 3. XOR loops, encoded data sections
# 4. String references (Window → Defined Strings)
```

### Radare2 (CLI alternative)
```bash
r2 -A binary                    # Open + analyze
afl                              # List all functions
pdf @main                        # Decompile main
pdf @sym.check_password          # Decompile specific function
iz                               # List strings in data section
axt @str.flag                    # Cross-references to "flag" string
VV @main                         # Visual graph mode
```

---

## Dynamic Analysis

### GDB
```bash
gdb ./binary
b main
r
# Step through, watch registers and memory
ni                               # Next instruction
x/s $rdi                         # String argument (64-bit first arg)
x/s $rsi                         # Second argument
info registers
```

### ltrace / strace
```bash
ltrace ./binary                  # Library calls (strcmp, memcmp = key!)
strace ./binary                  # System calls
ltrace -s 200 ./binary           # Show longer strings
```

**Key pattern:** If `ltrace` shows `strcmp("your_input", "s3cr3t_fl4g")` → that's the answer.

---

## Common Patterns

### XOR Obfuscation
```python
# Encrypted data XORed with key
data = [0x12, 0x45, 0x67, ...]   # From binary
key = [0x41, 0x42, 0x43]         # Found in binary or brute-forced
flag = ''.join(chr(d ^ key[i % len(key)]) for i, d in enumerate(data))
print(flag)
```

### Character-by-character check
```python
# Binary checks each char: if input[i] == expected[i]
# Side-channel: use ltrace or timing to leak one char at a time
# Or: extract expected array from binary data section
```

### Simple math transform
```python
# flag[i] = (input[i] + 5) ^ 0x37
# Reverse: input[i] = (flag[i] ^ 0x37) - 5
encoded = [0x72, 0x65, 0x76, ...]  # From binary
flag = ''.join(chr((c ^ 0x37) - 5) for c in encoded)
```

### Anti-debugging / obfuscation
```bash
# ptrace check — patch the check or use:
LD_PRELOAD=./fake_ptrace.so ./binary
# Or in GDB: set a breakpoint on ptrace, return 0

# UPX packed
upx -d binary                   # Unpack

# Strip symbols
# Use Ghidra auto-analysis to recover function boundaries
```

---

## Java Reversing

```bash
# .class file
jd-gui file.class                # GUI decompiler
cfr file.class                   # CLI decompiler

# .jar file
jar tf file.jar                  # List contents
jd-gui file.jar                  # Decompile all
unzip file.jar -d extracted/     # Extract then decompile
```

---

## Python Reversing

```bash
# .pyc file
uncompyle6 file.pyc > source.py
# or
decompyle3 file.pyc > source.py
# or
pycdc file.pyc > source.py       # For newer Python versions

# PyInstaller executable
pyinstxtractor binary.exe        # Extract .pyc files
# Then decompile the main .pyc

# PyArmor protected
# Use PyArmor-Unpacker if available
```

---

## .NET / C# Reversing

```bash
# Use dnSpy (Windows) or ILSpy
ilspycmd binary.exe              # CLI decompiler
# Focus on Main(), check for string operations and comparisons
```

---

## Android APK

```bash
# Decompile
jadx -d output/ app.apk          # Java source
apktool d app.apk                # Resources + smali

# Look for:
# - res/values/strings.xml (hardcoded secrets)
# - AndroidManifest.xml (activities, permissions)
# - Source code in jadx output
```

---

## Extracting Data from Binary

```python
# Read specific bytes from binary
with open('binary', 'rb') as f:
    f.seek(0x1234)               # Offset found in Ghidra
    data = f.read(32)
    print(data)
    print(data.hex())

# Or with r2
# r2 binary
# px 32 @ 0x1234                 # Print hex at offset
# ps @ 0x1234                    # Print string at offset
```

---

## Z3 for Constraint Solving

```python
# When binary has complex checks on input
from z3 import *

flag = [BitVec(f'f{i}', 8) for i in range(20)]
s = Solver()

# Add constraints from decompiled code
# e.g., flag[0] + flag[1] == 0xc3
s.add(flag[0] + flag[1] == 0xc3)
s.add(flag[0] ^ flag[2] == 0x55)
# ... add all constraints

# Printable ASCII constraint
for f in flag:
    s.add(f >= 0x20, f <= 0x7e)

if s.check() == sat:
    m = s.model()
    print(''.join(chr(m[f].as_long()) for f in flag))
```

---

## angr (automatic solver)

```python
import angr

proj = angr.Project('./binary', auto_load_libs=False)
state = proj.factory.entry_state()
simgr = proj.factory.simulation_manager(state)

# Find path to "Correct!" and avoid "Wrong!"
simgr.explore(
    find=0x401234,       # Address of success
    avoid=0x401256       # Address of failure
)

if simgr.found:
    found = simgr.found[0]
    print(found.posix.dumps(0))  # stdin that reaches success
```

---

## CRITICAL RULES FOR AGENT

1. **strings first** — flag might be in plaintext
2. **ltrace catches strcmp** — often reveals the answer immediately
3. **Decompile before debugging** — understand logic first
4. **Extract encoded data from binary** — then reverse the transform in Python
5. **Use Z3/angr for complex checks** — don't brute force manually
