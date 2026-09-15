#!/bin/sh
# Modèles Vosk de la commande vocale — installer/voix/telecharger-modele.sh [dossier]
#
# Les modèles ne sont pas dans le dépôt : 80 Mo de binaires qui ne changent jamais
# n'ont rien à faire dans l'historique git. On les prend à la source officielle
# (alphacephei.com, les auteurs de Vosk) et on vérifie leur empreinte : un
# téléchargement tronqué ou un fichier remplacé sur le serveur doit arrêter
# l'installation, pas donner un HUB qui n'entend rien sans dire pourquoi.
#
# Empreintes calculées au téléchargement du 13 septembre 2026 (sha256sum).
#
# Dossier par défaut : /opt/hub-voix/modeles (celui que lit hub-voix.py).
# Sans droit d'écriture dessus, lancer avec sudo ou donner un autre dossier.

set -eu

DOSSIER=${1:-/opt/hub-voix/modeles}
SOURCE=https://alphacephei.com/vosk/models

# nom  sha256
MODELES="vosk-model-small-fr-0.22 cabf6180e177eb9b3a9a9d43a437bd5e549f3a7d09525e5d69a3fed787be12ad
vosk-model-small-en-us-0.15 30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498"

for outil in curl sha256sum unzip; do
  command -v "$outil" >/dev/null || { echo "telecharger-modele : $outil manquant" >&2; exit 1; }
done

mkdir -p "$DOSSIER"
temporaire=$(mktemp -d "$DOSSIER/.telechargement.XXXXXX")
trap 'rm -rf "$temporaire"' EXIT

echo "$MODELES" | while read -r nom empreinte; do
  if [ -f "$DOSSIER/$nom/am/final.mdl" ]; then
    echo "$nom : déjà présent"
    continue
  fi
  echo "$nom : téléchargement"
  # --retry : la liaison du salon a déjà montré qu'elle n'est pas fiable
  # (ARCHITECTURE.md, contrainte n° 1).
  curl -fL --retry 3 --retry-delay 5 -o "$temporaire/$nom.zip" "$SOURCE/$nom.zip"
  if ! echo "$empreinte  $temporaire/$nom.zip" | sha256sum -c --quiet -; then
    echo "$nom : empreinte inattendue, modèle refusé" >&2
    exit 1
  fi
  unzip -q "$temporaire/$nom.zip" -d "$temporaire"
  # Déplacement en une fois : hub-voix.py ne voit jamais un modèle à moitié extrait.
  mv "$temporaire/$nom" "$DOSSIER/$nom"
  rm -f "$temporaire/$nom.zip"
  echo "$nom : installé dans $DOSSIER"
done
