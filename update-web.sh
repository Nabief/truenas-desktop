#!/bin/bash
# ============================================================
#  TrueNAS Desktop — Mise à jour en une commande
#
#  Depuis TrueNAS → System → Shell :
#    curl -fsSL https://raw.githubusercontent.com/Nabief/truenas-desktop/main/update-web.sh | sudo bash
#
#  Relit la config existante, re-télécharge les fichiers depuis
#  GitHub, ré-injecte le token, et recharge. Aucune resaisie.
# ============================================================
set -e

CONFIG=/etc/truenas-desktop/config.env
if [ ! -f "$CONFIG" ]; then
  echo "✗ Config introuvable ($CONFIG). Lance d'abord l'installation."
  exit 1
fi
# shellcheck disable=SC1090
. "$CONFIG"

GITHUB_RAW="${GITHUB_RAW:-https://raw.githubusercontent.com/Nabief/truenas-desktop/main}"
D="${INSTALL_DIR:?INSTALL_DIR manquant dans la config}"

echo "▸ Mise à jour depuis $GITHUB_RAW"
echo "  vers $D"

for f in fileops.py truenas-desktop.html vnc-viewer.html; do
  curl -fsSL "$GITHUB_RAW/$f" -o "$D/$f" && echo "  + $f"
done

# Ré-injecter le token dans le HTML (le fichier GitHub a un placeholder)
if [ -n "$FILEOPS_TOKEN" ]; then
  sed -i "s|FILEOPS_TOKEN_PLACEHOLDER|${FILEOPS_TOKEN}|g" "$D/truenas-desktop.html"
fi

# Le HTML est servi à chaud par nginx ; seul le sidecar doit redémarrer
# pour recharger fileops.py.
docker restart truenas-fileops >/dev/null 2>&1 || true

echo "✓ Mise à jour terminée."
echo "  Recharge le bureau avec Ctrl+F5 (attends ~30 s si le module VMs affiche 502)."
