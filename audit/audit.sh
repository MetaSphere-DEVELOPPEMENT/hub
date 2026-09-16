#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  audit.sh — l'état réel de la machine, avant toute installation
# ═══════════════════════════════════════════════════════════════════════════════
#
# CE QUE CE SCRIPT FAIT, ET CE QU'IL NE FAIT PAS.
#
# Il MESURE. Il n'installe rien, ne modifie rien, ne demande aucun privilège.
# Il s'exécute sans `sudo` : tout ce qui exigerait des droits est signalé comme
# non mesurable plutôt que deviné. Un audit qui invente une valeur est pire qu'un
# audit absent, parce qu'on s'y fie.
#
# Quand un outil manque, il écrit « absent » et poursuit. Sur une Ubuntu fraîche,
# la moitié des commandes d'inspection ne sont pas installées — c'est normal, et
# ce n'est pas une raison pour que l'audit s'arrête.
#
# À RELANCER À CHAQUE ÉTAPE, parce que trois mesures ne valent rien tant que la
# machine n'est pas à sa place définitive :
#   - la résolution réellement négociée avec la TV,
#   - l'audio HDMI,
#   - le débit Ethernet réel.
# Elles n'existent qu'une fois le câble HDMI et le câble réseau branchés.
#
#   ./audit.sh              affiche à l'écran
#   ./audit.sh > rapport.md garde une trace datée
#   HUB_AUDIT_BRUT=1 ./audit.sh   sans masquage, pour un diagnostic qui reste local
#
# POURQUOI LE RAPPORT MASQUE DES IDENTIFIANTS. Les rapports sont versionnés dans un
# dépôt public. Le nom du Wi-Fi et l'adresse MAC du point d'accès suffisent à
# situer la maison sur les cartes publiques de bornes Wi-Fi ; le préfixe IPv6
# global identifie l'abonnement ; les adresses fe80:: et les noms d'interface
# « wlx… » contiennent l'adresse MAC de la carte ; le nom d'hôte, les chemins
# /media/<utilisateur> et les UUID de /etc/crypttab nomment la personne et ses
# disques. Aucune de ces valeurs ne décide d'un choix d'architecture : les
# débits, modèles, pilotes et états restent en clair.

set -uo pipefail
export LC_ALL=C.UTF-8 2>/dev/null || true

titre() { printf '\n## %s\n\n' "$1"; }
ligne() { printf '  %-26s %s\n' "$1" "$2"; }

# Une commande absente n'est pas une erreur : c'est une information.
a() { command -v "$1" >/dev/null 2>&1; }
sinon_absent() { local v; v=$("$@" 2>/dev/null); [ -n "$v" ] && printf '%s' "$v" || printf '—'; }

# Tout passe par sed -E sans extension GNU (pas de \b ni de \s), pour que le
# masquage s'éprouve aussi sous macOS (bash 3.2, sed BSD).
masquer() {
  if [ "${HUB_AUDIT_BRUT:-0}" = 1 ]; then cat; return; fi
  sed -E \
    -e 's/ESSID:"[^"]*"/ESSID:"(masqué)"/g' \
    -e 's/(^|[^0-9A-Fa-f:])([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/\1(MAC masquée)/g' \
    -e 's/(wlx|enx)[0-9a-f]{12}/\1(masqué)/g' \
    -e 's/(^|[^0-9a-f:])(fe80|fec0):[0-9a-f:]*/\1\2::(masquée)/g' \
    -e 's/(^|[^0-9a-f:])f[cd][0-9a-f]{2}:[0-9a-f:]*/\1(IPv6 locale masquée)/g' \
    -e 's/(^|[^0-9a-f:])[23][0-9a-f]{3}:[0-9a-f]{1,4}:[0-9a-f:]*/\1(IPv6 globale masquée)/g' \
    -e 's/[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}/(UUID masqué)/g' \
    -e 's#(/run)?/media/[^ ]+#/media/(masqué)#g' \
    -e 's#/home/[^/ ]+#/home/(masqué)#g'
}

nom_hote() {
  if [ "${HUB_AUDIT_BRUT:-0}" = 1 ]; then hostname; else printf '(nom d%shôte masqué)' "'"; fi
}

# Chargé avec HUB_AUDIT_SOURCE=1, le script ne livre que ses fonctions : on
# éprouve ainsi le masque sur des sorties connues sans lancer tout l'audit.
[ "${HUB_AUDIT_SOURCE:-0}" = 1 ] && return 0 2>/dev/null

{
JOURS=(dimanche lundi mardi mercredi jeudi vendredi samedi)
MOIS=('' janvier février mars avril mai juin juillet août septembre octobre novembre décembre)
printf '# Audit matériel — %s %s %s %s, %s\n\n' \
  "${JOURS[$(date +%w)]}" "$(date +%-d)" "${MOIS[$(date +%-m)]}" "$(date +%Y)" "$(date +%Hh%M)"
printf '_Mesuré sur `%s`. Aucune installation, aucune modification._\n' "$(nom_hote)"

# ── Système ───────────────────────────────────────────────────────────────────
titre "Système"
if [ -r /etc/os-release ]; then
  . /etc/os-release
  ligne "distribution" "${PRETTY_NAME:-?}"
  ligne "nom de code" "${VERSION_CODENAME:-?}"
fi
ligne "noyau" "$(uname -r) ($(uname -m))"
ligne "systemd" "$(a systemctl && systemctl --version | head -1 || echo '—')"
ligne "session" "${XDG_SESSION_TYPE:-inconnue}"
ligne "bureau" "${XDG_CURRENT_DESKTOP:-aucun}"
ligne "connexion" "$(cat /etc/X11/default-display-manager 2>/dev/null || echo 'aucun gestionnaire')"
ligne "démarrée depuis" "$(a uptime && uptime -p || echo '—')"

titre "Machine"
for f in sys_vendor product_version product_name board_name; do
  v=$(cat "/sys/devices/virtual/dmi/id/$f" 2>/dev/null)
  [ -n "$v" ] && ligne "$f" "$v"
done
ligne "processeur" "$(a lscpu && lscpu | grep -E '^Model name|^Nom de modèle' | cut -d: -f2 | xargs || echo '—')"
ligne "cœurs / fils" "$(nproc 2>/dev/null || echo '—')"
ligne "mémoire" "$(a free && free -h | awk 'NR==2{print $2" dont "$7" disponibles"}' || echo '—')"

# ── Vidéo ─────────────────────────────────────────────────────────────────────
titre "GPU et décodage vidéo"
if a lspci; then
  lspci -nn 2>/dev/null | grep -iE 'vga|3d controller|display controller' | sed 's/^/  /'
else
  ligne "lspci" "absent — impossible d'identifier le GPU"
fi
ligne "pilote noyau" "$(a lspci && lspci -k 2>/dev/null | grep -A3 -iE 'vga|3d controller' | grep -m1 'Kernel driver' | cut -d: -f2 | xargs || echo '—')"
ligne "NVIDIA" "$(a nvidia-smi && nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null || echo 'aucun')"
ligne "rendu OpenGL" "$(a glxinfo && glxinfo -B 2>/dev/null | grep -m1 'OpenGL renderer' | cut -d: -f2 | xargs || echo 'glxinfo absent (paquet mesa-utils)')"
if a vainfo; then
  printf '  profils VA-API (décodage matériel) :\n'
  vainfo 2>/dev/null | grep -oE 'VAProfile[A-Za-z0-9]+' | sort -u | sed 's/VAProfile/    /' | tr '\n' ' ' | fold -w 92 -s | sed 's/^/  /'
  printf '\n'
else
  ligne "VA-API" "vainfo absent (paquet vainfo) — décodage matériel non vérifié"
fi
# AV1 est le point qui décide de la fluidité sur une TV en 2026 : YouTube et
# Netflix le poussent, et il n'est décodé en matériel qu'à partir de Tiger Lake.
ligne "AV1 matériel" "$(a vainfo && (vainfo 2>/dev/null | grep -q AV1 && echo 'OUI' || echo 'NON — repli processeur') || echo 'non vérifiable sans vainfo')"

titre "Sorties d'affichage"
trouve=0
for c in /sys/class/drm/card*-*; do
  [ -e "$c/status" ] || continue
  n=$(basename "$c"); s=$(cat "$c/status" 2>/dev/null)
  m=$(head -1 "$c/modes" 2>/dev/null)
  ligne "${n#card?-}" "$s${m:+  —  mode préféré $m}"
  trouve=1
done
[ "$trouve" = 0 ] && ligne "aucune sortie" "pas de /sys/class/drm — pilote graphique absent ?"
printf '\n'
printf '  _Une sortie « disconnected » ne se mesure pas : résolution, fréquence et_\n'
printf '  _audio HDMI ne sont lisibles qu%s écran branché._\n' "'"

titre "HDMI-CEC (télécommande de la TV)"
if ls /dev/cec* >/dev/null 2>&1; then
  ls /dev/cec* | sed 's/^/  périphérique : /'
else
  ligne "/dev/cec*" "aucun — pas de CEC matériel sur cette machine"
  printf '\n  _Sans CEC, la télécommande de la TV ne pilote pas le HUB. Il faut soit un_\n'
  printf '  _adaptateur USB-CEC, soit une manette ou un clavier sans fil._\n'
fi

# ── Audio ─────────────────────────────────────────────────────────────────────
titre "Audio"
for s in pipewire wireplumber pulseaudio; do
  ligne "$s" "$(systemctl --user is-active "$s" 2>/dev/null || echo '—')"
done
if a pactl; then
  printf '  sorties déclarées :\n'
  pactl list short sinks 2>/dev/null | awk '{print "    "$2}'
else
  ligne "pactl" "absent (paquet pulseaudio-utils) — sorties non listées"
fi
if a aplay; then
  printf '  cartes ALSA :\n'
  aplay -l 2>/dev/null | grep -E '^card|^carte' | sed 's/^/    /'
fi

# ── Réseau ────────────────────────────────────────────────────────────────────
titre "Réseau"
if a ip; then
  ip -br addr 2>/dev/null | grep -v '^lo' | sed 's/^/  /'
else
  ligne "ip" "absent"
fi
printf '\n'
for i in $(ls /sys/class/net 2>/dev/null | grep -v '^lo$'); do
  [ -e "/sys/class/net/$i/device" ] || continue
  porteuse=$(cat "/sys/class/net/$i/carrier" 2>/dev/null)
  vitesse=$(cat "/sys/class/net/$i/speed" 2>/dev/null)
  type=$([ -d "/sys/class/net/$i/wireless" ] && echo 'sans fil' || echo 'filaire')
  etat=$([ "$porteuse" = 1 ] && echo 'branché' || echo 'DÉBRANCHÉ')
  [ "${vitesse:--1}" -lt 0 ] 2>/dev/null && vitesse=""
  ligne "$i ($type)" "$etat${vitesse:+  —  ${vitesse} Mb/s}"
done
printf '\n'
if a iwconfig; then
  iwconfig 2>/dev/null | grep -E 'ESSID|Bit Rate|Frequency|Signal' | sed 's/^/  /' | head -6
fi
printf '\n  _Le débit wifi annoncé est un débit négocié, pas un débit utile : comptez la_\n'
printf '  _moitié. Pour du streaming de jeu, seul un test réel a valeur de preuve._\n'

titre "Bluetooth"
ctl=$(ls /sys/class/bluetooth/ 2>/dev/null)
if [ -n "$ctl" ]; then
  echo "$ctl" | sed 's/^/  contrôleur : /'
  ligne "service" "$(systemctl is-active bluetooth 2>/dev/null || echo '—')"
else
  ligne "contrôleur" "AUCUN détecté par le noyau"
  printf '\n  _Sans Bluetooth : pas de manette, pas de télécommande, pas de casque sans fil._\n'
fi

# ── Stockage ──────────────────────────────────────────────────────────────────
titre "Stockage"
if a lsblk; then
  lsblk -d -e 7 -o NAME,SIZE,MODEL,ROTA 2>/dev/null | sed 's/^/  /'
  printf '\n'
  lsblk -e 7 -o NAME,TYPE,FSTYPE,MOUNTPOINT 2>/dev/null | grep -vE '^\s*$' | sed 's/^/  /' | head -20
fi
printf '\n'
df -h / /home /boot/efi 2>/dev/null | sed 's/^/  /'
printf '\n'
# Un appareil de salon doit démarrer sans clavier. Un volume chiffré qui réclame
# une phrase de passe au démarrage rend le HUB inutilisable tel quel.
if [ -s /etc/crypttab ] && grep -qv '^\s*#' /etc/crypttab 2>/dev/null; then
  printf '  volumes chiffrés déclarés :\n'
  grep -v '^\s*#' /etc/crypttab | grep -v '^\s*$' | sed 's/^/    /'
  printf '    (« nofail » = le démarrage continue si le volume ne s%souvre pas)\n' "'"
else
  ligne "chiffrement" "aucun volume déclaré dans /etc/crypttab"
fi
ligne "racine chiffrée" "$(lsblk -o TYPE,MOUNTPOINT 2>/dev/null | grep -q '^crypt.*/$' && echo 'OUI — démarrage bloqué sans clavier' || echo 'non')"

# ── Ce qui est déjà là ────────────────────────────────────────────────────────
titre "Logiciels du HUB"
for p in kodi steam moonlight-qt sunshine gamescope retroarch vlc mpv \
         cec-client vainfo glxinfo wmctrl ethtool; do
  ligne "$p" "$(a "$p" && command -v "$p" || echo '—')"
done
ligne "flatpak" "$(a flatpak && echo "présent, $(flatpak list --app 2>/dev/null | wc -l) applications" || echo '—')"
ligne "snap" "$(a snap && echo "présent, $(snap list 2>/dev/null | tail -n +2 | wc -l) paquets" || echo '—')"

titre "Sessions proposées à la connexion"
for d in /usr/share/wayland-sessions /usr/share/xsessions; do
  [ -d "$d" ] || continue
  printf '  %s :\n' "$d"
  ls "$d" 2>/dev/null | sed 's/^/    /'
done

# ── Ce que cet audit NE sait pas ──────────────────────────────────────────────
titre "Ce qui reste non mesuré"
printf '  Ces points ne se mesurent pas depuis un terminal, ou pas sans matériel branché.\n'
printf '  Les laisser en blanc vaut mieux que les supposer.\n\n'
for m in \
  "résolution et fréquence réellement négociées avec la TV" \
  "sortie audio HDMI (présence, canaux, passthrough)" \
  "débit Ethernet réel, mesuré vers la box" \
  "latence et stabilité en streaming de jeu" \
  "consommation et bruit du ventilateur en lecture 4K prolongée"; do
  printf '  [ ] %s\n' "$m"
done
printf '\n'
} | masquer
