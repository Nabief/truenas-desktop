#!/usr/bin/env python3
# =============================================================
#  TrueNAS Desktop — Wizard d'installation web
#
#  Usage depuis le shell TrueNAS :
#    python3 /mnt/Truenas_Stockage/apps/desktop/setup-wizard.py
#
#  Puis ouvrir dans le navigateur :
#    http://IP_TRUENAS:8099/setup
# =============================================================

import http.server
import json
import os
import re
import subprocess
import threading
import socket
import sys
import secrets
import shutil
import queue
import time
import urllib.parse

PORT = 8090
GITHUB_RAW_DEFAULT = 'https://raw.githubusercontent.com/Nabief/truenas-desktop/main'
INSTALL_EVENTS = queue.Queue()
INSTALL_RUNNING = False
INSTALL_DONE = False

# ── Auto-détection IP ─────────────────────────────────────────
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

# ── Détection des pools ZFS montés sous /mnt ──────────────────
def list_pools():
    pools = []
    _SKIP = {'ix-apps', 'ix-applications', 'ix-virt', 'lost+found'}
    try:
        for name in sorted(os.listdir('/mnt')):
            if name.startswith('.') or name in _SKIP:
                continue
            if os.path.isdir(os.path.join('/mnt', name)):
                pools.append(name)
    except Exception:
        pass
    return pools

# ── Vérification prérequis ────────────────────────────────────
def check_prerequisites():
    results = {}
    results['root'] = os.geteuid() == 0
    results['docker'] = shutil.which('docker') is not None
    results['python'] = sys.version_info >= (3, 6)
    results['openssl'] = shutil.which('openssl') is not None
    return results

# ── Génération token ──────────────────────────────────────────
def generate_token():
    return secrets.token_urlsafe(24)

# ── Installation ──────────────────────────────────────────────
def emit(msg, level='info'):
    INSTALL_EVENTS.put({'msg': msg, 'level': level})

def run_cmd(cmd, shell=True):
    proc = subprocess.Popen(cmd, shell=shell, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        emit(line.rstrip())
    proc.wait()
    return proc.returncode

def _midclt(args, timeout=60):
    """Appelle le middleware TrueNAS. Retourne (code, stdout, stderr)."""
    try:
        p = subprocess.run(['midclt'] + args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or '').strip(), (p.stderr or '').strip()
    except Exception as e:
        return 1, '', str(e)


def configure_truenas(ssh_user):
    """Automatise les prérequis TrueNAS via midclt : SSH + auth mot de passe,
    et sudo NOPASSWD pour l'utilisateur. Non bloquant (avertit si échec)."""
    if not shutil.which('midclt'):
        emit('⚠ midclt introuvable — configure SSH/sudo manuellement.', 'warn')
        return
    emit('▸ Configuration TrueNAS (SSH + sudo) via middleware...', 'step')

    # 1. SSH : autoriser l'authentification par mot de passe
    rc, out, err = _midclt(['call', 'ssh.update', '{"passwordauth": true}'])
    emit('✓ SSH : auth par mot de passe activée' if rc == 0
         else f'⚠ ssh.update a échoué : {err or out}', 'ok' if rc == 0 else 'warn')

    # 2. SSH : activer le service au boot + démarrer
    _midclt(['call', 'service.update', 'ssh', '{"enable": true}'])
    rc, out, err = _midclt(['call', 'service.start', 'ssh'])
    emit('✓ Service SSH démarré' if rc == 0
         else f'⚠ Démarrage SSH : {err or out}', 'ok' if rc == 0 else 'warn')

    # 3. sudo NOPASSWD pour l'utilisateur SSH
    rc, out, err = _midclt(['call', 'user.query', f'[["username","=","{ssh_user}"]]'])
    uid = None
    if rc == 0 and out:
        try:
            data = json.loads(out)
            if data:
                uid = data[0].get('id')
        except Exception:
            pass
    if uid is not None:
        payload = '{"sudo_commands": ["ALL"], "sudo_commands_nopasswd": ["ALL"]}'
        rc, out, err = _midclt(['call', 'user.update', str(uid), payload])
        emit(f'✓ sudo sans mot de passe activé pour {ssh_user}' if rc == 0
             else f'⚠ user.update a échoué : {err or out}', 'ok' if rc == 0 else 'warn')
    else:
        emit(f'⚠ Utilisateur {ssh_user} introuvable — active le sudo NOPASSWD manuellement.', 'warn')


def run_install(config):
    global INSTALL_RUNNING, INSTALL_DONE
    INSTALL_RUNNING = True
    INSTALL_DONE = False

    try:
        install_dir  = config['install_dir']
        vm_dir       = config['vm_dir']
        iso_dir      = config['iso_dir']
        port         = config['port']
        truenas_ip   = config['truenas_ip']
        truenas_host = config['truenas_host']
        ssh_user     = config['ssh_user']
        ssh_pass     = config['ssh_pass']
        token        = config['token'] or generate_token()
        db_pass      = config.get('db_pass') or generate_token()

        script_dir = os.path.dirname(os.path.abspath(__file__))

        # ── 1. Répertoires ────────────────────────────────────
        emit('▸ Création des répertoires...', 'step')
        os.makedirs(install_dir, exist_ok=True)
        os.makedirs(vm_dir, exist_ok=True)
        os.chmod(vm_dir, 0o777)
        for sub in ('websites/conf.d', 'websites/php/8.3/ini', 'websites/php/8.2/ini',
                    'websites/php/8.1/ini', 'websites/php/7.4/ini', 'mariadb'):
            os.makedirs(os.path.join(install_dir, sub), exist_ok=True)
        emit(f'✓ {install_dir}', 'ok')
        emit(f'✓ {vm_dir}', 'ok')

        # ── 1b. Prérequis TrueNAS automatisés (SSH + sudo) ────
        configure_truenas(ssh_user)

        # ── 2. Sauvegarde config ──────────────────────────────
        emit('▸ Sauvegarde de la configuration...', 'step')
        os.makedirs('/etc/truenas-desktop', exist_ok=True)
        config_content = f"""INSTALL_DIR={install_dir}
VM_DIR={vm_dir}
ISO_DIR={iso_dir}
PORT={port}
TRUENAS_IP={truenas_ip}
TRUENAS_HOST={truenas_host}
SSH_USER={ssh_user}
SSH_PASS={ssh_pass}
FILEOPS_TOKEN={token}
GITHUB_RAW={(config.get('github_raw') or GITHUB_RAW_DEFAULT).rstrip('/')}
"""
        with open('/etc/truenas-desktop/config.env', 'w') as f:
            f.write(config_content)
        os.chmod('/etc/truenas-desktop/config.env', 0o600)
        emit('✓ /etc/truenas-desktop/config.env', 'ok')

        # ── 3. Récupération des fichiers (GitHub, sinon copie locale) ──
        emit('▸ Récupération des fichiers applicatifs...', 'step')
        github_raw = (config.get('github_raw') or GITHUB_RAW_DEFAULT).rstrip('/')
        import urllib.request as _u
        for fname in ['fileops.py', 'truenas-desktop.html', 'vnc-viewer.html']:
            dst = os.path.join(install_dir, fname)
            src = os.path.join(script_dir, fname)
            got = False
            if os.path.exists(src) and src != dst:
                try:
                    shutil.copy2(src, dst); got = True
                    emit(f'✓ {fname} (copié)', 'ok')
                except Exception:
                    pass
            if not got:
                try:
                    _u.urlretrieve(f'{github_raw}/{fname}', dst)
                    emit(f'✓ {fname} (téléchargé)', 'ok')
                except Exception as e:
                    emit(f'✗ Échec récupération {fname} : {e}', 'error')
                    raise RuntimeError(f'Impossible de récupérer {fname} depuis {github_raw}')

        # ── 4. Injection token dans le HTML ───────────────────
        html_path = os.path.join(install_dir, 'truenas-desktop.html')
        if os.path.exists(html_path):
            with open(html_path, 'r') as f:
                html = f.read()
            # Remplace le token quel que soit sa valeur actuelle (placeholder ou ancien token)
            html, n = re.subn(
                r"(FILEOPS_TOKEN_DEFAULT\s*=\s*')[^']*(')",
                lambda m: m.group(1) + token + m.group(2),
                html
            )
            if n:
                with open(html_path, 'w') as f:
                    f.write(html)
                emit('✓ Token injecté dans truenas-desktop.html', 'ok')
            else:
                emit('⚠ Token non trouvé dans le HTML (variable FILEOPS_TOKEN_DEFAULT absente)', 'warn')

        # ── 5. Génération docker-compose.yml ──────────────────
        emit('▸ Génération de docker-compose.yml...', 'step')
        php_reload = (
            "apk add --no-cache curl >/dev/null 2>&1 || true; "
            "[ -x /usr/local/bin/install-php-extensions ] || { curl -sSLf https://github.com/mlocati/docker-php-extension-installer/releases/latest/download/install-php-extensions -o /usr/local/bin/install-php-extensions && chmod +x /usr/local/bin/install-php-extensions; }; "
            "[ -s /conf/extensions.txt ] && install-php-extensions $(cat /conf/extensions.txt) || true; "
            "( last=''; lastext=''; while true; do e=$(cat /conf/.extreload 2>/dev/null); if [ \"$e\" != \"$lastext\" ]; then lastext=\"$e\"; { [ -s /conf/extensions.txt ] && install-php-extensions $(cat /conf/extensions.txt) >/dev/null 2>&1; } || true; kill -USR2 1 2>/dev/null || true; fi; v=$(cat /conf/.reload 2>/dev/null); if [ \"$v\" != \"$last\" ]; then last=\"$v\"; kill -USR2 1 2>/dev/null || true; fi; sleep 3; done ) & exec php-fpm"
        )
        web_reload = "last=''; ( while true; do v=$(cat /etc/nginx/conf.d/.reload 2>/dev/null); if [ \"$v\" != \"$last\" ]; then last=\"$v\"; nginx -t && nginx -s reload; fi; sleep 3; done ) & exec nginx -g 'daemon off;'"

        def php_service(ver):
            return f"""  php{ver.replace('.','')}:
    image: php:{ver}-fpm-alpine
    container_name: truenas-php{ver.replace('.','')}
    restart: unless-stopped
    environment:
      PHP_INI_SCAN_DIR: ":/conf/ini"
    volumes:
      - /mnt:/mnt
      - {install_dir}/websites/php/{ver}:/conf
    command: {json.dumps(["sh","-c",php_reload])}
    depends_on:
      - fileops
"""

        compose = f"""services:
  truenas-desktop:
    image: nginx:alpine
    container_name: truenas-desktop
    restart: unless-stopped
    user: root
    ports:
      - "{port}:80"
    volumes:
      - {install_dir}/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - {install_dir}/truenas-desktop.html:/usr/share/nginx/html/index.html:ro
      - {install_dir}/vnc-viewer.html:/usr/share/nginx/html/vnc-viewer.html:ro
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
      FILEOPS_TOKEN: "{token}"
      FILEOPS_PORT: "8765"
      FILEOPS_WS_PORT: "8766"
      HOST_BOOTSTRAP: "1"
      APP_DIR: "{install_dir}"
      GITHUB_RAW: "{github_raw}"
      TRUENAS_SSH_HOST: "{truenas_ip}"
      TRUENAS_SSH_USER: "{ssh_user}"
      TRUENAS_SSH_PASS: "{ssh_pass}"
      TRUENAS_SSH_PORT: "22"
      VM_DIR: "{vm_dir}"
      ISO_DIR: "{iso_dir}"
      WEB_CONF_DIR: "{install_dir}/websites/conf.d"
      WEB_PHP_VERSIONS: '{{"8.3":"truenas-php83:9000","8.2":"truenas-php82:9000","8.1":"truenas-php81:9000","7.4":"truenas-php74:9000"}}'
      WEB_PHP_DEFAULT: "8.3"
      WEB_PHP_DIR: "{install_dir}/websites/php"
      WEB_PROXY_PORT: "8080"
      DB_HOST: "mariadb"
      DB_PORT: "3306"
      DB_ROOT_PASSWORD: "{db_pass}"
    volumes:
      - /mnt:/mnt
      - {install_dir}/fileops.py:/app/fileops.py:ro
    command: sh -c "apk add --no-cache qemu-img ca-certificates && {{ apk add --no-cache p7zip libarchive-tools 2>/dev/null || true; apk add --no-cache unrar 2>/dev/null || true; }} && pip install websockets paramiko pymysql --break-system-packages -q && python /app/fileops.py"
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
      - {install_dir}/websites/conf.d:/etc/nginx/conf.d
    command: {json.dumps(["sh","-c",web_reload])}
    depends_on:
      - php83
      - php82
      - php81
      - php74

{php_service('8.3')}
{php_service('8.2')}
{php_service('8.1')}
{php_service('7.4')}
  mariadb:
    image: mariadb:11
    container_name: truenas-mariadb
    restart: unless-stopped
    environment:
      MARIADB_ROOT_PASSWORD: "{db_pass}"
      MARIADB_AUTO_UPGRADE: "1"
    expose:
      - "3306"
    volumes:
      - {install_dir}/mariadb:/var/lib/mysql
"""
        with open(os.path.join(install_dir, 'docker-compose.yml'), 'w') as f:
            f.write(compose)
        # Sauvegarde du mot de passe DB dans la config
        try:
            with open('/etc/truenas-desktop/config.env', 'a') as f:
                f.write(f'DB_ROOT_PASSWORD={db_pass}\n')
        except Exception:
            pass
        emit('✓ docker-compose.yml (stack complète)', 'ok')

        # ── 6. Génération nginx.conf ──────────────────────────
        emit('▸ Génération de nginx.conf...', 'step')
        nginx = f"""server {{
    listen 80;
    server_name _;
    client_max_body_size 20g;
    client_body_timeout 3600s;
    root /usr/share/nginx/html;
    index index.html;

    location / {{
        try_files $uri /index.html;
    }}

    location = /api/current {{
        proxy_pass            https://{truenas_ip}/api/current;
        proxy_http_version    1.1;
        proxy_set_header      Upgrade           $http_upgrade;
        proxy_set_header      Connection        "upgrade";
        proxy_set_header      Host              {truenas_host};
        proxy_ssl_verify      off;
        proxy_ssl_server_name off;
        proxy_read_timeout    3600s;
        proxy_send_timeout    3600s;
    }}

    location /s/ {{
        proxy_pass            http://fileops:8765/s/;
        proxy_http_version    1.1;
        proxy_set_header      Host $host;
        proxy_buffering       off;
        proxy_max_temp_file_size 0;
        proxy_read_timeout    3600s;
        proxy_send_timeout    3600s;
        proxy_connect_timeout 30s;
    }}

    location /api/ {{
        proxy_pass          https://{truenas_ip}/api/;
        proxy_http_version  1.1;
        proxy_ssl_verify    off;
        proxy_ssl_server_name off;
        proxy_set_header    Host              {truenas_host};
        proxy_set_header    Authorization     $http_authorization;
        proxy_pass_header   Authorization;
        proxy_set_header    Cookie            $http_cookie;
        proxy_pass_header   Set-Cookie;
        proxy_connect_timeout 10s;
        proxy_read_timeout    30s;
    }}

    location /_download/ {{
        proxy_pass            https://{truenas_ip}/_download/;
        proxy_http_version    1.1;
        proxy_ssl_verify      off;
        proxy_ssl_server_name off;
        proxy_set_header      Host {truenas_host};
        proxy_read_timeout    120s;
    }}

    location /fileops/ {{
        proxy_pass         http://fileops:8765/;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_connect_timeout 30s;
    }}

    location /truenas-shell {{
        proxy_pass         http://fileops:8766;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       $host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }}

    location /vnc-proxy {{
        proxy_pass         http://fileops:8766;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       $host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }}

    location = /vnc-viewer {{
        alias /usr/share/nginx/html/vnc-viewer.html;
        default_type text/html;
        add_header Cache-Control "no-cache";
    }}

    location /websocket {{
        proxy_pass            https://{truenas_ip}/websocket;
        proxy_http_version    1.1;
        proxy_set_header      Upgrade           $http_upgrade;
        proxy_set_header      Connection        "upgrade";
        proxy_set_header      Host              {truenas_host};
        proxy_set_header      Authorization     $http_authorization;
        proxy_pass_header     Authorization;
        proxy_ssl_verify      off;
        proxy_ssl_server_name off;
        proxy_read_timeout    3600s;
        proxy_send_timeout    3600s;
    }}
}}"""
        with open(os.path.join(install_dir, 'nginx.conf'), 'w') as f:
            f.write(nginx)
        emit('✓ nginx.conf', 'ok')

        # ── 7. Configuration host TrueNAS ─────────────────────
        host_script = os.path.join(install_dir, 'setup-truenas-host.sh')
        if os.path.exists(host_script):
            emit('▸ Configuration host TrueNAS (libvirtd, polkit)...', 'step')
            rc = run_cmd(f'bash {host_script}')
            if rc == 0:
                emit('✓ Host configuré', 'ok')
            else:
                emit('⚠ Erreur configuration host (non bloquant)', 'warn')

        # ── 8. Service systemd ────────────────────────────────
        emit('▸ Configuration service systemd...', 'step')
        service = f"""[Unit]
Description=TrueNAS Desktop App
After=zfs-mount.service docker.service network-online.target middlewared.service
Wants=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory={install_dir}
ExecStartPre=/bin/mkdir -p /run/truenas_libvirt
ExecStartPre=-/bin/systemctl start libvirtd
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
"""
        with open('/etc/systemd/system/truenas-desktop.service', 'w') as f:
            f.write(service)
        with open('/etc/tmpfiles.d/truenas-libvirt.conf', 'w') as f:
            f.write('d /run/truenas_libvirt 0755 root root -\n')
        run_cmd('systemctl daemon-reload && systemctl enable truenas-desktop 2>/dev/null')
        emit('✓ Service systemd activé', 'ok')

        # ── 9. Démarrage Docker ───────────────────────────────
        emit('▸ Démarrage de la stack Docker...', 'step')
        rc = run_cmd(f'cd {install_dir} && docker compose up -d --force-recreate')
        if rc == 0:
            emit('✓ Stack Docker démarrée', 'ok')
        else:
            emit('✗ Erreur démarrage Docker', 'error')
            INSTALL_RUNNING = False
            return

        emit(f'__DONE__{truenas_ip}:{port}', 'done')

    except Exception as e:
        emit(f'✗ Erreur : {e}', 'error')

    finally:
        INSTALL_RUNNING = False
        INSTALL_DONE = True


# ── HTML du wizard ────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TrueNAS Desktop — Installation</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0f1117; --surface: #1a1d27; --surface2: #22263a;
    --border: #2d3148; --accent: #5b7fff; --success: #4caf87;
    --warn: #f0a500; --error: #e05555; --text: #e8eaf0; --dim: #8892b0;
  }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif;
         min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
          width: 100%; max-width: 600px; overflow: hidden; box-shadow: 0 24px 64px rgba(0,0,0,0.5); }
  .header { background: linear-gradient(135deg, #1e2340 0%, #2a3060 100%);
            padding: 32px; text-align: center; border-bottom: 1px solid var(--border); }
  .logo { font-size: 40px; margin-bottom: 12px; }
  .header h1 { font-size: 22px; font-weight: 700; color: #fff; }
  .header p  { color: var(--dim); font-size: 13px; margin-top: 6px; }
  .steps { display: flex; padding: 24px 32px 20px; gap: 0; border-bottom: 1px solid var(--border); }
  .step  { flex: 1; text-align: center; font-size: 11px; color: var(--dim); position: relative;
            display: flex; flex-direction: column; align-items: center; gap: 10px; }
  .step::after { content: ''; position: absolute; bottom: 11px; left: calc(50% + 14px); right: calc(-50% + 14px);
                  height: 1px; background: var(--border); z-index: 0; }
  .step:last-child::after { display: none; }
  .step-label { font-size: 11px; letter-spacing: 0.2px; }
  .step-dot { width: 24px; height: 24px; border-radius: 50%; background: var(--surface2);
               border: 2px solid var(--border); display: inline-flex; align-items: center;
               justify-content: center; font-size: 10px; font-weight: 700;
               position: relative; z-index: 1; flex-shrink: 0; }
  .step.active .step-dot  { background: var(--accent); border-color: var(--accent); color: #fff; }
  .step.done   .step-dot  { background: var(--success); border-color: var(--success); color: #fff; }
  .step.active { color: var(--text); }
  .body { padding: 32px; }

  /* Prérequis */
  .prereq { display: flex; align-items: center; gap: 12px; padding: 10px 0;
             border-bottom: 1px solid var(--border); }
  .prereq:last-child { border-bottom: none; }
  .prereq-icon { font-size: 18px; width: 24px; text-align: center; }
  .prereq-label { flex: 1; font-size: 14px; }
  .badge { font-size: 11px; padding: 3px 10px; border-radius: 20px; font-weight: 600; }
  .badge.ok   { background: rgba(76,175,135,.15); color: var(--success); }
  .badge.fail { background: rgba(224,85,85,.15);  color: var(--error); }
  .badge.warn { background: rgba(240,165,0,.15);  color: var(--warn); }

  /* Formulaire */
  .section-title { font-size: 11px; font-weight: 700; color: var(--dim); text-transform: uppercase;
                    letter-spacing: 1px; margin: 20px 0 12px; }
  .section-title:first-child { margin-top: 0; }
  .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .form-group { margin-bottom: 14px; }
  .form-group label { display: block; font-size: 12px; color: var(--dim); margin-bottom: 6px; }
  .form-group input { width: 100%; background: var(--surface2); border: 1px solid var(--border);
                       border-radius: 8px; padding: 10px 12px; color: var(--text); font-size: 13px;
                       transition: border-color .2s; outline: none; }
  .form-group input:focus { border-color: var(--accent); }
  .hint { font-size: 11px; color: var(--dim); margin-top: 4px; }

  /* Log */
  .log { background: #0a0c12; border: 1px solid var(--border); border-radius: 10px;
          padding: 16px; font-family: 'Cascadia Code', 'Fira Code', monospace;
          font-size: 12px; height: 320px; overflow-y: auto; line-height: 1.7; }
  .log::-webkit-scrollbar { display: none; }
  .log { scrollbar-width: none; }
  .log .step  { color: #7b9fff; }
  .log .ok    { color: var(--success); }
  .log .warn  { color: var(--warn); }
  .log .error { color: var(--error); }
  .log .info  { color: #b0bec5; }

  /* Succès */
  .success-box { text-align: center; padding: 20px 0; }
  .success-box .big-icon { font-size: 56px; margin-bottom: 16px; }
  .success-box h2 { font-size: 20px; margin-bottom: 8px; }
  .success-box p  { color: var(--dim); font-size: 14px; }
  .open-btn { display: inline-block; margin-top: 20px; background: var(--accent);
               color: #fff; padding: 12px 32px; border-radius: 10px; text-decoration: none;
               font-weight: 600; font-size: 15px; transition: opacity .2s; }
  .open-btn:hover { opacity: .85; }

  /* Boutons */
  .actions { display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px; }
  .btn { padding: 11px 28px; border-radius: 10px; border: none; cursor: pointer;
          font-size: 14px; font-weight: 600; transition: opacity .2s; }
  .btn:hover { opacity: .85; }
  .btn-primary  { background: var(--accent); color: #fff; }
  .btn-secondary{ background: var(--surface2); color: var(--dim); border: 1px solid var(--border); }
  .btn:disabled { opacity: .4; cursor: not-allowed; }

  .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid rgba(255,255,255,.3);
              border-top-color: #fff; border-radius: 50%; animation: spin .7s linear infinite;
              margin-right: 8px; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }

  [hidden] { display: none !important; }

  /* Input avec bouton picker */
  .input-browse { display: flex; gap: 6px; }
  .input-browse input { flex: 1; }
  .btn-browse { background: var(--surface2); border: 1px solid var(--border); color: var(--dim);
                 border-radius: 8px; padding: 0 12px; cursor: pointer; font-size: 16px;
                 transition: border-color .2s; flex-shrink: 0; }
  .btn-browse:hover { border-color: var(--accent); color: var(--text); }

  /* Modale navigateur */
  .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.7);
                    display: flex; align-items: center; justify-content: center; z-index: 100; }
  .modal { background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
            width: 480px; max-width: 95vw; max-height: 80vh; display: flex; flex-direction: column;
            box-shadow: 0 24px 64px rgba(0,0,0,.6); }
  .modal-header { padding: 16px 20px; border-bottom: 1px solid var(--border);
                   display: flex; align-items: center; gap: 10px; }
  .modal-header h3 { flex: 1; font-size: 14px; font-weight: 600; }
  .modal-close { background: none; border: none; color: var(--dim); cursor: pointer;
                  font-size: 18px; padding: 2px 6px; border-radius: 4px; }
  .modal-close:hover { color: var(--text); }
  .modal-path { padding: 10px 20px; background: var(--surface2); font-size: 12px;
                 color: var(--dim); font-family: monospace; border-bottom: 1px solid var(--border); }
  .modal-list { flex: 1; overflow-y: auto; padding: 8px; scrollbar-width: none; }
  .modal-list::-webkit-scrollbar { display: none; }
  .modal-entry { display: flex; align-items: center; gap: 10px; padding: 9px 12px;
                  border-radius: 8px; cursor: pointer; font-size: 13px; }
  .modal-entry:hover { background: var(--surface2); }
  .modal-entry .icon { font-size: 16px; width: 20px; text-align: center; }
  .modal-footer { padding: 14px 20px; border-top: 1px solid var(--border);
                   display: flex; justify-content: flex-end; gap: 10px; }
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <div class="logo">🖥️</div>
    <h1>TrueNAS Desktop</h1>
    <p>Assistant d'installation</p>
  </div>

  <!-- Indicateur étapes -->
  <div class="steps">
    <div class="step active" id="s1"><span class="step-label">Prérequis</span><div class="step-dot" id="d1">1</div></div>
    <div class="step"        id="s2"><span class="step-label">Configuration</span><div class="step-dot" id="d2">2</div></div>
    <div class="step"        id="s3"><span class="step-label">Installation</span><div class="step-dot" id="d3">3</div></div>
    <div class="step"        id="s4"><span class="step-label">Terminé</span><div class="step-dot" id="d4">4</div></div>
  </div>

  <div class="body">

    <!-- Étape 1 : Prérequis -->
    <div id="page1">
      <div id="prereq-list">
        <div style="color:var(--dim);font-size:13px;">Vérification en cours...</div>
      </div>
      <div class="actions">
        <button class="btn btn-primary" id="btn-next1" disabled onclick="goTo(2)">Continuer →</button>
      </div>
    </div>

    <!-- Étape 2 : Configuration -->
    <div id="page2" hidden>
      <div class="section-title">📁 Chemins</div>
      <div class="form-group">
        <label>Répertoire d'installation</label>
        <div class="input-browse">
          <input id="install_dir" value="/mnt/Truenas_Stockage/apps/desktop" />
          <button class="btn-browse" onclick="openBrowser('install_dir')" title="Parcourir">📁</button>
        </div>
        <div id="pool-hint" style="font-size:12px;color:#8a9bbf;margin-top:4px;"></div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Dossier VMs</label>
          <div class="input-browse">
            <input id="vm_dir" value="/mnt/Truenas_Stockage/vms" />
            <button class="btn-browse" onclick="openBrowser('vm_dir')" title="Parcourir">📁</button>
          </div>
        </div>
        <div class="form-group">
          <label>Dossier ISOs (racine)</label>
          <div class="input-browse">
            <input id="iso_dir" value="/mnt/Truenas_Stockage" />
            <button class="btn-browse" onclick="openBrowser('iso_dir')" title="Parcourir">📁</button>
          </div>
        </div>
      </div>

      <div class="section-title">🌐 Réseau</div>
      <div class="form-row">
        <div class="form-group">
          <label>IP du TrueNAS</label>
          <input id="truenas_ip" placeholder="192.168.1.x" />
        </div>
        <div class="form-group">
          <label>Port du bureau</label>
          <input id="port" value="8099" />
        </div>
      </div>
      <div class="form-group">
        <label>Hostname / FQDN <span style="color:var(--dim)">(optionnel)</span></label>
        <input id="truenas_host" placeholder="même que l'IP si vide" />
        <div class="hint">Utilisé dans les en-têtes nginx. Laissez vide pour utiliser l'IP.</div>
      </div>

      <div class="section-title">🔐 Accès SSH</div>
      <div class="form-row">
        <div class="form-group">
          <label>Utilisateur SSH</label>
          <input id="ssh_user" value="truenas_admin" />
        </div>
        <div class="form-group">
          <label>Mot de passe SSH</label>
          <input id="ssh_pass" type="password" placeholder="••••••••" />
        </div>
      </div>

      <div class="section-title">🔑 Sécurité</div>
      <div class="form-group">
        <label>Token sidecar</label>
        <input id="token" placeholder="Laissez vide pour générer automatiquement" />
        <div class="hint">Clé secrète entre le navigateur et le service fileops.</div>
      </div>

      <div class="actions">
        <button class="btn btn-secondary" onclick="goTo(1)">← Retour</button>
        <button class="btn btn-primary"   onclick="startInstall()">Installer →</button>
      </div>
    </div>

    <!-- Étape 3 : Installation -->
    <div id="page3" hidden>
      <div class="log" id="log"></div>
      <div class="actions" style="margin-top:16px;">
        <button class="btn btn-secondary" id="btn-cancel" onclick="window.close()">Fermer</button>
      </div>
    </div>

    <!-- Étape 4 : Succès -->
    <div id="page4" hidden>
      <div class="success-box">
        <div class="big-icon">🎉</div>
        <h2>Installation réussie !</h2>
        <p>TrueNAS Desktop est prêt.</p>
        <a id="open-link" href="#" class="open-btn" target="_blank">Ouvrir le bureau →</a>
      </div>
    </div>

  </div>
</div>

<!-- Modale navigateur de dossiers -->
<div class="modal-overlay" id="browser-modal" hidden>
  <div class="modal">
    <div class="modal-header">
      <h3>📁 Choisir un dossier</h3>
      <button class="modal-close" onclick="closeBrowser()">✕</button>
    </div>
    <div class="modal-path" id="browser-path">/mnt</div>
    <div class="modal-list" id="browser-list"></div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeBrowser()">Annuler</button>
      <button class="btn btn-primary"   onclick="selectCurrent()">Choisir ce dossier</button>
    </div>
  </div>
</div>

<script>
let currentPage = 1;

function goTo(n) {
  document.getElementById('page' + currentPage).hidden = true;
  document.getElementById('s'    + currentPage).classList.remove('active');
  if (n > currentPage) document.getElementById('s' + currentPage).classList.add('done');
  currentPage = n;
  document.getElementById('page' + n).hidden = false;
  document.getElementById('s'    + n).classList.add('active');
}

// ── Navigateur de dossiers ────────────────────────────────────
let _browserTarget = null;
let _browserPath   = '/mnt';

function openBrowser(inputId) {
  _browserTarget = inputId;
  const cur = document.getElementById(inputId).value.trim();
  browseTo(cur || '/mnt');
  document.getElementById('browser-modal').hidden = false;
}

function closeBrowser() {
  document.getElementById('browser-modal').hidden = true;
}

function selectCurrent() {
  if (_browserTarget) document.getElementById(_browserTarget).value = _browserPath;
  closeBrowser();
}

function browseTo(path) {
  _browserPath = path;
  document.getElementById('browser-path').textContent = path;
  const list = document.getElementById('browser-list');
  list.innerHTML = '<div style="padding:20px;color:var(--dim);text-align:center">Chargement...</div>';
  fetch('/browse?path=' + encodeURIComponent(path))
    .then(r => r.json())
    .then(data => {
      _browserPath = data.path;
      document.getElementById('browser-path').textContent = data.path;
      if (!data.entries.length) {
        list.innerHTML = '<div style="padding:20px;color:var(--dim);text-align:center">Dossier vide</div>';
        return;
      }
      list.innerHTML = '';
      data.entries.forEach(e => {
        const div = document.createElement('div');
        div.className = 'modal-entry';
        div.innerHTML = `<span class="icon">${e.type === 'parent' ? '↩' : '📁'}</span><span>${e.name}</span>`;
        div.onclick = () => browseTo(e.path);
        list.appendChild(div);
      });
    });
}

// ── Étape 1 : prérequis ───────────────────────────────────────
fetch('/check').then(r => r.json()).then(data => {
  const icons = { root: '👤', docker: '🐳', python: '🐍', openssl: '🔑' };
  const labels = { root: 'Exécuté en root', docker: 'Docker disponible',
                   python: 'Python 3.6+', openssl: 'OpenSSL (génération token)' };
  let allOk = true;
  let html = '';
  for (const [k, ok] of Object.entries(data)) {
    const critical = k !== 'openssl';
    if (!ok && critical) allOk = false;
    const badge = ok ? '<span class="badge ok">✓ OK</span>'
                     : critical ? '<span class="badge fail">✗ Manquant</span>'
                                : '<span class="badge warn">⚠ Optionnel</span>';
    html += `<div class="prereq">
      <span class="prereq-icon">${icons[k]}</span>
      <span class="prereq-label">${labels[k]}</span>
      ${badge}
    </div>`;
  }
  document.getElementById('prereq-list').innerHTML = html;
  if (allOk) document.getElementById('btn-next1').disabled = false;

  // Auto-remplir l'IP
  fetch('/ip').then(r => r.text()).then(ip => {
    document.getElementById('truenas_ip').value = ip.trim();
  });

  // Auto-détecter le pool et pré-remplir les chemins
  fetch('/pools').then(r => r.json()).then(pools => {
    if (pools && pools.length) {
      const p = '/mnt/' + pools[0];
      document.getElementById('install_dir').value = p + '/apps/desktop';
      document.getElementById('vm_dir').value = p + '/vms';
      document.getElementById('iso_dir').value = p;
      if (pools.length > 1) {
        const hint = document.getElementById('pool-hint');
        if (hint) hint.textContent = 'Pools détectés : ' + pools.join(', ') + ' — utilise 📁 pour en choisir un autre.';
      }
    }
  }).catch(() => {});
});

// ── Étape 3 : installation ─────────────────────────────────────
function startInstall() {
  const ip   = document.getElementById('truenas_ip').value.trim();
  const pass = document.getElementById('ssh_pass').value.trim();
  if (!ip)   { alert('IP TrueNAS obligatoire'); return; }
  if (!pass) { alert('Mot de passe SSH obligatoire'); return; }

  const config = {
    install_dir:  document.getElementById('install_dir').value.trim(),
    vm_dir:       document.getElementById('vm_dir').value.trim(),
    iso_dir:      document.getElementById('iso_dir').value.trim(),
    port:         document.getElementById('port').value.trim(),
    truenas_ip:   ip,
    truenas_host: document.getElementById('truenas_host').value.trim() || ip,
    ssh_user:     document.getElementById('ssh_user').value.trim(),
    ssh_pass:     pass,
    token:        document.getElementById('token').value.trim(),
  };

  goTo(3);

  fetch('/install', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config)
  });

  // SSE pour la progression
  const log = document.getElementById('log');
  const es  = new EventSource('/events');
  es.onmessage = function(e) {
    const data = JSON.parse(e.data);
    if (data.msg.startsWith('__DONE__')) {
      es.close();
      const addr = data.msg.replace('__DONE__', '');
      document.getElementById('open-link').href = 'http://' + addr;
      goTo(4);
      return;
    }
    const cls = data.level === 'step' ? 'step' : data.level;
    const line = document.createElement('div');
    line.className = cls;
    line.textContent = data.msg;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  };
  es.onerror = function() { es.close(); };
}
</script>
</body>
</html>"""


# ── Serveur HTTP ──────────────────────────────────────────────
class WizardHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # Silencieux

    def do_GET(self):
        if self.path in ('/', '/setup'):
            self._html()
        elif self.path == '/check':
            self._json(check_prerequisites())
        elif self.path == '/ip':
            self._text(get_local_ip())
        elif self.path == '/pools':
            self._json(list_pools())
        elif self.path == '/events':
            self._sse()
        elif self.path.startswith('/browse'):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            path   = params.get('path', ['/mnt'])[0]
            self._browse(path)
        else:
            self.send_error(404)

    def _browse(self, path):
        try:
            path = os.path.realpath(path)
            entries = []
            if path != '/':
                entries.append({'name': '..', 'path': str(os.path.dirname(path)), 'type': 'parent'})
            for name in sorted(os.listdir(path)):
                full = os.path.join(path, name)
                if os.path.isdir(full) and not name.startswith('.'):
                    entries.append({'name': name, 'path': full, 'type': 'dir'})
            self._json({'path': path, 'entries': entries})
        except Exception as e:
            self._json({'path': path, 'entries': [], 'error': str(e)})

    def do_POST(self):
        if self.path == '/install':
            length = int(self.headers.get('Content-Length', 0))
            body   = self.rfile.read(length)
            config = json.loads(body)
            if not INSTALL_RUNNING:
                t = threading.Thread(target=run_install, args=(config,), daemon=True)
                t.start()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')
        else:
            self.send_error(404)

    def _html(self):
        data = HTML.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

    def _text(self, txt):
        data = txt.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

    def _sse(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()
        try:
            while True:
                try:
                    item = INSTALL_EVENTS.get(timeout=30)
                    msg  = json.dumps(item)
                    self.wfile.write(f'data: {msg}\n\n'.encode())
                    self.wfile.flush()
                    if item.get('level') == 'done':
                        break
                except queue.Empty:
                    # Keepalive
                    self.wfile.write(b': keepalive\n\n')
                    self.wfile.flush()
        except Exception:
            pass


# ── Main ──────────────────────────────────────────────────────
if __name__ == '__main__':
    ip = get_local_ip()
    server = http.server.HTTPServer(('0.0.0.0', PORT), WizardHandler)
    print()
    print('╔══════════════════════════════════════════╗')
    print('║      TrueNAS Desktop  —  Wizard          ║')
    print('╚══════════════════════════════════════════╝')
    print()
    print(f'  Ouvrez dans votre navigateur :')
    print(f'  ➜  http://{ip}:{PORT}/setup')
    print()
    print('  Ctrl+C pour arrêter le wizard.')
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nWizard arrêté.')
