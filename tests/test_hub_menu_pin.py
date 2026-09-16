"""Codes PIN des profils : vérifiés par hub-menu, échecs comptés sur disque.

    python3 -m unittest tests/test_hub_menu_pin.py
"""

import hashlib
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("hub_menu_pin", RACINE / "installer" / "hub-menu.py")
hub_menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub_menu)


def ancien_pin(code, sel="abc"):
    """Le format que la page écrivait avant : sha256("sel:code")."""
    return {"sel": sel, "empreinte": hashlib.sha256(f"{sel}:{code}".encode()).hexdigest()}


class AvecReglages(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.c = {"reglages": d / "config/hub/reglages.json", "pin-echecs": d / "state/hub/pin-echecs.json"}
        # Les vraies itérations prendraient des secondes sur l'ensemble des tests ;
        # la forme du calcul est la même.
        self._iterations = hub_menu.PIN_ITERATIONS
        hub_menu.PIN_ITERATIONS = 1000

    def tearDown(self):
        hub_menu.PIN_ITERATIONS = self._iterations
        self._tmp.cleanup()

    def ecrire(self, *profils):
        hub_menu.enregistrer_reglages(self.c, {"profilActif": profils[0]["id"], "profils": list(profils)})

    def profil_lu(self, ident):
        return next(p for p in hub_menu.charger_reglages(self.c)["profils"] if p["id"] == ident)


class Hachage(AvecReglages):
    def test_pbkdf2_avec_sel_aleatoire_de_16_octets(self):
        a, b = hub_menu.hacher_pin("1234"), hub_menu.hacher_pin("1234")
        self.assertEqual(a["algo"], "pbkdf2-sha256")
        self.assertEqual(len(bytes.fromhex(a["sel"])), 16)
        self.assertNotEqual(a["sel"], b["sel"])
        self.assertNotEqual(a["empreinte"], b["empreinte"])
        attendu = hashlib.pbkdf2_hmac("sha256", b"1234", bytes.fromhex(a["sel"]), a["iterations"]).hex()
        self.assertEqual(a["empreinte"], attendu)
        self.assertNotIn("1234", json.dumps(a))

    def test_au_moins_200000_iterations_en_vrai(self):
        self.assertGreaterEqual(self._iterations, 200_000)

    def test_verifie_les_deux_formats(self):
        self.assertTrue(hub_menu.pin_correct(hub_menu.hacher_pin("0420"), "0420"))
        self.assertFalse(hub_menu.pin_correct(hub_menu.hacher_pin("0420"), "0421"))
        self.assertTrue(hub_menu.pin_correct(ancien_pin("1234"), "1234"))
        self.assertFalse(hub_menu.pin_correct(ancien_pin("1234"), "4321"))

    def test_refuse_les_formes_douteuses(self):
        bon = hub_menu.hacher_pin("1234")
        for pin, code in ((None, "1234"), ({}, "1234"), (bon, "12345"), (bon, "12a4"), (bon, 1234), (bon, "１２３４"),
                          ({**bon, "iterations": 10 ** 9}, "1234"), ({**bon, "iterations": True}, "1234"),
                          ({**bon, "sel": "zz"}, "1234"), ({**bon, "algo": "md5"}, "1234")):
            self.assertFalse(hub_menu.pin_correct(pin, code), (pin, code))

    def test_creer_refuse_ce_qui_n_est_pas_quatre_chiffres(self):
        self.assertEqual(hub_menu.creer_pin("12"), {"resultat": "refus"})
        self.assertEqual(hub_menu.creer_pin("5678")["resultat"], "hache")


class Verification(AvecReglages):
    def test_bon_code_ouvre_le_profil(self):
        self.ecrire({"id": "sam", "pin": hub_menu.hacher_pin("1234")}, {"id": "camille"})
        r = hub_menu.verifier_pin(self.c, ["sam"], "1234", maintenant=1000)
        self.assertEqual((r["resultat"], r["profil"]), ("ok", "sam"))
        self.assertNotIn("pin", r, "déjà au bon format : rien à réécrire")

    def test_le_code_d_un_autre_profil_n_ouvre_pas(self):
        self.ecrire({"id": "sam", "pin": hub_menu.hacher_pin("1234")}, {"id": "camille", "pin": hub_menu.hacher_pin("0000")})
        self.assertEqual(hub_menu.verifier_pin(self.c, ["camille"], "1234", maintenant=1000)["resultat"], "refus")
        self.assertEqual(hub_menu.verifier_pin(self.c, ["camille", "sam"], "1234", maintenant=1000)["profil"], "sam")

    def test_ancien_format_verifie_une_fois_puis_reecrit_en_pbkdf2(self):
        self.ecrire({"id": "sam", "nom": "Sam", "pin": ancien_pin("1234")})
        r = hub_menu.verifier_pin(self.c, ["sam"], "1234", maintenant=1000)
        self.assertEqual(r["resultat"], "ok")
        relu = self.profil_lu("sam")
        self.assertEqual(relu["pin"]["algo"], "pbkdf2-sha256")
        self.assertEqual(r["pin"], relu["pin"], "la page reçoit la nouvelle empreinte pour ne pas réécrire l'ancienne")
        self.assertEqual(relu["nom"], "Sam")
        self.assertTrue(hub_menu.verifier_pin(self.c, ["sam"], "1234", maintenant=1001)["resultat"] == "ok")
        self.assertEqual(self.c["reglages"].stat().st_mode & 0o777, 0o600)

    def test_un_mauvais_code_ne_migre_rien(self):
        self.ecrire({"id": "sam", "pin": ancien_pin("1234")})
        hub_menu.verifier_pin(self.c, ["sam"], "9999", maintenant=1000)
        self.assertNotIn("algo", self.profil_lu("sam")["pin"])

    def test_empreintes_lues_sur_disque_pas_dans_la_demande(self):
        self.ecrire({"id": "sam", "pin": hub_menu.hacher_pin("1234")})
        for profils in (None, "sam", [{"id": "sam"}], ["inconnu"]):
            self.assertEqual(hub_menu.verifier_pin(self.c, profils, "1234", maintenant=1000)["resultat"], "refus", profils)


class Blocage(AvecReglages):
    def setUp(self):
        super().setUp()
        self.ecrire({"id": "sam", "pin": hub_menu.hacher_pin("1234")})

    def echouer(self, fois, maintenant):
        return [hub_menu.verifier_pin(self.c, ["sam"], "9999", maintenant=maintenant) for _ in range(fois)]

    def test_quatre_essais_libres_puis_30_s(self):
        reponses = self.echouer(5, 1000)
        self.assertEqual([r["attente"] for r in reponses], [0, 0, 0, 0, 30])
        r = hub_menu.verifier_pin(self.c, ["sam"], "1234", maintenant=1010)
        self.assertEqual((r["resultat"], r["attente"]), ("bloque", 20), "même le bon code attend")
        self.assertEqual(hub_menu.verifier_pin(self.c, ["sam"], "1234", maintenant=1031)["resultat"], "ok")

    def test_le_blocage_survit_au_redemarrage_du_menu(self):
        self.echouer(5, 1000)
        # Un nouveau processus : le module rechargé ne garde rien en mémoire.
        spec2 = importlib.util.spec_from_file_location("hub_menu_relance", RACINE / "installer" / "hub-menu.py")
        relance = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(relance)
        self.assertEqual(relance.verifier_pin(self.c, ["sam"], "1234", maintenant=1005)["resultat"], "bloque")

    def test_le_delai_double_et_plafonne(self):
        maintenant, attentes = 1000, []
        for _ in range(12):
            r = hub_menu.verifier_pin(self.c, ["sam"], "9999", maintenant=maintenant)
            attentes.append(r["attente"])
            maintenant += r["attente"] + 1
        self.assertEqual(attentes[4:10], [30, 60, 120, 240, 480, 900])
        self.assertEqual(max(attentes), 900)

    def test_changer_de_profil_ne_redonne_pas_d_essais(self):
        self.ecrire({"id": "sam", "pin": hub_menu.hacher_pin("1234")}, {"id": "camille", "pin": hub_menu.hacher_pin("5678")})
        for ident in ("sam", "camille", "sam", "camille"):
            hub_menu.verifier_pin(self.c, [ident], "0000", maintenant=1000)
        self.assertEqual(hub_menu.verifier_pin(self.c, ["camille"], "0000", maintenant=1000)["attente"], 30)

    def test_la_reussite_remet_le_compteur_a_zero(self):
        self.echouer(3, 1000)
        hub_menu.verifier_pin(self.c, ["sam"], "1234", maintenant=1000)
        self.assertEqual([r["attente"] for r in self.echouer(4, 1000)], [0, 0, 0, 0])

    def test_compteur_illisible_ou_horloge_en_arriere(self):
        self.c["pin-echecs"].parent.mkdir(parents=True, exist_ok=True)
        self.c["pin-echecs"].write_text("{ abîmé")
        self.assertEqual(hub_menu.verifier_pin(self.c, ["sam"], "1234", maintenant=1000)["resultat"], "ok")
        self.c["pin-echecs"].write_text(json.dumps({"echecs": 9, "jusqua": 10 ** 12}))
        self.assertEqual(hub_menu.attente_pin(self.c["pin-echecs"], 1000), 900)

    def test_essais_simultanes_tous_comptes(self):
        fils = [threading.Thread(target=hub_menu.verifier_pin, args=(self.c, ["sam"], "9999", 1000)) for _ in range(8)]
        for f in fils:
            f.start()
        for f in fils:
            f.join()
        self.assertEqual(json.loads(self.c["pin-echecs"].read_text())["echecs"], 5,
                         "les quatre libres, le cinquième bloque, les suivants attendent sans compter")
        self.assertEqual(self.c["pin-echecs"].stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
