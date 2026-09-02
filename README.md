# TrueNAS Desktop

Bureau web complet pour TrueNAS SCALE : gestionnaire de fichiers, terminal,
gestion QEMU/KVM (console VNC), Docker, sites web (PHP/MariaDB), gestionnaire
de téléchargements (débrideurs/premium), et plus.

L'installation se fait via un **assistant web** (formulaire) : une seule commande
à coller dans le Shell TrueNAS, puis tout se fait à la souris.

---

## Prérequis (côté TrueNAS, une fois)

- TrueNAS SCALE **24.10 ou antérieur** (les VMs utilisent libvirt/KVM ;
  voir la note « TrueNAS 25.04+ » plus bas).
- Un **pool de stockage** créé, et **Apps activé** (Apps → assigner un pool → Docker démarre).
- **Réseau/DNS** fonctionnels (passerelle + DNS, ex. 1.1.1.1 / 8.8.8.8).
- Un **utilisateur administrateur** local avec un **mot de passe** (ex. `truenas_admin`).

> Pas besoin d'activer SSH ni de configurer le sudo à la main : l'assistant le fait.

---

## Installation (assistant web)

1. **TrueNAS → System → Shell**, coller cette ligne :

   ```bash
   curl -fsSL https://raw.githubusercontent.com/Nabief/truenas-desktop/main/setup-wizard.py -o /tmp/tnd-setup.py && sudo python3 /tmp/tnd-setup.py
   ```

   Laisser cette fenêtre ouverte : elle affiche l'adresse de l'assistant.

2. Ouvrir dans le navigateur :

   ```
   http://IP_DU_NAS:8090/setup
   ```

3. Dérouler le formulaire :
   - **Prérequis** : tout doit être vert (le Shell doit être lancé en `sudo`).
   - **Configuration** : le **pool** est auto‑détecté, l'**IP** est auto‑remplie ;
     saisir l'**utilisateur admin** et son **mot de passe**. Le token et le mot de
     passe de la base sont générés automatiquement.
   - **Installer** : la progression défile. L'assistant active SSH + sudo,
     crée les dossiers, télécharge les fichiers, génère `docker-compose.yml` et
     `nginx.conf`, configure le host (libvirtd/polkit) et démarre la stack.

4. À la fin, cliquer **Ouvrir le bureau** :

   ```
   http://IP_DU_NAS:8099
   ```

   Se connecter avec **son compte TrueNAS** (même identifiant/mot de passe que
   l'interface web du NAS).

---

## Ce que l'assistant automatise

- Active le service **SSH** + **authentification par mot de passe** (via `midclt`).
- Donne le **sudo sans mot de passe** à l'utilisateur (nécessaire au pilotage libvirt).
- Crée le **dataset/dossiers** de l'application.
- Génère un **token** et un **mot de passe MariaDB** aléatoires.
- Génère `docker-compose.yml` (bureau + sidecar + sites PHP + MariaDB) et `nginx.conf`.
- Configure le **host** pour les VMs (libvirtd, polkit, réseau `default`).
- Démarre la stack et l'active au boot.

---

## Notes

- **Sécurité** : l'assistant active l'auth SSH par mot de passe et le sudo NOPASSWD
  pour le compte indiqué — pratique mais à assumer. Une variante par clé SSH dédiée
  est possible pour durcir.
- **TrueNAS 25.04+ (Fangtooth)** : la virtualisation est passée de libvirt/KVM à
  **Incus**. Sur ces versions, le module VMs (basé sur virsh/libvirt) ne fonctionne
  pas en l'état ; le reste du bureau (fichiers, Docker, sites, téléchargements)
  fonctionne.
- **Mise à jour** : pousser les nouveaux fichiers sur le dépôt, puis relancer
  l'assistant (idempotent) ou recréer les conteneurs.

## Dépannage rapide

- **502 Bad Gateway sur un module** : le sidecar `fileops` redémarre (installe ses
  dépendances). Attendre ~1 min et rafraîchir.
- **VMs : « Bad authentication type: publickey »** : activer l'auth mot de passe SSH.
- **VMs : « sudo: a password is required »** : activer le sudo **sans mot de passe**.
  (L'assistant à jour le fait automatiquement.)
- **Voyant WS rouge** : mot de passe SSH modifié après l'install → relancer
  l'assistant pour resynchroniser.
