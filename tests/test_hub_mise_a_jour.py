"""hub-mise-a-jour contre un vrai dépôt git local : vérifier, tests, installation, retour."""

import importlib.machinery
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

chemin = Path(__file__).resolve().parent.parent / "installer" / "mise-a-jour" / "hub-mise-a-jour"
chargeur = importlib.machinery.SourceFileLoader("hub_mise_a_jour", str(chemin))
spec = importlib.util.spec_from_loader("hub_mise_a_jour", chargeur)
maj = importlib.util.module_from_spec(spec)
chargeur.exec_module(maj)

TEST_OK = "import unittest\nclass T(unittest.TestCase):\n    def test(self): pass\n"
TEST_KO = "import unittest\nclass T(unittest.TestCase):\n    def test(self): self.fail('cassé')\n"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class DepotLocal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        racine = Path(self._tmp.name)
        self.source = racine / "source"
        self.versions = racine / "versions"
        self.source.mkdir()
        # symbolic-ref plutôt que « init -b » : un vieux git (2.9) traîne dans /usr/local/bin sur la machine de travail.
        git("init", "-q", cwd=self.source)
        git("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.source)
        git("config", "user.email", "t@t", cwd=self.source)
        git("config", "user.name", "t", cwd=self.source)
        self.etats = []
        self.installations = []
        self.echouer_installation = set()

    def tearDown(self):
        self._tmp.cleanup()

    def commit(self, test=TEST_OK):
        (self.source / "tests").mkdir(exist_ok=True)
        (self.source / "tests" / "test_x.py").write_text(test)
        (self.source / "installer").mkdir(exist_ok=True)
        (self.source / "installer" / "hub-installer.sh").write_text("exit 0\n")
        git("add", "-A", cwd=self.source)
        git("commit", "-q", "-m", "v", "--allow-empty", cwd=self.source)
        return git("rev-parse", "HEAD", cwd=self.source)

    def lancer(self, commande, **options):
        """Vrai git et vrais tests ; l'installateur est simulé et noté."""
        if commande[0] == "bash":
            depot = Path(options["cwd"]).name
            self.installations.append((depot, options["env"]["SUDO_USER"]))
            code = 1 if depot in self.echouer_installation else 0
            return subprocess.CompletedProcess(commande, code, "", "installateur en échec" if code else "")
        return maj.executer(commande, **options)

    def appliquer(self, installee):
        config = {"source": str(self.source), "branche": "main"}
        return maj.appliquer(config, "samuel", dossier_versions=self.versions,
                             etat=self.etats.append, lancer=self.lancer, installee=installee)

    def test_verifier_compare_au_commit_installe(self):
        c = self.commit()
        config = {"source": str(self.source), "branche": "main"}
        self.assertFalse(maj.verifier(config, c[:7])["disponible"])
        self.assertTrue(maj.verifier(config, "0123abc")["disponible"])

    def test_version_installee_lit_git_describe(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("v1.2-14-g3eb4bf5-dirty\n")
        self.assertEqual(maj.version_installee(f.name), "3eb4bf5")
        Path(f.name).write_text("3eb4bf5\n")
        self.assertEqual(maj.version_installee(f.name), "3eb4bf5")

    def test_nouvelle_version_testee_puis_installee_pour_l_utilisateur(self):
        c = self.commit()
        self.assertEqual(self.appliquer(installee="0000000"), 0)
        self.assertEqual(self.installations, [(c, "samuel")])
        self.assertEqual([e["etape"] for e in self.etats], ["verification", "telechargement", "tests", "installation", "terminee"])
        self.assertTrue((self.versions / c / ".git").is_dir())

    def test_deja_a_jour_ne_fait_rien(self):
        c = self.commit()
        self.assertEqual(self.appliquer(installee=c[:7]), 0)
        self.assertEqual(self.installations, [])
        self.assertEqual(self.etats[-1]["etape"], "a-jour")

    def test_tests_en_echec_rien_n_est_installe(self):
        self.commit(TEST_KO)
        self.assertEqual(self.appliquer(installee="0000000"), 1)
        self.assertEqual(self.installations, [])
        self.assertEqual(self.etats[-1]["raison"], "tests")

    def test_installation_en_echec_revient_a_la_version_precedente(self):
        ancienne = self.commit()
        self.appliquer(installee="0000000")
        nouvelle = self.commit()
        self.echouer_installation = {nouvelle}
        self.assertEqual(self.appliquer(installee=ancienne[:7]), 1)
        self.assertEqual(self.installations[-2:], [(nouvelle, "samuel"), (ancienne, "samuel")])
        self.assertEqual(self.etats[-1]["etape"], "echec")
        self.assertTrue(self.etats[-1]["retour"])

    def test_source_injoignable(self):
        config = {"source": str(self.source / "absent"), "branche": "main"}
        with self.assertRaises(RuntimeError):
            maj.verifier(config, None)

    def test_config(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "c.json"
            self.assertIsNone(maj.lire_config(f))
            f.write_text(json.dumps({"source": "git@github.com:moi/hub.git"}))
            self.assertEqual(maj.lire_config(f), {"source": "git@github.com:moi/hub.git", "branche": "main"})


if __name__ == "__main__":
    unittest.main()
