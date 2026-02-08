"""Digital forensics playbook — expert-level methodology."""

PLAYBOOK = r"""\
## Digital Forensics Playbook

You are solving a forensics CTF challenge. Work through layers of data
systematically — every file may contain hidden files, metadata, or
encoded data within it.

---

### PHASE 1: Initial Triage (always do ALL of these first)

```bash
# Step 1: What is this file actually?
file ./challenge_file
# CRITICAL: Don't trust the extension! A .png might be a ZIP, etc.

# Step 2: Hex header inspection
xxd ./challenge_file | head -5
# Common magic bytes:
#   89 50 4e 47 → PNG     |  ff d8 ff → JPEG      |  50 4b 03 04 → ZIP
#   1f 8b 08    → GZIP    |  42 4d    → BMP        |  25 50 44 46 → PDF
#   7f 45 4c 46 → ELF     |  52 49 46 46 → RIFF    |  d0 cf 11 e0 → OLE/DOC
#   52 61 72 21 → RAR     |  fd 37 7a 58 5a → XZ   |  4d 5a → PE/EXE

# Step 3: File size & metadata
ls -la ./challenge_file
exiftool ./challenge_file
# EXIF can contain: GPS, comments, author, software, thumbnail, XMP data
# Author/comment fields are common flag hiding spots

# Step 4: Strings scan
strings ./challenge_file | grep -iE "flag|ctf|key|secret|pass|base64|http"
strings -el ./challenge_file | head -20    # UTF-16LE strings (Windows)

# Step 5: Embedded file scan
binwalk ./challenge_file
# Look for: embedded ZIPs, PNGs, PDFs, gzip streams, certificates
# If binwalk finds things:
binwalk -e ./challenge_file              # extract all
binwalk --dd='.*' ./challenge_file       # extract EVERYTHING
```

---

### PHASE 2: Image Forensics

#### 2.1 PNG Analysis
```bash
# Check PNG structure — CRITICAL: look for extra chunks
pngcheck -v ./image.png
# Custom chunks (like tEXt, zTXt, iTXt) may contain the flag

# Extract ALL chunks manually
python3 -c "
import struct
data = open('image.png','rb').read()
pos = 8  # skip PNG signature
while pos < len(data):
    length = struct.unpack('>I', data[pos:pos+4])[0]
    chunk_type = data[pos+4:pos+8].decode('ascii','replace')
    chunk_data = data[pos+8:pos+8+length]
    print(f'{chunk_type}: {length} bytes → {chunk_data[:80]}')
    pos += 12 + length
"

# Check for data after IEND (appended data)
python3 -c "
data = open('image.png','rb').read()
iend = data.find(b'IEND')
if iend != -1:
    after = data[iend+8:]
    if after: print(f'Data after IEND: {len(after)} bytes'); open('after_iend.bin','wb').write(after)
    else: print('No data after IEND')
"

# Pixel-level analysis
python3 -c "
from PIL import Image
img = Image.open('image.png')
print(f'Size: {img.size}, Mode: {img.mode}')
# Check for LSB steganography
pixels = list(img.getdata())
lsb_bits = ''.join(str(p[0] & 1) for p in pixels[:800])
lsb_bytes = bytes(int(lsb_bits[i:i+8], 2) for i in range(0, len(lsb_bits)-7, 8))
print(f'LSB (first 100 bytes): {lsb_bytes[:100]}')
"

# Separate color channels — flag might be in one channel only
python3 -c "
from PIL import Image
img = Image.open('image.png')
for i, ch in enumerate(img.split()):
    ch.save(f'channel_{i}.png')
print('Saved separate channels')
"
```

#### 2.2 JPEG Analysis
```bash
# JPEG-specific: check for hidden data in JFIF/Exif segments
exiftool -a -u -g1 ./image.jpg        # ALL metadata with groups
# Check thumbnail — might be a different image!
exiftool -b -ThumbnailImage ./image.jpg > thumb.jpg

# Steghide (JPEG & BMP steganography)
steghide extract -sf ./image.jpg -p ""           # empty password
steghide extract -sf ./image.jpg -p "password"   # common password
steghide info ./image.jpg                        # show embedded info
```

#### 2.3 BMP / Other Images
```bash
# zsteg for PNG/BMP LSB steganography (try ALL channels and bit orders)
zsteg ./image.png -a              # try ALL combinations
zsteg ./image.bmp -a

# stegsolve logic (without GUI):
python3 -c "
from PIL import Image
img = Image.open('image.png')
# Extract bit plane N for each channel
for bit in range(8):
    for ch_idx, ch_name in enumerate(['R','G','B']):
        plane = img.copy()
        pixels = plane.load()
        for x in range(plane.width):
            for y in range(plane.height):
                p = list(pixels[x,y])
                val = 255 if (p[ch_idx] >> bit) & 1 else 0
                pixels[x,y] = (val, val, val) if plane.mode=='RGB' else val
        plane.save(f'plane_{ch_name}_bit{bit}.png')
        print(f'Saved plane_{ch_name}_bit{bit}.png')
"
```

---

### PHASE 3: Network Forensics (PCAP Analysis)

```bash
# Step 1: Overview
tshark -r capture.pcap -q -z io,stat,0
tshark -r capture.pcap -q -z conv,tcp    # TCP conversations
tshark -r capture.pcap -q -z http,tree   # HTTP summary

# Step 2: Protocol breakdown
tshark -r capture.pcap -q -z endpoints,tcp
tshark -r capture.pcap -T fields -e frame.number -e ip.src -e ip.dst \
    -e tcp.srcport -e tcp.dstport -e _ws.col.Protocol | head -30

# Step 3: Extract HTTP objects
mkdir -p http_objects
tshark -r capture.pcap --export-objects http,http_objects
ls -la http_objects/

# Step 4: Follow TCP streams one by one
tshark -r capture.pcap -q -z follow,tcp,ascii,0   # stream 0
tshark -r capture.pcap -q -z follow,tcp,ascii,1   # stream 1
# Increase stream number until no more streams

# Step 5: Look for specific data
tshark -r capture.pcap -Y 'http' -T fields -e http.request.uri -e http.response.code
tshark -r capture.pcap -Y 'dns' -T fields -e dns.qry.name
# DNS exfiltration: flag hidden in DNS query subdomains
tshark -r capture.pcap -Y 'dns.qry.name contains "flag"' -T fields -e dns.qry.name

# Step 6: FTP file extraction
tshark -r capture.pcap -Y 'ftp-data' -T fields -e tcp.payload | tr -d ':' | xxd -r -p > ftp_file

# Step 7: Extract credentials
tshark -r capture.pcap -Y 'http.authorization' -T fields -e http.authorization
tshark -r capture.pcap -Y 'ftp.request.command == "PASS"' -T fields -e ftp.request.arg
```

```python
# Python approach with scapy for complex analysis
from scapy.all import rdpcap, TCP, Raw

packets = rdpcap('capture.pcap')
for pkt in packets:
    if pkt.haslayer(Raw):
        data = pkt[Raw].load
        if b'flag' in data.lower():
            print(f"Found in packet: {data}")
```

---

### PHASE 4: Disk & Memory Forensics

#### 4.1 Disk Images
```bash
# Identify partitions
fdisk -l disk.img

# Mount filesystem
mkdir -p /mnt/disk
mount -o loop,ro disk.img /mnt/disk       # simple image
mount -o loop,ro,offset=1048576 disk.img /mnt/disk  # with partition offset

# File recovery from disk image
foremost -i disk.img -o recovered/
photorec disk.img

# Sleuth Kit analysis
fls -r disk.img              # list all files including deleted ($OrphanFiles)
icat disk.img <inode>        # extract file by inode number
tsk_recover -e disk.img recovered/  # recover all files
```

#### 4.2 Memory Dumps (Volatility)
```bash
# Step 1: Identify the OS profile
volatility -f memory.dmp imageinfo
# OR for Volatility 3:
vol -f memory.dmp windows.info

# Step 2: List processes
volatility -f memory.dmp --profile=<PROFILE> pslist
volatility -f memory.dmp --profile=<PROFILE> pstree

# Step 3: Common forensics targets
volatility -f memory.dmp --profile=<PROFILE> cmdscan     # command history
volatility -f memory.dmp --profile=<PROFILE> consoles    # console output
volatility -f memory.dmp --profile=<PROFILE> filescan    # open files
volatility -f memory.dmp --profile=<PROFILE> netscan     # network connections
volatility -f memory.dmp --profile=<PROFILE> clipboard   # clipboard contents
volatility -f memory.dmp --profile=<PROFILE> hashdump    # password hashes
volatility -f memory.dmp --profile=<PROFILE> hivelist    # registry hives

# Step 4: Dump suspicious process memory
volatility -f memory.dmp --profile=<PROFILE> memdump -p <PID> -D dump/

# Step 5: Extract files from memory
volatility -f memory.dmp --profile=<PROFILE> dumpfiles -Q <OFFSET> -D dump/
```

---

### PHASE 5: Document Forensics

```bash
# PDF analysis
pdftotext document.pdf -             # extract text
python3 -c "
import re
data = open('document.pdf','rb').read()
# Find JavaScript in PDF
js_matches = re.findall(b'/JS\\s*\\((.+?)\\)', data)
for m in js_matches: print(f'JS: {m}')
# Find embedded files
if b'/EmbeddedFile' in data: print('Has embedded files')
"

# Office documents (OOXML = ZIP)
unzip -l document.docx              # list contents
unzip document.docx -d docx_contents/
# Check for macros
olevba document.docm                # extract VBA macros

# OLE analysis
oleid document.doc                  # identify OLE indicators
oledump.py document.doc             # dump OLE streams
```

---

### PHASE 6: Audio Forensics

```bash
# Spectrogram analysis (flag hidden visually in spectrogram)
sox audio.wav -n spectrogram -o spectrogram.png

# DTMF decoding (telephone tones)
multimon-ng -t wav -a DTMF audio.wav

# SSTV decoding (slow-scan television)
# RX-SSTV or qsstv for decoding

# Binary/morse in audio
# Convert to raw samples, detect high/low for morse code
python3 -c "
import wave
w = wave.open('audio.wav','rb')
frames = w.readframes(-1)
import struct
samples = struct.unpack(f'{w.getnframes()}h', frames)
# Detect morse: high amplitude = dit/dah, low = silence
"
```

---

### PHASE 7: Steganography Summary

| Tool | File Types | What it Does |
|------|-----------|-------------|
| `steghide` | JPEG, BMP, WAV, AU | Password-based stego, try empty pw first |
| `zsteg` | PNG, BMP | LSB stego, all bit planes and channels |
| `stegsolve` logic | Any image | Bit plane analysis, channel separation |
| `binwalk` | Any | Embedded file detection and extraction |
| `foremost` | Any | File carving from raw data |
| `exiftool` | Any | Metadata extraction |
| `strings` | Any | Readable string extraction |
| `xxd` | Any | Hex dump for manual inspection |

**Steganography checklist (try in order):**
1. `strings` + `grep flag`
2. `exiftool` — check comments, author, description
3. `binwalk -e` — extract embedded files
4. `steghide extract -sf file -p ""` — empty password
5. `zsteg -a file.png` — all LSB combinations
6. Check after EOF marker (IEND for PNG, FFD9 for JPEG)
7. Separate color channels + bit planes
8. Check file size vs expected (extra data appended?)

---

### Decision Tree
```
What type of file?
├── Image (PNG/JPEG/BMP/GIF)
│   ├── exiftool → check metadata/comments
│   ├── binwalk → check for embedded files
│   ├── strings → grep for flags
│   ├── steghide/zsteg → steganography
│   └── pixel analysis → LSB, channels, bit planes
├── PCAP / Network capture
│   ├── tshark → protocol analysis, stream following
│   ├── HTTP objects extraction
│   └── DNS/FTP/custom protocol data
├── Disk image / Memory dump
│   ├── mount/fls → filesystem analysis
│   ├── volatility → memory forensics
│   └── foremost → file carving
├── Document (PDF/DOC/XLSX)
│   ├── unzip (OOXML) → check embedded files
│   ├── olevba → macro analysis
│   └── pdftotext → hidden text
├── Audio (WAV/MP3)
│   ├── spectrogram → visual message
│   ├── DTMF/morse → encoded data
│   └── LSB audio stego
└── Archive (ZIP/TAR/GZ)
    ├── Extract → analyze contents
    ├── Password protected → crack with john/fcrackzip
    └── Check for zip comments: unzip -z file.zip
```
"""
