"""hub-menu et le code de recopie d'écran de hub-enceinte : demandé, changé, affiché.

    python3 -m unittest tests/test_hub_menu_recopie.py
"""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

RACINE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("hub_menu_recopie", RACINE / "installer" / "hub-menu.py")
hub_menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub_menu)


def repond(stdout="", code=0, commandes=None):
    def executer(commande, **_):
        if commandes is not None:
            commandes.append(commande)
        return SimpleNamespace(returncode=code, stdout=stdout)
    return executer


class CodeRecopie(unittest.TestCase):
    def test_demande_le_code_ou_un_nouveau_avec_des_arguments_fixes(self):
        commandes = []
        self.assertEqual(hub_menu.code_recopie(executer=repond("4821\n", commandes=commandes)), "4821")
        self.assertEqual(hub_menu.code_recopie(nouveau=True, executer=repond("0937\n", commandes=commandes)), "0937")
        self.assertEqual(commandes, [["hub-enceinte", "code"], ["hub-enceinte", "code", "nouveau"]])

    def test_refuse_ce_qui_n_est_pas_un_code(self):
        for sortie, code in (("48210\n", 0), ("48a1", 0), ("٤٨٢١", 0), ("4821\n", 1), ("", 0), ("<b>4821</b>", 0)):
            self.assertIsNone(hub_menu.code_recopie(executer=repond(sortie, code)), (sortie, code))

    def test_hub_enceinte_absent_ou_bloque(self):
        def absent(*_, **__):
            raise FileNotFoundError("hub-enceinte")

        def bloque(*_, **__):
            raise subprocess.TimeoutExpired("hub-enceinte", 30)
        self.assertIsNone(hub_menu.code_recopie(executer=absent))
        self.assertIsNone(hub_menu.code_recopie(executer=bloque))
        self.assertIsNone(hub_menu.recopie_permise(executer=absent))

    def test_recopie_permise_selon_hub_enceinte_actif_ecran(self):
        commandes = []
        self.assertTrue(hub_menu.recopie_permise(executer=repond(code=0, commandes=commandes)))
        self.assertFalse(hub_menu.recopie_permise(executer=repond(code=1)))
        self.assertIsNone(hub_menu.recopie_permise(executer=repond(code=2)))
        self.assertEqual(commandes, [["hub-enceinte", "actif", "ecran"]])


class AppairageRecopie(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        execution = Path(self._tmp.name) / "run/hub"
        execution.mkdir(parents=True)
        self.c = {"execution": execution, "recopie-code": execution / "recopie-code.json"}

    def tearDown(self):
        self._tmp.cleanup()

    def ecrire(self, donnees):
        self.c["recopie-code"].write_text(donnees if isinstance(donnees, str) else json.dumps(donnees))

    def test_code_affiche_jusqu_a_l_echeance(self):
        self.assertIsNone(hub_menu.etat_code_recopie(self.c, maintenant=1000))
        self.ecrire({"code": "4821", "jusqua": 1060})
        self.assertEqual(hub_menu.etat_code_recopie(self.c, maintenant=1000), {"code": "4821", "jusqua": 1060})
        self.assertIsNone(hub_menu.etat_code_recopie(self.c, maintenant=1060), "échu : plus affiché même si le fichier traîne")

    def test_fichier_douteux_rien_d_affiche(self):
        for donnees in ("{coupé", [], {"code": 4821, "jusqua": 1060}, {"code": "48210", "jusqua": 1060},
                        {"code": "<img>", "jusqua": 1060}, {"code": "4821"}, {"code": "4821", "jusqua": True},
                        {"code": "4821", "jusqua": "1060"}):
            self.ecrire(donnees)
            self.assertIsNone(hub_menu.etat_code_recopie(self.c, maintenant=1000), donnees)

    def test_seuls_code_et_echeance_passent(self):
        self.ecrire({"code": "4821", "jusqua": 1060, "appareil": "iPhone", "secret": "x"})
        self.assertEqual(set(hub_menu.etat_code_recopie(self.c, maintenant=1000)), {"code", "jusqua"})


if __name__ == "__main__":
    unittest.main()
