#!/usr/bin/env python3
"""Tests de l'enceinte réseau, sans Spotify, sans iPhone, sans Kodi.

    python3 -m unittest installer/enceinte/test_hub_enceinte.py

POURQUOI CES TESTS. Ce qui peut mal tourner sans qu'on l'entende tout de suite, c'est la
logique : un film qui ne se met pas en pause, deux sons superposés, un nom qui casse la
configuration de shairport-sync, un bandeau qui reste affiché après la fin de la musique.
Les récepteurs eux-mêmes sont prouvés à part, en conteneur (README.md, « Preuves »).

La fin du fichier fait tourner le vrai coordinateur : socket, tube de métadonnées, et un
faux Kodi qui parle JSON-RPC sur la boucle locale.
"""
import base64
import subprocess
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_enceinte as E  # noqa: E402


def chemins_de(d):
    d = Path(d)
    return {
        "reglages": d / "config/hub/reglages.json",
        "config": d / "config/hub/enceinte",
        "cache": d / "cache/hub/spotify",
        "etat-spotify": d / "state/hub/spotify",
        "execution": d / "run/hub",
        "socket": d / "run/hub/enceinte.sock",
        "lecture": d / "run/hub/lecture.json",
        "pochettes": d / "run/hub/pochettes",
        "tube-airplay": d / "run/hub/airplay-metadonnees",
        "conf-airplay": d / "run/hub/shairport-sync.conf",
        "applique": d / "run/hub/enceinte-applique.json",
        "code-recopie": d / "config/hub/enceinte/code-recopie",
        "appareils-recopie": d / "config/hub/enceinte/uxplay-appareils",
        "demande-code": d / "run/hub/recopie-code.json",
    }


def element(genre, code, donnees=None):
    """Un élément du tube de shairport-sync, tel que metadata_hub l'écrit."""
    t, k = genre.encode().hex(), code.encode().hex()
    if donnees is None:
        return f"<item><type>{t}</type><code>{k}</code><length>0</length></item>\n".encode()
    b64 = base64.b64encode(donnees).decode()
    return (f"<item><type>{t}</type><code>{k}</code><length>{len(donnees)}</length>\n"
            f"<data encoding=\"base64\">\n{b64}</data></item>\n").encode()


class Reglages(unittest.TestCase):
    def test_tout_actif_par_defaut_nom_hub(self):
        self.assertEqual(E.reglages_enceinte(None), {"spotify": True, "airplay": True, "ecran": True, "nom": "HUB"})
        self.assertEqual(E.reglages_enceinte({"systeme": {}})["nom"], "HUB")

    def test_desactiver_chaque_service(self):
        r = E.reglages_enceinte({"systeme": {"enceinte": {"spotify": False, "ecran": False, "nom": "Salon"}}})
        self.assertEqual(r, {"spotify": False, "airplay": True, "ecran": False, "nom": "Salon"})

    def test_nom_nettoye(self):
        self.assertEqual(E.nom_propre("  Sa\nlon\t "), "Salon")
        self.assertEqual(E.nom_propre(""), "HUB")
        self.assertEqual(E.nom_propre(42), "HUB")
        self.assertEqual(len(E.nom_propre("x" * 100)), 40)

    def test_reglages_illisibles(self):
        with tempfile.TemporaryDirectory() as d:
            c = chemins_de(d)
            self.assertEqual(E.lire_reglages(c)["nom"], "HUB")
            self.assertTrue(E.lire_reglages(c)["recopiePermise"])
            c["reglages"].parent.mkdir(parents=True)
            c["reglages"].write_text("{pas du json")
            self.assertTrue(E.lire_reglages(c)["spotify"])
            # On ne sait plus qui regarde : la musique reste, la recopie non.
            self.assertFalse(E.lire_reglages(c)["recopiePermise"])
            self.assertFalse(E.actif(E.lire_reglages(c), "ecran"))


def reglages_profils(actif, **temps):
    return {"profilActif": actif, "profils": [
        {"id": "samuel"},
        {"id": "lea", "tempsEcran": {"limites": [None] * 7, "debut": None, "fin": None, **temps}},
    ]}


class RecopieSelonLeProfil(unittest.TestCase):
    """Le format est celui que lit hub-temps-ecran (profilActif, profils[].tempsEcran)."""

    def test_profil_sans_regle(self):
        self.assertFalse(E.profil_encadre(reglages_profils("samuel")))
        self.assertFalse(E.profil_encadre(None))
        self.assertFalse(E.profil_encadre({"profils": "x"}))
        # Règles présentes mais toutes vides : rien n'est compté, rien n'est refusé.
        self.assertFalse(E.profil_encadre(reglages_profils("lea")))

    def test_une_limite_un_seul_jour_suffit(self):
        limites = [None] * 7
        limites[5] = 90
        self.assertTrue(E.profil_encadre(reglages_profils("lea", limites=limites)))
        limites[5] = 0
        self.assertTrue(E.profil_encadre(reglages_profils("lea", limites=limites)))

    def test_plage_horaire(self):
        self.assertTrue(E.profil_encadre(reglages_profils("lea", fin="21:00")))
        self.assertTrue(E.profil_encadre(reglages_profils("lea", debut="07:30")))
        self.assertFalse(E.profil_encadre(reglages_profils("lea", debut="25:00")))

    def test_valeurs_ignorees_comme_hub_temps_ecran(self):
        self.assertFalse(E.profil_encadre(reglages_profils("lea", limites=[True] * 7)))
        self.assertFalse(E.profil_encadre(reglages_profils("lea", limites=[60] * 6)))
        self.assertFalse(E.profil_encadre(reglages_profils("lea", limites=[-1] * 7)))

    def test_actif(self):
        r = E.reglages_enceinte(None)
        self.assertTrue(E.actif({**r, "recopiePermise": True}, "ecran"))
        self.assertFalse(E.actif({**r, "recopiePermise": False}, "ecran"))
        self.assertTrue(E.actif({**r, "recopiePermise": False}, "spotify"))
        self.assertFalse(E.actif({**r, "ecran": False, "recopiePermise": True}, "ecran"))


class Configurations(unittest.TestCase):
    def setUp(self):
        self.c = chemins_de("/run/essai")
        self.r = E.reglages_enceinte({"systeme": {"enceinte": {"nom": 'Le "HUB" \\ salon'}}})

    def valeur(self, args, option):
        return args[args.index(option) + 1]

    def test_librespot(self):
        a = E.arguments_librespot(self.r, self.c, programme="/opt/l")
        self.assertEqual(a[0], "/opt/l")
        self.assertEqual(self.valeur(a, "--name"), 'Le "HUB" \\ salon')
        self.assertEqual(self.valeur(a, "--backend"), "pulseaudio")
        self.assertEqual(self.valeur(a, "--mixer"), "softvol")
        self.assertEqual(self.valeur(a, "--cache-size-limit"), "500M")
        self.assertEqual(self.valeur(a, "--zeroconf-port"), "5390")
        # librespot découpe --onevent sur les espaces : aucun argument ne doit en contenir d'autres.
        self.assertEqual(self.valeur(a, "--onevent").split(), ["/usr/local/bin/hub-enceinte", "evenement", "spotify"])

    def test_shairport_nom_echappe_et_ports(self):
        conf = E.config_shairport(self.r, self.c)
        self.assertIn('name = "Le \\"HUB\\" \\\\ salon";', conf)
        self.assertIn('output_backend = "pa";', conf)
        self.assertIn("port = 5000;", conf)
        self.assertIn("udp_port_base = 6001;", conf)
        self.assertIn('pipe_name = "/run/essai/run/hub/airplay-metadonnees";', conf)
        self.assertIn('mpris_service_bus = "session";', conf)
        self.assertIn('allow_session_interruption = "no";', conf)
        self.assertNotIn("password =", conf)
        self.assertEqual(conf.count("{"), conf.count("}"))

    def test_uxplay(self):
        a = E.arguments_uxplay(self.r, self.c, "0482", programme="/usr/bin/uxplay")
        self.assertEqual(self.valeur(a, "-n"), 'Le "HUB" \\ salon Écran')
        self.assertEqual(self.valeur(a, "-pin"), "0482")
        self.assertEqual(self.valeur(a, "-reg"), "/run/essai/config/hub/enceinte/uxplay-appareils")
        self.assertIn("-nh", a)
        self.assertIn("-fs", a)
        self.assertEqual(self.valeur(a, "-p"), "7000")
        self.assertEqual(self.valeur(a, "-vs"), "waylandsink")

    def test_uxplay_ne_plante_pas_sans_bureau_declare(self):
        self.assertEqual(E.environnement_uxplay({"A": "1"}), {"A": "1", "XDG_CURRENT_DESKTOP": "GNOME"})
        self.assertEqual(E.environnement_uxplay({"XDG_CURRENT_DESKTOP": "GNOME-Kiosk"})["XDG_CURRENT_DESKTOP"], "GNOME-Kiosk")

    def test_ports_airplay_et_ecran_ne_se_chevauchent_pas(self):
        base, etendue = E.PORTS_UDP_AIRPLAY
        airplay = set(range(base, base + etendue)) | {E.PORT_AIRPLAY}
        ecran = set(range(E.PORT_ECRAN, E.PORT_ECRAN + 3))
        self.assertFalse(airplay & ecran)
        self.assertNotIn(E.PORT_SPOTIFY, airplay | ecran | {5353})


class Evenements(unittest.TestCase):
    def test_librespot_piste(self):
        ev = E.evenement_librespot({
            "PLAYER_EVENT": "track_changed", "TRACK_ID": "abc", "NAME": "Titre",
            "ARTISTS": "A\nB", "ALBUM": "Album",
            "COVERS": "https://i.scdn.co/image/1\nhttps://i.scdn.co/image/2"})
        self.assertEqual(ev, {"source": "spotify", "nouvellePiste": True, "piste": "abc", "titre": "Titre",
                              "artiste": "A, B", "album": "Album", "pochetteUrl": "https://i.scdn.co/image/1"})

    def test_librespot_episode_et_couverture_non_https(self):
        ev = E.evenement_librespot({"PLAYER_EVENT": "track_changed", "NAME": "Ép. 3", "SHOW_NAME": "Émission",
                                    "COVERS": "http://exemple/x"})
        self.assertEqual(ev["artiste"], "Émission")
        self.assertIsNone(ev["pochetteUrl"])

    def test_librespot_etats(self):
        self.assertEqual(E.evenement_librespot({"PLAYER_EVENT": "playing"})["etat"], "lecture")
        self.assertEqual(E.evenement_librespot({"PLAYER_EVENT": "paused"})["etat"], "pause")
        self.assertEqual(E.evenement_librespot({"PLAYER_EVENT": "stopped"})["etat"], "arret")
        self.assertEqual(E.evenement_librespot({"PLAYER_EVENT": "session_disconnected"})["etat"], "arret")
        self.assertEqual(E.evenement_librespot({"PLAYER_EVENT": "session_client_changed", "CLIENT_NAME": "Pixel"})["appareil"], "Pixel")
        self.assertIsNone(E.evenement_librespot({"PLAYER_EVENT": "volume_changed", "VOLUME": "3"}))
        self.assertIsNone(E.evenement_librespot({}))

    def test_airplay_morceaux_coupes_n_importe_ou(self):
        flux = (element("ssnc", "pbeg") + element("ssnc", "snam", "iPhone de Sam".encode())
                + element("ssnc", "mdst") + element("core", "minm", "Clair de lune".encode())
                + element("core", "asar", "Debussy".encode()) + element("ssnc", "PICT", b"\xff\xd8image")
                + element("ssnc", "pfls") + element("ssnc", "pend"))
        lecteur, evenements = E.MetadonneesAirplay(), []
        for i in range(0, len(flux), 7):
            evenements += lecteur.nourrir(flux[i:i + 7])
        self.assertEqual(lecteur.reste, b"")
        self.assertEqual([e.get("etat") for e in evenements if "etat" in e], ["lecture", "pause", "arret"])
        self.assertIn({"source": "airplay", "appareil": "iPhone de Sam"}, evenements)
        self.assertIn({"source": "airplay", "titre": "Clair de lune"}, evenements)
        self.assertIn({"source": "airplay", "artiste": "Debussy"}, evenements)
        self.assertIn({"source": "airplay", "pochetteOctets": b"\xff\xd8image", "piste": "a1"}, evenements)

    def test_airplay_ignore_le_reste(self):
        lecteur = E.MetadonneesAirplay()
        self.assertEqual(lecteur.nourrir(element("ssnc", "pvol", b"-20.0,0,0,0") + element("core", "mper", b"12")), [])

    def test_uxplay(self):
        debut = E.ligne_uxplay("connection request from iPhone de Sam (iPhone15,2) with deviceID = AA:BB\n")
        self.assertEqual(debut, {"source": "ecran", "etat": "lecture", "appareil": "iPhone de Sam"})
        self.assertIsNone(E.ligne_uxplay("Open connections: 1"))
        self.assertEqual(E.ligne_uxplay("Open connections: 0"), {"source": "ecran", "etat": "arret"})
        self.assertIsNone(E.ligne_uxplay("raop_rtp_mirror starting"))
        # Messages de lib/raop_handlers.h, UxPlay 1.73.2.
        self.assertEqual(E.ligne_uxplay("client sent PAIR-PIN-START request\n"), {"source": "ecran", "demandeCode": True})
        self.assertEqual(E.ligne_uxplay("pair-pin-setup (step 3): client authentication failed\n"),
                         {"source": "ecran", "codeFaux": True})


class CodeRecopie(unittest.TestCase):
    def test_codes_evidents_refuses(self):
        for code in ("0000", "7777", "1234", "6789", "9876", "3210"):
            self.assertTrue(E.code_evident(code), code)
        self.assertFalse(E.code_evident("0482"))
        tirages = iter([1111, 1234, 0, 482])
        self.assertEqual(E.nouveau_code(lambda n: next(tirages)), "0482")

    def test_cree_une_fois_prive_puis_stable(self):
        with tempfile.TemporaryDirectory() as d:
            c = chemins_de(d)
            code = E.code_recopie(c)
            self.assertRegex(code, r"^\d{4}$")
            self.assertEqual(c["code-recopie"].stat().st_mode & 0o777, 0o600)
            self.assertEqual(E.code_recopie(c), code)
            c["code-recopie"].write_text("abc\n")
            self.assertNotEqual(E.code_recopie(c, hasard=lambda n: 4821), "abc")

    def test_renouveler_oublie_les_appareils(self):
        with tempfile.TemporaryDirectory() as d:
            c = chemins_de(d)
            E.code_recopie(c, hasard=lambda n: 4821)
            c["appareils-recopie"].write_text("cle,AA:BB,iPhone\n")
            (c["config"] / "uxplay.pem").write_text("cle")
            self.assertEqual(E.code_recopie(c, renouveler=True, hasard=lambda n: 5930), "5930")
            self.assertFalse(c["appareils-recopie"].exists())
            self.assertFalse((c["config"] / "uxplay.pem").exists())
            self.assertEqual(E.code_recopie(c), "5930")

    def test_commande_code_pour_le_menu(self):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "XDG_CONFIG_HOME": str(Path(d) / "config"), "XDG_RUNTIME_DIR": str(Path(d) / "run")}
            sortie = subprocess.run([sys.executable, E.__file__, "code"], env=env, capture_output=True, text=True, check=True)
            self.assertRegex(sortie.stdout, r"^\d{4}\n$")
            self.assertEqual((Path(d) / "config/hub/enceinte/code-recopie").read_text(), sortie.stdout)
            encore = subprocess.run([sys.executable, E.__file__, "code"], env=env, capture_output=True, text=True)
            self.assertEqual(encore.stdout, sortie.stdout)
            self.assertEqual(subprocess.run([sys.executable, E.__file__, "code", "x"], env=env).returncode, 2)

    def test_garde_cinq_codes_faux_en_un_quart_d_heure(self):
        g = E.GardeCode()
        self.assertEqual([g.code_faux(t) for t in (0, 10, 20, 30)], [False] * 4)
        self.assertTrue(g.code_faux(40))
        # Des erreurs espacées d'une soirée ne verrouillent jamais.
        g = E.GardeCode()
        self.assertFalse(any(g.code_faux(t * 400) for t in range(20)))

    def test_uxplay_verrouille_apres_cinq_codes_faux(self):
        faux = ("import sys, time\n"
                "print('client sent PAIR-PIN-START request', flush=True)\n"
                "for _ in range(5): print('pair-pin-setup (step 3): client authentication failed', flush=True)\n"
                "time.sleep(30)\n")
        with tempfile.TemporaryDirectory() as d:
            c = chemins_de(d)
            ancien = E.arguments_uxplay
            E.arguments_uxplay = lambda r, c, code: [sys.executable, "-c", faux]
            envoyes, envoyer = [], E.envoyer
            E.envoyer = lambda ev, c=None: envoyes.append(ev)
            try:
                with open(os.devnull, "w") as muet:
                    sortie, sys.stdout = sys.stdout, muet
                    try:
                        debut = time.time()
                        retour, verrouille = E.une_recopie(c, E.lire_reglages(c), "0482", E.GardeCode(), [])
                    finally:
                        sys.stdout = sortie
            finally:
                E.arguments_uxplay, E.envoyer = ancien, envoyer
            self.assertTrue(verrouille)
            self.assertLess(time.time() - debut, 10)
            self.assertIn({"source": "ecran", "demandeCode": True, "code": "0482"}, envoyes)
            self.assertEqual(envoyes[-1], {"source": "ecran", "etat": "arret"})


class Priorite(unittest.TestCase):
    def test_spotify_met_kodi_en_pause_et_le_bandeau_apparait(self):
        l = E.Lecture()
        self.assertEqual(l.appliquer({"source": "spotify", "nouvellePiste": True, "piste": "p", "titre": "T", "artiste": "A"}, 1), [])
        # Une piste annoncée avant la lecture n'est pas encore montrée…
        self.assertIsNone(l.publique())
        self.assertEqual(l.appliquer({"source": "spotify", "etat": "lecture"}, 2), [("kodi-pause",)])
        self.assertEqual(l.publique(), {"source": "spotify", "etat": "lecture", "titre": "T", "artiste": "A",
                                        "album": None, "appareil": None, "pochette": None, "ecran": False})

    def test_reprise_apres_pause_repause_kodi_mais_pas_un_changement_de_piste(self):
        l = E.Lecture()
        l.appliquer({"source": "spotify", "etat": "lecture"}, 1)
        self.assertEqual(l.appliquer({"source": "spotify", "nouvellePiste": True, "titre": "Suivante"}, 2), [])
        self.assertEqual(l.appliquer({"source": "spotify", "etat": "lecture"}, 3), [])
        l.appliquer({"source": "spotify", "etat": "pause"}, 4)
        self.assertEqual(l.publique()["etat"], "pause")
        self.assertEqual(l.appliquer({"source": "spotify", "etat": "lecture"}, 5), [("kodi-pause",)])

    def test_la_derniere_source_gagne(self):
        l = E.Lecture()
        l.appliquer({"source": "spotify", "etat": "lecture"}, 1)
        self.assertEqual(l.appliquer({"source": "airplay", "etat": "lecture"}, 2), [("kodi-pause",), ("arreter", "spotify")])
        self.assertEqual(l.publique()["source"], "airplay")
        self.assertNotIn("spotify", l.sources)

    def test_une_source_en_pause_n_est_pas_arretee(self):
        l = E.Lecture()
        l.appliquer({"source": "spotify", "etat": "lecture"}, 1)
        l.appliquer({"source": "spotify", "etat": "pause"}, 2)
        self.assertEqual(l.appliquer({"source": "airplay", "etat": "lecture"}, 3), [("kodi-pause",)])
        # Celle qui joue passe devant celle en pause.
        self.assertEqual(l.publique()["source"], "airplay")
        l.appliquer({"source": "airplay", "etat": "arret"}, 4)
        self.assertEqual(l.publique()["source"], "spotify")

    def test_kodi_qui_reprend_arrete_ce_qui_joue(self):
        l = E.Lecture()
        l.appliquer({"source": "airplay", "etat": "lecture"}, 1)
        l.appliquer({"source": "ecran", "etat": "pause"}, 2)
        self.assertEqual(l.kodi_lecture(), [("arreter", "airplay")])
        self.assertEqual(l.publique()["source"], "ecran")
        self.assertEqual(E.Lecture().kodi_lecture(), [])

    def test_recopie_d_ecran(self):
        l = E.Lecture()
        l.appliquer({"source": "spotify", "etat": "lecture"}, 1)
        self.assertEqual(l.appliquer({"source": "ecran", "etat": "lecture", "appareil": "iPad"}, 2),
                         [("kodi-pause",), ("arreter", "spotify")])
        self.assertTrue(l.publique()["ecran"])
        l.appliquer({"source": "ecran", "etat": "arret"}, 3)
        self.assertIsNone(l.publique())

    def test_arret_efface_les_metadonnees(self):
        l = E.Lecture()
        l.appliquer({"source": "airplay", "etat": "lecture", "titre": "Vieux"}, 1)
        l.appliquer({"source": "airplay", "etat": "arret"}, 2)
        l.appliquer({"source": "airplay", "etat": "lecture"}, 3)
        self.assertIsNone(l.publique()["titre"])

    def test_pochette_en_retard_ignoree_si_la_piste_a_change(self):
        l = E.Lecture()
        l.appliquer({"source": "spotify", "etat": "lecture", "nouvellePiste": True, "piste": "b"}, 1)
        l.appliquer({"source": "spotify", "piste": "a", "pochette": "file:///vieille.jpg"}, 2)
        self.assertIsNone(l.publique()["pochette"])
        l.appliquer({"source": "spotify", "piste": "b", "pochette": "file:///bonne.jpg"}, 3)
        self.assertEqual(l.publique()["pochette"], "file:///bonne.jpg")

    def test_source_inconnue_et_textes_bornes(self):
        l = E.Lecture()
        self.assertEqual(l.appliquer({"source": "netflix", "etat": "lecture"}), [])
        l.appliquer({"source": "airplay", "etat": "lecture", "titre": "x" * 500, "artiste": 12})
        self.assertEqual(len(l.publique()["titre"]), 200)
        self.assertIsNone(l.publique()["artiste"])


class Kodi(unittest.TestCase):
    def test_objets_colles_et_coupes(self):
        a = b'{"jsonrpc":"2.0","method":"Player.OnPause","params":{}}{"id":1,"result":[]}{"jsonrpc":'
        objets, reste = E.decouper_json(a)
        self.assertEqual(len(objets), 2)
        self.assertEqual(reste, b'{"jsonrpc":')
        objets, reste = E.decouper_json(reste + b'"2.0","method":"Player.OnPlay"}  ')
        self.assertEqual(objets[0]["method"], "Player.OnPlay")
        self.assertEqual(reste, b"")

    def test_reponses(self):
        self.assertEqual(E.reponse_kodi({"method": "Player.OnResume"}), ("kodi-lecture", []))
        self.assertEqual(E.reponse_kodi({"method": "Player.OnStop"}), (None, []))
        genre, requetes = E.reponse_kodi({"id": E.ID_JOUEURS, "result": [{"playerid": 1, "type": "video"}]})
        self.assertIsNone(genre)
        self.assertEqual(json.loads(requetes[0]), {"jsonrpc": "2.0", "method": "Player.PlayPause",
                                                   "params": {"playerid": 1, "play": False}, "id": 7002})


class Executions(unittest.TestCase):
    def enregistreur(self, codes=None):
        appels = []

        def executer(cmd, **_):
            appels.append(cmd)
            return SimpleNamespace(returncode=(codes or {}).get(cmd[0], 0))
        return appels, executer

    def test_arreter_airplay_par_mpris_sinon_relance(self):
        appels, executer = self.enregistreur()
        E.arreter_source("airplay", executer)
        self.assertEqual(appels[0][0], "gdbus")
        self.assertEqual(len(appels), 1)
        appels, executer = self.enregistreur({"gdbus": 1})
        E.arreter_source("airplay", executer)
        self.assertEqual(appels[-1], ["systemctl", "--user", "restart", "hub-airplay.service"])

    def test_arreter_spotify_relance_son_unite(self):
        appels, executer = self.enregistreur()
        E.arreter_source("spotify", executer)
        self.assertEqual(appels, [["systemctl", "--user", "restart", "hub-spotify.service"]])

    def test_appliquer_ne_relance_que_ce_qui_a_change(self):
        with tempfile.TemporaryDirectory() as d:
            c = chemins_de(d)
            r = E.lire_reglages(c)
            for s in E.SOURCES:
                E.noter_lancement(c, r, s)
            appels, executer = self.enregistreur()
            self.assertEqual(E.appliquer(c, executer), [])
            c["reglages"].parent.mkdir(parents=True, exist_ok=True)
            c["reglages"].write_text(json.dumps({"profils": [], "systeme": {"enceinte": {"ecran": False}}}))
            self.assertEqual(E.appliquer(c, executer), ["ecran"])
            self.assertEqual(appels, [["systemctl", "--user", "restart", "hub-airplay-ecran.service"]])
            # Désactivé : il ne repart pas, donc rien ne notera son lancement ; appliquer s'en souvient.
            self.assertEqual(E.appliquer(c, executer), [])
            c["reglages"].write_text(json.dumps({"systeme": {"enceinte": {"ecran": False, "nom": "Salon"}}}))
            self.assertEqual(sorted(E.appliquer(c, executer)), ["airplay", "ecran", "spotify"])

    def test_profil_encadre_arrete_la_recopie(self):
        with tempfile.TemporaryDirectory() as d:
            c = chemins_de(d)
            c["reglages"].parent.mkdir(parents=True)
            c["reglages"].write_text(json.dumps(reglages_profils("samuel")))
            r = E.lire_reglages(c)
            for s in E.SOURCES:
                E.noter_lancement(c, r, s)
            appels, executer = self.enregistreur()
            c["reglages"].write_text(json.dumps(reglages_profils("lea", fin="20:00")))
            self.assertEqual(E.appliquer(c, executer), ["ecran"])
            self.assertEqual(appels, [["systemctl", "--user", "restart", "hub-airplay-ecran.service"]])
            c["reglages"].write_text(json.dumps(reglages_profils("samuel")))
            self.assertEqual(E.appliquer(c, executer), ["ecran"])

    def test_actif(self):
        with tempfile.TemporaryDirectory() as d:
            ancien, programmes = dict(os.environ), (E.SHAIRPORT, E.UXPLAY)
            try:
                os.environ["XDG_CONFIG_HOME"] = d
                (Path(d) / "hub").mkdir()
                (Path(d) / "hub/reglages.json").write_text(json.dumps({"systeme": {"enceinte": {"airplay": False}}}))
                vrai = sys.executable
                E.SHAIRPORT, E.UXPLAY = vrai, vrai
                self.assertEqual(E.principal(["x", "actif", "airplay"]), 1)
                self.assertEqual(E.principal(["x", "actif", "ecran"]), 0)
                (Path(d) / "hub/reglages.json").write_text(json.dumps(reglages_profils("lea", limites=[60] * 7)))
                self.assertEqual(E.principal(["x", "actif", "ecran"]), 1)
                self.assertEqual(E.principal(["x", "actif", "airplay"]), 0)
                E.UXPLAY = "/nexiste/pas"
                self.assertEqual(E.principal(["x", "actif", "ecran"]), 1)
                with open(os.devnull, "w") as muet:
                    sortie, sys.stderr = sys.stderr, muet
                    try:
                        self.assertEqual(E.principal(["x", "actif", "netflix"]), 2)
                    finally:
                        sys.stderr = sortie
            finally:
                E.SHAIRPORT, E.UXPLAY = programmes
                os.environ.clear()
                os.environ.update(ancien)


class FauxKodi:
    """Un Kodi qui note les requêtes reçues et peut envoyer des notifications."""

    def __init__(self):
        self.serveur = socket.socket()
        self.serveur.bind(("127.0.0.1", 0))
        self.serveur.listen(1)
        self.adresse = self.serveur.getsockname()
        self.recu = []
        self.client = None
        threading.Thread(target=self.servir, daemon=True).start()

    def servir(self):
        self.client, _ = self.serveur.accept()
        tampon = b""
        while True:
            octets = self.client.recv(65536)
            if not octets:
                return
            objets, tampon = E.decouper_json(tampon + octets)
            for o in objets:
                self.recu.append(o)
                if o.get("method") == "Player.GetActivePlayers":
                    self.client.sendall(json.dumps({"id": o["id"], "jsonrpc": "2.0", "result": [{"playerid": 1, "type": "video"}]}).encode())

    def notifier(self, methode):
        self.client.sendall(json.dumps({"jsonrpc": "2.0", "method": methode, "params": {"data": {}, "sender": "xbmc"}}).encode())


class CoordinateurReel(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.c = chemins_de(self._tmp.name)
        self.kodi = FauxKodi()
        self.appels = []
        self.coord = E.Coordinateur(self.c, executer=lambda cmd, **_: self.appels.append(cmd) or SimpleNamespace(returncode=0),
                                    kodi=self.kodi.adresse)
        self.coord.ouvrir()
        self.fini = False
        self.fil = threading.Thread(target=self.tourner, daemon=True)
        self.fil.start()

    def tourner(self):
        while not self.fini:
            self.coord.tourner_une_fois(0.05)

    def tearDown(self):
        self.fini = True
        self.fil.join(2)
        self.coord.fermer()
        self._tmp.cleanup()

    def attendre(self, condition, delai=5):
        fin = time.time() + delai
        while time.time() < fin:
            if condition():
                return True
            time.sleep(0.02)
        self.fail("condition jamais atteinte")

    def lecture(self):
        try:
            return json.loads(self.c["lecture"].read_text())
        except (OSError, ValueError):
            return None

    def test_parcours_complet(self):
        self.attendre(lambda: self.kodi.client is not None)
        # Le crochet de librespot, lancé comme librespot le lance.
        env = {**os.environ, "XDG_RUNTIME_DIR": str(Path(self._tmp.name) / "run"),
               "PLAYER_EVENT": "track_changed", "TRACK_ID": "t1", "NAME": "Titre", "ARTISTS": "Artiste"}
        for evenement in ("track_changed", "playing"):
            env["PLAYER_EVENT"] = evenement

            subprocess.run([sys.executable, E.__file__, "evenement", "spotify"], env=env, check=True)
        self.attendre(lambda: (self.lecture() or {}).get("etat") == "lecture")
        self.assertEqual(self.lecture()["titre"], "Titre")
        # Kodi a été mis en pause : liste des joueurs, puis pause du joueur vidéo.
        self.attendre(lambda: any(o.get("method") == "Player.PlayPause" for o in self.kodi.recu))
        self.assertEqual([o for o in self.kodi.recu if o.get("method") == "Player.PlayPause"][0]["params"],
                         {"playerid": 1, "play": False})

        # AirPlay arrive par le tube : il prend la main, Spotify est arrêté.
        tube = os.open(self.c["tube-airplay"], os.O_WRONLY | os.O_NONBLOCK)
        os.write(tube, element("ssnc", "pbeg") + element("ssnc", "mdst") + element("core", "minm", b"Chanson")
                 + element("ssnc", "PICT", b"\x89PNG pochette"))
        os.close(tube)
        self.attendre(lambda: (self.lecture() or {}).get("pochette"))
        etat = self.lecture()
        self.assertEqual((etat["source"], etat["titre"]), ("airplay", "Chanson"))
        self.assertEqual(Path(etat["pochette"][7:]).read_bytes(), b"\x89PNG pochette")
        self.attendre(lambda: ["systemctl", "--user", "restart", "hub-spotify.service"] in self.appels)

        # On relance le film dans Kodi : AirPlay s'arrête, le bandeau disparaît.
        self.kodi.notifier("Player.OnResume")
        self.attendre(lambda: any(a[0] == "gdbus" for a in self.appels))
        self.attendre(lambda: self.lecture() is None)

    def test_code_montre_sur_la_tv_puis_cache(self):
        self.attendre(lambda: self.kodi.client is not None)
        env = {**os.environ, "XDG_RUNTIME_DIR": str(Path(self._tmp.name) / "run")}
        # Comme le lanceur d'UxPlay l'envoie.
        E.envoyer({"source": "ecran", "demandeCode": True, "code": "0482"}, self.c)
        self.attendre(lambda: self.c["demande-code"].exists())
        self.assertEqual(json.loads(self.c["demande-code"].read_text())["code"], "0482")
        self.assertEqual(self.c["demande-code"].stat().st_mode & 0o777, 0o600)
        self.attendre(lambda: any(o.get("method") == "GUI.ShowNotification" for o in self.kodi.recu))
        notification = [o for o in self.kodi.recu if o.get("method") == "GUI.ShowNotification"][0]
        self.assertIn("0482", notification["params"]["message"])
        # Un code qui n'en est pas un n'est jamais affiché.
        E.envoyer({"source": "ecran", "demandeCode": True, "code": "<b>"}, self.c)
        # L'appareil est appairé, la recopie commence : le code disparaît.
        subprocess.run([sys.executable, E.__file__, "evenement", "ecran", "lecture"], env=env, check=True)
        self.attendre(lambda: not self.c["demande-code"].exists())

    def test_changement_de_profil_relance_la_recopie(self):
        self.c["reglages"].parent.mkdir(parents=True, exist_ok=True)
        self.c["reglages"].write_text(json.dumps(reglages_profils("lea", limites=[60] * 7)))
        self.attendre(lambda: ["systemctl", "--user", "restart", "hub-airplay-ecran.service"] in self.appels)


if __name__ == "__main__":
    unittest.main()
