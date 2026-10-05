#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  construire-cle.sh — l'image de la clé USB qui installe le HUB
# ═══════════════════════════════════════════════════════════════════════════════
#
# Part de l'ISO officielle d'Ubuntu 26.04 (empreinte vérifiée), et y ajoute :
#   /hub/                 le projet HUB tel que commité (git archive), avec VERSION
#   /nocloud/user-data    l'installation automatique (cle/user-data.modele rempli)
#   /boot/grub/grub.cfg   un menu qui demande de valider avant d'effacer le disque
# Le démarrage BIOS/UEFI de l'ISO d'origine est rejoué tel quel (xorriso, dans un
# conteneur : rien à installer sur la machine).
#
#   ./construire-cle.sh [--disque /dev/nvme0n1] [--iso CHEMIN] [--sortie hub-cle.iso]
#
# Produit sortie/hub-cle.iso et sortie/MOT-DE-PASSE.txt (hors git).

# POURQUOI DES SYLLABES TIRÉES DE /dev/urandom. L'ancien générateur (deux mots parmi
# dix et quatre chiffres, avec $RANDOM) ne donnait que 20 bits : 900 000
# possibilités, qu'un hachage $6$ ne protège pas longtemps si le fichier user-data de
# la clé traîne. Ici, 12 syllables consonne-voyelle (16 consonnes × 5 voyelles, soit
# 6,3 bits chacune) donnent 75 bits. Elles restent lisibles à voix haute et se tapent
# sur une TV avec un clavier AZERTY sans majuscule ni chiffre ni touche morte :
# « kobave-tirulo-pedusa-fijomi ». Les octets sont tirés par rejet (un octet ≥ 255
# est jeté pour les voyelles) pour que chaque lettre ait exactement la même chance.
generer_mot_de_passe() {
  local consonnes=bcdfgjklmnprstvz voyelles=aeiou mdp="" n=0 octet
  while [ "$n" -lt 24 ]; do
    for octet in $(od -An -tu1 -N48 /dev/urandom); do
      [ "$n" -lt 24 ] || break
      if [ $((n % 2)) -eq 0 ]; then
        mdp="$mdp${consonnes:$((octet % 16)):1}"
      else
        [ "$octet" -lt 255 ] || continue
        mdp="$mdp${voyelles:$((octet % 5)):1}"
        [ $((n % 6)) -eq 5 ] && [ "$n" -lt 23 ] && mdp="$mdp-"
      fi
      n=$((n + 1))
    done
  done
  printf '%s\n' "$mdp"
}
# Chargé avec HUB_CLE_SOURCE=1, le script ne livre que ce générateur, pour l'éprouver
# sans ISO ni Docker.
if [ "${HUB_CLE_SOURCE:-0}" = 1 ]; then return 0; fi

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
RACINE=$(cd .. && pwd)
ISO="$HOME/Téléchargements/ubuntu-26.04.1-desktop-amd64.iso"
DISQUE=/dev/nvme0n1
SORTIE=hub-cle.iso
# Le compte créé sur le HUB : celui de qui construit la clé, pas une constante du dépôt
# (il est public). Le nom complet vient du système quand il le connaît.
UTILISATEUR_HUB="${USER:-$(id -un)}"
NOM_HUB=$( (id -F 2>/dev/null || getent passwd "$UTILISATEUR_HUB" 2>/dev/null | cut -d: -f5 | cut -d, -f1) | head -n 1)
NOM_HUB="${NOM_HUB:-$UTILISATEUR_HUB}"
while [ $# -gt 0 ]; do
  case "$1" in
    --disque) shift; DISQUE="$1" ;;
    --iso) shift; ISO="$1" ;;
    --sortie) shift; SORTIE="$1" ;;
    --utilisateur) shift; UTILISATEUR_HUB="$1" ;;
    --nom) shift; NOM_HUB="$1" ;;
    *) echo "argument inconnu : $1" >&2; exit 2 ;;
  esac
  shift
done

attendue=$(awk '$2 ~ /ubuntu-26.04.1-desktop-amd64.iso$/ {print $1}' "$RACINE/vm/SHA256SUMS")
printf '  … vérification de l’ISO\n'
[ "$(sha256sum "$ISO" | cut -d' ' -f1)" = "$attendue" ] || { echo "  ✗ empreinte de l'ISO fausse" >&2; exit 3; }

[ -z "$(git -C "$RACINE" status --porcelain -- installer audit cle tests VERSION NOUVEAUTES.md)" ] \
  || { echo "  ✗ modifications non commitées dans installer/ audit/ cle/ tests/ VERSION NOUVEAUTES.md : la clé doit contenir une version identifiable" >&2; exit 4; }

travail=$(mktemp -d "$PWD/.construction.XXXX")
trap 'rm -rf "$travail"' EXIT
mkdir -p "$travail/hub" "$travail/nocloud" "$travail/nocloud-apercu" "$travail/boot/grub/themes/hub" sortie

# Tout ce que l'installateur et la mise à jour attendent d'un dépôt : VERSION (le numéro
# que le menu affiche), NOUVEAUTES.md (ce qu'il raconte), tests/ (ce que la mise à jour
# rejoue), LICENSE. Sans eux, un HUB installé depuis la clé n'avait ni numéro ni
# nouveautés, et sa première mise à jour ne savait pas d'où elle partait.
git -C "$RACINE" archive HEAD installer audit cle tests ARCHITECTURE.md CLAUDE.md VERSION NOUVEAUTES.md LICENSE | tar -x -C "$travail/hub"
# Pas de .git sur la clé : l'empreinte et la date du commit voyagent dans COMMIT, que
# poser_version (hub-installer.sh) lit à défaut de git.
printf '%s\n%s\n' "$(git -C "$RACINE" rev-parse HEAD)" "$(git -C "$RACINE" log -1 --format=%cs)" > "$travail/hub/COMMIT"

# Un mot de passe propre à cette clé : il sert à sudo et au bureau, jamais à l'allumage.
if [ ! -f sortie/MOT-DE-PASSE.txt ]; then
  (umask 077 && generer_mot_de_passe > sortie/MOT-DE-PASSE.txt)
  chmod 600 sortie/MOT-DE-PASSE.txt
elif grep -Eqx '[a-z]+-[a-z]+-[0-9]{4}' sortie/MOT-DE-PASSE.txt; then
  # On ne le remplace pas d'office : une clé déjà installée avec ce mot de passe
  # doit rester ouvrable par celui qui le connaît.
  printf '  ! sortie/MOT-DE-PASSE.txt vient de l’ancien générateur (20 bits, devinable) :\n' >&2
  printf '    supprimez-le pour en tirer un robuste, puis reconstruisez la clé.\n' >&2
fi
# Par l'entrée standard : en argument, le mot de passe se lirait dans la liste des processus.
hache=$(openssl passwd -6 -stdin < sortie/MOT-DE-PASSE.txt)
cle_ssh=$(cat "$HOME/.ssh/id_rsa.pub")

printf '%s' "$UTILISATEUR_HUB" | grep -Eq '^[a-z_][a-z0-9_-]{0,31}$' || { echo "  ✗ nom d'utilisateur invalide pour Ubuntu : $UTILISATEUR_HUB (--utilisateur)" >&2; exit 6; }
sed -e "s|@MOT_DE_PASSE_HACHE@|$hache|" -e "s|@CLE_SSH@|$cle_ssh|" -e "s|@DISQUE@|$DISQUE|" \
    -e "s|@UTILISATEUR@|$UTILISATEUR_HUB|" -e "s|@NOM@|$NOM_HUB|" user-data.modele > "$travail/nocloud/user-data"
: > "$travail/nocloud/meta-data"
cp grub.cfg "$travail/boot/grub/grub.cfg"
cp apercu/user-data apercu/meta-data "$travail/nocloud-apercu/"

# Thème du menu de démarrage : fond et pastilles générés, polices converties pour GRUB.
python3 theme-grub/generer.py "$travail/boot/grub/themes/hub"
cp theme-grub/theme.txt "$travail/boot/grub/themes/hub/"
for s in 20 24 26; do grub-mkfont -s "$s" -o "$travail/boot/grub/themes/hub/ubuntu-regular-$s.pf2" /usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf 2>/dev/null; done
for s in 26 64; do grub-mkfont -b -s "$s" -o "$travail/boot/grub/themes/hub/ubuntu-bold-$s.pf2" /usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf 2>/dev/null; done
if grep -n '"@[A-Z_]*@"' "$travail/nocloud/user-data"; then echo "  ✗ valeur non remplie" >&2; exit 5; fi

printf '  … assemblage de l’image (xorriso)\n'
docker run --rm -u "$(id -u):$(id -g)" -v "$ISO:/iso/source.iso:ro" -v "$travail:/ajout:ro" -v "$PWD/sortie:/sortie" \
  hub-xorriso:1 xorriso -indev /iso/source.iso -outdev "/sortie/$SORTIE" \
    -map /ajout/hub /hub -map /ajout/nocloud /nocloud -map /ajout/nocloud-apercu /nocloud-apercu \
    -map /ajout/boot/grub/grub.cfg /boot/grub/grub.cfg -map /ajout/boot/grub/themes /boot/grub/themes \
    -boot_image any replay 2>&1 | tail -3

printf '  ✓ sortie/%s (%s)\n' "$SORTIE" "$(du -h "sortie/$SORTIE" | cut -f1)"
printf '  ✓ version du HUB : %s (%s) — disque visé : %s\n' "$(head -n 1 "$travail/hub/VERSION")" "$(head -c 7 "$travail/hub/COMMIT")" "$DISQUE"
