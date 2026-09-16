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
#   - aucun client de jeu natif (Steam, Moonlight, appli GeForce NOW) : le mode Jeux
#     propose les services en nuage dans Chrome, et les applis si on les installe ;
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
# Source par défaut de la mise à jour depuis le menu : le dépôt public du projet, lu
# en HTTPS sans compte. Écrite seulement si /etc/hub/mise-a-jour.json n'existe pas.
# Qu'il soit public ne suffit pas à lui faire confiance : seuls les commits signés
# par /etc/hub/signataires-autorises sont installés (étape 9).
SOURCE_MISE_A_JOUR='{"source": "https://github.com/MetaSphere-DEVELOPPEMENT/hub.git", "branche": "master"}'
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

# Le HUB s'installe pour la personne qui lance sudo. hub-mise-a-jour, qui relance ce
# script depuis un service système (root, sans terminal, sans $USER), passe SUDO_USER
# lui-même. Lancé depuis un shell root sans
# sudo, il se serait installé pour root, que GDM ne connecte jamais.
UTILISATEUR="${SUDO_USER:-${USER:-}}"
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
  # hub-web à côté de hub-menu : le menu l'importe pour savoir quelles tuiles proposer,
  # et gnome-kiosk-script le lance pour le mode « web ».
  poser "$DEPOT/hub-web"                  /usr/local/bin/hub-web               0755 || return 1
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
  # Le HTTPS local (dictée) fabrique son autorité avec openssl, présent sur toute
  # Ubuntu ; sans lui la télécommande reste en http, sans micro.
  command -v openssl >/dev/null ||
    alerte "openssl absent : télécommande en http seul, dictée depuis le téléphone indisponible"
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
    # 8790 : la page http (QR code) ; 8791 : son double HTTPS, pour la dictée.
    local port
    for port in 8790 8791; do
      if [ -z "$reseau" ]; then
        alerte "ufw actif mais réseau local introuvable : port $port non ouvert, la télécommande sera bloquée"
      elif LC_ALL=C ufw status 2>/dev/null | grep -Eq "^$port/tcp[[:space:]]+ALLOW[[:space:]]+$reseau\b"; then
        deja "ufw : $port/tcp ouvert à $reseau"
      else
        faire ufw allow from "$reseau" to any port "$port" proto tcp || return 1
        ok "ufw : $port/tcp ouvert à $reseau seulement"
      fi
    done
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

# ── 8. Habillage : hub-theme et démarrage graphique ───────────────────────────
etape_habillage() {
  etape "8. Habillage aux couleurs du profil"
  local theme="$DEPOT/theme/hub-theme"
  if [ ! -f "$theme" ]; then
    deja "aucun hub-theme dans le dépôt — étape sautée"
    return 0
  fi
  # Les scripts de session l'appellent avant Kodi et le bureau ; absent, ils passent.
  poser "$theme" /usr/local/bin/hub-theme 0755 || return 1

  # Plymouth : l'écran de démarrage, aux couleurs du profil AU MOMENT de l'installation
  # (il s'affiche avant toute session). Généré en tant que l'utilisateur, pour lire
  # SON profil. On compare au thème en place pour ne reconstruire l'initramfs —
  # une à deux minutes — que si quelque chose change.
  local cible=/usr/share/plymouth/themes/hub genere
  genere=$(mktemp -d) || { echec "mktemp impossible"; return 1; }
  chmod 0755 "$genere"
  [ "$(id -u)" -eq 0 ] && chown "$UTILISATEUR" "$genere"
  local en_utilisateur=()
  [ "$(id -u)" -eq 0 ] && en_utilisateur=(runuser -u "$UTILISATEUR" --)
  if ! "${en_utilisateur[@]}" python3 "$theme" plymouth "$genere/hub" >/dev/null 2>&1; then
    rm -rf "$genere"
    alerte "hub-theme plymouth a échoué : l'écran de démarrage reste celui d'Ubuntu"
    return 0
  fi
  local alternative
  alternative=$(update-alternatives --query default.plymouth 2>/dev/null | awk '/^Value:/ {print $2}')
  if diff -r -q "$genere/hub" "$cible" >/dev/null 2>&1 && [ "$alternative" = "$cible/hub.plymouth" ]; then
    deja "Plymouth : thème hub en place"
  else
    faire install -d -m 0755 "$cible" &&
    faire sh -c 'install -m 0644 "$1"/* "$2"/' copie "$genere/hub" "$cible" &&
    faire update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth \
      "$cible/hub.plymouth" 200 &&
    faire update-alternatives --set default.plymouth "$cible/hub.plymouth" || { rm -rf "$genere"; return 1; }
    # Le thème doit être dans l'initramfs, sinon Plymouth affiche celui d'avant jusqu'au
    # montage de la racine. Ubuntu 26.04 le construit avec dracut, mais par
    # update-initramfs, que dracut fournit : il ne régénère que les noyaux présents
    # dans /boot. « dracut --regenerate-all » parcourt /usr/lib/modules et échoue sur
    # le dossier qu'un ancien noyau désinstallé y laisse (vu en VM le 15/09/2026).
    if command -v update-initramfs >/dev/null; then
      faire update-initramfs -u -k all || { rm -rf "$genere"; return 1; }
    else
      faire dracut --force || { rm -rf "$genere"; return 1; }
    fi
    ok "Plymouth : thème hub, initramfs reconstruit"
  fi
  rm -rf "$genere"

  # Sans « splash » sur la ligne du noyau, Plymouth reste en mode texte. Ubuntu Desktop
  # le met par défaut ; une installation automatisée (la VM d'essai) ne l'avait pas.
  if grep -qw splash /proc/cmdline; then
    deja "noyau démarré avec splash"
  elif grep -Eq '^GRUB_CMDLINE_LINUX_DEFAULT=.*\bsplash\b' /etc/default/grub 2>/dev/null; then
    deja "splash dans /etc/default/grub (effectif au prochain démarrage)"
  elif grep -q '^GRUB_CMDLINE_LINUX_DEFAULT=' /etc/default/grub 2>/dev/null; then
    faire sed -i -E 's/^(GRUB_CMDLINE_LINUX_DEFAULT="[^"]*)"/\1 splash"/' /etc/default/grub &&
    faire update-grub || return 1
    ok "splash ajouté à la ligne du noyau (GRUB)"
  else
    alerte "ligne du noyau sans splash et GRUB introuvable : Plymouth restera en mode texte"
  fi
}

# ── 9. Mise à jour depuis le menu ─────────────────────────────────────────────
etape_mise_a_jour() {
  etape "9. Mise à jour depuis le menu"
  local maj="$DEPOT/mise-a-jour"
  if [ ! -f "$maj/hub-mise-a-jour" ] || [ ! -f "$maj/hub-mise-a-jour.service" ]; then
    deja "aucune mise à jour dans le dépôt ($maj) — étape sautée"
    return 0
  fi
  # git : une Ubuntu Desktop neuve ne l'a pas, et la mise à jour clone le dépôt.
  installer_paquets -- git || return 1
  poser "$maj/hub-mise-a-jour" /usr/local/bin/hub-mise-a-jour 0755 || return 1
  poser "$maj/hub-mise-a-jour.service" /etc/systemd/system/hub-mise-a-jour.service 0644 || return 1
  if [ -f "$maj/50-hub-mise-a-jour.rules" ]; then
    poser "$maj/50-hub-mise-a-jour.rules" /etc/polkit-1/rules.d/50-hub-mise-a-jour.rules 0644 || return 1
  fi
  # Pas d'activation au démarrage : le service ne tourne que quand le menu le lance.
  if [ "$POUR_DE_VRAI" != 1 ] ||
     [ "$(systemctl show -p LoadState --value hub-mise-a-jour.service 2>/dev/null)" != loaded ] ||
     [ "$(systemctl show -p NeedDaemonReload --value hub-mise-a-jour.service 2>/dev/null)" = yes ]; then
    faire systemctl daemon-reload || return 1
  fi

  # Le groupe « hub » est ce que la règle polkit autorise. L'appartenance ne vaut qu'à
  # la session suivante : d'où le redémarrage demandé en fin d'installation.
  if getent group hub >/dev/null; then
    deja "groupe hub"
  else
    faire groupadd hub || return 1
    ok "groupe hub"
  fi
  if id -nG "$UTILISATEUR" 2>/dev/null | tr ' ' '\n' | grep -qx hub; then
    deja "$UTILISATEUR dans le groupe hub"
  else
    faire usermod -aG hub "$UTILISATEUR" || return 1
    ok "$UTILISATEUR dans le groupe hub (effectif à la prochaine session)"
  fi

  local d
  for d in /etc/hub /var/lib/hub/versions; do
    if [ -d "$d" ]; then deja "$d/"; else faire install -d -m 0755 "$d" || return 1; ok "$d/"; fi
  done
  local env_voulu="HUB_UTILISATEUR=$UTILISATEUR"
  if [ "$(cat /etc/hub/mise-a-jour.env 2>/dev/null)" = "$env_voulu" ]; then
    deja "/etc/hub/mise-a-jour.env"
  elif [ "$POUR_DE_VRAI" = 1 ]; then
    printf '%s\n' "$env_voulu" >/etc/hub/mise-a-jour.env && chmod 0644 /etc/hub/mise-a-jour.env ||
      { echec "écriture de /etc/hub/mise-a-jour.env"; return 1; }
    ok "/etc/hub/mise-a-jour.env ($env_voulu)"
  else
    faire "écrire $env_voulu dans /etc/hub/mise-a-jour.env"
  fi
  # La source est un choix de l'utilisateur (GitHub, le Mac…) : jamais écrasée.
  if [ -f /etc/hub/mise-a-jour.json ]; then
    deja "/etc/hub/mise-a-jour.json conservé tel quel"
  elif [ "$POUR_DE_VRAI" = 1 ]; then
    printf '%s\n' "$SOURCE_MISE_A_JOUR" >/etc/hub/mise-a-jour.json &&
      chmod 0644 /etc/hub/mise-a-jour.json || { echec "écriture de /etc/hub/mise-a-jour.json"; return 1; }
    ok "/etc/hub/mise-a-jour.json (dépôt GitHub, branche master)"
  else
    faire "créer /etc/hub/mise-a-jour.json : $SOURCE_MISE_A_JOUR"
  fi

  # Chaîne de confiance des mises à jour : hub-mise-a-jour n'installe qu'un commit signé
  # par une clé de /etc/hub/signataires-autorises. Ce fichier n'est posé depuis le dépôt
  # que s'il est absent ou sans aucune clé — première installation, faite par le
  # propriétaire depuis un support qu'il contrôle ; sans clé, aucune mise à jour n'a pu
  # passer, rien n'est donc à protéger — ou quand l'installateur tourne depuis un commit dont
  # hub-mise-a-jour vient de vérifier la signature : ce commit s'exécute déjà en root,
  # le laisser changer les clés ne donne rien de plus, et c'est ainsi qu'une clé se
  # remplace sans passer devant le HUB. Lancé à la main depuis un clone quelconque, il
  # ne remplace jamais un fichier existant. Un dépôt sans aucune clé ne vide jamais un
  # fichier qui en contient : ce serait bloquer toutes les mises à jour suivantes.
  local sig_depot="$maj/signataires-autorises" sig=/etc/hub/signataires-autorises
  local une_cle='^[[:space:]]*[^#[:space:]]' verifiee=0
  if [ -n "${HUB_MISE_A_JOUR_VERIFIEE:-}" ] &&
     [ "$(git -C "$DEPOT/.." rev-parse HEAD 2>/dev/null)" = "$HUB_MISE_A_JOUR_VERIFIEE" ]; then
    verifiee=1
  fi
  if [ ! -f "$sig_depot" ]; then
    alerte "absent du dépôt : $sig_depot ($sig inchangé)"
  elif { [ ! -e "$sig" ] && [ ! -L "$sig" ]; } || cmp -s "$sig_depot" "$sig" ||
       { [ -f "$sig" ] && [ ! -L "$sig" ] && ! grep -Eq "$une_cle" "$sig"; }; then
    poser "$sig_depot" "$sig" 0644 || return 1
  elif [ "$verifiee" = 1 ] && grep -Eq "$une_cle" "$sig_depot"; then
    poser "$sig_depot" "$sig" 0644 || return 1
  elif [ "$verifiee" = 1 ]; then
    alerte "le dépôt ne liste aucune clé : $sig conservé tel quel"
  else
    deja "$sig conservé (remplacé seulement par une mise à jour vérifiée, ou à la main : mise-a-jour/README.md)"
  fi
  local sig_lu="$sig"
  [ -e "$sig" ] || sig_lu="$sig_depot"
  if ! grep -Eq "$une_cle" "$sig_lu" 2>/dev/null; then
    alerte "aucun signataire autorisé : les mises à jour depuis le menu seront refusées (mise-a-jour/README.md)"
  fi
}

# ── 10. Commande vocale (si elle est livrée) ─────────────────────────────────
etape_voix() {
  etape "10. Commande vocale (si elle est livrée)"
  local voix="$DEPOT/voix" opt=/opt/hub-voix f
  if [ ! -f "$voix/hub-voix.py" ] || [ ! -f "$voix/hub-voix.service" ]; then
    deja "aucun service vocal complet dans le dépôt ($voix) — étape sautée"
    return 0
  fi
  # La disposition est celle qu'attend l'unité livrée (ExecStart dans /opt/hub-voix,
  # venv à côté) : l'installateur s'y plie plutôt que de la réécrire, pour qu'un
  # seul endroit décide où vit le service.
  installer_paquets -- python3-venv pipewire-bin curl unzip || return 1
  poser "$voix/hub-voix.py"         "$opt/hub-voix.py"         0755 || return 1
  poser "$voix/hub_voix_logique.py" "$opt/hub_voix_logique.py" 0644 || return 1
  # Les mots courants que la grammaire ajoute aux commandes : sans eux, la TV qui parle
  # redevient capable de lancer des commandes (voix/README.md, « Mesures »).
  for f in remplissage-fr.txt remplissage-en.txt; do
    poser "$voix/$f" "$opt/$f" 0644 || return 1
  done
  # Vosk n'est pas empaqueté par Ubuntu : un venv isolé, plutôt qu'un pip lancé en
  # root sur le Python du système, que la prochaine mise à jour d'apt casserait.
  # Version FIGÉE et roue vérifiée par son empreinte (voix/README.md) : un « pip
  # install vosk » installerait ce que PyPI sert le jour de la mise à jour.
  local version_vosk=0.3.45
  local empreinte_vosk=25e025093c4399d7278f543568ed8cc5460ac3a4bf48c23673ace1e25d26619f
  if [ "$("$opt/venv/bin/python" -c 'import importlib.metadata as m, vosk; print(m.version("vosk"))' 2>/dev/null)" = "$version_vosk" ]; then
    deja "$opt/venv (vosk $version_vosk)"
  else
    faire python3 -m venv "$opt/venv" || return 1
    if [ "$POUR_DE_VRAI" = 1 ]; then
      local roues; roues=$(mktemp -d) || { echec "mktemp impossible"; return 1; }
      # --require-hashes vaut pour la roue de vosk ; ses dépendances (cffi, requests,
      # srt, tqdm, websockets) viennent ensuite de PyPI, sans version figée.
      printf 'vosk==%s --hash=sha256:%s\n' "$version_vosk" "$empreinte_vosk" >"$roues/exigences.txt"
      faire "$opt/venv/bin/pip" install -q --no-deps --only-binary=:all: --require-hashes \
        -r "$roues/exigences.txt" &&
      faire "$opt/venv/bin/pip" install -q "vosk==$version_vosk"
      local code=$?; rm -rf "$roues"; [ "$code" -eq 0 ] || return 1
    else
      faire "$opt/venv/bin/pip" install --require-hashes "vosk==$version_vosk (sha256 ${empreinte_vosk:0:12}…), puis ses dépendances"
    fi
    ok "$opt/venv (vosk $version_vosk, roue vérifiée)"
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

# ── 11. Streaming et jeu en nuage : Google Chrome ─────────────────────────────
# Empreinte de la clé « Google Inc. (Linux Packages Signing Authority) », relevée le
# 15 septembre 2026 (gpg --show-keys /usr/share/keyrings/google-chrome.gpg). La clé
# téléchargée doit la porter : un fichier remplacé en chemin n'entre pas dans apt.
EMPREINTE_GOOGLE="EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796"
DEPOT_CHROME='Types: deb
URIs: https://dl.google.com/linux/chrome-stable/deb/
Suites: stable
Components: main
Architectures: amd64
Signed-By: /usr/share/keyrings/google-chrome.gpg'

etape_navigateur() {
  etape "11. Streaming et jeu en nuage — Google Chrome"
  # Chrome et non le Chromium ou le Firefox d'Ubuntu, livrés en snap : GeForce NOW et
  # Xbox Cloud Gaming n'acceptent que Chromium, et Widevine comme VA-API dépendent du
  # confinement du snap. Le .deb de Google porte Widevine (Netflix, Disney+, Canal+).
  if [ "$(dpkg --print-architecture)" != amd64 ]; then
    alerte "Google Chrome n'existe qu'en amd64 : services web non installés"
    return 0
  fi
  installer_paquets -- curl gpg || return 1
  local cle=/usr/share/keyrings/google-chrome.gpg sources=/etc/apt/sources.list.d/google-chrome.sources
  if [ -f "$cle" ] && gpg --show-keys --with-colons "$cle" 2>/dev/null | grep -q "^fpr:*$EMPREINTE_GOOGLE:"; then
    deja "$cle (empreinte vérifiée)"
  elif [ "$POUR_DE_VRAI" = 1 ]; then
    local tmp; tmp=$(mktemp -d) || { echec "mktemp impossible"; return 1; }
    faire curl -fsSL --retry 3 -o "$tmp/cle.asc" https://dl.google.com/linux/linux_signing_key.pub ||
      { rm -rf "$tmp"; return 1; }
    if ! gpg --show-keys --with-colons "$tmp/cle.asc" 2>/dev/null | grep -q "^fpr:*$EMPREINTE_GOOGLE:"; then
      rm -rf "$tmp"; echec "la clé de Google téléchargée ne porte pas l'empreinte attendue"; return 1
    fi
    faire gpg --batch --yes --dearmor -o "$tmp/cle.gpg" "$tmp/cle.asc" &&
    faire install -D -m 0644 "$tmp/cle.gpg" "$cle"
    local code=$?; rm -rf "$tmp"; [ "$code" -eq 0 ] || return 1
    ok "$cle (empreinte $EMPREINTE_GOOGLE)"
  else
    faire "télécharger linux_signing_key.pub, vérifier l'empreinte $EMPREINTE_GOOGLE, la poser dans $cle"
  fi
  # Même fichier et même contenu que ceux qu'écrit la tâche cron du paquet
  # (/etc/cron.daily/google-chrome) : sinon apt voit deux sources avec deux Signed-By
  # différents et refuse de se mettre à jour.
  if [ "$(grep -v '^#' "$sources" 2>/dev/null | grep -v '^X-Repolib' | sed '/^$/d')" = "$DEPOT_CHROME" ]; then
    deja "$sources"
  elif [ "$POUR_DE_VRAI" = 1 ]; then
    printf '%s\n' "$DEPOT_CHROME" >"$sources.hub" && faire install -m 0644 "$sources.hub" "$sources"
    local code=$?; rm -f "$sources.hub"; [ "$code" -eq 0 ] || return 1
    APT_A_JOUR=0
    ok "$sources"
  else
    faire "écrire $sources (dépôt stable de Google, Signed-By $cle)"
  fi
  # intel-media-va-driver : le pilote VA-API (iHD) de l'UHD 630, pour que Chrome décode
  # H.264, HEVC et VP9 par la puce. Vérifier ensuite avec vainfo et chrome://gpu.
  installer_paquets -- google-chrome-stable intel-media-va-driver || return 1
  if [ -d "$MAISON/.local/share/hub/navigateur" ]; then
    deja "$MAISON/.local/share/hub/navigateur/ (un dossier par profil)"
  else
    faire runuser -u "$UTILISATEUR" -- mkdir -p "$MAISON/.local/share/hub/navigateur" || return 1
    ok "$MAISON/.local/share/hub/navigateur/ (un dossier par profil, créé au premier lancement)"
  fi
}

# ── 12. Temps d'écran ─────────────────────────────────────────────────────────
etape_temps_ecran() {
  etape "12. Temps d'écran par profil"
  if [ ! -f "$DEPOT/hub-temps-ecran" ]; then
    deja "hub-temps-ecran absent du dépôt — étape sautée"
    return 0
  fi
  # gnome-kiosk-script lance les modes à travers lui ; s'il manque, les modes se lancent
  # sans décompte. libnotify-bin : l'avertissement dans la session Ubuntu (notify-send).
  installer_paquets -- libnotify-bin || return 1
  poser "$DEPOT/hub-temps-ecran" /usr/local/bin/hub-temps-ecran 0755 || return 1
  # Le bureau est une autre session : il y est compté par un autostart (OnlyShowIn=ubuntu).
  poser "$DEPOT/hub-temps-ecran-bureau.desktop" /etc/xdg/autostart/hub-temps-ecran-bureau.desktop 0644 || return 1
  if [ -d "$MAISON/.local/state/hub" ]; then
    deja "$MAISON/.local/state/hub/ (temps-ecran.json)"
  else
    faire runuser -u "$UTILISATEUR" -- mkdir -p "$MAISON/.local/state/hub" || return 1
    ok "$MAISON/.local/state/hub/ (temps-ecran.json y sera tenu)"
  fi
}

# ── 13. Allumage programmé et Wake-on-LAN ─────────────────────────────────────
# Wake-on-LAN sur les cartes Ethernet physiques. Deux réglages parce qu'aucun ne suffit
# seul : ethtool agit tout de suite mais s'oublie au redémarrage, NetworkManager le
# remet à chaque connexion (802-3-ethernet.wake-on-lan).
activer_wake_on_lan() {
  local carte nom mac trouve=0 uuid type
  for carte in /sys/class/net/*; do
    [ "$(cat "$carte/type" 2>/dev/null)" = 1 ] && [ -e "$carte/device" ] && [ ! -e "$carte/wireless" ] || continue
    nom=${carte##*/}; mac=$(cat "$carte/address" 2>/dev/null); trouve=1
    if ! ethtool "$nom" 2>/dev/null | grep -q '^[[:space:]]*Supports Wake-on:.*g'; then
      alerte "$nom ne se réveille pas par paquet magique (ethtool : Supports Wake-on sans « g »)"
      continue
    fi
    if ethtool "$nom" 2>/dev/null | grep -q '^[[:space:]]*Wake-on:.*g'; then
      deja "$nom : Wake-on-LAN actif"
    else
      faire ethtool -s "$nom" wol g || return 1
      ok "$nom : Wake-on-LAN actif"
    fi
    ok "$nom : adresse MAC $mac — à enregistrer dans l'application Wake-on-LAN du téléphone"
  done
  [ "$trouve" = 1 ] || alerte "aucune carte Ethernet : pas d'allumage à distance (le wifi ne le permet pas)"
  command -v nmcli >/dev/null || { alerte "nmcli absent : Wake-on-LAN à réactiver après chaque redémarrage"; return 0; }
  while IFS=: read -r uuid type; do
    [ "$type" = 802-3-ethernet ] || continue
    if nmcli -g 802-3-ethernet.wake-on-lan connection show "$uuid" 2>/dev/null | grep -q magic; then
      deja "NetworkManager : Wake-on-LAN gardé pour la connexion $uuid"
    else
      faire nmcli connection modify "$uuid" 802-3-ethernet.wake-on-lan magic || return 1
      ok "NetworkManager : Wake-on-LAN gardé pour la connexion $uuid"
    fi
  done < <(nmcli -g UUID,TYPE connection show 2>/dev/null)
  alerte "BIOS (F1) : « Wake on LAN » activé et « Enhanced Power Saving Mode » désactivé, sinon la carte dort à l'arrêt"
}

etape_allumage() {
  etape "13. Allumage programmé et Wake-on-LAN"
  local al="$DEPOT/allumage"
  if [ ! -f "$al/hub-allumage" ] || [ ! -f "$al/hub-allumage.service" ]; then
    deja "aucun allumage programmé dans le dépôt ($al) — étape sautée"
    return 0
  fi
  command -v rtcwake >/dev/null || installer_paquets -- util-linux || return 1
  poser "$al/hub-allumage" /usr/local/bin/hub-allumage 0755 || return 1
  poser "$al/hub-allumage.service" /etc/systemd/system/hub-allumage.service 0644 || return 1
  poser "$al/hub-allumage-demarrage.service" /etc/systemd/system/hub-allumage-demarrage.service 0644 || return 1
  poser "$al/50-hub-allumage.rules" /etc/polkit-1/rules.d/50-hub-allumage.rules 0644 || return 1
  if [ "$POUR_DE_VRAI" != 1 ] ||
     [ "$(systemctl show -p NeedDaemonReload --value hub-allumage.service 2>/dev/null)" = yes ] ||
     [ "$(systemctl show -p LoadState --value hub-allumage-demarrage.service 2>/dev/null)" != loaded ]; then
    faire systemctl daemon-reload || return 1
  fi
  # Le groupe que la règle polkit autorise ; le même que pour la mise à jour.
  if getent group hub >/dev/null; then deja "groupe hub"; else faire groupadd hub || return 1; ok "groupe hub"; fi
  if id -nG "$UTILISATEUR" 2>/dev/null | tr ' ' '\n' | grep -qx hub; then
    deja "$UTILISATEUR dans le groupe hub"
  else
    faire usermod -aG hub "$UTILISATEUR" || return 1
    ok "$UTILISATEUR dans le groupe hub (effectif à la prochaine session)"
  fi
  local env_voulu="HUB_UTILISATEUR=$UTILISATEUR"
  if [ "$(cat /etc/hub/allumage.env 2>/dev/null)" = "$env_voulu" ]; then
    deja "/etc/hub/allumage.env"
  elif [ "$POUR_DE_VRAI" = 1 ]; then
    install -d -m 0755 /etc/hub && printf '%s\n' "$env_voulu" >/etc/hub/allumage.env && chmod 0644 /etc/hub/allumage.env ||
      { echec "écriture de /etc/hub/allumage.env"; return 1; }
    ok "/etc/hub/allumage.env ($env_voulu)"
  else
    faire "écrire $env_voulu dans /etc/hub/allumage.env"
  fi
  if [ -d /var/lib/hub ]; then deja "/var/lib/hub/"; else faire install -d -m 0755 /var/lib/hub || return 1; ok "/var/lib/hub/"; fi
  # Pas de démarrage maintenant : le programme se réarme au prochain démarrage, et le
  # menu le relance à chaque changement d'horaire.
  if [ "$(systemctl is-enabled hub-allumage-demarrage.service 2>/dev/null)" = enabled ]; then
    deja "hub-allumage-demarrage.service activé"
  else
    faire systemctl enable hub-allumage-demarrage.service || return 1
    ok "hub-allumage-demarrage.service activé (réveil détecté et réarmé à chaque démarrage)"
  fi
  [ -e /sys/class/rtc/rtc0/wakealarm ] ||
    alerte "pas d'alarme d'horloge (/sys/class/rtc/rtc0/wakealarm) : l'allumage programmé ne pourra pas marcher ici"
  activer_wake_on_lan
}

# ── 15. Télécommande de la TV par HDMI-CEC ─────────────────────────────────────
# Le M720q n'a pas de CEC : tout ceci ne sert qu'avec l'adaptateur USB Pulse-Eight
# (installer/cec/README.md). Posé quand même sans lui : le service attend l'adaptateur
# sans rien coûter, et le brancher plus tard suffit.
etape_cec() {
  etape "15. Télécommande de la TV (HDMI-CEC)"
  local cec="$DEPOT/cec" lib=/usr/local/lib/hub f n
  if [ ! -f "$cec/hub-cec.py" ] || [ ! -f "$cec/hub-cec.service" ]; then
    deja "aucune télécommande CEC dans le dépôt ($cec) — étape sautée"
    return 0
  fi
  # cec-utils (cec-client) et libcec7 : universe, 7.1.1 sur Ubuntu 26.04.
  installer_paquets -- cec-utils || return 1
  for f in hub-cec.py hub_cec_logique.py README.md; do
    poser "$cec/$f" "$lib/cec/$f" "$([ "$f" = hub-cec.py ] && echo 0755 || echo 0644)" || return 1
  done
  # Le service reconnaît Kodi, le bureau et hub-web avec la logique de la voix.
  if [ -f "$DEPOT/voix/hub_voix_logique.py" ]; then
    poser "$DEPOT/voix/hub_voix_logique.py" "$lib/voix/hub_voix_logique.py" 0644 || return 1
  fi
  poser "$cec/70-hub-cec.rules" /etc/udev/rules/70-hub-cec.rules 0644 || return 1
  # Mode « relais » : Kodi ne doit pas ouvrir l'adaptateur que tient hub-cec. Posé
  # seulement s'il n'existe pas : un choix fait dans les réglages de Kodi est gardé.
  for n in 1001 1002; do
    f="$MAISON/.kodi/userdata/peripheral_data/cec_2548_$n.xml"
    if [ -f "$f" ]; then deja "$f (gardé tel quel)"; else poser "$cec/kodi-cec-desactive.xml" "$f" 0644 "$UTILISATEUR" || return 1; fi
  done
  poser "$cec/hub-cec.service" /usr/local/lib/systemd/user/hub-cec.service 0644 || return 1
  activer_unite_globale hub-cec.service || return 1
}

# ── 14. Enceinte réseau : Spotify Connect, AirPlay, recopie d'écran ─────────
# Versions FIGÉES. librespot n'est empaqueté ni par Ubuntu ni par le projet (sources
# seules) : on prend le binaire du .deb raspotify, vérifié par son empreinte, sans
# installer le paquet (installer/enceinte/README.md). Monter de version : ces trois
# lignes, après avoir relancé la preuve en conteneur.
LIBRESPOT_DEB_URL="https://github.com/dtcooper/raspotify/releases/download/0.48.2/raspotify_0.48.2.librespot.v0.8.0-9c7d756_amd64.deb"
LIBRESPOT_DEB_SHA256=7f2c232af89834608bc393f6f9295a22a2659fe938f65c108b78a70c8b539733
LIBRESPOT_VERSION="librespot 0.8.0 9c7d7561"

# Les builds raspotify suffixent la ligne : « librespot 0.8.0 9c7d7561 (Built on
# 2026-07-18, Build ID: PxD46HQ7, Profile: release) », relevé sur le M720q le 17/09/2026.
# L'égalité exacte refusait ce binaire pourtant vérifié par son empreinte. On exige la
# version et le commit, suivis de rien ou d'une espace : « 9c7d75610 » ne passe pas.
# Testé par tests/test_hub_installer_librespot.py, et appelé par la preuve en conteneur.
librespot_attendu() { # binaire
  case "$("$1" --version 2>/dev/null | head -n 1)" in
    "$LIBRESPOT_VERSION" | "$LIBRESPOT_VERSION "*) return 0 ;;
    *) return 1 ;;
  esac
}

# Le réseau de l'interface qui porte la route par défaut : ce qu'on ouvre ne doit être
# joignable ni depuis un VPN ni depuis une interface de conteneur.
reseau_local() {
  local iface
  iface=$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')
  ip -4 -o addr show dev "${iface:-lo}" 2>/dev/null | awk '{print $4; exit}' |
    python3 -c 'import ipaddress,sys; print(ipaddress.ip_interface(sys.stdin.read().strip()).network)' 2>/dev/null
}

etape_enceinte() {
  etape "14. Enceinte réseau (Spotify Connect, AirPlay, recopie d'écran)"
  local src="$DEPOT/enceinte" lib=/usr/local/lib/hub/enceinte opt=/opt/hub-enceinte
  if [ ! -f "$src/hub_enceinte.py" ] || [ ! -f "$src/hub-enceinte.service" ]; then
    deja "aucune enceinte réseau dans le dépôt ($src) — étape sautée"
    return 0
  fi
  if [ "$(dpkg --print-architecture 2>/dev/null)" != amd64 ]; then
    alerte "architecture $(dpkg --print-architecture) : le librespot figé est amd64, enceinte réseau non installée"
    return 0
  fi

  # Le paquet shairport-sync active un service SYSTÈME sur ALSA, démarré dès
  # l'installation : il prendrait la carte son à PipeWire. Masqué AVANT le paquet,
  # il ne démarre jamais ; le masque survit aux mises à jour du paquet.
  if [ "$(systemctl is-enabled shairport-sync.service 2>/dev/null)" = masked ]; then
    deja "service système shairport-sync masqué"
  else
    if systemctl cat shairport-sync.service >/dev/null 2>&1; then
      faire systemctl disable --now shairport-sync.service || return 1
    fi
    faire systemctl mask shairport-sync.service || return 1
    ok "service système shairport-sync masqué (hub-airplay le lance dans la session)"
  fi
  # uxplay avec les greffons GStreamer qu'il utilise : waylandsink (bad), pulsesink
  # (good), et le décodage H.264 (libav en repli du décodage matériel VA-API).
  installer_paquets -- shairport-sync uxplay avahi-daemon libpulse0 libasound2t64 libglib2.0-bin \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-good gstreamer1.0-libav curl || return 1

  if librespot_attendu "$opt/librespot"; then
    deja "$opt/librespot ($LIBRESPOT_VERSION)"
  elif [ "$POUR_DE_VRAI" = 1 ]; then
    local tmp; tmp=$(mktemp -d) || { echec "mktemp impossible"; return 1; }
    faire curl -fsSL --retry 3 -o "$tmp/raspotify.deb" "$LIBRESPOT_DEB_URL" &&
    faire sh -c 'echo "$1  $2" | sha256sum -c -' empreinte "$LIBRESPOT_DEB_SHA256" "$tmp/raspotify.deb" &&
    faire dpkg-deb -x "$tmp/raspotify.deb" "$tmp/paquet" &&
    faire install -D -m 0755 "$tmp/paquet/usr/bin/librespot" "$opt/librespot"
    local code=$?; rm -rf "$tmp"; [ "$code" -eq 0 ] || return 1
    librespot_attendu "$opt/librespot" ||
      { echec "$opt/librespot ne répond pas « $LIBRESPOT_VERSION »"; return 1; }
    ok "$opt/librespot ($LIBRESPOT_VERSION, .deb vérifié, paquet non installé)"
  else
    faire "télécharger $LIBRESPOT_DEB_URL, vérifier sha256 ${LIBRESPOT_DEB_SHA256:0:12}…, extraire librespot vers $opt/librespot"
  fi

  poser "$src/hub_enceinte.py" "$lib/hub_enceinte.py" 0755 || return 1
  [ -f "$src/README.md" ] && { poser "$src/README.md" "$lib/README.md" 0644 || return 1; }
  if [ "$(readlink /usr/local/bin/hub-enceinte 2>/dev/null)" = "$lib/hub_enceinte.py" ]; then
    deja "/usr/local/bin/hub-enceinte"
  else
    faire ln -sfn "$lib/hub_enceinte.py" /usr/local/bin/hub-enceinte || return 1
    ok "/usr/local/bin/hub-enceinte"
  fi
  local u
  for u in hub-enceinte hub-spotify hub-airplay hub-airplay-ecran; do
    poser "$src/$u.service" "/usr/local/lib/systemd/user/$u.service" 0644 || return 1
    activer_unite_globale "$u.service" || return 1
  done

  # Même règle que la télécommande : ufw inactif par défaut ; actif, on n'ouvre qu'au
  # réseau local. Ports fixés dans hub_enceinte.py (PORT_*).
  if command -v ufw >/dev/null && LC_ALL=C ufw status 2>/dev/null | grep -q '^Status: active'; then
    local reseau regle port proto
    reseau=$(reseau_local)
    if [ -z "$reseau" ]; then
      alerte "ufw actif mais réseau local introuvable : Spotify et AirPlay seront bloqués"
      return 0
    fi
    for regle in 5353/udp 5390/tcp 5000/tcp 6001:6010/udp 7000:7002/tcp 7000:7002/udp; do
      port=${regle%/*}; proto=${regle#*/}
      if LC_ALL=C ufw status 2>/dev/null | grep -Eq "^$port/$proto[[:space:]]+ALLOW[[:space:]]+$reseau\b"; then
        deja "ufw : $regle ouvert à $reseau"
      else
        faire ufw allow from "$reseau" to any port "$port" proto "$proto" || return 1
        ok "ufw : $regle ouvert à $reseau seulement"
      fi
    done
  fi
}

etape_mesure
etape_session
etape_accueil
etape_kodi
etape_telecommande
etape_demarrage
etape_habillage
etape_mise_a_jour
# Sans téléchargement lourd : avant la voix et Chrome.
etape_temps_ecran
etape_allumage
# La voix vient après la bascule du démarrage : elle télécharge (pip, modèles) et un
# réseau capricieux ne doit pas priver le salon de son HUB. Son échec reste compté.
etape_voix
# Chrome aussi après la bascule : 110 Mo à télécharger, et Kodi ne doit pas en dépendre.
etape_navigateur
# L'enceinte télécharge librespot : après la bascule, comme la voix et Chrome.
etape_enceinte
# La télécommande CEC : un paquet de 1 Mo, sans effet tant que l'adaptateur manque.
etape_cec

# ── Fin ───────────────────────────────────────────────────────────────────────
etape "Ce qui reste à faire à la main"
cat <<'RESTE'
  [ ] télécommande de la TV : acheter l'adaptateur Pulse-Eight USB-CEC, le brancher,
      puis la liste « À éprouver » de installer/cec/README.md
  [ ] trancher d'où vient le streaming de jeu, puis relancer pour le mode Gaming
  [ ] relancer audit/audit.sh une fois la TV branchée, pour les trois mesures
      qui n'existent qu'à ce moment-là
  [ ] régler l'audio de Kodi après mesure (ARCHITECTURE.md, section Audio)
  [ ] BIOS : Automatic Power On (réveil programmé), Wake on LAN, Enhanced Power Saving
      Mode désactivé ; éprouver avec sudo rtcwake -m off -s 120 (installer/allumage/README.md)
  [ ] enceinte réseau : Spotify (compte Premium) et iPhone sur le même réseau que le HUB,
      puis la liste « À éprouver » de installer/enceinte/README.md
  [ ] vérifier le décodage matériel de Chrome : vainfo, puis chrome://gpu (hub-web --essai)
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
