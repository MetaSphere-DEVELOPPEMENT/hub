#!/usr/bin/env python3
"""Les garde-fous du clavier-souris, route par route, par de vraies requêtes.

Lancer : python3 -m unittest installer/telecommande/test_pointeur_service.py

POURQUOI UN FICHIER À PART. Un téléphone qui tape dans la session du bureau, c'est le
plus gros pouvoir que la télécommande ait jamais donné. Chaque condition qui le garde
fermé a donc son test ici, sur les TROIS routes qui y mènent (`POST /api/commande`,
`POST /api/pointeur/session`, le WebSocket `/api/pointeur`), en http et en https réels
sur la boucle locale, contre un faux /dev/uinput qui note ce que le noyau aurait reçu :
« rien n'a été écrit » est vérifié, pas supposé.
"""

import json
import socket
import ssl
import subprocess
import sys
import time
import unittest
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import hub_pointeur as P  # noqa: E402
import hub_telecommande as T  # noqa: E402
from banc_essai import ClientWS  # noqa: E402
from test_pointeur import FauxNoyau, LISTE, bloc  # noqa: E402
from test_telecommande import AvecDossier, FauxMenu  # noqa: E402

SYN = (P.EV_SYN, P.SYN_REPORT, 0)


class AvecPointeur(AvecDossier):
    """Le service en http ET https, un faux noyau, un faux logind, un contexte au choix."""

    def setUp(self):
        super().setUp()
        self.noyau = FauxNoyau()
        self.contexte = "bureau"
        self.session = bloc()            # ce que logind répond : active, déverrouillée
        self.executes = []
        routeur = T.Routeur(self.chemins["socket"], executer=self._executer,
                            processus=lambda noms: [1] if self.contexte == "bureau" and "gnome-shell" in noms else [],
                            web_en_cours=lambda: self.contexte == "web", kodi_http=None)
        self.tls = T.AutoriteLocale(self.chemins["tls"])
        self.service = T.Service(self.chemins, routeur=routeur, tls=self.tls)
        self.service.pointeur = T.Pointeur(self.service, fabrique=self.noyau.peripherique,
                                           lancer=self._executer, acces=lambda: self.acces)
        self.acces = None
        self.service.fenetre.ouvrir()
        self.serveurs = T.demarrer_ecoutes(self.service, "127.0.0.1", 0, 0, sondage=0.05)
        self.http, self.https = (s.server_address[1] for s in self.serveurs)
        self.activer(True)

    def tearDown(self):
        self.service.pointeur.fermer("arret")
        for s in self.serveurs:
            s.shutdown()
            s.server_close()
        super().tearDown()

    def _executer(self, commande, **_kw):
        self.executes.append(commande)
        sortie = ""
        if "list-sessions" in commande:
            sortie = LISTE.replace("1000", str(__import__("os").getuid()))
        elif "show-session" in commande:
            sortie = self.session
        elif "gsettings" in commande:
            sortie = "[('xkb', 'fr+oss')]"
        return subprocess.CompletedProcess(commande, 0, stdout=sortie, stderr="")

    def activer(self, oui):
        self.chemins["reglages"].parent.mkdir(parents=True, exist_ok=True)
        self.chemins["reglages"].write_text(json.dumps({"systeme": {"telecommandeSouris": oui}}))

    def contexte_client(self):
        return ssl.create_default_context(cafile=str(self.tls.racine_crt))

    def requete(self, methode, chemin, corps=None, jeton=None, securise=True, entetes=None):
        import http.client
        if securise:
            c = http.client.HTTPSConnection("127.0.0.1", self.https, timeout=5, context=self.contexte_client())
        else:
            c = http.client.HTTPConnection("127.0.0.1", self.http, timeout=5)
        h = {"Host": f"127.0.0.1:{self.https if securise else self.http}", **(entetes or {})}
        donnees = None
        if corps is not None:
            donnees = json.dumps(corps).encode()
            h["Content-Type"] = "application/json"
        if jeton:
            h["Authorization"] = f"Bearer {jeton}"
        c.request(methode, chemin, body=donnees, headers=h)
        r = c.getresponse()
        brut = r.read()
        c.close()
        try:
            valeur = json.loads(brut)
        except ValueError:
            valeur = brut
        return r.status, {k.lower(): v for k, v in r.getheaders()}, valeur

    def appairer(self, securise=True, autoriser=True, **corps):
        """Un téléphone appairé — et, par défaut, déjà autorisé à la souris et au
        clavier, comme si on avait fait le second geste devant la TV : la plupart des
        tests d'ici portent sur une AUTRE condition, pas sur celle-ci (voir la classe
        `DroitParTelephone`, qui la teste seule). `autoriser=False` la laisse fermée."""
        self.service.fenetre.ouvrir()
        statut, _h, rep = self.requete("POST", "/api/appairer",
                                       {"code": self.service.appairage.code, "nom": "Test", **corps},
                                       securise=securise)
        self.assertEqual(statut, 200, rep)
        if securise and autoriser:
            self.service.jetons.autoriser_pointeur(rep["id"], True)
        return rep["jeton"]

    def ticket(self, jeton):
        statut, _h, rep = self.requete("POST", "/api/pointeur/session", {}, jeton=jeton)
        self.assertEqual(statut, 200, rep)
        return rep["ticket"]

    def ws(self, ticket=None, securise=True, origine=None, protocoles=None, entetes=None):
        port = self.https if securise else self.http
        brut = socket.create_connection(("127.0.0.1", port), timeout=5)
        if securise:
            brut = self.contexte_client().wrap_socket(brut, server_hostname="127.0.0.1")
        schema = "https" if securise else "http"
        client = ClientWS(brut, f"127.0.0.1:{port}", ticket=ticket,
                          origine=origine or f"{schema}://127.0.0.1:{port}", protocoles=protocoles,
                          entetes=entetes)
        self.addCleanup(client.fermer)
        return client

    def ouvrir_ws(self, jeton):
        client = self.ws(self.ticket(jeton))
        self.assertEqual(client.statut, 101, client.corps)
        self.assertEqual(client.recevoir()["t"], "pret")
        return client

    def evenements(self):
        return self.noyau.evenements()

    def rien_ecrit(self, message=None):
        self.assertEqual(self.noyau.ecrits, [], message)
        self.assertEqual(self.noyau.ioctls, [], "le périphérique n'a même pas été créé")


class SansAppairage(AvecPointeur):
    """Aucune des routes nouvelles ne s'ouvre à qui n'a pas de jeton."""

    def test_route_par_route(self):
        for securise in (True, False):
            for jeton in (None, "faux" * 10):
                self.assertEqual(self.requete("POST", "/api/pointeur/session", {}, jeton=jeton,
                                              securise=securise)[0], 401)
                self.assertEqual(self.requete("POST", "/api/commande", {"nom": "haut"}, jeton=jeton,
                                              securise=securise)[0], 401)
                self.assertEqual(self.requete("GET", "/api/pointeur", jeton=jeton, securise=securise)[0], 401)
            for ticket in (None, "x" * 43, ""):
                client = self.ws(ticket, securise=securise)
                self.assertEqual(client.statut, 401, (securise, ticket))
        self.rien_ecrit()

    def test_un_jeton_valide_ne_remplace_pas_le_ticket_sur_le_websocket(self):
        jeton = self.appairer()
        client = self.ws(None, entetes={"Authorization": f"Bearer {jeton}"})
        self.assertEqual(client.statut, 401)
        self.rien_ecrit()


class Conditions(AvecPointeur):
    """Chaque condition, seule, suffit à tout refuser — sur les trois routes."""

    def refuse_partout(self, jeton, raison, securise=True):
        statut, _h, rep = self.requete("POST", "/api/pointeur/session", {}, jeton=jeton, securise=securise)
        self.assertEqual((statut, rep.get("raison")), (403, raison))
        for nom, extra in (("haut", {}), ("ok", {}), ("retour", {}), ("texte", {"texte": "bonjour"})):
            statut, _h, rep = self.requete("POST", "/api/commande", {"nom": nom, **extra}, jeton=jeton,
                                           securise=securise)
            self.assertEqual(statut, 200)
            self.assertFalse(rep["ok"], nom)
            self.assertEqual(rep["raison"], f"pointeur-{raison}", nom)
        statut, _h, rep = self.requete("GET", "/api/etat", jeton=jeton, securise=securise)
        self.assertEqual(rep["pointeur"], {"permis": False, "raison": raison})
        self.rien_ecrit(raison)

    def test_desactive_par_defaut(self):
        self.chemins["reglages"].unlink()
        self.refuse_partout(self.appairer(), "desactive")

    def test_reglage_abime_ou_ambigu_vaut_desactive(self):
        jeton = self.appairer()
        for contenu in ('{"systeme": {"telecommandeSouris": "true"}}', '{"systeme": {"telecommandeSouris": 1}}',
                        '{"systeme": []}', "pas du json", "[]"):
            self.chemins["reglages"].write_text(contenu)
            self.refuse_partout(jeton, "desactive")

    def test_http_refuse_meme_avec_un_jeton_sur(self):
        jeton = self.appairer()
        self.refuse_partout(jeton, "connexion-non-securisee", securise=False)

    def test_websocket_en_http_refuse(self):
        jeton = self.appairer()
        ticket = self.ticket(jeton)
        client = self.ws(ticket, securise=False)
        self.assertEqual(client.statut, 403)
        self.rien_ecrit()

    def test_jeton_obtenu_en_http_refuse_meme_presente_en_https(self):
        # Un jeton qui a voyagé en clair sur le wifi a pu être lu : il garde la
        # télécommande d'avant, jamais le clavier.
        self.refuse_partout(self.appairer(securise=False), "jeton-non-sur")

    def test_jeton_obtenu_par_transfert_refuse(self):
        # Le ticket de transfert est rendu EN HTTP à qui présente le jeton http : qui a
        # lu l'un a pu demander l'autre.
        jeton_http = self.appairer(securise=False)
        _s, _h, rep = self.requete("POST", "/api/transfert", {}, jeton=jeton_http, securise=False)
        ticket = rep["url"].split("=", 1)[1]
        statut, _h, rep = self.requete("POST", "/api/appairer", {"transfert": ticket, "nom": "Pixel"})
        self.assertEqual(statut, 200)
        self.refuse_partout(rep["jeton"], "jeton-non-sur")

    def test_retaper_le_code_en_https_rend_le_jeton_sur_sans_tuer_le_jeton_http(self):
        jeton_http = self.appairer(securise=False)
        _s, _h, rep = self.requete("POST", "/api/transfert", {}, jeton=jeton_http, securise=False)
        _s, _h, rep = self.requete("POST", "/api/appairer", {"transfert": rep["url"].split("=", 1)[1]})
        jeton_https = rep["jeton"]
        statut, _h, rep = self.requete("POST", "/api/appairer", {"code": self.service.appairage.code},
                                       jeton=jeton_https)
        self.assertEqual(statut, 200)
        self.assertEqual(len(self.service.jetons.lister()), 1, "toujours une seule entrée")
        # Le jeton est sûr, mais retaper le code ne suffit plus, à lui seul, à ouvrir le
        # clavier : il faut le second geste, devant la TV, pour ce téléphone (condition
        # 4, voir DroitParTelephone). Avant ce geste, la raison affichée le dit.
        self.assertEqual(self.requete("GET", "/api/etat", jeton=rep["jeton"])[2]["pointeur"],
                         {"permis": False, "raison": "non-autorise"})
        self.service.jetons.autoriser_pointeur(rep["id"], True)
        self.assertEqual(self.requete("GET", "/api/etat", jeton=rep["jeton"])[2]["pointeur"]["permis"], True)
        self.assertEqual(self.requete("GET", "/api/etat", jeton=jeton_https)[0], 401, "l'ancien secret ne vaut plus")
        self.assertEqual(self.requete("GET", "/api/etat", jeton=jeton_http, securise=False)[0], 200,
                         "le favori http du même téléphone continue de marcher")
        self.assertEqual(self.requete("GET", "/api/etat", jeton=jeton_http)[2]["pointeur"]["raison"], "jeton-non-sur")

    def test_menu_et_kodi_gardent_leur_chemin(self):
        jeton = self.appairer()
        menu = FauxMenu(self.chemins["socket"])
        try:
            self.contexte = "menu"
            statut, _h, rep = self.requete("POST", "/api/pointeur/session", {}, jeton=jeton)
            self.assertEqual((statut, rep["raison"]), (403, "contexte"))
            statut, _h, rep = self.requete("POST", "/api/commande", {"nom": "haut"}, jeton=jeton)
            self.assertEqual(rep, {"ok": True, "cible": "menu"})
            self.assertEqual(menu.recevoir(), "haut")
            self.assertEqual(self.requete("GET", "/api/etat", jeton=jeton)[2],
                             {"ok": True, "contexte": "menu", "pointeur": {"permis": False, "raison": "contexte"}})
        finally:
            menu.fermer()
        self.rien_ecrit()

    def test_ecran_verrouille(self):
        self.session = bloc(LockedHint="yes")
        self.refuse_partout(self.appairer(), "session-verrouillee")

    def test_ecran_de_connexion(self):
        self.session = bloc(Active="no") + "\n\n" + bloc(Class="greeter")
        self.refuse_partout(self.appairer(), "session-en-arriere-plan")

    def test_uinput_inaccessible_la_page_sait_pourquoi(self):
        jeton = self.appairer()
        for raison in ("uinput-absent", "uinput-refuse"):
            self.acces = raison
            self.refuse_partout(jeton, raison)

    def test_uinput_qui_echoue_a_l_ouverture(self):
        import errno
        self.noyau.erreur_ouverture = errno.EACCES
        jeton = self.appairer()
        statut, _h, rep = self.requete("POST", "/api/commande", {"nom": "haut"}, jeton=jeton)
        self.assertEqual((rep["ok"], rep["raison"]), (False, "pointeur-uinput-refuse"))
        client = self.ws(self.ticket(jeton))
        self.assertEqual(client.statut, 403)

    def test_repli_sans_uinput_tout_le_reste_marche_comme_avant(self):
        self.acces = "uinput-absent"
        jeton = self.appairer()
        statut, _h, rep = self.requete("POST", "/api/commande", {"nom": "volume:+"}, jeton=jeton)
        self.assertTrue(rep["ok"])
        statut, _h, rep = self.requete("POST", "/api/commande", {"nom": "accueil"}, jeton=jeton)
        self.assertEqual(rep, {"ok": True, "cible": "bureau"})
        self.assertIn(["gnome-session-quit", "--logout", "--no-prompt"], self.executes)

    def test_module_absent_meme_repli(self):
        ancien, T.POINTEUR = T.POINTEUR, None
        try:
            self.refuse_partout(self.appairer(), "module-absent")
        finally:
            T.POINTEUR = ancien


class DroitParTelephone(Conditions):
    """Condition 4 : un jeton sûr ne suffit plus, il faut aussi CE téléphone autorisé
    nommément (Réglages → Télécommande). Refusé par défaut à l'appairage.

    Hérite de `Conditions` pour `refuse_partout` : c'est la même famille de tests,
    « une condition, seule, suffit à tout refuser »."""

    def test_appairage_seul_ne_donne_pas_le_clavier(self):
        self.refuse_partout(self.appairer(autoriser=False), "non-autorise")

    def test_autorisation_par_l_identifiant_l_ouvre_sans_nouvel_appairage(self):
        jeton = self.appairer(autoriser=False)
        ident = self.service.jetons.valide(jeton)
        self.assertTrue(self.service.jetons.autoriser_pointeur(ident, True))
        self.assertEqual(self.requete("GET", "/api/etat", jeton=jeton)[2]["pointeur"]["permis"], True)
        self.assertEqual(self.requete("POST", "/api/pointeur/session", {}, jeton=jeton)[0], 200)

    def test_autre_telephone_du_meme_appairage_n_est_pas_touche(self):
        jeton_a = self.appairer(nom="Pixel de A")
        jeton_b = self.appairer(autoriser=False, appareil="a" * 32, nom="Pixel de B")
        self.assertEqual(self.requete("POST", "/api/pointeur/session", {}, jeton=jeton_a)[0], 200)
        self.refuse_partout(jeton_b, "non-autorise")

    def test_lister_et_cli_voient_le_droit(self):
        jeton = self.appairer(autoriser=False)
        ident = self.service.jetons.valide(jeton)
        avant = next(t for t in self.service.jetons.lister() if t["id"] == ident)
        self.assertFalse(avant["pointeurAutorise"])
        self.service.jetons.autoriser_pointeur(ident, True)
        apres = next(t for t in self.service.jetons.lister() if t["id"] == ident)
        self.assertTrue(apres["pointeurAutorise"])


class Tickets(AvecPointeur):
    def test_usage_unique(self):
        jeton = self.appairer()
        ticket = self.ticket(jeton)
        self.assertEqual(self.ws(ticket).statut, 101)
        self.assertEqual(self.ws(ticket).statut, 401)

    def test_expire(self):
        jeton = self.appairer()
        ticket = self.ticket(jeton)
        reel = self.service.horloge
        self.service.horloge = lambda: reel() + T.DUREE_TICKET_POINTEUR_S + 1
        self.assertEqual(self.ws(ticket).statut, 401)

    def test_un_ticket_de_pointeur_n_appaire_pas_et_inversement(self):
        jeton = self.appairer()
        ticket = self.ticket(jeton)
        self.assertEqual(self.requete("POST", "/api/appairer", {"transfert": ticket})[0], 403)
        _s, _h, rep = self.requete("POST", "/api/transfert", {}, jeton=jeton)
        transfert = rep["url"].split("=", 1)[1]
        self.assertEqual(self.ws(transfert).statut, 401)
        self.rien_ecrit()

    def test_origine_etrangere_refusee(self):
        jeton = self.appairer()
        for origine in ("https://evil.example", f"http://127.0.0.1:{self.https}", "null"):
            self.assertEqual(self.ws(self.ticket(jeton), origine=origine).statut, 403, origine)
        client = self.ws(self.ticket(jeton), entetes={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(client.statut, 403)
        self.rien_ecrit()

    def test_poignee_de_main_incomplete(self):
        jeton = self.appairer()
        client = self.ws(self.ticket(jeton), entetes={"Sec-WebSocket-Version": "8"})
        self.assertEqual(client.statut, 400)
        # Sans le protocole « hub-pointeur », ce n'est pas la page.
        client = self.ws(None, protocoles=["ticket." + self.ticket(jeton)])
        self.assertEqual(client.statut, 400)

    def test_telephone_revoque_entre_ticket_et_ouverture(self):
        jeton = self.appairer()
        ticket = self.ticket(jeton)
        self.service.jetons.revoquer_tout()
        self.assertEqual(self.ws(ticket).statut, 401)


class Gestes(AvecPointeur):
    def setUp(self):
        super().setUp()
        self.jeton = self.appairer()
        self.client = self.ouvrir_ws(self.jeton)
        self.noyau.ecrits.clear()

    def synchroniser(self):
        """Un aller-retour : tout ce qui précède a été traité par le service."""
        self.client.envoyer({"t": "p", "n": 1})
        recu = self.client.recevoir()
        while recu and recu.get("t") == "r":   # comptes rendus de textes, déjà vérifiés ailleurs
            recu = self.client.recevoir()
        self.assertEqual(recu, {"t": "p", "n": 1})

    def test_souris(self):
        self.client.envoyer({"t": "m", "x": 12, "y": -3})
        self.client.envoyer({"t": "c", "b": "gauche"})
        self.client.envoyer({"t": "c", "b": "droite"})
        self.client.envoyer({"t": "d", "y": 120})
        self.synchroniser()
        self.assertEqual(self.evenements(), [
            [(P.EV_REL, P.REL_X, 12), (P.EV_REL, P.REL_Y, -3), SYN],
            [(P.EV_KEY, P.BTN_LEFT, 1), SYN], [(P.EV_KEY, P.BTN_LEFT, 0), SYN],
            [(P.EV_KEY, P.BTN_RIGHT, 1), SYN], [(P.EV_KEY, P.BTN_RIGHT, 0), SYN],
            [(P.EV_REL, P.REL_WHEEL_HI_RES, 120), (P.EV_REL, P.REL_WHEEL, 1), SYN]])

    def test_touches_nommees(self):
        for nom in ("haut", "bas", "gauche", "droite", "ok", "retour", "effacer", "lecture"):
            self.client.envoyer({"t": "k", "n": nom})
        self.synchroniser()
        appuis = [lot[0][1] for lot in self.evenements() if lot[0][2] == 1]
        self.assertEqual(appuis, [P.KEY_UP, P.KEY_DOWN, P.KEY_LEFT, P.KEY_RIGHT, P.KEY_ENTER, P.KEY_ESC,
                                  P.KEY_BACKSPACE, P.KEY_PLAYPAUSE])

    def test_texte_en_azerty_et_compte_rendu(self):
        self.client.envoyer({"t": "x", "s": "aé@ 😀"})
        rep = self.client.recevoir()
        self.assertEqual(rep, {"t": "r", "ok": True, "approximations": [], "ignores": ["😀"]})
        appuis = [lot[0][1] for lot in self.evenements() if lot[0][2] == 1]
        self.assertEqual(appuis, [P.KEY_Q, P.KEY_2, P.KEY_RIGHTALT, P.KEY_0, P.KEY_SPACE])

    def test_disposition_non_couverte_le_texte_est_refuse_la_souris_reste(self):
        self.client.fermer()
        self.attendre_fermeture()
        ancien = self._executer
        self.service.pointeur.lancer = lambda c, **k: (
            subprocess.CompletedProcess(c, 0, stdout="[('xkb', 'de')]", stderr="") if "gsettings" in c else ancien(c))
        client = self.ouvrir_ws(self.jeton)
        self.noyau.ecrits.clear()
        client.envoyer({"t": "x", "s": "abc"})
        self.assertEqual(client.recevoir(), {"t": "r", "ok": False, "raison": "disposition-non-couverte"})
        client.envoyer({"t": "m", "x": 1, "y": 1})
        client.envoyer({"t": "p", "n": 2})
        client.recevoir()
        self.assertEqual(self.evenements(), [[(P.EV_REL, P.REL_X, 1), (P.EV_REL, P.REL_Y, 1), SYN]])

    def attendre_fermeture(self, delai=3):
        fin = time.time() + delai
        while self.service.pointeur.ouvert and time.time() < fin:
            time.sleep(0.02)
        self.assertFalse(self.service.pointeur.ouvert, "le périphérique devait disparaître")

    def test_rien_hors_de_la_liste_fermee(self):
        # Le seuil de fermeture a son propre test : ici on veut voir CHAQUE message refusé.
        seuil, T.ERREURS_POINTEUR_MAX = T.ERREURS_POINTEUR_MAX, 100
        self.addCleanup(setattr, T, "ERREURS_POINTEUR_MAX", seuil)
        for message in ({"t": "k", "n": "ctrl+alt+t"}, {"t": "k", "n": "super"}, {"t": "k", "code": 29},
                        {"t": "k", "n": ["haut"]}, {"t": "c", "b": "milieu"}, {"t": "exec", "s": "xterm"},
                        {"t": "m", "x": "12", "y": 1}, {"t": "m", "x": 1.5, "y": 1}, {"t": "m", "x": True, "y": 1},
                        {"t": "x", "s": 3}, {"t": "x"}):
            self.client.envoyer(message)
        self.synchroniser()
        self.assertEqual(self.noyau.ecrits, [])

    def test_trop_de_messages_invalides_ferme(self):
        for _ in range(T.ERREURS_POINTEUR_MAX + 1):
            self.client.envoyer({"t": "exec"})
        self.assertIsNone(self.client.recevoir())
        self.assertEqual(self.client.code_fermeture, 1008)

    def test_deplacement_borne(self):
        self.client.envoyer({"t": "m", "x": 10 ** 9, "y": -(10 ** 9)})
        self.synchroniser()
        self.assertEqual(self.evenements(), [[(P.EV_REL, P.REL_X, T.DEPLACEMENT_MAX),
                                              (P.EV_REL, P.REL_Y, -T.DEPLACEMENT_MAX), SYN]])

    def test_debit_des_mouvements_borne(self):
        for _ in range(T.MOUVEMENTS_RESERVE * 3):
            self.client.envoyer({"t": "m", "x": 1, "y": 0})
        self.synchroniser()
        self.assertLessEqual(len(self.noyau.ecrits), T.MOUVEMENTS_RESERVE + T.MOUVEMENTS_PAR_S)
        self.assertGreaterEqual(len(self.noyau.ecrits), T.MOUVEMENTS_RESERVE)

    def test_debit_des_frappes_borne(self):
        for _ in range(T.FRAPPES_RESERVE * 2):
            self.client.envoyer({"t": "k", "n": "bas"})
        self.synchroniser()
        appuis = [lot for lot in self.evenements() if lot[0] == (P.EV_KEY, P.KEY_DOWN, 1)]
        self.assertLessEqual(len(appuis), T.FRAPPES_RESERVE + T.FRAPPES_PAR_S)
        # Et le même seau sert à la route HTTP : pas de porte de derrière.
        _s, _h, rep = self.requete("POST", "/api/commande", {"nom": "bas"}, jeton=self.jeton)
        self.assertEqual((rep["ok"], rep["raison"]), (False, "pointeur-debit"))

    def test_texte_trop_long_refuse(self):
        self.client.envoyer({"t": "x", "s": "a" * (T.TAILLE_MAX_TEXTE + 1)})
        self.assertEqual(self.client.recevoir(), {"t": "r", "ok": False, "raison": "texte-invalide"})
        self.assertEqual(self.noyau.ecrits, [])

    def test_trame_trop_grosse_ferme(self):
        self.client.envoyer_brut(b"x" * (T.TRAME_POINTEUR_MAX + 1))
        self.assertIsNone(self.client.recevoir())
        self.assertEqual(self.client.code_fermeture, 1009)

    def test_commande_http_passe_par_le_clavier(self):
        for nom, code in (("haut", P.KEY_UP), ("ok", P.KEY_ENTER), ("retour", P.KEY_ESC)):
            self.noyau.ecrits.clear()
            _s, _h, rep = self.requete("POST", "/api/commande", {"nom": nom}, jeton=self.jeton)
            self.assertEqual(rep, {"ok": True, "cible": "bureau"})
            self.assertEqual(self.evenements(), [[(P.EV_KEY, code, 1), SYN], [(P.EV_KEY, code, 0), SYN]])
        self.noyau.ecrits.clear()
        _s, _h, rep = self.requete("POST", "/api/commande", {"nom": "texte", "texte": "École"}, jeton=self.jeton)
        self.assertEqual(rep, {"ok": True, "cible": "bureau", "approximations": [], "ignores": []})
        self.assertEqual(self.evenements()[0][0], (P.EV_KEY, P.KEY_LEFTSHIFT, 1))

    def test_les_commandes_du_menu_ne_deviennent_pas_des_touches(self):
        for nom in ("tv", "reglages", "eteindre", "theme:clair", "web:netflix"):
            _s, _h, rep = self.requete("POST", "/api/commande", {"nom": nom}, jeton=self.jeton)
            self.assertFalse(rep["ok"], nom)
        self.assertEqual(self.noyau.ecrits, [])

    def test_fermeture_de_la_page_detruit_le_peripherique(self):
        self.client.fermer()
        self.attendre_fermeture()
        self.assertEqual(self.noyau.ioctls[-1][0], P.UI_DEV_DESTROY)


class EnCoursDeSession(AvecPointeur):
    """Ce qui était permis à l'ouverture peut cesser de l'être : la session tombe."""

    def setUp(self):
        super().setUp()
        self.service.pointeur.PERIODE_GARDIEN_S = 0.05
        self.service.pointeur.DUREE_GARDE_S = 0.05
        self.jeton = self.appairer()
        self.client = self.ouvrir_ws(self.jeton)

    def coupee(self, raison):
        fin = self.client.recevoir(delai=5)
        self.assertEqual(fin, {"t": "fin", "raison": raison})
        self.assertIsNone(self.client.recevoir(delai=5))
        self.assertFalse(self.service.pointeur.ouvert)
        self.assertEqual(self.noyau.ioctls[-1][0], P.UI_DEV_DESTROY)
        self.noyau.ecrits.clear()
        _s, _h, rep = self.requete("POST", "/api/commande", {"nom": "haut"}, jeton=self.jeton)
        self.assertFalse(rep.get("ok"))
        self.assertEqual(self.noyau.ecrits, [])

    def test_verrouillage(self):
        self.session = bloc(LockedHint="yes")
        self.coupee("session-verrouillee")

    def test_passage_a_l_ecran_de_connexion(self):
        self.session = bloc(Active="no")
        self.coupee("session-en-arriere-plan")

    def test_interrupteur_eteint(self):
        self.activer(False)
        self.coupee("desactive")

    def test_retour_au_menu(self):
        menu = FauxMenu(self.chemins["socket"])
        self.addCleanup(menu.fermer)
        self.contexte = "menu"
        fin = self.client.recevoir(delai=5)
        self.assertEqual(fin, {"t": "fin", "raison": "contexte"})

    def test_telephone_retire_depuis_la_tv(self):
        ident = self.service.jetons.lister()[0]["id"]
        T.Jetons(self.chemins["jetons"]).revoquer(ident)
        fin = self.client.recevoir(delai=5)
        self.assertEqual(fin, {"t": "fin", "raison": "revoque"})
        self.assertIsNone(self.client.recevoir(delai=5))

    def test_droit_a_la_souris_retire_depuis_la_tv(self):
        """Comme un retrait complet, mais le téléphone garde sa télécommande : seul le
        droit à la souris et au clavier part, `--interdire-souris` plutôt que
        `--revoquer`."""
        ident = self.service.jetons.lister()[0]["id"]
        T.Jetons(self.chemins["jetons"]).autoriser_pointeur(ident, False)
        self.coupee("non-autorise")
        # La télécommande, elle, marche toujours : ce n'est pas une révocation.
        self.assertIn(ident, self.service.jetons.identifiants())

    def test_un_autre_telephone_garde_sa_session(self):
        autre = self.ouvrir_ws(self.appairer())
        T.Jetons(self.chemins["jetons"]).revoquer(self.service.jetons.valide(self.jeton))
        self.assertEqual(self.client.recevoir(delai=5), {"t": "fin", "raison": "revoque"})
        autre.envoyer({"t": "p", "n": 7})
        self.assertEqual(autre.recevoir(delai=5), {"t": "p", "n": 7})
        self.assertTrue(self.service.pointeur.ouvert)

    def test_silence_prolonge_ferme(self):
        self.service.pointeur.DELAI_MUET_S = 0.3
        client = self.ouvrir_ws(self.appairer())
        self.assertEqual(client.recevoir(delai=5), {"t": "fin", "raison": "muet"})


class AccueilPartout(AvecPointeur):
    def test_accueil_ferme_le_service_web_comme_la_voix(self):
        self.contexte = "web"
        jeton = self.appairer(securise=False)
        _s, _h, rep = self.requete("POST", "/api/commande", {"nom": "accueil"}, jeton=jeton, securise=False)
        self.assertEqual(rep, {"ok": True, "cible": "web"})
        self.assertTrue(any(c[-1] == "--fermer" and c[0].endswith("hub-web") for c in self.executes), self.executes)
        self.assertEqual(self.requete("GET", "/api/etat", jeton=jeton, securise=False)[2]["contexte"], "web")
        self.rien_ecrit()

    def test_dans_le_web_les_fleches_sont_des_touches(self):
        self.contexte = "web"
        jeton = self.appairer()
        _s, _h, rep = self.requete("POST", "/api/commande", {"nom": "droite"}, jeton=jeton)
        self.assertEqual(rep, {"ok": True, "cible": "web"})
        self.assertEqual(self.evenements()[0], [(P.EV_KEY, P.KEY_RIGHT, 1), SYN])


class EnTetes(AvecPointeur):
    def test_csp_autorise_le_websocket_de_cette_origine_seulement(self):
        _s, h, _c = self.requete("GET", "/")
        self.assertIn(f"connect-src 'self' wss://127.0.0.1:{self.https}", h["content-security-policy"])
        _s, h, _c = self.requete("GET", "/", securise=False)
        self.assertNotIn("wss:", h["content-security-policy"])
        self.assertNotIn("ws:", h["content-security-policy"].replace("wss:", ""))


class Journal(AvecPointeur):
    def test_ouverture_et_fermeture_journalisees_sans_le_texte_tape(self):
        jeton = self.appairer()
        with self.assertLogs("hub-telecommande", level="INFO") as journal:
            client = self.ouvrir_ws(jeton)
            client.envoyer({"t": "x", "s": "motdepasse"})
            client.recevoir()
            client.fermer()
            fin = time.time() + 3
            while self.service.pointeur.ouvert and time.time() < fin:
                time.sleep(0.02)
        texte = "\n".join(journal.output)
        self.assertIn("souris et clavier : session ouverte", texte)
        self.assertIn("session fermée", texte)
        self.assertNotIn("motdepasse", texte, "ce qui est tapé peut être un mot de passe")


if __name__ == "__main__":
    unittest.main()
