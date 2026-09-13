#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  lancer-vm.sh — une machine virtuelle qui ressemble au HUB, pour l'éprouver
# ═══════════════════════════════════════════════════════════════════════════════
#
# POURQUOI. L'installateur du HUB n'a jamais tourné pour de vrai. Le lancer d'abord
# sur la machine du salon, c'est découvrir ses défauts là où ils coûtent le plus.
# Cette machine virtuelle est la même cible en plus sûr : Ubuntu 26.04, démarrage
# UEFI comme le ThinkCentre M720q, disque non chiffré, installation automatique.
#
# CE QU'IL REFUSE. Il ne démarre jamais sur une ISO dont l'empreinte ne correspond
# pas à celle publiée par Canonical. Une image tronquée par une coupure donne une
# installation qui échoue au milieu, sans dire pourquoi — et on accuse l'installateur
# du HUB d'un défaut qui n'est pas le sien.
#
#   ./lancer-vm.sh --installer   premier démarrage : installe Ubuntu automatiquement
#   ./lancer-vm.sh               démarrages suivants : sur le disque installé
#   ./lancer-vm.sh --ecran       ouvre une fenêtre au lieu de tourner sans écran
#   ./lancer-vm.sh --iso CHEMIN  ISO rangée ailleurs que dans ce dossier
#
# Une fois démarrée :  ssh -i cle-vm -p 2222 samuel@127.0.0.1

set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"

ISO="ubuntu-26.04.1-desktop-amd64.iso"
DISQUE="disque-hub.qcow2"
TAILLE_DISQUE="40G"
PORT_SSH=2222
OVMF_CODE="/usr/share/OVMF/OVMF_CODE_4M.fd"
OVMF_VARS_MODELE="/usr/share/OVMF/OVMF_VARS_4M.fd"
OVMF_VARS="uefi-variables.fd"
INSTALLER=0
ECRAN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --installer) INSTALLER=1 ;;
    --ecran)     ECRAN=1 ;;
    --iso)       shift; ISO="${1:?--iso attend un chemin}" ;;
    -h|--help)   sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "argument inconnu : $1" >&2; exit 2 ;;
  esac
  shift
done

refus() { printf '  ✗ %s\n' "$1" >&2; exit "${2:-1}"; }
ok()    { printf '  ✓ %s\n' "$1"; }

printf '\n  Machine virtuelle du HUB\n\n'

# ── Ce que la machine hôte doit fournir ──────────────────────────────────────
command -v qemu-system-x86_64 >/dev/null || refus "qemu-system-x86_64 absent"
[ -r /dev/kvm ] && [ -w /dev/kvm ] || refus "/dev/kvm inaccessible : sans KVM la machine serait vingt fois trop lente pour juger quoi que ce soit"
[ -r "$OVMF_CODE" ] || refus "$OVMF_CODE absent : sans UEFI, l'essai ne ressemblerait pas au M720q"
ok "KVM et UEFI disponibles"

# ── Le premier démarrage installe ; les suivants démarrent sur le disque ─────
if [ "$INSTALLER" = 1 ]; then
  [ -f "$ISO" ] || refus "ISO introuvable : $ISO"
  [ -f cidata.iso ] || refus "cidata.iso absent : c'est lui qui rend l'installation automatique"

  attendue=$(awk -v n="$(basename "$ISO")" '$2 == "*"n || $2 == n {print $1}' SHA256SUMS 2>/dev/null)
  [ -n "$attendue" ] || refus "aucune empreinte pour $(basename "$ISO") dans SHA256SUMS"
  printf '  … vérification de l empreinte (6 Gio, une minute environ)\n'
  obtenue=$(sha256sum "$ISO" | cut -d' ' -f1)
  [ "$obtenue" = "$attendue" ] || refus "empreinte FAUSSE — l'ISO est incomplète ou abîmée. Attendue ${attendue:0:16}…, obtenue ${obtenue:0:16}…" 3
  ok "empreinte conforme à celle de Canonical"

  if [ -f "$DISQUE" ]; then
    refus "$DISQUE existe déjà. Réinstaller effacerait l'essai en cours : supprimez-le d'abord si c'est voulu."
  fi
  qemu-img create -q -f qcow2 "$DISQUE" "$TAILLE_DISQUE" || refus "création du disque impossible"
  ok "disque virtuel créé ($TAILLE_DISQUE, ne consomme que ce qui est écrit)"
  # Des variables UEFI propres à cette machine : le modèle système reste intact.
  cp "$OVMF_VARS_MODELE" "$OVMF_VARS"
else
  [ -f "$DISQUE" ] || refus "aucun disque installé : lancez d'abord ./lancer-vm.sh --installer"
  [ -f "$OVMF_VARS" ] || cp "$OVMF_VARS_MODELE" "$OVMF_VARS"
fi

# ── Le port SSH ne doit pas déjà être pris ───────────────────────────────────
if ss -ltn 2>/dev/null | grep -q ":$PORT_SSH\b"; then
  refus "le port $PORT_SSH est déjà pris — une autre machine virtuelle tourne-t-elle ?"
fi

args=(
  -name hub-essai
  -machine q35,accel=kvm
  -cpu host -smp 2 -m 4096
  -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE"
  -drive "if=pflash,format=raw,file=$OVMF_VARS"
  -drive "file=$DISQUE,if=virtio,format=qcow2"
  -netdev "user,id=reseau,hostfwd=tcp:127.0.0.1:$PORT_SSH-:22"
  -device virtio-net-pci,netdev=reseau
  -device virtio-vga
  # Pointeur ABSOLU : la souris relative par défaut ne se positionne pas de façon
  # fiable, si bien qu'on ne peut ni cliquer depuis le moniteur ni viser juste en VNC.
  # L'installateur d'Ubuntu 26.04 attend un clic sur « Install » (voir autoinstall).
  -device qemu-xhci -device usb-tablet
  -audiodev none,id=son -device intel-hda -device hda-duplex,audiodev=son
  # Moniteur QEMU sur une socket : il permet de capturer l'écran sans visionneuse.
  # Sans lui, une installation arrêtée sur une question ressemble à une installation
  # lente, et on attend pour rien.
  -monitor "unix:$PWD/moniteur.sock,server,nowait"
)
if [ "$INSTALLER" = 1 ]; then
  # On démarre le noyau de l'ISO directement, avec `autoinstall` sur sa ligne de
  # commande. Sans ce paramètre, l'installateur de bureau trouve bien la configuration
  # mais s'arrête sur « Ready to install » et attend un clic : vu le 13 septembre 2026,
  # il n'a jamais commencé. Le noyau et l'initrd sont extraits de l'ISO vérifiée
  # (voir extraire-noyau), pas téléchargés à part.
  [ -f noyau-installation ] && [ -f initrd-installation ] \
    || refus "noyau-installation / initrd-installation absents : extrayez-les de l'ISO"
  args+=(
    -drive "file=$ISO,media=cdrom,readonly=on"
    -drive "file=cidata.iso,media=cdrom,readonly=on"
    -kernel noyau-installation
    -initrd initrd-installation
    -append "autoinstall ds=nocloud --- quiet"
    # La fin d'installation redémarre la machine. Avec le noyau passé en direct, elle
    # relancerait l'installateur en boucle : on laisse QEMU s'arrêter à la place.
    -no-reboot
  )
fi
if [ "$ECRAN" = 1 ]; then
  args+=(-display gtk)
else
  args+=(-display none -vnc 127.0.0.1:1)
  ok "sans écran : VNC sur 127.0.0.1:5901 pour regarder"
fi

ok "SSH redirigé : ssh -i cle-vm -p $PORT_SSH samuel@127.0.0.1"
printf '\n'
exec qemu-system-x86_64 "${args[@]}"
