"""La clé HUB doit installer Ubuntu et poser le HUB SANS réseau.

Le 16/09/2026 sur le M720q, câble débranché : `packages:` demandait git, absent du
pool de l'ISO. L'installateur s'est arrêté avant late-commands — Ubuntu nue, sans
/opt/hub ni premier démarrage. Ce test ne remplace pas l'essai en VM sans réseau
(vm/essayer-cle.sh --sans-reseau) : il empêche seulement de recommettre ce défaut-là.

    python3 -m unittest tests/test_cle_hors_ligne.py
"""

import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
MODELE = RACINE / "cle" / "user-data.modele"
POOL = RACINE / "cle" / "paquets-iso-ubuntu-26.04.1.txt"


def section(texte, cle):
    """Les éléments « - … » de la liste YAML `cle:` sous autoinstall (sans dépendre de PyYAML)."""
    elements, dedans = [], False
    for ligne in texte.splitlines():
        if re.match(rf"^  {cle}:\s*$", ligne):
            dedans = True
            continue
        if dedans:
            m = re.match(r"^    - (.+?)\s*$", ligne)
            if m:
                elements.append(m.group(1).strip('"'))
            elif ligne.strip() and not ligne.lstrip().startswith("#"):
                break
    return elements


class CleHorsLigne(unittest.TestCase):
    def setUp(self):
        self.modele = MODELE.read_text()
        self.pool = {l.strip() for l in POOL.read_text().splitlines() if l.strip() and not l.startswith("#")}

    def test_liste_du_pool_plausible(self):
        self.assertGreater(len(self.pool), 100)
        self.assertIn("openssh-server", self.pool)

    def test_paquets_tous_dans_le_pool(self):
        paquets = section(self.modele, "packages")
        absents = [p for p in paquets if p not in self.pool]
        self.assertEqual(absents, [], "absents du pool de l'ISO : l'installation hors ligne s'arrêterait avant late-commands")

    def test_serveur_ssh_installable_hors_ligne(self):
        if re.search(r"^\s+install-server:\s*true", self.modele, re.M):
            self.assertIn("openssh-server", self.pool)

    def test_late_commands_sans_reseau(self):
        commandes = section(self.modele, "late-commands")
        self.assertTrue(any("/opt/hub" in c for c in commandes))
        for c in commandes:
            self.assertNotRegex(c, r"\b(apt|apt-get|curl|wget|git|snap|pip3?)\b", c)

    def test_rien_qui_telecharge(self):
        # Pilotes propriétaires et codecs viennent de l'archive, pas du pool de l'ISO.
        for cle in ("drivers", "codecs"):
            self.assertNotRegex(self.modele, rf"(?ms)^  {cle}:\s*\n\s+install:\s*true", cle)


if __name__ == "__main__":
    unittest.main()
