"""hub-menu et l'enceinte réseau : l'état de lecture relayé à la page, et le réglage.

    python3 -m unittest tests/test_hub_menu_lecture.py

Le fichier lu est celui qu'écrit hub-enceinte (installer/enceinte/hub_enceinte.py) : le
dernier test fait écrire le vrai coordinateur et vérifie que le menu le relit tel quel.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("hub_menu", RACINE / "installer" / "hub-menu.py")
hub_menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub_menu)
sys.path.insert(0, str(RACINE / "installer" / "enceinte"))
import hub_enceinte  # noqa: E402


class EtatLecture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.execution = Path(self._tmp.name) / "run/hub"
        self.execution.mkdir(parents=True)
        self.c = {"execution": self.execution, "lecture": self.execution / "lecture.json"}

    def tearDown(self):
        self._tmp.cleanup()

    def ecrire(self, donnees):
        self.c["lecture"].write_text(json.dumps(donnees) if not isinstance(donnees, str) else donnees)

    def test_rien_ne_joue(self):
        self.assertIsNone(hub_menu.etat_lecture(self.c))
        self.ecrire("{coupé")
        self.assertIsNone(hub_menu.etat_lecture(self.c))
        self.ecrire({"source": "netflix", "etat": "lecture"})
        self.assertIsNone(hub_menu.etat_lecture(self.c))
        self.ecrire({"source": "spotify", "etat": "arret"})
        self.assertIsNone(hub_menu.etat_lecture(self.c))

    def test_champs_connus_et_bornes(self):
        self.ecrire({"source": "airplay", "etat": "pause", "titre": "x" * 300, "artiste": 3, "album": " ",
                     "appareil": "iPhone", "script": "<b>", "ecran": "oui"})
        self.assertEqual(hub_menu.etat_lecture(self.c), {
            "source": "airplay", "etat": "pause", "ecran": False, "titre": "x" * 200,
            "artiste": None, "album": None, "appareil": "iPhone", "pochette": None})

    def test_pochette_seulement_du_dossier_d_execution(self):
        pochettes = self.execution / "pochettes"
        pochettes.mkdir()
        (pochettes / "spotify-1.jpg").write_bytes(b"\xff\xd8")
        ailleurs = Path(self._tmp.name) / "secret.jpg"
        ailleurs.write_bytes(b"x")
        for uri, attendu in [
            ((pochettes / "spotify-1.jpg").as_uri(), (pochettes / "spotify-1.jpg").resolve().as_uri()),
            (ailleurs.as_uri(), None),
            ((pochettes / ".." / ".." / ".." / "secret.jpg").as_uri(), None),
            ((pochettes / "absente.jpg").as_uri(), None),
            ("https://i.scdn.co/image/abc", None),
        ]:
            self.ecrire({"source": "spotify", "etat": "lecture", "pochette": uri})
            self.assertEqual(hub_menu.etat_lecture(self.c)["pochette"], attendu, uri)

    def test_le_coordinateur_et_le_menu_parlent_le_meme_format(self):
        c = {k: Path(self._tmp.name) / "run/hub" / Path(v).name if k in ("lecture", "pochettes", "socket", "tube-airplay") else v
             for k, v in hub_enceinte.chemins().items()}
        c["execution"] = self.execution
        coord = hub_enceinte.Coordinateur(c)
        coord.traiter({"source": "airplay", "etat": "lecture", "titre": "Chanson", "appareil": "iPad"})
        coord.traiter({"source": "airplay", "pochetteOctets": b"\x89PNG", "piste": None})
        etat = hub_menu.etat_lecture(self.c)
        self.assertEqual((etat["source"], etat["titre"], etat["appareil"]), ("airplay", "Chanson", "iPad"))
        self.assertTrue(etat["pochette"].startswith("file://"))
        coord.traiter({"source": "airplay", "etat": "arret"})
        self.assertIsNone(hub_menu.etat_lecture(self.c))


class ReglageEnceinte(unittest.TestCase):
    def appels(self):
        liste = []
        return liste, lambda cmd, **_: liste.append(cmd)

    def test_ne_relance_que_si_le_reglage_change(self):
        liste, executer = self.appels()
        avant = {"systeme": {"voix": True, "enceinte": {"spotify": True, "nom": "HUB"}}}
        theme = {"systeme": {"voix": False, "enceinte": {"spotify": True, "nom": "HUB"}}}
        self.assertFalse(hub_menu.appliquer_enceinte(avant, theme, executer))
        self.assertEqual(liste, [])
        nom = {"systeme": {"enceinte": {"spotify": True, "nom": "Salon"}}}
        self.assertTrue(hub_menu.appliquer_enceinte(theme, nom, executer))
        self.assertEqual(liste, [["hub-enceinte", "appliquer"]])

    def test_hub_enceinte_absent(self):
        def absent(*_, **__):
            raise FileNotFoundError("hub-enceinte")
        self.assertFalse(hub_menu.appliquer_enceinte(None, {"systeme": {"enceinte": {"ecran": False}}}, absent))


if __name__ == "__main__":
    unittest.main()
