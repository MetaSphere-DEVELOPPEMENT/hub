#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  essayer-cle.sh — démarrer la VM exactement comme le M720q sur la clé HUB
# ═══════════════════════════════════════════════════════════════════════════════
#
# Pas de noyau passé en direct, pas de cidata à côté : l'image de la clé est branchée
# comme une clé USB, le disque est un NVMe (celui que la clé vise), et le micrologiciel
# UEFI démarre dessus tout seul. Ce qui marche ici est ce que fera la vraie clé.
#
#   ./essayer-cle.sh --installer                 disque neuf + clé branchée (menu : valider par Entrée)
#   ./essayer-cle.sh                             clé retirée : premier démarrage puis HUB
#   ... --sans-reseau                            câble Ethernet débranché dès l'allumage
#   ./cable.py branche                           le rebrancher, VM allumée
#
# SANS RÉSEAU : le cas que la VM n'essayait pas. Le réseau de QEMU est toujours là, si
# bien que la clé n'avait jamais installé qu'avec le miroir d'Ubuntu joignable. Sur le
# M720q, câble débranché (16/09/2026), un paquet absent du pool de l'ISO a arrêté
# l'installation avant la copie du HUB. Le scénario complet est dans ARCHITECTURE.md
# (« La clé HUB, avec et sans réseau »).
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"
DISQUE=disque-hub-cle.qcow2
VARS=disque-hub-cle-uefi-variables.fd
CLE=../cle/sortie/hub-cle.iso
INSTALLER=0
SANS_RESEAU=0
for arg in "$@"; do
  case "$arg" in
    --installer)   INSTALLER=1 ;;
    --sans-reseau) SANS_RESEAU=1 ;;
    *) echo "argument inconnu : $arg" >&2; exit 2 ;;
  esac
done
args=(
  -name hub-cle -machine q35,accel=kvm -cpu host -smp 2 -m 4096
  -drive "if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd"
  -drive "if=pflash,format=raw,file=$VARS"
  -drive "if=none,id=nvme,file=$DISQUE,format=qcow2" -device nvme,drive=nvme,serial=HUBNVME
  -netdev "user,id=reseau,hostfwd=tcp:127.0.0.1:2222-:22" -device virtio-net-pci,netdev=reseau
  -device virtio-vga -device qemu-xhci -device usb-tablet -device usb-kbd
  -audiodev none,id=son -device intel-hda -device hda-duplex,audiodev=son
  -monitor "unix:$PWD/moniteur.sock,server,nowait"
  -display none -vnc 127.0.0.1:1
)
if [ "$INSTALLER" = 1 ]; then
  [ -f "$CLE" ] || { echo "image de clé absente : ../cle/construire-cle.sh" >&2; exit 1; }
  [ -f "$DISQUE" ] && { echo "$DISQUE existe déjà : supprimez-le pour réinstaller" >&2; exit 1; }
  qemu-img create -q -f qcow2 "$DISQUE" 64G
  cp /usr/share/OVMF/OVMF_VARS_4M.fd "$VARS"
  args+=(-drive "if=none,id=cle,file=$CLE,format=raw,readonly=on" -device usb-storage,drive=cle,removable=on)
fi
if [ "$SANS_RESEAU" = 0 ]; then
  exec qemu-system-x86_64 "${args[@]}"
fi

# Lancée en pause (-S) : le câble est débranché avant la première instruction, sans
# course avec le micrologiciel ni avec l'installateur.
rm -f moniteur.sock
qemu-system-x86_64 "${args[@]}" -S &
qemu=$!
for _ in $(seq 50); do [ -S moniteur.sock ] && break; sleep 0.1; done
if ! python3 cable.py debranche --demarrer; then
  kill "$qemu" 2>/dev/null
  exit 1
fi
wait "$qemu"
