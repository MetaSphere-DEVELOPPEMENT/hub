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
    """Le mot d'éveil « HUB » seul (réglage "hub"), celui des premières mesures."""

    def analyse(self, texte):
        return L.analyser(texte, "fr", "hub")

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
        return L.analyser(texte, "fr", "hub")

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
        e = L.Ecoute("fr", mot_eveil="hub")
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
        return L.analyser(texte, "en", "hub")

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
        self.assertEqual(L.analyser("hub télé", "de", "hub"), (True, "tv"))


class Protocole(unittest.TestCase):
    # Lu dans hub-menu.py plutôt que recopié : une commande que le menu ne connaît pas
    # serait jetée sans un mot, et une commande du menu sans phrase ne se dirait pas.
    @staticmethod
    def commandes_du_menu():
        import ast
        source = Path(__file__).resolve().parent.parent / "hub-menu.py"
        for noeud in ast.parse(source.read_text(encoding="utf-8")).body:
            if isinstance(noeud, ast.Assign) and any(getattr(c, "id", None) == "COMMANDES"
                                                     for c in noeud.targets):
                return set(ast.literal_eval(noeud.value))
        raise AssertionError("COMMANDES introuvable dans hub-menu.py")

    def test_commandes_du_protocole_et_seulement_elles(self):
        protocole = self.commandes_du_menu()
        self.assertIn("web:netflix", protocole)
        for langue in L.LANGUES:
            self.assertEqual(set(L.COMMANDES[langue]), protocole, langue)


class Web(unittest.TestCase):
    def test_services_francais(self):
        for texte, commande in [("hub lance netflix", "web:netflix"), ("hub youtube", "web:youtube"),
                                ("hub mets france télé", "web:francetv"), ("hub disney plus", "web:disneyplus"),
                                ("hub ouvre prime vidéo", "web:primevideo"), ("hub va sur twitch", "web:twitch"),
                                ("hub lance geforce now", "web:geforcenow"), ("hub xbox", "web:xcloud"),
                                ("hub steam", "web:steam"), ("hub moonlight", "web:moonlight"),
                                ("hub canal plus", "web:canalplus"), ("hub arte", "web:arte"),
                                ("hub booster", "web:boosteroid")]:
            self.assertEqual(L.analyser(texte, "fr", "hub"), (True, commande), texte)

    def test_france_tele_n_est_pas_la_tele(self):
        # « télé » seul est la commande tv : la phrase la plus longue doit l'emporter.
        self.assertEqual(L.analyser("ok hub france télé", "fr"), (True, "web:francetv"))
        self.assertEqual(L.analyser("ok hub télé", "fr"), (True, "tv"))

    def test_services_anglais(self):
        for texte, commande in [("hub launch netflix", "web:netflix"), ("hub open prime video", "web:primevideo"),
                                ("hub france tv", "web:francetv"), ("hub xbox cloud", "web:xcloud"),
                                ("hub tv", "tv")]:
            self.assertEqual(L.analyser(texte, "en", "hub"), (True, commande), texte)

    def test_hub_web_vivant(self):
        racine = Path(tempfile.mkdtemp())
        pid = racine / "web.pid"
        self.assertFalse(L.web_en_cours(pid, racine=str(racine)))
        pid.write_text("4242\n")
        self.assertFalse(L.web_en_cours(pid, racine=str(racine)))  # processus disparu
        (racine / "4242").mkdir()
        (racine / "4242" / "cmdline").write_bytes(b"bash\x00")
        self.assertFalse(L.web_en_cours(pid, racine=str(racine)))  # pid repris par un autre
        (racine / "4242" / "cmdline").write_bytes(b"/usr/bin/python3\x00/usr/local/bin/hub-web\x00netflix\x00")
        self.assertTrue(L.web_en_cours(pid, racine=str(racine)))
        pid.write_text("pas un nombre")
        self.assertFalse(L.web_en_cours(pid, racine=str(racine)))


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
        g = L.grammaire("fr", mots_remplissage=[])
        self.assertIn("ok hub", g)
        self.assertNotIn("hub", g)  # « HUB » seul n'est plus un mot d'éveil par défaut
        self.assertIn("[unk]", g)
        self.assertIn("télé", g)
        self.assertIn("ok hub télé", g)
        self.assertIn("ok hub lance la télé", g)
        self.assertIn("hub télé", L.grammaire("fr", "hub", mots_remplissage=[]))
        self.assertIn("salut hub netflix", L.grammaire("fr", "salut-hub", mots_remplissage=[]))
        self.assertIn("hey hub netflix", L.grammaire("en", "salut-hub", mots_remplissage=[]))
        self.assertIn("nestor télé", L.grammaire("fr", "Nestor", mots_remplissage=[]))

    def test_chaque_phrase_de_la_grammaire_s_analyse(self):
        # Une phrase que Vosk peut rendre mais que l'analyse ne reconnaîtrait pas serait
        # une commande entendue et pourtant ignorée : l'utilisateur ne comprendrait pas.
        for langue in L.LANGUES:
            for mot in list(L.MOTS_EVEIL) + ["nestor"]:
                for phrase in L.grammaire(langue, mot, mots_remplissage=[]):
                    if phrase == "[unk]":
                        continue
                    eveil, commande = L.analyser(phrase, langue, mot)
                    self.assertTrue(eveil or commande, (langue, mot, phrase))
                    if phrase.startswith(L.eveils(mot, langue)) and phrase not in L.eveils(mot, langue):
                        self.assertTrue(eveil and commande, (langue, mot, phrase))

    def test_sans_doublon(self):
        for langue in L.LANGUES:
            g = L.grammaire(langue)
            self.assertEqual(len(g), len(set(g)), langue)

    def test_remplissage_livre(self):
        # Les fichiers sont dans le dépôt, à côté du module : sans eux, la TV redevient
        # capable de lancer des commandes (voir grammaire()).
        for langue in L.LANGUES:
            mots = L.remplissage(langue)
            self.assertEqual(len(mots), L.NOMBRE_REMPLISSAGE, langue)
            g = L.grammaire(langue)
            commandes = set(L.grammaire(langue, mots_remplissage=[]))
            ajoutes = [p for p in g if p not in commandes]
            self.assertGreater(len(ajoutes), 1800, langue)
            # Aucun mot de nos phrases n'est ajouté seul.
            reserves = {m for p in commandes for m in p.split()}
            self.assertFalse(set(ajoutes) & reserves, langue)

    def test_remplissage_absent(self):
        self.assertEqual(L.remplissage("fr", dossier="/nexiste/pas"), [])


class MotEveil(unittest.TestCase):
    def test_nettoyer(self):
        for preregle in L.MOTS_EVEIL:
            self.assertEqual(L.nettoyer_mot_eveil(preregle), preregle)
        self.assertEqual(L.nettoyer_mot_eveil("  Nestor "), "nestor")
        self.assertEqual(L.nettoyer_mot_eveil("Dis  Hélène"), "dis hélène")
        self.assertEqual(L.nettoyer_mot_eveil("Jean-Pierre"), "jean-pierre")
        for mauvais in ("", "   ", "R2D2", "un deux trois", "x" * 30, None, 42, ["hub"], "hub!"):
            self.assertIsNone(L.nettoyer_mot_eveil(mauvais), mauvais)

    def test_par_langue(self):
        self.assertEqual(L.eveils("ok-hub", "fr"), ("okay hub", "ok hub"))
        self.assertEqual(L.eveils("salut-hub", "en"), ("hey hub",))
        self.assertEqual(L.eveils("Nestor", "en"), ("nestor",))
        self.assertEqual(L.eveils("R2D2", "fr"), L.eveils(L.MOT_EVEIL_PAR_DEFAUT, "fr"))

    def test_refus(self):
        self.assertIsNone(L.refus_mot_eveil("salut-hub", "fr"))
        self.assertIsNone(L.refus_mot_eveil("Nestor", "fr", vocabulaire={"nestor"}))
        self.assertEqual(L.refus_mot_eveil("Nestor", "fr", vocabulaire={"hector"}), "inconnu")
        self.assertEqual(L.refus_mot_eveil("Télé", "fr"), "commande")
        self.assertEqual(L.refus_mot_eveil("Netflix", "fr"), "commande")
        self.assertEqual(L.refus_mot_eveil("R2D2", "fr"), "forme")

    def test_ok_hub_par_defaut(self):
        self.assertEqual(L.analyser("ok hub lance la télé", "fr"), (True, "tv"))
        self.assertEqual(L.analyser("okay hub", "fr"), (True, None))
        # « HUB » seul ne réveille plus : c'est ce qui sortait de la TV (« hub de la le steam »).
        self.assertEqual(L.analyser("hub télé", "fr"), (False, "tv"))
        self.assertEqual(L.Ecoute("fr").entendre("hub télé", 0.0), [])

    def test_prenom(self):
        self.assertEqual(L.analyser("nestor lance netflix", "fr", "nestor"), (True, "web:netflix"))
        self.assertEqual(L.analyser("hub netflix", "fr", "nestor"), (False, None))


class AncreDuMotEveil(unittest.TestCase):
    """Sorties réelles de Vosk (grammaire avec remplissage, 15 septembre 2026)."""

    def test_hub_mal_entendu_derriere_l_ancre(self):
        for texte, mot, attendu in [
            ("ok aide lance la télé", "ok-hub", (True, "tv")),
            ("salut va hub les films", "salut-hub", (True, "tv")),
            ("salut hommes jeux", "salut-hub", (True, "gaming")),
            ("salut jouer", "salut-hub", (True, "gaming")),
            ("dis la hub retour", "dis-hub", (True, "retour")),
        ]:
            self.assertEqual(L.analyser(texte, "fr", mot), attendu, texte)

    def test_ancre_seule_au_repos_ouvre_l_ecoute_mais_ok_valide_pendant(self):
        e = L.Ecoute("fr")
        self.assertEqual(e.entendre("okay", 0.0), ["voix:entendu:okay", "voix:eveil"])
        self.assertEqual(e.entendre("ok", 2.0), ["voix:entendu:ok", "ok", "voix:repos"])
        s = L.Ecoute("fr", mot_eveil="salut-hub")
        self.assertEqual(s.entendre("salut", 0.0)[-1], "voix:eveil")
        # Plus tard, une phrase qui commence par « salut » : la fenêtre se ferme, rien d'autre.
        self.assertEqual(s.entendre("salut [unk]", 10.0), ["voix:repos"])

    def test_aide_juste_apres_le_mot_d_eveil(self):
        self.assertEqual(L.analyser("ok hub aide xbox", "fr"), (True, "web:xcloud"))
        self.assertEqual(L.analyser("ok hub aide", "fr"), (True, "aide"))

    def test_ancre_seule_ou_presque_ouvre_l_ecoute(self):
        e = L.Ecoute("fr", mot_eveil="salut-hub")
        self.assertEqual(e.entendre("salut hommes", 0.0), ["voix:entendu:salut hommes", "voix:eveil"])
        self.assertEqual(e.entendre("télé", 2.0)[1], "tv")
        # « salut aide » : « Salut HUB. » dit seul, pas la commande d'aide.
        self.assertEqual(L.analyser("salut aide", "fr", "salut-hub"), (True, None))

    def test_phrases_ordinaires_apres_l_ancre(self):
        for texte in ("salut tu vas bien", "ok d'accord on fait ça demain", "salut les copains on se retrouve",
                      "dis donc il est tard"):
            self.assertEqual(L.analyser(texte, "fr", "salut-hub" if texte.startswith("salut") else
                                        "dis-hub" if texte.startswith("dis") else "ok-hub")[1], None, texte)

    def test_joker_saute_jusqu_a_deux_mots(self):
        # Vosk a rendu « Salut HUB, mets les jeux » (voix gilles) ainsi : les deux mots
        # sautés remplacent « hub », quels qu'ils soient. Trois, c'est une phrase.
        self.assertEqual(L.analyser("salut en bas mets les jeux", "fr", "salut-hub"), (True, "gaming"))
        self.assertEqual(L.analyser("salut tu es en bas mets les jeux", "fr", "salut-hub"), (False, None))

    def test_la_tv_transcrite_en_mots_ordinaires(self):
        for texte in ("lyon veut devenir un hub européen de la logistique",
                      "ce soir sur arte un documentaire sur les océans",
                      "la nouvelle saison arrive sur netflix vendredi"):
            self.assertEqual(L.Ecoute("fr").entendre(texte, 0.0), [], texte)


class Vocabulaire(unittest.TestCase):
    @staticmethod
    def faux_gr_fst(mots):
        import struct

        def chaine(b):
            return struct.pack("<i", len(b)) + b
        entete = struct.pack("<i", 0x7EB2FEB4 & 0) + chaine(b"ngram") + chaine(b"standard") + \
            struct.pack("<iiqqqq", 2, 1, 0, 0, 0, 0)
        table = struct.pack("<I", 0x7EB2FB74) + chaine(b"words.txt") + struct.pack("<qq", len(mots), len(mots))
        for cle, mot in enumerate(mots):
            table += chaine(mot.encode()) + struct.pack("<q", cle)
        chemin = Path(tempfile.mkdtemp()) / "Gr.fst"
        chemin.write_bytes(entete + table + b"\x00" * 64)
        return chemin

    def test_table_de_mots(self):
        chemin = self.faux_gr_fst(["<eps>", "!SIL", "[unk]", "nestor", "télé"])
        self.assertEqual(L.vocabulaire_vosk(chemin), {"<eps>", "!SIL", "[unk]", "nestor", "télé"})

    def test_fichier_absent_ou_autre(self):
        self.assertEqual(L.vocabulaire_vosk("/nexiste/pas"), set())
        autre = Path(tempfile.mkdtemp()) / "Gr.fst"
        autre.write_bytes(b"\x00" * 200)
        self.assertEqual(L.vocabulaire_vosk(autre), set())

    def test_modele_reel_si_present(self):
        chemin = Path(os.environ.get("HUB_VOIX_MODELES", "/opt/hub-voix/modeles")) / \
            "vosk-model-small-fr-0.22" / "graph" / "Gr.fst"
        if not chemin.is_file():
            self.skipTest("modèle français absent")
        mots = L.vocabulaire_vosk(chemin)
        self.assertGreater(len(mots), 100000)
        for mot in ("ok", "hub", "salut", "netflix", "nestor"):
            self.assertIn(mot, mots)


class Ecoute(unittest.TestCase):
    def setUp(self):
        self.e = L.Ecoute("fr", delai_eveil=6.0, mot_eveil="hub")

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
        self.assertEqual(L.Ecoute("en", mot_eveil="hub").entendre("[unk]", 0.0), [])
        self.assertEqual(L.Ecoute("en", mot_eveil="hub").entendre("help", 0.0), [])

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
        evenements = L.Ecoute("fr").entendre("ok hub " + "[unk] " * 200, 0.0)
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

    def test_retour_ferme_d_abord_le_service_web(self):
        self.assertEqual(L.cible("retour", menu_ouvert=False, kodi=True, bureau=True, web=True), "web")
        self.assertEqual(L.cible("retour", menu_ouvert=True, kodi=False, bureau=False, web=True), "menu")
        self.assertIsNone(L.cible("web:netflix", menu_ouvert=False, kodi=False, bureau=False, web=True))

    def test_retour_sans_rien_a_fermer(self):
        self.assertIsNone(L.cible("retour", menu_ouvert=False, kodi=False, bureau=False))


class ReglagesMotEveil(unittest.TestCase):
    def test_lire(self):
        dossier = Path(tempfile.mkdtemp())
        chemin = dossier / "reglages.json"
        self.assertEqual(L.lire_mot_eveil(chemin), L.MOT_EVEIL_PAR_DEFAUT)
        for valeur, attendu in [("salut-hub", "salut-hub"), ("  Nestor", "nestor"), ("R2D2", L.MOT_EVEIL_PAR_DEFAUT),
                                (7, L.MOT_EVEIL_PAR_DEFAUT)]:
            chemin.write_text(json.dumps({"systeme": {"motEveil": valeur}}))
            self.assertEqual(L.lire_mot_eveil(chemin), attendu, valeur)
        chemin.write_text("[]")
        self.assertEqual(L.lire_mot_eveil(chemin), L.MOT_EVEIL_PAR_DEFAUT)


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
