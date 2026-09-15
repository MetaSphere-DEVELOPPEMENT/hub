#!/usr/bin/env python3
"""Banc d'essai de la télécommande pour les tests navigateur (test_navigateur.mjs).

Lance le vrai service sur 127.0.0.1 (ports choisis par le noyau) avec des chemins
dans DOSSIER, et un faux socket de menu qui écrit chaque datagramme reçu, une ligne
par datagramme, dans DOSSIER/menu.txt. Écrit ensuite une ligne JSON sur la sortie
standard ({"http": port, ...}) et tourne jusqu'à ce que son entrée standard se ferme.

POURQUOI UN BANC PLUTÔT QUE LE SERVICE TEL QUEL. Le test navigateur doit lire le
code (fichier d'état), voir ce qui arrive au menu et ne rien exécuter sur la machine
(ni wpctl ni gnome-session-quit) : c'est exactement ce que remplace ce fichier, et
rien d'autre. Ce n'est pas installé sur le HUB.
"""

import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_telecommande as T  # noqa: E402


def main():
    dossier = Path(sys.argv[1])
    options = set(sys.argv[2:])
    chemins = {
        "etat": dossier / "run" / "telecommande.json",
        "socket": dossier / "run" / "menu.sock",
        "jetons": dossier / "config" / "telecommande-jetons.json",
        "photos": dossier / "photos",
        "reglages": dossier / "config" / "reglages.json",
        "tls": dossier / "config" / "telecommande-tls",
    }
    chemins["socket"].parent.mkdir(parents=True, exist_ok=True)
    menu = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    menu.bind(str(chemins["socket"]))
    journal_menu = dossier / "menu.txt"
    journal_menu.write_text("")

    def ecouter():
        while True:
            try:
                texte = menu.recv(4096).decode()
            except OSError:
                return
            with journal_menu.open("a") as f:
                f.write(texte + "\n")

    threading.Thread(target=ecouter, daemon=True).start()

    def executer(commande, **_kw):
        sortie = "Volume: 0.40\n" if "get-volume" in commande else ""
        return subprocess.CompletedProcess(commande, 0, stdout=sortie, stderr="")

    routeur = T.Routeur(chemins["socket"], executer=executer, processus=lambda _n: [], kodi_http=None)
    service = T.Service(chemins, routeur=routeur, **({"https": True} if "--https" in options else {}))
    ports = T.demarrer_ecoutes(service, "127.0.0.1", 0, 0 if "--https" in options else None) \
        if hasattr(T, "demarrer_ecoutes") else None
    if ports is None:
        serveur = T.creer_serveur(service, "127.0.0.1", 0)
        threading.Thread(target=serveur.serve_forever, args=(0.05,), daemon=True).start()
        ports = {"http": serveur.server_address[1]}
    print(json.dumps(ports), flush=True)
    sys.stdin.read()


if __name__ == "__main__":
    main()
