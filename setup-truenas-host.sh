#!/bin/bash
# ============================================================
# setup-truenas-host.sh
# À exécuter UNE FOIS en root sur le host TrueNAS SCALE
# pour activer la gestion QEMU/KVM depuis le bureau.
#
# Usage :
#   chmod +x setup-truenas-host.sh
#   sudo ./setup-truenas-host.sh
#
# Idempotent : sans danger à relancer après une mise à jour.
# ============================================================
set -e

VIRSH_URI="qemu:///system"
VM_DIR="/mnt/Truenas_Stockage/vms"

echo "=== 1/5  Suppression du timeout libvirtd ==="
mkdir -p /etc/systemd/system/libvirtd.service.d
cat > /etc/systemd/system/libvirtd.service.d/notimeout.conf << 'EOF'
[Service]
Environment=LIBVIRTD_ARGS=
EOF
systemctl daemon-reload
systemctl restart libvirtd

echo "=== 2/5  Attente du socket libvirt ==="
for i in $(seq 1 15); do
  [ -S /run/libvirt/libvirt-sock ] && echo "  socket OK" && break
  echo "  attente $i/15..."
  sleep 1
done
if [ ! -S /run/libvirt/libvirt-sock ]; then
  echo "ERREUR : socket libvirt introuvable après 15s"
  journalctl -u libvirtd -n 20 --no-pager
  exit 1
fi

echo "=== 3/5  Règle polkit pour truenas_admin ==="
mkdir -p /etc/polkit-1/rules.d
cat > /etc/polkit-1/rules.d/80-truenas-libvirt.rules << 'EOF'
polkit.addRule(function(action, subject) {
    if (action.id == "org.libvirt.unix.manage" &&
        subject.user == "truenas_admin") {
            return polkit.Result.YES;
    }
});
EOF
echo "  règle écrite dans /etc/polkit-1/rules.d/80-truenas-libvirt.rules"

echo "=== 4/5  Réseau 'default' libvirt ==="
virsh -c "$VIRSH_URI" net-start default 2>/dev/null && echo "  default démarré" || echo "  default déjà actif"
virsh -c "$VIRSH_URI" net-autostart default && echo "  autostart activé" || true

echo "=== 5/5  Dossier VMs ==="
mkdir -p "$VM_DIR"
chmod 777 "$VM_DIR"
echo "  $VM_DIR prêt"

echo ""
echo "=== Setup terminé ! ==="
echo "Vérification :"
virsh -c "$VIRSH_URI" list --all
virsh -c "$VIRSH_URI" net-list --all
