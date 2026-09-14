# TrueNAS Desktop — Installation sans ligne de commande

Déploiement 100% via l'interface web de TrueNAS SCALE (24.10+), sans shell.

## 1. Publier les fichiers sur GitHub (une fois)

Crée un dépôt **public** (ex: `truenas-desktop`) contenant au minimum :

```
fileops.py
truenas-desktop.html
vnc-viewer.html
app-init.sh
```

Note l'URL « raw » de la branche, par exemple :
`https://raw.githubusercontent.com/TON_USER/truenas-desktop/main`

## 2. Pré-requis sur le NAS (interface web uniquement)

- **Storage** → créer le dataset `POOL/apps/desktop` (remplace `POOL` par ton pool).
- **System → Services → SSH** → *Start* + *Start Automatically*.
- Un utilisateur admin (ex: `truenas_admin`) avec **sudo** (rôle *Local Administrator*).

## 3. Installer l'app

**Apps → Discover Apps → Custom App → Install via YAML.**

Colle le contenu de `docker-compose.customapp.yml`, puis avant de valider :

1. Remplace **partout** `/mnt/POOL` par ton pool (ex: `/mnt/tank`).
2. Renseigne les valeurs marquées `← MODIFIER` :
   - `GITHUB_RAW` = l'URL raw de ton dépôt (étape 1)
   - `FILEOPS_TOKEN` = un secret que tu choisis (**identique** dans `app-init` et `fileops`)
   - `TRUENAS_IP` / `TRUENAS_HOST` / `TRUENAS_UI_URL` = l'IP (ou FQDN) du NAS
   - `TRUENAS_SSH_USER` / `TRUENAS_SSH_PASS` = identifiants de l'admin SSH
   - `DB_ROOT_PASSWORD` = un mot de passe (**identique** dans `fileops` et `mariadb`)

Valide. Au premier lancement :

- `app-init` télécharge les fichiers depuis GitHub, injecte le token, génère `nginx.conf`, puis s'arrête.
- `fileops` démarre et **configure le host** (libvirtd + polkit + réseau) automatiquement via SSH — nécessaire pour les VMs.
- Les autres conteneurs démarrent (le premier boot installe pip/qemu/p7zip : ~1 min).

## 4. Accès

```
http://IP_DU_NAS:8099
```

## 5. Mises à jour

Pousse les nouveaux fichiers sur GitHub, puis dans l'UI TrueNAS :
**Apps → l'app → Edit → Save** (ou *Restart*) — `app-init` re-télécharge la dernière version.

---

### Dépannage

- **Page blanche / 403** : vérifie que `FILEOPS_TOKEN` est **identique** dans `app-init` et `fileops`.
- **`app-init` échoue** : `GITHUB_RAW` incorrect ou dépôt privé → rends le dépôt public et vérifie l'URL.
- **VMs indisponibles** : SSH non activé ou utilisateur sans sudo → le bootstrap host ne peut pas s'exécuter. Vérifie les logs du conteneur `truenas-fileops`.
- **Uploads volumineux** : déjà géré (`client_max_body_size 20g`).
