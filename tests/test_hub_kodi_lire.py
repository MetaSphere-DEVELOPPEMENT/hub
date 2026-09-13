"""hub-kodi-lire contre un faux Kodi JSON-RPC : attente, requête de reprise."""

import importlib.machinery
import importlib.util
import json
import socket
import subprocess
import threading
import unittest
from pathlib import Path

chemin = Path(__file__).resolve().parent.parent / "installer" / "hub-kodi-lire"
chargeur = importlib.machinery.SourceFileLoader("hub_kodi_lire", str(chemin))
spec = importlib.util.spec_from_loader("hub_kodi_lire", chargeur)
lire = importlib.util.module_from_spec(spec)
chargeur.exec_module(lire)


class FauxKodi:
    """Répond « pong » au ping et note chaque requête, en coupant les réponses en deux
    paquets comme peut le faire un vrai serveur."""

    def __init__(self):
        self.serveur = socket.create_server(("127.0.0.1", 0))
        self.port = self.serveur.getsockname()[1]
        self.requetes = []
        threading.Thread(target=self.servir, daemon=True).start()

    def servir(self):
        while True:
            try:
                client, _ = self.serveur.accept()
            except OSError:
                return
            with client:
                donnees = json.loads(client.recv(65536))
                self.requetes.append(donnees)
                reponse = json.dumps({"id": donnees["id"], "jsonrpc": "2.0",
                                      "result": "pong" if donnees["method"] == "JSONRPC.Ping" else "OK"}).encode()
                client.sendall(reponse[:10])
                client.sendall(reponse[10:])

    def fermer(self):
        self.serveur.close()


class HubKodiLire(unittest.TestCase):
    def test_requete_de_reprise(self):
        r = json.loads(lire.requete_lecture("smb://nas/film.mkv"))
        self.assertEqual(r["method"], "Player.Open")
        self.assertEqual(r["params"], {"item": {"file": "smb://nas/film.mkv"}, "options": {"resume": True}})

    def test_attend_que_kodi_reponde_puis_demande_la_lecture(self):
        kodi = FauxKodi()
        self.addCleanup(kodi.fermer)
        processus = subprocess.Popen(["sleep", "5"])
        self.addCleanup(processus.kill)
        self.assertTrue(lire.attendre_jsonrpc(processus, attente=5, port=kodi.port, pause=.05))
        reponse = lire.envoyer(lire.requete_lecture("/media/dune.mkv"), port=kodi.port)
        self.assertEqual(reponse["result"], "OK")
        self.assertEqual(kodi.requetes[-1]["params"]["item"]["file"], "/media/dune.mkv")

    def test_abandonne_si_kodi_se_ferme_avant_de_repondre(self):
        processus = subprocess.Popen(["true"])
        processus.wait()
        libre = socket.create_server(("127.0.0.1", 0))
        port = libre.getsockname()[1]
        libre.close()
        self.assertFalse(lire.attendre_jsonrpc(processus, attente=5, port=port, pause=.05))

    def test_sans_fichier_refuse(self):
        self.assertEqual(lire.main([]), 2)


if __name__ == "__main__":
    unittest.main()
