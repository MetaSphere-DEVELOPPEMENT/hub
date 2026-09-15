"""hub-menu côté temps d'écran et allumage : ce qu'il lit, ce qu'il accepte de la page.

    python3 -m unittest tests/test_hub_menu_temps.py
"""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("hub_menu_temps", RACINE / "installer" / "hub-menu.py")
hub_menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub_menu)


class ProgrammesVoisins(unittest.TestCase):
    def test_trouves_dans_le_depot(self):
        self.assertTrue(hasattr(hub_menu.programme_voisin("hub-temps-ecran"), "restant"))
        self.assertTrue(hasattr(hub_menu.programme_voisin("hub-allumage"), "prochain"))
        self.assertIsNone(hub_menu.programme_voisin("hub-inexistant"))


class TempsEcran(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self._tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self._tmp.cleanup()

    def test_etat_vide_puis_prolongation(self):
        etat = hub_menu.temps_ecran()
        self.assertEqual(etat["profils"], {})
        self.assertIn("aujourdhui", etat)
        etat = hub_menu.prolonger_temps("lea", 30)
        jour = etat["profils"]["lea"][etat["aujourdhui"]]
        self.assertEqual(jour["bonus"], 1800)
        self.assertTrue((Path(self._tmp.name) / "hub" / "temps-ecran.json").exists())

    def test_prolongation_bornee(self):
        # La page n'accorde que 15, 30 ou 60 minutes ; tout le reste est ignoré.
        for profil, minutes in (("lea", 600), ("lea", -15), ("lea", "30"), ("", 15), ("x" * 200, 15), (None, 15)):
            self.assertIsNone(hub_menu.prolonger_temps(profil, minutes), (profil, minutes))


class Allumage(unittest.TestCase):
    def test_reveil_programme_seulement_au_premier_affichage(self):
        with tempfile.TemporaryDirectory() as d:
            signal = Path(d) / "reveil"
            self.assertFalse(hub_menu.reveil_programme(signal, deja_ouvert=False))
            signal.write_text(json.dumps({"reveil": 1}))
            self.assertTrue(hub_menu.reveil_programme(signal, deja_ouvert=False))
            self.assertFalse(hub_menu.reveil_programme(signal, deja_ouvert=True), "revenir de Kodi n'est pas un réveil")

    def test_etat_lu_sans_root(self):
        with tempfile.TemporaryDirectory() as d:
            fichier = Path(d) / "allumage.json"
            fichier.write_text(json.dumps({"reveil": 1789538400, "extinction": None}))
            etat = hub_menu.etat_allumage(fichier)
            self.assertEqual(etat["reveil"], 1789538400)
            self.assertIsInstance(etat["ethernet"], list)

    def test_appliquer_demarre_le_service_autorise(self):
        commandes = []
        ok = hub_menu.appliquer_allumage(lambda c, **_: commandes.append(c) or SimpleNamespace(returncode=0))
        self.assertTrue(ok)
        self.assertEqual(commandes, [["systemctl", "start", "--no-block", "hub-allumage.service"]])


if __name__ == "__main__":
    unittest.main()
