"""La vérification de librespot de hub-installer.sh (étape 14), sur de faux binaires.

Le 17/09/2026, sur le M720q, l'installateur a refusé le vrai librespot : il exigeait
l'égalité exacte avec « librespot 0.8.0 9c7d7561 » alors que le binaire ajoute
« (Built on …, Profile: release) ». On teste ici la fonction elle-même, extraite du
script, sous `set -u` comme dans l'installateur.

    python3 -m unittest tests/test_hub_installer_librespot.py
"""

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
INSTALLATEUR = RACINE / "installer" / "hub-installer.sh"
PREUVE = RACINE / "installer" / "enceinte" / "preuve" / "preuve.sh"

# La ligne réelle, relevée sur le M720q le 17/09/2026 (librespot --version, stdout).
REELLE = "librespot 0.8.0 9c7d7561 (Built on 2026-07-18, Build ID: PxD46HQ7, Profile: release)"


def extraire(script):
    """Les constantes LIBRESPOT_* et librespot_attendu, telles qu'écrites dans le script."""
    lignes = script.read_text().splitlines()
    garde, dans_fonction = [], False
    for ligne in lignes:
        if re.match(r"^LIBRESPOT_[A-Z0-9_]+=", ligne):
            garde.append(ligne)
        elif ligne.startswith("librespot_attendu() {"):
            dans_fonction = True
        if dans_fonction:
            garde.append(ligne)
            if ligne == "}":
                dans_fonction = False
    return "\n".join(garde)


class LibrespotAttendu(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self._tmp.name)
        self.code = extraire(INSTALLATEUR)
        self.assertIn("librespot_attendu() {", self.code)

    def tearDown(self):
        self._tmp.cleanup()

    def faux(self, sortie, erreur="", code=0):
        binaire = self.dossier / "librespot"
        binaire.write_text(
            "#!/bin/sh\n"
            f"[ \"$1\" = --version ] || exit 9\n"
            f"printf '%s' '{sortie}'\n"
            f"printf '%s' '{erreur}' >&2\n"
            f"exit {code}\n"
        )
        binaire.chmod(0o755)
        return binaire

    def accepte(self, binaire):
        r = subprocess.run(
            ["bash", "-c", f'set -uo pipefail\n{self.code}\nlibrespot_attendu "$1"', "test", str(binaire)],
            capture_output=True, text=True,
        )
        # Une variable mal écrite ferait échouer `set -u` avec un message : ce n'est pas un refus.
        self.assertEqual(r.stderr, "", r.stderr)
        return r.returncode == 0

    def test_reponse_exacte(self):
        self.assertTrue(self.accepte(self.faux("librespot 0.8.0 9c7d7561\n")))

    def test_reponse_suffixee_du_m720q(self):
        self.assertTrue(self.accepte(self.faux(REELLE + "\n")))

    def test_seule_la_premiere_ligne_compte(self):
        self.assertTrue(self.accepte(self.faux(REELLE + "\nautre chose\n")))
        self.assertFalse(self.accepte(self.faux("avertissement\n" + REELLE + "\n")))

    def test_mauvais_commit(self):
        self.assertFalse(self.accepte(self.faux("librespot 0.8.0 9c7d756 (Built on 2026-07-18)\n")))
        self.assertFalse(self.accepte(self.faux("librespot 0.8.0 9c7d756\n")))

    def test_prefixe_trompeur(self):
        self.assertFalse(self.accepte(self.faux("librespot 0.8.0 9c7d75610\n")))
        self.assertFalse(self.accepte(self.faux("librespot 0.8.0 9c7d75610 (Built on 2026-07-18)\n")))

    def test_autre_version(self):
        self.assertFalse(self.accepte(self.faux("librespot 0.8.1 9c7d7561 (Built on 2026-07-18)\n")))

    def test_rien_sur_stdout(self):
        self.assertFalse(self.accepte(self.faux("", erreur=REELLE + "\n")))
        self.assertFalse(self.accepte(self.faux("", code=1)))

    def test_binaire_absent(self):
        self.assertFalse(self.accepte(self.dossier / "absent"))


class PlusDeComparaisonExacte(unittest.TestCase):
    def test_installateur_passe_par_la_fonction(self):
        script = INSTALLATEUR.read_text()
        self.assertNotRegex(script, r'= "\$LIBRESPOT_VERSION"')
        self.assertGreaterEqual(script.count('librespot_attendu "$opt/librespot"'), 2)

    def test_la_preuve_verifie_avec_l_installateur(self):
        # La preuve affichait la version sans la comparer : le défaut est passé inaperçu.
        preuve = PREUVE.read_text()
        self.assertIn("librespot_attendu", preuve)
        self.assertNotIn("raspotify_0.48.2", preuve, "l'URL doit venir de hub-installer.sh, pas d'une copie")


if __name__ == "__main__":
    unittest.main()
