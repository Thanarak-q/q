"""Cryptography challenge playbook — expert-level methodology."""

PLAYBOOK = r"""\
## Cryptography Playbook

You are solving a cryptography CTF challenge. Read the source code first,
identify the cryptosystem, then apply the correct attack.

---

### PHASE 1: Identification

1. **Read the source code completely** — the vulnerability is ALWAYS in the code.
2. Identify the cryptosystem and parameters.
3. Check what you're given (ciphertext, public key, oracle access, etc.).
4. Check what's reused, hardcoded, or improperly generated.

**Quick checks on raw data:**
```python
import base64, binascii
# Is it base64?
try: base64.b64decode(data); print("base64")
except: pass
# Is it hex?
try: bytes.fromhex(data); print("hex")
except: pass
# Check length — 256 bytes = RSA-2048, 128 bytes = RSA-1024, 16/32 = AES block
```

---

### PHASE 2: RSA Attacks

**Always start by trying to factor n on factordb.com** (use the network tool
to query `http://factordb.com/api?query=<n>`).

#### 2.1 Small Public Exponent (e=3) + Small Message
```python
import gmpy2
# If m^e < n, then c = m^e and we can just take the e-th root
m, exact = gmpy2.iroot(c, e)
if exact:
    print(bytes.fromhex(hex(int(m))[2:]))
```

#### 2.2 Common Modulus Attack
Same n, two different e values encrypting same plaintext:
```python
import gmpy2
# Given: n, e1, e2, c1, c2 where gcd(e1,e2) = 1
# Extended GCD: a*e1 + b*e2 = 1
g, a, b = gmpy2.gcdext(e1, e2)
# m = c1^a * c2^b mod n
if a < 0:
    c1 = gmpy2.invert(c1, n)
    a = -a
if b < 0:
    c2 = gmpy2.invert(c2, n)
    b = -b
m = (pow(c1, a, n) * pow(c2, b, n)) % n
```

#### 2.3 Wiener's Attack (small d)
When d < n^0.25 / 3:
```python
from Crypto.PublicKey import RSA
# Use continued fraction expansion of e/n
def wiener(e, n):
    cf = continued_fraction(e, n)
    convergents = get_convergents(cf)
    for k, d in convergents:
        if k == 0: continue
        phi = (e * d - 1) // k
        # Solve x^2 - (n - phi + 1)*x + n = 0
        b = n - phi + 1
        disc = b*b - 4*n
        if disc >= 0:
            sq = gmpy2.isqrt(disc)
            if sq*sq == disc and (b+sq) % 2 == 0:
                return d
    return None
```

#### 2.4 Fermat Factorization (p ≈ q)
```python
import gmpy2
def fermat_factor(n):
    a = gmpy2.isqrt(n) + 1
    b2 = a*a - n
    while not gmpy2.is_square(b2):
        a += 1
        b2 = a*a - n
    b = gmpy2.isqrt(b2)
    return int(a - b), int(a + b)
```

#### 2.5 Hastad's Broadcast Attack
Same m encrypted with e different public keys (e=3, 3 ciphertexts):
```python
# CRT on c1,c2,c3 with n1,n2,n3, then cube root
from sympy.ntheory.modular import crt
remainders = [c1, c2, c3]
moduli = [n1, n2, n3]
x, _ = crt(moduli, remainders)
m = gmpy2.iroot(x, 3)[0]
```

#### 2.6 RSA with known bits / partial key
```python
# Coppersmith's method via SageMath
# If you know part of p (high bits):
# p_approx = known_high_bits << unknown_bit_length
# Use small_roots() to find the rest
```

#### 2.7 RSA padding — PKCS#1 v1.5
If error messages differ for valid/invalid padding → Bleichenbacher attack.

#### 2.8 Multi-prime RSA
```python
# phi = (p1-1)*(p2-1)*(p3-1)*...
# d = inverse(e, phi)
```

---

### PHASE 3: Symmetric Crypto Attacks

#### 3.1 ECB Mode Detection & Exploitation
```python
# Detection: encrypt 2+ identical blocks, check for repeated ciphertext blocks
# If ct has repeated 16-byte blocks → ECB
# Attack: ECB byte-at-a-time (chosen-plaintext oracle)
# Pad known bytes to align target byte at block boundary
# Brute-force one byte at a time by comparing blocks
```

#### 3.2 CBC Bit-Flip Attack
```python
# Flip bit in ciphertext block N to change corresponding bit in plaintext block N+1
# target_byte = original_byte ^ desired_byte ^ ciphertext_byte
# Useful for: changing "admin=0" to "admin=1" in encrypted cookies
ct = bytearray(ciphertext)
block_offset = target_block_index * 16
byte_offset = block_offset + target_byte_position
ct[byte_offset] ^= ord(original_char) ^ ord(desired_char)
```

#### 3.3 CBC Padding Oracle
```python
# If server returns different errors for valid/invalid padding:
# Decrypt any ciphertext byte-by-byte
# For each byte position (right to left):
#   Try all 256 values for the ciphertext byte
#   Valid padding reveals the intermediate value
#   plaintext = intermediate XOR previous_ciphertext
# Use the python `padding-oracle` library or implement manually.
```

#### 3.4 AES-CTR / Stream Cipher Nonce Reuse
```python
# If nonce is reused: c1 XOR c2 = m1 XOR m2
# Use crib dragging: XOR with known words and check for readable text
c1_xor_c2 = bytes(a ^ b for a, b in zip(c1, c2))
for word in [b'the ', b'flag', b'CTF{', b'http']:
    for i in range(len(c1_xor_c2) - len(word)):
        result = bytes(c ^ w for c, w in zip(c1_xor_c2[i:], word))
        if all(32 <= b < 127 for b in result):
            print(f"pos={i} word={word} → {result}")
```

#### 3.5 Mersenne Twister / PRNG Prediction
```python
# If you can observe 624 consecutive 32-bit outputs:
# Clone the internal state and predict future outputs
# Use: from randcrack import RandCrack
# rc = RandCrack()
# for _ in range(624): rc.submit(observed_value)
# predicted = rc.predict_getrandbits(32)

# For Python random.randint(a,b) — extract the underlying getrandbits calls
```

#### 3.6 LCG (Linear Congruential Generator)
```python
# state = (a * state + c) % m
# If you know 3+ consecutive outputs, solve for a, c, m
# s1 = a*s0 + c mod m → a = (s2-s1) * inverse(s1-s0, m) mod m
```

---

### PHASE 4: Classical Ciphers

#### 4.1 XOR Cipher
```python
# Single-byte XOR: try all 256 keys, check for readable output
for key in range(256):
    result = bytes(b ^ key for b in ciphertext)
    if b'flag' in result or all(32 <= b < 127 for b in result):
        print(f"key={key}: {result}")

# Multi-byte XOR with known plaintext prefix (e.g., flag format)
known = b'flag{'
key_fragment = bytes(c ^ p for c, p in zip(ciphertext, known))
# Repeat key_fragment to get full key
```

#### 4.2 Caesar / ROT
```python
for shift in range(26):
    result = ''.join(chr((ord(c) - ord('a') + shift) % 26 + ord('a'))
                     if c.isalpha() else c for c in ciphertext.lower())
    print(f"shift={shift}: {result}")
```

#### 4.3 Vigenere
```python
# Step 1: Find key length via Kasiski/Friedman (Index of Coincidence)
# Step 2: Split ciphertext into groups by key position
# Step 3: Frequency-analyze each group as Caesar cipher
```

#### 4.4 Substitution Cipher
- Frequency analysis: `e` is most common, then `t,a,o,i,n`
- Bigrams: `th`, `he`, `in`, `er`, `an`
- Use quipqiup.com logic or implement.

---

### PHASE 5: Hash Attacks

#### 5.1 Hash Length Extension
```python
# Vulnerable: MAC = H(secret || message), server verifies
# Attack: extend message without knowing secret
# Use hashpumpy: hashpump -s <orig_sig> -d <orig_data> -a <append> -k <secret_len>
# Brute-force secret length from 1 to 64
```

#### 5.2 Hash Collision
```python
# MD5 collision: use fastcoll or UniColl
# SHA-1: SHAttered attack (known colliding PDFs)
# For CTF: often they check md5(a) == md5(b) with a != b
# Use known MD5 collision pairs from the literature
```

---

### PHASE 6: Elliptic Curve Attacks

#### 6.1 Small Subgroup / Invalid Curve
- If the curve order has small factors → Pohlig-Hellman.
- If point validation is missing → use points on a weaker curve.

#### 6.2 Nonce Reuse in ECDSA
```python
# If k is reused in two signatures (r1==r2):
# k = (z1 - z2) * inverse(s1 - s2, n) mod n
# private_key = (s1*k - z1) * inverse(r1, n) mod n
```

---

### Tool Usage Patterns
```python
# Always start with this template:
from Crypto.Util.number import long_to_bytes, bytes_to_long, inverse, GCD
import gmpy2

# Decode RSA components
n = <value>
e = <value>
c = <value>

# Quick checks:
print(f"n bits: {n.bit_length()}")
print(f"e = {e}")
print(f"GCD(e, some_known_phi) = {GCD(e, phi)}")

# Final decryption:
m = pow(c, d, n)
print(long_to_bytes(m))
```

### Decision Tree
```
Given source code?
├── Yes → Read code → Identify crypto system → Apply specific attack
└── No → Given only ciphertext?
    ├── Looks like base64/hex → Decode → Check for nested encoding
    ├── Has public key file → Extract n,e → Factor n → Decrypt
    ├── Large number pairs → Probably RSA
    └── Short text → Probably classical cipher (XOR, Caesar, Vigenere)
```
"""
