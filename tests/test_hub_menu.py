"""Ce que hub-menu fait sans écran : réglages, météo en cache, minuteur, voix.

    python3 -m unittest discover -s tests
"""

import importlib.util
import json
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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

    def test_reglages_lisibles_par_l_utilisateur_seul(self):
        # Les empreintes des codes PIN y sont : ni le groupe ni les autres comptes.
        import os
        ancien = os.umask(0o002)
        try:
            hub_menu.enregistrer_reglages(self.c, {"profils": [{"id": "a"}]})
        finally:
            os.umask(ancien)
        self.assertEqual(self.c["reglages"].stat().st_mode & 0o777, 0o600)

    def test_un_fichier_existant_trop_ouvert_est_resserre(self):
        self.c["reglages"].parent.mkdir(parents=True)
        self.c["reglages"].write_text(json.dumps({"profils": [{"id": "a"}]}))
        self.c["reglages"].chmod(0o644)
        self.assertIsNotNone(hub_menu.charger_reglages(self.c))
        self.assertEqual(self.c["reglages"].stat().st_mode & 0o777, 0o600)

    def test_dernier_choix_ignore_eteindre_et_web(self):
        hub_menu.retenir(self.c, "bureau")
        hub_menu.retenir(self.c, "eteindre")
        hub_menu.retenir(self.c, "web")
        self.assertEqual(hub_menu.dernier_choix(self.c), "bureau")


class Meteo(AvecDossier):
    def test_releve_frais_puis_cache_sans_nouvelle_requete(self):
        appels = []
        telecharger = lambda url: appels.append(url) or METEO
        r1 = hub_menu.meteo(self.c, 45.76, 4.84, maintenant=1000, telecharger=telecharger)
        r2 = hub_menu.meteo(self.c, 45.76, 4.84, maintenant=1000 + 60, telecharger=telecharger)
        self.assertEqual(len(appels), 1)
        self.assertFalse(r1["horsLigne"])
        self.assertEqual(r2["donnees"], METEO)
        self.assertIn("latitude=45.76", appels[0])

    def test_sans_reseau_rend_le_cache_marque_hors_ligne(self):
        hub_menu.meteo(self.c, 45.76, 4.84, maintenant=1000, telecharger=lambda url: METEO)

        def coupe(url):
            raise OSError("réseau absent")
        r = hub_menu.meteo(self.c, 45.76, 4.84, maintenant=1000 + 3600, telecharger=coupe)
        self.assertTrue(r["horsLigne"])
        self.assertEqual(r["releve"], 1000)

    def test_autre_ville_ne_reutilise_pas_le_cache(self):
        hub_menu.meteo(self.c, 45.76, 4.84, maintenant=1000, telecharger=lambda url: METEO)

        def coupe(url):
            raise OSError
        self.assertIsNone(hub_menu.meteo(self.c, 43.3, 5.4, maintenant=1010, telecharger=coupe))

    def test_reponse_inattendue_n_ecrase_pas_le_cache(self):
        hub_menu.meteo(self.c, 45.76, 4.84, maintenant=1000, telecharger=lambda url: METEO)
        r = hub_menu.meteo(self.c, 45.76, 4.84, maintenant=5000, telecharger=lambda url: {"error": True})
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
            {"url": "http://192.168.1.50:8790/", "code": "123456", "expire": 5, "telephones": 1, "appairageLe": None, "secret": "x"}))
        self.assertEqual(hub_menu.etat_telecommande(self.c),
                         {"url": "http://192.168.1.50:8790/", "code": "123456", "expire": 5, "telephones": 1,
                          "listeTelephones": None, "appairageLe": None,
                          "https": None, "appairageOuvert": None, "appairageJusque": None, "empreinteRacineCourte": None,
                          "empreinteRacine": None})

    def test_liste_des_telephones_relayee_ou_ecartee(self):
        base = {"url": "http://192.168.1.50:8790/", "code": "123456"}
        liste = [{"id": "2ab063", "nom": "Pixel 8", "cree": 1789400000000, "vu": 1789500000000}]
        hub_menu.ecrire_atomique(self.c["telecommande"], json.dumps({**base, "listeTelephones": liste}))
        self.assertEqual(hub_menu.etat_telecommande(self.c)["listeTelephones"], liste)
        # Ce qui n'a pas la forme attendue n'atteint pas la page : elle en fait des boutons.
        for mauvaise in ("2ab063", 42, [{"nom": "sans id"}], [["2ab063"]], [None]):
            hub_menu.ecrire_atomique(self.c["telecommande"], json.dumps({**base, "listeTelephones": mauvaise}))
            self.assertIsNone(hub_menu.etat_telecommande(self.c)["listeTelephones"], mauvaise)

    def test_retirer_un_telephone_passe_par_la_commande_du_service(self):
        appels = []

        def executer(commande, **_kw):
            appels.append(commande)
            return subprocess.CompletedProcess(commande, 0)

        self.assertTrue(hub_menu.retirer_telephone("2ab063", executer=executer))
        self.assertEqual(appels, [["hub-telecommande", "--revoquer", "2ab063"]])
        # Rien du réseau ne devient argument : un identifiant qui n'a pas la forme
        # attendue n'appelle rien du tout.
        for mauvais in (None, 42, "", "2ab063; rm -rf /", "../../etc", "x" * 40):
            self.assertFalse(hub_menu.retirer_telephone(mauvais, executer=executer), mauvais)
        self.assertEqual(len(appels), 1)

    def test_fenetre_d_appairage_et_empreinte_courte(self):
        base = {"url": "http://192.168.1.50:8790/", "code": "123456"}
        hub_menu.ecrire_atomique(self.c["telecommande"], json.dumps({**base, "https": "https://hub.local:8791/", "appairageOuvert": True,
                                                                       "appairageJusque": 1789500000000, "empreinteRacineCourte": "3A9F 12C0 4481 7BE2"}))
        etat = hub_menu.etat_telecommande(self.c)
        self.assertEqual((etat["https"], etat["appairageOuvert"], etat["appairageJusque"], etat["empreinteRacineCourte"]),
                         ("https://hub.local:8791/", True, 1789500000000, "3A9F 12C0 4481 7BE2"))
        for mauvais in ({"appairageOuvert": "oui"}, {"appairageOuvert": 1}, {"appairageJusque": True}, {"empreinteRacineCourte": "3a9f 12c0 4481 7be2"},
                        {"empreinteRacineCourte": "3A9F12C044817BE2"}, {"empreinteRacineCourte": "<b>3A9F 12C0 4481 7BE2"}):
            hub_menu.ecrire_atomique(self.c["telecommande"], json.dumps({**base, **mauvais}))
            cle = next(iter(mauvais))
            self.assertIsNone(hub_menu.etat_telecommande(self.c)[cle], mauvais)

    def test_empreinte_du_certificat_transmise_si_bien_formee(self):
        empreinte = ":".join(["AB", "0C"] * 16)
        base = {"url": "http://192.168.1.50:8790/", "code": "123456"}
        hub_menu.ecrire_atomique(self.c["telecommande"], json.dumps({**base, "empreinteRacine": empreinte}))
        self.assertEqual(hub_menu.etat_telecommande(self.c)["empreinteRacine"], empreinte)
        for mauvaise in (None, 42, "AB:CD", empreinte.lower(), empreinte + ":00", "<b>" + empreinte[3:]):
            hub_menu.ecrire_atomique(self.c["telecommande"], json.dumps({**base, "empreinteRacine": mauvaise}))
            self.assertIsNone(hub_menu.etat_telecommande(self.c)["empreinteRacine"], mauvaise)

    def test_ouvrir_la_fenetre_d_appairage(self):
        import os
        self.c["telecommande-appairage"] = Path(self._tmp.name) / "run/hub/telecommande-appairage"
        fenetre = self.c["telecommande-appairage"]
        self.assertTrue(hub_menu.ouvrir_appairage(self.c))
        self.assertTrue(fenetre.is_file() and not fenetre.is_symlink())
        self.assertEqual(fenetre.stat().st_mode & 0o777, 0o600)
        os.utime(fenetre, (1000, 1000))
        hub_menu.ouvrir_appairage(self.c)
        self.assertGreater(fenetre.stat().st_mtime, time.time() - 60, "retoucher remet la date à maintenant")
        hub_menu.fermer_appairage(self.c)
        self.assertFalse(fenetre.exists())
        hub_menu.fermer_appairage(self.c)

    def test_un_lien_symbolique_est_remplace_sans_toucher_sa_cible(self):
        import os
        fenetre = self.c["telecommande-appairage"] = Path(self._tmp.name) / "run/hub/telecommande-appairage"
        cible = Path(self._tmp.name) / "cible"
        cible.write_text("x")
        os.utime(cible, (1000, 1000))
        fenetre.parent.mkdir(parents=True, exist_ok=True)
        fenetre.symlink_to(cible)
        self.assertTrue(hub_menu.ouvrir_appairage(self.c))
        self.assertFalse(fenetre.is_symlink())
        self.assertEqual(cible.stat().st_mtime, 1000)

    def test_suivre_retouche_toutes_les_30_s_et_ferme_en_quittant(self):
        import os
        fenetre = self.c["telecommande-appairage"] = Path(self._tmp.name) / "run/hub/telecommande-appairage"
        touche = hub_menu.suivre_appairage(self.c, True, None, maintenant=1000)
        self.assertEqual(touche, 1000)
        os.utime(fenetre, (1, 1))
        self.assertEqual(hub_menu.suivre_appairage(self.c, True, touche, maintenant=1010), 1000)
        self.assertEqual(fenetre.stat().st_mtime, 1, "pas de retouche avant 30 s")
        self.assertEqual(hub_menu.suivre_appairage(self.c, True, touche, maintenant=1030), 1030)
        self.assertGreater(fenetre.stat().st_mtime, 1)
        self.assertIsNone(hub_menu.suivre_appairage(self.c, False, 1030, maintenant=1032))
        self.assertFalse(fenetre.exists())

    def test_texte_envoye_du_telephone(self):
        self.assertEqual(hub_menu.message_voix("texte:Brest".encode()), {"type": "texte", "texte": "Brest"})


class Habillage(unittest.TestCase):
    def test_active_regenere_les_fonds_desactive_restaure_une_fois(self):
        with tempfile.TemporaryDirectory() as d:
            marqueur = Path(d) / "habillage-desactive"
            lances = []
            executer = lambda cmd, **k: lances.append(cmd)
            hub_menu.appliquer_habillage({"systeme": {}}, executer, marqueur)
            self.assertEqual(lances[-1], ["hub-theme", "apercu"])
            hub_menu.appliquer_habillage({"systeme": {"habillage": False}}, executer, marqueur)
            hub_menu.appliquer_habillage({"systeme": {"habillage": False}}, executer, marqueur)
            self.assertEqual(lances.count(["hub-theme", "restaurer"]), 1)
            self.assertTrue(marqueur.exists())
            hub_menu.appliquer_habillage({"systeme": {"habillage": True}}, executer, marqueur)
            self.assertFalse(marqueur.exists())

    def test_hub_theme_absent_ne_casse_rien(self):
        def absent(*a, **k):
            raise FileNotFoundError
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(hub_menu.appliquer_habillage({"systeme": {}}, absent, Path(d) / "m"))


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


class Internet(unittest.TestCase):
    """L'indicateur de l'en-tête : NetworkManager simulé, jamais de réseau réel."""

    def nmcli(self, sortie, code=0):
        appels = []

        def executer(cmd, **k):
            appels.append(cmd)
            return SimpleNamespace(stdout=sortie, returncode=code)
        executer.appels = appels
        return executer

    def test_connectivite_lue_chez_networkmanager(self):
        for sortie, attendu in (("full\n", "full"), ("limited\n", "limited"), ("portal\n", "portal"),
                                ("none\n", "none"), ("unknown\n", "unknown"), ("n'importe quoi\n", None)):
            with self.subTest(sortie=sortie):
                executer = self.nmcli(sortie)
                self.assertEqual(hub_menu.connectivite_nm(executer), attendu)
        # Relire l'état connu, jamais « connectivity check » : pas d'appel réseau à chaque relevé.
        self.assertEqual(executer.appels, [["nmcli", "-t", "networking", "connectivity"]])
        self.assertIsNone(hub_menu.connectivite_nm(self.nmcli("", code=8)))

        def absent(*a, **k):
            raise FileNotFoundError("nmcli")
        self.assertIsNone(hub_menu.connectivite_nm(absent))

    def test_trois_etats_d_apres_networkmanager_sans_sonde(self):
        sonde = mock.Mock(side_effect=AssertionError("NetworkManager sait : pas de sonde"))
        self.assertEqual(hub_menu.etat_internet("full", "192.168.1.20", sonde), {"etat": "internet"})
        self.assertEqual(hub_menu.etat_internet("limited", "192.168.1.20", sonde), {"etat": "local"})
        self.assertEqual(hub_menu.etat_internet("portal", "192.168.1.20", sonde), {"etat": "local", "nuance": "portail"})
        self.assertEqual(hub_menu.etat_internet("none", None, sonde), {"etat": "aucun"})

    def test_sans_avis_de_networkmanager_la_sonde_tranche(self):
        self.assertEqual(hub_menu.etat_internet("unknown", "192.168.1.20", lambda: True), {"etat": "internet"})
        self.assertEqual(hub_menu.etat_internet(None, "192.168.1.20", lambda: False), {"etat": "local"})
        sonde = mock.Mock()
        self.assertEqual(hub_menu.etat_internet(None, None, sonde), {"etat": "aucun"})
        sonde.assert_not_called()

    def test_sonde_resolution_puis_connexion_courte_vers_la_source(self):
        vus = []

        class Connexion:
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def connecter(adresse, timeout):
            vus.append((adresse, timeout))
            return Connexion()
        self.assertTrue(hub_menu.sonder_internet(connecter=connecter))
        self.assertEqual(vus, [(("github.com", 443), hub_menu.SONDE_DELAI_S)])

        def dns_absent(*a, **k):
            raise socket.gaierror(-3, "Temporary failure in name resolution")
        self.assertFalse(hub_menu.sonder_internet(connecter=dns_absent))

        def trop_long(*a, **k):
            raise socket.timeout("timed out")
        self.assertFalse(hub_menu.sonder_internet(connecter=trop_long))


class VerificationAuto(unittest.TestCase):
    H = 3600

    def due(self, **k):
        base = dict(maintenant=100 * self.H, suivi=None, internet="internet", active=True, deja_ce_demarrage=False, occupe=False)
        return hub_menu.verification_auto_due(**{**base, **k})

    def test_au_demarrage_des_qu_internet_est_la(self):
        self.assertTrue(self.due())
        self.assertTrue(self.due(suivi={"le": 100 * self.H - 60}), "une fois par démarrage, même vérifié juste avant")

    def test_jamais_sans_internet(self):
        for internet in ("local", "aucun", None):
            with self.subTest(internet=internet):
                self.assertFalse(self.due(internet=internet))

    def test_jamais_pendant_un_mode_ou_une_installation_ni_desactivee(self):
        self.assertFalse(self.due(occupe=True))
        self.assertFalse(self.due(active=False))

    def test_puis_toutes_les_six_heures(self):
        maintenant = 100 * self.H
        self.assertFalse(self.due(deja_ce_demarrage=True, suivi={"le": maintenant - 5 * self.H}))
        self.assertTrue(self.due(deja_ce_demarrage=True, suivi={"le": maintenant - 6 * self.H}))
        self.assertTrue(self.due(deja_ce_demarrage=True, suivi=None))

    def test_un_echec_se_reessaie_plus_tot(self):
        maintenant = 100 * self.H
        self.assertFalse(self.due(deja_ce_demarrage=True, suivi={"le": maintenant - 20 * 60, "echec": True}))
        self.assertTrue(self.due(deja_ce_demarrage=True, suivi={"le": maintenant - 30 * 60, "echec": True}))

    def test_reglage_actif_par_defaut(self):
        self.assertTrue(hub_menu.maj_auto_active(None))
        self.assertTrue(hub_menu.maj_auto_active({"systeme": {}}))
        self.assertFalse(hub_menu.maj_auto_active({"systeme": {"miseAJourAuto": False}}))

    def test_installation_en_cours(self):
        maintenant = 1000 * self.H
        self.assertFalse(hub_menu.installation_en_cours(None, maintenant))
        self.assertTrue(hub_menu.installation_en_cours({"etape": "tests", "le": (maintenant - 60) * 1000}, maintenant))
        self.assertFalse(hub_menu.installation_en_cours({"etape": "echec", "le": (maintenant - 60) * 1000}, maintenant))
        # Service tué en pleine installation : l'état resté n'empêche pas les vérifications pour toujours.
        self.assertFalse(hub_menu.installation_en_cours({"etape": "installation", "le": (maintenant - 3 * self.H) * 1000}, maintenant))

    def test_annonce_une_seule_fois_par_version(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "maj-auto.json"
            dispo = {"disponible": True, "verifiable": True, "distant": "abc123", "installee": "000000"}
            suivi, annoncer = hub_menu.noter_verification_auto(f, dispo, 10)
            self.assertTrue(annoncer)
            self.assertEqual(hub_menu.lire_json(f), {"le": 10, "verification": dispo, "echec": False, "annoncee": "abc123"})
            self.assertFalse(hub_menu.noter_verification_auto(f, dispo, 20)[1])
            self.assertTrue(hub_menu.noter_verification_auto(f, {**dispo, "distant": "def456"}, 30)[1])
            self.assertFalse(hub_menu.noter_verification_auto(f, {**dispo, "distant": "fed789", "verifiable": False}, 40)[1])
            self.assertFalse(hub_menu.noter_verification_auto(f, {"disponible": False, "distant": "000000"}, 50)[1])

    def test_un_echec_garde_la_derniere_bonne_reponse(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "maj-auto.json"
            dispo = {"disponible": True, "distant": "abc123", "installee": "000000"}
            hub_menu.noter_verification_auto(f, dispo, 10)
            suivi, annoncer = hub_menu.noter_verification_auto(f, {"erreur": "reseau", "detail": "DNS"}, 20)
            self.assertFalse(annoncer)
            self.assertEqual((suivi["le"], suivi["echec"], suivi["verification"]), (20, True, dispo))

    def test_version_disponible_retrouvee_au_retour_d_un_mode(self):
        dispo = {"disponible": True, "distant": "abc123456789", "installee": "000000"}
        self.assertEqual(hub_menu.maj_auto_initiale({"verification": dispo}, "0000000"), dispo)
        self.assertIsNone(hub_menu.maj_auto_initiale({"verification": dispo}, "abc1234"), "installée depuis")
        self.assertIsNone(hub_menu.maj_auto_initiale({"verification": dispo}, "1111111"), "autre version en place")
        self.assertIsNone(hub_menu.maj_auto_initiale({"verification": {"disponible": False}}, "0000000"))
        self.assertIsNone(hub_menu.maj_auto_initiale(None, "0000000"))

    def test_commit_installe(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "VERSION"
            self.assertIsNone(hub_menu.commit_installe(f))
            f.write_text("v1-3-ga03afa7-dirty\n")
            self.assertEqual(hub_menu.commit_installe(f), "a03afa7")


class SuiviInstallation(unittest.TestCase):
    def test_un_etat_d_avant_le_lancement_est_ignore(self):
        # Constaté le 17/09/2026 : « Installer » affichait l'échec d'un essai précédent, resté
        # dans /run jusqu'au redémarrage, dès que le service tardait plus de 2 s à écrire.
        lance_le = 1_000_000
        ancien = {"etape": "echec", "raison": "source", "le": lance_le - 60_000}
        self.assertIsNone(hub_menu.etat_depuis(ancien, lance_le))
        self.assertIsNone(hub_menu.etat_depuis({"etape": "echec"}, lance_le))
        frais = {"etape": "verification", "le": lance_le + 300}
        self.assertEqual(hub_menu.etat_depuis(frais, lance_le), frais)
        self.assertIsNone(hub_menu.etat_depuis(None, lance_le))

    def test_bilan_du_service(self):
        sortie = "ActiveState=failed\nResult=exit-code\nExecMainStatus=1\nStateChangeTimestampMonotonic=5000000000\n"
        executer = lambda cmd, **k: SimpleNamespace(stdout=sortie, returncode=0)
        self.assertEqual(hub_menu.bilan_service(executer), {"ActiveState": "failed", "Result": "exit-code", "ExecMainStatus": "1", "StateChangeTimestampMonotonic": "5000000000"})

        def absent(*a, **k):
            raise FileNotFoundError("systemctl")
        self.assertIsNone(hub_menu.bilan_service(absent))

    def test_service_arrete_sans_etat_devient_un_echec_detaille(self):
        lance = 4990.0
        arrete = {"ActiveState": "failed", "Result": "resources", "ExecMainStatus": "0", "StateChangeTimestampMonotonic": "4995000000"}
        echec = hub_menu.echec_sans_etat(arrete, lance, ecoule=8)
        self.assertEqual((echec["etape"], echec["raison"]), ("echec", "service"))
        self.assertIn("resources", echec["detail"])
        self.assertIsNone(hub_menu.echec_sans_etat(arrete, lance, ecoule=2), "on laisse au service le temps d'écrire")
        # Arrêt d'un lancement précédent, et job en attente (network-online.target) : on attend.
        vieux = {**arrete, "StateChangeTimestampMonotonic": "1000000000"}
        self.assertIsNone(hub_menu.echec_sans_etat(vieux, lance, ecoule=30))
        self.assertIsNone(hub_menu.echec_sans_etat({**arrete, "ActiveState": "activating"}, lance, ecoule=30))
        self.assertIsNone(hub_menu.echec_sans_etat(None, lance, ecoule=30))


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

    def test_services_web_par_nom_jamais_par_adresse(self):
        self.assertEqual(hub_menu.message_voix(b"web:netflix"), {"type": "commande", "nom": "web:netflix"})
        for brut in (b"web:https://exemple.org", b"web:", b"web:NETFLIX"):
            self.assertIsNone(hub_menu.message_voix(brut), brut)
        self.assertEqual(hub_menu.service_choisi({"type": "choix", "mode": "web", "service": "youtube"}), "youtube")
        for mauvais in ("https://www.youtube.com/tv", "youtube\nbureau", None, 3, ""):
            self.assertIsNone(hub_menu.service_choisi({"type": "choix", "mode": "web", "service": mauvais}), mauvais)

    def test_services_disponibles_lus_dans_hub_web(self):
        d = hub_menu.services_disponibles(RACINE / "installer" / "hub-web")
        self.assertEqual(set(d["services"]), hub_menu.SERVICES_WEB)
        self.assertIsNone(hub_menu.services_disponibles(RACINE / "nexiste-pas"))

    def test_infos_ne_plantent_pas(self):
        i = hub_menu.infos()
        self.assertTrue(i["machine"])
        self.assertTrue(i["disqueLibre"].endswith("Go"))


class Fluidite(AvecDossier):
    def test_compteur_demande_par_variable_ou_par_fichier(self):
        self.c["mesurer-fluidite"] = self.c["execution"] / "mesurer-fluidite"
        self.assertFalse(hub_menu.mesure_fluidite_demandee(self.c, {}))
        self.assertTrue(hub_menu.mesure_fluidite_demandee(self.c, {"HUB_FPS": "1"}))
        self.assertFalse(hub_menu.mesure_fluidite_demandee(self.c, {"HUB_FPS": "0"}))
        self.c["execution"].mkdir(parents=True)
        self.c["mesurer-fluidite"].touch()
        self.assertTrue(hub_menu.mesure_fluidite_demandee(self.c, {}))
        # Des chemins sans l'entrée (anciens appelants) : pas de compteur, pas d'erreur.
        self.assertFalse(hub_menu.mesure_fluidite_demandee({}, {}))

    def test_releve_de_la_page_en_une_ligne_de_nombres(self):
        ligne = hub_menu.ligne_fps({"type": "fps", "ecran": "accueil", "moyenne": 29.7, "min": 24, "longues": 3, "pire": 118, "fenetre": 5})
        self.assertEqual(ligne, "hub-menu : fluidité accueil — 29.7 images/s, pire seconde 24, 3 images > 50 ms (pire 118 ms) sur 5.0 s")
        self.assertIsNone(hub_menu.ligne_fps({"type": "fps", "moyenne": "beaucoup"}))
        self.assertIn("fluidité ? —", hub_menu.ligne_fps({"ecran": "x\nfaux", "moyenne": 1, "min": 1, "longues": 0, "pire": 1, "fenetre": 1}))

    def test_ligne_de_rendu_omet_ce_qui_manque(self):
        self.assertEqual(hub_menu.ligne_rendu({"webkit": "2.52.6", "acceleration": "always", "gsk": None, "ecran": "3840x2160", "frequence": "30.00 Hz"}),
                         "hub-menu : rendu webkit=2.52.6 ; acceleration=always ; ecran=3840x2160 ; frequence=30.00 Hz")


# Sortie de `gdctl show --verbose` sur la TV du salon : un seul écran, un 4K plafonné à
# 30 Hz par le lien HDMI 1.4, et des modes 60 Hz en 1080p. L'arbre est celui que dessine
# gdctl (tools/gdctl de mutter) : quatre colonnes par niveau.
GDCTL_TV = """\
Monitors:
└──Monitor HDMI-2 (SONY TV)
   ├──Vendor: SNY
   ├──Product: SONY TV
   ├──Serial: 0x01010101
   ├──Modes (5)
   │   ├──3840x2160@30.000
   │   │   ├──Dimension: 3840x2160
   │   │   ├──Refresh rate: 30.000
   │   │   ├──Preferred scale: 2.0
   │   │   ├──Supported scales: [1.0, 2.0]
   │   │   └──Properties: (2)
   │   │       ├──is-current ⇒  yes
   │   │       └──is-preferred ⇒  yes
   │   ├──1920x1080@60.000
   │   │   ├──Dimension: 1920x1080
   │   │   ├──Refresh rate: 60.000
   │   │   ├──Preferred scale: 1.0
   │   │   ├──Supported scales: [1.0]
   │   │   └──Properties: (0)
   │   ├──1920x1080@50.000
   │   │   ├──Dimension: 1920x1080
   │   │   ├──Refresh rate: 50.000
   │   │   ├──Preferred scale: 1.0
   │   │   ├──Supported scales: [1.0]
   │   │   └──Properties: (0)
   │   ├──1280x720@60.000
   │   │   ├──Dimension: 1280x720
   │   │   ├──Refresh rate: 60.000
   │   │   ├──Preferred scale: 1.0
   │   │   ├──Supported scales: [1.0]
   │   │   └──Properties: (0)
   │   └──720x480@60.000
   │       ├──Dimension: 720x480
   │       ├──Refresh rate: 60.000
   │       ├──Preferred scale: 1.0
   │       ├──Supported scales: [1.0]
   │       └──Properties: (0)
   ├──Preferences
   │   └──Backlight: None
   └──Properties: (2)
       ├──display-name ⇒  SONY TV
       └──is-builtin ⇒  no

Logical monitors:
└──Logical monitor #1
   ├──Position: (0, 0)
   ├──Scale: 2.0
   ├──Transform: normal
   ├──Primary: yes
   └──Monitors: (1)
       └──HDMI-2 (SONY TV)
"""


class Affichage(unittest.TestCase):
    def sortie(self, texte="", code=0):
        return lambda *a, **k: SimpleNamespace(returncode=code, stdout=texte, stderr="")

    def test_modes_et_mode_actif_lus_dans_la_sortie_de_gdctl(self):
        ecrans = hub_menu.lire_modes(GDCTL_TV)
        self.assertEqual(len(ecrans), 1)
        self.assertEqual(ecrans[0]["connecteur"], "HDMI-2")
        self.assertEqual(ecrans[0]["nom"], "SONY TV")
        self.assertEqual([m["nom"] for m in ecrans[0]["modes"]],
                         ["3840x2160@30.000", "1920x1080@60.000", "1920x1080@50.000", "1280x720@60.000", "720x480@60.000"])
        actif = ecrans[0]["modes"][0]
        self.assertEqual((actif["largeur"], actif["hauteur"], actif["frequence"]), (3840, 2160, 30.0))
        self.assertTrue(actif["courant"] and actif["prefere"])
        self.assertFalse(any(m["courant"] for m in ecrans[0]["modes"][1:]))

    def test_une_sortie_inattendue_ne_donne_aucun_mode(self):
        for texte in ("", "gdctl: command not found", "Monitors:\n(rien)", "3840x2160@30.000", GDCTL_TV.replace("──", " ")):
            self.assertEqual(hub_menu.lire_modes(texte), [], texte[:30])

    def test_les_modes_vont_du_plus_confortable_au_moins_bon(self):
        modes = hub_menu.lire_modes(GDCTL_TV)[0]["modes"]
        # 60 Hz d'abord, puis la définition ; le 4K à 30 Hz ferme la marche, le 720×480 sort.
        self.assertEqual([m["nom"] for m in hub_menu.modes_confortables(modes)],
                         ["1920x1080@60.000", "1920x1080@50.000", "1280x720@60.000", "3840x2160@30.000"])

    def test_les_frequences_presque_egales_ne_font_pas_doublon(self):
        modes = [
            {"nom": "1920x1080@60.000", "largeur": 1920, "hauteur": 1080, "frequence": 60.0, "courant": False, "prefere": True},
            {"nom": "1920x1080@59.940", "largeur": 1920, "hauteur": 1080, "frequence": 59.94, "courant": True, "prefere": False},
        ]
        # Le mode actif gagne le doublon : il doit rester marqué dans la liste affichée.
        retenus = hub_menu.modes_confortables(modes)
        self.assertEqual([m["nom"] for m in retenus], ["1920x1080@59.940"])
        self.assertTrue(retenus[0]["courant"])

    def test_le_mode_actif_est_toujours_propose(self):
        # Le moins bon des dix, mais c'est celui qui est actif : il prend la dernière place.
        modes = [{"nom": f"{1920 + i}x1080@60.000", "largeur": 1920 + i, "hauteur": 1080,
                  "frequence": 60.0, "courant": i == 0, "prefere": False} for i in range(10)]
        retenus = hub_menu.modes_confortables(modes, maximum=3)
        self.assertEqual([m["nom"] for m in retenus],
                         ["1929x1080@60.000", "1928x1080@60.000", "1920x1080@60.000"])

    def test_sans_gdctl_la_section_reste_en_lecture_seule(self):
        etat = hub_menu.etat_affichage(executer=self.sortie(GDCTL_TV), trouver=lambda _: None)
        self.assertEqual(etat["gdctl"], False)
        self.assertEqual(etat["modes"], [])
        self.assertIsNone(etat["erreur"])
        # Et rien ne s'applique, quoi que la page demande.
        refus = hub_menu.changer_mode("1920x1080@60.000", executer=self.sortie(GDCTL_TV), trouver=lambda _: None)
        self.assertEqual((refus["applique"], refus["raison"]), (False, "absent"))

    def test_gdctl_en_echec_est_rapporte_sans_modes(self):
        executer = lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="Could not connect to display config")
        etat = hub_menu.etat_affichage(executer=executer, trouver=lambda _: "/usr/bin/gdctl")
        self.assertTrue(etat["gdctl"])
        self.assertEqual(etat["modes"], [])
        self.assertIn("display config", etat["erreur"])

    def test_applique_le_mode_choisi_et_l_enregistre(self):
        appels = []

        def executer(commande, **k):
            appels.append(commande)
            return SimpleNamespace(returncode=0, stdout=GDCTL_TV, stderr="")

        r = hub_menu.changer_mode("1920x1080@60.000", executer=executer, trouver=lambda _: "/usr/bin/gdctl")
        self.assertTrue(r["applique"])
        self.assertEqual(r["avant"], "3840x2160@30.000")
        self.assertIn(["gdctl", "set", "--persistent", "--logical-monitor", "--primary",
                       "--monitor", "HDMI-2", "--mode", "1920x1080@60.000"], appels)

    def test_refuse_une_valeur_qui_ne_vient_pas_de_la_liste(self):
        appels = []

        def executer(commande, **k):
            appels.append(commande)
            return SimpleNamespace(returncode=0, stdout=GDCTL_TV, stderr="")

        for mauvais in ("1920x1080@60", "800x600@60.000", "; reboot", "1920x1080@60.000 --autre"):
            r = hub_menu.changer_mode(mauvais, executer=executer, trouver=lambda _: "/usr/bin/gdctl")
            self.assertEqual((r["applique"], r["raison"]), (False, "inconnu"), mauvais)
        self.assertEqual([c for c in appels if "set" in c], [], "aucune application ne doit partir")
        # Même en court-circuitant la liste, la commande refuse ce qui n'est pas un mode.
        self.assertEqual(hub_menu.appliquer_mode("HDMI-2", "; reboot")[0], False)
        self.assertEqual(hub_menu.appliquer_mode("HDMI-2 ; reboot", "1920x1080@60.000")[0], False)

    def test_une_application_refusee_par_l_ecran_est_dite(self):
        def executer(commande, **k):
            if "set" in commande:
                return SimpleNamespace(returncode=1, stdout="", stderr="No mode 1920x1080@60.000 available for HDMI-2")
            return SimpleNamespace(returncode=0, stdout=GDCTL_TV, stderr="")

        r = hub_menu.changer_mode("1920x1080@60.000", executer=executer, trouver=lambda _: "/usr/bin/gdctl")
        self.assertEqual((r["applique"], r["raison"]), (False, "echec"))
        self.assertIn("No mode", r["erreur"])

    def test_gdctl_introuvable_a_l_execution_ne_plante_pas(self):
        def executer(*a, **k):
            raise OSError("[Errno 2] No such file or directory: 'gdctl'")

        etat = hub_menu.etat_affichage(executer=executer, trouver=lambda _: "/usr/bin/gdctl")
        self.assertEqual(etat["modes"], [])
        self.assertIn("No such file", etat["erreur"])

    def test_mode_a_retablir_au_demarrage(self):
        lu = hub_menu.modes_ecran(executer=self.sortie(GDCTL_TV), trouver=lambda _: "/usr/bin/gdctl")
        garde = {"systeme": {"affichage": {"mode": "1920x1080@60.000", "connecteur": "HDMI-2", "retablir": True}}}
        self.assertEqual(hub_menu.mode_a_retablir(garde, lu), "1920x1080@60.000")
        # Déjà actif, refusé, sur un autre écran, inconnu de l'écran, ou rien de gardé.
        for reglages in (
            {"systeme": {"affichage": {"mode": "3840x2160@30.000", "retablir": True}}},
            {"systeme": {"affichage": {"mode": "1920x1080@60.000", "retablir": False}}},
            {"systeme": {"affichage": {"mode": "1920x1080@60.000", "connecteur": "DP-1", "retablir": True}}},
            {"systeme": {"affichage": {"mode": "2560x1440@60.000", "retablir": True}}},
            {"systeme": {}}, {}, None,
        ):
            self.assertIsNone(hub_menu.mode_a_retablir(reglages, lu), reglages)
        # Sans gdctl, rien à rétablir.
        self.assertIsNone(hub_menu.mode_a_retablir(garde, hub_menu.modes_ecran(trouver=lambda _: None)))

if __name__ == "__main__":
    unittest.main()
