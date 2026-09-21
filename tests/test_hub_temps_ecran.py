"""Temps d'écran : comptage par profil et par jour, limites, plages, prolongations.

    python3 -m unittest tests/test_hub_temps_ecran.py
"""

import contextlib
import importlib.machinery
import io
import importlib.util
import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
chargeur = importlib.machinery.SourceFileLoader("hub_temps_ecran", str(RACINE / "installer" / "hub-temps-ecran"))
spec = importlib.util.spec_from_loader("hub_temps_ecran", chargeur)
te = importlib.util.module_from_spec(spec)
chargeur.exec_module(te)


def ts(texte):
    """« 2026-09-15 20:00 » en heure locale → horodatage."""
    return datetime.strptime(texte, "%Y-%m-%d %H:%M").timestamp()


# Le 15 septembre 2026 est un mardi ; le 19 un samedi.
MARDI, SAMEDI = "2026-09-15", "2026-09-19"
REGLES = {"limites": [120, 120, 120, 120, 120, 180, 180], "debut": "07:00", "fin": "21:00"}


class Regles(unittest.TestCase):
    def test_limite_selon_le_jour_de_la_semaine(self):
        self.assertEqual(te.limite_du_jour(REGLES, datetime.fromtimestamp(ts(f"{MARDI} 10:00"))), 120)
        self.assertEqual(te.limite_du_jour(REGLES, datetime.fromtimestamp(ts(f"{SAMEDI} 10:00"))), 180)
        self.assertIsNone(te.limite_du_jour({"limites": [None] * 7}, datetime.now()))
        self.assertIsNone(te.limite_du_jour({}, datetime.now()))

    def test_regles_absentes_ou_abimees_ne_limitent_rien(self):
        for regles in (None, {}, {"limites": "x"}, {"limites": [None] * 7, "debut": None, "fin": None}):
            self.assertIsNone(te.restant(regles, {}, ts(f"{MARDI} 23:30")), regles)

    def test_heure_invalide_ignoree(self):
        self.assertIsNone(te.minutes_du_jour("25:00"))
        self.assertIsNone(te.minutes_du_jour("abc"))
        self.assertEqual(te.minutes_du_jour("21:30"), 21 * 60 + 30)

    def test_regles_du_profil_lues_dans_les_reglages(self):
        reglages = {"profilActif": "camille", "profils": [{"id": "sam"}, {"id": "camille", "tempsEcran": REGLES}]}
        self.assertEqual(te.regles_du_profil(reglages, "camille"), REGLES)
        self.assertIsNone(te.regles_du_profil(reglages, "sam"))
        self.assertIsNone(te.regles_du_profil(None, "camille"))


class Restant(unittest.TestCase):
    def test_quota_moins_le_temps_passe(self):
        jour = {"secondes": 3600}
        self.assertEqual(te.restant({"limites": [120] * 7}, jour, ts(f"{MARDI} 10:00")), 3600)

    def test_jamais_negatif(self):
        self.assertEqual(te.restant({"limites": [60] * 7}, {"secondes": 9000}, ts(f"{MARDI} 10:00")), 0)

    def test_la_plage_horaire_coupe_avant_le_quota(self):
        # 20 h 30, quota presque intact : c'est 21 h qui décide.
        self.assertEqual(te.restant(REGLES, {"secondes": 0}, ts(f"{MARDI} 20:30")), 30 * 60)

    def test_hors_plage_rien(self):
        self.assertEqual(te.restant(REGLES, {}, ts(f"{MARDI} 21:00")), 0)
        self.assertEqual(te.restant(REGLES, {}, ts(f"{MARDI} 06:59")), 0)

    def test_plage_sans_quota(self):
        regles = {"limites": [None] * 7, "fin": "21:00"}
        self.assertEqual(te.restant(regles, {}, ts(f"{MARDI} 20:00")), 3600)

    def test_la_prolongation_ajoute_au_quota(self):
        jour = {"secondes": 7200, "bonus": 900}
        self.assertEqual(te.restant({"limites": [120] * 7}, jour, ts(f"{MARDI} 10:00")), 900)

    def test_la_prolongation_ouvre_aussi_la_plage(self):
        # Un parent accorde 30 min à 21 h 10 : l'enfant a bien 30 min, plage ou pas.
        etat = {}
        te.prolonger(etat, "camille", 30, ts(f"{MARDI} 21:10"))
        jour = etat["profils"]["camille"][MARDI]
        self.assertEqual(te.restant(REGLES, jour, ts(f"{MARDI} 21:10")), 30 * 60)
        self.assertEqual(te.restant(REGLES, jour, ts(f"{MARDI} 21:40")), 0)

    def test_prolongations_successives_se_cumulent(self):
        etat = {}
        te.prolonger(etat, "camille", 15, ts(f"{MARDI} 21:00"))
        te.prolonger(etat, "camille", 15, ts(f"{MARDI} 21:05"))
        jour = etat["profils"]["camille"][MARDI]
        self.assertEqual(jour["bonus"], 1800)
        self.assertEqual(te.restant(REGLES, jour, ts(f"{MARDI} 21:05")), 25 * 60)


class Comptage(unittest.TestCase):
    def test_ajoute_par_profil_jour_et_mode(self):
        etat = {}
        te.ajouter(etat, "camille", "tv", 600, ts(f"{MARDI} 10:00"))
        te.ajouter(etat, "camille", "tv", 60, ts(f"{MARDI} 11:00"))
        te.ajouter(etat, "camille", "bureau", 30, ts(f"{MARDI} 12:00"))
        te.ajouter(etat, "sam", "tv", 5, ts(f"{MARDI} 12:00"))
        jour = etat["profils"]["camille"][MARDI]
        self.assertEqual(jour["secondes"], 690)
        self.assertEqual(jour["modes"], {"tv": 660, "bureau": 30})
        self.assertEqual(etat["profils"]["sam"][MARDI]["secondes"], 5)

    def test_historique_sept_jours_du_plus_ancien_au_plus_recent(self):
        etat = {}
        te.ajouter(etat, "camille", "tv", 100, ts("2026-09-10 10:00"))
        te.ajouter(etat, "camille", "tv", 200, ts(f"{MARDI} 10:00"))
        te.ajouter(etat, "camille", "tv", 999, ts("2026-09-01 10:00"))
        h = te.historique(etat, "camille", ts(f"{MARDI} 12:00"))
        self.assertEqual([j["jour"] for j in h], [f"2026-09-{d:02d}" for d in range(9, 16)])
        self.assertEqual([j["secondes"] for j in h], [0, 100, 0, 0, 0, 0, 200])

    def test_menage_des_vieux_jours(self):
        etat = {}
        te.ajouter(etat, "camille", "tv", 100, ts("2026-07-01 10:00"))
        te.ajouter(etat, "camille", "tv", 100, ts(f"{MARDI} 10:00"))
        te.menage(etat, ts(f"{MARDI} 12:00"))
        self.assertEqual(list(etat["profils"]["camille"]), [MARDI])


class Fichier(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.chemin = Path(self._tmp.name) / "state/hub/temps-ecran.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_fichier_absent_ou_abime(self):
        self.assertEqual(te.lire_etat(self.chemin), {"version": 1, "profils": {}})
        self.chemin.parent.mkdir(parents=True)
        self.chemin.write_text("{ tronqué")
        self.assertEqual(te.lire_etat(self.chemin), {"version": 1, "profils": {}})

    def test_modifier_ecrit_atomiquement(self):
        te.modifier_etat(self.chemin, lambda e: te.ajouter(e, "camille", "tv", 42, ts(f"{MARDI} 10:00")))
        self.assertEqual(json.loads(self.chemin.read_text())["profils"]["camille"][MARDI]["secondes"], 42)
        restes = sorted(p.name for p in self.chemin.parent.iterdir())
        self.assertEqual(restes, ["temps-ecran.json", "temps-ecran.json.verrou"])

    def test_ecritures_concurrentes_ne_perdent_rien(self):
        # Le menu (prolongation) et le suivi d'un mode peuvent écrire en même temps.
        def boucle():
            for _ in range(25):
                te.modifier_etat(self.chemin, lambda e: te.ajouter(e, "camille", "tv", 1, ts(f"{MARDI} 10:00")))
        fils = [threading.Thread(target=boucle) for _ in range(4)]
        [f.start() for f in fils]
        [f.join() for f in fils]
        self.assertEqual(te.lire_etat(self.chemin)["profils"]["camille"][MARDI]["secondes"], 100)


class FauxProcessus:
    def __init__(self, duree_s, horloge):
        self.fin = horloge.t + duree_s
        self.horloge = horloge
        self.pid = 4242
        self.termine = False

    def wait(self, timeout=None):
        if self.termine or self.horloge.t + (timeout or 0) >= self.fin:
            self.horloge.t = max(self.horloge.t, min(self.fin, self.horloge.t + (timeout or 0)))
            return 0
        self.horloge.t += timeout
        raise te.subprocess.TimeoutExpired("faux", timeout)


class Horloge:
    def __init__(self, texte):
        self.t = ts(texte)

    def __call__(self):
        return self.t


class Suivi(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.c = {"etat": d / "temps-ecran.json", "reglages": d / "reglages.json"}
        self.avertissements = []
        self.termines = []

    def tearDown(self):
        self._tmp.cleanup()

    def reglages(self, regles):
        self.c["reglages"].write_text(json.dumps({"profilActif": "camille", "profils": [{"id": "camille", "langue": "fr", "tempsEcran": regles}]}))

    def suivre(self, horloge, processus, mode="tv"):
        return te.suivre(
            mode, self.c, horloge=horloge, pas=15,
            demarrer=lambda: processus,
            avertir=lambda nature, minutes, mode, langue: self.avertissements.append((nature, minutes)),
            terminer=lambda p, mode: (self.termines.append(mode), setattr(p, "termine", True)),
        )

    def test_compte_la_duree_du_mode(self):
        self.reglages(None)
        h = Horloge(f"{MARDI} 10:00")
        self.suivre(h, FauxProcessus(600, h))
        self.assertEqual(te.lire_etat(self.c["etat"])["profils"]["camille"][MARDI]["secondes"], 600)
        self.assertEqual(self.avertissements, [])

    def test_avertit_cinq_minutes_avant_puis_ramene_au_menu(self):
        self.reglages({"limites": [10] * 7})
        h = Horloge(f"{MARDI} 10:00")
        self.suivre(h, FauxProcessus(3600, h))
        self.assertEqual([n for n, _ in self.avertissements], ["bientot", "fin"])
        self.assertEqual(self.avertissements[0][1], 5)
        self.assertEqual(self.termines, ["tv"])
        passe = te.lire_etat(self.c["etat"])["profils"]["camille"][MARDI]["secondes"]
        self.assertTrue(600 <= passe <= 615, passe)

    def test_refuse_de_lancer_quand_le_temps_est_ecoule(self):
        self.reglages({"limites": [None] * 7, "fin": "21:00"})
        h = Horloge(f"{MARDI} 21:30")
        lances = []
        code = te.suivre("tv", self.c, horloge=h, pas=15, demarrer=lambda: lances.append(1),
                         avertir=lambda *a: self.avertissements.append(a[0]), terminer=lambda *a: None)
        self.assertEqual(code, te.CODE_TEMPS_ECOULE)
        self.assertEqual(lances, [])
        self.assertEqual(self.avertissements, ["fin"])

    def test_un_saut_d_horloge_ne_compte_pas_des_heures(self):
        # Mise en veille, changement d'heure : on plafonne chaque pas.
        self.reglages(None)
        h = Horloge(f"{MARDI} 10:00")
        p = FauxProcessus(30, h)
        vrai_wait = p.wait

        def wait(timeout=None):
            h.t += 5 * 3600
            return vrai_wait(timeout)
        p.wait = wait
        self.suivre(h, p)
        self.assertLessEqual(te.lire_etat(self.c["etat"])["profils"]["camille"][MARDI]["secondes"], 60)


class ReglagesIllisibles(unittest.TestCase):
    """Abîmer reglages.json ne doit plus lever les limites de l'enfant, ni en imposer au parent."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.c = {"etat": d / "temps-ecran.json", "reglages": d / "reglages.json"}
        self.avertissements = []
        # Les messages attendus sur la sortie d'erreur n'encombrent pas le rapport des tests.
        self._stderr = contextlib.redirect_stderr(io.StringIO())
        self._stderr.__enter__()

    def tearDown(self):
        self._stderr.__exit__(None, None, None)
        self._tmp.cleanup()

    def ecrire(self, actif, texte=None):
        self.c["reglages"].write_text(texte if texte is not None else json.dumps({"profilActif": actif, "profils": [
            {"id": "sam", "langue": "en"},
            {"id": "lea", "tempsEcran": {"limites": [None] * 7, "fin": "21:00"}}]}))

    def lancer_a(self, heure):
        lances = []
        code = te.suivre("tv", self.c, horloge=Horloge(f"{MARDI} {heure}"), pas=15, demarrer=lambda: lances.append(1) or FauxProcessus(0, Horloge(f"{MARDI} {heure}")),
                         avertir=lambda *a: self.avertissements.append(a[0]), terminer=lambda *a: None)
        return code, lances

    def test_enfant_garde_ses_limites_si_le_fichier_s_abime(self):
        self.ecrire("lea")
        self.assertEqual(te.profil_et_regles(self.c)[0], "lea")
        for abime in ("{ tronqué", "[]", '{"profils": "x"}', ""):
            self.ecrire(None, abime)
            code, lances = self.lancer_a("21:30")
            self.assertEqual((code, lances), (te.CODE_TEMPS_ECOULE, []), abime)

    def test_enfant_garde_ses_limites_si_le_fichier_disparait(self):
        self.ecrire("lea")
        te.profil_et_regles(self.c)
        self.c["reglages"].unlink()
        self.assertEqual(self.lancer_a("21:30")[0], te.CODE_TEMPS_ECOULE)

    def test_fichier_illisible_par_ses_droits(self):
        import os
        if os.geteuid() == 0:
            self.skipTest("root lit tout")
        self.ecrire("lea")
        te.profil_et_regles(self.c)
        self.c["reglages"].chmod(0)
        self.assertEqual(self.lancer_a("21:30")[0], te.CODE_TEMPS_ECOULE)

    def test_parent_sans_limite_n_est_pas_enferme(self):
        self.ecrire("sam")
        te.profil_et_regles(self.c)
        self.ecrire(None, "{ tronqué")
        self.assertEqual(te.profil_et_regles(self.c), ("sam", None, "en"))
        code, lances = self.lancer_a("21:30")
        self.assertEqual((code, lances), (0, [1]))

    def test_sans_regle_connue_le_hub_ne_bloque_pas(self):
        # Compromis documenté : rien de connu à appliquer, on ne l'invente pas.
        self.ecrire(None, "{ tronqué")
        self.assertEqual(te.profil_et_regles(self.c), ("inconnu", None, "fr"))
        self.assertEqual(self.lancer_a("21:30")[1], [1])

    def test_la_copie_suit_les_changements_et_reste_privee(self):
        self.ecrire("lea")
        te.profil_et_regles(self.c)
        self.ecrire("sam")
        te.profil_et_regles(self.c)
        secours = te.chemin_secours(self.c)
        self.assertEqual(json.loads(secours.read_text())["profilActif"], "sam")
        self.assertEqual(secours.stat().st_mode & 0o777, 0o600)


class Avertir(unittest.TestCase):
    def test_chaque_mode_son_moyen(self):
        appels = []
        kodi = lambda methode, params=None: appels.append(("kodi", methode, params["title"]))
        lancer = lambda commande, **_: appels.append(("lance", commande[0] if commande[0] == "notify-send" else commande[-3]))
        self.assertEqual(te.avertir("bientot", 5, "tv", "fr", executer=lancer, kodi=kodi), "kodi")
        self.assertEqual(appels[-1], ("kodi", "GUI.ShowNotification", "Plus que 5 min d'écran aujourd'hui"))
        self.assertEqual(te.avertir("fin", 0, "bureau", "en", executer=lancer, kodi=kodi), "notify-send")
        self.assertEqual(te.avertir("fin", 0, "web", "fr", executer=lancer, kodi=kodi), "fenetre")
        self.assertEqual(appels[-1], ("lance", "fenetre"))

    def test_kodi_injoignable_repli_sur_la_fenetre(self):
        def kodi(*_):
            raise ConnectionRefusedError()
        lances = []
        self.assertEqual(te.avertir("bientot", 3, "tv", "fr", executer=lambda c, **_: lances.append(c), kodi=kodi), "fenetre")
        self.assertIn("Plus que 3 min d'écran aujourd'hui", lances[0])


class TempsDeVeille(unittest.TestCase):
    """Bug rapporté 22/09/2026 : le temps du mode TV continuait à s'accumuler
    pendant la veille (l'écran de veille de Kodi, faute de mieux — voir le
    commentaire de kodi_en_veille)."""

    def test_kodi_en_veille_lit_le_screensaver(self):
        reponse = lambda *_: json.dumps({"result": {"System.ScreenSaverActive": True}})
        self.assertTrue(te.kodi_en_veille(kodi=reponse))
        reponse = lambda *_: json.dumps({"result": {"System.ScreenSaverActive": False}})
        self.assertFalse(te.kodi_en_veille(kodi=reponse))

    def test_kodi_en_veille_repli_si_injoignable(self):
        def kodi(*_):
            raise ConnectionRefusedError()
        self.assertFalse(te.kodi_en_veille(kodi=kodi))

    def test_kodi_en_veille_repli_si_reponse_abimee(self):
        self.assertFalse(te.kodi_en_veille(kodi=lambda *_: b"pas du json"))
        self.assertFalse(te.kodi_en_veille(kodi=lambda *_: json.dumps({"result": {}})))

    def test_suivre_ne_compte_pas_pendant_la_veille(self):
        # Même scène que test_compte_la_duree_du_mode (Compter.suivre), mais avec
        # en_pause actif tout du long : rien ne doit s'ajouter à l'état.
        d = Path(tempfile.mkdtemp())
        c = {"etat": d / "temps-ecran.json", "reglages": d / "reglages.json"}
        c["reglages"].write_text(json.dumps({"profilActif": "camille",
                                              "profils": [{"id": "camille", "langue": "fr"}]}))
        h = Horloge(f"{MARDI} 10:00")
        p = FauxProcessus(600, h)
        te.suivre("tv", c, horloge=h, pas=15, demarrer=lambda: p,
                  avertir=lambda *a: None, terminer=lambda *a: None, en_pause=lambda: True)
        self.assertEqual(te.lire_etat(c["etat"])["profils"]["camille"][MARDI]["secondes"], 0)

    def test_suivre_reprend_le_compte_des_le_reveil(self):
        # en_pause change d'avis en cours de route (le spectateur revient) : seul le
        # temps pendant lequel il répondait True doit manquer à l'appel.
        d = Path(tempfile.mkdtemp())
        c = {"etat": d / "temps-ecran.json", "reglages": d / "reglages.json"}
        c["reglages"].write_text(json.dumps({"profilActif": "camille",
                                              "profils": [{"id": "camille", "langue": "fr"}]}))
        h = Horloge(f"{MARDI} 10:00")
        p = FauxProcessus(30, h)
        en_veille = {"valeur": True}
        te.suivre("tv", c, horloge=h, pas=15, demarrer=lambda: p,
                  avertir=lambda *a: None, terminer=lambda *a: None, en_pause=lambda: en_veille["valeur"])
        self.assertEqual(te.lire_etat(c["etat"])["profils"]["camille"][MARDI]["secondes"], 0)
        en_veille["valeur"] = False
        d2 = Path(tempfile.mkdtemp())
        c2 = {"etat": d2 / "temps-ecran.json", "reglages": c["reglages"]}
        h2 = Horloge(f"{MARDI} 10:00")
        p2 = FauxProcessus(30, h2)
        te.suivre("tv", c2, horloge=h2, pas=15, demarrer=lambda: p2,
                  avertir=lambda *a: None, terminer=lambda *a: None, en_pause=lambda: en_veille["valeur"])
        self.assertEqual(te.lire_etat(c2["etat"])["profils"]["camille"][MARDI]["secondes"], 30)


class Commande(unittest.TestCase):
    def test_arguments(self):
        self.assertEqual(te.analyser(["lancer", "tv", "--", "kodi", "--windowing=wayland"]),
                         ("lancer", "tv", ["kodi", "--windowing=wayland"]))
        self.assertEqual(te.analyser(["bureau"]), ("bureau", "bureau", None))
        self.assertIsNone(te.analyser(["lancer", "tv"]))
        self.assertIsNone(te.analyser(["n-importe"]))


if __name__ == "__main__":
    unittest.main()
