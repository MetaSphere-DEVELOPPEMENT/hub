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

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
RACINE=$(cd .. && pwd)
ISO="$HOME/Téléchargements/ubuntu-26.04.1-desktop-amd64.iso"
DISQUE=/dev/nvme0n1
SORTIE=hub-cle.iso
while [ $# -gt 0 ]; do
  case "$1" in
    --disque) shift; DISQUE="$1" ;;
    --iso) shift; ISO="$1" ;;
    --sortie) shift; SORTIE="$1" ;;
    *) echo "argument inconnu : $1" >&2; exit 2 ;;
  esac
  shift
done

attendue=$(awk '$2 ~ /ubuntu-26.04.1-desktop-amd64.iso$/ {print $1}' "$RACINE/vm/SHA256SUMS")
printf '  … vérification de l’ISO\n'
[ "$(sha256sum "$ISO" | cut -d' ' -f1)" = "$attendue" ] || { echo "  ✗ empreinte de l'ISO fausse" >&2; exit 3; }

[ -z "$(git -C "$RACINE" status --porcelain -- installer audit cle)" ] \
  || { echo "  ✗ modifications non commitées dans installer/ audit/ cle/ : la clé doit contenir une version identifiable" >&2; exit 4; }

travail=$(mktemp -d "$PWD/.construction.XXXX")
trap 'rm -rf "$travail"' EXIT
mkdir -p "$travail/hub" "$travail/nocloud" "$travail/nocloud-apercu" "$travail/boot/grub/themes/hub" sortie

git -C "$RACINE" archive HEAD installer audit cle ARCHITECTURE.md CLAUDE.md | tar -x -C "$travail/hub"
git -C "$RACINE" describe --always --dirty > "$travail/hub/VERSION"

# Un mot de passe propre à cette clé : il sert à sudo et au bureau, jamais à l'allumage.
if [ ! -f sortie/MOT-DE-PASSE.txt ]; then
  mots=(salon kodi aurore braise ocean nebuleuse lumiere canape cinema etoile)
  printf '%s-%s-%s\n' "${mots[RANDOM%10]}" "${mots[RANDOM%10]}" "$((RANDOM%9000+1000))" > sortie/MOT-DE-PASSE.txt
  chmod 600 sortie/MOT-DE-PASSE.txt
fi
hache=$(openssl passwd -6 "$(cat sortie/MOT-DE-PASSE.txt)")
cle_ssh=$(cat "$HOME/.ssh/id_rsa.pub")

sed -e "s|@MOT_DE_PASSE_HACHE@|$hache|" -e "s|@CLE_SSH@|$cle_ssh|" -e "s|@DISQUE@|$DISQUE|" user-data.modele > "$travail/nocloud/user-data"
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
printf '  ✓ version du HUB : %s — disque visé : %s\n' "$(cat "$travail/hub/VERSION")" "$DISQUE"
