"""Les garde-fous du clavier-souris de la télécommande téléphone, gardés par la mise à jour.

POURQUOI ICI, EN PLUS de installer/telecommande/test_pointeur_service.py. La mise à jour
depuis le menu ne lance que `tests/` avant d'installer (hub-mise-a-jour, lancer_tests) :
une version qui ouvrirait le clavier du bureau à un téléphone non autorisé doit être
REFUSÉE par le HUB lui-même, pas seulement par la machine de développement.

Rien ici n'ouvre de port, ne lance openssl ni ne touche /dev/uinput : ces tests tournent
sous « nobody », dans une copie du dépôt, sur un HUB installé.

    python3 -m unittest tests/test_telecommande_souris.py
"""

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
TEL = RACINE / "installer" / "telecommande"


def charger(nom):
    spec = importlib.util.spec_from_file_location(nom, TEL / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


P = charger("hub_pointeur")
T = charger("hub_telecommande")

SESSION = "Active=yes\nLockedHint=no\nClass=user\nType=wayland\nRemote=no\n"


class Conditions(unittest.TestCase):
    """Pointeur.refus : chaque condition, seule, suffit à refuser."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.chemins = {"etat": d / "run/telecommande.json", "appairage": d / "run/appairage",
                        "socket": d / "run/menu.sock", "jetons": d / "config/jetons.json",
                        "photos": d / "photos", "tls": d / "config/tls", "reglages": d / "config/reglages.json"}
        self.contexte, self.session, self.acces = "bureau", SESSION, None
        routeur = T.Routeur(self.chemins["socket"], executer=self.lancer, kodi_http=None,
                            processus=lambda noms: [1] if (self.contexte == "bureau" and "gnome-shell" in noms)
                            or (self.contexte == "kodi" and "kodi" in noms) else [],
                            web_en_cours=lambda: self.contexte == "web")
        self.service = T.Service(self.chemins, routeur=routeur)
        self.service.pointeur = T.Pointeur(self.service, fabrique=lambda: self.fail("périphérique créé"),
                                           lancer=self.lancer, acces=lambda: self.acces)
        self.service.pointeur.DUREE_GARDE_S = -1  # pas de mémoire entre deux questions
        self.regler(True)

    def tearDown(self):
        self._tmp.cleanup()

    def lancer(self, commande, **_kw):
        import os
        sortie = f"2 {os.getuid()} salon seat0 tty2\n" if "list-sessions" in commande else self.session
        return subprocess.CompletedProcess(commande, 0, stdout=sortie, stderr="")

    def regler(self, valeur):
        self.chemins["reglages"].parent.mkdir(parents=True, exist_ok=True)
        self.chemins["reglages"].write_text(json.dumps({"systeme": {"telecommandeSouris": valeur}}))

    def refus(self, ident="abc123", sure=True, securise=True):
        return self.service.pointeur.refus(ident, sure, securise)

    def test_tout_reuni_c_est_permis(self):
        self.assertIsNone(self.refus())
        self.contexte = "web"
        self.assertIsNone(self.refus())

    def test_eteint_par_defaut(self):
        self.chemins["reglages"].unlink()
        self.assertEqual(self.refus(), "desactive")

    def test_seul_true_allume(self):
        for valeur in ("true", 1, "oui", None, {}, [True]):
            self.regler(valeur)
            self.assertEqual(self.refus(), "desactive", repr(valeur))

    def test_jamais_en_http(self):
        self.assertEqual(self.refus(securise=False), "connexion-non-securisee")

    def test_jamais_avec_un_jeton_qui_a_pu_voyager_en_clair(self):
        self.assertEqual(self.refus(sure=False), "jeton-non-sur")
        self.assertEqual(self.refus(ident=None), "jeton-non-sur")

    def test_jamais_dans_le_menu_ni_dans_kodi_ni_nulle_part(self):
        for contexte in ("kodi", "rien"):
            self.contexte = contexte
            self.assertEqual(self.refus(), "contexte", contexte)

    def test_jamais_ecran_verrouille_ni_ecran_de_connexion(self):
        self.session = SESSION.replace("LockedHint=no", "LockedHint=yes")
        self.assertEqual(self.refus(), "session-verrouillee")
        self.session = SESSION.replace("Active=yes", "Active=no")
        self.assertEqual(self.refus(), "session-en-arriere-plan")
        self.session = SESSION.replace("Class=user", "Class=greeter")
        self.assertEqual(self.refus(), "session-en-arriere-plan")
        self.session = ""
        self.assertEqual(self.refus(), "session-en-arriere-plan")

    def test_logind_muet_c_est_non(self):
        self.service.pointeur.lancer = lambda c, **k: None
        self.assertEqual(self.refus(), "session-inconnue")

    def test_uinput_inaccessible_dit_pourquoi(self):
        self.acces = "uinput-refuse"
        self.assertEqual(self.refus(), "uinput-refuse")

    def test_les_commandes_refusees_n_ouvrent_pas_le_peripherique(self):
        self.regler(False)
        for nom in T.TOUCHES_COMMANDE:
            r = self.service.executer_commande(nom, None, "abc123", True, True)
            self.assertEqual(r, {"ok": False, "cible": "bureau", "raison": "pointeur-desactive"})
        r = self.service.executer_commande("texte", "bonjour", "abc123", True, True)
        self.assertEqual(r["raison"], "pointeur-desactive")


class JetonsSurs(unittest.TestCase):
    def test_seul_le_code_tape_en_https_donne_un_jeton_sur(self):
        with tempfile.TemporaryDirectory() as d:
            jetons = T.Jetons(Path(d) / "jetons.json")
            ident, http, _a = jetons.creer("Pixel")
            _i, transfert, _a = jetons.creer("Pixel", remplace=ident, ajouter=True)
            _i, https, _a = jetons.creer("Pixel", remplace=ident, ajouter=True, sure=True)
            self.assertEqual(jetons.valide_detail(http), (ident, False))
            self.assertEqual(jetons.valide_detail(transfert), (ident, False))
            self.assertEqual(jetons.valide_detail(https), (ident, True))
            self.assertEqual(jetons.valide_detail("x" * 43), (None, False))
            # Un fichier d'avant cette version : aucun jeton n'y est sûr.
            contenu = json.loads((Path(d) / "jetons.json").read_text())
            for t in contenu["telephones"]:
                t.pop("sures")
            (Path(d) / "jetons.json").write_text(json.dumps(contenu))
            self.assertEqual(T.Jetons(Path(d) / "jetons.json").valide_detail(https), (ident, False))

    def test_une_empreinte_sure_inconnue_du_telephone_ne_vaut_rien(self):
        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "jetons.json"
            jetons = T.Jetons(chemin)
            ident, jeton, _a = jetons.creer("Pixel")
            contenu = json.loads(chemin.read_text())
            contenu["telephones"][0]["sures"] = ["0" * 64, True, None]
            chemin.write_text(json.dumps(contenu))
            self.assertEqual(T.Jetons(chemin).valide_detail(jeton), (ident, False))


class Peripherique(unittest.TestCase):
    def test_ni_ctrl_ni_alt_ni_super_ni_touches_de_fonction(self):
        interdits = {29, 97, 56, 125, 126, 99, 111} | set(range(59, 69)) | {87, 88}
        self.assertEqual(P.touches_declarees() & interdits, set())

    def test_la_page_ne_nomme_que_des_touches_de_la_liste(self):
        page = (TEL / "page.html").read_text(encoding="utf-8")
        demandees = set(re.findall(r'data-touche="([^"]+)"', page))
        self.assertTrue(demandees)
        self.assertLessEqual(demandees, set(P.TOUCHES_NOMMEES))
        self.assertLessEqual(set(T.TOUCHES_COMMANDE), set(P.TOUCHES_NOMMEES))


class Installation(unittest.TestCase):
    def setUp(self):
        self.script = (RACINE / "installer" / "hub-installer.sh").read_text(encoding="utf-8")
        self.regle = (TEL / "71-hub-uinput.rules").read_text(encoding="utf-8")

    def lignes_actives(self, texte):
        return [l for l in texte.splitlines() if l.strip() and not l.lstrip().startswith("#")]

    def test_regle_udev_groupe_dedie_jamais_input(self):
        actives = self.lignes_actives(self.regle)
        self.assertEqual(len(actives), 1)
        self.assertIn('KERNEL=="uinput"', actives[0])
        self.assertIn('GROUP="hub-uinput"', actives[0])
        self.assertIn('MODE="0660"', actives[0])
        self.assertNotIn("uaccess", actives[0])
        self.assertNotRegex(actives[0], r'MODE="0?66[67]"')

    def test_l_installateur_ne_met_personne_dans_le_groupe_input(self):
        for ligne in self.lignes_actives(self.script):
            if "usermod" in ligne or "gpasswd" in ligne or "adduser" in ligne:
                self.assertNotRegex(ligne, r"\binput\b", ligne)

    def test_la_regle_va_dans_rules_d_et_le_module_est_charge_au_demarrage(self):
        self.assertIn("/etc/udev/rules.d/71-hub-uinput.rules", self.script)
        self.assertIn("/etc/modules-load.d/hub-uinput.conf", self.script)
        self.assertEqual(self.lignes_actives((TEL / "hub-uinput.conf").read_text()), ["uinput"])
        self.assertIn('poser "$tel/hub_pointeur.py"', self.script)

    def test_l_etape_en_simulation_sous_set_u(self):
        """La fonction elle-même, extraite du script, avec de faux `poser`, `getent`, `id` :
        elle doit aller au bout sans variable indéfinie, et ne demander que ce groupe-là."""
        debut = self.script.index("souris_telecommande() {")
        fonction = self.script[debut:self.script.index("\n}\n", debut) + 3]
        harnais = """set -uo pipefail
POUR_DE_VRAI=0; UTILISATEUR=salon
poser() { echo "POSER $2 $3"; }
faire() { echo "FAIRE $*"; }
deja() { echo "DEJA $*"; }; ok() { echo "OK $*"; }; alerte() { echo "ALERTE $*"; }
getent() { return 2; }
id() { echo "salon adm hub"; }
""" + fonction + """
d=$(mktemp -d); touch "$d/hub_pointeur.py"
souris_telecommande "$d" /usr/local/lib/hub; echo "CODE $?"
souris_telecommande "$d/absent" /usr/local/lib/hub; echo "SANS $?"
"""
        r = subprocess.run(["bash", "-c", harnais], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stderr, "")
        sortie = r.stdout.splitlines()
        self.assertIn("CODE 0", sortie)
        self.assertEqual(sortie[-1], "SANS 0", "un dépôt sans hub_pointeur.py saute l'étape sans échouer")
        self.assertIn("POSER /usr/local/lib/hub/telecommande/hub_pointeur.py 0644", sortie)
        self.assertIn("POSER /etc/udev/rules.d/71-hub-uinput.rules 0644", sortie)
        self.assertIn("FAIRE groupadd --system hub-uinput", sortie)
        self.assertIn("FAIRE usermod -aG hub-uinput salon", sortie)
        self.assertFalse([l for l in sortie if re.search(r"(usermod|groupadd).*\binput\b", l)])

    def test_eteint_par_defaut_dans_le_menu(self):
        menu = (RACINE / "installer" / "menu" / "hub.js").read_text(encoding="utf-8")
        self.assertRegex(menu, r"\n\s*telecommandeSouris: false,")
        self.assertNotRegex(menu, r"telecommandeSouris: true")

    def test_l_unite_reste_sans_privileges(self):
        unite = (TEL / "hub-telecommande.service").read_text(encoding="utf-8")
        self.assertIn("NoNewPrivileges=yes", self.lignes_actives(unite))


if __name__ == "__main__":
    unittest.main()
