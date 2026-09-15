"""Temps d'écran : comptage par profil et par jour, limites, plages, prolongations.

    python3 -m unittest tests/test_hub_temps_ecran.py
"""

import importlib.machinery
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


class Commande(unittest.TestCase):
    def test_arguments(self):
        self.assertEqual(te.analyser(["lancer", "tv", "--", "kodi", "--windowing=wayland"]),
                         ("lancer", "tv", ["kodi", "--windowing=wayland"]))
        self.assertEqual(te.analyser(["bureau"]), ("bureau", "bureau", None))
        self.assertIsNone(te.analyser(["lancer", "tv"]))
        self.assertIsNone(te.analyser(["n-importe"]))


if __name__ == "__main__":
    unittest.main()
