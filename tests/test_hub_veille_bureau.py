"""Le mode ambiant sur le bureau Ubuntu : quand hub-veille-bureau lance l'ambiant, ce que
hub-menu --ambiant accepte, et ce que le temps d'écran en retient.

    python3 -m unittest tests/test_hub_veille_bureau.py

Ni GNOME ni Mutter ici : le bus D-Bus est un faux qui répond ce qu'on lui dit et note
les appels ; gsettings aussi.
"""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import re
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
INSTALLER = RACINE / "installer"


def charger(nom, chemin):
    chargeur = importlib.machinery.SourceFileLoader(nom, str(chemin))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(nom, chargeur))
    chargeur.exec_module(module)
    return module


vb = charger("hub_veille_bureau", INSTALLER / "veille" / "hub-veille-bureau")
hub_menu = charger("hub_menu_ambiant", INSTALLER / "hub-menu.py")
te = charger("hub_temps_ecran_ambiant", INSTALLER / "hub-temps-ecran")


# ── Le délai ──────────────────────────────────────────────────────────────
class Delai(unittest.TestCase):
    def test_profil_actif_puis_reglage_commun_puis_dix_minutes(self):
        profils = [{"id": "a", "veille": None}, {"id": "b", "veille": 5}]
        self.assertEqual(vb.minutes_veille({"profilActif": "b", "profils": profils, "systeme": {"veille": 30}}), 5)
        self.assertEqual(vb.minutes_veille({"profilActif": "a", "profils": profils, "systeme": {"veille": 30}}), 30)
        self.assertEqual(vb.minutes_veille({"profilActif": "a", "profils": profils}), 10)
        self.assertEqual(vb.minutes_veille(None), 10)

    def test_jamais_est_zero_pas_le_defaut(self):
        self.assertEqual(vb.minutes_veille({"profilActif": "a", "profils": [{"id": "a", "veille": 0}], "systeme": {"veille": 10}}), 0)

    def test_profil_inconnu_prend_le_premier_comme_la_page(self):
        self.assertEqual(vb.minutes_veille({"profilActif": "zz", "profils": [{"id": "a", "veille": 30}]}), 30)

    def test_valeurs_absurdes_ignorees(self):
        for mauvais in ("10", True, -1, 10 ** 9):
            self.assertEqual(vb.minutes_veille({"profils": [{"id": "a", "veille": mauvais}], "systeme": {}}), 10, mauvais)


class ReglagesGnome(unittest.TestCase):
    def test_ecran_noir_repousse_apres_l_ambiant(self):
        # Défaut GNOME 300 s, ambiant à 10 min : l'écran noir passerait avant.
        self.assertEqual(vb.idle_delay_voulu(300, 600), 600 + vb.AMBIANT_VISE_S)

    def test_rien_si_la_place_est_deja_faite_ou_jamais(self):
        self.assertIsNone(vb.idle_delay_voulu(600 + vb.AMBIANT_MIN_S, 600))
        self.assertIsNone(vb.idle_delay_voulu(0, 600), "« jamais » reste « jamais »")
        self.assertIsNone(vb.idle_delay_voulu(300, 0), "ambiant désactivé : GNOME inchangé")

    def test_lecture_de_gsettings(self):
        self.assertEqual(vb.valeur_gsettings("uint32 300\n"), 300)
        self.assertEqual(vb.valeur_gsettings("'suspend'\n"), "suspend")
        self.assertEqual(vb.valeur_gsettings("true"), "true")
        self.assertIsNone(vb.valeur_gsettings(""))

    def faux_gsettings(self, valeurs):
        ecrits = []

        def executer(argv):
            if argv[1] == "get":
                cle = (argv[2], argv[3])
                return (0, valeurs[cle]) if cle in valeurs else (1, "")
            ecrits.append(argv[2:])
            return 0, ""
        return executer, ecrits

    VALEURS = {
        ("org.gnome.desktop.session", "idle-delay"): "uint32 300",
        ("org.gnome.desktop.screensaver", "lock-enabled"): "true",
        ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-type"): "'suspend'",
        ("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-timeout"): "0",
    }

    def test_ecrit_seulement_idle_delay_jamais_le_verrouillage(self):
        executer, ecrits = self.faux_gsettings(self.VALEURS)
        rapport = vb.coordonner_gnome(600, executer)
        self.assertEqual(ecrits, [["org.gnome.desktop.session", "idle-delay", "1500"]])
        self.assertTrue(rapport["idle-delay-ecrit"])
        self.assertNotIn("alerte", rapport, "Ubuntu 26.04 : pas de mise en veille automatique sur secteur")

    def test_etat_n_ecrit_rien(self):
        executer, ecrits = self.faux_gsettings(self.VALEURS)
        self.assertEqual(vb.coordonner_gnome(600, executer, ecrire=False)["idle-delay-voulu"], 1500)
        self.assertEqual(ecrits, [])

    def test_mise_en_veille_avant_l_ecran_noir_signalee_pas_changee(self):
        valeurs = dict(self.VALEURS)
        valeurs[("org.gnome.settings-daemon.plugins.power", "sleep-inactive-ac-timeout")] = "900"
        executer, ecrits = self.faux_gsettings(valeurs)
        rapport = vb.coordonner_gnome(600, executer)
        self.assertIn("mise en veille automatique", rapport["alerte"])
        self.assertEqual([e[1] for e in ecrits], ["idle-delay"])

    def test_gsettings_absent_ne_casse_rien(self):
        rapport = vb.coordonner_gnome(600, lambda argv: (1, ""))
        self.assertIsNone(rapport["idle-delay"])
        self.assertNotIn("idle-delay-voulu", rapport)


# ── La surveillance ───────────────────────────────────────────────────────
class FauxBus:
    def __init__(self):
        self.appels, self.abonnements = [], {}
        self.reponses = {"AddIdleWatch": (7,), "AddUserActiveWatch": (8,), "GetActive": (False,),
                         "IsInhibited": (False,), "RemoveWatch": ()}

    def appeler(self, cible, methode, parametres=None):
        self.appels.append((cible[2], methode, parametres))
        reponse = self.reponses[methode]
        if isinstance(reponse, Exception):
            raise reponse
        return reponse

    def abonner(self, cible, signal, rappel):
        self.abonnements[(cible[2], signal)] = rappel

    def signal(self, interface, signal, *valeurs):
        self.abonnements[(interface, signal)](valeurs)

    def methodes(self):
        return [m for _, m, _ in self.appels]


class FauxProcessus:
    pid = 4242

    def __init__(self):
        self.termine = False

    def terminate(self):
        self.termine = True


class Surveillance(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.marqueur = Path(self._tmp.name) / "hub" / "ambiant-bureau"
        self.bus, self.lances, self.minuteries, self.journal = FauxBus(), [], [], []

    def tearDown(self):
        self._tmp.cleanup()

    def lancer(self, a_la_fin):
        p = FauxProcessus()
        self.lances.append((p, a_la_fin))
        return p

    def veille(self, delai_s=600):
        v = vb.Veille(self.bus, self.lancer, lambda s, f: self.minuteries.append((s, f)), delai_s,
                      self.marqueur, journal=self.journal.append)
        v.demarrer()
        return v

    def inactif(self):
        self.bus.signal("org.gnome.Mutter.IdleMonitor", "WatchFired", 7)

    def test_surveillance_mutter_en_millisecondes(self):
        self.veille(600)
        self.assertEqual(self.bus.appels[0], ("org.gnome.Mutter.IdleMonitor", "AddIdleWatch", ("(t)", (600_000,))))

    def test_jamais_ne_surveille_rien(self):
        self.veille(0)
        self.assertEqual(self.bus.appels, [])

    def test_inactif_lance_l_ambiant_et_marque_le_temps_d_ecran(self):
        self.veille()
        self.inactif()
        self.assertEqual(len(self.lances), 1)
        self.assertEqual(self.marqueur.read_text().strip(), "4242")
        self.assertIn(("org.gnome.SessionManager", "IsInhibited", ("(u)", (8,))), self.bus.appels)

    def test_video_en_cours_pas_d_ambiant(self):
        self.bus.reponses["IsInhibited"] = (True,)
        self.veille()
        self.inactif()
        self.assertEqual(self.lances, [])
        self.assertFalse(self.marqueur.exists())
        self.assertIn("inhibée", self.journal[-1])

    def test_ecran_deja_verrouille_pas_d_ambiant(self):
        self.bus.reponses["GetActive"] = (True,)
        self.veille()
        self.inactif()
        self.assertEqual(self.lances, [])

    def test_deja_lance_pas_de_second(self):
        self.veille()
        self.inactif()
        self.inactif()
        self.assertEqual(len(self.lances), 1)
        self.assertIn("déjà", self.journal[-1])

    def test_reveil_puis_nouvelle_inactivite_relance(self):
        self.veille()
        self.inactif()
        self.lances[0][1]()
        self.assertFalse(self.marqueur.exists())
        self.inactif()
        self.assertEqual(len(self.lances), 2)

    def test_une_autre_surveillance_ne_lance_rien(self):
        self.veille()
        self.bus.signal("org.gnome.Mutter.IdleMonitor", "WatchFired", 99)
        self.assertEqual(self.lances, [])

    def test_surveillance_d_activite_armee_apres_l_apparition(self):
        self.veille()
        self.inactif()
        self.assertNotIn("AddUserActiveWatch", self.bus.methodes(), "la fenêtre qui apparaît n'est pas un retour")
        secondes, armer = self.minuteries[-1]
        self.assertEqual(secondes, vb.ARMER_ACTIVITE_S)
        armer()
        self.assertIn("AddUserActiveWatch", self.bus.methodes())

    def test_retour_ambiant_ferme_seul_rien_a_faire(self):
        self.veille()
        self.inactif()
        processus, fin = self.lances[0]
        self.minuteries[-1][1]()
        self.bus.signal("org.gnome.Mutter.IdleMonitor", "WatchFired", 8)
        fin()
        self.minuteries[-1][1]()
        self.assertFalse(processus.termine)

    def test_retour_ambiant_reste_affiche_on_le_ferme(self):
        # Il n'avait pas le clavier : la touche est allée au bureau, l'horloge ne doit pas rester.
        self.veille()
        self.inactif()
        processus, _ = self.lances[0]
        self.minuteries[-1][1]()
        self.bus.signal("org.gnome.Mutter.IdleMonitor", "WatchFired", 8)
        secondes, verifier = self.minuteries[-1]
        self.assertEqual(secondes, vb.FERMER_SI_RESTE_S)
        verifier()
        self.assertTrue(processus.termine)

    def test_fin_de_l_ambiant_retire_la_surveillance_d_activite(self):
        self.veille()
        self.inactif()
        self.minuteries[-1][1]()
        self.lances[0][1]()
        self.assertEqual(self.bus.appels[-1], ("org.gnome.Mutter.IdleMonitor", "RemoveWatch", ("(u)", (8,))))

    def test_ecran_noir_de_gnome_ferme_l_ambiant(self):
        self.veille()
        self.inactif()
        self.bus.signal("org.gnome.ScreenSaver", "ActiveChanged", True)
        self.assertTrue(self.lances[0][0].termine)

    def test_gnome_shell_muet_on_lance_quand_meme(self):
        self.bus.reponses["GetActive"] = RuntimeError("pas de réponse")
        self.veille()
        self.inactif()
        self.assertEqual(len(self.lances), 1)

    def test_hub_menu_absent_journalise(self):
        def absent(_):
            raise FileNotFoundError("hub-menu")
        v = vb.Veille(self.bus, absent, lambda s, f: None, 600, self.marqueur, journal=self.journal.append)
        v.demarrer()
        self.inactif()
        self.assertIn("impossible", self.journal[-1])
        self.assertFalse(v.ambiant_vivant())


class UneSeuleSurveillance(unittest.TestCase):
    def test_second_verrou_refuse(self):
        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "hub" / "veille-bureau.verrou"
            premier = vb.verrouiller(chemin)
            self.assertIsNotNone(premier)
            self.assertIsNone(vb.verrouiller(chemin))
            premier.close()
            second = vb.verrouiller(chemin)
            self.assertIsNotNone(second)
            second.close()

    def test_arguments(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(vb.main(["--nimporte"]), 2)


# ── hub-menu --ambiant ────────────────────────────────────────────────────
class MenuAmbiant(unittest.TestCase):
    def test_arguments(self):
        self.assertEqual(hub_menu.analyser_arguments([]), {"ambiant": False})
        self.assertEqual(hub_menu.analyser_arguments(["--ambiant"]), {"ambiant": True})
        for mauvais in (["--ambiant", "tv"], ["tv"], ["--ambiant", "--ambiant"], ["-a"]):
            self.assertIsNone(hub_menu.analyser_arguments(mauvais), mauvais)

    def test_arguments_refuses_avant_gtk(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(hub_menu.lancer(["bureau"]), 2)

    def test_aucune_action_depuis_l_ambiant(self):
        for genre in ("choix", "relancer", "reglages", "minuteur", "maj-appliquer", "allumage-appliquer",
                      "pin-verifier", "pin-creer", "temps-prolonger", "appairage", "recopie-code", "inconnu"):
            self.assertFalse(hub_menu.message_permis(genre, ambiant=True), genre)
        for genre in ("meteo", "cadre", "ambiant-fin"):
            self.assertTrue(hub_menu.message_permis(genre, ambiant=True), genre)

    def test_le_menu_normal_ignore_la_fin_d_ambiant(self):
        self.assertFalse(hub_menu.message_permis("ambiant-fin", ambiant=False))
        self.assertTrue(hub_menu.message_permis("choix", ambiant=False))

    def test_tout_message_de_la_page_passe_par_le_filtre(self):
        source = (INSTALLER / "hub-menu.py").read_text()
        corps = source[source.index("def message_recu"):source.index("# La voix")]
        self.assertRegex(corps, r"if not message or not message_permis\(message\[\"type\"\], self\.ambiant\):\s+return")
        # L'ambiant ne rend jamais de choix au script de session.
        fin = source[source.index("menu.run(None)"):]
        self.assertLess(fin.index("if ambiant:"), fin.index("print(menu.choix)"))

    def test_reveil(self):
        for genre in ("touche", "clic", "molette", "toucher"):
            self.assertTrue(hub_menu.reveil_ambiant(genre, 0), genre)
        self.assertFalse(hub_menu.reveil_ambiant("mouvement", 0.2, 500), "le pointeur sous la fenêtre qui apparaît")
        self.assertFalse(hub_menu.reveil_ambiant("mouvement", 10, 3), "un frôlement")
        self.assertTrue(hub_menu.reveil_ambiant("mouvement", 10, 60))
        self.assertFalse(hub_menu.reveil_ambiant(None, 10))


# ── Temps d'écran ─────────────────────────────────────────────────────────
class TempsEcran(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def processus(self, pid, cmdline):
        (self.d / "proc" / str(pid)).mkdir(parents=True)
        (self.d / "proc" / str(pid) / "cmdline").write_bytes(cmdline)
        marqueur = self.d / "ambiant-bureau"
        marqueur.write_text(f"{pid}\n")
        return marqueur

    def test_ambiant_affiche(self):
        marqueur = self.processus(12, b"python3\0/usr/local/bin/hub-menu\0--ambiant\0")
        self.assertTrue(te.ambiant_bureau_affiche(marqueur, proc=self.d / "proc"))

    def test_marqueur_perime_ou_numero_repris(self):
        self.assertFalse(te.ambiant_bureau_affiche(self.d / "absent", proc=self.d / "proc"))
        marqueur = self.processus(13, b"firefox\0")
        self.assertFalse(te.ambiant_bureau_affiche(marqueur, proc=self.d / "proc"))
        marqueur.write_text("99\n")
        self.assertFalse(te.ambiant_bureau_affiche(marqueur, proc=self.d / "proc"))
        marqueur.write_text("abc")
        self.assertFalse(te.ambiant_bureau_affiche(marqueur, proc=self.d / "proc"))

    def test_le_bureau_ne_compte_pas_le_temps_en_ambiant(self):
        c = {"etat": self.d / "temps-ecran.json", "reglages": self.d / "reglages.json"}
        c["reglages"].write_text(json.dumps({"profilActif": "lea", "profils": [{"id": "lea"}]}))
        debut = datetime(2026, 9, 17, 15, 0).timestamp()
        temps = [debut]

        def horloge():
            return temps[0]

        class Bureau:
            pid, tours = None, 0

            def wait(self, timeout=None):
                Bureau.tours += 1
                temps[0] += timeout
                if Bureau.tours == 8:
                    return 0
                raise subprocess.TimeoutExpired("bureau", timeout)

        # Quatre pas de 15 s à l'écran, puis quatre en mode ambiant.
        te.suivre("bureau", c, demarrer=Bureau, horloge=horloge, pas=15,
                  avertir=lambda *a: None, terminer=lambda *a: None, en_pause=lambda: Bureau.tours > 4)
        jour = te.lire_etat(c["etat"])["profils"]["lea"]["2026-09-17"]
        self.assertEqual(jour["secondes"], 60)


# ── Installation ──────────────────────────────────────────────────────────
class Installation(unittest.TestCase):
    def test_autostart_du_bureau_seulement(self):
        texte = (INSTALLER / "veille" / "hub-veille-bureau.desktop").read_text()
        self.assertIn("\nOnlyShowIn=ubuntu;\n", texte)
        self.assertIn("\nExec=/usr/local/bin/hub-veille-bureau\n", texte)

    def test_aucun_autostart_avec_une_phase(self):
        # GNOME 50 n'a plus de lanceur d'autostart à lui : systemd-xdg-autostart-generator
        # marque NotShowIn=GNOME toute entrée qui porte une phase (xdg-autostart-service.c),
        # et la session « ubuntu » est ubuntu:GNOME. Vu en VM le 15/09/2026 (ARCHITECTURE.md).
        for fichier in INSTALLER.rglob("*.desktop"):
            self.assertNotIn("X-GNOME-Autostart-Phase", fichier.read_text(), fichier)

    def test_l_installateur_pose_la_veille_avec_le_menu(self):
        script = (INSTALLER / "hub-installer.sh").read_text()
        self.assertIn('poser "$DEPOT/veille/hub-veille-bureau" /usr/local/bin/hub-veille-bureau 0755', script)
        self.assertIn('poser "$DEPOT/veille/hub-veille-bureau.desktop" /etc/xdg/autostart/hub-veille-bureau.desktop 0644', script)
        session = script[script.index("etape_session() {"):script.index("etape_accueil() {")]
        self.assertIn("poser_veille_bureau || return 1", session)
        self.assertEqual(subprocess.run(["bash", "-n", str(INSTALLER / "hub-installer.sh")]).returncode, 0)

    def test_la_page_charge_l_extension(self):
        self.assertTrue(re.search(r'<script src="veille-bureau.js"></script>', (INSTALLER / "menu" / "index.html").read_text()))


if __name__ == "__main__":
    unittest.main()
