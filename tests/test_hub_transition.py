"""L'écran d'attente de la bascule vers le bureau, et son branchement.

    python3 -m unittest tests/test_hub_transition.py

hub-transition n'importe GTK qu'à l'intérieur de lancer() : tout ce qui est
testé ici — lecture des options, couleurs, feuille de style — se vérifie donc
sans serveur graphique, donc ici, sur une machine de développement.

Le reste (hub-vers-bureau) est un script shell qui appelle busctl et
gnome-session-quit : impossible à exécuter ailleurs que sur le mini PC. On
vérifie alors ce qui peut l'être sans le lancer — l'ordre des étapes et le
nettoyage en cas d'échec — parce que ce sont précisément les deux endroits où
une erreur laisserait la TV dans un état que l'utilisateur ne peut pas quitter.
"""

import importlib.util
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("hub_transition", RACINE / "installer" / "hub-transition.py")
transition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transition)

VERS_BUREAU = (RACINE / "installer" / "hub-vers-bureau").read_text(encoding="utf-8")


class Couleur(unittest.TestCase):
    def test_trois_nombres(self):
        self.assertEqual(transition.couleur("255,181,71"), (255, 181, 71))
        self.assertEqual(transition.couleur("  0, 0 ,0 "), (0, 0, 0))

    def test_hexadecimal(self):
        self.assertEqual(transition.couleur("#ffb547"), (255, 181, 71))
        self.assertEqual(transition.couleur("#FFB547"), (255, 181, 71))

    def test_illisible_rend_none(self):
        """None, pas une exception : l'appelant retombe sur l'ambre par défaut.
        Un accent mal écrit ne doit jamais coûter l'écran d'attente."""
        for mauvais in ("", "   ", "bleu", "1,2", "1,2,3,4", "#ffb", "#gggggg", "300,0,0", "-1,0,0", "1,2,x"):
            self.assertIsNone(transition.couleur(mauvais), mauvais)

    def test_aucun_texte(self):
        self.assertIsNone(transition.couleur(None))


class Options(unittest.TestCase):
    def test_sans_argument(self):
        options = transition.analyser([])
        self.assertEqual(options["titre"], transition.TITRE_DEFAUT)
        self.assertEqual(options["detail"], transition.DETAIL_DEFAUT)
        self.assertEqual(options["accent"], transition.ACCENT_DEFAUT)

    def test_titre_detail_accent(self):
        options = transition.analyser(["--titre", "Ouverture de Kodi…", "--detail", "Patience", "--accent", "#3ba7ff"])
        self.assertEqual(options["titre"], "Ouverture de Kodi…")
        self.assertEqual(options["detail"], "Patience")
        self.assertEqual(options["accent"], (59, 167, 255))

    def test_accent_invalide_garde_le_defaut(self):
        options = transition.analyser(["--accent", "turquoise"])
        self.assertEqual(options["accent"], transition.ACCENT_DEFAUT)

    def test_option_inconnue_ignoree(self):
        """Une option de trop ne doit pas faire sortir le programme : l'écran
        vaut mieux qu'un message d'erreur que personne ne lit sur une TV."""
        options = transition.analyser(["--inconnue", "x", "--titre", "Vu"])
        self.assertEqual(options["titre"], "Vu")

    def test_option_finale_sans_valeur(self):
        options = transition.analyser(["--titre"])
        self.assertEqual(options["titre"], transition.TITRE_DEFAUT)


class FeuilleDeStyle(unittest.TestCase):
    def test_accent_et_fond_presents(self):
        style = transition.css((255, 181, 71)).decode("utf-8")
        self.assertIn("rgb(255,181,71)", style)
        self.assertIn("rgb(%d,%d,%d)" % transition.FOND, style)

    def test_est_du_binaire(self):
        """Gtk.CssProvider.load_from_data attend des octets en GTK 4 ; lui
        passer une chaîne lève, et l'écran resterait noir."""
        self.assertIsInstance(transition.css(transition.ACCENT_DEFAUT), bytes)


class AccordAvecLeMenu(unittest.TestCase):
    def test_meme_ambre_que_la_carte_bureau(self):
        """La carte pressée dans le menu et l'écran qui suit portent la même
        couleur : c'est ce qui fait lire les deux comme un seul geste."""
        js = (RACINE / "installer" / "menu" / "hub.js").read_text(encoding="utf-8")
        r, v, b = transition.ACCENT_DEFAUT
        self.assertIn("bureau: [%d, %d, %d]" % (r, v, b), js)


class Branchement(unittest.TestCase):
    """hub-vers-bureau ne peut pas tourner ici ; on vérifie sa forme."""

    def test_lance_avant_habillage_et_deconnexion(self):
        """L'écran doit précéder hub-theme et le démontage, sinon il n'a plus
        rien à couvrir : c'est exactement ce temps-là qui était noir."""
        lancement = VERS_BUREAU.index("hub-transition >")
        for suite in ("hub-theme bureau", "SetSession", "gnome-session-quit"):
            self.assertLess(lancement, VERS_BUREAU.index(suite), suite)

    def test_detache_de_ce_script(self):
        """Sans setsid il appartiendrait au groupe du script, et le exec final
        l'emporterait avec lui — l'écran disparaîtrait au pire moment."""
        self.assertIn("setsid /usr/local/bin/hub-transition", VERS_BUREAU)

    def test_absent_ne_bloque_pas_la_bascule(self):
        self.assertIn("[ -x /usr/local/bin/hub-transition ]", VERS_BUREAU)

    def test_retire_si_la_bascule_echoue(self):
        """Si SetSession échoue on reste dans le menu : l'écran d'attente doit
        partir, sinon il masque ce menu revenu derrière lui et la TV paraît
        bloquée alors qu'elle ne l'est pas."""
        retrait = VERS_BUREAU.index("retirer_transition\n", VERS_BUREAU.index("SetSession"))
        self.assertLess(retrait, VERS_BUREAU.index("exit 1"))

    def test_pose_par_l_installateur(self):
        installateur = (RACINE / "installer" / "hub-installer.sh").read_text(encoding="utf-8")
        self.assertIn("/usr/local/bin/hub-transition", installateur)


if __name__ == "__main__":
    unittest.main()
