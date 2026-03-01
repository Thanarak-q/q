#!/usr/bin/env bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
RESET='\033[0m'

REPO="https://github.com/Thanarak-q/q"
REPO_DIR="$HOME/.local/share/agentq"
APP_DIR="$REPO_DIR"

echo -e "\n${BOLD}Installing agentq...${RESET}\n"

# ── 1. Check Python ──────────────────────────────────────────────────────────

PYTHON=""
for py in python3 python; do
  if command -v "$py" &>/dev/null; then
    ver=$("$py" -c "import sys; v=sys.version_info; print(v.major,v.minor)" 2>/dev/null)
    major=$(echo "$ver" | cut -d' ' -f1)
    minor=$(echo "$ver" | cut -d' ' -f2)
    if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
      PYTHON="$py"
      echo -e "${GREEN}✓${RESET} Python $major.$minor found"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo -e "${RED}✗ Python 3.10+ not found. Install from https://python.org${RESET}"
  exit 1
fi

# ── 2. Check git ─────────────────────────────────────────────────────────────

if ! command -v git &>/dev/null; then
  echo -e "${RED}✗ git not found. Install git and try again.${RESET}"
  exit 1
fi

# ── 3. Clone or update repo ───────────────────────────────────────────────────

if [ -d "$REPO_DIR/.git" ]; then
  echo "  Updating from GitHub..."
  git -C "$REPO_DIR" pull --quiet
  echo -e "${GREEN}✓${RESET} Updated to latest version"
else
  echo "  Cloning from GitHub..."
  git clone "$REPO" "$REPO_DIR" --quiet
  echo -e "${GREEN}✓${RESET} Cloned repository"
fi

# ── 4. Install pip dependencies ──────────────────────────────────────────────

echo "  Installing Python dependencies..."
"$PYTHON" -m pip install -r "$APP_DIR/requirements.txt" --quiet --user
echo -e "${GREEN}✓${RESET} Dependencies installed"

# ── 5. Create ~/.q directories ───────────────────────────────────────────────

mkdir -p ~/.q/logs ~/.q/sessions ~/.q/sessions/screenshots ~/.q/reports
echo -e "${GREEN}✓${RESET} Created ~/.q/ data directory"

# ── 6. Create ~/.q/settings.json if missing ──────────────────────────────────

if [ ! -f ~/.q/settings.json ]; then
  cat > ~/.q/settings.json <<'EOF'
{
  "openai_api_key": "",
  "anthropic_api_key": "",
  "google_api_key": "",

  "default_model": "gpt-4o",
  "fast_model": "gpt-4o-mini",
  "reasoning_model": "o3",
  "fallback_model": "",

  "temperature": 0.2,
  "max_tokens": 4096,
  "streaming": true,

  "max_iterations": 15,
  "max_cost_per_challenge": 2.00,

  "log_level": "INFO",
  "sandbox_mode": "docker"
}
EOF
  echo -e "${GREEN}✓${RESET} Created ~/.q/settings.json"
fi

# ── 7. Install agentq command ─────────────────────────────────────────────────

mkdir -p ~/.local/bin
cat > ~/.local/bin/agentq <<'EOF'
#!/usr/bin/env bash
REPO_DIR="$HOME/.local/share/agentq"
APP_DIR="$REPO_DIR"

# Discover Python 3.10+ at runtime — never baked in at install time
PYTHON=""
for py in python3 python; do
  if command -v "$py" &>/dev/null; then
    ver=$("$py" -c "import sys; v=sys.version_info; print(v.major,v.minor)" 2>/dev/null)
    major=$(echo "$ver" | cut -d' ' -f1)
    minor=$(echo "$ver" | cut -d' ' -f2)
    if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
      PYTHON="$py"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo "Error: Python 3.10+ not found. Install from https://python.org"
  exit 1
fi

# Handle update subcommand
if [ "$1" = "update" ]; then
  echo "Updating agentq..."
  git -C "$REPO_DIR" pull
  "$PYTHON" -m pip install -r "$APP_DIR/requirements.txt" --quiet --user
  echo "Done! agentq is up to date."
  exit 0
fi

exec "$PYTHON" "$APP_DIR/main.py" "$@"
EOF
chmod +x ~/.local/bin/agentq
echo -e "${GREEN}✓${RESET} Installed agentq command"

# ── 8. Ensure ~/.local/bin is on PATH ────────────────────────────────────────

SHELL_RC=""
if [ -n "$ZSH_VERSION" ] || [ "$(basename "$SHELL")" = "zsh" ]; then
  SHELL_RC="$HOME/.zshrc"
elif [ -n "$BASH_VERSION" ] || [ "$(basename "$SHELL")" = "bash" ]; then
  SHELL_RC="$HOME/.bashrc"
fi

if [ -n "$SHELL_RC" ] && ! grep -q 'local/bin' "$SHELL_RC" 2>/dev/null; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
  echo -e "${GREEN}✓${RESET} Added ~/.local/bin to PATH in $SHELL_RC"
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo -e "\n${BOLD}${GREEN}agentq is ready!${RESET}\n"

if grep -q '"openai_api_key": ""' ~/.q/settings.json 2>/dev/null; then
  echo -e "${YELLOW}Next: add your API key to ~/.q/settings.json${RESET}"
  echo '  "openai_api_key": "sk-..."'
  echo '  "anthropic_api_key": "sk-ant-..."'
  echo ""
fi

echo -e "Type ${BOLD}agentq${RESET} to start."
echo -e "To update later: ${BOLD}agentq update${RESET}"
echo -e "(If command not found, run: ${BOLD}source $SHELL_RC${RESET})\n"
