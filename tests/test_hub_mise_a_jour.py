"""hub-mise-a-jour contre un vrai dépôt git local : signature, tests, installation, retour.

Vrai git, vraies clés SSH (générées pour le test), vrais tests du dépôt simulé ;
l'installateur est simulé, et runuser aussi (ce poste n'est pas root) : on vérifie
que la commande passe par lui, puis on lance ce qu'elle contient.

    python3 -m unittest tests/test_hub_mise_a_jour.py
"""

import importlib.machinery
import importlib.util
import json
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

chemin = Path(__file__).resolve().parent.parent / "installer" / "mise-a-jour" / "hub-mise-a-jour"
chargeur = importlib.machinery.SourceFileLoader("hub_mise_a_jour", str(chemin))
spec = importlib.util.spec_from_loader("hub_mise_a_jour", chargeur)
maj = importlib.util.module_from_spec(spec)
chargeur.exec_module(maj)

TEST_OK = "import unittest\nclass T(unittest.TestCase):\n    def test(self): pass\n"
TEST_KO = "import unittest\nclass T(unittest.TestCase):\n    def test(self): self.fail('cassé')\n"
# Des tests qui écrivent là où ils tournent, et qui échouent s'ils voient le .git :
# ils doivent tourner dans une copie, jamais dans le clone que root installera.
TEST_ECRIT = ("import unittest\nfrom pathlib import Path\nclass T(unittest.TestCase):\n"
              "    def test(self):\n        self.assertFalse(Path('.git').exists())\n"
              "        Path('trace-des-tests').write_text('x')\n")


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def version_de_git():
    try:
        sortie = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout
    except OSError:
        return ()
    trouve = re.search(r"(\d+)\.(\d+)", sortie)
    return tuple(int(x) for x in trouve.groups()) if trouve else ()


# Les signatures SSH de git datent de la 2.34 (Ubuntu 26.04 en a une bien plus récente).
SIGNATURES_SSH = version_de_git() >= (2, 34) and shutil.which("ssh-keygen") is not None


class Lectures(unittest.TestCase):
    def test_version_installee_lit_git_describe(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("v1.2-14-g3eb4bf5-dirty\n")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(maj.version_installee(f.name), "3eb4bf5")
        Path(f.name).write_text("3eb4bf5\n")
        self.assertEqual(maj.version_installee(f.name), "3eb4bf5")

    def test_config(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "c.json"
            self.assertIsNone(maj.lire_config(f))
            f.write_text(json.dumps({"source": "git@github.com:moi/hub.git"}))
            self.assertEqual(maj.lire_config(f), {"source": "git@github.com:moi/hub.git", "branche": "main"})

    def test_modele_du_depot_ne_contient_aucune_cle(self):
        # Le modèle livré est vide : tant que le propriétaire n'y a pas mis sa clé, un HUB
        # installé avec refuse les mises à jour au lieu de faire confiance à n'importe qui.
        modele = chemin.parent / "signataires-autorises"
        self.assertTrue(modele.is_file())
        with tempfile.TemporaryDirectory() as d:
            copie = Path(d) / "s"
            shutil.copy(modele, copie)
            os.chmod(copie, 0o644)
            self.assertEqual(maj.signataires_autorises(copie)[0], False)

    def test_propriete_donnee_sans_suivre_les_liens(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "sous").mkdir()
            (Path(d) / "sous" / "f").write_text("x")
            os.symlink("/etc/passwd", Path(d) / "sous" / "lien")
            moi = pwd.getpwuid(os.getuid())
            with mock.patch.object(maj.os, "chown") as chown, mock.patch.object(maj.pwd, "getpwnam", return_value=moi):
                maj.donner_au_compte(d, "nobody")
            touches = {c.args[0] for c in chown.call_args_list}
            self.assertIn(os.path.join(d, "sous", "lien"), touches)
            self.assertNotIn("/etc/passwd", touches)
            self.assertTrue(all(c.kwargs.get("follow_symlinks") is False for c in chown.call_args_list))


@unittest.skipUnless(SIGNATURES_SSH, "git ≥ 2.34 et ssh-keygen nécessaires aux signatures SSH")
class DepotLocal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cles = tempfile.TemporaryDirectory()
        cls.cles = Path(cls._cles.name)
        for nom in ("autorisee", "autre"):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", nom, "-f", str(cls.cles / nom)],
                           check=True, stdin=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        cls._cles.cleanup()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        racine = Path(self._tmp.name)
        self.source = racine / "source"
        self.versions = racine / "versions"
        self.signataires = racine / "signataires-autorises"
        self.source.mkdir()
        # symbolic-ref plutôt que « init -b » : ne dépend pas de la version de git.
        git("init", "-q", cwd=self.source)
        git("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.source)
        git("config", "user.email", "t@t", cwd=self.source)
        git("config", "user.name", "t", cwd=self.source)
        git("config", "gpg.format", "ssh", cwd=self.source)
        cle = (self.cles / "autorisee.pub").read_text().split()
        self.signataires.write_text(f"# propriétaire\nhub@test namespaces=\"git\" {cle[0]} {cle[1]}\n")
        os.chmod(self.signataires, 0o644)
        self.etats = []
        self.installations = []
        self.verifies = []
        self.lancements_tests = []
        self.donnes = []
        self.commandes_git = []
        self.apres_ls_remote = None
        self.echouer_installation = set()

    def tearDown(self):
        self._tmp.cleanup()

    def commit(self, test=TEST_OK, cle="autorisee"):
        (self.source / "tests").mkdir(exist_ok=True)
        (self.source / "tests" / "test_x.py").write_text(test)
        (self.source / "installer").mkdir(exist_ok=True)
        (self.source / "installer" / "hub-installer.sh").write_text("exit 0\n")
        git("add", "-A", cwd=self.source)
        signature = ["-c", f"user.signingkey={self.cles / cle}.pub", "commit", "-S"] if cle else ["commit", "--no-gpg-sign"]
        git(*signature, "-q", "-m", "v", "--allow-empty", cwd=self.source)
        return git("rev-parse", "HEAD", cwd=self.source)

    def lancer(self, commande, **options):
        """Vrai git et vrais tests ; l'installateur est simulé et noté, runuser est retiré."""
        if commande[0] == "bash":
            depot = Path(options["cwd"]).name
            self.installations.append((depot, options["env"]["SUDO_USER"]))
            self.verifies.append(options["env"].get("HUB_MISE_A_JOUR_VERIFIEE"))
            code = 1 if depot in self.echouer_installation else 0
            return subprocess.CompletedProcess(commande, code, "", "installateur en échec" if code else "")
        if commande[0] == "runuser":
            self.lancements_tests.append((commande, options))
            return maj.executer(commande[4:], **options)
        self.commandes_git.append(commande)
        r = maj.executer(commande, **options)
        if "ls-remote" in commande and self.apres_ls_remote:
            self.apres_ls_remote()
        return r

    def lancer_les_tests(self, depot, lancer):
        return maj.lancer_tests(depot, lancer, donner=lambda dossier, compte: self.donnes.append((dossier, compte)))

    def appliquer(self, installee):
        config = {"source": str(self.source), "branche": "main"}
        return maj.appliquer(config, "samuel", dossier_versions=self.versions, etat=self.etats.append,
                             lancer=self.lancer, installee=installee, signataires=self.signataires, tests=self.lancer_les_tests)

    def test_verifier_compare_au_commit_installe(self):
        c = self.commit()
        config = {"source": str(self.source), "branche": "main"}
        self.assertFalse(maj.verifier(config, c[:7], signataires=self.signataires)["disponible"])
        reponse = maj.verifier(config, "0123abc", signataires=self.signataires)
        self.assertTrue(reponse["disponible"])
        self.assertTrue(reponse["verifiable"])

    def test_verifier_signale_une_version_non_verifiable(self):
        self.commit()
        config = {"source": str(self.source), "branche": "main"}
        reponse = maj.verifier(config, "0123abc", signataires=self.signataires.with_name("absent"))
        self.assertTrue(reponse["disponible"])
        self.assertFalse(reponse["verifiable"])
        self.assertEqual(reponse["raison"], "signataires")

    def test_version_signee_testee_sans_root_puis_installee(self):
        c = self.commit()
        self.assertEqual(self.appliquer(installee="0000000"), 0)
        self.assertEqual(self.installations, [(c, "samuel")])
        self.assertEqual(self.verifies, [c])
        self.assertEqual([e["etape"] for e in self.etats], ["verification", "telechargement", "tests", "installation", "terminee"])
        self.assertEqual(self.etats[-1]["signataire"], "hub@test")
        self.assertTrue((self.versions / c / ".git").is_dir())
        # Les tests passent par runuser, sous nobody, avec une maison jetable, hors du clone.
        (commande, options), = self.lancements_tests
        self.assertEqual(commande[:4], ["runuser", "-u", "nobody", "--"])
        self.assertEqual(commande[-5:], ["-m", "unittest", "discover", "-s", "tests"])
        bac = Path(options["cwd"]).parent
        self.assertNotEqual(Path(options["cwd"]).resolve(), (self.versions / c).resolve())
        self.assertEqual(Path(options["env"]["HOME"]).parent, bac)
        self.assertNotIn("SUDO_USER", options["env"])
        self.assertEqual(self.donnes, [(str(bac), "nobody")])
        self.assertFalse(bac.exists(), "copie des tests effacée")

    def test_clone_superficiel_sans_sous_modules(self):
        c = self.commit()
        self.commit()
        maj.cloner({"source": str(self.source), "branche": "main"}, c, self.versions, self.lancer)
        clone = next(commande for commande in self.commandes_git if "clone" in commande)
        for option in ("--depth", "--single-branch", "--no-recurse-submodules", "--no-local"):
            self.assertIn(option, clone)
        depot = next(self.versions.iterdir())
        self.assertEqual(git("rev-parse", "--is-shallow-repository", cwd=depot), "true")

    def test_les_tests_ne_touchent_pas_le_clone(self):
        c = self.commit(TEST_ECRIT)
        self.assertEqual(self.appliquer(installee="0000000"), 0, self.etats[-1])
        self.assertFalse((self.versions / c / "trace-des-tests").exists())

    def test_commit_non_signe_refuse(self):
        c = self.commit(cle=None)
        self.assertEqual(self.appliquer(installee="0000000"), 1)
        self.assertEqual((self.etats[-1]["etape"], self.etats[-1]["raison"]), ("echec", "signature"))
        self.assertEqual(self.installations, [])
        self.assertEqual(self.lancements_tests, [], "aucun code du clone avant la vérification")
        self.assertFalse((self.versions / c).exists(), "clone refusé effacé")

    def test_commit_signe_par_une_autre_cle_refuse(self):
        self.commit(cle="autre")
        self.assertEqual(self.appliquer(installee="0000000"), 1)
        self.assertEqual(self.etats[-1]["raison"], "signature")
        self.assertIn("non signé par une clé autorisée", self.etats[-1]["detail"])
        self.assertEqual((self.installations, self.lancements_tests), ([], []))

    def test_sans_signataires_rien_n_est_telecharge(self):
        self.commit()
        contenu = self.signataires.read_text()
        for preparer in (lambda: self.signataires.unlink(),
                         lambda: self.signataires.write_text("# modèle vide\n\n"),
                         lambda: os.chmod(self.signataires, 0o666)):
            with self.subTest():
                self.signataires.write_text(contenu)
                os.chmod(self.signataires, 0o644)
                preparer()
                self.etats.clear()
                self.assertEqual(self.appliquer(installee="0000000"), 1)
                self.assertEqual((self.etats[-1]["etape"], self.etats[-1]["raison"]), ("echec", "signataires"))
                self.assertIn("aucun signataire autorisé", self.etats[-1]["detail"])
                self.assertFalse(self.versions.exists())
                self.assertEqual(self.installations, [])

    def test_la_version_verifiee_est_celle_du_clone_pas_celle_annoncee(self):
        # La source avance d'un commit non signé entre ls-remote et le clone.
        self.commit()
        self.apres_ls_remote = lambda: self.commit(cle=None)
        self.assertEqual(self.appliquer(installee="0000000"), 1)
        self.assertEqual(self.etats[-1]["raison"], "signature")
        self.assertEqual(self.etats[-1]["version"], git("rev-parse", "HEAD", cwd=self.source)[:12])
        self.assertEqual(self.installations, [])

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
        # Le retour ne se présente pas comme une version fraîchement vérifiée.
        self.assertEqual(self.verifies[-2:], [nouvelle, None])
        self.assertEqual(self.etats[-1]["etape"], "echec")
        self.assertTrue(self.etats[-1]["retour"])

    def test_source_injoignable(self):
        config = {"source": str(self.source / "absent"), "branche": "main"}
        with self.assertRaises(RuntimeError):
            maj.verifier(config, None)


if __name__ == "__main__":
    unittest.main()
