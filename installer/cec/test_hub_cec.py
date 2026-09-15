#!/usr/bin/env python3
"""Tests de la télécommande CEC, sans adaptateur, sans TV, sans cec-client.

Lancer (depuis installer/cec) : python3 -m unittest test_hub_cec

CE QUI EST PROUVÉ ICI. La lecture des lignes au format exact de libcec 7.1.1, la
reconnaissance des appuis (répétés, longs, sans relâcher), la décision menu / Kodi /
service web / bureau, le partage de l'adaptateur avec Kodi, les ordres à la TV, et le
service entier contre un faux cec-client qui rejoue une trace. CE QUI NE L'EST PAS :
qu'une Sony KD-55XG70 envoie bien ces trames-là (voir README.md).
"""

import ast
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import hub_cec_logique as C  # noqa: E402

TRACE = ICI / "traces" / "sony-bravia-navigation.log"
SIMULATEUR = ICI / "simulateur_cec_client.py"


def charger_service():
    import importlib.util
    spec = importlib.util.spec_from_file_location("hub_cec", ICI / "hub-cec.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lignes_trace():
    return [l.rstrip("\n") for l in TRACE.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


class LectureDesLignes(unittest.TestCase):
    def test_appui_et_relache(self):
        self.assertEqual(C.lire_ligne("TRAFFIC: [            2000]\t>> 01:44:02"),
                         {"type": "trame", "source": 0, "destination": 1, "opcode": 0x44, "donnees": [2]})
        self.assertEqual(C.lire_ligne("TRAFFIC: [            2150]\t>> 01:45")["opcode"], 0x45)

    def test_trames_emises_et_texte_ignores(self):
        # « << » est ce que le HUB envoie lui-même : ce n'est pas une touche.
        self.assertIsNone(C.lire_ligne("TRAFFIC: [             140]\t<< 1f:84:10:00:01"))
        self.assertIsNone(C.lire_ligne("DEBUG:   [            2001]\tkey pressed: down (2) current(ff) duration(0)"))
        self.assertIsNone(C.lire_ligne("NOTICE:  [             102]\tconnection opened"))
        self.assertIsNone(C.lire_ligne(""))

    def test_diffusion_et_interrogation(self):
        self.assertEqual(C.lire_ligne("TRAFFIC: [           10000]\t>> 0f:36"),
                         {"type": "trame", "source": 0, "destination": 15, "opcode": 0x36, "donnees": []})
        self.assertEqual(C.lire_ligne("TRAFFIC: [            9800]\t>> 01")["opcode"], None)

    def test_etats_de_connexion(self):
        self.assertEqual(C.lire_ligne("waiting for input"), {"type": "ouvert"})
        self.assertEqual(C.lire_ligne("unable to open the device on port /dev/ttyACM0")["type"], "echec")
        self.assertEqual(C.lire_ligne("no serial port given. trying autodetect: FAILED")["type"], "echec")

    def test_toute_la_trace_se_lit(self):
        types = [(C.lire_ligne(l) or {}).get("type") for l in lignes_trace()]
        self.assertEqual(types.count("ouvert"), 1)
        self.assertEqual(types.count("echec"), 0)
        self.assertEqual(types.count("trame"), 22)


class Appuis(unittest.TestCase):
    def rejouer(self, lignes, clavier=None):
        clavier = clavier or C.Clavier()
        evenements = []
        for ligne in lignes:
            trame = C.lire_ligne(ligne)
            if trame and trame["type"] == "trame":
                instant = int(ligne.split("[")[1].split("]")[0]) / 1000
                evenements += clavier.tic(instant) + clavier.trame(trame, instant)
        return evenements + clavier.tic(1e9)

    def test_trace_sony(self):
        self.assertEqual(self.rejouer(lignes_trace()),
                         ["bas", "bas", "ok", "retour", "droite", "droite", "droite", "accueil"])

    def test_retour_court_attend_le_relacher(self):
        c = C.Clavier()
        self.assertEqual(c.trame({"type": "trame", "opcode": 0x44, "donnees": [0x0D]}, 0.0), [])
        self.assertEqual(c.trame({"type": "trame", "opcode": 0x45, "donnees": []}, 0.2), ["retour"])

    def test_tv_sans_relacher(self):
        # Une TV qui n'envoie ni répétition ni « released » : relâché implicite.
        c = C.Clavier()
        c.trame({"type": "trame", "opcode": 0x44, "donnees": [0x0D]}, 0.0)
        self.assertEqual(c.tic(0.5), [])
        self.assertEqual(c.tic(0.9), ["retour"])
        self.assertEqual(c.tic(5.0), [])

    def test_meme_touche_apres_silence_est_un_nouvel_appui(self):
        c = C.Clavier()
        self.assertEqual(c.trame({"type": "trame", "opcode": 0x44, "donnees": [0x00]}, 0.0), ["ok"])
        self.assertEqual(c.trame({"type": "trame", "opcode": 0x44, "donnees": [0x00]}, 2.0), ["ok"])
        # répétition d'une touche non répétable : rien de plus
        self.assertEqual(c.trame({"type": "trame", "opcode": 0x44, "donnees": [0x00]}, 2.4), [])

    def test_autre_touche_pendant_retour_tenu(self):
        c = C.Clavier()
        c.trame({"type": "trame", "opcode": 0x44, "donnees": [0x0D]}, 0.0)
        self.assertEqual(c.trame({"type": "trame", "opcode": 0x44, "donnees": [0x01]}, 0.3), ["retour", "haut"])

    def test_appui_long_par_tic_seul(self):
        c = C.Clavier()
        for t in (0.0, 0.45, 0.9):
            c.trame({"type": "trame", "opcode": 0x44, "donnees": [0x0D]}, t)
        self.assertEqual(c.tic(1.25), ["accueil"])
        self.assertEqual(c.trame({"type": "trame", "opcode": 0x45, "donnees": []}, 1.4), [])

    def test_touche_inconnue_ignoree(self):
        c = C.Clavier()
        self.assertEqual(c.trame({"type": "trame", "opcode": 0x44, "donnees": [0x72]}, 0.0), [])
        self.assertEqual(c.trame({"type": "trame", "opcode": 0x44, "donnees": []}, 0.1), [])


class Decision(unittest.TestCase):
    def test_menu(self):
        for nom in ("haut", "bas", "gauche", "droite", "ok", "retour"):
            self.assertEqual(C.destination(nom, "menu"), ("menu", nom))
        self.assertEqual(C.destination("accueil", "menu"), ("menu", "retour"))
        self.assertIsNone(C.destination("lecture", "menu"))

    def test_noms_du_menu_existent_dans_hub_menu(self):
        source = ICI.parent / "hub-menu.py"
        for noeud in ast.parse(source.read_text(encoding="utf-8")).body:
            if isinstance(noeud, ast.Assign) and any(getattr(c, "id", None) == "COMMANDES" for c in noeud.targets):
                self.assertLessEqual(C.VERS_MENU, set(ast.literal_eval(noeud.value)))
                return
        self.fail("COMMANDES introuvable dans hub-menu.py")

    def test_kodi_en_relais(self):
        self.assertEqual(C.destination("bas", "kodi"), ("kodi", "Input.Down", None))
        self.assertEqual(C.destination("retour", "kodi"), ("kodi", "Input.Back", None))
        self.assertEqual(C.destination("lecture-pause", "kodi"),
                         ("kodi", "Input.ExecuteAction", {"action": "playpause"}))
        self.assertEqual(C.destination("accueil", "kodi"), ("kodi-quitter",))

    def test_kodi_qui_tient_l_adaptateur(self):
        for nom in ("bas", "accueil", "retour"):
            self.assertIsNone(C.destination(nom, "kodi", partage="ceder"))

    def test_service_web_seul_l_appui_long(self):
        self.assertEqual(C.destination("accueil", "web"), ("web-fermer",))
        for nom in ("retour", "ok", "bas"):
            self.assertIsNone(C.destination(nom, "web"))

    def test_bureau_et_rien(self):
        for nom in ("retour", "accueil", "ok"):
            self.assertIsNone(C.destination(nom, "bureau"))
            self.assertIsNone(C.destination(nom, None))

    def test_contexte_meme_ordre_que_la_voix(self):
        self.assertEqual(C.contexte(True, True, True, True), "menu")
        self.assertEqual(C.contexte(False, True, True, True), "web")
        self.assertEqual(C.contexte(False, False, True, True), "kodi")
        self.assertEqual(C.contexte(False, False, False, True), "bureau")
        self.assertIsNone(C.contexte(False, False, False, False))

    def test_partage(self):
        self.assertTrue(C.tenir_adaptateur("relais", kodi_tourne=True))
        self.assertTrue(C.tenir_adaptateur("ceder", kodi_tourne=False))
        self.assertFalse(C.tenir_adaptateur("ceder", kodi_tourne=True))


class Environnement(unittest.TestCase):
    def test_adaptateur_dans_sysfs(self):
        racine = Path(tempfile.mkdtemp())
        self.assertFalse(C.adaptateur_present(str(racine)))
        (racine / "1-1").mkdir()
        (racine / "1-1" / "idVendor").write_text("046d\n")
        (racine / "1-1" / "idProduct").write_text("c52b\n")
        (racine / "usb1").mkdir()  # concentrateur sans identifiants lisibles
        self.assertFalse(C.adaptateur_present(str(racine)))
        (racine / "1-2").mkdir()
        (racine / "1-2" / "idVendor").write_text("2548\n")
        (racine / "1-2" / "idProduct").write_text("1002\n")
        self.assertTrue(C.adaptateur_present(str(racine)))
        self.assertFalse(C.adaptateur_present("/nexiste/pas"))

    def test_commande(self):
        self.assertEqual(C.commande_cec_client(), ["cec-client", "-t", "r", "-o", "HUB", "-d", "13"])
        self.assertEqual(C.commande_cec_client(port_hdmi=2)[-2:], ["-p", "2"])
        self.assertNotIn("-p", C.commande_cec_client(port_hdmi=99))

    def test_reglages(self):
        dossier = Path(tempfile.mkdtemp())
        chemin = dossier / "reglages.json"
        defauts = {"partage": "relais", "port_hdmi": None, "allumer_tv": True, "veille_tv": True}
        self.assertEqual(C.lire_reglages(chemin), defauts)
        chemin.write_text("{abîmé")
        self.assertEqual(C.lire_reglages(chemin), defauts)
        chemin.write_text(json.dumps({"systeme": {"cec": {"partage": "ceder", "portHdmi": 3,
                                                          "allumerTv": False, "veilleTv": False}}}))
        self.assertEqual(C.lire_reglages(chemin), {"partage": "ceder", "port_hdmi": 3,
                                                   "allumer_tv": False, "veille_tv": False})
        chemin.write_text(json.dumps({"systeme": {"cec": {"partage": "n-importe", "portHdmi": True,
                                                          "allumerTv": "oui"}}}))
        self.assertEqual(C.lire_reglages(chemin), defauts)


class FausseVoix:
    """Ce que le service demande à hub_voix_logique, réglable par le test."""
    NOMS_KODI = {"kodi.bin"}
    NOMS_BUREAU = {"gnome-shell"}

    def __init__(self):
        self.kodi = False
        self.quitter = []

    def processus(self, noms):
        return [1234] if self.kodi and noms == self.NOMS_KODI else []

    def web_en_cours(self, _chemin):
        return False

    def quitter_kodi_tcp(self):
        self.quitter.append(True)
        return True


class ServiceContreSimulateur(unittest.TestCase):
    """Le service entier, avec le faux cec-client qui rejoue la trace Sony deux fois plus vite."""

    VITESSE = 2

    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp())
        self.execution = self.dossier / "run"
        self.execution.mkdir()
        self.usb = self.dossier / "usb"
        (self.usb / "1-2").mkdir(parents=True)
        (self.usb / "1-2" / "idVendor").write_text("2548\n")
        (self.usb / "1-2" / "idProduct").write_text("1002\n")
        self.journal = self.dossier / "sim.log"
        self.env = {"HUB_CEC_SIM_TRACE": str(TRACE), "HUB_CEC_SIM_VITESSE": str(self.VITESSE),
                    "HUB_CEC_SIM_JOURNAL": str(self.journal)}
        self.ancien_env = {k: os.environ.get(k) for k in list(self.env) + ["HUB_KODI_PORT", "HUB_CEC_SIM_ECHEC"]}
        os.environ.update(self.env)
        self.hub_cec = charger_service()
        self.voix = FausseVoix()
        # Un programme exécutable qui lance le simulateur avec le même Python.
        self.programme = self.dossier / "cec-client"
        self.programme.write_text(f"#!/bin/sh\nexec {sys.executable} {SIMULATEUR} \"$@\"\n")
        self.programme.chmod(0o755)

    def tearDown(self):
        for cle, valeur in self.ancien_env.items():
            if valeur is None:
                os.environ.pop(cle, None)
            else:
                os.environ[cle] = valeur

    def service(self):
        s = self.hub_cec.Service(programme=str(self.programme), reglages=self.dossier / "reglages.json",
                                 dossier_execution=self.execution, racine_usb=str(self.usb), voix=self.voix)
        s.clavier = C.Clavier(appui_long=C.APPUI_LONG_S / self.VITESSE, relache=C.RELACHE_IMPLICITE_S / self.VITESSE)
        return s

    def faire_tourner(self, service, duree):
        fin = time.monotonic() + duree
        actions = []
        while time.monotonic() < fin:
            actions += service.etape(attente=0.02)
        return actions

    def ordres(self):
        return [l[len("ordre : "):] for l in self.journal.read_text().splitlines() if l.startswith("ordre : ")] \
            if self.journal.exists() else []

    def test_menu_ouvert(self):
        menu = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        menu.bind(str(self.execution / "menu.sock"))
        menu.settimeout(0.01)
        service = self.service()
        service.ouvrir_controle()
        try:
            self.faire_tourner(service, 10.5 / self.VITESSE + 0.8)
            recus = []
            while True:
                try:
                    recus.append(menu.recv(100).decode())
                except socket.timeout:
                    break
            self.assertEqual(recus, ["bas", "bas", "ok", "retour", "droite", "droite", "droite", "retour"])
            # À l'ouverture : TV allumée et entrée basculée, une seule fois par démarrage.
            self.assertEqual(self.ordres(), ["on 0", "as"])
            self.assertTrue((self.execution / "cec-tv-allumee").exists())

            # Ordre venu d'un autre programme (hub-cec.py --tv veille).
            self.assertTrue(C.envoyer(self.execution / "cec.sock", "tv:veille"))
            actions = self.faire_tourner(service, 0.3)
            self.assertIn(("ordre", "tv:veille", True), actions)
            self.assertEqual(self.ordres()[-1], "standby 0")
        finally:
            service.arret()
            menu.close()
        self.assertEqual(self.ordres()[-1], "q")
        self.assertFalse((self.execution / "cec.sock").exists())

        # Service relancé (changement de mode) : la TV n'est pas rallumée.
        self.journal.unlink()
        service = self.service()
        try:
            self.faire_tourner(service, 0.6)
        finally:
            service.arret()
        self.assertEqual(self.ordres(), ["q"])

    def test_kodi_en_relais(self):
        recu = []
        serveur = socket.socket()
        serveur.bind(("127.0.0.1", 0))
        serveur.listen(20)
        serveur.settimeout(0.2)
        os.environ["HUB_KODI_PORT"] = str(serveur.getsockname()[1])
        arret = threading.Event()

        def kodi():
            while not arret.is_set():
                try:
                    client, _ = serveur.accept()
                except socket.timeout:
                    continue
                recu.append(json.loads(client.recv(4096)))
                client.sendall(b'{"id":1,"jsonrpc":"2.0","result":"OK"}')
                client.close()

        fil = threading.Thread(target=kodi)
        fil.start()
        self.voix.kodi = True
        (self.execution / "cec-tv-allumee").touch()
        service = self.service()
        try:
            self.faire_tourner(service, 10.5 / self.VITESSE + 0.8)
        finally:
            service.arret()
            arret.set()
            fil.join()
            serveur.close()
        self.assertEqual([r["method"] for r in recu],
                         ["Input.Down", "Input.Down", "Input.Select", "Input.Back",
                          "Input.Right", "Input.Right", "Input.Right"])
        self.assertEqual(self.voix.quitter, [True])
        self.assertEqual(self.ordres(), ["q"])  # TV déjà allumée à ce démarrage

    def test_ceder_l_adaptateur_a_kodi(self):
        (self.dossier / "reglages.json").write_text(json.dumps({"systeme": {"cec": {"partage": "ceder"}}}))
        (self.execution / "cec-tv-allumee").touch()
        os.environ["HUB_CEC_SIM_TRACE"] = ""
        self.voix.kodi = True
        service = self.service()
        try:
            self.faire_tourner(service, 0.5)
            self.assertIsNone(service.client)
            self.assertFalse(self.journal.exists())  # jamais lancé tant que Kodi tourne

            self.voix.kodi = False
            service.prochain_essai = 0.0
            self.faire_tourner(service, 1.0)
            self.assertTrue(service.client and service.client.ouvert)
            # Kodi a envoyé « Inactive Source » en quittant : on reprend l'entrée.
            self.assertEqual(self.ordres(), ["as"])

            self.voix.kodi = True
            self.faire_tourner(service, 0.5)
            self.assertIsNone(service.client)
            self.assertEqual(self.ordres(), ["as", "q"])
        finally:
            service.arret()

    def test_port_verrouille(self):
        os.environ["HUB_CEC_SIM_ECHEC"] = "verrou"
        service = self.service()
        try:
            self.faire_tourner(service, 0.8)
            self.assertIsNone(service.client)
            # Pas de relance en boucle : un essai toutes les PERIODE_ADAPTATEUR secondes.
            lancements = [l for l in self.journal.read_text().splitlines() if l.startswith("lancé")]
            self.assertEqual(len(lancements), 1)
        finally:
            service.arret()

    def test_sans_adaptateur_rien_n_est_lance(self):
        (self.usb / "1-2" / "idVendor").write_text("046d\n")
        service = self.service()
        try:
            self.faire_tourner(service, 0.4)
        finally:
            service.arret()
        self.assertFalse(self.journal.exists())

    def test_ligne_de_commande_tv_sans_service(self):
        env = dict(os.environ, XDG_RUNTIME_DIR=str(self.dossier / "vide"))
        r = subprocess.run([sys.executable, str(ICI / "hub-cec.py"), "--tv", "allumer"],
                           env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 1)
        self.assertIn("n'écoute pas", r.stderr)


if __name__ == "__main__":
    unittest.main()
