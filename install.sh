#!/usr/bin/env sh
# Instala o erp-fakes (Linux e macOS). Uso:
#   curl -fsSL https://raw.githubusercontent.com/ggvinos/erp-fakes-qa/main/install.sh | sh
#   ./install.sh --remover     desinstala
# Variáveis: ERP_FAKES_SRC (origem do pip, padrão o GitHub ou esta pasta), ERP_FAKES_SEM_TUNEL=1 (não baixa o cloudflared)
set -eu

REPO="git+https://github.com/ggvinos/erp-fakes-qa.git"
DIR="${XDG_DATA_HOME:-$HOME/.local/share}/erp-fakes"
BIN="$HOME/.local/bin"

if [ "${1:-}" = "--remover" ]; then
  if command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q erp-fakes; then pipx uninstall erp-fakes; fi
  rm -rf "$DIR" "$BIN/erp-fakes"
  echo "erp-fakes removido. Estado e chaves continuam em ~/.config/erp-fakes (apague se quiser)."
  exit 0
fi

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "Precisa de Python 3.10 ou superior." >&2; exit 1; }

if [ -n "${ERP_FAKES_SRC:-}" ]; then SRC="$ERP_FAKES_SRC"
elif [ -f "$(dirname "$0")/pyproject.toml" ] 2>/dev/null; then SRC="$(cd "$(dirname "$0")" && pwd)"
else SRC="$REPO"; fi

if command -v pipx >/dev/null 2>&1; then
  pipx install --force "$SRC"
else
  "$PY" -m venv "$DIR/venv" || { echo "Falhou criar o venv. No Debian/Ubuntu: sudo apt install python3-venv" >&2; exit 1; }
  "$DIR/venv/bin/pip" install --quiet --upgrade "$SRC"
  mkdir -p "$BIN"
  ln -sf "$DIR/venv/bin/erp-fakes" "$BIN/erp-fakes"
fi

CMD="erp-fakes"
command -v erp-fakes >/dev/null 2>&1 || CMD="$BIN/erp-fakes"

if [ "${ERP_FAKES_SEM_TUNEL:-}" != "1" ]; then
  "$CMD" --instalar-tunel || echo "Aviso: sem o cloudflared o programa só funciona com --no-tunnel."
fi

case ":$PATH:" in *":$BIN:"*) ;; *) echo "Adicione $BIN ao PATH para usar o comando erp-fakes." ;; esac
echo "Pronto. Rode: erp-fakes"
