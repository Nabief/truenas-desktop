#!/bin/bash
# ============================================================
#  TrueNAS Desktop — Mise à jour
#  Relit la config existante, met à jour les fichiers,
#  redémarre la stack sans toucher aux données.
#
#  Usage :
#    bash /mnt/Truenas_Stockage/apps/desktop/update.sh
# ============================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()    { echo -e "${CYAN}▸ $*${RESET}"; }
success() { echo -e "${GREEN}✓ $*${RESET}"; }
error()   { echo -e "${RED}✗ $*${RESET}"; exit 1; }

CONFIG="/etc/truenas-desktop/config.env"
[ -f "$CONFIG" ] || error "Aucune config trouvée dans $CONFIG — lancez install.sh d'abord"
source "$CONFIG"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "${BOLD}── TrueNAS Desktop — Mise à jour ──────────────────${RESET}"
echo "  Depuis  : $SCRIPT_DIR"
echo "  Vers    : $INSTALL_DIR"
echo ""

info "Copie des fichiers mis à jour..."
for f in fileops.py truenas-desktop.html vnc-viewer.html setup-truenas-host.sh; do
  src="$SCRIPT_DIR/$f"
  dst="$INSTALL_DIR/$f"
  if [ -f "$src" ] && [ "$src" != "$dst" ]; then
    cp "$src" "$dst"
    success "Mis à jour : $f"
  elif [ -f "$src" ]; then
    success "En place : $f (source = destination)"
  fi
done

# ── Injecter le token dans truenas-desktop.html ──────────────
if [ -n "$FILEOPS_TOKEN" ] && [ -f "$INSTALL_DIR/truenas-desktop.html" ]; then
  sed -i "s|FILEOPS_TOKEN_DEFAULT = '[^']*'|FILEOPS_TOKEN_DEFAULT = '${FILEOPS_TOKEN}'|g" "$INSTALL_DIR/truenas-desktop.html"
  success "Token injecté dans truenas-desktop.html"
fi

info "Redémarrage de la stack..."
cd "$INSTALL_DIR"
docker compose restart 2>/dev/null || docker-compose restart
success "Stack redémarrée"

echo ""
success "Mise à jour terminée !"
