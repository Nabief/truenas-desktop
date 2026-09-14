# 2FA devant le bureau avec Authelia

Ajoute une **double authentification** (mot de passe + code TOTP) devant le
TrueNAS Desktop, imposée **côté serveur** par le nginx du bureau qui délègue à
**Authelia**. Kit **opt‑in** : l'installation par défaut n'est pas modifiée
(elle garde la barrière Basic auth). Tu bascules sur Authelia en suivant ce guide.

> 🆕 **Nouvelle install** : l'assistant web (`setup-wizard.py`) propose désormais une
> case **« Activer la 2FA (Authelia) »** dans l'étape Sécurité. Coché + 2 domaines
> saisis, il génère et démarre **automatiquement** toute la stack ci-dessous ; il ne
> te reste que les 2 entrées DNS et l'enrôlement TOTP. Ce guide reste la référence
> pour une install existante ou pour comprendre/dépanner.

> Fichiers du kit : `authelia/configuration.yml`, `authelia/users_database.yml`,
> `authelia/secrets.env.example`, `docker-compose.authelia.yml`,
> `authelia/nginx-authelia.snippet.conf`.

## Pré‑requis important : des domaines

Authelia s'appuie sur un **cookie de session** qui **exige des noms de domaine**
(pas des IP nues). Il te faut, via ton **DNS local**, deux sous‑domaines qui
pointent vers le NAS :

| Rôle | Exemple | Pointe vers |
|------|---------|-------------|
| Bureau | `desktop.goassistance.fr` | IP du NAS |
| Portail Authelia | `auth.goassistance.fr` | IP du NAS |

Les deux doivent partager un **domaine parent** (ici `goassistance.fr`) — c'est le
`domain` du cookie. Sur ton réseau, fais résoudre ces deux noms vers l'IP du NAS
(entrée DNS locale, Pi‑hole, ou fichier hosts). Le bureau reste **en LAN/VPN** :
ne publie jamais ces domaines sur Internet.

## 1. Secrets

```bash
cd /mnt/Truenas_Stockage/apps/desktop/authelia
cp secrets.env.example secrets.env
# Génère 3 secrets et colle-les dans secrets.env :
openssl rand -hex 32   # -> AUTHELIA_SESSION_SECRET
openssl rand -hex 32   # -> AUTHELIA_STORAGE_ENCRYPTION_KEY
openssl rand -hex 32   # -> AUTHELIA_IDENTITY_VALIDATION_RESET_PASSWORD_JWT_SECRET
chmod 600 secrets.env
```

## 2. Utilisateur + mot de passe

```bash
# Génère le hash argon2id de ton mot de passe :
docker run --rm authelia/authelia:4.39 \
  authelia crypto hash generate argon2 --password 'TON_MOT_DE_PASSE'
```

Colle la chaîne `$argon2id$...` dans `authelia/users_database.yml` (champ `password`),
ajuste `email`, et — dans `authelia/configuration.yml` — remplace `example.com`,
`desktop.example.com`, `auth.example.com` par tes domaines réels (et les ports si
tu n'utilises pas 8099).

## 3. Démarrer Authelia

```bash
cd /mnt/Truenas_Stockage/apps/desktop
docker compose -f docker-compose.yml -f docker-compose.authelia.yml up -d
docker logs truenas-authelia   # vérifie qu'il démarre sans erreur de config
```

## 4. Basculer le nginx du bureau sur Authelia

Édite `nginx.conf` (du bureau) en suivant `authelia/nginx-authelia.snippet.conf` :

1. **Retire** les deux lignes `auth_basic` du bloc `server{}` et **ajoute** à la
   place le `resolver`, les directives `auth_request` + `auth_request_set` +
   `error_page`, et l'emplacement interne `location /internal/authelia/authz`.
2. Dans `location /s/ {`, remplace `auth_basic off;` par **`auth_request off;`**
   (les partages publics restent ouverts).
3. Donne un `server_name desktop.example.com;` au bloc bureau et **ajoute** le
   second `server{}` qui sert le portail sur `auth.example.com`.

Puis recharge :

```bash
docker restart truenas-desktop
```

## 5. Enrôler le second facteur (TOTP)

Ouvre `http://desktop.goassistance.fr:8099` → tu es redirigé vers le portail
Authelia → connecte-toi avec ton identifiant/mot de passe. Pour le premier
enrôlement TOTP, Authelia écrit le lien d'activation dans un fichier (pas de mail) :

```bash
cat /mnt/Truenas_Stockage/apps/desktop/authelia/notification.txt
```

Ouvre le lien affiché, scanne le QR code avec ton appli d'authentification
(Aegis, Google Authenticator, 2FAS…), valide. Les connexions suivantes
demanderont le **code à 6 chiffres**.

## Secours (si tu te verrouilles)

L'accès **direct** au NAS (interface TrueNAS, SSH) n'est jamais affecté. Pour
revenir à la barrière simple sans Authelia :

```bash
cd /mnt/Truenas_Stockage/apps/desktop
# Remets les 2 lignes auth_basic dans nginx.conf (et auth_basic off; dans /s/),
# retire les blocs auth_request, puis :
docker restart truenas-desktop
docker compose -f docker-compose.yml -f docker-compose.authelia.yml stop authelia
```

## Notes

- **TLS** : en HTTP sur le LAN les cookies fonctionnent (schéma `http` dans
  `authelia_url`). Pour du HTTPS (recommandé à terme), mets des certificats sur
  les deux domaines et passe les URLs en `https://` (sans `:8099` si tu écoutes en 443).
- Ce kit n'enlève **pas** les deux autres remparts : bureau **hors d'Internet**,
  et **snapshots + sauvegarde** que le bureau ne peut pas supprimer.
- Version d'Authelia épinglée : **4.39** (le schéma de config évolue selon les
  versions ; garde cette image ou adapte la config si tu montes de version).
