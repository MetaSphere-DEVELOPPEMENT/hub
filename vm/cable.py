#!/usr/bin/env python3
"""Débrancher ou rebrancher le câble Ethernet de la machine virtuelle (moniteur QEMU).

POURQUOI UN CÂBLE ET PAS « PAS DE CARTE ». Sur le M720q, le 16/09/2026, eno1 existait
mais sans porteuse (« unavailable ») : l'installateur a décidé seul de passer hors
ligne. Une VM sans carte réseau, ou avec un réseau isolé qui distribue quand même une
adresse, ne prend pas le même chemin. `set_link off` reproduit la carte présente, câble
débranché.

    ./cable.py debranche             pendant que la VM tourne
    ./cable.py debranche --demarrer  VM lancée en pause (-S) : débranche puis démarre
    ./cable.py branche               « on branche le câble »
"""
import os, socket, sys

ETATS = {"debranche": "off", "branche": "on"}
if len(sys.argv) < 2 or sys.argv[1] not in ETATS:
    print(__doc__.strip().splitlines()[-3:], file=sys.stderr)
    sys.exit(2)

# Chemin relatif : un chemin de socket trop long est refusé (108 octets sous Linux).
os.chdir(os.path.dirname(os.path.abspath(__file__)))
s = socket.socket(socket.AF_UNIX)
s.connect("moniteur.sock")
s.settimeout(3)


def lire():
    recu = b""
    try:
        while not recu.endswith(b"(qemu) "):
            recu += s.recv(4096)
    except socket.timeout:
        pass
    return recu.decode(errors="replace")


def commande(texte):
    s.sendall((texte + "\n").encode())
    return lire()


# La bannière d'abord : sinon chaque commande lirait la réponse de la précédente, et un
# refus de QEMU passerait pour un succès.
lire()
# « reseau » : l'identifiant du -netdev dans essayer-cle.sh.
reponse = commande(f"set_link reseau {ETATS[sys.argv[1]]}")
if "not found" in reponse or "rror" in reponse:
    print(f"refusé par QEMU : {reponse.strip()}", file=sys.stderr)
    sys.exit(1)
if "--demarrer" in sys.argv[2:]:
    commande("cont")
print(f"câble {sys.argv[1]}" + (", machine démarrée" if "--demarrer" in sys.argv[2:] else ""))
