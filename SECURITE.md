# Sécurité — barrière d'authentification devant le bureau

## Pourquoi

Le sidecar `fileops` tourne **en root**, monte **tout le pool** (`/mnt`) et expose une
API de fichiers **plus un terminal**. Son seul contrôle d'accès natif est le
`FILEOPS_TOKEN` — or ce token est **inscrit dans la page HTML** servie par nginx, et
l'écran de login du bureau est purement **côté client**. Conséquence : sans barrière
serveur, **quiconque peut atteindre le port 8099 obtient un accès root au NAS**.

La barrière ajoutée impose une **authentification HTTP (côté serveur)** *avant* de servir
la page et les endpoints sensibles (`/`, `/fileops/`, `/truenas-shell`, `/vnc-proxy`,
`/vnc-viewer`). Les liens de partage publics `/s/` en sont **exemptés**.

> ⚠️ La barrière ne remplace **pas** les deux autres remparts :
> 1. **Ne jamais exposer le bureau à Internet** (pas de reverse proxy public / port-forward). Accès distant = **VPN**.
> 2. **Snapshots ZFS + sauvegarde hors-machine** que le bureau ne peut pas supprimer, pour que les données restent récupérables quoi qu'il arrive.

## Nouvelles installations

`install.sh` et l'assistant web demandent (ou génèrent) un **identifiant + mot de passe
du bureau**, écrivent `.htpasswd` et le montent dans le conteneur nginx. Rien à faire de
plus : les identifiants sont affichés en fin d'installation.

## Activer sur une installation EXISTANTE

Le bouton « Mettre à jour » ne déploie que `fileops.py` et le HTML — **pas** `nginx.conf`.
Il faut donc activer la barrière à la main, une fois, sur le NAS.

Depuis le Shell TrueNAS (adapte le chemin d'install si besoin) :

```bash
cd /mnt/<pool>/apps/desktop

# 1) Identifiant + mot de passe du bureau (remplace VOTRE_MOT_DE_PASSE)
printf 'admin:%s\n' "$(openssl passwd -apr1 'VOTRE_MOT_DE_PASSE')" > .htpasswd
chmod 600 .htpasswd
```

**2) `nginx.conf`** — au niveau `server`, juste après la ligne `index index.html;`, ajoute :

```nginx
    auth_basic           "TrueNAS Desktop";
    auth_basic_user_file /etc/nginx/.htpasswd;
```

et dans le bloc `location /s/ {`, ajoute en **première** ligne (pour garder les partages publics) :

```nginx
        auth_basic off;
```

**3) `docker-compose.yml`** — dans le service `truenas-desktop`, ajoute un volume :

```yaml
      - /mnt/<pool>/apps/desktop/.htpasswd:/etc/nginx/.htpasswd:ro
```

**4) Recréer et recharger :**

```bash
docker compose up -d
docker restart truenas-desktop
```

Le navigateur demandera désormais l'identifiant/mot de passe **avant** d'afficher le bureau.

## En cas de verrouillage (secours)

Si tu te retrouves bloqué (mauvais mot de passe, `.htpasswd` vide/absent) :

```bash
cd /mnt/<pool>/apps/desktop
# Option A : régénérer le mot de passe
printf 'admin:%s\n' "$(openssl passwd -apr1 'NOUVEAU_MDP')" > .htpasswd && docker restart truenas-desktop
# Option B : désactiver temporairement la barrière
#   -> commente les 2 lignes 'auth_basic' dans nginx.conf, puis :
docker restart truenas-desktop
```

L'accès **direct** au reste du NAS (interface TrueNAS, SSH) n'est jamais affecté par cette barrière.

## Aller plus loin : 2FA via un portail

Pour un vrai second facteur (login + code TOTP), place un portail
**Authelia** ou **authentik** devant le bureau et remplace les deux lignes `auth_basic`
par une délégation `auth_request` vers le portail (protège `/`, `/fileops/`,
`/truenas-shell`, `/vnc-proxy` ; laisse `/s/` public). La barrière Basic reste un bon
socle mono-facteur en attendant.

## Durcissement complémentaire (optionnel)

- **Clé SSH dédiée** pour le sidecar + **désactivation de l'auth SSH par mot de passe** sur le NAS (réduit la surface de brute-force). Le `sudo NOPASSWD` reste nécessaire au pilotage libvirt.
- **Permissions strictes** sur les secrets (`.env`, `config.env`, `.htpasswd` en `chmod 600`).
- **Ne monter que les datasets utiles** au lieu de tout `/mnt`, si l'usage le permet.


## Récupération — identifiants / mot de passe oubliés

Il n'y a pas de « mot de passe oublié » intégré, mais rien n'est bloquant : l'admin du
NAS garde toujours la main (l'accès UI TrueNAS / SSH n'est jamais protégé par le bureau).
Remplace `<pool>` par ton pool de stockage.

### Barrière simple (login du bureau)

Le mot de passe n'est pas stocké en clair (seulement le hash `.htpasswd`) : on le **réinitialise**.

- Le plus simple : **relancer l'assistant d'installation** (idempotent) en saisissant un
  nouveau mot de passe → il régénère `.htpasswd`.
- Ou en une ligne (SSH / Shell TrueNAS) :
  ```bash
  printf 'admin:%s\n' "$(openssl passwd -apr1 'NOUVEAU_MDP')" > /mnt/<pool>/apps/desktop/.htpasswd
  docker restart truenas-desktop
  ```

### 2FA Authelia

- **Mot de passe oublié** : si le SMTP est configuré, utilise le lien « Réinitialiser le
  mot de passe » du portail (mail). Sinon, régénère le hash argon2 et remplace-le dans
  `authelia/users_database.yml` :
  ```bash
  docker run --rm authelia/authelia:4.39 authelia crypto hash generate argon2 --password 'NOUVEAU_MDP'
  # colle la chaine $argon2id$... dans users_database.yml, puis :
  docker compose up -d --force-recreate authelia
  ```
- **Appareil TOTP perdu** (téléphone cassé...) : efface l'enrôlement et recommence :
  ```bash
  rm -f /mnt/<pool>/apps/desktop/authelia/db.sqlite3
  docker restart truenas-authelia
  ```
  → à la reconnexion, Authelia propose de ré-enrôler un nouveau QR code.

> Filet ultime : l'accès **UI TrueNAS / SSH** du NAS n'est jamais protégé par le bureau —
> on ne peut donc pas se verrouiller dehors définitivement.
