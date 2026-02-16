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

## Crypto / Blockchain OSINT

```bash
# Bitcoin address lookup
# blockchain.com/explorer or mempool.space
# Follow transaction chains

# Ethereum
# etherscan.io — address, transactions, contract source
```

---

## CRITICAL RULES FOR AGENT

1. **exiftool first on any image** — metadata is the easiest win
2. **Check Wayback Machine** for deleted content
3. **Sherlock for usernames** — fast cross-platform search
4. **Don't overthink** — CTF OSINT usually has a clear trail to follow
5. **Combine clues** — single clue rarely enough, cross-reference findings
