#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
#  premier-demarrage.sh — au premier allumage après la clé : audit, puis HUB
# ═══════════════════════════════════════════════════════════════════════════════
#
# POURQUOI AU PREMIER DÉMARRAGE, ET PAS PENDANT L'INSTALLATION D'UBUNTU. Pendant
# l'installation, la machine n'est pas encore elle-même : pas de GDM qui tourne, pas
# d'AccountsService, pas le vrai matériel vu par le système installé. L'audit mesurerait
# l'installateur, pas le HUB. Ici, la machine a démarré sur son disque : l'audit décrit
# ce qui sera vraiment le HUB, puis hub-installer.sh fait exactement ce qu'il a fait
# en VM.
#
# Tout s'affiche sur l'écran (tty1), avant l'écran de connexion : branché à la TV, on
# voit l'installation avancer. Tout est aussi gardé dans /var/log/hub/.
#
# Une seule tentative réussie : ensuite le service se désactive. En cas d'échec, il
# reste actif et retentera au prochain démarrage (réseau absent, coupure…).

set -uo pipefail
DEPOT=/opt/hub
JOURNAL=/var/log/hub
UTILISATEUR=samuel
mkdir -p "$JOURNAL"
exec > >(tee -a "$JOURNAL/premier-demarrage.log") 2>&1

plymouth quit 2>/dev/null || true
chvt 1 2>/dev/null || true
setterm --blank 0 --powersave off 2>/dev/null || true
clear 2>/dev/null || true

# Couleurs du HUB sur la console : turquoise pour l'avancement, ambre pour ce qui attend.
T=$'\e[1;38;2;62;224;208m'; A=$'\e[38;2;255;181;71m'; D=$'\e[38;2;154;166;189m'; Z=$'\e[0m'
printf '\n\n   %s▪  H U B%s\n' "$T" "$Z"
printf '   %spremière mise en route%s\n\n' "$D" "$Z"
printf '   %sNe pas éteindre la machine : 20 à 40 minutes. Elle redémarrera toute seule.%s\n\n' "$A" "$Z"

# ── Réseau : l'installateur télécharge Kodi, WebKit, les modèles de voix… ────
attente=0
until getent hosts archive.ubuntu.com >/dev/null 2>&1; do
  if [ $((attente % 30)) -eq 0 ]; then
    printf '   %s… en attente du réseau : branchez le câble Ethernet (%d s)%s\n' "$A" "$attente" "$Z"
  fi
  sleep 5
  attente=$((attente+5))
done
printf '   %s✓%s réseau disponible\n\n' "$T" "$Z"

# ── Audit : la règle du projet, même ici ─────────────────────────────────────
printf '   %s[1/2]%s Audit du matériel…\n' "$T" "$Z"
rapport="$JOURNAL/audit-$(date +%F-%H%M).md"
runuser -u "$UTILISATEUR" -- bash "$DEPOT/audit/audit.sh" > "$rapport" 2>&1
printf '   ✓ audit écrit dans %s\n\n' "$rapport"

# ── Installation du HUB ─────────────────────────────────────────────────────
printf '   %s[2/2]%s Installation du HUB…\n\n' "$T" "$Z"
cd "$DEPOT" || exit 1
if SUDO_USER="$UTILISATEUR" DEBIAN_FRONTEND=noninteractive bash installer/hub-installer.sh --pour-de-vrai; then
  cp "$rapport" "/home/$UTILISATEUR/audit-premier-demarrage.md" 2>/dev/null && chown "$UTILISATEUR:" "/home/$UTILISATEUR/audit-premier-demarrage.md"
  systemctl disable hub-premier-demarrage.service
  printf '\n   ✓ HUB installé. Redémarrage dans 10 secondes…\n'
  sleep 10
  systemctl reboot
else
  code=$?
  printf '\n   ✗ L’installation du HUB a échoué (code %d).\n' "$code"
  printf '     Le détail est dans %s/premier-demarrage.log.\n' "$JOURNAL"
  printf '     Ubuntu démarre normalement ; l’installation sera retentée au prochain allumage.\n'
  sleep 60
  exit 0
fi
