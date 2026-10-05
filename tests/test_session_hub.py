"""La boucle de session (gnome-kiosk-script) quand le menu ne démarre pas, et le retour au
HUB épinglé au dock du bureau (hub-session-par-defaut).

    python3 -m unittest tests/test_session_hub.py

Les deux scripts appellent hub-menu, systemctl, busctl : hors de portée d'ici. On en
extrait les fonctions concernées et on les lance dans sh avec de faux binaires.
"""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
KIOSQUE = (RACINE / "installer" / "gnome-kiosk-script").read_text(encoding="utf-8")
SESSION = (RACINE / "installer" / "hub-session-par-defaut").read_text(encoding="utf-8")


def fonctions(script, *noms):
    """Le texte des fonctions shell `nom() { … }` du script, telles qu'écrites."""
    morceaux = []
    for nom in noms:
        debut = script.index(f"{nom}() {{")
        fin = script.index("\n}\n", debut) + 3
        morceaux.append(script[debut:fin])
    return "\n".join(morceaux)


def executable(chemin, texte):
    chemin.write_text("#!/bin/sh\n" + texte)
    chemin.chmod(0o755)


class MenuQuiNeDemarrePas(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.faux = self.d / "bin"
        self.faux.mkdir()
        self.trace = self.d / "trace"
        executable(self.faux / "sleep", f'echo "sleep $1" >>"{self.trace}"\n')
        self.code = fonctions(KIOSQUE, "delai_apres_echecs", "attendre_apres_echec")

    def tearDown(self):
        self._tmp.cleanup()

    def attendre(self, code=1):
        compteur = self.d / "run" / "hub" / "menu-echecs"
        script = f'{self.code}\nattendre_apres_echec "{compteur}" {code}\n'
        env = dict(os.environ, PATH=f"{self.faux}:{os.environ['PATH']}")
        r = subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return compteur, r.stderr

    def test_syntaxe(self):
        subprocess.run(["sh", "-n", str(RACINE / "installer" / "gnome-kiosk-script")], check=True)

    def test_attente_croissante_puis_plafonnee(self):
        attentes = []
        for _ in range(7):
            compteur, _journal = self.attendre()
            attentes.append(self.trace.read_text().splitlines()[-1])
        self.assertEqual(attentes, ["sleep 1", "sleep 2", "sleep 4", "sleep 8", "sleep 16", "sleep 30", "sleep 30"])
        self.assertEqual(compteur.read_text().strip(), "7")

    def test_un_compteur_abime_repart_de_zero(self):
        compteur = self.d / "run" / "hub" / "menu-echecs"
        compteur.parent.mkdir(parents=True)
        compteur.write_text("rm -rf / ; 12 pommes\n")
        self.attendre()
        self.assertEqual(compteur.read_text().strip(), "13", "seuls les chiffres comptent, rien n'est exécuté")

    def test_le_journal_dit_le_code_et_le_delai(self):
        _compteur, journal = self.attendre(code=137)
        self.assertIn("code 137", journal)
        self.assertIn("nouvel essai dans 1 s", journal)

    def test_la_boucle_n_attend_qu_apres_un_echec_et_remet_le_compteur_a_zero(self):
        """La forme de la boucle : un menu qui sort sans choix ET en erreur déclenche
        l'attente ; toute sortie normale efface le compteur avant de lire le choix."""
        lecture = KIOSQUE.index("sortie=$(/usr/local/bin/hub-menu)")
        self.assertLess(lecture, KIOSQUE.index('if [ -z "$sortie" ] && [ "$code" -ne 0 ]; then'))
        self.assertLess(KIOSQUE.index('attendre_apres_echec "$COMPTEUR_ECHECS" "$code"'), KIOSQUE.index('rm -f "$COMPTEUR_ECHECS"'))
        self.assertLess(KIOSQUE.index('rm -f "$COMPTEUR_ECHECS"'), KIOSQUE.index("choix=$(printf"))
        self.assertIn('setsid /usr/local/bin/hub-transition --secours "$delai"', KIOSQUE)
        self.assertIn('[ "$n" -ge 2 ]', KIOSQUE, "l'écran de secours à partir du deuxième échec seulement")


class RetourAuHubDansLeDock(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.faux = self.d / "bin"
        self.faux.mkdir()
        self.ecrits = self.d / "ecrits"
        self.code = fonctions(SESSION, "epingler_retour")

    def tearDown(self):
        self._tmp.cleanup()

    def epingler(self, favoris, marqueur=None):
        executable(self.faux / "gsettings",
                   f'if [ "$1" = get ]; then printf \'%s\\n\' "{favoris}"; else echo "$3=$4" >>"{self.ecrits}"; fi\n')
        marqueur = marqueur or self.d / "config" / "hub" / "dock-retour-pose"
        env = dict(os.environ, PATH=f"{self.faux}:{os.environ['PATH']}")
        r = subprocess.run(["sh", "-c", f'{self.code}\nepingler_retour "{marqueur}"\n'], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.ecrits.read_text() if self.ecrits.exists() else "", marqueur

    def test_syntaxe(self):
        subprocess.run(["sh", "-n", str(RACINE / "installer" / "hub-session-par-defaut")], check=True)

    def test_ajoute_en_tete_une_fois(self):
        ecrits, marqueur = self.epingler("['firefox.desktop', 'org.gnome.Nautilus.desktop']")
        self.assertEqual(ecrits.strip(), "favorite-apps=['retour-au-hub.desktop', 'firefox.desktop', 'org.gnome.Nautilus.desktop']")
        self.assertTrue(marqueur.exists(), "le marqueur dit que c'est fait")
        # Une seconde ouverture du bureau, même sans le favori (retiré exprès) : rien.
        self.ecrits.unlink()
        ecrits, _ = self.epingler("['firefox.desktop']", marqueur)
        self.assertEqual(ecrits, "")

    def test_deja_present_ou_liste_vide(self):
        ecrits, _ = self.epingler("['retour-au-hub.desktop', 'firefox.desktop']")
        self.assertEqual(ecrits, "", "déjà là : on n'écrit pas")
        self.ecrits.unlink(missing_ok=True)
        ecrits, _ = self.epingler("@as []", self.d / "m2")
        self.assertEqual(ecrits.strip(), "favorite-apps=['retour-au-hub.desktop']")

    def test_gsettings_absent_ou_reponse_inattendue(self):
        ecrits, marqueur = self.epingler("pas une liste")
        self.assertEqual(ecrits, "")
        self.assertFalse(marqueur.exists(), "rien de fait : on réessaiera à la prochaine ouverture")


if __name__ == "__main__":
    unittest.main()
