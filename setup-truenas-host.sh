#!/bin/bash
# ============================================================
# setup-truenas-host.sh  (v1.4.0)
# Prépare libvirt/QEMU-KVM pour le bureau, SANS modifier /etc.
#
#   ⚠ Les versions <1.4.0 écrivaient un drop-in systemd
#     (/etc/systemd/system/libvirtd.service.d/notimeout.conf), une règle
#     polkit et faisaient « systemctl enable ». Sur TrueNAS 25.x cela
#     créait un « ordering cycle » systemd fatal (ix-etc.service /
#     middlewared en échec au boot → « middleware is not running »).
#
#   Cette version ne touche plus /etc : elle démarre libvirt À LA DEMANDE
#   (start, jamais enable) et n'altère pas l'ordonnancement de boot.
#   Le démarrage automatique de la stack est géré par un Init/Shutdown
#   Script TrueNAS (POSTINIT), en dehors du chemin critique systemd.
#
# Usage :
#   chmod +x setup-truenas-host.sh
#   sudo ./setup-truenas-host.sh
#
# Idempotent, sans effet de bord sur le boot.
# ============================================================
set +e

VIRSH_URI="qemu:///system"

echo "=== Réparation : suppression des anciennes modifs /etc (si présentes) ==="
systemctl disable truenas-desktop 2>/dev/null || true
rm -f /etc/systemd/system/truenas-desktop.service
rm -f /etc/systemd/system/libvirtd.service.d/notimeout.conf
rmdir /etc/systemd/system/libvirtd.service.d 2>/dev/null || true
rm -f /etc/tmpfiles.d/truenas-libvirt.conf
rm -f /etc/polkit-1/rules.d/80-truenas-libvirt.rules
systemctl daemon-reload 2>/dev/null || true

echo "=== Démarrage de libvirt (à la demande, sans 'enable') ==="
systemctl unmask libvirtd.socket libvirtd-ro.socket libvirtd-admin.socket 2>/dev/null || true
systemctl start libvirtd 2>/dev/null || systemctl start virtqemud 2>/dev/null || true

echo "=== Attente du socket libvirt ==="
for i in $(seq 1 15); do
  [ -S /run/libvirt/libvirt-sock ] && echo "  socket OK" && break
  sleep 1
done

echo "=== Réseau 'default' libvirt ==="
virsh -c "$VIRSH_URI" net-start default 2>/dev/null && echo "  default démarré" || echo "  default déjà actif/absent"

echo ""
echo "=== Terminé (aucune modification de /etc, aucun impact sur le boot). ==="
virsh -c "$VIRSH_URI" list --all 2>/dev/null
virsh -c "$VIRSH_URI" net-list --all 2>/dev/null
