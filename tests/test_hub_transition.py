"""L'écran d'attente (hub-transition) et ses deux branchements : la bascule vers le
bureau, et la boucle de session quand le menu ne démarre pas.

    python3 -m unittest tests/test_hub_transition.py

hub-transition n'importe GTK qu'à l'intérieur de lancer() : options, textes, couleurs et
feuille de style se vérifient sans serveur graphique. hub-vers-bureau appelle busctl et
gnome-session-quit, hors de portée d'ici : on vérifie sa forme — l'ordre des étapes et le
nettoyage en cas d'échec — parce que ce sont les deux endroits où une erreur laisserait
la TV dans un état dont on ne sort pas.
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("hub_transition", RACINE / "installer" / "hub-transition.py")
transition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transition)

VERS_BUREAU = (RACINE / "installer" / "hub-vers-bureau").read_text(encoding="utf-8")


class Couleur(unittest.TestCase):
    def test_trois_nombres_ou_hexadecimal(self):
        self.assertEqual(transition.couleur("255,181,71"), (255, 181, 71))
        self.assertEqual(transition.couleur("  0, 0 ,0 "), (0, 0, 0))
        self.assertEqual(transition.couleur("#ffb547"), (255, 181, 71))
        self.assertEqual(transition.couleur("#FFB547"), (255, 181, 71))

    def test_illisible_rend_none_jamais_une_exception(self):
        for mauvais in ("", "   ", "bleu", "1,2", "1,2,3,4", "#ffb", "#gggggg", "300,0,0", "-1,0,0", "1,2,x", None):
            self.assertIsNone(transition.couleur(mauvais), mauvais)


class Options(unittest.TestCase):
    def test_sans_argument_la_bascule_vers_le_bureau(self):
        options = transition.analyser([])
        self.assertEqual((options["mode"], options["accent"]), ("bureau", transition.ACCENT_BUREAU))
        self.assertEqual(options["titre"], "Ouverture du bureau…")
        self.assertIn("ferm", options["detail"])

    def test_secours_avec_compte_a_rebours(self):
        options = transition.analyser(["--secours", "8"])
        self.assertEqual((options["mode"], options["secondes"], options["accent"]), ("secours", 8, transition.ACCENT_SECOURS))
        self.assertIn("Nouvel essai dans 8 s", options["detail"])
        self.assertEqual(transition.analyser(["--secours", "x"])["secondes"], 10, "un délai illisible ne prive pas d'écran")
        self.assertEqual(transition.analyser(["--secours", "99999"])["secondes"], 3600)

    def test_titre_detail_accent_et_option_inconnue(self):
        options = transition.analyser(["--inconnue", "x", "--titre", "Ouverture de Kodi…", "--detail", "Patience", "--accent", "#3ba7ff"])
        self.assertEqual((options["titre"], options["detail"], options["accent"]), ("Ouverture de Kodi…", "Patience", (59, 167, 255)))
        self.assertEqual(transition.analyser(["--accent", "turquoise"])["accent"], transition.ACCENT_BUREAU)
        self.assertEqual(transition.analyser(["--titre"])["titre"], "Ouverture du bureau…")

    def test_textes_dans_la_langue_du_profil(self):
        self.assertEqual(transition.analyser([], langue="en")["titre"], "Opening the desktop…")
        self.assertIn("Trying again in 4 s", transition.analyser(["--secours", "4"], langue="en")["detail"])
        self.assertEqual(transition.analyser([], langue="xx")["titre"], "Ouverture du bureau…", "langue inconnue : français")


class LangueDuProfil(unittest.TestCase):
    def test_lue_dans_les_reglages_sinon_francais(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "reglages.json"
            f.write_text(json.dumps({"profilActif": "b", "profils": [{"id": "a", "langue": "fr"}, {"id": "b", "langue": "en"}]}))
            self.assertEqual(transition.langue_du_profil(f), "en")
            f.write_text(json.dumps({"profilActif": "z", "profils": [{"id": "a", "langue": "en"}]}))
            self.assertEqual(transition.langue_du_profil(f), "fr", "profil actif inconnu")
            f.write_text("{ abîmé")
            self.assertEqual(transition.langue_du_profil(f), "fr")
            f.write_text(json.dumps([1, 2]))
            self.assertEqual(transition.langue_du_profil(f), "fr")
            self.assertEqual(transition.langue_du_profil(Path(d) / "absent"), "fr")


class FeuilleDeStyle(unittest.TestCase):
    def test_accent_et_fond_presents(self):
        style = transition.css((255, 181, 71))
        self.assertIn("rgb(255,181,71)", style)
        self.assertIn("rgb(%d,%d,%d)" % transition.FOND, style)
        self.assertIsInstance(style, str)


class AccordAvecLeMenu(unittest.TestCase):
    def test_les_couleurs_sont_celles_des_cartes_du_menu(self):
        """La carte pressée et l'écran qui suit portent la même couleur : c'est ce qui fait
        lire les deux comme un seul geste. Si l'une change, l'autre doit suivre."""
        js = (RACINE / "installer" / "menu" / "hub.js").read_text(encoding="utf-8")
        self.assertIn("bureau: [%d, %d, %d]" % transition.ACCENT_BUREAU, js)
        self.assertIn("arret: [%d, %d, %d]" % transition.ACCENT_SECOURS, js)


class Branchement(unittest.TestCase):
    """hub-vers-bureau ne peut pas tourner ici ; on vérifie sa forme."""

    def test_lance_avant_habillage_et_deconnexion(self):
        lancement = VERS_BUREAU.index("hub-transition >")
        for suite in ("hub-theme bureau", "SetSession", "gnome-session-quit"):
            self.assertLess(lancement, VERS_BUREAU.index(suite), suite)

    def test_detache_et_facultatif(self):
        self.assertIn("setsid /usr/local/bin/hub-transition", VERS_BUREAU)
        self.assertIn("[ -x /usr/local/bin/hub-transition ]", VERS_BUREAU)

    def test_retire_si_la_bascule_echoue(self):
        retrait = VERS_BUREAU.index("retirer_transition\n", VERS_BUREAU.index("SetSession"))
        self.assertLess(retrait, VERS_BUREAU.index("exit 1"))

    def test_pose_par_l_installateur(self):
        installateur = (RACINE / "installer" / "hub-installer.sh").read_text(encoding="utf-8")
        self.assertIn("/usr/local/bin/hub-transition", installateur)


if __name__ == "__main__":
    unittest.main()
