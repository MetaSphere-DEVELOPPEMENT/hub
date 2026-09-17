"""hub-mise-a-jour contre un vrai dépôt git local : signature, tests, installation, retour.

Vrai git, vraies clés SSH (générées pour le test), vrais tests du dépôt simulé ;
l'installateur est simulé, et runuser aussi (ce poste n'est pas root) : on vérifie
que la commande passe par lui, puis on lance ce qu'elle contient.

    python3 -m unittest tests/test_hub_mise_a_jour.py
"""

import errno
import importlib.machinery
import importlib.util
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
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

    def test_signataires_du_depot_bien_formes(self):
        # Le fichier du dépôt porte la clé publique du propriétaire. Ce test exigeait
        # autrefois un modèle vide : il a échoué sur le HUB (17/09/2026) dès que la vraie
        # clé y a été ajoutée, et a bloqué la mise à jour. Ce qui compte, c'est que chaque
        # ligne soit une entrée allowed_signers que git sait lire, et qu'aucune ne soit
        # en double ; qu'il soit vide ou non, sa lecture doit rester cohérente.
        modele = chemin.parent / "signataires-autorises"
        self.assertTrue(modele.is_file())
        entrees = [l.strip() for l in modele.read_text(encoding="utf-8").splitlines()
                   if l.strip() and not l.lstrip().startswith("#")]
        self.assertEqual(len(entrees), len(set(entrees)), "entrée en double")
        for entree in entrees:
            champs = entree.split()
            self.assertGreaterEqual(len(champs), 4, entree)
            self.assertEqual(champs[1], 'namespaces="git"', entree)
            self.assertRegex(champs[2], r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+|sk-ssh-ed25519@openssh\.com)$", entree)
            self.assertRegex(champs[3], r"^[A-Za-z0-9+/]+=*$", entree)
        with tempfile.TemporaryDirectory() as d:
            copie = Path(d) / "s"
            shutil.copy(modele, copie)
            os.chmod(copie, 0o644)
            self.assertEqual(maj.signataires_autorises(copie)[0], bool(entrees))

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

    def test_sortie_non_utf8_ne_fait_pas_tomber_la_mise_a_jour(self):
        # Un installateur qui écrit un octet invalide (sortie d'apt, nom de fichier) levait
        # UnicodeDecodeError : hors des erreurs attrapées, le service tombait sans publier
        # d'état et le menu restait sur « Installation… ».
        r = maj.executer([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'caf\\xe9')"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("caf", r.stdout)

    def test_classement_des_messages_de_git(self):
        # Messages relevés avec git 2.54 (curl) le 17/09/2026, et ceux d'OpenSSH.
        cas = {
            "fatal: unable to access 'https://github.com/x/hub.git/': Could not resolve host: github.com": "reseau",
            "fatal: unable to access 'https://github.com/x/hub.git/': Failed to connect to github.com port 443 after 2 ms: Couldn't connect to server": "reseau",
            "error: RPC failed; curl 92 HTTP/2 stream 0 was not closed cleanly\nfatal: early EOF": "reseau",
            "fatal: unable to access 'https://github.com/x/hub.git/': SSL certificate problem: certificate is not yet valid": "reseau",
            "ssh: connect to host mac.local port 22: No route to host": "reseau",
            "remote: Repository not found.\nfatal: repository 'https://github.com/x/absent.git/' not found": "source",
            "fatal: could not read Username for 'https://github.com': terminal prompts disabled": "source",
            "warning: Could not find remote branch main to clone.\nfatal: Remote branch main not found in upstream origin": "source",
            "fatal: '/srv/absent' does not appear to be a git repository": "source",
            "fatal: detected dubious ownership in repository at '/srv/hub.git'": "source",
            "fatal: unable to access 'https://github.com/x/hub.git/': The requested URL returned error: 403": "source",
            "error: object 1234: badTimezone: invalid author/committer line\nfatal: fsck error in packed object": "clone",
        }
        for sortie, raison in cas.items():
            with self.subTest(sortie=sortie):
                self.assertEqual(maj.classer_git(sortie, "clone"), raison)

    def test_classement_des_exceptions(self):
        self.assertEqual(maj.classer_erreur(maj.Echec("reseau", "pas de DNS")), ("reseau", "pas de DNS"))
        raison, detail = maj.classer_erreur(subprocess.TimeoutExpired(["git", "clone", "x"], 600))
        self.assertEqual(raison, "delai")
        self.assertIn("600", detail)
        for numero in (errno.ENOSPC, errno.EACCES, errno.EROFS, errno.ENOTEMPTY):
            with self.subTest(numero=numero):
                raison, detail = maj.classer_erreur(OSError(numero, os.strerror(numero), "/var/lib/hub/versions/abc"))
                self.assertEqual(raison, "disque")
                self.assertIn("/var/lib/hub/versions/abc", detail)
        self.assertEqual(maj.classer_erreur(FileNotFoundError(errno.ENOENT, "No such file", "git"))[0], "autre")
        self.assertEqual(maj.classer_erreur(ValueError("inattendu"))[0], "autre")
        self.assertLessEqual(len(maj.classer_erreur(RuntimeError("x" * 5000))[1]), maj.DETAIL_MAX)

    def test_unite_lit_l_environnement_de_la_session(self):
        # « Rechercher » tourne dans la session (pam_env y a lu /etc/environment : proxy…),
        # « Installer » dans un service qui ne le lit pas : la même source pouvait répondre à
        # l'un et pas à l'autre. Et un mise-a-jour.env absent empêchait le service de
        # démarrer sans qu'aucun état ne soit publié.
        unite = (chemin.parent / "hub-mise-a-jour.service").read_text()
        self.assertIn("EnvironmentFile=-/etc/environment\n", unite)
        self.assertIn("EnvironmentFile=-/etc/hub/mise-a-jour.env\n", unite)
        self.assertLess(unite.index("/etc/environment"), unite.index("/etc/hub/mise-a-jour.env"))

    def test_configuration_absente_publiee_au_menu(self):
        with tempfile.TemporaryDirectory() as d:
            etats = []
            with mock.patch("sys.stdout"):
                self.assertEqual(maj.main(["appliquer"], config=Path(d) / "absent.json", ecrire=etats.append), 3)
            self.assertEqual((etats[-1]["etape"], etats[-1]["raison"]), ("echec", "configuration"))
            config = Path(d) / "c.json"
            config.write_text('{"source": "https://exemple.invalid/hub.git"}')
            etats.clear()
            with mock.patch.dict(os.environ, {}, clear=False), mock.patch("sys.stderr"):
                os.environ.pop("HUB_UTILISATEUR", None)
                self.assertEqual(maj.main(["appliquer"], config=config, ecrire=etats.append), 2)
            self.assertEqual((etats[-1]["etape"], etats[-1]["raison"]), ("echec", "configuration"))
            self.assertIn("HUB_UTILISATEUR", etats[-1]["detail"])


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
        self.pauses = []
        # Réponses simulées de git avant de laisser passer le vrai : [(motif, CompletedProcess | exception)].
        self.pannes = []
        # runuser n'existe pas sur un Mac, et vit dans /usr/sbin sur Ubuntu : le programme le
        # cherche par chemin absolu (PATH_ADMIN). On lui en donne un faux, jamais exécuté
        # puisque lancer() intercepte la commande.
        self.admin = racine / "admin"
        self.admin.mkdir()
        (self.admin / "runuser").write_text("#!/bin/sh\nexit 99\n")
        os.chmod(self.admin / "runuser", 0o755)
        self._path_admin = os.environ.get("PATH_ADMIN")
        os.environ["PATH_ADMIN"] = str(self.admin)

    def tearDown(self):
        if self._path_admin is None:
            os.environ.pop("PATH_ADMIN", None)
        else:
            os.environ["PATH_ADMIN"] = self._path_admin
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
        if Path(commande[0]).name == "runuser":
            self.lancements_tests.append((commande, options))
            return maj.executer(commande[4:], **options)
        self.commandes_git.append(commande)
        for i, (motif, reponse) in enumerate(self.pannes):
            if motif in commande:
                del self.pannes[i]
                if isinstance(reponse, BaseException):
                    raise reponse
                return reponse
        r = maj.executer(commande, **options)
        if "ls-remote" in commande and self.apres_ls_remote:
            self.apres_ls_remote()
        return r

    def lancer_les_tests(self, depot, lancer):
        return maj.lancer_tests(depot, lancer, donner=lambda dossier, compte: self.donnes.append((dossier, compte)))

    def appliquer(self, installee):
        config = {"source": str(self.source), "branche": "main"}
        return maj.appliquer(config, "samuel", dossier_versions=self.versions, etat=self.etats.append,
                             lancer=self.lancer, installee=installee, signataires=self.signataires, tests=self.lancer_les_tests,
                             attendre=self.pauses.append)

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
        self.assertEqual([Path(commande[0]).name, *commande[1:4]], ["runuser", "-u", "nobody", "--"])
        self.assertTrue(Path(commande[0]).is_absolute(), "runuser lancé par un chemin absolu, le PATH des tests est réduit")
        self.assertEqual(commande[-5:], ["-m", "unittest", "discover", "-s", "tests"])
        bac = Path(options["cwd"]).parent
        self.assertNotEqual(Path(options["cwd"]).resolve(), (self.versions / c).resolve())
        self.assertEqual(Path(options["env"]["HOME"]).parent, bac)
        self.assertNotIn("SUDO_USER", options["env"])
        self.assertEqual(self.donnes, [(str(bac), "nobody")])
        self.assertFalse(bac.exists(), "copie des tests effacée")

    def test_runuser_absent_le_dit_et_n_installe_rien(self):
        """Sans util-linux-extra (Ubuntu 26.04), runuser manque : l'échec le nomme au lieu
        de sortir en « source », et rien n'est installé (constaté sur le HUB le 17/09/2026)."""
        self.commit()
        os.environ["PATH_ADMIN"] = str(self.admin / "vide")
        self.assertEqual(self.appliquer(installee="0000000"), 1)
        self.assertEqual(self.etats[-1]["raison"], "outil")
        self.assertIn("util-linux-extra", self.etats[-1]["detail"])
        self.assertEqual(self.installations, [])

    def test_runuser_cherche_hors_du_path_des_tests(self):
        """Le PATH donné aux tests ne contient pas /usr/sbin, où vit runuser : il est
        cherché dans les dossiers d'administration et lancé par son chemin absolu."""
        self.assertEqual(maj.abaisseur(str(self.admin)), str(self.admin / "runuser"))
        with self.assertRaises(maj.Echec) as e:
            maj.abaisseur(str(self.admin / "vide"))
        self.assertEqual(e.exception.raison, "outil")

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

    def test_dossier_de_version_sans_git_remplace(self):
        # Reste d'un essai interrompu (coupure pendant un effacement) : un dossier au nom du
        # commit, sans .git. os.replace refusait d'écraser un dossier non vide, et l'OSError
        # remontait en « source injoignable ».
        c = self.commit()
        (self.versions / c / "installer").mkdir(parents=True)
        (self.versions / c / "installer" / "reste").write_text("x")
        self.assertEqual(self.appliquer(installee="0000000"), 0, self.etats[-1])
        self.assertEqual(self.installations, [(c, "samuel")])
        self.assertTrue((self.versions / c / ".git").is_dir())
        self.assertFalse((self.versions / c / "installer" / "reste").exists())

    def test_clone_provisoire_residuel_efface(self):
        c = self.commit()
        residuel = self.versions / f".{c}.tmp"
        (residuel / "tests").mkdir(parents=True)
        (residuel / "tests" / "vieux.py").write_text("x")
        self.assertEqual(self.appliquer(installee="0000000"), 0, self.etats[-1])
        self.assertFalse(residuel.exists())

    def test_reseau_coupe_un_instant_reessaye(self):
        c = self.commit()
        panne = subprocess.CompletedProcess([], 128, "", "fatal: unable to access 'https://github.com/x/hub.git/': Could not resolve host: github.com")
        self.pannes = [("ls-remote", panne), ("clone", panne)]
        self.assertEqual(self.appliquer(installee="0000000"), 0, self.etats[-1])
        self.assertEqual(self.installations, [(c, "samuel")])
        self.assertEqual(len(self.pauses), 2)

    def test_reseau_absent_classe_et_detaille(self):
        self.commit()
        panne = subprocess.CompletedProcess([], 128, "", "fatal: unable to access 'https://github.com/x/hub.git/': Could not resolve host: github.com")
        self.pannes = [("ls-remote", panne)] * (len(maj.ESSAIS_RESEAU) + 1)
        self.assertEqual(self.appliquer(installee="0000000"), 1)
        self.assertEqual((self.etats[-1]["etape"], self.etats[-1]["raison"]), ("echec", "reseau"))
        self.assertIn("Could not resolve host", self.etats[-1]["detail"])
        self.assertEqual(len(self.pauses), len(maj.ESSAIS_RESEAU))
        self.assertFalse(self.versions.exists(), "rien téléchargé")

    def test_source_introuvable_publiee_sans_exception(self):
        config = {"source": str(self.source / "absent"), "branche": "main"}
        code = maj.appliquer(config, "samuel", dossier_versions=self.versions, etat=self.etats.append, lancer=self.lancer,
                             installee="0000000", signataires=self.signataires, tests=self.lancer_les_tests, attendre=self.pauses.append)
        self.assertEqual(code, 1)
        self.assertEqual((self.etats[-1]["etape"], self.etats[-1]["raison"]), ("echec", "source"))
        self.assertIn("absent", self.etats[-1]["detail"])
        self.assertEqual(self.pauses, [], "une source introuvable ne se réessaie pas")

    def test_delai_du_clone_depasse(self):
        c = self.commit()
        self.pannes = [("clone", subprocess.TimeoutExpired(["git", "clone"], 600))]
        self.assertEqual(self.appliquer(installee="0000000"), 1)
        self.assertEqual((self.etats[-1]["raison"], self.etats[-1]["version"]), ("delai", c[:12]))
        self.assertEqual(self.installations, [])

    def test_clone_refuse_par_fsck_classe_clone(self):
        self.commit()
        self.pannes = [("clone", subprocess.CompletedProcess([], 128, "", "error: object 1234: badTimezone\nfatal: fsck error in packed object"))]
        self.assertEqual(self.appliquer(installee="0000000"), 1)
        self.assertEqual(self.etats[-1]["raison"], "clone")
        self.assertIn("fsck error", self.etats[-1]["detail"])
        self.assertEqual(self.pauses, [])

    def test_dossier_des_versions_inutilisable_classe_disque(self):
        self.commit()
        self.versions.write_text("un fichier à la place du dossier")
        self.assertEqual(self.appliquer(installee="0000000"), 1)
        self.assertEqual(self.etats[-1]["raison"], "disque")
        self.assertIn(str(self.versions), self.etats[-1]["detail"])

    def test_installateur_trop_long_revient_a_la_version_precedente(self):
        ancienne = self.commit()
        self.appliquer(installee="0000000")
        self.commit()
        lancer = self.lancer

        def trop_long(commande, **options):
            if commande[0] == "bash" and Path(options["cwd"]).name != ancienne:
                raise subprocess.TimeoutExpired(commande, 3600)
            return lancer(commande, **options)
        self.lancer = trop_long
        self.assertEqual(self.appliquer(installee=ancienne[:7]), 1)
        self.assertEqual((self.etats[-1]["raison"], self.etats[-1]["retour"]), ("installation", True))
        self.assertIn("60 minutes", self.etats[-1]["detail"])

    def test_source_injoignable(self):
        config = {"source": str(self.source / "absent"), "branche": "main"}
        with self.assertRaises(RuntimeError):
            maj.verifier(config, None)


if __name__ == "__main__":
    unittest.main()
