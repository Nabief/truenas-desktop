#!/bin/bash
# ============================================================
#  TrueNAS Desktop — Installeur interactif
#  Fonctionne sur TrueNAS SCALE 23.10+ (Debian 12 base)
#
#  Usage depuis le shell TrueNAS :
#    bash install.sh
#
#  Ou en une commande (une fois le repo en ligne) :
#    curl -fsSL https://raw.githubusercontent.com/VOTRE_USER/truenas-desktop/main/install.sh | bash
# ============================================================
set -e

# ── Couleurs ──────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}▸ $*${RESET}"; }
success() { echo -e "${GREEN}✓ $*${RESET}"; }
warn()    { echo -e "${YELLOW}⚠ $*${RESET}"; }
error()   { echo -e "${RED}✗ $*${RESET}"; exit 1; }
ask()     { echo -e "${BOLD}$*${RESET}"; }

# ── Banner ────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║      TrueNAS Desktop  —  Installeur      ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${RESET}"
echo ""

# ── Vérifications préalables ──────────────────────────────────
info "Vérification des prérequis..."

[ "$(id -u)" -eq 0 ] || error "Ce script doit être exécuté en root (sudo bash install.sh)"

command -v docker   >/dev/null 2>&1 || error "Docker n'est pas installé"
command -v virsh    >/dev/null 2>&1 || warn  "virsh introuvable — libvirt sera configuré pendant l'install"
command -v openssl  >/dev/null 2>&1 || true  # optionnel pour le token

success "Prérequis OK"
echo ""

# ── Chargement config existante (mise à jour) ─────────────────
EXISTING_CONFIG=""
if [ -f "/etc/truenas-desktop/config.env" ]; then
  EXISTING_CONFIG="/etc/truenas-desktop/config.env"
  warn "Installation existante détectée — appuyez sur Entrée pour conserver les valeurs."
  source "$EXISTING_CONFIG" 2>/dev/null || true
fi

# ── Questions de configuration ────────────────────────────────
echo -e "${BOLD}── Configuration ─────────────────────────────────────${RESET}"
echo ""

ask "Répertoire d'installation [${INSTALL_DIR:-/mnt/Truenas_Stockage/apps/desktop}] :"
read -r input
INSTALL_DIR="${input:-${INSTALL_DIR:-/mnt/Truenas_Stockage/apps/desktop}}"

ask "Dossier de stockage des VMs [${VM_DIR:-/mnt/Truenas_Stockage/vms}] :"
read -r input
VM_DIR="${input:-${VM_DIR:-/mnt/Truenas_Stockage/vms}}"

ask "Dossier racine pour les ISOs [${ISO_DIR:-/mnt/Truenas_Stockage}] :"
read -r input
ISO_DIR="${input:-${ISO_DIR:-/mnt/Truenas_Stockage}}"

ask "Port d'écoute HTTP du bureau [${PORT:-8099}] :"
read -r input
PORT="${input:-${PORT:-8099}}"

ask "Adresse IP du TrueNAS [${TRUENAS_IP:-192.168.1.1}] :"
read -r input
TRUENAS_IP="${input:-${TRUENAS_IP:-192.168.1.1}}"

ask "Nom d'hôte / FQDN du TrueNAS [${TRUENAS_HOST:-${TRUENAS_IP}}] :"
read -r input
TRUENAS_HOST="${input:-${TRUENAS_HOST:-${TRUENAS_IP}}}"

# URL utilisée par le bouton "Interface TrueNAS" du bureau.
# Par défaut : IP locale TrueNAS sans port forcé.
TRUENAS_UI_URL="${TRUENAS_UI_URL:-http://${TRUENAS_IP}}"

ask "Utilisateur SSH TrueNAS [${SSH_USER:-truenas_admin}] :"
read -r input
SSH_USER="${input:-${SSH_USER:-truenas_admin}}"

ask "Mot de passe SSH pour $SSH_USER :"
read -rs SSH_PASS_INPUT
echo ""
if [ -n "$SSH_PASS_INPUT" ]; then
  SSH_PASS="$SSH_PASS_INPUT"
elif [ -z "$SSH_PASS" ]; then
  error "Mot de passe SSH obligatoire"
fi

ask "Token sidecar (laissez vide pour en générer un automatiquement) [${FILEOPS_TOKEN:-}] :"
read -r input
if [ -n "$input" ]; then
  FILEOPS_TOKEN="$input"
elif [ -z "$FILEOPS_TOKEN" ]; then
  FILEOPS_TOKEN="$(openssl rand -base64 24 2>/dev/null || cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 32)"
  info "Token généré automatiquement : $FILEOPS_TOKEN"
fi
if [ -z "$DB_ROOT_PASSWORD" ]; then
  DB_ROOT_PASSWORD="$(openssl rand -base64 18 2>/dev/null | tr -dc 'a-zA-Z0-9' | head -c 24 || cat /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 24)"
  info "Mot de passe root MariaDB généré : $DB_ROOT_PASSWORD"
fi
echo ""

# ── Authentification du bureau (barrière serveur) ──────────
ask "Utilisateur d'accès au bureau [${DESK_AUTH_USER:-admin}] :"
read -r input
DESK_AUTH_USER="${input:-${DESK_AUTH_USER:-admin}}"
ask "Mot de passe d'accès au bureau (vide = généré) :"
read -rs DESK_PASS_INPUT
echo ""
if [ -n "$DESK_PASS_INPUT" ]; then
  DESK_AUTH_PASS="$DESK_PASS_INPUT"
elif [ -z "$DESK_AUTH_PASS" ]; then
  DESK_AUTH_PASS="$(openssl rand -base64 12 2>/dev/null | tr -dc 'A-Za-z0-9' | head -c 16)"
  info "Mot de passe bureau généré : $DESK_AUTH_PASS"
fi
echo ""

# ── Résumé ────────────────────────────────────────────────────
echo -e "${BOLD}── Résumé ────────────────────────────────────────────${RESET}"
echo "  Répertoire  : $INSTALL_DIR"
echo "  VMs         : $VM_DIR"
echo "  ISOs        : $ISO_DIR"
echo "  Port        : $PORT"
echo "  TrueNAS IP  : $TRUENAS_IP"
echo "  TrueNAS host: $TRUENAS_HOST"
echo "  TrueNAS UI  : $TRUENAS_UI_URL"
echo "  SSH user    : $SSH_USER"
echo "  Token       : $FILEOPS_TOKEN"
echo "  Accès bureau: $DESK_AUTH_USER / $DESK_AUTH_PASS"
echo ""
ask "Confirmer l'installation ? [O/n]"
read -r confirm
[ "${confirm,,}" = "n" ] && echo "Annulé." && exit 0

# ── Sauvegarde config ─────────────────────────────────────────
mkdir -p /etc/truenas-desktop
cat > /etc/truenas-desktop/config.env << EOF
INSTALL_DIR=$INSTALL_DIR
VM_DIR=$VM_DIR
ISO_DIR=$ISO_DIR
PORT=$PORT
TRUENAS_IP=$TRUENAS_IP
TRUENAS_HOST=$TRUENAS_HOST
TRUENAS_UI_URL=$TRUENAS_UI_URL
SSH_USER=$SSH_USER
SSH_PASS=$SSH_PASS
FILEOPS_TOKEN=$FILEOPS_TOKEN
DB_ROOT_PASSWORD=$DB_ROOT_PASSWORD
DESK_AUTH_USER=$DESK_AUTH_USER
DESK_AUTH_PASS=$DESK_AUTH_PASS
EOF
chmod 600 /etc/truenas-desktop/config.env
success "Configuration sauvegardée dans /etc/truenas-desktop/config.env"

# ── Création des répertoires ──────────────────────────────────
info "Création des répertoires..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$VM_DIR"
chmod 777 "$VM_DIR"
success "Répertoires créés"

# ── .htpasswd (barrière d'auth du bureau) ──────────────
if command -v openssl >/dev/null 2>&1; then
  printf '%s:%s\n' "$DESK_AUTH_USER" "$(openssl passwd -apr1 "$DESK_AUTH_PASS")" > "$INSTALL_DIR/.htpasswd"
  chmod 644 "$INSTALL_DIR/.htpasswd" 2>/dev/null || true
  success ".htpasswd généré (utilisateur : $DESK_AUTH_USER)"
else
  warn "openssl introuvable — .htpasswd non généré ; l'auth du bureau bloquera l'accès tant qu'il manque."
  : > "$INSTALL_DIR/.htpasswd"
fi

# ── Détermine le répertoire source des fichiers ───────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

copy_file() {
  local src="$SCRIPT_DIR/$1"
  local dst="$INSTALL_DIR/$1"
  if [ -f "$src" ]; then
    cp "$src" "$dst"
    success "Copié : $1"
  else
    warn "Fichier source manquant : $src (ignoré)"
  fi
}

# ── Copie des fichiers applicatifs ────────────────────────────
info "Copie des fichiers..."
for f in fileops.py truenas-desktop.html vnc-viewer.html setup-truenas-host.sh update.sh; do
  copy_file "$f"
done

# ── Génération docker-compose.yml ─────────────────────────────
info "Génération de docker-compose.yml..."
cat > "$INSTALL_DIR/docker-compose.yml" << EOF
version: '3.8'

x-php-common: &php-common
  restart: unless-stopped
  environment:
    PHP_INI_SCAN_DIR: ":/conf/ini"
  command:
    - sh
    - -c
    - |
      apk add --no-cache curl >/dev/null 2>&1 || true
      if [ ! -x /usr/local/bin/install-php-extensions ]; then
        curl -sSLf https://github.com/mlocati/docker-php-extension-installer/releases/latest/download/install-php-extensions -o /usr/local/bin/install-php-extensions && chmod +x /usr/local/bin/install-php-extensions || true
      fi
      [ -s /conf/extensions.txt ] && install-php-extensions \$\$(cat /conf/extensions.txt) || true
      ( last=""; lastext=""
        while true; do
          e=\$\$(cat /conf/.extreload 2>/dev/null)
          if [ "\$\$e" != "\$\$lastext" ]; then lastext="\$\$e"; { [ -s /conf/extensions.txt ] && install-php-extensions \$\$(cat /conf/extensions.txt) >/dev/null 2>&1; } || true; kill -USR2 1 2>/dev/null || true; fi
          v=\$\$(cat /conf/.reload 2>/dev/null)
          if [ "\$\$v" != "\$\$last" ]; then last="\$\$v"; kill -USR2 1 2>/dev/null || true; fi
          sleep 3
        done ) &
      exec php-fpm

services:
  truenas-desktop:
    image: nginx:alpine
    container_name: truenas-desktop
    restart: unless-stopped
    user: root
    ports:
      - "${PORT}:80"
    volumes:
      - ${INSTALL_DIR}/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ${INSTALL_DIR}/truenas-desktop.html:/usr/share/nginx/html/index.html:ro
      - ${INSTALL_DIR}/vnc-viewer.html:/usr/share/nginx/html/vnc-viewer.html:ro
      - ${INSTALL_DIR}/.htpasswd:/etc/nginx/.htpasswd:ro

    depends_on:
      - fileops

  fileops:
    image: python:3.11-alpine
    container_name: truenas-fileops
    restart: unless-stopped
    user: root
    stdin_open: true
    tty: true
    environment:
      FILEOPS_TOKEN: "${FILEOPS_TOKEN}"
      FILEOPS_PORT: "8765"
      FILEOPS_WS_PORT: "8766"
      HOST_BOOTSTRAP: "1"
      APP_DIR: "${INSTALL_DIR}"
      GITHUB_RAW: "https://raw.githubusercontent.com/Nabief/truenas-desktop/main"
      TRUENAS_SSH_HOST: "${TRUENAS_IP}"
      TRUENAS_SSH_USER: "${SSH_USER}"
      TRUENAS_SSH_PASS: "${SSH_PASS}"
      TRUENAS_SSH_PORT: "22"
      VM_DIR: "${VM_DIR}"
      ISO_DIR: "${ISO_DIR}"
      WEB_CONF_DIR: "${INSTALL_DIR}/websites/conf.d"
      WEB_PHP_VERSIONS: '{"8.3":"truenas-php83:9000","8.2":"truenas-php82:9000","8.1":"truenas-php81:9000","7.4":"truenas-php74:9000"}'
      WEB_PHP_DEFAULT: "8.3"
      WEB_PHP_DIR: "${INSTALL_DIR}/websites/php"
      WEB_PROXY_PORT: "8080"
      DB_HOST: "mariadb"
      DB_PORT: "3306"
      DB_ROOT_PASSWORD: "${DB_ROOT_PASSWORD}"
    volumes:
      - /mnt:/mnt
      - ${INSTALL_DIR}/fileops.py:/app/fileops.py:ro
    command: sh -c "apk add --no-cache qemu-img ca-certificates && { apk add --no-cache p7zip libarchive-tools 2>/dev/null || true; apk add --no-cache unrar 2>/dev/null || true; } && pip install websockets paramiko pymysql --break-system-packages -q && python /app/fileops.py"
    expose:
      - "8765"
      - "8766"

  websites:
    image: nginx:alpine
    container_name: truenas-websites
    restart: unless-stopped
    ports:
      - "8080:8080"
      - "8100-8130:8100-8130"
    volumes:
      - /mnt:/mnt
      - ${INSTALL_DIR}/websites/conf.d:/etc/nginx/conf.d
    command:
      - sh
      - -c
      - |
        last=""
        ( while true; do
            v=\$\$(cat /etc/nginx/conf.d/.reload 2>/dev/null)
            if [ "\$\$v" != "\$\$last" ]; then last="\$\$v"; nginx -t && nginx -s reload; fi
            sleep 3
          done ) &
        exec nginx -g 'daemon off;'
    depends_on:
      - php83
      - php82
      - php81
      - php74

  php83:
    <<: *php-common
    image: php:8.3-fpm-alpine
    container_name: truenas-php83
    volumes:
      - /mnt:/mnt
      - ${INSTALL_DIR}/websites/php/8.3:/conf

  php82:
    <<: *php-common
    image: php:8.2-fpm-alpine
    container_name: truenas-php82
    volumes:
      - /mnt:/mnt
      - ${INSTALL_DIR}/websites/php/8.2:/conf

  php81:
    <<: *php-common
    image: php:8.1-fpm-alpine
    container_name: truenas-php81
    volumes:
      - /mnt:/mnt
      - ${INSTALL_DIR}/websites/php/8.1:/conf

  php74:
    <<: *php-common
    image: php:7.4-fpm-alpine
    container_name: truenas-php74
    volumes:
      - /mnt:/mnt
      - ${INSTALL_DIR}/websites/php/7.4:/conf

  mariadb:
    image: mariadb:11
    container_name: truenas-mariadb
    restart: unless-stopped
    environment:
      MARIADB_ROOT_PASSWORD: "${DB_ROOT_PASSWORD}"
      MARIADB_AUTO_UPGRADE: "1"
    # Port non publié : accès via le réseau Docker interne uniquement (DB_HOST=mariadb).
    expose:
      - "3306"
    volumes:
      - ${INSTALL_DIR}/mariadb:/var/lib/mysql
EOF
mkdir -p "$INSTALL_DIR/websites/conf.d" "$INSTALL_DIR/websites/php/8.3/ini" "$INSTALL_DIR/websites/php/8.2/ini" "$INSTALL_DIR/websites/php/8.1/ini" "$INSTALL_DIR/websites/php/7.4/ini" "$INSTALL_DIR/mariadb"
success "docker-compose.yml généré"

# ── Génération nginx.conf ─────────────────────────────────────
info "Génération de nginx.conf..."
cat > "$INSTALL_DIR/nginx.conf" << NGINXEOF
server {
    listen 80;
    server_name _;

    # File Station : uploads volumineux
    client_max_body_size 20g;
    client_body_timeout 3600s;
    root /usr/share/nginx/html;
    index index.html;
    # ── Barrière d'authentification devant tout le bureau ────────────
    # Login exigé avant d'accéder à la page (qui contient le token) et aux
    # endpoints fileops / terminal / VNC. /s/ (partages publics) est exempté.
    # 2FA : déléguer à un portail (Authelia / authentik) via auth_request.
    auth_basic           "TrueNAS Desktop";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        try_files \$uri /index.html;
    }

    location = /api/current {
        proxy_pass            https://${TRUENAS_IP}/api/current;
        proxy_http_version    1.1;
        proxy_set_header      Upgrade           \$http_upgrade;
        proxy_set_header      Connection        "upgrade";
        proxy_set_header      Host              ${TRUENAS_HOST};
        proxy_ssl_verify      off;
        proxy_ssl_server_name off;
        proxy_read_timeout    3600s;
        proxy_send_timeout    3600s;
    }

    location /api/ {
        proxy_pass          https://${TRUENAS_IP}/api/;
        proxy_http_version  1.1;
        proxy_ssl_verify    off;
        proxy_ssl_server_name off;
        proxy_set_header    Host              ${TRUENAS_HOST};
        proxy_set_header    Authorization     \$http_authorization;
        proxy_pass_header   Authorization;
        proxy_set_header    Cookie            \$http_cookie;
        proxy_pass_header   Set-Cookie;
        proxy_connect_timeout 10s;
        proxy_read_timeout    30s;
    }

    location /_download/ {
        proxy_pass            https://${TRUENAS_IP}/_download/;
        proxy_http_version    1.1;
        proxy_ssl_verify      off;
        proxy_ssl_server_name off;
        proxy_set_header      Host ${TRUENAS_HOST};
        proxy_read_timeout    120s;
    }

    # Liens de partage publics (sans token) — landing page + téléchargement/zip
    location /s/ {
        auth_basic off;
        proxy_pass            http://fileops:8765/s/;
        proxy_http_version    1.1;
        proxy_set_header      Host \$host;
        proxy_buffering       off;
        proxy_max_temp_file_size 0;
        proxy_read_timeout    3600s;
        proxy_send_timeout    3600s;
        proxy_connect_timeout 30s;
    }

    location /fileops/ {
        proxy_pass         http://fileops:8765/;
        proxy_http_version 1.1;
        proxy_set_header   Host \$host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_connect_timeout 30s;
    }

    location /truenas-shell {
        proxy_pass         http://fileops:8766;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       \$host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location /vnc-proxy {
        proxy_pass         http://fileops:8766;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       \$host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location = /vnc-viewer {
        alias /usr/share/nginx/html/vnc-viewer.html;
        default_type text/html;
        add_header Cache-Control "no-cache";
    }

    location /websocket {
        proxy_pass            https://${TRUENAS_IP}/websocket;
        proxy_http_version    1.1;
        proxy_set_header      Upgrade           \$http_upgrade;
        proxy_set_header      Connection        "upgrade";
        proxy_set_header      Host              ${TRUENAS_HOST};
        proxy_set_header      Authorization     \$http_authorization;
        proxy_pass_header     Authorization;
        proxy_ssl_verify      off;
        proxy_ssl_server_name off;
        proxy_read_timeout    3600s;
        proxy_send_timeout    3600s;
    }
}
NGINXEOF
success "nginx.conf généré"

# ── Injecter le token dans truenas-desktop.html ───────────────
# (si le fichier contient un placeholder FILEOPS_TOKEN_PLACEHOLDER)
if grep -q "FILEOPS_TOKEN_PLACEHOLDER" "$INSTALL_DIR/truenas-desktop.html" 2>/dev/null; then
  sed -i "s|FILEOPS_TOKEN_PLACEHOLDER|${FILEOPS_TOKEN}|g" "$INSTALL_DIR/truenas-desktop.html"
  success "Token injecté dans truenas-desktop.html"
fi

# ── Injection configuration locale dans le HTML ───────────────
# Important : NAS_URL reste vide pour que les appels API passent par le nginx du bureau.
# Le bouton "Interface TrueNAS" ouvre l'URL native locale, par défaut http://TRUENAS_IP.
info "Injection de la configuration locale dans truenas-desktop.html..."
python3 - << PYCFG
from pathlib import Path
import re
p = Path(r"$INSTALL_DIR/truenas-desktop.html")
s = p.read_text(encoding="utf-8")
s = re.sub(r"const NAS_URL\s*=\s*['\"][^'\"]*['\"];", "const NAS_URL = '';", s, count=1)
s = re.sub(r"const TRUENAS_UI\s*=\s*['\"][^'\"]*['\"];", "const TRUENAS_UI = '$TRUENAS_UI_URL';", s, count=1)
p.write_text(s, encoding="utf-8")
PYCFG
success "Configuration locale injectée : Interface TrueNAS -> $TRUENAS_UI_URL"

# ── Réparation : suppression des anciennes modifs /etc (boot 25.x) ──
info "Nettoyage des anciennes modifications systemd/libvirt..."
systemctl disable truenas-desktop 2>/dev/null || true
rm -f /etc/systemd/system/truenas-desktop.service
rm -f /etc/systemd/system/libvirtd.service.d/notimeout.conf
rmdir /etc/systemd/system/libvirtd.service.d 2>/dev/null || true
rm -f /etc/tmpfiles.d/truenas-libvirt.conf
rm -f /etc/polkit-1/rules.d/80-truenas-libvirt.rules
systemctl daemon-reload 2>/dev/null || true

# ── Préparation libvirt à la demande (sans modif /etc, sans 'enable') ──
info "Préparation de libvirt (à la demande)..."
bash "$INSTALL_DIR/setup-truenas-host.sh" || warn "Préparation libvirt non bloquante"

# ── Démarrage automatique via Init/Shutdown Script TrueNAS (POSTINIT) ──
# Remplace l'ancien service systemd : un POSTINIT s'exécute APRÈS le middleware,
# hors du chemin critique de boot (aucun « ordering cycle » possible sur 25.x).
info "Configuration du démarrage automatique (POSTINIT)..."
cat > "$INSTALL_DIR/autostart.sh" << 'AEOF'
#!/bin/bash
# TrueNAS Desktop — demarrage POSTINIT (v1.4.0). N'altere jamais l'ordonnancement systemd.
set +e
INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$INSTALL_DIR/autostart.log"
echo "=== $(date '+%F %T') POSTINIT ===" >> "$LOG"
for i in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 2; done
systemctl start libvirtd 2>/dev/null || systemctl start virtqemud 2>/dev/null || true
virsh -c qemu:///system net-start default >/dev/null 2>&1 || true
cd "$INSTALL_DIR" && /usr/bin/docker compose up -d >> "$LOG" 2>&1
echo "exit docker compose: $?" >> "$LOG"
AEOF
chmod +x "$INSTALL_DIR/autostart.sh"
if command -v midclt >/dev/null 2>&1; then
  midclt call initshutdownscript.query '[["comment","=","TrueNAS Desktop autostart"]]' 2>/dev/null \
    | python3 -c 'import sys,json
try:
    for e in json.load(sys.stdin): print(e["id"])
except Exception: pass' 2>/dev/null \
    | while read -r _id; do [ -n "$_id" ] && midclt call initshutdownscript.delete "$_id" >/dev/null 2>&1; done
  if midclt call initshutdownscript.create \
      "{\"type\":\"COMMAND\",\"command\":\"bash $INSTALL_DIR/autostart.sh\",\"when\":\"POSTINIT\",\"enabled\":true,\"timeout\":300,\"comment\":\"TrueNAS Desktop autostart\"}" >/dev/null 2>&1; then
    success "Démarrage auto configuré (Init/Shutdown Script POSTINIT)"
  else
    warn "POSTINIT non créé — lancez \$INSTALL_DIR/autostart.sh au besoin."
  fi
else
  warn "midclt introuvable — démarrage auto non configuré."
fi

# ── Démarrage de la stack Docker ──────────────────────────────
info "Démarrage de la stack Docker..."
cd "$INSTALL_DIR"
docker compose up -d --force-recreate 2>/dev/null || docker-compose up -d --force-recreate
# Force nginx à relire le HTML monté et évite de servir une ancienne version.
docker restart truenas-desktop >/dev/null 2>&1 || true
success "Stack Docker démarrée et conteneur desktop redémarré"

# ── Résultat final ────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}${BOLD}║   Installation terminée avec succès !    ║${RESET}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════╝${RESET}"
echo ""
echo -e "  Bureau accessible sur : ${BOLD}http://$(hostname -I | awk '{print $1}'):${PORT}${RESET}"
echo ""
echo -e "  Pour mettre à jour plus tard : ${CYAN}bash $INSTALL_DIR/update.sh${RESET}"
echo ""
