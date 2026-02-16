# CTF Misc Skill

Quick reference for miscellaneous challenges: encoding, scripting, pyjail, etc.

> **How to Use This Skill File:** This is a REFERENCE, not a script.
> Do NOT follow it top to bottom. Read the relevant section for YOUR
> challenge, understand the technique, adapt to THIS specific target,
> and form a hypothesis FIRST, then pick the right tool. Pick tools
> based on what you OBSERVE, not based on the order listed here.

---

## Encoding Chains (most common misc challenge)

```bash
# Try these in order
echo "input" | base64 -d
echo "input" | xxd -r -p
echo "input" | tr 'A-Za-z' 'N-ZA-Mn-za-m'    # ROT13

# Multi-layer: use CyberChef "Magic" to auto-detect
# https://gchq.github.io/CyberChef/

# Binary to ASCII
python3 -c "print(''.join(chr(int(b,2)) for b in 'BINARY_STRING'.split()))"

# Decimal to ASCII
python3 -c "print(''.join(chr(int(n)) for n in [104,101,108,108,111]))"

# Morse code
# .... . .-.. .-.. --- → HELLO

# Braille, Semaphore, NATO phonetic → lookup tables
```

---

## Python Jail Escape

```python
# When eval/exec is restricted

# No builtins
().__class__.__bases__[0].__subclasses__()
# Find subprocess.Popen or os._wrap_close in subclass list

# No imports
__builtins__.__import__('os').system('cat flag.txt')

# Restricted characters
# No dots: getattr(getattr(__builtins__, '__import__')('os'), 'system')('cat flag.txt')
# No quotes: chr(99)+chr(97)+chr(116) → "cat"

# Breakout from restricted shell
import os; os.system('/bin/sh')
__import__('os').system('cat flag*')
```

---

## Scripting Challenges (nc automation)

```python
from pwn import *

p = remote('ctf.example.com', 1337)

# Pattern: server asks math questions, answer quickly
while True:
    try:
        line = p.recvline().decode().strip()
        # Parse math: "What is 123 + 456?"
        if '+' in line:
            nums = [int(x) for x in line.split() if x.isdigit()]
            answer = sum(nums)
        p.sendline(str(answer).encode())
    except EOFError:
        print(p.recvall().decode())
        break
```

---

## QR Code / Barcode

```bash
# Decode QR code
zbarimg image.png                    # CLI decoder
python3 -c "
from PIL import Image
from pyzbar.pyzbar import decode
print(decode(Image.open('qr.png'))[0].data.decode())
"

# Generate QR code (sometimes needed)
qrencode -o output.png "data"
```

---

## Audio Challenges

```bash
# Spectrogram (visual message hidden in frequency)
sox audio.wav -n spectrogram -o spec.png

# DTMF tones (phone dialing)
multimon-ng -t wav -a DTMF audio.wav

# SSTV (slow-scan TV — image encoded in audio)
# Use QSSTV or online decoder

# Morse in audio
# Audacity → visualize, manually decode or use:
# https://morsecode.world/international/decoder/audio-decoder-adaptive.html

# Reverse audio
sox input.wav output.wav reverse

# Speed change
sox input.wav output.wav speed 2.0
```

---

## Network Misc

```bash
# Netcat interaction
nc target.com 1337

# DNS exfiltration
dig +short TXT flag.target.com
dig +short AAAA flag.target.com

# Custom protocol — analyze with Wireshark first
# Then script with pwntools:
from pwn import *
p = remote('target.com', 1337)
p.recvuntil(b'> ')
p.sendline(b'command')
```

---

## Jail / Sandbox Escape

```bash
# Restricted shell (rbash, limited commands)
# Try:
/bin/sh
/bin/bash
export PATH=/usr/bin:/bin:$PATH
$(cat /flag.txt)
`cat /flag.txt`

# vim/vi escape
:!/bin/sh
:set shell=/bin/sh
:shell

# Python escape
import pty; pty.spawn('/bin/sh')

# Find readable files
find / -readable -name "*flag*" 2>/dev/null
```

---

## Data Recovery / Carving

```bash
# File in file
binwalk file                         # Detect embedded files
binwalk -e file                      # Auto-extract

# Magic bytes check
xxd file | head -5                   # Check file header
# Fix corrupted header by comparing to known magic bytes

# Common magic bytes:
# PNG:  89 50 4E 47
# JPEG: FF D8 FF
# ZIP:  50 4B 03 04
# PDF:  25 50 44 46
# GIF:  47 49 46 38
# ELF:  7F 45 4C 46
```

---

## Esoteric Languages

```
# Brainfuck: ++++[>++++<-]>.
# Use: https://copy.sh/brainfuck/

# Whitespace: spaces, tabs, newlines only
# Use: https://vii5ard.github.io/whitespace/

# Ook: Ook. Ook? Ook!
# Variant of Brainfuck

# Piet: colored pixel art that's actually code
# Use: https://www.bertnase.de/npiet/npiet-execute.php

# JSFuck: []()!+ only
# Use browser console to execute
```

---

## CRITICAL RULES FOR AGENT

1. **CyberChef Magic first** for unknown encoding
2. **Check file type** — misc challenges often disguise files
3. **Automate with pwntools** for interactive challenges
4. **Look for hidden layers** — binwalk everything suspicious
5. **Read challenge description carefully** — misc challenges rely on hints
