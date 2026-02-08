"""Reverse engineering playbook — expert-level methodology."""

PLAYBOOK = r"""\
## Reverse Engineering Playbook

You are solving a reverse engineering CTF challenge. Combine static and
dynamic analysis to understand the program logic, then extract or
generate the correct input/flag.

---

### PHASE 1: Reconnaissance

```bash
# Step 1: File identification
file ./binary
# ELF 64-bit? 32-bit? statically linked? stripped?
# PE32? .NET? Java JAR? Python .pyc?

# Step 2: Quick string scan
strings ./binary | head -50
strings -n 8 ./binary | grep -iE "flag|pass|key|correct|wrong|win|secret|try"

# Step 3: Check if packed
# UPX signature:
strings ./binary | grep "UPX"
# If packed:
upx -d ./binary -o ./binary_unpacked

# Step 4: Identify language/compiler
# Go: look for "runtime.gopanic", "main.main"
# Rust: look for "core::panicking", mangled symbols with "17h"
# C++: mangled symbols starting with "_Z"
# .NET: "mscorlib", PE with CLI header
# Python .pyc: magic bytes differ by version
# Java .class: magic 0xCAFEBABE

# Step 5: List functions
nm ./binary 2>/dev/null | grep ' T '       # exported functions
r2 -A ./binary -c 'afl' -q                 # radare2 function list
objdump -d ./binary | grep '<.*>:'          # function entries
```

---

### PHASE 2: Static Analysis

#### 2.1 Decompilation with radare2
```bash
# Full analysis + decompile main
r2 -A ./binary -c '
afl                    # list all functions
s main                 # seek to main
pdf                    # print disassembly
pdc                    # print decompiled C-like code
' -q

# Decompile specific function
r2 -A ./binary -c 'pdf @sym.check_password' -q

# Find cross-references to a string
r2 -A ./binary -c '
iz                     # list strings in data section
izz                    # list all strings including code
axt @str.Correct       # xrefs to "Correct" string
' -q

# Look for crypto constants
r2 -A ./binary -c '/x 637263' -q    # search for "crc" bytes
```

#### 2.2 Pattern Recognition

**Flag validation (most common CTF RE pattern):**
The binary typically:
1. Reads user input
2. Transforms it (XOR, shift, lookup table, custom algorithm)
3. Compares result against hardcoded array

**Identify the transformation:**
```
Single-byte XOR:       input[i] ^ KEY = expected[i]
Addition/subtraction:  input[i] + KEY = expected[i]
Lookup table:          table[input[i]] = expected[i]
Multi-step:            f(g(input[i])) = expected[i]
Matrix operation:      M * input_vector = expected_vector
Custom VM:             bytecode interpreter, each opcode = operation
```

#### 2.3 Extracting Hardcoded Data
```bash
# Extract the comparison array
r2 -A ./binary -c '
s obj.expected_values   # seek to data object
px 64                   # hex dump 64 bytes
pxw 32                  # hex dump as 32-bit words
' -q

# Or with objdump
objdump -s -j .rodata ./binary   # dump read-only data section
objdump -s -j .data ./binary     # dump data section
```

---

### PHASE 3: Dynamic Analysis

#### 3.1 ltrace & strace
```bash
# Library calls — reveals strcmp, memcmp with expected values!
ltrace ./binary <<< "test_input"
# OUTPUT: strcmp("transformed_test", "expected_value") = ...
# This reveals the expected value directly!

# System calls
strace ./binary <<< "test_input"
# Reveals file operations, network connections
```
**ltrace is INCREDIBLY powerful** — if the binary uses `strcmp` or `memcmp`
to check the flag, ltrace shows both arguments in cleartext.

#### 3.2 GDB Debugging
```bash
# Set breakpoint at comparison, examine registers
gdb -q ./binary -ex 'b *main+0x42' -ex 'r' -ex 'x/s $rdi' -ex 'x/s $rsi'

# Common breakpoint targets:
gdb -q ./binary -ex '
b strcmp
b memcmp
b strncmp
commands
  x/s $rdi
  x/s $rsi
  continue
end
r
' <<< "AAAA"

# Examine stack at specific point:
gdb -q ./binary -ex 'b check_flag' -ex 'r' -ex 'x/20wx $rsp'

# Patch a conditional jump (bypass check):
# Change JNE (0x75) to JE (0x74) or NOP (0x90)
gdb -q ./binary -ex 'b *0x401234' -ex 'r' -ex 'set *(char*)0x401234=0x74' -ex 'c'
```

---

### PHASE 4: Automated Solving Techniques

#### 4.1 angr (Symbolic Execution)
Most powerful tool for flag-checker binaries:
```python
import angr
import claripy

proj = angr.Project('./binary', auto_load_libs=False)

# Define symbolic input
flag_len = 32
flag = claripy.BVS('flag', flag_len * 8)

# Create initial state
state = proj.factory.entry_state(stdin=angr.SimFile('/dev/stdin', content=flag))

# Add constraints for printable ASCII
for i in range(flag_len):
    byte = flag.get_byte(i)
    state.solver.add(byte >= 0x20)
    state.solver.add(byte <= 0x7e)

# Explore paths
simgr = proj.factory.simulation_manager(state)

# Find address of "Correct!" print, avoid "Wrong!" print
simgr.explore(
    find=0x401234,   # address of success path
    avoid=0x401256   # address of failure path
)

if simgr.found:
    solution = simgr.found[0]
    flag_value = solution.solver.eval(flag, cast_to=bytes)
    print(f"Flag: {flag_value}")
```

**Finding success/failure addresses:**
```bash
# In radare2, look for strings and their xrefs:
r2 -A ./binary -c 'izz~Correct' -q    # find "Correct" string
r2 -A ./binary -c 'izz~Wrong' -q      # find "Wrong" string
r2 -A ./binary -c 'axt @str.Correct' -q  # who references it
```

#### 4.2 Z3 Solver
For known constraint systems:
```python
from z3 import *

# Define symbolic variables for each flag character
flag = [BitVec(f'f{i}', 8) for i in range(32)]
s = Solver()

# Add printable constraints
for c in flag:
    s.add(c >= 0x20, c <= 0x7e)

# Add constraints from reverse-engineered check function
# Example: flag[0] ^ 0x42 == 0x24
s.add(flag[0] ^ 0x42 == 0x24)
# Example: flag[1] + flag[2] == 0xd5
s.add(flag[1] + flag[2] == 0xd5)
# ... add all constraints from the binary

if s.check() == sat:
    m = s.model()
    result = bytes([m[c].as_long() for c in flag])
    print(f"Flag: {result}")
```

#### 4.3 Brute-Force (character by character)
If the binary checks characters one at a time and leaks info:
```python
import subprocess, string

flag = ''
for pos in range(32):
    for c in string.printable:
        test = flag + c + 'A' * (31 - pos)
        result = subprocess.run(['./binary'], input=test.encode(),
                                capture_output=True, timeout=5)
        # Check if we got further (timing, output length, etc.)
        if b'Correct' in result.stdout:
            flag += c; break
        # Or use timing: if len() > previous_len
```

---

### PHASE 5: Language-Specific Techniques

| Language | Decompiler | Key Patterns |
|----------|-----------|--------------|
| C/C++ | r2, Ghidra | Direct disassembly, vtables for C++ |
| Go | r2, Ghidra | `main.main`, string table at specific section |
| Rust | r2, Ghidra | Mangled names, panic handlers |
| Python .pyc | uncompyle6, decompyle3, pycdc | `uncompyle6 chall.pyc` gives source |
| Java .class | jadx, cfr, procyon | `jadx -d output chall.jar` gives source |
| .NET | monodis, ilspy (wine) | `monodis --method chall.exe` |
| JavaScript | node --print, beautifier | de-obfuscate, eval tracing |
| WebAssembly | wasm2wat, wasm-decompile | Convert to WAT text format |

```bash
# Python bytecode
uncompyle6 chall.pyc > chall.py          # Python 3.8 and below
python3 -m dis chall.pyc                   # bytecode disassembly (any version)
pycdc chall.pyc > chall.py                 # works with newer Python versions

# Java
jadx -d output chall.jar && cat output/**/*.java

# .NET
monodis chall.exe                          # IL disassembly
```

---

### Decision Tree
```
What type of binary?
├── ELF → file, checksec, strings, r2 decompile
├── PE → strings, check .NET or native
├── Python .pyc → decompile to source, read logic
├── Java .jar → decompile with jadx, read source
├── Packed (UPX) → unpack first, then analyze
└── Unknown → binwalk, check for nested files

Analysis strategy:
├── Simple flag check → ltrace first (might reveal answer directly!)
├── Complex algorithm → r2 decompile → understand → implement inverse
├── Many constraints → angr symbolic execution or Z3 solver
├── Obfuscated → dynamic analysis with gdb breakpoints
└── Custom VM → reverse bytecode format, write disassembler
```
"""
