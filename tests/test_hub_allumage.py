"""Allumage et extinction programmés : calcul des horaires, commandes produites, réveil détecté.

Aucune commande n'est exécutée : rtcwake et systemd-run sont remplacés par un faux
qui note ce qu'on lui demande (ce poste de travail ne doit ni s'éteindre ni se réveiller).

    python3 -m unittest tests/test_hub_allumage.py
"""

import importlib.machinery
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

RACINE = Path(__file__).resolve().parent.parent
chargeur = importlib.machinery.SourceFileLoader("hub_allumage", str(RACINE / "installer" / "allumage" / "hub-allumage"))
spec = importlib.util.spec_from_loader("hub_allumage", chargeur)
al = importlib.util.module_from_spec(spec)
chargeur.exec_module(al)

# Mardi 15 septembre 2026.
MARDI_22H = datetime(2026, 9, 15, 22, 0)
TOUS_LES_JOURS_7H = ["07:00"] * 7


class Horaires(unittest.TestCase):
    def test_lendemain_matin(self):
        self.assertEqual(al.prochain(TOUS_LES_JOURS_7H, MARDI_22H), datetime(2026, 9, 16, 7, 0))

    def test_meme_jour_si_pas_encore_passe(self):
        self.assertEqual(al.prochain(TOUS_LES_JOURS_7H, datetime(2026, 9, 15, 6, 0)), datetime(2026, 9, 15, 7, 0))

    def test_saute_les_jours_sans_horaire(self):
        # Semaine seulement (lundi → vendredi) : vendredi soir, prochain réveil lundi.
        semaine = ["07:00"] * 5 + [None, None]
        self.assertEqual(al.prochain(semaine, datetime(2026, 9, 18, 22, 0)), datetime(2026, 9, 21, 7, 0))

    def test_meme_jour_la_semaine_suivante(self):
        mardi = [None, "07:00", None, None, None, None, None]
        self.assertEqual(al.prochain(mardi, datetime(2026, 9, 15, 8, 0)), datetime(2026, 9, 22, 7, 0))

    def test_une_minute_de_marge(self):
        # 6 h 59 min 30 : trop tard pour armer 7 h 00 de façon fiable.
        self.assertEqual(al.prochain(TOUS_LES_JOURS_7H, datetime(2026, 9, 15, 6, 59, 30)), datetime(2026, 9, 16, 7, 0))

    def test_rien_de_programme(self):
        self.assertIsNone(al.prochain([None] * 7, MARDI_22H))
        self.assertIsNone(al.prochain(None, MARDI_22H))
        self.assertIsNone(al.prochain(["7h"] * 7, MARDI_22H), "format refusé")
        self.assertIsNone(al.prochain(["07:00"] * 3, MARDI_22H), "sept jours exactement")


class Configuration(unittest.TestCase):
    def test_lue_dans_les_reglages_du_menu(self):
        reglages = {"profils": [{"id": "a"}], "systeme": {"allumage": {"reveils": TOUS_LES_JOURS_7H, "extinctions": ["23:30"] * 7}}}
        config = al.configuration(reglages)
        self.assertEqual(config["reveils"], TOUS_LES_JOURS_7H)
        self.assertEqual(config["extinctions"], ["23:30"] * 7)

    def test_valeurs_etrangeres_ecartees(self):
        # Service root lisant un fichier de l'utilisateur : rien d'autre que HH:MM ne passe.
        reglages = {"systeme": {"allumage": {"reveils": ["07:00; rm -rf /", 7, None, "24:00", "7:05", "", "06:30"]}}}
        self.assertEqual(al.configuration(reglages)["reveils"], [None, None, None, None, None, None, "06:30"])
        self.assertEqual(al.configuration(None), {"reveils": [None] * 7, "extinctions": [None] * 7})


class Appliquer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.etat = Path(self._tmp.name) / "allumage.json"
        self.commandes = []

    def tearDown(self):
        self._tmp.cleanup()

    def executer(self, commande, **_):
        self.commandes.append(commande)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_arme_le_reveil_et_l_extinction(self):
        config = {"reveils": TOUS_LES_JOURS_7H, "extinctions": ["23:30"] * 7}
        resultat = al.appliquer(config, MARDI_22H, executer=self.executer, etat=self.etat)
        reveil = int(datetime(2026, 9, 16, 7, 0).timestamp())
        self.assertIn(["rtcwake", "-m", "no", "-t", str(reveil)], self.commandes)
        self.assertIn(["systemctl", "stop", "hub-extinction.timer"], self.commandes)
        lancement = next(c for c in self.commandes if c[0] == "systemd-run")
        self.assertIn("--on-calendar=2026-09-15 23:30:00", lancement)
        self.assertEqual(lancement[-2:], ["/usr/local/bin/hub-allumage", "eteindre"])
        self.assertEqual(resultat["reveil"], reveil)
        self.assertEqual(json.loads(self.etat.read_text())["reveil"], reveil)

    def test_sans_programme_desarme_tout(self):
        al.appliquer({"reveils": [None] * 7, "extinctions": [None] * 7}, MARDI_22H, executer=self.executer, etat=self.etat)
        self.assertEqual(self.commandes, [["rtcwake", "-m", "disable"], ["systemctl", "stop", "hub-extinction.timer"]])
        self.assertIsNone(json.loads(self.etat.read_text())["reveil"])

    def test_echec_de_rtcwake_signale(self):
        def refuse(commande, **_):
            self.commandes.append(commande)
            return SimpleNamespace(returncode=1, stdout="", stderr="rtcwake: /dev/rtc0: no wakealarm")
        r = al.appliquer({"reveils": TOUS_LES_JOURS_7H, "extinctions": [None] * 7}, MARDI_22H, executer=refuse, etat=self.etat)
        self.assertIn("no wakealarm", r["erreur"])


class LectureDesReglages(unittest.TestCase):
    """root lit un fichier de l'utilisateur : ni lien, ni FIFO, ni fichier sans fin."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fichier_ordinaire_lu(self):
        f = self.dossier / "reglages.json"
        f.write_text(json.dumps({"systeme": {}}))
        self.assertEqual(al.lire_json(f), {"systeme": {}})

    def test_lien_symbolique_refuse(self):
        vrai = self.dossier / "vrai.json"
        vrai.write_text("{}")
        for cible in (vrai, Path("/dev/zero")):
            lien = self.dossier / f"lien-{cible.name}"
            os.symlink(cible, lien)
            self.assertIsNone(al.lire_json(lien))

    def test_fifo_refusee_sans_bloquer(self):
        fifo = self.dossier / "reglages.json"
        os.mkfifo(fifo)
        # Sans O_NONBLOCK, l'ouverture attendrait un écrivain pour toujours : un fil
        # à part permet de constater le blocage au lieu de figer la suite de tests.
        resultat = []
        fil = threading.Thread(target=lambda: resultat.append(al.lire_json(fifo)), daemon=True)
        fil.start()
        fil.join(5)
        self.assertFalse(fil.is_alive(), "lecture bloquée sur une FIFO")
        self.assertEqual(resultat, [None])

    def test_taille_bornee(self):
        f = self.dossier / "gros.json"
        f.write_text('"' + "x" * 300 + '"')
        self.assertIsNone(al.lire_json(f, taille_max=100))
        self.assertEqual(al.lire_json(f, taille_max=1000), "x" * 300)

    def test_absent_ou_invalide(self):
        self.assertIsNone(al.lire_json(self.dossier / "absent.json"))
        (self.dossier / "casse.json").write_bytes(b"\xff{")
        self.assertIsNone(al.lire_json(self.dossier / "casse.json"))


class Reveil(unittest.TestCase):
    def test_demarrage_pres_du_reveil_arme(self):
        reveil = datetime(2026, 9, 16, 7, 0).timestamp()
        self.assertTrue(al.demarre_par_reveil(reveil + 40, reveil))
        self.assertFalse(al.demarre_par_reveil(reveil + 3600, reveil))
        self.assertFalse(al.demarre_par_reveil(reveil - 300, reveil))
        self.assertFalse(al.demarre_par_reveil(reveil, None))


class WakeOnLan(unittest.TestCase):
    def test_trouve_la_carte_ethernet_et_son_adresse(self):
        with tempfile.TemporaryDirectory() as d:
            net = Path(d)
            for nom, type_, sans_fil, adresse in (("enp0s31f6", "1", False, "8c:16:45:aa:bb:cc"), ("wlx00", "1", True, "00:11:22:33:44:55"), ("lo", "772", False, "00:00:00:00:00:00")):
                (net / nom).mkdir()
                (net / nom / "type").write_text(type_ + "\n")
                (net / nom / "address").write_text(adresse + "\n")
                if nom != "lo":
                    (net / nom / "device").mkdir()
                if sans_fil:
                    (net / nom / "wireless").mkdir()
            self.assertEqual(al.cartes_ethernet(net), [{"interface": "enp0s31f6", "adresse": "8c:16:45:aa:bb:cc"}])


if __name__ == "__main__":
    unittest.main()
