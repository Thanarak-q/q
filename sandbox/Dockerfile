FROM ubuntu:22.04

LABEL maintainer="ctf-agent"
LABEL description="Sandbox environment for CTF challenge solving with pre-installed tools"

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# ── Base system + build tools ──────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    autoconf \
    automake \
    libtool \
    pkg-config \
    ca-certificates \
    gnupg \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# ── Python ─────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# ── Networking tools ───────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    netcat-openbsd \
    nmap \
    socat \
    dnsutils \
    whois \
    openssh-client \
    proxychains4 \
    tcpdump \
    tshark \
    && rm -rf /var/lib/apt/lists/*

# ── Crypto & encoding tools ───────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssl \
    libssl-dev \
    libgmp-dev \
    libmpfr-dev \
    libmpc-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Binary analysis & reversing ───────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    file \
    binutils \
    xxd \
    gdb \
    gdbserver \
    ltrace \
    strace \
    radare2 \
    upx-ucl \
    nasm \
    && rm -rf /var/lib/apt/lists/*

# ── Forensics tools ───────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    binwalk \
    foremost \
    exiftool \
    steghide \
    pngcheck \
    poppler-utils \
    sox \
    libimage-exiftool-perl \
    testdisk \
    sleuthkit \
    unzip \
    p7zip-full \
    cabextract \
    rar \
    xz-utils \
    bzip2 \
    cpio \
    && rm -rf /var/lib/apt/lists/*

# ── Web tools ─────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    jq \
    libxml2-utils \
    git \
    && rm -rf /var/lib/apt/lists/*

# ── Web recon tools ───────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    nikto \
    whatweb \
    && rm -rf /var/lib/apt/lists/*

# ── Subfinder (subdomain enumeration) ────────────────────────────────
RUN wget -q -O /tmp/subfinder.zip \
    https://github.com/projectdiscovery/subfinder/releases/download/v2.6.6/subfinder_2.6.6_linux_amd64.zip \
    && unzip -o /tmp/subfinder.zip -d /usr/local/bin/ subfinder \
    && chmod +x /usr/local/bin/subfinder \
    && rm -f /tmp/subfinder.zip \
    || true

# ── wordlists directory ───────────────────────────────────────────────
RUN mkdir -p /usr/share/wordlists

# ── sqlmap (latest from git) ──────────────────────────────────────────
RUN git clone --depth 1 https://github.com/sqlmapproject/sqlmap.git /opt/sqlmap \
    && ln -s /opt/sqlmap/sqlmap.py /usr/local/bin/sqlmap

# ── gobuster ──────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends golang-go \
    && go install github.com/OJ/gobuster/v3@latest \
    && cp /root/go/bin/gobuster /usr/local/bin/gobuster \
    && apt-get purge -y golang-go \
    && apt-get autoremove -y \
    && rm -rf /root/go /var/lib/apt/lists/*

# ── John the Ripper (jumbo) ───────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    john \
    fcrackzip \
    hashcat \
    && rm -rf /var/lib/apt/lists/*

# ── Small common wordlist for in-container use ─────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    wordlist \
    wamerican-small \
    && rm -rf /var/lib/apt/lists/* \
    && if [ -f /usr/share/dict/american-english-small ]; then \
       ln -sf /usr/share/dict/american-english-small /usr/share/wordlists/english.txt; fi

# ── Python CTF libraries ──────────────────────────────────────────────
RUN pip3 install --no-cache-dir --break-system-packages \
    pwntools \
    pycryptodome \
    z3-solver \
    gmpy2 \
    sympy \
    requests \
    httpx \
    beautifulsoup4 \
    lxml \
    Pillow \
    numpy \
    scipy \
    ropper \
    ROPGadget \
    randcrack \
    python-magic \
    pyshark \
    scapy \
    hashpumpy || true

# ── angr (separate layer — large install) ─────────────────────────────
RUN pip3 install --no-cache-dir --break-system-packages angr || true

# ── one_gadget (Ruby gem) ─────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends ruby ruby-dev \
    && gem install one_gadget --no-document \
    && rm -rf /var/lib/apt/lists/*

# ── checksec.sh ───────────────────────────────────────────────────────
RUN wget -q -O /usr/local/bin/checksec \
    https://raw.githubusercontent.com/slimm609/checksec.sh/main/checksec \
    && chmod +x /usr/local/bin/checksec

# ── zsteg (Ruby gem for PNG/BMP stego) ────────────────────────────────
RUN gem install zsteg --no-document

# ── git-dumper (for .git exposure) ────────────────────────────────────
RUN pip3 install --no-cache-dir --break-system-packages git-dumper || true

# ── pycdc / decompyle3 (Python decompilers) ───────────────────────────
RUN pip3 install --no-cache-dir --break-system-packages \
    decompyle3 \
    uncompyle6 \
    xortool \
    || true

# ── Cleanup ───────────────────────────────────────────────────────────
RUN apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# ── Workspace ─────────────────────────────────────────────────────────
WORKDIR /workspace

# ── Non-root user for isolation ───────────────────────────────────────
RUN useradd -m -s /bin/bash -u 1000 ctfplayer \
    && chown ctfplayer:ctfplayer /workspace
USER ctfplayer

# ── Health check ──────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=3s \
    CMD pgrep -x sleep > /dev/null || exit 1

CMD ["sleep", "infinity"]
