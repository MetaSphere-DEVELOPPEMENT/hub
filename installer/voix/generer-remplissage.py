#!/usr/bin/env python3
"""Fabrique remplissage-<langue>.txt : les mots courants que la grammaire ajoute aux commandes.

    generer-remplissage.py LISTE_DE_FRÉQUENCES GR_FST SORTIE [NOMBRE]

POURQUOI. Voir hub_voix_logique.grammaire : sans mots ordinaires à côté de nos
phrases, le décodeur force la parole de la TV dans nos commandes.

D'OÙ VIENNENT LES FRÉQUENCES. hermitdave/FrequencyWords, listes 2018 tirées des
sous-titres OpenSubtitles (content/2018/fr/fr_50k.txt, en/en_50k.txt, téléchargées le
15 septembre 2026) : de la langue parlée, des dialogues de films et de séries — ce que
dit une TV. Format : « mot fréquence » par ligne, du plus fréquent au moins fréquent.

On garde, dans l'ordre, les mots que le modèle connaît (table de Gr.fst) et qui
contiennent une lettre. Les mots de nos phrases sont retirés plus tard, par grammaire().
Rien de ce fichier ne vient du corpus de mesure : les phrases de test n'ont servi à
choisir ni la liste ni le nombre de mots.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_voix_logique as L  # noqa: E402


def main():
    if len(sys.argv) not in (4, 5):
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    liste, gr_fst, sortie = sys.argv[1:4]
    nombre = int(sys.argv[4]) if len(sys.argv) == 5 else L.NOMBRE_REMPLISSAGE
    vocabulaire = L.vocabulaire_vosk(gr_fst)
    if not vocabulaire:
        print(f"table de mots illisible : {gr_fst}", file=sys.stderr)
        return 1
    retenus, vus = [], set()
    for ligne in Path(liste).read_text(encoding="utf-8").splitlines():
        champs = ligne.split()
        if not champs:
            continue
        mot = champs[0]
        if mot in vocabulaire and mot not in vus and any(c.isalpha() for c in mot):
            retenus.append(mot)
            vus.add(mot)
            if len(retenus) == nombre:
                break
    Path(sortie).write_text("\n".join(retenus) + "\n", encoding="utf-8")
    print(f"{sortie} : {len(retenus)} mots")
    return 0


if __name__ == "__main__":
    sys.exit(main())
