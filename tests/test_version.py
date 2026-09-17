"""Le numéro de version du HUB : cohérent entre VERSION, NOUVEAUTES.md et ce que le
menu affiche, et incrémenté dès que ce qui s'installe change.

POURQUOI CE GARDE-FOU. Le numéro est écrit à la main : c'est la seule chose de la
chaîne qu'on peut oublier. L'empreinte du commit, elle, se calcule toute seule — d'où
la règle : rien ne DÉCIDE sur le numéro (voir hub-mise-a-jour), mais rien ne doit
partir avec un numéro périmé non plus.

    python3 -m unittest discover -s tests
"""

import importlib.util
import re
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
VERSION = RACINE / "VERSION"
NOUVEAUTES = RACINE / "NOUVEAUTES.md"
spec = importlib.util.spec_from_file_location("hub_menu", RACINE / "installer" / "hub-menu.py")
hub_menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub_menu)

NUMERO = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
# « ## 1.0.0 — 17 septembre 2026 »
TITRE = re.compile(r"^## (\d+\.\d+\.\d+) — (\d{1,2}) (\w+) (\d{4})\s*$")
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre")
# Ce que l'installateur pose sur le HUB : le numéro doit changer quand l'un d'eux change.
INSTALLE = ("installer", "VERSION", "NOUVEAUTES.md")


def numero_du_depot():
    return VERSION.read_text(encoding="utf-8").strip()


def sections():
    titres = [TITRE.match(l) for l in NOUVEAUTES.read_text(encoding="utf-8").splitlines() if l.startswith("## ")]
    return [t for t in titres if t]


def git(*arguments):
    try:
        r = subprocess.run(["git", "-C", str(RACINE), *arguments], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


class Numero(unittest.TestCase):
    def test_version_est_un_numero_a_trois_nombres(self):
        self.assertTrue(VERSION.is_file(), "VERSION manque à la racine du dépôt")
        brut = VERSION.read_text(encoding="utf-8")
        self.assertRegex(brut.strip(), NUMERO, "VERSION doit contenir MAJEUR.MINEUR.CORRECTIF")
        self.assertEqual(len([l for l in brut.splitlines() if l.strip()]), 1,
                         "VERSION ne porte que le numéro : la date est dans NOUVEAUTES.md")

    def test_nouveautes_commence_par_la_version_du_depot(self):
        titres = sections()
        self.assertTrue(titres, "NOUVEAUTES.md n'a aucune section « ## x.y.z — jour mois année »")
        self.assertEqual(titres[0].group(1), numero_du_depot(),
                         "la première section de NOUVEAUTES.md doit porter le numéro de VERSION")
        _, jour, mois, annee = titres[0].groups()
        self.assertIn(mois, MOIS, "le mois doit être écrit en toutes lettres, en français")
        self.assertTrue(1 <= int(jour) <= 31 and 2020 <= int(annee) <= 2100)

    def test_les_versions_vont_de_la_plus_recente_a_la_plus_ancienne_sans_doublon(self):
        numeros = [tuple(int(n) for n in t.group(1).split(".")) for t in sections()]
        self.assertEqual(len(numeros), len(set(numeros)), "deux sections portent le même numéro")
        self.assertEqual(numeros, sorted(numeros, reverse=True),
                         "NOUVEAUTES.md se lit de la version la plus récente à la plus ancienne")

    def test_la_section_dit_quelque_chose(self):
        quoi = hub_menu.nouveautes(NOUVEAUTES)
        self.assertTrue(quoi and len(quoi) > 40, "la première section de NOUVEAUTES.md est vide")
        self.assertNotIn("##", quoi, "le titre de section ne doit pas se retrouver dans le résumé")

    def test_le_menu_affiche_ce_numero(self):
        # infos() est ce que la page reçoit pour Réglages → À propos.
        infos = hub_menu.infos()
        self.assertEqual(infos["version"], numero_du_depot())
        self.assertEqual(infos["nouveautes"], hub_menu.nouveautes(NOUVEAUTES))


    def test_fichier_installe_sans_numero_complete_par_le_depot(self):
        """Un HUB installé avant les numéros n'a que l'empreinte : le menu affiche quand
        même le numéro du dépôt, sinon À propos dirait « version inconnue »."""
        with tempfile.TemporaryDirectory() as d:
            ancien = Path(d) / "VERSION"
            ancien.write_text("abc1234\n")
            with unittest.mock.patch.object(hub_menu, "VERSION_INSTALLEE", ancien):
                infos = hub_menu.infos()
        self.assertEqual(infos["version"], numero_du_depot())
        self.assertEqual(infos["commit"], "abc1234")


class FichierInstalle(unittest.TestCase):
    """Le format posé par l'installateur dans /usr/local/share/hub/VERSION."""

    def test_trois_lignes_numero_empreinte_date(self):
        lu = hub_menu.lire_version
        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "VERSION"
            chemin.write_text("1.2.3\nabc1234\n2026-09-17\n")
            self.assertEqual(lu(chemin), {"numero": "1.2.3", "commit": "abc1234", "date": "2026-09-17"})
            # Un HUB installé avant les numéros : une ligne, l'empreinte seule.
            chemin.write_text("v0.9-12-gabc1234-dirty\n")
            self.assertEqual(lu(chemin), {"numero": None, "commit": "abc1234", "date": None})
            # Le VERSION du dépôt, sans empreinte ni date.
            chemin.write_text("1.2.3\n")
            self.assertEqual(lu(chemin), {"numero": "1.2.3", "commit": None, "date": None})
            # Illisible ou absent : rien d'inventé.
            self.assertEqual(lu(Path(d) / "absent"), {"numero": None, "commit": None, "date": None})
            chemin.write_text("\n\n")
            self.assertEqual(lu(chemin), {"numero": None, "commit": None, "date": None})


class VersionPubliee(unittest.TestCase):
    """Si l'étiquette « v<VERSION> » existe, ce qui s'installe n'a pas bougé depuis.

    C'est le garde-fou qui compte : on ne publie pas deux contenus différents sous le
    même numéro. Hors dépôt git (clone d'archive, copie), il n'y a rien à comparer et
    le test ne s'applique pas."""

    def test_le_numero_change_des_que_ce_qui_s_installe_change(self):
        numero = numero_du_depot()
        if git("rev-parse", "--git-dir") is None:
            self.skipTest("pas un dépôt git : rien à comparer")
        if git("rev-parse", "--verify", f"refs/tags/v{numero}") is None:
            # Version en cours d'écriture : l'étiquette se pose au moment de publier
            # (installer/mise-a-jour/README.md). Rien à vérifier tant qu'elle n'existe pas.
            self.skipTest(f"v{numero} pas encore publiée")
        change = git("diff", "--name-only", f"v{numero}", "--", *INSTALLE)
        self.assertEqual(change, "", f"v{numero} est publiée et ces fichiers ont changé depuis :"
                                     f"\n{change}\nIncrémente VERSION et ajoute sa section à NOUVEAUTES.md.")


if __name__ == "__main__":
    unittest.main()
