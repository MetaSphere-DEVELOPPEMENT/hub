#!/usr/bin/env python3
"""Poser quelques réglages dans guisettings.xml de Kodi sans toucher aux autres.

POURQUOI PAS UN FICHIER COMPLET. guisettings.xml porte tous les réglages de
l'utilisateur (langue, audio, affichage…). Le remplacer par une copie du dépôt
effacerait ce qu'il a réglé devant la TV à chaque relance de l'installateur. On ne
modifie donc que les identifiants demandés ; s'il n'existe pas encore (Kodi jamais
lancé), on crée un fichier qui ne contient qu'eux, et Kodi complète le reste par ses
valeurs par défaut au premier démarrage.

L'attribut default="true" est retiré d'un réglage qu'on modifie : Kodi le pose sur
les valeurs par défaut, et le laisser ferait passer notre choix pour un défaut.

    regler-guisettings.py verifier|appliquer CHEMIN id=valeur…
    code 0 : conforme (verifier) ou écrit (appliquer) · 1 : à modifier (verifier)
"""

import os
import sys
import xml.etree.ElementTree as ET


def main(arguments):
    if len(arguments) < 3 or arguments[0] not in ("verifier", "appliquer"):
        print(__doc__, file=sys.stderr)
        return 2
    action, chemin = arguments[0], arguments[1]
    voulus = dict(a.split("=", 1) for a in arguments[2:])

    if os.path.exists(chemin):
        arbre = ET.parse(chemin)
        racine = arbre.getroot()
    else:
        racine = ET.Element("settings", version="2")
        arbre = ET.ElementTree(racine)

    existants = {e.get("id"): e for e in racine.iter("setting")}
    a_changer = [k for k, v in voulus.items() if k not in existants or (existants[k].text or "") != v]
    if action == "verifier":
        return 1 if a_changer else 0

    for cle in a_changer:
        element = existants.get(cle)
        if element is None:
            element = ET.SubElement(racine, "setting", id=cle)
        element.text = voulus[cle]
        element.attrib.pop("default", None)

    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    temporaire = chemin + ".hub"
    arbre.write(temporaire, encoding="utf-8")
    # Un remplacement atomique : une coupure pendant l'écriture ne laisse pas à Kodi
    # un fichier tronqué, qu'il remplacerait par des réglages vierges.
    os.replace(temporaire, chemin)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
