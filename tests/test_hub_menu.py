"""Ce que hub-menu fait sans écran : réglages, météo en cache, minuteur, voix.

    python3 -m unittest discover -s tests
"""

import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

RACINE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("hub_menu", RACINE / "installer" / "hub-menu.py")
hub_menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub_menu)

METEO = {"current": {"temperature_2m": 21}, "daily": {}, "hourly": {}}


class AvecDossier(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.c = {
            "reglages": d / "config/hub/reglages.json",
            "dernier": d / "state/hub/dernier-choix",
            "meteo": d / "cache/hub/meteo.json",
            "execution": d / "run/hub",
            "socket": d / "run/hub/menu.sock",
            "deja-ouvert": d / "run/hub/menu-deja-ouvert",
            "minuteur": d / "run/hub/minuteur-fin",
            "telecommande": d / "run/hub/telecommande.json",
        }

    def tearDown(self):
        self._tmp.cleanup()


class Reglages(AvecDossier):
    def test_enregistre_puis_relit(self):
        donnees = {"profilActif": "a", "profils": [{"id": "a", "nom": "Samuel"}], "systeme": {}}
        self.assertTrue(hub_menu.enregistrer_reglages(self.c, donnees))
        self.assertEqual(hub_menu.charger_reglages(self.c), donnees)

    def test_refuse_ce_qui_n_est_pas_des_reglages(self):
        for mauvais in (None, [], {"profils": []}, {"profils": [{"nom": "sans id"}]}, {"profils": "x"}):
            self.assertFalse(hub_menu.enregistrer_reglages(self.c, mauvais), mauvais)
        self.assertFalse(self.c["reglages"].exists())

    def test_un_fichier_abime_ne_casse_pas_le_demarrage(self):
        self.c["reglages"].parent.mkdir(parents=True)
        self.c["reglages"].write_text("{ tronqué")
        self.assertIsNone(hub_menu.charger_reglages(self.c))

    def test_ecriture_atomique_ne_laisse_pas_de_provisoire(self):
        hub_menu.enregistrer_reglages(self.c, {"profils": [{"id": "a"}]})
        self.assertEqual([p.name for p in self.c["reglages"].parent.iterdir()], ["reglages.json"])

    def test_dernier_choix_ignore_eteindre(self):
        hub_menu.retenir(self.c, "bureau")
        hub_menu.retenir(self.c, "eteindre")
        self.assertEqual(hub_menu.dernier_choix(self.c), "bureau")


class Meteo(AvecDossier):
    def test_releve_frais_puis_cache_sans_nouvelle_requete(self):
        appels = []
        telecharger = lambda url: appels.append(url) or METEO
        r1 = hub_menu.meteo(self.c, 48.5, -4.07, maintenant=1000, telecharger=telecharger)
        r2 = hub_menu.meteo(self.c, 48.5, -4.07, maintenant=1000 + 60, telecharger=telecharger)
        self.assertEqual(len(appels), 1)
        self.assertFalse(r1["horsLigne"])
        self.assertEqual(r2["donnees"], METEO)
        self.assertIn("latitude=48.5", appels[0])

    def test_sans_reseau_rend_le_cache_marque_hors_ligne(self):
        hub_menu.meteo(self.c, 48.5, -4.07, maintenant=1000, telecharger=lambda url: METEO)

        def coupe(url):
            raise OSError("réseau absent")
        r = hub_menu.meteo(self.c, 48.5, -4.07, maintenant=1000 + 3600, telecharger=coupe)
        self.assertTrue(r["horsLigne"])
        self.assertEqual(r["releve"], 1000)

    def test_autre_ville_ne_reutilise_pas_le_cache(self):
        hub_menu.meteo(self.c, 48.5, -4.07, maintenant=1000, telecharger=lambda url: METEO)

        def coupe(url):
            raise OSError
        self.assertIsNone(hub_menu.meteo(self.c, 43.3, 5.4, maintenant=1010, telecharger=coupe))

    def test_reponse_inattendue_n_ecrase_pas_le_cache(self):
        hub_menu.meteo(self.c, 48.5, -4.07, maintenant=1000, telecharger=lambda url: METEO)
        r = hub_menu.meteo(self.c, 48.5, -4.07, maintenant=5000, telecharger=lambda url: {"error": True})
        self.assertTrue(r["horsLigne"])
        self.assertEqual(json.loads(self.c["meteo"].read_text())["donnees"], METEO)

    def test_geocodage_ne_garde_que_l_utile(self):
        brut = {"results": [{"id": 1, "name": "Brest", "latitude": 48.39, "longitude": -4.49, "admin1": "Bretagne", "country_code": "FR", "population": 139000}, {"name": "sans coordonnées"}]}
        self.assertEqual(hub_menu.geocodage("Brest", "fr", telecharger=lambda url: brut),
                         [{"id": 1, "name": "Brest", "latitude": 48.39, "longitude": -4.49, "admin1": "Bretagne", "country_code": "FR"}])

    def test_geocodage_sans_reseau_rend_une_liste_vide(self):
        def coupe(url):
            raise OSError
        self.assertEqual(hub_menu.geocodage("Brest", "fr", telecharger=coupe), [])


class Minuteur(AvecDossier):
    def test_programme_un_minuteur_systemd_utilisateur(self):
        commandes = []
        executer = lambda cmd, **_: commandes.append(cmd) or SimpleNamespace(returncode=0)
        fin = hub_menu.programmer_minuteur(self.c, 30, executer=executer, maintenant=1000)
        self.assertEqual(fin, (1000 + 1800) * 1000)
        self.assertEqual(commandes[0], ["systemctl", "--user", "stop", "hub-minuteur.timer"])
        self.assertIn("--on-active=30m", commandes[1])
        self.assertEqual(commandes[1][:2], ["systemd-run", "--user"])
        self.assertEqual(hub_menu.minuteur_en_cours(self.c, maintenant=1000), fin)

    def test_zero_annule(self):
        executer = lambda cmd, **_: SimpleNamespace(returncode=0)
        hub_menu.programmer_minuteur(self.c, 30, executer=executer, maintenant=1000)
        self.assertIsNone(hub_menu.programmer_minuteur(self.c, 0, executer=executer))
        self.assertIsNone(hub_menu.minuteur_en_cours(self.c))

    def test_echec_de_systemd_ne_pretend_rien(self):
        executer = lambda cmd, **_: SimpleNamespace(returncode=1)
        self.assertIsNone(hub_menu.programmer_minuteur(self.c, 30, executer=executer))
        self.assertIsNone(hub_menu.minuteur_en_cours(self.c))

    def test_minuteur_echu_n_est_plus_affiche(self):
        executer = lambda cmd, **_: SimpleNamespace(returncode=0)
        hub_menu.programmer_minuteur(self.c, 1, executer=executer, maintenant=1000)
        self.assertIsNone(hub_menu.minuteur_en_cours(self.c, maintenant=1000 + 120))


class Telecommande(AvecDossier):
    def test_absent_ou_incomplet_rend_none(self):
        self.assertIsNone(hub_menu.etat_telecommande(self.c))
        hub_menu.ecrire_atomique(self.c["telecommande"], json.dumps({"code": "123456"}))
        self.assertIsNone(hub_menu.etat_telecommande(self.c))

    def test_ne_garde_que_les_champs_connus(self):
        hub_menu.ecrire_atomique(self.c["telecommande"], json.dumps(
            {"url": "http://192.168.1.40:8790/", "code": "123456", "expire": 5, "telephones": 1, "appairageLe": None, "secret": "x"}))
        self.assertEqual(hub_menu.etat_telecommande(self.c),
                         {"url": "http://192.168.1.40:8790/", "code": "123456", "expire": 5, "telephones": 1, "appairageLe": None})

    def test_texte_envoye_du_telephone(self):
        self.assertEqual(hub_menu.message_voix("texte:Brest".encode()), {"type": "texte", "texte": "Brest"})


class MiseAJour(unittest.TestCase):
    def test_verifier_rend_la_reponse_de_l_outil(self):
        faux = lambda *a, **k: SimpleNamespace(stdout='{"disponible": true, "distant": "abc", "installee": "def"}', returncode=0)
        self.assertEqual(hub_menu.verifier_mise_a_jour(faux)["disponible"], True)

    def test_outil_absent_ou_reponse_illisible(self):
        def absent(*a, **k):
            raise FileNotFoundError("hub-mise-a-jour")
        self.assertEqual(hub_menu.verifier_mise_a_jour(absent)["erreur"], "indisponible")
        illisible = lambda *a, **k: SimpleNamespace(stdout="pas du json", returncode=1)
        self.assertEqual(hub_menu.verifier_mise_a_jour(illisible)["erreur"], "indisponible")

    def test_lancement_par_systemd(self):
        commandes = []
        ok = hub_menu.lancer_mise_a_jour(lambda cmd, **k: commandes.append(cmd) or SimpleNamespace(returncode=0))
        self.assertTrue(ok)
        self.assertEqual(commandes, [["systemctl", "start", "--no-block", "hub-mise-a-jour.service"]])

    def test_etat(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "etat.json"
            self.assertIsNone(hub_menu.etat_mise_a_jour(f))
            f.write_text('{"etape": "tests", "version": "abc"}')
            self.assertEqual(hub_menu.etat_mise_a_jour(f)["etape"], "tests")


class ReprisesKodi(unittest.TestCase):
    """Base de test aux colonnes de Kodi 21 (movie_view, episode_view, art, texture)."""

    def setUp(self):
        import sqlite3
        self._tmp = tempfile.TemporaryDirectory()
        self.kodi = Path(self._tmp.name) / ".kodi"
        bases = self.kodi / "userdata" / "Database"
        bases.mkdir(parents=True)
        (bases / "MyVideos116.db").write_bytes(b"")
        with sqlite3.connect(bases / "MyVideos131.db") as bd:
            bd.executescript("""
                CREATE TABLE movie_view (idMovie, c00, strPath, strFileName, resumeTimeInSeconds, totalTimeInSeconds, lastPlayed);
                CREATE TABLE episode_view (idEpisode, c00, strTitle, c12, c13, strPath, strFileName, resumeTimeInSeconds, totalTimeInSeconds, lastPlayed);
                CREATE TABLE art (media_id, media_type, type, url);
                INSERT INTO movie_view VALUES (1, 'Dune', '/media/films/', 'dune.mkv', 3600, 9000, '2026-09-10 21:00:00');
                INSERT INTO movie_view VALUES (2, 'Vu en entier', '/media/films/', 'fini.mkv', 0, 6000, '2026-09-12 21:00:00');
                INSERT INTO episode_view VALUES (7, 'Le retour', 'Chernobyl', '1', '3', 'smb://nas/series/', 'smb://nas/series/c-s01e03.mkv', 600, 3600, '2026-09-12 22:00:00');
                INSERT INTO art VALUES (1, 'movie', 'poster', 'image://dune.jpg/');
            """)
        with sqlite3.connect(bases / "Textures13.db") as bd:
            bd.executescript("CREATE TABLE texture (url, cachedurl); INSERT INTO texture VALUES ('image://dune.jpg/', 'a/abcd.jpg');")
        miniature = self.kodi / "userdata" / "Thumbnails" / "a" / "abcd.jpg"
        miniature.parent.mkdir(parents=True)
        miniature.write_bytes(b"jpg")
        self.miniature = miniature

    def tearDown(self):
        self._tmp.cleanup()

    def test_films_et_episodes_commences_du_plus_recent(self):
        r = hub_menu.reprises_kodi(self.kodi)
        self.assertEqual([e["titre"] for e in r], ["Chernobyl", "Dune"])
        self.assertEqual(r[0]["sousTitre"], "S01 E03 · Le retour")
        self.assertEqual(r[0]["fichier"], "smb://nas/series/c-s01e03.mkv")
        self.assertEqual(r[1]["fichier"], "/media/films/dune.mkv")
        self.assertEqual((r[1]["position"], r[1]["duree"]), (3600.0, 9000.0))

    def test_affiche_depuis_le_cache_de_miniatures(self):
        r = hub_menu.reprises_kodi(self.kodi)
        self.assertEqual(r[1]["image"], self.miniature.as_uri())
        self.assertIsNone(r[0]["image"])

    def test_sans_kodi_ou_schema_inconnu_liste_vide(self):
        self.assertEqual(hub_menu.reprises_kodi(Path(self._tmp.name) / "absent"), [])
        import sqlite3
        with sqlite3.connect(self.kodi / "userdata/Database/MyVideos140.db") as bd:
            bd.execute("CREATE TABLE autre (x)")
        self.assertEqual(hub_menu.reprises_kodi(self.kodi), [])


class Images(unittest.TestCase):
    def test_avatars_les_plus_recents_d_abord_et_seulement_des_images(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for i, nom in enumerate(["ancienne.jpg", "recente.png", "notes.txt", "photo.WEBP"]):
                (d / nom).write_bytes(b"x")
                os.utime(d / nom, (1000 + i, 1000 + i))
            os.utime(d / "recente.png", (5000, 5000))
            noms = [Path(u).name for u in hub_menu.avatars([d])]
        self.assertEqual(noms, ["recente.png", "photo.WEBP", "ancienne.jpg"])

    def test_datagramme_avatars(self):
        self.assertEqual(hub_menu.message_voix(b"avatars"), {"type": "avatars"})


class Messages(unittest.TestCase):
    def test_commandes_vocales(self):
        self.assertEqual(hub_menu.message_voix(b"tv"), {"type": "commande", "nom": "tv"})
        self.assertEqual(hub_menu.message_voix(b"theme:sombre"), {"type": "commande", "nom": "theme:sombre"})
        self.assertEqual(hub_menu.message_voix(b"voix:eveil"), {"type": "voix", "etat": "eveil"})
        self.assertEqual(hub_menu.message_voix("voix:entendu:lance la télé".encode()), {"type": "voix", "etat": "entendu", "texte": "lance la télé"})

    def test_datagrammes_inconnus_ignores(self):
        for brut in (b"rm -rf", b"voix:nimporte", b"\xff\xfe", b""):
            self.assertIsNone(hub_menu.message_voix(brut), brut)

    def test_messages_de_la_page(self):
        self.assertEqual(hub_menu.lire_message_page("tv"), {"type": "choix", "mode": "tv"})
        self.assertEqual(hub_menu.lire_message_page('{"type":"infos"}'), {"type": "infos"})
        self.assertIsNone(hub_menu.lire_message_page("pas du json"))
        self.assertIsNone(hub_menu.lire_message_page("[1,2]"))

    def test_duree_lisible(self):
        self.assertEqual(hub_menu.duree_lisible(59), "0 min")
        self.assertEqual(hub_menu.duree_lisible(3 * 3600 + 5 * 60), "3 h 05")
        self.assertEqual(hub_menu.duree_lisible(2 * 86400 + 4 * 3600), "2 j 4 h")

    def test_infos_ne_plantent_pas(self):
        i = hub_menu.infos()
        self.assertTrue(i["machine"])
        self.assertTrue(i["disqueLibre"].endswith("Go"))


if __name__ == "__main__":
    unittest.main()
