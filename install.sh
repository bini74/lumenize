#!/bin/sh
# Crée le venv, installe bleak et la commande ~/.local/bin/lumenize.
set -eu
cd "$(dirname "$0")"
DIR="$(pwd)"

echo "→ environnement Python…"
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/lumenize" <<WRAP
#!/bin/sh
exec "$DIR/.venv/bin/python" "$DIR/cli.py" "\$@"
WRAP
chmod +x "$HOME/.local/bin/lumenize"
echo "✓ installé : $HOME/.local/bin/lumenize"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "⚠ ajoute ~/.local/bin au PATH" ;; esac
