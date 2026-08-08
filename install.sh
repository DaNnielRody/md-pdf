#!/bin/sh
set -eu

SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SHARE="${XDG_DATA_HOME:-$HOME/.local/share}/mdpdf"
BIN="$HOME/.local/bin"

say()  { printf '%s\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; }

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$SHARE" "$BIN/mdpdf"
    say "✓ mdpdf removed from $SHARE and $BIN"
    exit 0
fi

missing=0
for cmd in python3 pandoc weasyprint; do
    command -v "$cmd" >/dev/null 2>&1 || { warn "missing: $cmd"; missing=1; }
done

python3 - <<'PY' 2>/dev/null || { echo "  ! python3 must be 3.11+ (tomllib)" >&2; missing=1; }
import sys, tomllib
sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY

command -v npx >/dev/null 2>&1 || warn "npx not found — Mermaid diagrams will be skipped"
for b in /usr/bin/microsoft-edge /usr/bin/google-chrome /usr/bin/chromium /usr/bin/chromium-browser; do
    [ -x "$b" ] && { browser=$b; break; }
done
[ -n "${browser:-}" ] || warn "no Chromium found — Mermaid diagrams will be skipped"

if [ "$missing" -eq 1 ]; then
    cat >&2 <<'EOF'

Install what is missing and run again:

  Debian/Ubuntu   sudo apt install pandoc weasyprint python3
  Fedora          sudo dnf install pandoc weasyprint python3
  Arch            sudo pacman -S pandoc python-weasyprint python
  macOS           brew install pandoc weasyprint python@3.12
  pip (any)       pipx install weasyprint

EOF
    exit 1
fi

mkdir -p "$SHARE" "$BIN"

if [ "${1:-}" = "--link" ]; then
    rm -rf "$SHARE"
    ln -s "$SRC" "$SHARE"
    say "→ $SHARE -> $SRC (symlink)"
else
    rm -rf "$SHARE"
    mkdir -p "$SHARE"
    cp -R "$SRC/mdpdf.py" "$SRC/design.py" "$SRC/base.css" "$SRC/themes" "$SHARE/"
    [ -f "$SRC/README.md" ] && cp "$SRC/README.md" "$SHARE/"
    say "→ $SHARE"
fi

cat > "$BIN/mdpdf" <<EOF
#!/bin/sh
exec python3 "${SHARE}/mdpdf.py" "\$@"
EOF
chmod +x "$BIN/mdpdf"
say "→ $BIN/mdpdf"

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) warn "$BIN is not on your PATH — add this to your ~/.zshrc:"
       warn '  export PATH="$HOME/.local/bin:$PATH"' ;;
esac

say ""
say "✓ installed. Check with:  mdpdf themes"
