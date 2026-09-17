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
# L'écran (tty1, avant l'écran de connexion) ne montre qu'un résumé : une ligne par
# étape de l'installateur, avec le temps écoulé. La sortie complète de l'installateur
# va dans /var/log/hub/ seulement : affichée telle quelle, elle faisait défiler des
# centaines de lignes d'apt qui chassaient « Ne pas éteindre » du haut de la TV, sans
# dire où on en était sur 20 à 40 minutes.
#
# Une seule tentative réussie : ensuite le service se désactive. En cas d'échec, il
# reste actif et retentera au prochain démarrage (réseau absent, coupure…).

set -uo pipefail
# Surchargeables pour les tests seulement : systemd ne pose aucune de ces variables.
DEPOT=${HUB_DEPOT:-/opt/hub}
JOURNAL=${HUB_JOURNAL:-/var/log/hub}
UTILISATEUR=samuel
mkdir -p "$JOURNAL"
LOG="$JOURNAL/premier-demarrage.log"
SORTIE_INSTALLATEUR="$JOURNAL/installateur.log"

# fd 3 = l'écran ; tout le reste (erreurs des commandes comprises) part au journal.
# Pas de tee : la ligne d'avancement se redessine sur place (\r) et n'a rien à faire
# dans un journal, où elle deviendrait des milliers de lignes.
exec 3>&1
exec >>"$LOG" 2>&1
printf '\n=== premier démarrage, %s ===\n' "$(date '+%F %T')"

plymouth quit || true
chvt 1 || true
setterm --blank 0 --powersave off >&3 || true
# Police de 16×32 : la police par défaut de la console, lue à 3 m sur une TV, est
# minuscule. ter-v32b vient du paquet console-terminus, qu'Ubuntu Desktop n'installe
# pas forcément : absente, on garde la police du noyau plutôt que d'échouer.
for police in /usr/share/consolefonts/ter-v32b.psf.gz /usr/share/consolefonts/ter-v32b.psf; do
  if [ -e "$police" ] && command -v setfont >/dev/null; then
    setfont "$police" || true
    break
  fi
done

# Couleurs du HUB sur la console : turquoise pour l'avancement, ambre pour ce qui attend.
T=$'\e[1;38;2;62;224;208m'; A=$'\e[1;38;2;255;181;71m'; D=$'\e[38;2;154;166;189m'
R=$'\e[1;38;2;255;107;107m'; Z=$'\e[0m'; EFF=$'\r\e[K'

# Écrit à l'écran et au journal. Le format est toujours une constante de ce script.
# shellcheck disable=SC2059
dire() { printf "$@" >&3; printf "$@"; }

duree() { printf '%d min %02d s' $(($1 / 60)) $(($1 % 60)); }

entete() {
  printf '\e[H\e[2J' >&3
  printf '\n\n   %s▪  H U B%s\n' "$T" "$Z" >&3
  printf '   %spremière mise en route%s\n\n' "$D" "$Z" >&3
  # Sur l'écran d'échec, « Ne pas éteindre » contredirait la consigne d'éteindre pour réessayer.
  [ "${1:-}" = echec ] ||
    printf '   %sNe pas éteindre la machine : 20 à 40 minutes. Elle redémarrera toute seule.%s\n\n' "$A" "$Z" >&3
}
entete

# ── Réseau : l'installateur télécharge Kodi, WebKit, les modèles de voix… ────
# La ligne d'attente se redessine au lieu de s'empiler toutes les 30 s : une nuit sans
# câble aurait fini par pousser l'en-tête hors de l'écran.
attente=0
until getent hosts archive.ubuntu.com >/dev/null 2>&1; do
  [ "$attente" -eq 0 ] && printf 'en attente du réseau\n'
  printf '%s   %s… en attente du réseau : branchez le câble Ethernet (%s)%s' \
    "$EFF" "$A" "$(duree "$attente")" "$Z" >&3
  sleep 5
  attente=$((attente + 5))
done
dire '%s   %s✓%s réseau disponible\n\n' "$EFF" "$T" "$Z"

# ── Audit : la règle du projet, même ici ─────────────────────────────────────
dire '   %s[1/2]%s Audit du matériel…\n' "$T" "$Z"
rapport="$JOURNAL/audit-$(date +%F-%H%M).md"
runuser -u "$UTILISATEUR" -- bash "$DEPOT/audit/audit.sh" >"$rapport" 2>&1
dire '   ✓ audit écrit dans %s\n\n' "$rapport"

# ── Installation du HUB ─────────────────────────────────────────────────────
# Les étapes sont comptées dans l'installateur lui-même (« etape "N. titre" ») : le
# total suit l'installateur sans qu'on ait à le recompter ici.
total=$(grep -cE '^[[:space:]]*etape "[0-9]+\. ' "$DEPOT/installer/hub-installer.sh")
dire '   %s[2/2]%s Installation du HUB (%s étapes)\n' "$T" "$Z" "${total:-?}"
dire '   %sDétail : %s%s\n\n' "$D" "$SORTIE_INSTALLATEUR" "$Z"

cd "$DEPOT" || exit 1
: >"$SORTIE_INSTALLATEUR"
debut=$SECONDS
SUDO_USER="$UTILISATEUR" DEBIAN_FRONTEND=noninteractive \
  bash installer/hub-installer.sh --pour-de-vrai </dev/null >>"$SORTIE_INSTALLATEUR" 2>&1 &
pid=$!

# Hors terminal, l'installateur n'écrit pas de couleurs : ses titres d'étape sont des
# lignes « ── N. titre ». On suit le fichier et on clôt chaque étape à l'arrivée de la
# suivante, avec sa durée ; la ligne courante montre le temps total écoulé. Le rang
# affiché est l'ordre d'exécution, pas le numéro du titre (10 et 11 passent après 13).
vues=0; titre=''; debut_etape=$debut
cloture() {
  dire '%s   %s✓%s %s %s(%s)%s\n' "$EFF" "$T" "$Z" "$titre" "$D" "$(duree $((SECONDS - debut_etape)))" "$Z"
}
suivre() {
  local lignes n i
  lignes=$(grep -E '^── [0-9]+\. ' "$SORTIE_INSTALLATEUR" | sed 's/^── //')
  n=$(printf '%s' "$lignes" | grep -c '')
  i=$vues
  while [ "$i" -lt "$n" ]; do
    i=$((i + 1))
    [ -n "$titre" ] && cloture
    titre=$(printf '%s\n' "$lignes" | sed -n "${i}p")
    debut_etape=$SECONDS
  done
  vues=$n
}
while kill -0 "$pid" 2>/dev/null; do
  suivre
  printf '%s   %s▸%s %s  %s[%d/%s · %s écoulées]%s' "$EFF" "$T" "$Z" "${titre:-démarrage de l’installateur…}" \
    "$D" "$vues" "${total:-?}" "$(duree $((SECONDS - debut)))" "$Z" >&3
  sleep 1
done
wait "$pid"
code=$?
suivre

if [ "$code" -eq 0 ]; then
  [ -n "$titre" ] && cloture
  cp "$rapport" "/home/$UTILISATEUR/audit-premier-demarrage.md" && chown "$UTILISATEUR:" "/home/$UTILISATEUR/audit-premier-demarrage.md"
  systemctl disable hub-premier-demarrage.service
  dire '\n   %s✓ HUB installé en %s.%s Redémarrage dans 10 secondes…\n' "$T" "$(duree $((SECONDS - debut)))" "$Z"
  sleep 10
  systemctl reboot
  exit 0
fi

# ── Échec ─────────────────────────────────────────────────────────────────────
# L'écran reste jusqu'à une touche ou au redémarrage : affiché 60 s puis remplacé par
# l'écran de connexion, un échec survenu pendant qu'on n'était pas devant la TV (20 à
# 40 min) passait inaperçu. Sans clavier, éteindre et rallumer relance la tentative.
# TimeoutStartSec du service borne encore l'attente : au-delà, GDM démarre.
printf 'échec, code %d\n' "$code"
entete echec
dire '   %s✗ L’installation du HUB a échoué%s (code %d, après %s, étape « %s »).\n\n' \
  "$R" "$Z" "$code" "$(duree $((SECONDS - debut)))" "${titre:-avant la première étape}"
printf '   %sDernières lignes :%s\n' "$D" "$Z" >&3
# Sans les codes de couleur, et coupées : une ligne d'apt de 300 caractères occuperait
# trois lignes d'écran et repousserait l'en-tête.
tail -n 8 "$SORTIE_INSTALLATEUR" | sed $'s/\e\\[[0-9;]*[A-Za-z]//g' | cut -c1-100 | sed 's/^/     /' >&3
dire '\n   Détail complet : %s\n' "$SORTIE_INSTALLATEUR"
dire '   L’installation sera retentée au prochain allumage.\n\n'
dire '   %sAppuyez sur une touche pour continuer vers Ubuntu, ou éteignez et rallumez pour réessayer.%s\n' "$A" "$Z"
# Les touches frappées pendant l'installation attendent dans le tampon du terminal :
# on les vide, sinon l'écran d'échec disparaîtrait aussitôt affiché.
while read -r -s -n 1 -t 1 _; do :; done
read -r -s -n 1 _
printf 'écran d’échec quitté par une touche\n'
exit 0
