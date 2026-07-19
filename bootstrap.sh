#!/usr/bin/env bash
# Run this once, inside a-shell, right after `git clone`-ing this repo.
# It installs pure-Python dependencies, sets up local (never-synced) config
# storage, and installs the `aic` launcher into ~/Documents/bin.
#
# It deliberately does not touch OneDrive/pickFolder itself — bookmark a synced
# folder yourself (e.g. via a-shell's `pickFolder` command) before running
# `aic` for the first time, since the first-run prompts will ask for that
# folder's path directly.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_HOME="${MOBILECLI_HOME:-$HOME/Documents/.mobilecli}"
BIN_DIR="$HOME/Documents/bin"

echo "Repo directory: $REPO_DIR"

echo "Installing pure-Python dependencies (pip installs C-extension packages will fail under a-shell by design — see requirements.txt)..."
pip install -r "$REPO_DIR/requirements.txt"

mkdir -p "$LOCAL_HOME" "$BIN_DIR"
if [ ! -f "$LOCAL_HOME/secrets.json" ]; then
  echo "{}" > "$LOCAL_HOME/secrets.json"
fi

cat > "$BIN_DIR/aic" <<LAUNCHER
#!/usr/bin/env python3
import sys
sys.path.insert(0, "$REPO_DIR")
from ai_cli.repl import main
main(sys.argv[1:])
LAUNCHER
chmod +x "$BIN_DIR/aic"

echo ""
echo "Done. Run 'aic' to start (first run will ask for an API key and the path"
echo "to your shared workflow folder)."
