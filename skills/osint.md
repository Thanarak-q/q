# CTF OSINT Skill

Quick reference. Extract info from public sources systematically.

> **How to Use This Skill File:** This is a REFERENCE, not a script.
> Do NOT follow it top to bottom. Read the relevant section for YOUR
> challenge, understand the technique, adapt to THIS specific target,
> and form a hypothesis FIRST, then pick the right tool. Pick tools
> based on what you OBSERVE, not based on the order listed here.

---

## Image Analysis

```bash
# Metadata first
exiftool image.jpg                              # GPS, camera, author, dates
exiftool -gpslatitude -gpslongitude image.jpg   # GPS coordinates directly

# Reverse image search
# Google Images, TinEye, Yandex Images (best for faces/locations)

# GPS to location
# Google Maps: paste coordinates
# https://www.google.com/maps?q=LAT,LON
```

**Key EXIF fields:** GPSLatitude, GPSLongitude, Author, Comment, DateTimeOriginal, Software

---

## Username / Person Search

```bash
# Username across platforms
sherlock username                    # Check 300+ sites
whatsmyname username                 # Alternative

# Email lookup
holehe email@example.com            # Check which sites email is registered on

# Social media
# Check: Twitter, GitHub, LinkedIn, Instagram, Reddit, Discord
# Look for: bio info, posts, connections, repositories
```

---

## Social Media Intelligence

### Twitter / X

```bash
# Search operators (use in Twitter search bar or API)
# from:username — tweets by user
# to:username — replies to user
# "exact phrase" — exact match
# since:2024-01-01 until:2024-06-01 — date range
# filter:links — only tweets with links
# geocode:LAT,LON,RADIUS — tweets near location

# API-based (requires bearer token)
curl -H "Authorization: Bearer $BEARER" \
  "https://api.twitter.com/2/users/by/username/TARGET?user.fields=created_at,description,location,public_metrics"

# Get recent tweets
curl -H "Authorization: Bearer $BEARER" \
  "https://api.twitter.com/2/users/USER_ID/tweets?max_results=100&tweet.fields=created_at,geo"

# Archived/deleted tweets
# Check web.archive.org/web/*/twitter.com/username
# Use Wayback Machine CDX API for bulk lookup
curl "https://web.archive.org/cdx/search/cdx?url=twitter.com/TARGET/*&output=json&limit=50"
```

### GitHub

```bash
# User profile and repos
curl "https://api.github.com/users/USERNAME"
curl "https://api.github.com/users/USERNAME/repos?sort=updated&per_page=100"

# Search commits by email
curl "https://api.github.com/search/commits?q=author-email:user@example.com"

# Search code by user
curl "https://api.github.com/search/code?q=user:USERNAME+password"

# Activity feed (public events)
curl "https://api.github.com/users/USERNAME/events/public?per_page=100"

# Gists (often overlooked)
curl "https://api.github.com/users/USERNAME/gists"
```

### LinkedIn

```
# No public API — use browser-based techniques
# Google dork: site:linkedin.com/in/ "target name" "company"
# Check cached versions in Google cache or Wayback Machine
# Cross-reference job titles with company about pages
```

### Reddit

```bash
# User profile and comments (JSON API)
curl "https://www.reddit.com/user/USERNAME/comments.json?limit=100&sort=new"
curl "https://www.reddit.com/user/USERNAME/submitted.json?limit=100"
curl "https://www.reddit.com/user/USERNAME/about.json"   # Account age, karma

# Search user's posts in specific subreddit
curl "https://www.reddit.com/r/SUBREDDIT/search.json?q=author:USERNAME&restrict_sr=on&limit=100"

# PushShift (archived data, may include deleted posts)
# https://api.pushshift.io/reddit/search/comment/?author=USERNAME&size=500
```

### Discord

```
# Discord OSINT techniques:
# - Server invite links can reveal server info
# - User IDs encode account creation date (snowflake timestamp)
# - Public bots index messages in some servers

# Decode Discord snowflake ID to timestamp
python3 -c "import datetime; uid=USER_ID; print(datetime.datetime.utcfromtimestamp(((uid >> 22) + 1420070400000) / 1000))"

# Search for Discord invite links in other sources
# Pattern: discord.gg/INVITE or discord.com/invite/INVITE
```

---

## Email Investigation

### Email Header Analysis

```bash
# Extract headers from raw email (saved as email.eml)
# Key headers to examine:
# - Received: (trace route, each hop adds one — read bottom to top)
# - X-Originating-IP: (sender's real IP, if present)
# - Message-ID: (domain reveals sending infrastructure)
# - Return-Path: (bounce address, may differ from From:)

# Parse and display headers
python3 -c "
import email, sys
msg = email.message_from_string(open('email.eml').read())
for h in ['From','To','Date','Subject','Message-ID','X-Originating-IP','Return-Path']:
    print(f'{h}: {msg.get(h, \"N/A\")}')
for i, r in enumerate(msg.get_all('Received', [])):
    print(f'Received[{i}]: {r.strip()[:120]}')
"
```

### SPF / DKIM / DMARC Checking

```bash
# SPF record — authorized senders for domain
dig target.com TXT | grep "v=spf1"

# DKIM selector discovery
dig selector1._domainkey.target.com TXT
dig google._domainkey.target.com TXT
dig default._domainkey.target.com TXT

# DMARC policy
dig _dmarc.target.com TXT

# Verify if a sender IP is authorized by SPF
python3 -c "
import ipaddress, subprocess, re
txt = subprocess.check_output(['dig', '+short', 'target.com', 'TXT']).decode()
# Parse include/ip4/ip6 mechanisms from SPF record
print(txt)
"
```

### Email-to-Identity Correlation

```bash
# holehe — check email registration across sites
holehe target@example.com

# Email format discovery for a company
# Check: Hunter.io, email-format.com, Phonebook.cz
# Common patterns: first.last@, flast@, firstl@

# Gravatar lookup (email hash -> avatar/profile)
python3 -c "
import hashlib
email = 'target@example.com'.strip().lower()
h = hashlib.md5(email.encode()).hexdigest()
print(f'https://gravatar.com/{h}')
print(f'https://gravatar.com/{h}.json')
"
```

### Breach Database Lookup

```bash
# HaveIBeenPwned API (requires API key for searched-by-email)
curl -H "hibp-api-key: $HIBP_KEY" \
  "https://haveibeenpwned.com/api/v3/breachedaccount/target@example.com"

# Check pastes
curl -H "hibp-api-key: $HIBP_KEY" \
  "https://haveibeenpwned.com/api/v3/pasteaccount/target@example.com"

# Breach name lookup (no key needed)
curl "https://haveibeenpwned.com/api/v3/breach/BreachName"
```

---

## Domain / Website Investigation

```bash
# DNS records
dig target.com ANY
dig target.com MX
dig target.com TXT                   # SPF, DKIM, verification records
nslookup target.com

# WHOIS
whois target.com                     # Registration info, registrant

# Historical data
# web.archive.org — Wayback Machine snapshots
# Check old versions for leaked info, removed pages

# Subdomains
subfinder -d target.com
amass enum -d target.com

# Technology detection
whatweb target.com                   # Tech stack
curl -sI target.com                  # Server headers
```

---

## Network Infrastructure Deep Dive

### BGP / ASN Lookup

```bash
# Find ASN for an IP
whois -h whois.radb.net 1.2.3.4       # RADB lookup
curl "https://stat.ripe.net/data/prefix-overview/data.json?resource=1.2.3.4"

# ASN details and prefixes
whois -h whois.radb.net AS12345
curl "https://stat.ripe.net/data/announced-prefixes/data.json?resource=AS12345"

# BGP routing info
curl "https://stat.ripe.net/data/bgp-state/data.json?resource=1.2.3.4"

# Hurricane Electric BGP toolkit
# https://bgp.he.net/AS12345 — prefixes, peers, whois
# https://bgp.he.net/ip/1.2.3.4 — prefix, origin AS
```

### IP Geolocation

```bash
# Free geolocation APIs
curl "https://ipinfo.io/1.2.3.4/json"
curl "https://ipapi.co/1.2.3.4/json"
curl "https://ip-api.com/json/1.2.3.4"

# MaxMind GeoLite2 (local DB, more accurate)
# mmdbinspect -db GeoLite2-City.mmdb 1.2.3.4

# Note: IP geolocation is approximate — city-level at best
# VPNs, CDNs, and cloud providers make it unreliable
```

### Reverse DNS

```bash
# Reverse lookup
dig -x 1.2.3.4                        # PTR record
host 1.2.3.4

# Bulk reverse DNS for a subnet
# Useful for discovering hostnames on shared infrastructure
for i in $(seq 1 254); do
  host 192.168.1.$i 2>/dev/null | grep "name pointer"
done

# DNS zone transfer attempt (often blocked, but worth trying)
dig axfr target.com @ns1.target.com
```

### Port Scanning Patterns for OSINT

```bash
# Light scan — common web/service ports only
nmap -sT -Pn --top-ports 20 target.com

# Shodan (passive — no direct scanning needed)
shodan host 1.2.3.4
shodan search "hostname:target.com"
shodan search "ssl.cert.subject.CN:target.com"

# Censys search
# https://search.censys.io/hosts/1.2.3.4

# Certificate transparency for subdomain discovery
curl -s "https://crt.sh/?q=%.target.com&output=json" | \
  python3 -c "import sys,json;[print(x['name_value']) for x in json.load(sys.stdin)]" | sort -u
```

### Cloud Provider Metadata Detection

```bash
# AWS metadata endpoint (if you have SSRF or access)
curl -s http://169.254.169.254/latest/meta-data/
curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/
curl -s http://169.254.169.254/latest/user-data

# GCP metadata
curl -s -H "Metadata-Flavor: Google" http://169.254.169.254/computeMetadata/v1/

# Azure metadata
curl -s -H "Metadata: true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01"

# Detect cloud provider from IP
# AWS IP ranges: https://ip-ranges.amazonaws.com/ip-ranges.json
# GCP: https://www.gstatic.com/ipranges/cloud.json
# Azure: published as JSON, rotated periodically
python3 -c "
import json, urllib.request, ipaddress
target = ipaddress.ip_address('1.2.3.4')
data = json.loads(urllib.request.urlopen('https://ip-ranges.amazonaws.com/ip-ranges.json').read())
for p in data['prefixes']:
    if target in ipaddress.ip_network(p['ip_prefix']):
        print(f'AWS: {p[\"region\"]} — {p[\"service\"]}'); break
else:
    print('Not in AWS ranges')
"
```

---

## Geolocation

```
Clues to look for in images:
- Street signs, store names (language narrows country)
- License plates (format varies by country)
- Driving side (left vs right)
- Sun position (north vs south hemisphere)
- Vegetation, terrain
- Architecture style
- Power line types
- Road markings

Tools:
- Google Street View — verify location
- Google Lens — identify landmarks
- SunCalc — sun position by time/location
- Overpass Turbo — search OpenStreetMap data
```

---

## Advanced Geolocation

### Google Maps API Tricks

```bash
# Geocode an address to coordinates
curl "https://maps.googleapis.com/maps/api/geocode/json?address=QUERY&key=$GMAP_KEY"

# Reverse geocode coordinates to address
curl "https://maps.googleapis.com/maps/api/geocode/json?latlng=LAT,LON&key=$GMAP_KEY"

# Street View metadata (check if imagery exists at location)
curl "https://maps.googleapis.com/maps/api/streetview/metadata?location=LAT,LON&key=$GMAP_KEY"

# Places search (find nearby landmarks)
curl "https://maps.googleapis.com/maps/api/place/nearbysearch/json?location=LAT,LON&radius=500&key=$GMAP_KEY"

# Without API key: manual Google Maps URL tricks
# https://www.google.com/maps/@LAT,LON,17z       — zoom to location
# https://www.google.com/maps/search/QUERY/@LAT,LON,15z — search near point
```

### Satellite Imagery Analysis

```
Sources:
- Google Earth Pro (free desktop app) — historical imagery slider
- Sentinel Hub EO Browser — free Sentinel-2 satellite data
- NASA Worldview — global daily imagery
- Mapillary — crowdsourced street-level photos (alternative to Street View)

Techniques:
- Compare historical imagery to spot construction/demolition dates
- Measure shadow lengths to estimate building height or time of day
- Use seasonal vegetation changes to narrow date ranges
- Look for unique rooftop patterns or parking lot layouts
```

### Timezone Inference from Metadata

```bash
# Extract timezone from EXIF
exiftool -OffsetTime -OffsetTimeOriginal -TimeZone image.jpg

# If only DateTimeOriginal is available (no timezone):
# Cross-reference with known event times or solar position
# Use SunCalc: given shadow angle + date -> possible lat/lon

# Infer timezone from email headers
# "Date: Mon, 15 Jan 2024 14:30:00 +0530" -> IST (India)
# "Date: Mon, 15 Jan 2024 14:30:00 -0500" -> EST (US East)

python3 -c "
from datetime import timezone, timedelta
offset_hours = 5.5  # +0530
tz = timezone(timedelta(hours=offset_hours))
print(f'UTC offset: {tz}')
# Common: +0530=IST, +0900=JST/KST, +0100=CET, -0500=EST, -0800=PST
"
```

### Cross-Referencing Multiple Geo-Clues

```
Strategy for multi-clue geolocation:
1. List ALL visible clues: language, script, signs, plates, terrain, sun, infrastructure
2. Each clue eliminates regions — intersect the sets
3. Language on signs -> narrow to country/region
4. Driving side -> left (UK, Japan, Aus, India...) or right (most others)
5. License plate format -> specific country (e.g., EU blue strip = Europe)
6. Vegetation + terrain -> climate zone
7. Power poles (wood=rural Americas/Aus, concrete=Europe/Asia)
8. Road markings (yellow center=Americas, white=Europe)
9. Google Maps/Street View to verify final hypothesis
10. Use Overpass Turbo for OSM queries:
    [out:json]; node["shop"="bakery"](around:500,LAT,LON); out;
```

---

## Document / File OSINT

```bash
# PDF/Office metadata
exiftool document.pdf               # Author, creation tool, dates
exiftool document.docx

# Hidden data in documents
strings document.pdf | grep -i flag
binwalk document.pdf                 # Embedded files
```

---

## Code Repository OSINT

### .git Directory Exposure

```bash
# Check if .git is exposed on a web server
curl -s -o /dev/null -w "%{http_code}" https://target.com/.git/HEAD
# 200 = exposed, 403/404 = not accessible

# If exposed, download the repo
# Using git-dumper (pip install git-dumper)
git-dumper https://target.com/.git/ ./dumped-repo

# Manual reconstruction
curl -s https://target.com/.git/HEAD          # Current ref
curl -s https://target.com/.git/config        # Remote URLs, author info
curl -s https://target.com/.git/refs/heads/main  # Commit hash

# Download objects manually
# Given a hash like abc123def456...
curl -s https://target.com/.git/objects/ab/c123def456... -o obj
python3 -c "import zlib; print(zlib.decompress(open('obj','rb').read()))"
```

### Commit History Mining

```bash
# Full commit log with all branches
git log --all --oneline --graph         # Visual overview
git log --all --format="%H %ae %s"      # Hash, email, subject

# Search commit messages
git log --all --grep="password"
git log --all --grep="secret"
git log --all --grep="key"
git log --all --grep="flag"

# Show all authors/committers
git log --all --format="%ae" | sort -u   # Author emails
git log --all --format="%an" | sort -u   # Author names

# Find when a file was deleted
git log --all --diff-filter=D -- "*.env"
git log --all --diff-filter=D -- "config*"
```

### Finding Secrets in Git History

```bash
# Search full diff history for sensitive strings
git log -p --all -S "password"          # Pickaxe: commits that add/remove "password"
git log -p --all -S "BEGIN RSA"
git log -p --all -S "AKIA"             # AWS access key prefix
git log -p --all -S "flag{"

# Grep across all history
git log -p --all | grep -i "password\|secret\|token\|api.key\|flag{"

# Check specific file history
git log -p --all -- ".env"
git log -p --all -- "config.json"
git log -p --all -- "*.pem"

# Tools for automated secret scanning
# trufflehog — scans git history for high-entropy strings and known patterns
trufflehog git file://./repo --only-verified
# gitleaks — fast secret scanner
gitleaks detect -s ./repo -v
```

### GitHub Dork Queries

```bash
# GitHub search operators (use on github.com/search or API)
# Search code for secrets:
#   "password" org:TARGETORG
#   "api_key" user:USERNAME
#   "BEGIN RSA PRIVATE KEY" user:USERNAME
#   filename:.env user:USERNAME
#   filename:id_rsa user:USERNAME
#   filename:credentials user:USERNAME

# Search by file extension:
#   extension:pem user:USERNAME
#   extension:sql user:USERNAME
#   extension:env user:USERNAME

# API-based code search
curl -H "Authorization: token $GH_TOKEN" \
  "https://api.github.com/search/code?q=password+user:USERNAME"

# Search issues and PRs for leaked info
curl -H "Authorization: token $GH_TOKEN" \
  "https://api.github.com/search/issues?q=secret+repo:ORG/REPO"
```

---

## Network / Infrastructure

```bash
# IP lookup
whois 1.2.3.4
nmap -sV target.com                  # Open ports/services
shodan host 1.2.3.4                  # Shodan info

# Certificate transparency
# crt.sh — find subdomains via SSL certificates
curl "https://crt.sh/?q=%.target.com&output=json" | jq '.[].name_value'
```

---

## Wireless / RF OSINT

### BSSID Lookup

```bash
# WiGLE API — lookup wireless network by BSSID (MAC address)
# https://wigle.net — largest wardriving database
# Register for API access at https://api.wigle.net

# Search by BSSID
curl -H "Authorization: Basic $WIGLE_AUTH" \
  "https://api.wigle.net/api/v2/network/search?netid=AA:BB:CC:DD:EE:FF"

# Search by SSID (network name)
curl -H "Authorization: Basic $WIGLE_AUTH" \
  "https://api.wigle.net/api/v2/network/search?ssid=TargetNetwork"

# Search by location
curl -H "Authorization: Basic $WIGLE_AUTH" \
  "https://api.wigle.net/api/v2/network/search?latrange1=LAT1&latrange2=LAT2&longrange1=LON1&longrange2=LON2"
```

### MAC Address Vendor Lookup

```bash
# First 3 octets (OUI) identify the manufacturer
# AA:BB:CC -> vendor lookup

# Online lookup
curl "https://api.macvendors.com/AA:BB:CC:DD:EE:FF"

# Local OUI database (often at /usr/share/nmap/nmap-mac-prefixes)
grep -i "AABBCC" /usr/share/nmap/nmap-mac-prefixes

# Python lookup
python3 -c "
import urllib.request
mac = 'AA:BB:CC:DD:EE:FF'
url = f'https://api.macvendors.com/{mac}'
print(urllib.request.urlopen(url).read().decode())
"

# Significance in CTFs:
# - MAC vendor reveals device type (IoT, router brand, phone manufacturer)
# - Combined with WiGLE, can geolocate a device
# - Helps identify infrastructure in network capture challenges
```

---

## Crypto / Blockchain OSINT

```bash
# Bitcoin address lookup
# blockchain.com/explorer or mempool.space
# Follow transaction chains

# Ethereum
# etherscan.io — address, transactions, contract source
```

---

## CTF-Specific OSINT Tips

### Common Flag Hiding Patterns

```
OSINT CTF challenges typically hide flags via:
1. Image metadata (EXIF GPS, Author, Comment fields)
2. Historical website snapshots (Wayback Machine)
3. DNS TXT records (dig target.com TXT)
4. WHOIS registration details (registrant name/email/org)
5. Git repository history (deleted commits, old branches)
6. Social media profile details (bio, pinned posts, old tweets)
7. SSL certificate details (Subject Alt Names, Organization)
8. Pastebin / GitHub Gist dumps
9. Base64/hex encoded strings in public profiles or comments
10. File metadata in shared documents (PDF author, DOCX properties)
```

### Steganography Overlaps

```bash
# OSINT challenges sometimes embed data in images beyond EXIF
# Quick stego checks that overlap with OSINT:

# Check for appended data after image EOF
strings image.jpg | tail -20
binwalk image.jpg

# Check LSB steganography
zsteg image.png                      # PNG/BMP LSB analysis
steghide extract -sf image.jpg       # JPEG steganography (may need passphrase)

# Sometimes the "OSINT" is finding the passphrase elsewhere
# (e.g., in a social media post) to unlock stego content
```

### Multi-Step Investigation Chains

```
Typical CTF OSINT chain pattern:
1. Start with a username, email, image, or domain
2. Pivot: username -> social media profiles -> real name or location
3. Pivot: email -> breach data -> password reuse or other accounts
4. Pivot: image -> EXIF GPS -> Google Maps -> nearby business name
5. Pivot: domain -> WHOIS -> registrant email -> other domains
6. Pivot: GitHub profile -> commit email -> other repos -> secrets in history

Key mindset:
- Each finding is a PIVOT POINT — ask "what can I search for with this?"
- Document your chain: input -> finding -> next search -> finding -> ...
- If stuck, go back to an earlier pivot and try a different branch
- Check ALL linked accounts, not just the obvious ones
- Look for inconsistencies (different timezones, languages, names)
- Deleted content is gold — always check archives and caches
```

### Quick Checklist for CTF OSINT

```
For EVERY OSINT challenge, run through this checklist:
[ ] exiftool on all provided files
[ ] strings + binwalk on all provided files
[ ] Google/Yandex reverse image search on all images
[ ] sherlock / holehe on any usernames/emails found
[ ] dig ANY + WHOIS on any domains
[ ] Wayback Machine on any URLs
[ ] crt.sh on any domains
[ ] GitHub search for any usernames/emails
[ ] Check source code (View Source) of any web pages
[ ] Base64/hex decode any suspicious strings
```

---

## CRITICAL RULES FOR AGENT

1. **exiftool first on any image** — metadata is the easiest win
2. **Check Wayback Machine** for deleted content
3. **Sherlock for usernames** — fast cross-platform search
4. **Don't overthink** — CTF OSINT usually has a clear trail to follow
5. **Combine clues** — single clue rarely enough, cross-reference findings
6. **Follow the pivot chain** — each finding should lead to a new search; if you hit a dead end, backtrack and try a different pivot
7. **Check DNS TXT records early** — CTFs love hiding flags and clues in TXT, SPF, and DMARC records
8. **Always check git history** — if a repo is involved, `git log -p --all` is mandatory; secrets hide in deleted commits
9. **Use APIs before scraping** — GitHub, Reddit, Twitter all have JSON APIs that are faster and more reliable than parsing HTML
10. **Decode everything suspicious** — base64, hex, ROT13, URL encoding; CTF flags are often lightly encoded in public data
11. **Document your investigation chain** — track what you searched, what you found, and what you pivoted on; this prevents going in circles
12. **Cloud metadata is SSRF gold** — if you find SSRF in an OSINT-adjacent web challenge, always try 169.254.169.254
13. **MAC/BSSID lookups can geolocate** — WiGLE maps wireless networks to physical locations; valuable when a pcap or MAC address is provided
