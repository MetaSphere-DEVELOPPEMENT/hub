#!/usr/bin/env python3
"""Faux cec-client pour éprouver hub-cec sans adaptateur ni TV.

    simulateur_cec_client.py [options de cec-client ignorées]

Environnement :
  HUB_CEC_SIM_TRACE    trace à rejouer (format de cec-client, voir traces/)
  HUB_CEC_SIM_VITESSE  facteur de temps (défaut 1 ; 10 = dix fois plus vite)
  HUB_CEC_SIM_JOURNAL  fichier où consigner la ligne de commande et les ordres reçus
  HUB_CEC_SIM_ECHEC    « verrou » : se comporte comme un port déjà tenu par Kodi

Comme le vrai : les lignes d'en-tête sortent tout de suite, les trames à leur
horodatage, chaque ordre reçu sur l'entrée (« on 0 », « standby 0 », « as ») produit
la trame émise que libcec journaliserait, et « q » termine le programme.
"""

import os
import re
import select
import sys
import time

# Trames qu'émettrait libcec pour chaque ordre, depuis l'adresse logique 1 (norme CEC :
# 0x04 Image View On, 0x36 Standby, 0x82 Active Source avec l'adresse physique 1.0.0.0).
TRAMES_ORDRES = {"on 0": "<< 10:04", "standby 0": "<< 10:36", "as": "<< 1f:82:10:00"}


def consigner(texte):
    chemin = os.environ.get("HUB_CEC_SIM_JOURNAL")
    if chemin:
        with open(chemin, "a", encoding="utf-8") as f:
            f.write(texte + "\n")


def ecrire(texte):
    sys.stdout.write(texte + "\n")
    sys.stdout.flush()


def main():
    consigner("lancé : " + " ".join(sys.argv[1:]))
    vitesse = float(os.environ.get("HUB_CEC_SIM_VITESSE", "1"))
    if os.environ.get("HUB_CEC_SIM_ECHEC") == "verrou":
        ecrire("opening a connection to the CEC adapter...")
        ecrire("ERROR:   [             10]\tcould not open a connection (try 1)")
        ecrire("unable to open the device on port /dev/ttyACM0")
        return 1

    lignes = []
    trace = os.environ.get("HUB_CEC_SIM_TRACE")
    if trace:
        with open(trace, encoding="utf-8") as f:
            lignes = [l.rstrip("\n") for l in f if l.strip() and not l.startswith("#")]
    else:
        # Sans trace : un adaptateur qui s'ouvre et une TV qui ne dit rien.
        lignes = ["opening a connection to the CEC adapter...", "waiting for input"]

    debut = time.monotonic()
    horloge_trace = 0
    entree = sys.stdin.fileno()
    tampon = b""
    while True:
        attente = 0.05
        if lignes:
            m = re.match(r"^[A-Z]+:\s*\[\s*(\d+)\]", lignes[0])
            if m:
                horloge_trace = int(m.group(1))
            echeance = debut + horloge_trace / 1000 / vitesse
            if time.monotonic() >= echeance:
                ecrire(lignes.pop(0))
                continue
            attente = min(attente, max(0.0, echeance - time.monotonic()))
        prets, _, _ = select.select([entree], [], [], attente)
        if not prets:
            continue
        morceau = os.read(entree, 4096)
        if not morceau:
            return 0
        tampon += morceau
        while b"\n" in tampon:
            ligne, tampon = tampon.split(b"\n", 1)
            ordre = ligne.decode().strip()
            consigner("ordre : " + ordre)
            if ordre == "q":
                return 0
            if ordre in TRAMES_ORDRES:
                instant = int((time.monotonic() - debut) * 1000 * vitesse)
                ecrire(f"TRAFFIC: [{instant:16d}]\t{TRAMES_ORDRES[ordre]}")


if __name__ == "__main__":
    sys.exit(main())
