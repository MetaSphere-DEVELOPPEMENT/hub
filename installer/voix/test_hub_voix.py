#!/usr/bin/env python3
"""Tests de la logique de la commande vocale, sans micro, sans modèle, sans Vosk.

Lancer : python3 -m unittest installer/voix/test_hub_voix.py   (ou pytest)

POURQUOI CES TESTS EXISTENT. Ce qui se trompe dans une commande vocale n'est presque
jamais la reconnaissance elle-même : c'est ce qu'on fait du texte. « Retour au HUB »
qui contient le mot d'éveil, « OK HUB » qui contient la commande « ok », une TV qui
dit « films » au milieu d'un journal : chacun de ces cas a déclenché la mauvaise
action dans un premier jet. Ils sont figés ici.
"""

import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path

import hub_voix_logique as L


class Normalisation(unittest.TestCase):
    def test_majuscules_ponctuation_accents(self):
        self.assertEqual(L.normaliser("HUB, lance la Télé !"), "hub lance la tele")

    def test_apostrophes_et_espaces(self):
        self.assertEqual(L.normaliser("  retour   à l'accueil "), "retour a l accueil")

    def test_inconnus_de_vosk_retires(self):
        self.assertEqual(L.normaliser("[unk] hub [unk]"), "hub")


class AnalyseFrancais(unittest.TestCase):
    def analyse(self, texte):
        return L.analyser(texte, "fr")

    def test_eveil_seul(self):
        self.assertEqual(self.analyse("hub"), (True, None))
        self.assertEqual(self.analyse("OK HUB"), (True, None))
        self.assertEqual(self.analyse("okay hub"), (True, None))

    def test_eveil_et_commande_dans_la_meme_phrase(self):
        self.assertEqual(self.analyse("HUB, lance la télé"), (True, "tv"))
        self.assertEqual(self.analyse("ok hub télévision"), (True, "tv"))
        self.assertEqual(self.analyse("hub mets les films"), (True, "tv"))
        self.assertEqual(self.analyse("hub kodi"), (True, "tv"))

    def test_commande_seule(self):
        self.assertEqual(self.analyse("jeux"), (False, "gaming"))
        self.assertEqual(self.analyse("jouer"), (False, "gaming"))
        self.assertEqual(self.analyse("ordinateur"), (False, "bureau"))
        self.assertEqual(self.analyse("travailler"), (False, "bureau"))
        self.assertEqual(self.analyse("paramètres"), (False, "reglages"))
        self.assertEqual(self.analyse("réglages"), (False, "reglages"))
        self.assertEqual(self.analyse("aide"), (False, "aide"))

    def test_retour_au_hub_n_est_pas_un_eveil_suivi_de_rien(self):
        # « hub » est à la fin, pas au début : c'est la commande, pas le mot d'éveil.
        self.assertEqual(self.analyse("retour au hub"), (False, "retour"))
        self.assertEqual(self.analyse("hub retour au hub"), (True, "retour"))
        self.assertEqual(self.analyse("accueil"), (False, "retour"))
        self.assertEqual(self.analyse("retour"), (False, "retour"))

    def test_eteindre(self):
        self.assertEqual(self.analyse("hub éteins"), (True, "eteindre"))
        self.assertEqual(self.analyse("éteindre le hub"), (False, "eteindre"))

    def test_navigation(self):
        for texte, commande in [("gauche", "gauche"), ("à droite", "droite"),
                                ("en haut", "haut"), ("bas", "bas"), ("valide", "ok"),
                                ("ouvre", "ok"), ("ok", "ok")]:
            self.assertEqual(self.analyse(texte), (False, commande), texte)

    def test_ok_hub_ok(self):
        # « OK HUB » est l'éveil ; le « ok » qui suit est la validation.
        self.assertEqual(self.analyse("ok hub ok"), (True, "ok"))
        self.assertEqual(self.analyse("hub ok"), (True, "ok"))

    def test_ouvre_suivi_d_une_cible_n_est_pas_valider(self):
        self.assertEqual(self.analyse("hub ouvre les réglages"), (True, "reglages"))

    def test_meteo_et_profils(self):
        self.assertEqual(self.analyse("hub météo"), (True, "meteo"))
        self.assertEqual(self.analyse("hub ouvre la météo"), (True, "meteo"))
        self.assertEqual(self.analyse("profils"), (False, "profils"))
        self.assertEqual(self.analyse("hub changer de profil"), (True, "profils"))

    def test_avatars_reserve_a_la_telecommande(self):
        for langue in L.LANGUES:
            self.assertNotIn("avatars", L.COMMANDES[langue])

    def test_theme(self):
        self.assertEqual(self.analyse("hub thème clair"), (True, "theme:clair"))
        self.assertEqual(self.analyse("thème sombre"), (False, "theme:sombre"))

    def test_rien_de_connu(self):
        self.assertEqual(self.analyse("hub la météo de demain"), (True, None))
        self.assertEqual(self.analyse("la météo de demain"), (False, None))
        self.assertEqual(self.analyse(""), (False, None))

    def test_langue_anglaise_non_comprise_en_francais(self):
        self.assertEqual(self.analyse("hub settings"), (True, None))


class SortiesReellesDeVosk(unittest.TestCase):
    """Textes réellement rendus par vosk-model-small-fr-0.22 sur le corpus de synthèse.

    La grammaire de Vosk n'impose pas l'ordre des phrases : elle restreint les MOTS,
    que le décodeur enchaîne librement. Il rend donc « hub éteindre le va hub » ou
    « ok va hub jeux », jamais prévus tels quels. L'analyse doit les lire.
    """

    def analyse(self, texte):
        return L.analyser(texte, "fr")

    def test_mots_parasites_autour_de_la_commande(self):
        self.assertEqual(self.analyse("hub éteindre le va hub"), (True, "eteindre"))
        self.assertEqual(self.analyse("hub retour au va"), (True, "retour"))
        self.assertEqual(self.analyse("ok va hub jeux"), (True, "gaming"))
        self.assertEqual(self.analyse("va hub retour"), (True, "retour"))
        self.assertEqual(self.analyse("va le la hub en bas"), (True, "bas"))

    def test_hub_confondu_avec_aide_devant_une_commande(self):
        # « heub » et « aide » sont voisins pour le petit modèle : « aide » en tête,
        # suivi d'une autre commande, ne peut être qu'un « HUB » mal entendu.
        self.assertEqual(self.analyse("aide kodi"), (True, "tv"))
        self.assertEqual(self.analyse("aide bureau"), (True, "bureau"))
        self.assertEqual(self.analyse("aide"), (False, "aide"))
        self.assertEqual(self.analyse("hub aide"), (True, "aide"))

    def test_aide_dans_une_vraie_phrase_n_eveille_pas(self):
        # « Aide-moi à porter ces cartons » (voix siwis et tom, avec et sans bruit).
        self.assertEqual(self.analyse("aide mode bureau"), (False, None))
        self.assertEqual(self.analyse("aide [unk] bureau"), (False, None))
        e = L.Ecoute("fr")
        self.assertEqual(e.entendre("aide [unk]", 0.0), [])
        self.assertEqual(e.entendre("quel temps", 1.0), [])

    def test_deux_commandes_c_est_du_bruit(self):
        self.assertEqual(self.analyse("hub kodi réglages"), (True, None))
        self.assertEqual(self.analyse("va le kodi réglages la la ouvre"), (False, None))

    def test_mot_inconnu_du_hub_reste_bloquant(self):
        self.assertEqual(self.analyse("hub thème les films jouer"), (True, None))

    def test_hub_trop_loin_n_est_pas_un_eveil(self):
        self.assertEqual(self.analyse("retour au hub"), (False, "retour"))
        self.assertEqual(self.analyse("bureau télé hub"), (False, None))


class AnalyseAnglais(unittest.TestCase):
    def analyse(self, texte):
        return L.analyser(texte, "en")

    def test_commandes(self):
        cas = [("hub", (True, None)), ("hey hub", (True, None)),
               ("ok hub launch the tv", (True, "tv")), ("hub movies", (True, "tv")),
               ("games", (False, "gaming")), ("desktop", (False, "bureau")),
               ("turn off the hub", (False, "eteindre")), ("settings", (False, "reglages")),
               ("help", (False, "aide")), ("go back", (False, "retour")),
               ("back to the hub", (False, "retour")), ("home", (False, "retour")),
               ("left", (False, "gauche")), ("select", (False, "ok")),
               ("light theme", (False, "theme:clair")), ("dark mode", (False, "theme:sombre")),
               ("hub weather", (True, "meteo")), ("switch profile", (False, "profils"))]
        for texte, attendu in cas:
            self.assertEqual(self.analyse(texte), attendu, texte)

    def test_langue_inconnue_retombe_sur_le_francais(self):
        self.assertEqual(L.analyser("hub télé", "de"), (True, "tv"))


class Protocole(unittest.TestCase):
    # Recopié du protocole fixé avec hub-menu.py : une commande hors de cette liste
    # serait jetée par le menu sans un mot.
    PROTOCOLE = {"tv", "gaming", "bureau", "eteindre", "reglages", "aide", "meteo", "profils",
                 "retour", "gauche", "droite", "haut", "bas", "ok", "theme:clair", "theme:sombre"}

    def test_commandes_du_protocole_et_seulement_elles(self):
        for langue in L.LANGUES:
            self.assertEqual(set(L.COMMANDES[langue]), self.PROTOCOLE, langue)


class Processus(unittest.TestCase):
    def test_trouve_par_nom_court_et_proprietaire(self):
        racine = Path(tempfile.mkdtemp())
        for pid, nom in ((101, "kodi.bin"), (102, "gnome-kiosk"), (103, "bash")):
            (racine / str(pid)).mkdir()
            (racine / str(pid) / "comm").write_text(nom + "\n")
        (racine / "self").mkdir()
        self.assertEqual(L.processus(L.NOMS_KODI, racine=str(racine)), [101])
        self.assertEqual(L.processus(L.NOMS_BUREAU, racine=str(racine)), [])
        self.assertEqual(L.processus(L.NOMS_KODI, racine=str(racine), uid=os.getuid() + 1), [])
        self.assertEqual(L.processus(L.NOMS_KODI, racine="/nexiste/pas"), [])


class Grammaire(unittest.TestCase):
    def test_contient_eveils_commandes_et_inconnu(self):
        g = L.grammaire("fr")
        self.assertIn("hub", g)
        self.assertIn("ok hub", g)
        self.assertIn("[unk]", g)
        self.assertIn("télé", g)
        self.assertIn("hub télé", g)
        self.assertIn("ok hub lance la télé", g)

    def test_chaque_phrase_de_la_grammaire_s_analyse(self):
        # Une phrase que Vosk peut rendre mais que l'analyse ne reconnaîtrait pas serait
        # une commande entendue et pourtant ignorée : l'utilisateur ne comprendrait pas.
        for langue in L.LANGUES:
            for phrase in L.grammaire(langue):
                if phrase == "[unk]":
                    continue
                eveil, commande = L.analyser(phrase, langue)
                self.assertTrue(eveil or commande, (langue, phrase))

    def test_sans_doublon(self):
        for langue in L.LANGUES:
            g = L.grammaire(langue)
            self.assertEqual(len(g), len(set(g)), langue)


class Ecoute(unittest.TestCase):
    def setUp(self):
        self.e = L.Ecoute("fr", delai_eveil=6.0)

    def test_eveil_puis_commande(self):
        self.assertEqual(self.e.entendre("hub", 0.0), ["voix:entendu:hub", "voix:eveil"])
        self.assertEqual(self.e.entendre("télé", 2.0), ["voix:entendu:télé", "tv", "voix:repos"])
        # L'éveil est consommé : la TV qui dit « films » ensuite ne relance rien.
        self.assertEqual(self.e.entendre("films", 3.0), [])

    def test_phrase_complete(self):
        self.assertEqual(self.e.entendre("hub lance la télé", 0.0),
                         ["voix:entendu:hub lance la télé", "tv", "voix:repos"])

    def test_aide_seul_au_repos_vaut_eveil(self):
        # Au repos, une commande sans éveil est ignorée de toute façon : « aide » seul
        # y est donc plus probablement un « HUB » mal entendu qu'une demande d'aide.
        self.assertEqual(self.e.entendre("aide", 0.0), ["voix:entendu:aide", "voix:eveil"])
        self.assertEqual(self.e.entendre("aide", 2.0), ["voix:entendu:aide", "aide", "voix:repos"])

    def test_inconnu_seul_en_anglais_ne_reveille_pas(self):
        self.assertEqual(L.Ecoute("en").entendre("[unk]", 0.0), [])
        self.assertEqual(L.Ecoute("en").entendre("help", 0.0), [])

    def test_commande_sans_eveil_ignoree(self):
        # C'est la protection contre le son de la TV : sans « HUB », rien ne se passe.
        self.assertEqual(self.e.entendre("films", 0.0), [])
        self.assertEqual(self.e.entendre("[unk]", 0.0), [])

    def test_delai_depasse(self):
        self.e.entendre("hub", 0.0)
        self.assertEqual(self.e.tic(5.0), [])
        self.assertEqual(self.e.tic(6.5), ["voix:repos"])
        self.assertEqual(self.e.tic(7.0), [])
        self.assertEqual(self.e.entendre("télé", 7.5), [])

    def test_incompris_apres_eveil_garde_l_ecoute(self):
        # Le son de la TV entre « HUB » et la commande donne un [unk] : on le signale,
        # mais on n'oblige pas à redire « HUB ». La fenêtre garde son échéance.
        self.e.entendre("hub", 0.0)
        self.assertEqual(self.e.entendre("[unk]", 1.0), ["voix:entendu:[unk]", "voix:incompris"])
        self.assertEqual(self.e.entendre("jeux", 2.0)[1], "gaming")

    def test_incompris_n_allonge_pas_la_fenetre(self):
        self.e.entendre("hub", 0.0)
        self.e.entendre("la pluie demain", 5.0)
        self.assertEqual(self.e.tic(6.5), ["voix:repos"])

    def test_eveil_suivi_de_charabia(self):
        self.assertEqual(self.e.entendre("hub [unk]", 0.0),
                         ["voix:entendu:hub [unk]", "voix:incompris", "voix:eveil"])
        self.assertEqual(self.e.entendre("télé", 3.0)[1], "tv")

    def test_bruit_avant_l_eveil(self):
        self.assertEqual(self.e.entendre("[unk] hub télé", 0.0)[1], "tv")

    def test_eveil_expire_sans_tic(self):
        self.e.entendre("hub", 0.0)
        self.assertEqual(self.e.entendre("télé", 30.0), ["voix:repos"])

    def test_resultat_vide_ne_consomme_pas_l_eveil(self):
        # Vosk rend souvent un résultat vide sur un bruit court entre l'éveil et la
        # commande ; il ne doit pas fermer la fenêtre d'écoute.
        self.e.entendre("hub", 0.0)
        self.assertEqual(self.e.entendre("", 1.0), [])
        self.assertEqual(self.e.entendre("jeux", 2.0)[1], "gaming")

    def test_double_eveil_prolonge(self):
        self.e.entendre("hub", 0.0)
        self.e.entendre("ok hub", 5.0)
        self.assertEqual(self.e.tic(8.0), [])
        self.assertEqual(self.e.entendre("bureau", 9.0)[1], "bureau")

    def test_texte_entendu_borne(self):
        evenements = L.Ecoute("fr").entendre("hub " + "[unk] " * 200, 0.0)
        self.assertLessEqual(len(evenements[0].encode()), L.TAILLE_MAX_ENTENDU + 20)

    def test_changer_de_langue(self):
        self.e.langue = "en"
        self.assertEqual(self.e.entendre("hub settings", 0.0)[1], "reglages")


class Cible(unittest.TestCase):
    def test_menu_ouvert_recoit_tout(self):
        for commande in ("tv", "eteindre", "retour", "voix:eveil", "theme:clair"):
            self.assertEqual(L.cible(commande, menu_ouvert=True, kodi=False, bureau=False), "menu")

    def test_retour_quitte_kodi(self):
        self.assertEqual(L.cible("retour", menu_ouvert=False, kodi=True, bureau=False), "kodi")

    def test_retour_quitte_le_bureau(self):
        self.assertEqual(L.cible("retour", menu_ouvert=False, kodi=False, bureau=True), "bureau")

    def test_kodi_prime_sur_le_bureau(self):
        # Kodi lancé depuis le bureau : « retour » ferme d'abord ce qu'on regarde.
        self.assertEqual(L.cible("retour", menu_ouvert=False, kodi=True, bureau=True), "kodi")

    def test_hors_menu_le_reste_est_ignore(self):
        for commande in ("tv", "eteindre", "gauche", "meteo", "profils", "voix:eveil",
                         "voix:micro-absent"):
            self.assertIsNone(L.cible(commande, menu_ouvert=False, kodi=True, bureau=True), commande)

    def test_retour_sans_rien_a_fermer(self):
        self.assertIsNone(L.cible("retour", menu_ouvert=False, kodi=False, bureau=False))


class Reglages(unittest.TestCase):
    def ecrire(self, contenu):
        dossier = tempfile.mkdtemp()
        chemin = Path(dossier) / "reglages.json"
        chemin.write_text(contenu if isinstance(contenu, str) else json.dumps(contenu))
        return chemin

    def test_fichier_absent(self):
        self.assertEqual(L.lire_reglages(Path("/nexiste/pas.json")), (True, "fr"))

    def test_fichier_illisible(self):
        self.assertEqual(L.lire_reglages(self.ecrire("{pas du json")), (True, "fr"))
        self.assertEqual(L.lire_reglages(self.ecrire("[1, 2]")), (True, "fr"))

    def test_profil_actif_et_voix(self):
        chemin = self.ecrire({"profilActif": "b",
                              "profils": [{"id": "a", "langue": "fr"}, {"id": "b", "langue": "en"}],
                              "systeme": {"voix": False}})
        self.assertEqual(L.lire_reglages(chemin), (False, "en"))

    def test_profil_actif_introuvable(self):
        chemin = self.ecrire({"profilActif": "z", "profils": [{"id": "a", "langue": "en"}]})
        self.assertEqual(L.lire_reglages(chemin), (True, "en"))

    def test_langue_inconnue_et_types_faux(self):
        chemin = self.ecrire({"profilActif": "a", "profils": [{"id": "a", "langue": "klingon"}],
                              "systeme": {"voix": "oui"}})
        self.assertEqual(L.lire_reglages(chemin), (True, "fr"))


class Micros(unittest.TestCase):
    # Extraits réels de pw-dump sur le M720q (13 septembre 2026), réduits à l'utile.
    CARTE_INTERNE = {"id": 46, "type": "PipeWire:Interface:Device",
                     "info": {"props": {"device.bus": "pci"},
                              "params": {"EnumRoute": [
                                  {"direction": "Input", "name": "analog-input-front-mic", "available": "no"},
                                  {"direction": "Input", "name": "analog-input-mic", "available": "no"},
                                  {"direction": "Output", "name": "hdmi-output-0", "available": "yes"}]}}}
    SOURCE_INTERNE = {"id": 40, "type": "PipeWire:Interface:Node",
                      "info": {"props": {"media.class": "Audio/Source", "device.id": 46,
                                         "node.name": "alsa_input.pci-0000_00_1f.3.analog-stereo"}}}
    CARTE_USB = {"id": 70, "type": "PipeWire:Interface:Device",
                 "info": {"props": {"device.bus": "usb"}, "params": {"EnumRoute": []}}}
    SOURCE_USB = {"id": 71, "type": "PipeWire:Interface:Node",
                  "info": {"props": {"media.class": "Audio/Source", "device.id": 70,
                                     "node.name": "alsa_input.usb-micro-00.mono-fallback"}}}

    def test_prise_jack_vide_n_est_pas_un_micro(self):
        self.assertEqual(L.micros_pipewire([self.CARTE_INTERNE, self.SOURCE_INTERNE]), [])

    def test_micro_usb(self):
        dump = [self.CARTE_INTERNE, self.SOURCE_INTERNE, self.CARTE_USB, self.SOURCE_USB]
        self.assertEqual(L.micros_pipewire(dump), ["alsa_input.usb-micro-00.mono-fallback"])

    def test_micro_branche_sur_la_prise(self):
        carte = json.loads(json.dumps(self.CARTE_INTERNE))
        carte["info"]["params"]["EnumRoute"][0]["available"] = "yes"
        self.assertEqual(L.micros_pipewire([carte, self.SOURCE_INTERNE]),
                         ["alsa_input.pci-0000_00_1f.3.analog-stereo"])

    def test_sources_virtuelles_et_moniteurs_exclus(self):
        virtuelle = {"id": 80, "type": "PipeWire:Interface:Node",
                     "info": {"props": {"media.class": "Audio/Source/Virtual", "node.name": "v"}}}
        flux = {"id": 81, "type": "PipeWire:Interface:Node",
                "info": {"props": {"media.class": "Stream/Input/Audio", "node.name": "f"}}}
        self.assertEqual(L.micros_pipewire([virtuelle, flux, {"type": "autre"}, {}]), [])

    def test_micro_usb_prefere_a_la_prise(self):
        carte = json.loads(json.dumps(self.CARTE_INTERNE))
        carte["info"]["params"]["EnumRoute"][0]["available"] = "yes"
        dump = [carte, self.SOURCE_INTERNE, self.CARTE_USB, self.SOURCE_USB]
        self.assertEqual(L.micros_pipewire(dump)[0], "alsa_input.usb-micro-00.mono-fallback")


class Datagrammes(unittest.TestCase):
    def test_envoi_vers_un_socket_qui_ecoute(self):
        dossier = tempfile.mkdtemp()
        chemin = os.path.join(dossier, "menu.sock")
        serveur = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        serveur.bind(chemin)
        self.assertTrue(L.envoyer(chemin, "voix:entendu:hub lance la télé"))
        self.assertEqual(serveur.recv(4096).decode("utf-8"), "voix:entendu:hub lance la télé")
        serveur.close()

    def test_socket_absent_ou_mort(self):
        dossier = tempfile.mkdtemp()
        chemin = os.path.join(dossier, "menu.sock")
        self.assertFalse(L.envoyer(chemin, "tv"))
        # Fichier resté après un menu tombé : personne n'écoute, pas d'exception.
        serveur = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        serveur.bind(chemin)
        serveur.close()
        self.assertFalse(L.envoyer(chemin, "tv"))


class QuitterKodi(unittest.TestCase):
    def test_json_rpc_tcp(self):
        recu = []
        serveur = socket.socket()
        serveur.bind(("127.0.0.1", 0))
        serveur.listen(1)
        port = serveur.getsockname()[1]

        def repondre():
            client, _ = serveur.accept()
            recu.append(json.loads(client.recv(4096)))
            client.sendall(b'{"id":1,"jsonrpc":"2.0","result":"OK"}')
            client.close()

        fil = threading.Thread(target=repondre)
        fil.start()
        self.assertTrue(L.quitter_kodi_tcp("127.0.0.1", port))
        fil.join()
        serveur.close()
        self.assertEqual(recu[0]["method"], "Application.Quit")

    def test_json_rpc_tcp_ferme(self):
        serveur = socket.socket()
        serveur.bind(("127.0.0.1", 0))
        port = serveur.getsockname()[1]
        serveur.close()
        self.assertFalse(L.quitter_kodi_tcp("127.0.0.1", port))


if __name__ == "__main__":
    unittest.main()
