# CTF Forensics Skill

Quick reference. Be efficient — run the right command first, not everything.

---

## First Steps (ALWAYS do these first)

```bash
file <target>                    # What is it?
exiftool <target>                # Metadata (flags hide here!)
strings -n 8 <target> | head -50 # Quick string scan
hexdump -C <target> | head -5   # Magic bytes check
```

**Then branch by file type below.**

---

## PCAP / Network Forensics

```bash
# Overview first (1 command tells you a lot)
tshark -r file.pcap -q -z conv,ip

# HTTP traffic summary
tshark -r file.pcap -q -z http,tree

# Extract HTTP requests with IPs
tshark -r file.pcap -Y 'http.request' -T fields \
  -e ip.src -e ip.dst -e http.request.method -e http.request.uri

# Find attacker patterns (SQLi, shells, login brute force)
tshark -r file.pcap -Y 'http.request' -T fields \
  -e ip.src -e http.request.uri | sort | uniq -c | sort -rn

# Extract POST data (login attempts, uploads)
tshark -r file.pcap -Y 'http.request.method==POST' -T fields \
  -e ip.src -e http.request.uri -e http.file_data

# DNS queries
tshark -r file.pcap -Y 'dns.qr==0' -T fields -e ip.src -e dns.qry.name

# Export HTTP objects
tshark -r file.pcap --export-objects http,./exported_files

# Follow specific TCP stream
tshark -r file.pcap -z follow,tcp,ascii,0
```

**Attacker identification pattern:**
1. `tshark -q -z conv,ip` → find IPs with most traffic
2. `tshark -Y 'http.request' -T fields -e ip.src -e http.request.uri` → check what each IP accessed
3. Look for: SQLi (`UNION SELECT`, `OR 1=1`), shell uploads, `/admin/` access, encoded payloads
4. **Answer immediately when pattern is clear. Don't over-analyze.**

**TLS decryption (weak RSA):**
1. Export server cert from Server Hello → `public.der`
2. `openssl x509 -in public.der -inform DER -noout -modulus`
3. Factor weak modulus (factordb.com, yafu)
4. `rsatool -p P -q Q -o private.pem`

---

## Image / Steganography

```bash
exiftool image.jpg               # Check ALL metadata fields for flag
steghide extract -sf image.jpg   # JPEG steganography (try empty password first)
zsteg image.png                  # PNG/BMP LSB analysis
binwalk image.png                # Embedded files inside image
stegsolve                        # Visual bit plane analysis

# Check for appended data after image
binwalk -e image.jpg             # Auto-extract embedded files
```

**Common patterns:**
- Flag in EXIF: Author, Comment, ImageDescription fields
- `steghide` with empty password or challenge-hinted password
- `zsteg -a` for exhaustive PNG analysis
- Appended ZIP/RAR after image EOF marker

---

## PDF Analysis

```bash
exiftool document.pdf            # Metadata (Author, Title = common flag spots)
strings document.pdf | grep -i flag
pdftotext document.pdf -         # Extract all text
binwalk document.pdf             # Embedded files
qpdf --show-pages document.pdf  # Page structure
```

---

## Memory Forensics (Volatility 3)

```bash
vol3 -f memory.dmp windows.info         # OS info
vol3 -f memory.dmp windows.pslist       # Process list
vol3 -f memory.dmp windows.cmdline      # Command lines
vol3 -f memory.dmp windows.netscan      # Network connections
vol3 -f memory.dmp windows.filescan     # Files in memory
vol3 -f memory.dmp windows.hashdump     # Password hashes
vol3 -f memory.dmp windows.dumpfiles --physaddr <addr>  # Extract file

# Search for flags/strings in memory
strings memory.dmp | grep -i "flag{"
vol3 -f memory.dmp windows.strings --strings-file strings.txt
```

**Linux memory:**
```bash
vol3 -f memory.dmp linux.bash           # Bash history
vol3 -f memory.dmp linux.pslist         # Processes
```

---

## Disk Image / File System

```bash
# Mount read-only
sudo mount -o loop,ro image.dd /mnt/evidence

# List all files (including deleted)
fls -r image.dd

# Extract file by inode
icat image.dd <inode_number>

# Carve deleted files
photorec image.dd
foremost -i image.dd

# Find hidden files
find /mnt/evidence -name ".*"
ls -la /mnt/evidence
```

**Deleted partition recovery:**
```bash
fdisk -l image.img           # Check partition table
testdisk image.img           # Interactive recovery
```

---

## Windows Forensics

**Registry:**
```bash
# SAM = users/passwords, SYSTEM = boot key, SOFTWARE = installed apps
regipy-dump SAM
regipy-dump SYSTEM
```

**Event Logs (.evtx):**
- 4720 = User created
- 4724 = Password reset
- 1102 = Audit log cleared
- 4625 = Failed logon
- 7045 = Service installed

**Recycle Bin:** `$R` files = data, `$I` files = metadata

---

## Log Analysis

```bash
# Find flag fragments
grep -iE "(flag|part|piece|fragment)" server.log

# Reconstruct fragmented flags
grep "FLAGPART" server.log | sed 's/.*FLAGPART: //' | uniq | tr -d '\n'

# Find anomalies (most common entries)
sort logfile.log | uniq -c | sort -rn | head

# Timeline suspicious IPs
grep "111.224.250.131" access.log | head -20
```

---

## Archive / Encoded Data

```bash
# Base64
echo "base64string" | base64 -d

# Hex
echo "hexstring" | xxd -r -p

# ROT13
echo "text" | tr 'A-Za-z' 'N-ZA-Mn-za-m'

# ZIP with password
fcrackzip -u -D -p wordlist.txt archive.zip
john --format=pkzip hash.txt
```

---

## Common Flag Locations

- PDF/image metadata fields (Author, Title, Comment, Keywords)
- Deleted files (Recycle Bin, disk carving)
- Log file fragments (grep for flag pattern)
- Memory strings
- Registry values
- Browser history (places.sqlite)
- HTTP response bodies in PCAP
- Embedded files (binwalk extraction)

---

## CRITICAL RULES FOR AGENT

1. **Run overview commands first** — don't blindly enumerate
2. **Answer as soon as you find the answer** — don't keep investigating
3. **Max 3-5 commands** for simple questions (like "find attacker IP")
4. **Don't repeat commands** that another agent already ran
5. **Truncate large outputs** — pipe through `head` or `grep`
