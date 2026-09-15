# 2FA Authelia derriere Nginx Proxy Manager (NPM)

> Memo de reference. L'assistant d'installation (`setup-wizard.py`) fait tout le cote
> NAS automatiquement quand tu coches « Activer la 2FA ». Ce document decrit la
> methode complete, les etapes manuelles (NPM + DNS + email) et surtout les pieges.

Remplace `exemple.fr`, `192.168.1.10` (NAS) et `192.168.1.2` (NPM) par tes valeurs.
Les deux sous-domaines doivent partager le meme domaine parent.

> **Recommande : NPMplus** (un fork de Nginx Proxy Manager). Il **integre nativement Authelia**
> (menu « Auth Request » -> « authelia (modern) »), ce qui evite de monter des snippets dans le
> conteneur NPM et rend la mise en place bien plus simple que NPM standard. Depot :
> https://github.com/ZoeyVid/NPMplus

## Principe

Navigateur -> **NPM (HTTPS Let's Encrypt)** -> { portail Authelia | bureau }. NPM exige
login + code TOTP (via Authelia) avant de laisser passer vers le bureau. Authelia 4.39
**exige des URLs HTTPS** : c'est NPM qui les fournit.

- Bureau  : `https://desktop.exemple.fr`  ->  NPM  ->  `NAS:8099`
- Portail : `https://auth.exemple.fr`      ->  NPM  ->  `NAS:9091`

## 1. Cote NAS — fait par l'assistant

En cochant « 2FA », l'assistant cree `authelia/` avec : `secrets.env` (secrets aleatoires,
**preserves** aux reinstallations), `users_database.yml` (utilisateur + hash argon2 du mot de
passe), `configuration.yml` (HTTPS), le conteneur `truenas-authelia` publie sur le port
**9091**, et le nginx du bureau **sans barriere locale** (NPM+Authelia protegent en amont).
Fichiers d'exemple : voir `authelia/`.

## 2. Demarrer / recharger Authelia

```bash
cd /mnt/<pool>/apps/desktop
docker compose up -d --force-recreate authelia
docker logs --tail 10 truenas-authelia    # doit dire "Startup complete" + "Listening ... :9091"
```

> **Piege n1 :** un simple `docker restart` **ne recharge PAS** `secrets.env` (Docker ne lit
> `env_file` qu'a la creation du conteneur). Apres toute modif des secrets ou du mot de passe
> SMTP, utilise **`up -d --force-recreate`**, jamais `restart`.

## 3. NPM — deux hotes proxy

**Portail** `auth.exemple.fr` -> Forward **http** `192.168.1.10` port **9091** ;
SSL Let's Encrypt + Force SSL + Websockets ; rien dans Advanced.

**Bureau** `desktop.exemple.fr` -> Forward **http** `192.168.1.10` port **8099** ;
SSL + Force SSL + Websockets ; plus l'authentification Authelia :

- **NPMplus — RECOMMANDE** : dans l'hote proxy du bureau, Auth Request = **`authelia (modern)`**,
  Auth Request Upstream = **`http://192.168.1.10:9091`** (schema + hote + port, **sans** chemin).
  Rien d'autre a monter cote NPM.
- **NPM standard (sans integration Authelia)** : monte `authelia/npm/` dans le conteneur NPM sous
  `/snippets`, puis onglet Advanced :
  ```
  include /snippets/authelia-location.conf;
  location / { include /snippets/proxy.conf; include /snippets/authelia-authrequest.conf; proxy_pass $forward_scheme://$server:$port; }
  ```

> **Piege n2 :** le certificat Let's Encrypt echoue (« Internal Error ») **tant que le DNS
> ne resout pas** le domaine. Fais d'abord l'etape 4, attends quelques minutes, puis demande le cert.

## 4. DNS

Ajoute `desktop` et `auth` comme tes autres services (chez ton hebergeur DNS), pointant vers ton
acces habituel (enregistrements A publics, ou IP de NPM en reseau local). Verifie :
```bash
nslookup desktop.exemple.fr
```

## 5. Email (SMTP) — optionnel

Renseigne dans l'assistant (serveur, port, identifiant, mot de passe), ou a la main dans
`configuration.yml` :
```yaml
notifier:
  smtp:
    address: 'submissions://mail.exemple.fr:465'   # 465 = SSL ; 587 -> submission://mail.exemple.fr:587 (STARTTLS)
    username: 'noreply@exemple.fr'
    sender: 'TrueNAS Desktop <noreply@exemple.fr>'
    subject: '[Authelia] {title}'
```
et le mot de passe dans `secrets.env` :
```
AUTHELIA_NOTIFIER_SMTP_PASSWORD=...
```
puis **`docker compose up -d --force-recreate authelia`** (piege n1 !). Sans SMTP, les codes
sont ecrits dans `authelia/notification.txt`.

## 6. Enrolement TOTP

Ouvre `https://desktop.exemple.fr` -> portail Authelia -> login -> le code de verification arrive
par email (ou dans `notification.txt`), puis scanne le QR (Aegis, Google Authenticator...).

## Pieges (resume)

- **`restart` ne recharge pas `secrets.env`** -> `up -d --force-recreate`.
- **Cle de chiffrement changee** -> Authelia refuse la base (`db.sqlite3`). L'assistant preserve
  desormais les secrets ; si tu changes la cle a la main, supprime `authelia/db.sqlite3` (vide tant
  que rien n'est enrole) puis recree le conteneur.
- **Cert Let's Encrypt** : DNS d'abord, certificat ensuite.
- **`535 auth failed`** vient du **mot de passe SMTP** (ou d'un caractere invisible colle) : teste-le
  dans le webmail ; s'il marche la, c'est que le conteneur n'a pas ete recree (voir piege n1).

## Secours

L'acces direct au NAS (UI TrueNAS, SSH) n'est jamais affecte. Pour revenir a la barriere simple :
remets `auth_basic` dans le nginx du bureau, recree le bureau, et `docker rm -f truenas-authelia`.
