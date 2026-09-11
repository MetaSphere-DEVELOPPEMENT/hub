#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  hub-installer.sh — installe et paramètre le HUB sur une Ubuntu fraîche
# ═══════════════════════════════════════════════════════════════════════════════
#
# IL SIMULE PAR DÉFAUT. Sans `--pour-de-vrai`, il n'écrit rien, n'installe rien,
# ne touche à aucun fichier : il imprime exactement ce qu'il ferait. Ce n'est pas
# de la prudence de façade — ce script n'a jamais été exécuté en conditions
# réelles au moment où il a été écrit, et un script non éprouvé qui s'exécute en
# root sur une machine neuve est un mauvais marché.
#
# IL AUDITE AVANT D'AGIR, et refuse si les conditions ne sont pas réunies. La
# règle du projet — l'audit précède toute installation — est appliquée par le
# code, pas laissée à la discipline de celui qui l'exécute.
#
# IL EST REJOUABLE. Chaque étape vérifie avant de faire. Le relancer sur une
# machine déjà installée ne casse rien et ne réinstalle rien : il dit « déjà fait »
# et passe. On peut donc l'interrompre et le reprendre.
#
#   ./hub-installer.sh                 simule, n'écrit rien           (défaut)
#   ./hub-installer.sh --pour-de-vrai  exécute
#   ./hub-installer.sh --sans-audit    passe outre le refus (à ses risques)
#
# Ce qu'il NE fait pas, et c'est délibéré :
#   - il n'installe aucun client de jeu, tant que « streamer depuis quoi ? » n'est
#     pas tranché ;
#   - il ne dessine pas le menu du HUB, tant que « avec quoi pilote-t-on ? » n'est
#     pas tranché. Il pose une session HUB minimale qui liste les modes et suffit
#     à prouver que l'aller-retour fonctionne.

set -uo pipefail

VERSION_ATTENDUE="26.04"
UTILISATEUR="${SUDO_USER:-$USER}"
JOURNAL="/var/log/hub-installer.log"
POUR_DE_VRAI=0
SANS_AUDIT=0

for arg in "$@"; do
  case "$arg" in
    --pour-de-vrai) POUR_DE_VRAI=1 ;;
    --sans-audit)   SANS_AUDIT=1 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "argument inconnu : $arg" >&2; exit 2 ;;
  esac
done

# ── Affichage ─────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  VERT=$'\e[32m'; ROUGE=$'\e[31m'; JAUNE=$'\e[33m'; GRIS=$'\e[90m'; GRAS=$'\e[1m'; RAZ=$'\e[0m'
else
  VERT=''; ROUGE=''; JAUNE=''; GRIS=''; GRAS=''; RAZ=''
fi
etape()  { printf '\n%s── %s%s\n' "$GRAS" "$1" "$RAZ"; }
ok()     { printf '  %s✓%s %s\n' "$VERT" "$RAZ" "$1"; }
deja()   { printf '  %s·%s %s %s(déjà fait)%s\n' "$GRIS" "$RAZ" "$1" "$GRIS" "$RAZ"; }
alerte() { printf '  %s!%s %s\n' "$JAUNE" "$RAZ" "$1"; }
refus()  { printf '  %s✗%s %s\n' "$ROUGE" "$RAZ" "$1"; }

# `faire` est le seul endroit qui exécute. En simulation il imprime et rend 0 :
# tout le reste du script s'écrit donc sans jamais se demander dans quel mode il
# tourne, et la simulation parcourt exactement le même chemin que l'exécution.
faire() {
  if [ "$POUR_DE_VRAI" = 1 ]; then
    printf '  %s$ %s%s\n' "$GRIS" "$*" "$RAZ"
    "$@" >>"$JOURNAL" 2>&1
  else
    printf '  %s[simulation]%s %s\n' "$GRIS" "$RAZ" "$*"
  fi
}

# Écrire un fichier passe aussi par une seule porte, pour la même raison.
ecrire() { # $1 = chemin, entrée standard = contenu
  local cible="$1"
  if [ "$POUR_DE_VRAI" = 1 ]; then
    install -D /dev/stdin "$cible"
  else
    printf '  %s[simulation]%s écrirait %s :\n' "$GRIS" "$RAZ" "$cible"
    sed 's/^/      /'
  fi
}

present() { command -v "$1" >/dev/null 2>&1; }

# ── En-tête ───────────────────────────────────────────────────────────────────
printf '\n%s  HUB — installation%s   %s\n' "$GRAS" "$RAZ" "$(date '+%F %Hh%M')"
if [ "$POUR_DE_VRAI" = 1 ]; then
  printf '  %sMODE RÉEL — la machine va être modifiée%s\n' "$ROUGE$GRAS" "$RAZ"
  [ "$(id -u)" -ne 0 ] && { refus "à lancer avec sudo en mode réel"; exit 1; }
  touch "$JOURNAL" 2>/dev/null && ok "journal : $JOURNAL"
else
  printf '  %sSIMULATION — rien ne sera modifié. Ajoutez --pour-de-vrai pour exécuter.%s\n' "$JAUNE" "$RAZ"
fi

# ── 1. L'audit, et le refus ───────────────────────────────────────────────────
etape "1. Audit préalable"

bloquants=0
avertissements=0

version=$( . /etc/os-release 2>/dev/null && echo "${VERSION_ID:-inconnue}" )
if [ "$version" = "$VERSION_ATTENDUE" ]; then
  ok "Ubuntu $version"
else
  refus "Ubuntu $version — ce script vise la $VERSION_ATTENDUE"
  bloquants=$((bloquants+1))
fi

# Un appareil de salon doit s'allumer comme une TV. Une phrase de passe au
# démarrage rend tout le reste inutile : c'est un refus, pas un avertissement.
if lsblk -o TYPE,MOUNTPOINT 2>/dev/null | grep -q '^crypt.*/$'; then
  refus "la racine est chiffrée — le HUB ne pourra pas démarrer sans clavier"
  bloquants=$((bloquants+1))
else
  ok "racine non chiffrée : démarrage sans clavier possible"
fi

filaire=""
for i in /sys/class/net/*; do
  n=$(basename "$i"); [ "$n" = lo ] && continue
  [ -e "$i/device" ] || continue
  [ -d "$i/wireless" ] && continue
  [ "$(cat "$i/carrier" 2>/dev/null)" = 1 ] && filaire="$n"
done
if [ -n "$filaire" ]; then
  ok "Ethernet branché sur $filaire ($(cat /sys/class/net/$filaire/speed 2>/dev/null || echo '?') Mb/s)"
else
  alerte "aucun Ethernet branché — le wifi USB 2,4 GHz ne tiendra pas le streaming"
  avertissements=$((avertissements+1))
fi

if ls /sys/class/drm/card*-*/status >/dev/null 2>&1 &&
   grep -qx connected /sys/class/drm/card*-*/status 2>/dev/null; then
  for c in /sys/class/drm/card*-*; do
    [ "$(cat "$c/status" 2>/dev/null)" = connected ] &&
      ok "écran sur $(basename "${c#card?-}") — mode préféré $(head -1 "$c/modes" 2>/dev/null)"
  done
else
  alerte "aucun écran détecté — résolution et audio HDMI resteront non mesurés"
  avertissements=$((avertissements+1))
fi

if [ -n "$(ls /sys/class/bluetooth/ 2>/dev/null)" ]; then
  ok "contrôleur Bluetooth présent"
else
  alerte "aucun Bluetooth — ni manette, ni télécommande, ni casque sans fil"
  avertissements=$((avertissements+1))
fi

if ls /dev/cec* >/dev/null 2>&1; then
  ok "HDMI-CEC présent : la télécommande de la TV pourra piloter le HUB"
else
  alerte "aucun HDMI-CEC — la télécommande de la TV ne pilotera rien"
  avertissements=$((avertissements+1))
fi

printf '\n  %d bloquant(s), %d avertissement(s)\n' "$bloquants" "$avertissements"
if [ "$bloquants" -gt 0 ] && [ "$SANS_AUDIT" = 0 ]; then
  printf '\n  %sInstallation refusée.%s Corrigez les points bloquants, ou relancez avec\n' "$ROUGE$GRAS" "$RAZ"
  printf '  --sans-audit si vous savez ce que vous faites.\n\n'
  exit 3
fi
[ "$bloquants" -gt 0 ] && alerte "points bloquants ignorés sur demande (--sans-audit)"

# ── 2. De quoi finir l'audit ──────────────────────────────────────────────────
# L'audit lui-même ne sait pas tout mesurer tant que ces outils manquent : le
# décodage matériel, le rendu OpenGL, le débit du lien filaire. On les pose en
# premier pour que le prochain passage de audit.sh soit complet.
etape "2. Outils de mesure"
mesure_manquants=()
for p in vainfo mesa-utils ethtool; do
  case "$p" in
    mesa-utils) present glxinfo && { deja "$p"; continue; } ;;
    *)          present "$p"    && { deja "$p"; continue; } ;;
  esac
  mesure_manquants+=("$p")
done
if [ ${#mesure_manquants[@]} -gt 0 ]; then
  faire apt-get update -qq
  faire apt-get install -y "${mesure_manquants[@]}"
  ok "à installer : ${mesure_manquants[*]}"
fi

# ── 3. Mode TV ────────────────────────────────────────────────────────────────
etape "3. Mode TV — Kodi"
if present kodi; then
  deja "kodi"
else
  faire apt-get install -y kodi
  ok "kodi"
fi
# `kodi-standalone` ouvre sa propre session : Kodi devient un mode à part entière
# et non une fenêtre posée sur un bureau. Quitter Kodi termine la session, ce qui
# est précisément le « retour au HUB » qu'on veut, sans rien écrire pour l'obtenir.
if [ -f /usr/share/xsessions/kodi.desktop ] || [ -f /usr/share/wayland-sessions/kodi.desktop ]; then
  deja "session Kodi déclarée"
else
  alerte "le paquet kodi ne déclare pas de session — à vérifier après installation"
fi

# ── 4. La session HUB ─────────────────────────────────────────────────────────
etape "4. Session HUB"

# Le menu lui-même reste volontairement rudimentaire : son dessin dépend de ce
# avec quoi on pilotera (manette, télécommande CEC, clavier), qui n'est pas
# tranché. Ce qui est posé ici suffit à prouver l'aller-retour entre les modes,
# et c'est ce qu'un prototype doit prouver.
ecrire /usr/local/bin/hub-menu <<'MENU'
#!/usr/bin/env bash
# Menu d'accueil du HUB. Rudimentaire par choix : le dessin définitif dépend du
# périphérique de pilotage, qui n'est pas arrêté. Lancer un mode, c'est ouvrir
# une session ; en sortir ramène ici.
set -uo pipefail
while true; do
  clear
  cat <<'ECRAN'

    H U B

    1   TV        Kodi
    2   Gaming    (non configuré — source de streaming à décider)
    3   Desktop   Ubuntu
    q   Éteindre

ECRAN
  read -rsn1 -p "  choix : " c; echo
  case "$c" in
    1) kodi-standalone ;;
    2) echo "  Le mode Gaming n'est pas encore configuré."; read -rsn1 ;;
    3) exec gnome-session ;;
    q) systemctl poweroff ;;
  esac
done
MENU
faire chmod +x /usr/local/bin/hub-menu

ecrire /usr/share/xsessions/hub.desktop <<'SESSION'
[Desktop Entry]
Name=HUB
Comment=Menu d'accueil du HUB
Exec=/usr/local/bin/hub-menu
Type=Application
SESSION
ok "session HUB déclarée"

# ── 5. Démarrage automatique ──────────────────────────────────────────────────
etape "5. Démarrage automatique sur le HUB"
# Un appareil de salon s'allume sur son menu, pas sur un écran de connexion.
# GDM lit ce fichier ; on n'y touche que ces trois lignes et on garde une copie
# de l'original, parce que ce fichier appartient au système et pas à ce script.
if [ -f /etc/gdm3/custom.conf ]; then
  if grep -q '^AutomaticLoginEnable=true' /etc/gdm3/custom.conf 2>/dev/null; then
    deja "connexion automatique"
  else
    faire cp -n /etc/gdm3/custom.conf /etc/gdm3/custom.conf.avant-hub
    ok "sauvegarde : /etc/gdm3/custom.conf.avant-hub"
    alerte "à ajouter dans [daemon] : AutomaticLoginEnable=true / AutomaticLogin=$UTILISATEUR"
    alerte "et dans AccountsService : XSession=hub"
  fi
else
  alerte "gdm3 absent — démarrage automatique non configuré"
fi

# ── Fin ───────────────────────────────────────────────────────────────────────
etape "Ce qui reste à faire à la main"
cat <<'RESTE'
  [ ] trancher avec quoi on pilote : clé Bluetooth, adaptateur USB-CEC, clavier
  [ ] trancher d'où vient le streaming de jeu, puis relancer pour le mode Gaming
  [ ] relancer audit/audit.sh une fois la TV branchée, pour les trois mesures
      qui n'existent qu'à ce moment-là
RESTE
printf '\n'
[ "$POUR_DE_VRAI" = 1 ] || printf '  %sRien n%sa été modifié.%s\n\n' "$JAUNE" "'" "$RAZ"
