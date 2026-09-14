# 2FA avec Authelia — **derrière Nginx Proxy Manager (NPM)**

> ⚠️ **Méthode à jour.** L'ancienne approche « Authelia intégré au nginx du bureau
> en HTTP » ne fonctionne pas : **Authelia 4.39 exige des URLs en HTTPS**. Comme NPM
> fournit déjà du HTTPS (Let's Encrypt), on met **Authelia derrière NPM**. La case
> « 2FA » de l'assistant (`setup-wizard.py`) génère l'ancienne approche et **ne doit
> pas être utilisée** ; fais une install **sans** 2FA, puis suis ce guide.

Topologie : navigateur → **NPM (HTTPS)** → { portail Authelia | bureau }. NPM
demande le login + code TOTP (via Authelia) avant de laisser passer vers le bureau.

- Bureau : `https://desktop.goassistance.fr`  (NPM → `NAS:8099`)
- Portail : `https://auth.goassistance.fr`     (NPM → `NAS:9091`)

Remplace `goassistance.fr`, `192.168.0.200` (NAS) et `192.168.0.254` (NPM) par tes valeurs.

---

## 1. Fichiers Authelia sur le NAS

```bash
cd /mnt/Truenas_Stockage/apps/desktop
mkdir -p authelia
```

**Secrets** (`authelia/secrets.env`) — 3 valeurs aléatoires :
```bash
cd authelia
printf 'AUTHELIA_SESSION_SECRET=%s\n'                              "$(openssl rand -hex 32)"  > secrets.env
printf 'AUTHELIA_STORAGE_ENCRYPTION_KEY=%s\n'                      "$(openssl rand -hex 32)" >> secrets.env
printf 'AUTHELIA_IDENTITY_VALIDATION_RESET_PASSWORD_JWT_SECRET=%s\n' "$(openssl rand -hex 32)" >> secrets.env
cd ..
```

**Utilisateur** (`authelia/users_database.yml`) — génère le hash puis colle-le :
```bash
docker run --rm authelia/authelia:4.39 authelia crypto hash generate argon2 --password 'TON_MOT_DE_PASSE'
```
```yaml
# authelia/users_database.yml
users:
  admin:
    disabled: false
    displayname: 'Admin'
    password: '$argon2id$v=19$...'   # ← colle le Digest ci-dessus
    email: 'admin@goassistance.fr'
    groups: ['admins']
```

**Config** (`authelia/configuration.yml`) — **URLs en HTTPS** :
```yaml
theme: 'dark'
log: { level: 'info' }
server: { address: 'tcp://:9091' }
totp: { issuer: 'TrueNAS Desktop', period: 30 }
authentication_backend:
  file: { path: '/config/users_database.yml' }
access_control:
  default_policy: 'deny'
  rules:
    - domain: 'desktop.goassistance.fr'
      policy: 'two_factor'
session:
  cookies:
    - name: 'authelia_session'
      domain: 'goassistance.fr'
      authelia_url: 'https://auth.goassistance.fr'
      default_redirection_url: 'https://desktop.goassistance.fr'
      expiration: '1h'
      inactivity: '15m'
storage:
  local: { path: '/config/db.sqlite3' }
notifier:
  filesystem: { filename: '/config/notification.txt' }
```

## 2. Démarrer Authelia (port 9091 publié pour NPM)

`docker-compose.authelia.yml` :
```yaml
services:
  authelia:
    image: authelia/authelia:4.39
    container_name: truenas-authelia
    restart: unless-stopped
    ports: ["9091:9091"]
    volumes: ["/mnt/Truenas_Stockage/apps/desktop/authelia:/config"]
    env_file: ["/mnt/Truenas_Stockage/apps/desktop/authelia/secrets.env"]
    environment: { TZ: "Europe/Paris" }
    healthcheck: { disable: true }
```
```bash
docker rm -f truenas-authelia 2>/dev/null
docker compose -f docker-compose.yml -f docker-compose.authelia.yml up -d authelia
docker logs --tail 15 truenas-authelia    # doit dire "listening", sans "fatal"
```

## 3. Bureau nginx « sans auth locale »

NPM+Authelia protège en amont : retire `auth_basic` du `nginx.conf` du bureau
(le fichier `nginx-desktop-plain.conf` fourni est prêt), puis :
```bash
docker restart truenas-desktop
```
> ⚠️ L'accès **direct** à `192.168.0.200:8099` contourne alors Authelia. À restreindre
> par pare-feu (n'autoriser que l'IP de NPM) une fois la 2FA validée.

## 4. Snippets dans NPM

Sur l'hôte NPM, place les 3 fichiers de `authelia/npm/` (`authelia-location.conf`,
`authelia-authrequest.conf`, `proxy.conf`) dans un dossier, et **monte-le dans le
conteneur NPM sous `/snippets`** (ajout d'un volume `- /chemin/snippets:/snippets:ro`
dans le compose de NPM, puis `docker restart` de NPM).

> Dans `authelia-location.conf`, l'adresse d'Authelia est `http://192.168.0.200:9091`
> (IP du NAS + port publié). Adapte si besoin.

## 5. NPM — proxy host du portail

`auth.goassistance.fr` → Forward **http** `192.168.0.200` port **9091**,
SSL Let's Encrypt + **Force SSL** + **Websockets**. Rien dans « Advanced ».

## 6. NPM — proxy host du bureau

`desktop.goassistance.fr` → Forward **http** `192.168.0.200` port **8099**,
SSL + Force SSL + Websockets. Onglet **Advanced** :
```
include /snippets/authelia-location.conf;
location / {
    include /snippets/proxy.conf;
    include /snippets/authelia-authrequest.conf;
    proxy_pass $forward_scheme://$server:$port;
}
```
> Les liens de partage publics `/s/` seront alors protégés eux aussi. Si tu les
> utilises, ajoute une location `/s/` **sans** `authelia-authrequest.conf`.

## 7. DNS (AdGuard) — pointer vers **NPM**

NPM est la porte d'entrée : les deux réécritures pointent vers **l'IP de NPM**, pas le NAS :
```
desktop.goassistance.fr → 192.168.0.254
auth.goassistance.fr    → 192.168.0.254
```

## 8. Enrôler le TOTP

Ouvre `https://desktop.goassistance.fr` → portail Authelia → login → il te propose
d'enrôler le TOTP. Le lien d'activation est écrit dans :
```bash
cat /mnt/Truenas_Stockage/apps/desktop/authelia/notification.txt
```
Scanne le QR code (Aegis, Google Authenticator…). Les connexions suivantes demandent
le **code à 6 chiffres**.

## Secours

L'accès direct au NAS (UI TrueNAS, SSH) n'est jamais affecté. Pour revenir en
barrière simple : remets `auth_basic` dans le `nginx.conf` du bureau,
`docker restart truenas-desktop`, et `docker rm -f truenas-authelia`.
