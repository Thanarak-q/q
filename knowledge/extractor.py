"""Auto-extract knowledge entries from solve sessions.

Analyzes tool calls and commands to identify techniques, file types,
and useful commands for the knowledge base.
"""

from __future__ import annotations

from typing import Any


def extract_from_solve(
    challenge: str,
    category: str,
    steps_log: list[dict[str, Any]],
    answer: str,
    flag: str | None,
    cost: float,
) -> dict[str, Any]:
    """Generate a knowledge entry from a completed solve session.

    Args:
        challenge: Challenge description text.
        category: Classified category.
        steps_log: List of step dicts from session data.
        answer: Final answer text.
        flag: Found flag string, or None.
        cost: Total cost in USD.

    Returns:
        Knowledge entry dict ready for KnowledgeBase.add().
    """
    commands: list[str] = []
    tools_used: set[str] = set()
    techniques: set[str] = set()
    file_types: set[str] = set()

    for step in steps_log:
        if step.get("event") != "tool_call":
            continue

        tool = step.get("tool_name", "")
        tools_used.add(tool)
        args = step.get("tool_args", {})

        if tool == "shell":
            cmd = args.get("command", "")
            if cmd:
                commands.append(cmd)
                _detect_shell_techniques(cmd, techniques)

        elif tool == "python_exec":
            code = args.get("code", "")
            _detect_python_techniques(code, techniques)

        elif tool == "browser":
            techniques.add("browser automation")

        elif tool == "network":
            method = args.get("method", "")
            if method == "http":
                techniques.add("HTTP requests")
            elif method == "tcp":
                techniques.add("raw TCP")

    # Detect file types from challenge text
    _detect_file_types(challenge, file_types)

    return {
        "challenge": challenge[:200],
        "category": category,
        "file_types": sorted(file_types),
        "techniques": sorted(techniques),
        "tools_used": sorted(tools_used),
        "commands": commands[:5],
        "answer": answer[:200] if answer else "",
        "flag": flag or "",
        "steps": len(steps_log),
        "cost": round(cost, 4),
        "success": bool(answer or flag),
    }


def _detect_shell_techniques(cmd: str, techniques: set[str]) -> None:
    """Detect techniques from a shell command."""
    patterns = {
        "tshark": {
            "-z conv": "tshark conversation stats",
            "-Y http": "http traffic filter",
            "-z http,tree": "http tree stats",
            "-T fields": "tshark field extraction",
        },
        "strings": {"": "strings extraction"},
        "binwalk": {"": "binwalk embedded files"},
        "steghide": {"": "steghide extraction"},
        "stegsolve": {"": "stegsolve analysis"},
        "zsteg": {"": "zsteg PNG analysis"},
        "volatility": {"": "memory forensics"},
        "vol3": {"": "memory forensics"},
        "vol.py": {"": "memory forensics"},
        "sqlmap": {"": "SQL injection"},
        "hashcat": {"": "hash cracking"},
        "john": {"": "hash cracking"},
        "gdb": {"": "binary debugging"},
        "ghidra": {"": "decompilation"},
        "r2": {"": "radare2 analysis"},
        "objdump": {"": "disassembly"},
        "base64": {"": "base64 decoding"},
        "xxd": {"": "hex analysis"},
        "file ": {"": "file type detection"},
        "foremost": {"": "file carving"},
        "exiftool": {"": "metadata extraction"},
        "openssl": {"": "OpenSSL crypto"},
        "curl": {"": "HTTP request"},
        "wget": {"": "HTTP download"},
        "nmap": {"": "port scanning"},
        "gobuster": {"": "directory brute force"},
        "ffuf": {"": "web fuzzing"},
        "checksec": {"": "binary security check"},
        "ROPgadget": {"": "ROP gadget search"},
        "one_gadget": {"": "one_gadget search"},
        "patchelf": {"": "ELF patching"},
    }

    cmd_lower = cmd.lower()
    for tool_key, sub_patterns in patterns.items():
        if tool_key.lower() in cmd_lower:
            for sub_key, technique_name in sub_patterns.items():
                if not sub_key or sub_key in cmd:
                    techniques.add(technique_name)


def _detect_python_techniques(code: str, techniques: set[str]) -> None:
    """Detect techniques from Python code."""
    detections = {
        "pwntools": "pwntools exploit",
        "from pwn": "pwntools exploit",
        "z3": "z3 constraint solving",
        "Crypto.": "pycryptodome",
        "from Crypto": "pycryptodome",
        "hashlib": "hash computation",
        "angr": "angr symbolic execution",
        "capstone": "capstone disassembly",
        "PIL": "image processing",
        "struct.": "binary struct parsing",
        "scapy": "scapy packet crafting",
        "requests": "HTTP requests",
        "beautifulsoup": "HTML parsing",
        "base64": "base64 decoding",
        "binascii": "binary encoding",
    }

    code_lower = code.lower()
    for pattern, technique in detections.items():
        if pattern.lower() in code_lower:
            techniques.add(technique)


def _detect_file_types(text: str, file_types: set[str]) -> None:
    """Detect file types mentioned in challenge text."""
    detections = {
        ".pcap": "pcap",
        ".pcapng": "pcap",
        "wireshark": "pcap",
        "packet capture": "pcap",
        ".pdf": "pdf",
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".gif": "image",
        ".bmp": "image",
        ".dmp": "memory_dump",
        "memory dump": "memory_dump",
        "memdump": "memory_dump",
        ".vmem": "memory_dump",
        ".zip": "archive",
        ".tar": "archive",
        ".gz": "archive",
        ".7z": "archive",
        ".rar": "archive",
        ".elf": "elf_binary",
        "binary": "elf_binary",
        "executable": "elf_binary",
        ".py": "python",
        ".js": "javascript",
        ".php": "php",
        ".sql": "sql",
        ".db": "database",
        ".sqlite": "database",
    }

    text_lower = text.lower()
    for pattern, ftype in detections.items():
        if pattern in text_lower:
            file_types.add(ftype)
