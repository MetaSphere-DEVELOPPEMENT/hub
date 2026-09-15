#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  hub-installer.sh — installe et paramètre le HUB sur une Ubuntu 26.04 fraîche
# ═══════════════════════════════════════════════════════════════════════════════
#
# IL SIMULE PAR DÉFAUT. Sans `--pour-de-vrai`, il n'écrit rien, n'installe rien : il
# imprime ce qu'il ferait. La simulation parcourt le même chemin que l'exécution,
# si bien qu'elle montre aussi ce qui est déjà en place.
#
# IL AUDITE AVANT D'AGIR, et refuse si les conditions ne sont pas réunies. La règle
# du projet — l'audit précède toute installation — est appliquée par le code, pas
# laissée à la discipline de celui qui l'exécute.
#
# IL S'ARRÊTE SUR UN ÉCHEC. Chaque commande est vérifiée ; une étape qui échoue est
# abandonnée et comptée, et le démarrage automatique n'est pas basculé sur une
# session HUB incomplète. Le code de sortie dit s'il faut relancer.
#
# IL EST REJOUABLE. Chaque étape compare avant d'agir et dit « déjà fait ». On peut
# l'interrompre, corriger, relancer.
#
#   ./hub-installer.sh                      simule, n'écrit rien          (défaut)
#   sudo ./hub-installer.sh --pour-de-vrai  exécute
#   ... --sans-audit                        passe outre le refus (à ses risques)
#
# LA FORME INSTALLÉE (éprouvée en machine virtuelle, voir ARCHITECTURE.md) :
#   GDM ouvre seul la session « gnome-kiosk-script-wayland » ; elle exécute
#   ~/.local/bin/gnome-kiosk-script, une boucle menu → mode → menu. Kodi tourne
#   dans cette session ; le bureau Ubuntu est une autre session, choisie pour la
#   connexion suivante, et qui remet le HUB par défaut dès qu'elle s'ouvre.
#
# Ce qu'il NE fait pas, délibérément :
#   - aucun client de jeu, tant que « streamer depuis quoi ? » n'est pas tranché ;
#   - aucun réglage audio ou vidéo de Kodi : ils se mesurent devant la TV
#     (ARCHITECTURE.md, cases à cocher) ;
#   - il n'écrase jamais ~/.config/hub/reglages.json, qui appartient au menu.
#
# Codes de sortie : 0 tout est en place · 1 au moins une étape en échec ·
#                   2 argument invalide · 3 refusé par l'audit

set -uo pipefail

DEPOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"   # le dossier installer/
VERSION_ATTENDUE="26.04"
SESSION_HUB="gnome-kiosk-script-wayland"
JOURNAL="/var/log/hub-installer.log"
POUR_DE_VRAI=0
SANS_AUDIT=0

for arg in "$@"; do
  case "$arg" in
    --pour-de-vrai) POUR_DE_VRAI=1 ;;
    --sans-audit)   SANS_AUDIT=1 ;;
    -h|--help) sed -n '2,39p' "$0"; exit 0 ;;
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

ECHECS=0

# `faire` est le seul endroit qui exécute. En simulation il imprime et rend 0 : le
# reste du script s'écrit sans se demander dans quel mode il tourne.
#
# La version précédente jetait le code de retour : un apt-get en échec affichait ✓
# et la suite s'installait sur du vide. Ici un échec est affiché avec la fin du
# journal, compté, et rendu à l'appelant, qui abandonne son étape (`|| return 1`).
faire() {
  if [ "$POUR_DE_VRAI" != 1 ]; then
    printf '  %s[simulation]%s %s\n' "$GRIS" "$RAZ" "$*"
    return 0
  fi
  printf '  %s$ %s%s\n' "$GRIS" "$*" "$RAZ"
  printf '\n[%s] $ %s\n' "$(date '+%F %T')" "$*" >>"$JOURNAL"
  "$@" >>"$JOURNAL" 2>&1
  local code=$?
  if [ "$code" -ne 0 ]; then
    refus "échec (code $code) : $*"
    tail -n 8 "$JOURNAL" | sed 's/^/      /'
    ECHECS=$((ECHECS+1))
  fi
  return "$code"
}

# Une étape qui ne peut pas continuer sans avoir échoué par `faire` (un préalable
# manquant, un fichier du dépôt absent) passe par ici pour être comptée aussi.
echec() { refus "$1"; ECHECS=$((ECHECS+1)); return 1; }

paquet_present() {
  [ "$(dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null)" = installed ]
}

APT_A_JOUR=0
# Installe ce qui manque, et rien d'autre. `--no-install-recommends` est passé par
# l'appelant quand les recommandations ont un effet visible (voir Kodi).
installer_paquets() { # [options apt…] -- paquets…
  local options=() manquants=() p
  while [ $# -gt 0 ] && [ "$1" != -- ]; do options+=("$1"); shift; done
  shift
  for p in "$@"; do
    if paquet_present "$p"; then deja "$p"; else manquants+=("$p"); fi
  done
  [ ${#manquants[@]} -eq 0 ] && return 0
  if [ "$APT_A_JOUR" = 0 ]; then
    faire apt-get update -q || return 1
    APT_A_JOUR=1
  fi
  # Une Ubuntu fraîche lance ses mises à jour automatiques au premier démarrage et
  # tient le verrou d'apt plusieurs minutes : on attend au lieu d'échouer.
  faire env DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    -o DPkg::Lock::Timeout=900 "${options[@]}" "${manquants[@]}" || return 1
  ok "installé : ${manquants[*]}"
}

# Pose un fichier du dépôt s'il est absent ou différent. Pour les fichiers de
# l'utilisateur, les dossiers parents sont créés À SON NOM : `install -D` lancé en
# root laisserait un ~/.kodi ou un ~/.config/hub appartenant à root, et Kodi ou le
# menu ne pourraient plus y écrire.
poser() { # source destination mode [utilisateur]
  local src="$1" dst="$2" mode="$3" qui="${4:-}"
  [ -f "$src" ] || { echec "absent du dépôt : $src"; return 1; }
  if [ -f "$dst" ] && cmp -s "$src" "$dst" && [ "$(stat -c %a "$dst")" = "${mode#0}" ] &&
     { [ -z "$qui" ] || [ "$(stat -c %U "$dst")" = "$qui" ]; }; then
    deja "$dst"; return 0
  fi
  if [ -n "$qui" ]; then
    faire runuser -u "$qui" -- mkdir -p "$(dirname "$dst")" || return 1
    faire install -o "$qui" -g "$(id -gn "$qui")" -m "$mode" "$src" "$dst" || return 1
  else
    faire install -D -m "$mode" "$src" "$dst" || return 1
  fi
  ok "$dst"
}

# Remplace un répertoire entier par celui du dépôt, plus d'éventuels fichiers venus
# d'ailleurs (qrcode.js de la télécommande vit à côté de la page du menu). Copier
# fichier par fichier laisserait en place ce que le dépôt a supprimé ; on compare
# donc l'état voulu entier, puis on construit la nouvelle version à côté et on
# l'échange, pour ne jamais laisser un menu à moitié copié.
poser_repertoire() { # source destination [fichier-ajouté…]
  local src="$1" dst="$2" f voulu
  shift 2
  [ -d "$src" ] || { echec "absent du dépôt : $src"; return 1; }
  for f in "$@"; do [ -f "$f" ] || { echec "absent du dépôt : $f"; return 1; }; done
  voulu=$(mktemp -d) || { echec "mktemp impossible"; return 1; }
  cp -r "$src/." "$voulu/" && { [ $# -eq 0 ] || cp "$@" "$voulu/"; } &&
    find "$voulu" \( -name __pycache__ -o -name '*.pyc' \) -prune -exec rm -rf {} +
  if [ -d "$dst" ] && diff -r -q "$voulu" "$dst" >/dev/null 2>&1; then
    rm -rf "$voulu"; deja "$dst/"; return 0
  fi
  faire mkdir -p "$(dirname "$dst")" &&
  faire rm -rf "$dst.nouveau" &&
  faire cp -r "$voulu" "$dst.nouveau" &&
  faire chmod -R u=rwX,go=rX "$dst.nouveau" &&
  faire rm -rf "$dst" &&
  faire mv "$dst.nouveau" "$dst"
  local code=$?; rm -rf "$voulu"; [ "$code" -eq 0 ] || return 1
  ok "$dst/"
}

# ── En-tête ───────────────────────────────────────────────────────────────────
printf '\n%s  HUB — installation%s   %s\n' "$GRAS" "$RAZ" "$(date '+%F %Hh%M')"
if [ "$POUR_DE_VRAI" = 1 ]; then
  printf '  %sMODE RÉEL — la machine va être modifiée%s\n' "$ROUGE$GRAS" "$RAZ"
  [ "$(id -u)" -eq 0 ] || { refus "à lancer avec sudo en mode réel"; exit 1; }
  touch "$JOURNAL" 2>/dev/null || { refus "journal impossible à écrire : $JOURNAL"; exit 1; }
  ok "journal : $JOURNAL"
else
  printf '  %sSIMULATION — rien ne sera modifié. Ajoutez --pour-de-vrai (avec sudo) pour exécuter.%s\n' "$JAUNE" "$RAZ"
fi

# Le HUB s'installe pour la personne qui lance sudo. Lancé depuis un shell root sans
# sudo, il se serait installé pour root, que GDM ne connecte jamais.
UTILISATEUR="${SUDO_USER:-$USER}"
if [ -z "$UTILISATEUR" ] || [ "$UTILISATEUR" = root ] || ! id "$UTILISATEUR" >/dev/null 2>&1; then
  refus "utilisateur du HUB introuvable : lancez « sudo $0 » depuis son compte"
  exit 1
fi
MAISON="$(getent passwd "$UTILISATEUR" | cut -d: -f6)"
ok "installation pour $UTILISATEUR ($MAISON)"

# ── 1. L'audit, et le refus ───────────────────────────────────────────────────
etape "1. Audit préalable"

bloquants=0
avertissements=0

version=$( . /etc/os-release 2>/dev/null && echo "${VERSION_ID:-inconnue}" )
if [ "$version" = "$VERSION_ATTENDUE" ]; then
  ok "Ubuntu $version"
else
  refus "Ubuntu $version — ce script vise la $VERSION_ATTENDUE (sessions et écrans d'accueil en dépendent)"
  bloquants=$((bloquants+1))
fi

# Tout le HUB repose sur GDM : connexion automatique et choix de session.
if [ -f /etc/gdm3/custom.conf ]; then
  ok "GDM présent"
else
  refus "GDM absent (/etc/gdm3/custom.conf) — ce n'est pas une Ubuntu Desktop"
  bloquants=$((bloquants+1))
fi

# Un appareil de salon doit s'allumer comme une TV. Une phrase de passe au
# démarrage rend tout le reste inutile : c'est un refus, pas un avertissement.
if lsblk -o TYPE,MOUNTPOINTS 2>/dev/null | grep -Eq '^crypt[[:space:]]+/$'; then
  refus "la racine est chiffrée — le HUB ne pourra pas démarrer sans clavier"
  bloquants=$((bloquants+1))
else
  ok "racine non chiffrée : démarrage sans clavier possible"
fi

virt=$(systemd-detect-virt 2>/dev/null)
if [ -n "$virt" ] && [ "$virt" != none ]; then
  alerte "machine virtuelle ($virt) : les mesures matérielles ci-dessous ne décrivent pas le M720q"
  avertissements=$((avertissements+1))
fi

filaire=""
for i in /sys/class/net/*; do
  n=$(basename "$i"); [ "$n" = lo ] && continue
  [ -e "$i/device" ] || continue
  [ -d "$i/wireless" ] && continue
  [ "$(cat "$i/carrier" 2>/dev/null)" = 1 ] && { filaire="$n"; break; }
done
if [ -n "$filaire" ]; then
  # Le noyau écrit -1 quand le pilote ne connaît pas le débit (carte virtuelle,
  # lien pas encore négocié). L'afficher tel quel faisait lire « -1 Mb/s ».
  debit=$(cat "/sys/class/net/$filaire/speed" 2>/dev/null)
  if [[ "$debit" =~ ^[0-9]+$ ]] && [ "$debit" -gt 0 ]; then
    ok "Ethernet branché sur $filaire (lien négocié à $debit Mb/s — un débit annoncé, pas mesuré)"
  else
    ok "Ethernet branché sur $filaire (débit non annoncé par le pilote)"
  fi
else
  alerte "aucun Ethernet branché — le wifi USB 2,4 GHz ne tiendra pas le streaming"
  avertissements=$((avertissements+1))
fi

ecrans=0
for c in /sys/class/drm/card*-*; do
  [ "$(cat "$c/status" 2>/dev/null)" = connected ] || continue
  ecrans=$((ecrans+1))
  # « card1-HDMI-A-1 » → « HDMI-A-1 ». L'ancienne version retirait le préfixe du
  # chemin complet, où il ne figure pas en tête, et affichait « card1-Virtual-1 ».
  nom=$(basename "$c"); nom="${nom#card*-}"
  mode=$(head -n 1 "$c/modes" 2>/dev/null)
  ok "écran sur $nom — mode préféré ${mode:-non annoncé}"
done
if [ "$ecrans" -eq 0 ]; then
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
# audit.sh ne sait pas tout mesurer tant que ces outils manquent : le décodage
# matériel, le rendu OpenGL, le débit du lien filaire. On les pose en premier pour
# que le prochain passage de l'audit soit complet.
etape_mesure() {
  etape "2. Outils de mesure"
  installer_paquets -- vainfo mesa-utils ethtool
}

# Le menu affiche la version installée : c'est la première chose qu'on demande quand
# un soir « ça ne marche plus ». Elle vient du dépôt dont on installe, pas d'un
# numéro tenu à la main qu'on oublierait de changer.
poser_version() {
  local version_depot cible=/usr/local/share/hub/VERSION
  # safe.directory : lancé par sudo, git refuse un dépôt appartenant à l'utilisateur.
  version_depot=$(git -c safe.directory='*' -C "$DEPOT/.." describe --always --dirty 2>/dev/null)
  # Une Ubuntu neuve n'a pas git : la révision se lit alors directement dans .git
  # (sans l'indication « -dirty », que seul git sait calculer).
  if [ -z "$version_depot" ] && [ -f "$DEPOT/../.git/HEAD" ]; then
    local tete; tete=$(cat "$DEPOT/../.git/HEAD")
    case "$tete" in
      "ref: "*) version_depot=$(cat "$DEPOT/../.git/${tete#ref: }" 2>/dev/null ||
                  awk -v r="${tete#ref: }" '$2 == r {print $1}' "$DEPOT/../.git/packed-refs" 2>/dev/null) ;;
      *) version_depot="$tete" ;;
    esac
    version_depot="${version_depot:0:7}"
  fi
  if [ -z "$version_depot" ] && [ -f "$DEPOT/../VERSION" ]; then
    version_depot=$(head -n 1 "$DEPOT/../VERSION")
  fi
  if [ -z "$version_depot" ]; then
    alerte "version inconnue (ni dépôt git, ni fichier VERSION) : le menu n'en affichera pas"
    return 0
  fi
  if [ "$(cat "$cible" 2>/dev/null)" = "$version_depot" ]; then
    deja "$cible ($version_depot)"; return 0
  fi
  if [ "$POUR_DE_VRAI" = 1 ]; then
    printf '%s\n' "$version_depot" >"$cible.hub" &&
    faire install -D -m 0644 "$cible.hub" "$cible"
    local code=$?; rm -f "$cible.hub"; [ "$code" -eq 0 ] || return 1
  else
    faire "écrire $version_depot dans $cible"
  fi
  ok "$cible ($version_depot)"
}

# ── 3. Session et menu ────────────────────────────────────────────────────────
etape_session() {
  etape "3. Session HUB et menu"
  # gnome-kiosk-script-session fournit la session Wayland plein écran : Ubuntu 26.04
  # n'a plus de Xorg, /usr/share/xsessions ne sert plus à rien. Le menu est une page
  # web locale affichée par WebKitGTK depuis Python.
  installer_paquets -- gnome-kiosk-script-session python3-gi gir1.2-gtk-4.0 gir1.2-webkit-6.0 || return 1
  if [ "$POUR_DE_VRAI" = 1 ] && [ ! -f "/usr/share/wayland-sessions/$SESSION_HUB.desktop" ]; then
    echec "la session $SESSION_HUB n'est pas déclarée après installation du paquet"; return 1
  fi

  poser "$DEPOT/hub-menu.py"              /usr/local/bin/hub-menu              0755 || return 1
  # qrcode.js appartient à la télécommande mais le menu le charge : il est posé avec
  # la page, sinon chaque relance supprimerait l'autre moitié.
  local ajouts=()
  [ -f "$DEPOT/telecommande/qrcode.js" ] && ajouts+=("$DEPOT/telecommande/qrcode.js")
  poser_repertoire "$DEPOT/menu" /usr/local/share/hub/menu "${ajouts[@]}" || return 1
  poser_version || return 1
  poser "$DEPOT/hub-vers-bureau"          /usr/local/bin/hub-vers-bureau       0755 || return 1
  poser "$DEPOT/hub-session-par-defaut"   /usr/local/bin/hub-session-par-defaut 0755 || return 1
  poser "$DEPOT/hub-session-par-defaut.desktop" /etc/xdg/autostart/hub-session-par-defaut.desktop 0644 || return 1
  poser "$DEPOT/retour-au-hub.desktop"    /usr/share/applications/retour-au-hub.desktop 0644 || return 1
  # Le script que gnome-kiosk-script-session exécute. S'il manque, la session en crée
  # un d'exemple et ouvre un éditeur de texte sur la TV.
  poser "$DEPOT/gnome-kiosk-script" "$MAISON/.local/bin/gnome-kiosk-script" 0755 "$UTILISATEUR" || return 1

  # Les réglages appartiennent au menu, qui les écrit. On prépare leur dossier au nom
  # de l'utilisateur, et on ne touche jamais au fichier : le relancer après un
  # changement de langue ou de fond ne doit rien défaire.
  if [ -f "$MAISON/.config/hub/reglages.json" ]; then
    deja "$MAISON/.config/hub/reglages.json conservé tel quel"
  elif [ -d "$MAISON/.config/hub" ]; then
    deja "$MAISON/.config/hub/ (le menu y écrira ses réglages)"
  else
    faire runuser -u "$UTILISATEUR" -- mkdir -p "$MAISON/.config/hub" || return 1
    ok "$MAISON/.config/hub/ (le menu y écrira ses réglages)"
  fi

  # L'installateur précédent déclarait une session X11 « hub » : sur 26.04 elle
  # n'apparaît nulle part, mais elle induirait le prochain lecteur en erreur.
  if [ -f /usr/share/xsessions/hub.desktop ]; then
    faire rm -f /usr/share/xsessions/hub.desktop || return 1
    ok "ancienne session X11 retirée"
  fi
}

# ── 4. Écrans d'accueil d'Ubuntu ──────────────────────────────────────────────
etape_accueil() {
  etape "4. Écrans d'accueil d'Ubuntu"
  # gnome-initial-setup s'ouvre à la première connexion (« Bienvenue ») puis après
  # chaque montée de version (« Help Improve Ubuntu », service
  # gnome-initial-setup-upgrade-login). Dans la session kiosque, il se pose PAR-DESSUS
  # le menu et attend une souris. Vu en machine virtuelle le 13 septembre 2026. Le
  # second marqueur porte le numéro de version : on le dérive d'os-release pour ne pas
  # revoir l'écran à la 28.04.
  local f
  for f in "$MAISON/.config/gnome-initial-setup-done" \
           "$MAISON/.config/gnome-initial-setup/upgrade-$version-done"; do
    if [ -f "$f" ]; then
      deja "$f"
    else
      faire runuser -u "$UTILISATEUR" -- mkdir -p "$(dirname "$f")" &&
      faire runuser -u "$UTILISATEUR" -- sh -c 'echo yes > "$1"' marqueur "$f" || return 1
      ok "$f"
    fi
  done
}

# ── 5. Mode TV : Kodi ─────────────────────────────────────────────────────────
etape_kodi() {
  etape "5. Mode TV — Kodi"
  # Sans les recommandations. Le paquet kodi recommande kodi-visualization-spectrum ;
  # installé par apt, cet add-on n'est pas dans le manifeste de Kodi, qui l'inscrit
  # donc « désactivé » et ouvre au premier lancement « Disabled add-ons — enable
  # Spectrum? » (CApplication::ConfigureAndEnableAddons, Kodi 21.3). Sur une TV, cette
  # question sans réponse évidente bloque la télécommande. Une visualisation musicale
  # n'a rien à faire dans le HUB ; le dépôt officiel, lui, est gardé explicitement.
  installer_paquets --no-install-recommends -- kodi kodi-repository-kodi || return 1
  if paquet_present kodi-visualization-spectrum; then
    alerte "kodi-visualization-spectrum est installé : Kodi demandera une fois s'il faut l'activer"
    alerte "  (sudo apt-get remove kodi-visualization-spectrum pour ne jamais voir la question)"
  fi

  # Kodi n'a pas besoin de session à lui : il tourne dans la session HUB, lancé par
  # gnome-kiosk-script. Le quitter rend la main au menu. Ce raccourci l'y ramène
  # d'une touche (Accueil ou F12).
  poser "$DEPOT/kodi/keymaps/hub.xml" "$MAISON/.kodi/userdata/keymaps/hub.xml" 0644 "$UTILISATEUR" || return 1

  # « Continuer à regarder » : hub-kodi-lire lance Kodi puis lui demande la reprise
  # par JSON-RPC (localhost:9090). Kodi n'écoute que si le contrôle par les programmes
  # de CETTE machine est autorisé ; celui depuis le réseau reste fermé, rien d'autre
  # que le HUB n'a à piloter Kodi.
  poser "$DEPOT/hub-kodi-lire" /usr/local/bin/hub-kodi-lire 0755 || return 1
  local reglages="$MAISON/.kodi/userdata/guisettings.xml"
  local voulus=(services.esenabled=true services.esallinterfaces=false)
  if python3 "$DEPOT/kodi/regler-guisettings.py" verifier "$reglages" "${voulus[@]}" 2>/dev/null; then
    deja "Kodi : contrôle par les programmes locaux autorisé, réseau fermé"
  elif pgrep -u "$UTILISATEUR" -x kodi.bin >/dev/null 2>&1; then
    # Kodi réécrit guisettings.xml en quittant : modifié maintenant, il serait perdu.
    echec "Kodi tourne : quittez-le puis relancez, sinon il écraserait ce réglage en quittant"
    return 1
  else
    faire runuser -u "$UTILISATEUR" -- mkdir -p "$(dirname "$reglages")" &&
    faire runuser -u "$UTILISATEUR" -- python3 - appliquer "$reglages" "${voulus[@]}" \
      <"$DEPOT/kodi/regler-guisettings.py" || return 1
    ok "Kodi : contrôle par les programmes locaux autorisé (JSON-RPC sur localhost:9090), réseau fermé"
  fi
}

# ── 6. Télécommande téléphone ─────────────────────────────────────────────────
activer_unite_globale() { # nom
  if [ "$(systemctl --global is-enabled "$1" 2>/dev/null)" = enabled ]; then
    deja "$1 activé pour les sessions"
  else
    faire systemctl --global enable "$1" || return 1
    ok "$1 activé à l'ouverture des sessions"
  fi
}

etape_telecommande() {
  etape "6. Télécommande téléphone"
  local tel="$DEPOT/telecommande" lib=/usr/local/lib/hub
  if [ ! -f "$tel/hub_telecommande.py" ] || [ ! -f "$tel/hub-telecommande.service" ]; then
    deja "aucune télécommande dans le dépôt ($tel) — étape sautée"
    return 0
  fi
  # Sans Bluetooth ni CEC, c'est le seul moyen de piloter le HUB depuis le canapé :
  # elle passe avant la bascule du démarrage, et son échec l'empêche.
  # page.html doit rester à côté du programme : il la lit là (lien résolu).
  poser "$tel/hub_telecommande.py" "$lib/telecommande/hub_telecommande.py" 0755 || return 1
  poser "$tel/page.html"           "$lib/telecommande/page.html"           0644 || return 1
  if [ -f "$tel/README.md" ]; then
    poser "$tel/README.md" "$lib/telecommande/README.md" 0644 || return 1
  fi
  # La télécommande pilote Kodi et le bureau avec la logique de la voix ; elle la
  # cherche ici, que la commande vocale soit installée ou non.
  if [ -f "$DEPOT/voix/hub_voix_logique.py" ]; then
    poser "$DEPOT/voix/hub_voix_logique.py" "$lib/voix/hub_voix_logique.py" 0644 || return 1
  else
    alerte "voix/hub_voix_logique.py absent : la télécommande ne pilotera ni Kodi ni le bureau"
  fi
  if [ "$(readlink /usr/local/bin/hub-telecommande 2>/dev/null)" = "$lib/telecommande/hub_telecommande.py" ]; then
    deja "/usr/local/bin/hub-telecommande"
  else
    faire ln -sfn "$lib/telecommande/hub_telecommande.py" /usr/local/bin/hub-telecommande || return 1
    ok "/usr/local/bin/hub-telecommande"
  fi
  poser "$tel/hub-telecommande.service" /usr/local/lib/systemd/user/hub-telecommande.service 0644 || return 1
  activer_unite_globale hub-telecommande.service || return 1

  # ufw est inactif sur une Ubuntu neuve. S'il a été activé, on ouvre le port au seul
  # réseau de l'interface qui porte la route par défaut : la télécommande n'a rien à
  # faire joignable depuis un VPN ou une interface de conteneur.
  if command -v ufw >/dev/null && LC_ALL=C ufw status 2>/dev/null | grep -q '^Status: active'; then
    local iface reseau
    iface=$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')
    reseau=$(ip -4 -o addr show dev "${iface:-lo}" 2>/dev/null | awk '{print $4; exit}' |
             python3 -c 'import ipaddress,sys; print(ipaddress.ip_interface(sys.stdin.read().strip()).network)' 2>/dev/null)
    if [ -z "$reseau" ]; then
      alerte "ufw actif mais réseau local introuvable : port 8790 non ouvert, la télécommande sera bloquée"
    elif LC_ALL=C ufw status 2>/dev/null | grep -Eq "^8790/tcp[[:space:]]+ALLOW[[:space:]]+$reseau\b"; then
      deja "ufw : 8790/tcp ouvert à $reseau"
    else
      faire ufw allow from "$reseau" to any port 8790 proto tcp || return 1
      ok "ufw : 8790/tcp ouvert à $reseau seulement"
    fi
  fi
}

# ── 7. Démarrage automatique sur le HUB ───────────────────────────────────────
etape_demarrage() {
  etape "7. Démarrage automatique sur le HUB"
  # Basculer le démarrage sur une session dont une pièce manque, c'est allumer la TV
  # sur un écran noir sans clavier pour réparer. On ne le fait que sur un parcours
  # sans échec.
  if [ "$ECHECS" -gt 0 ]; then
    echec "$ECHECS échec(s) plus haut : le démarrage n'est pas basculé sur une session incomplète"
    return 1
  fi

  # La session se choisit dans AccountsService, pas dans un fichier qu'on écrirait
  # soi-même : c'est lui que GDM consulte, et que hub-vers-bureau modifie ensuite.
  local compte actuelle
  compte=$(busctl call org.freedesktop.Accounts /org/freedesktop/Accounts \
             org.freedesktop.Accounts FindUserByName s "$UTILISATEUR" 2>/dev/null |
           awk '{gsub(/"/, "", $2); print $2}')
  actuelle=$(busctl get-property org.freedesktop.Accounts "${compte:-/}" \
               org.freedesktop.Accounts.User Session 2>/dev/null | awk '{gsub(/"/, "", $2); print $2}')
  if [ -z "$compte" ]; then
    echec "AccountsService ne connaît pas $UTILISATEUR"; return 1
  elif [ "$actuelle" = "$SESSION_HUB" ]; then
    deja "session par défaut : $SESSION_HUB"
  else
    faire busctl call org.freedesktop.Accounts "$compte" org.freedesktop.Accounts.User \
      SetSession s "$SESSION_HUB" || return 1
    ok "session par défaut : $SESSION_HUB (était : ${actuelle:-aucune})"
  fi

  # GDM : connexion automatique au démarrage ET connexion temporisée. Sans la
  # seconde, fermer le bureau Ubuntu laisse l'écran de connexion : la connexion
  # automatique ne vaut qu'une fois par démarrage. Vu en machine virtuelle.
  local conf=/etc/gdm3/custom.conf
  local cles=(AutomaticLoginEnable=true "AutomaticLogin=$UTILISATEUR"
              TimedLoginEnable=true "TimedLogin=$UTILISATEUR" TimedLoginDelay=1)
  local nouveau
  nouveau=$(awk -v bloc="$(printf '%s\n' "${cles[@]}")" '
    BEGIN { n = split(bloc, lignes, "\n"); for (i = 1; i <= n; i++) if (lignes[i] != "") {
              split(lignes[i], kv, "="); cle[kv[1]] = 1; ordre[++m] = lignes[i] } }
    function poser_bloc() { for (i = 1; i <= m; i++) print ordre[i]; pose = 1 }
    /^[[:space:]]*\[/ { section = $0; gsub(/[[:space:]]/, "", section)
                        print; if (section == "[daemon]") poser_bloc(); next }
    section == "[daemon]" && match($0, /^[[:space:]]*[A-Za-z]+[[:space:]]*=/) {
      k = substr($0, RSTART, RLENGTH); gsub(/[[:space:]=]/, "", k); if (k in cle) next }
    { print }
    END { if (!pose) { print ""; print "[daemon]"; poser_bloc() } }
  ' "$conf")
  if [ "$nouveau" = "$(cat "$conf")" ]; then
    deja "GDM : connexion automatique et temporisée pour $UTILISATEUR"
  else
    # Ce fichier appartient au système : on garde l'original une fois pour toutes.
    if [ ! -f "$conf.avant-hub" ]; then
      faire cp -p "$conf" "$conf.avant-hub" || return 1
      ok "sauvegarde : $conf.avant-hub"
    fi
    if [ "$POUR_DE_VRAI" = 1 ]; then
      printf '%s\n' "$nouveau" >"$conf.hub" && faire install -m 0644 "$conf.hub" "$conf"
      local code=$?; rm -f "$conf.hub"; [ "$code" -eq 0 ] || return 1
    else
      faire "écrire dans [daemon] de $conf :" "${cles[@]}"
    fi
    ok "GDM : connexion automatique et temporisée pour $UTILISATEUR"
  fi
}

# ── 8. Commande vocale (si elle est livrée) ──────────────────────────────────
etape_voix() {
  etape "8. Commande vocale (si elle est livrée)"
  local voix="$DEPOT/voix" opt=/opt/hub-voix f
  if [ ! -f "$voix/hub-voix.py" ] || [ ! -f "$voix/hub-voix.service" ]; then
    deja "aucun service vocal complet dans le dépôt ($voix) — étape sautée"
    return 0
  fi
  # La disposition est celle qu'attend l'unité livrée (ExecStart dans /opt/hub-voix,
  # venv à côté) : l'installateur s'y plie plutôt que de la réécrire, pour qu'un
  # seul endroit décide où vit le service.
  installer_paquets -- python3-venv pipewire-bin curl unzip || return 1
  for f in hub-voix.py hub_voix_logique.py; do
    poser "$voix/$f" "$opt/$f" 0755 || return 1
  done
  # Vosk n'est pas empaqueté par Ubuntu : un venv isolé, plutôt qu'un pip lancé en
  # root sur le Python du système, que la prochaine mise à jour d'apt casserait.
  if [ -x "$opt/venv/bin/python" ] && "$opt/venv/bin/python" -c 'import vosk' 2>/dev/null; then
    deja "$opt/venv (vosk)"
  else
    faire python3 -m venv "$opt/venv" &&
    faire "$opt/venv/bin/pip" install -q vosk || return 1
    ok "$opt/venv (vosk)"
  fi
  if [ -f "$voix/telecharger-modele.sh" ]; then
    # Le script vérifie les empreintes et saute ce qui est déjà là : rejouable.
    faire sh "$voix/telecharger-modele.sh" "$opt/modeles" || return 1
    ok "modèles Vosk dans $opt/modeles"
  else
    alerte "telecharger-modele.sh absent : modèles Vosk à poser à la main dans $opt/modeles"
  fi
  # Unité UTILISATEUR (micro de PipeWire, socket du menu dans $XDG_RUNTIME_DIR) ;
  # /etc/systemd/user la rend disponible à toute session, activée par --global.
  poser "$voix/hub-voix.service" /etc/systemd/user/hub-voix.service 0644 || return 1
  activer_unite_globale hub-voix.service
}

etape_mesure
etape_session
etape_accueil
etape_kodi
etape_telecommande
etape_demarrage
# La voix vient après la bascule du démarrage : elle télécharge (pip, modèles) et un
# réseau capricieux ne doit pas priver le salon de son HUB. Son échec reste compté.
etape_voix

# ── Fin ───────────────────────────────────────────────────────────────────────
etape "Ce qui reste à faire à la main"
cat <<'RESTE'
  [ ] trancher avec quoi on pilote : clé Bluetooth, adaptateur USB-CEC, clavier
  [ ] trancher d'où vient le streaming de jeu, puis relancer pour le mode Gaming
  [ ] relancer audit/audit.sh une fois la TV branchée, pour les trois mesures
      qui n'existent qu'à ce moment-là
  [ ] régler l'audio de Kodi après mesure (ARCHITECTURE.md, section Audio)
RESTE
printf '\n'
if [ "$POUR_DE_VRAI" != 1 ]; then
  printf '  %sRien n%sa été modifié.%s\n\n' "$JAUNE" "'" "$RAZ"
  exit 0
fi
if [ "$ECHECS" -gt 0 ]; then
  printf '  %s%d échec(s).%s Détail dans %s ; corrigez puis relancez, le script reprend où il en est.\n\n' \
    "$ROUGE$GRAS" "$ECHECS" "$RAZ" "$JOURNAL"
  exit 1
fi
printf '  %sHUB en place.%s Redémarrez pour arriver sur le menu.\n\n' "$VERT$GRAS" "$RAZ"
