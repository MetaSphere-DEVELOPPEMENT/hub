"""L'écran du premier démarrage doit rester lisible et tenir jusqu'au bout.

Relevé par l'audit de design du 17/09/2026 (lecture de cle/premier-demarrage.sh) : la
sortie de hub-installer.sh défilait sur la console et chassait « Ne pas éteindre »,
aucune progression n'était affichée sur 20 à 40 min, et un échec restait 60 s à l'écran
avant l'écran de connexion. Ce test exécute le script avec de faux binaires ; il ne
remplace pas la vraie console du M720q (police, couleurs 24 bits, tty1).

    python3 -m unittest tests/test_premier_demarrage.py
"""

import os
import re
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SCRIPT = RACINE / "cle" / "premier-demarrage.sh"


def executable(chemin, texte):
    chemin.write_text("#!/bin/bash\n" + texte)
    chemin.chmod(chemin.stat().st_mode | stat.S_IEXEC)


def sans_couleurs(texte):
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", texte)


class PremierDemarrage(unittest.TestCase):
    def preparer(self, code_installateur):
        self.dossier = Path(tempfile.mkdtemp())
        faux, depot, self.journal = self.dossier / "bin", self.dossier / "depot", self.dossier / "journal"
        for d in (faux, depot / "installer", depot / "audit"):
            d.mkdir(parents=True)
        (depot / "audit" / "audit.sh").write_text("echo audit\n")
        # Titres copiés du vrai installateur, dans son ordre d'exécution, noyés dans du bruit d'apt.
        titres = [l for l in (RACINE / "installer" / "hub-installer.sh").read_text().splitlines()
                  if re.match(r'^\s*etape "[0-9]+\. ', l)]
        corps = "".join(f"{t.strip().replace('etape ', 'etape  ', 1)}\nfor i in $(seq 40); do echo \"Dépaquetage de paquet-$i …\"; done\n"
                        for t in titres[:3])
        executable(depot / "installer" / "hub-installer.sh",
                   'etape() { printf "\\n── %s\\n" "$1"; }\n'
                   + corps + f"echo 'E: dernière erreur d’apt'\nexit {code_installateur}\n"
                   + "\n".join(titres))  # le décompte lit le fichier entier ; « etape  » doublé ci-dessus n'est pas compté
        self.appels = self.dossier / "appels"
        for nom in ("plymouth", "chvt", "setterm"):
            executable(faux / nom, "exit 0\n")
        executable(faux / "runuser", 'while [ "$1" != -- ]; do shift; done; shift; exec "$@"\n')
        executable(faux / "systemctl", f'echo "systemctl $*" >>"{self.appels}"\n')
        # Réseau absent aux deux premiers essais : l'attente doit se redessiner sur place.
        executable(faux / "getent", f'n=$(cat "{self.dossier}/getent" 2>/dev/null || echo 0); '
                                    f'echo $((n+1)) >"{self.dossier}/getent"; [ "$n" -ge 2 ]\n')
        executable(faux / "sleep", 'exec /bin/sleep 0.02\n')
        env = dict(os.environ, PATH=f"{faux}:{os.environ['PATH']}", HUB_DEPOT=str(depot), HUB_JOURNAL=str(self.journal))
        return subprocess.Popen(["bash", str(SCRIPT)], env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_syntaxe(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)

    def test_reussite_ecran_resume_et_redemarrage(self):
        proc = self.preparer(0)
        sortie, erreurs = proc.communicate(timeout=60)
        ecran = sans_couleurs(sortie.decode())
        self.assertEqual(proc.returncode, 0, erreurs)
        self.assertEqual(erreurs, b"")
        # Le bruit de l'installateur va au journal, jamais à l'écran.
        self.assertNotIn("Dépaquetage", ecran)
        self.assertIn("Dépaquetage de paquet-40", (self.journal / "installateur.log").read_text())
        self.assertIn("Ne pas éteindre", ecran)
        self.assertIn("en attente du réseau", ecran)
        self.assertIn("Installation du HUB (15 étapes)", ecran)
        for titre in ("1. Audit préalable", "2. Outils de mesure", "3. Session HUB et menu"):
            self.assertRegex(ecran, rf"✓ {re.escape(titre)} \(\d+ min \d\d s\)")
        self.assertRegex(ecran, r"HUB installé en \d+ min \d\d s")
        # Moins d'une ligne d'écran par étape : l'en-tête ne peut plus défiler hors de la TV.
        lignes = [l for l in re.split(r"[\r\n]", ecran) if l.strip()]
        self.assertLess(len(lignes), 30, lignes)
        appels = self.appels.read_text()
        self.assertIn("systemctl disable hub-premier-demarrage.service", appels)
        self.assertIn("systemctl reboot", appels)

    def test_echec_reste_affiche_jusqua_une_touche(self):
        proc = self.preparer(3)
        time.sleep(4)
        self.assertIsNone(proc.poll(), "l'écran d'échec a disparu sans qu'on touche à rien")
        sortie, erreurs = proc.communicate(input=b"x", timeout=30)
        ecran = sans_couleurs(sortie.decode())
        self.assertEqual(proc.returncode, 0, erreurs)
        self.assertIn("L’installation du HUB a échoué (code 3", ecran)
        self.assertIn("étape « 3. Session HUB et menu »", ecran)
        self.assertIn("E: dernière erreur d’apt", ecran)
        self.assertIn("Appuyez sur une touche", ecran)
        # L'en-tête est redessiné au-dessus de l'échec, sans « Ne pas éteindre » qui
        # contredirait « éteignez et rallumez ».
        apres_effacement = sortie.decode().rsplit("\x1b[H\x1b[2J", 1)[-1]
        self.assertIn("H U B", apres_effacement)
        self.assertNotIn("Ne pas éteindre", apres_effacement)
        self.assertFalse(self.appels.exists() and "reboot" in self.appels.read_text())


if __name__ == "__main__":
    unittest.main()
