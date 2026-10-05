"""Ce que hub-installer.sh pose, sans l'exécuter : destinations et versions.

    python3 -m unittest tests/test_hub_installer.py

Deux défauts vus à la relecture du 06/10/2026 : la règle udev de l'adaptateur CEC était
posée dans /etc/udev/rules/, qu'udev ne lit pas (seul rules.d compte) — l'adaptateur
serait resté à root ; et depuis la clé USB, sans .git, aucune empreinte n'était écrite.
"""

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
INSTALLATEUR = RACINE / "installer" / "hub-installer.sh"


class Destinations(unittest.TestCase):
    def test_les_regles_vont_dans_rules_d(self):
        script = INSTALLATEUR.read_text(encoding="utf-8")
        destinations = re.findall(r'poser\s+"[^"]+\.rules"\s+(\S+\.rules)', script)
        self.assertGreaterEqual(len(destinations), 3, "udev CEC, udev uinput, polkit…")
        for destination in destinations:
            self.assertRegex(destination, r"^/etc/(udev|polkit-1)/rules\.d/", destination)

    def test_la_regle_cec_et_son_readme_disent_le_meme_chemin(self):
        regle = (RACINE / "installer" / "cec" / "70-hub-cec.rules").read_text(encoding="utf-8")
        readme = (RACINE / "installer" / "cec" / "README.md").read_text(encoding="utf-8")
        for texte in (regle, readme):
            self.assertIn("/etc/udev/rules.d/70-hub-cec.rules", texte)
            self.assertNotIn("/etc/udev/rules/70", texte)


def extraire_poser_version(script):
    """La fonction poser_version telle qu'écrite, avec de quoi la lancer à vide."""
    debut = script.index("poser_version() {")
    fin = script.index("\n}\n", debut) + 3
    return script[debut:fin]


class VersionDepuisLaCle(unittest.TestCase):
    """Depuis la clé USB il n'y a pas de .git : l'empreinte et la date viennent de COMMIT."""

    def ecrire_version(self, depot):
        code = extraire_poser_version(INSTALLATEUR.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as cible:
            # Le script écrit /usr/local/share/hub/VERSION : on détourne le chemin vers un
            # dossier jetable et on remplace install par un cp, le reste est tel quel.
            code_essai = code.replace("cible=/usr/local/share/hub/VERSION", f"cible={cible}/VERSION")
            script = (
                "set -u\n"
                f"DEPOT={depot}/installer\nPOUR_DE_VRAI=1\n"
                "deja() { :; }\nok() { :; }\nalerte() { echo \"ALERTE $1\"; }\n"
                # install -D n'existe pas sur le BSD install d'un Mac : copie simple.
                "faire() { if [ \"$1\" = install ]; then cp \"${@: -2:1}\" \"${@: -1}\"; else \"$@\"; fi; }\nposer() { :; }\n"
                + code_essai + "\nposer_version\n"
                f"cat {cible}/VERSION\n"
            )
            r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout

    def test_sans_git_ni_commit_le_numero_seul(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "installer").mkdir()
            (Path(d) / "VERSION").write_text("1.2.3\n")
            lignes = self.ecrire_version(d).splitlines()
        self.assertEqual(lignes[0], "1.2.3")

    def test_commit_de_la_cle_donne_empreinte_et_date(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "installer").mkdir()
            (Path(d) / "VERSION").write_text("1.2.3\n")
            (Path(d) / "COMMIT").write_text("b55acf7a9c2e9f3d4b1c0d2e3f4a5b6c7d8e9f01\n2026-10-06\n")
            lignes = self.ecrire_version(d).splitlines()
        self.assertEqual(lignes, ["1.2.3", "b55acf7a9c2e9f3d4b1c0d2e3f4a5b6c7d8e9f01", "2026-10-06"])

    def test_commit_abime_n_injecte_rien(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "installer").mkdir()
            (Path(d) / "VERSION").write_text("1.2.3\n")
            (Path(d) / "COMMIT").write_text("$(touch /tmp/pwn) b55acf7\npas une date\n")
            lignes = self.ecrire_version(d).splitlines()
        self.assertEqual(lignes[:2], ["1.2.3", "b55acf7"])
        self.assertEqual(lignes[2:], [], "une date qui n'en est pas une n'est pas écrite")


class Cle(unittest.TestCase):
    def test_l_archive_de_la_cle_emporte_version_nouveautes_tests_et_licence(self):
        script = (RACINE / "cle" / "construire-cle.sh").read_text(encoding="utf-8")
        archive = re.search(r"git -C \"\$RACINE\" archive HEAD ([^|]+)\|", script).group(1).split()
        for element in ("installer", "cle", "tests", "VERSION", "NOUVEAUTES.md", "LICENSE"):
            self.assertIn(element, archive)
        self.assertNotIn('describe --always --dirty > "$travail/hub/VERSION"', script,
                         "VERSION doit rester le numéro seul : l'empreinte va dans COMMIT")
        self.assertIn('"$travail/hub/COMMIT"', script)

    def test_l_identite_de_la_cle_est_remplie_pas_ecrite_dans_le_depot(self):
        modele = (RACINE / "cle" / "user-data.modele").read_text(encoding="utf-8")
        self.assertIn('username: "@UTILISATEUR@"', modele)
        self.assertIn('realname: "@NOM@"', modele)
        script = (RACINE / "cle" / "construire-cle.sh").read_text(encoding="utf-8")
        self.assertIn("s|@UTILISATEUR@|", script)
        self.assertIn("s|@NOM@|", script)
        premier = (RACINE / "cle" / "premier-demarrage.sh").read_text(encoding="utf-8")
        self.assertNotRegex(premier, r"^UTILISATEUR=[a-z]+\s*$", "le compte est lu sur la machine, pas écrit ici")


if __name__ == "__main__":
    unittest.main()
