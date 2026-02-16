# CTF Cryptography Skill

Quick reference. Identify cipher type first, then attack.

> **How to Use This Skill File:** This is a REFERENCE, not a script.
> Do NOT follow it top to bottom. Read the relevant section for YOUR
> challenge, understand the technique, adapt to THIS specific target,
> and form a hypothesis FIRST, then pick the right tool. Pick tools
> based on what you OBSERVE, not based on the order listed here.

---

## Identification (do this first)

```
Base64?     → ends with = or ==, charset A-Za-z0-9+/
Hex?        → all 0-9a-f, even length
Base32?     → uppercase A-Z2-7, padding with =
ROT13?      → readable-ish English but wrong letters
Caesar?     → single alphabet shift
Vigenere?   → polyalphabetic, repeating key
RSA?        → large numbers: n, e, c (or p, q given)
AES?        → binary/hex blob + key or IV mentioned
XOR?        → binary data + key hint
Hash?       → fixed length hex (32=MD5, 40=SHA1, 64=SHA256)
```

**Use CyberChef (`https://gchq.github.io/CyberChef/`) for quick decode chains.**

---

## Encoding (not encryption)

```bash
# Base64
echo "encoded" | base64 -d
python3 -c "import base64; print(base64.b64decode('encoded'))"

# Hex
echo "68656c6c6f" | xxd -r -p
python3 -c "print(bytes.fromhex('68656c6c6f'))"

# Base32
python3 -c "import base64; print(base64.b32decode('ENCODED'))"

# Multiple layers — try CyberChef "Magic" recipe
# Common: base64 → hex → base64 → flag
```

---

## Classical Ciphers

```bash
# Caesar / ROT
# Try all 25 shifts
python3 -c "
s='CIPHER_TEXT'
for i in range(26):
    print(i, ''.join(chr((ord(c)-65+i)%26+65) if c.isupper() else chr((ord(c)-97+i)%26+97) if c.islower() else c for c in s))
"

# ROT13 specifically
echo "text" | tr 'A-Za-z' 'N-ZA-Mn-za-m'

# Vigenere (known key)
python3 -c "
key='KEY'; ct='CIPHERTEXT'
pt=''.join(chr((ord(c)-ord(k))%26+65) for c,k in zip(ct, key*(len(ct)//len(key)+1)) if c.isalpha())
print(pt)
"

# Substitution cipher → use quipqiup.com or frequency analysis
```

---

## RSA Attacks

```python
# Given: n, e, c
# Standard decrypt (if p, q known)
from Crypto.Util.number import long_to_bytes, inverse
phi = (p-1)*(q-1)
d = inverse(e, phi)
m = pow(c, d, n)
print(long_to_bytes(m))

# Small e attack (e=3, small message)
import gmpy2
m, exact = gmpy2.iroot(c, e)
if exact:
    print(long_to_bytes(int(m)))

# Fermat factoring (p and q close together)
import gmpy2
a = gmpy2.isqrt(n) + 1
while True:
    b2 = a*a - n
    b = gmpy2.isqrt(b2)
    if b*b == b2:
        p, q = int(a+b), int(a-b)
        break
    a += 1

# Wiener attack (large e, small d)
# Use: pip install owiener
import owiener
d = owiener.attack(e, n)

# Common modulus attack (same n, two different e values)
# Given: n, e1, c1, e2, c2
from Crypto.Util.number import inverse
g, a, b = extended_gcd(e1, e2)
m = (pow(c1, a, n) * pow(c2, b, n)) % n

# Factor n online
# factordb.com — paste n, might already be factored
# RsaCtfTool: python3 RsaCtfTool.py -n N -e E --uncipher C
```

---

## AES

```python
# ECB mode (same plaintext block → same ciphertext block)
# Detect: look for repeated 16-byte blocks in ciphertext
from Crypto.Cipher import AES
cipher = AES.new(key, AES.MODE_ECB)
plaintext = cipher.decrypt(ciphertext)

# CBC mode
cipher = AES.new(key, AES.MODE_CBC, iv=iv)
plaintext = cipher.decrypt(ciphertext)

# CBC padding oracle attack
# Use: padding-oracle-attacker or custom script
# Detect: server returns different errors for bad padding vs bad data
```

---

## XOR

```python
# Single-byte XOR brute force
ct = bytes.fromhex("CIPHERTEXT_HEX")
for key in range(256):
    pt = bytes([b ^ key for b in ct])
    if b'flag' in pt or pt.isascii():
        print(f"Key {key}: {pt}")

# Known plaintext XOR
# key = plaintext XOR ciphertext
key = bytes([p ^ c for p, c in zip(known_plaintext, ciphertext)])

# Repeating key XOR
# 1. Find key length (Hamming distance / Kasiski)
# 2. Break into blocks, solve each as single-byte XOR
# Use: xortool -l <keylen> -c <most_common_char> file
```

---

## Hash Cracking

```bash
# Identify hash type
hashid "hash_value"
# or by length: 32=MD5, 40=SHA1, 64=SHA256

# Hashcat
hashcat -m 0 hash.txt wordlist.txt       # MD5
hashcat -m 100 hash.txt wordlist.txt     # SHA1
hashcat -m 1400 hash.txt wordlist.txt    # SHA256
hashcat -m 1000 hash.txt wordlist.txt    # NTLM

# John the Ripper
john --format=raw-md5 --wordlist=wordlist.txt hash.txt

# Online
# crackstation.net, hashes.com, cmd5.com
```

---

## Z3 Solver (constraint satisfaction)

```python
from z3 import *
# Define variables
x, y = Ints('x y')
s = Solver()

# Add constraints from challenge
s.add(x + y == 100)
s.add(x * 2 - y == 50)

if s.check() == sat:
    m = s.model()
    print(f"x={m[x]}, y={m[y]}")
```

---

## Useful Python One-Liners

```python
# Bytes to int
int.from_bytes(b'text', 'big')

# Int to bytes
n.to_bytes((n.bit_length()+7)//8, 'big')

# Long to bytes (pycryptodome)
from Crypto.Util.number import long_to_bytes, bytes_to_long

# GCD
from math import gcd
```

---

## CRITICAL RULES FOR AGENT

1. **Identify the cipher type first** — don't guess randomly
2. **Try simple decoding first** (base64, hex, ROT13) before complex crypto
3. **Check factordb.com for RSA** — n might already be factored
4. **Use pycryptodome** for implementation, not manual math
5. **Read the challenge description** — hints about algorithm are usually there
