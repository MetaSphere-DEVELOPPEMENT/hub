#!/usr/bin/env python3
"""Tests de la télécommande téléphone, sans réseau externe.

Lancer : python3 -m unittest installer/telecommande/test_telecommande.py

POURQUOI CES TESTS EXISTENT. Une télécommande sur le réseau local, c'est une porte :
tout ce qui la garde fermée (code, jeton, limite d'essais, liste blanche, Host) est
vérifié ici par de vraies requêtes HTTP sur la boucle locale, pas en appelant les
fonctions de l'intérieur. Le serveur d'essai écoute sur 127.0.0.1 et un port choisi
par le noyau : rien ne sort de la machine.

Le QR code est décodé par un décodeur écrit ici (lecture des modules, masque, et
vérification de la correction d'erreurs Reed-Solomon recalculée indépendamment de
la bibliothèque), puis par zbarimg ou zxing-cpp s'ils sont présents sur l'hôte.
"""

import http.client
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import hub_telecommande as T  # noqa: E402


class Horloge:
    """Temps maîtrisé : la limite d'essais et l'expiration du code se testent sans attendre."""

    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class AvecDossier(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self._tmp.name)
        self.chemins = {
            "etat": self.dossier / "run" / "hub" / "telecommande.json",
            "socket": self.dossier / "run" / "hub" / "menu.sock",
            "jetons": self.dossier / "config" / "hub" / "telecommande-jetons.json",
            "photos": self.dossier / "Images" / "HUB" / "profils",
        }
        self.horloge = Horloge()

    def tearDown(self):
        self._tmp.cleanup()


# ── Appairage (logique) ─────────────────────────────────────────────────────
class Appairage(AvecDossier):
    def nouveau(self, **kw):
        changements = []
        a = T.Appairage(horloge=self.horloge, au_changement=lambda: changements.append(a.code), **kw)
        return a, changements

    def test_code_a_six_chiffres(self):
        a, _ = self.nouveau()
        self.assertRegex(a.code, r"^\d{6}$")
        self.assertGreater(a.expire_ms, self.horloge() * 1000)

    def test_bon_code_accepte_puis_renouvele(self):
        a, changements = self.nouveau()
        ancien = a.code
        self.assertEqual(a.essayer("10.0.0.2", ancien), T.OK)
        self.assertNotEqual(a.code, ancien, "un code servi une fois ne doit plus rien ouvrir")
        self.assertEqual(a.essayer("10.0.0.3", ancien), T.MAUVAIS)
        self.assertTrue(changements)

    def test_mauvais_code_refuse(self):
        a, _ = self.nouveau()
        faux = "000000" if a.code != "000000" else "111111"
        self.assertEqual(a.essayer("10.0.0.2", faux), T.MAUVAIS)
        self.assertEqual(a.essayer("10.0.0.2", "abc"), T.MAUVAIS)
        self.assertEqual(a.essayer("10.0.0.2", None), T.MAUVAIS)

    def test_cinq_essais_par_minute_par_ip(self):
        a, _ = self.nouveau()
        faux = "000000" if a.code != "000000" else "111111"
        for _ in range(5):
            self.assertEqual(a.essayer("10.0.0.2", faux), T.MAUVAIS)
        # Le sixième est refusé même avec le bon code : sinon la limite ne limite rien.
        self.assertEqual(a.essayer("10.0.0.2", a.code), T.TROP)
        # Une autre IP n'est pas punie pour la première.
        self.assertEqual(a.essayer("10.0.0.9", faux), T.MAUVAIS)
        self.horloge.t += 61
        self.assertEqual(a.essayer("10.0.0.2", a.code), T.OK)

    def test_code_expire_est_renouvele(self):
        a, changements = self.nouveau()
        ancien = a.code
        self.horloge.t += T.DUREE_CODE_S + 1
        a.verifier_expiration()
        self.assertNotEqual((a.code, len(changements)), (ancien, 0))
        self.assertEqual(a.essayer("10.0.0.2", ancien) if a.code != ancien else T.MAUVAIS, T.MAUVAIS)

    def test_trop_d_echecs_toutes_ip_confondues_renouvelle_le_code(self):
        # Contre une attaque répartie sur plusieurs adresses du réseau local.
        a, _ = self.nouveau()
        ancien = a.code
        for i in range(T.ECHECS_AVANT_RENOUVELLEMENT):
            a.essayer(f"10.0.1.{i}", "000000" if ancien != "000000" else "111111")
        self.assertNotEqual(a.code, ancien)


# ── Jetons ──────────────────────────────────────────────────────────────────
class Jetons(AvecDossier):
    def test_creation_fichier_0600_sans_le_jeton_en_clair(self):
        j = T.Jetons(self.chemins["jetons"], horloge=self.horloge)
        ident, jeton = j.creer("Pixel")
        self.assertGreaterEqual(len(jeton), 40)
        mode = stat.S_IMODE(os.stat(self.chemins["jetons"]).st_mode)
        self.assertEqual(mode, 0o600)
        contenu = self.chemins["jetons"].read_text()
        self.assertNotIn(jeton, contenu)
        self.assertEqual(j.valide(jeton), ident)
        self.assertIsNone(j.valide("n'importe quoi"))
        self.assertIsNone(j.valide(""))

    def test_revocation_vue_par_le_service_en_cours(self):
        service = T.Jetons(self.chemins["jetons"], horloge=self.horloge)
        ident, jeton = service.creer("Pixel")
        _autre, jeton2 = service.creer("iPhone")
        # La révocation passe par une autre instance (la ligne de commande), comme en vrai.
        ligne_de_commande = T.Jetons(self.chemins["jetons"], horloge=self.horloge)
        self.assertTrue(ligne_de_commande.revoquer(ident))
        self.assertIsNone(service.valide(jeton))
        self.assertIsNotNone(service.valide(jeton2))
        self.assertEqual(ligne_de_commande.revoquer_tout(), 1)
        self.assertIsNone(service.valide(jeton2))

    def test_fichier_abime_ne_valide_rien(self):
        self.chemins["jetons"].parent.mkdir(parents=True)
        self.chemins["jetons"].write_text("{pas du json")
        j = T.Jetons(self.chemins["jetons"], horloge=self.horloge)
        self.assertIsNone(j.valide("x"))
        self.assertEqual(j.lister(), [])


# ── Serveur HTTP réel sur la boucle locale ──────────────────────────────────
class FauxMenu:
    """Le socket datagramme du menu, tel que hub-menu.py le crée."""

    def __init__(self, chemin):
        Path(chemin).parent.mkdir(parents=True, exist_ok=True)
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.s.bind(str(chemin))
        self.s.settimeout(2)

    def recevoir(self):
        return self.s.recv(4096).decode()

    def fermer(self):
        self.s.close()


class AvecServeur(AvecDossier):
    def setUp(self):
        super().setUp()
        self.executes = []
        self.processus = set()
        routeur = T.Routeur(
            self.chemins["socket"],
            executer=self._executer,
            processus=lambda noms: [1] if noms & self.processus else [],
            kodi_port=self._port_libre(),
            kodi_http=None,
        )
        self.service = T.Service(self.chemins, routeur=routeur, horloge=self.horloge)
        self.serveur = T.creer_serveur(self.service, "127.0.0.1", 0)
        self.port = self.serveur.server_address[1]
        # Sondage court : shutdown() attend la fin du tour de boucle en cours.
        self.fil = threading.Thread(target=self.serveur.serve_forever, args=(0.05,), daemon=True)
        self.fil.start()

    def tearDown(self):
        self.serveur.shutdown()
        self.serveur.server_close()
        super().tearDown()

    @staticmethod
    def _port_libre():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _executer(self, commande, **_kw):
        self.executes.append(commande)
        sortie = "Volume: 0.45\n" if "get-volume" in commande else ""
        return subprocess.CompletedProcess(commande, 0, stdout=sortie, stderr="")

    def requete(self, methode, chemin, corps=None, jeton=None, entetes=None, brut=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(entetes or {})
        donnees = brut
        if corps is not None:
            donnees = json.dumps(corps).encode()
            h.setdefault("Content-Type", "application/json")
        if jeton:
            h["Authorization"] = f"Bearer {jeton}"
        c.request(methode, chemin, body=donnees, headers=h)
        r = c.getresponse()
        texte = r.read()
        c.close()
        try:
            valeur = json.loads(texte)
        except ValueError:
            valeur = texte
        return r.status, dict((k.lower(), v) for k, v in r.getheaders()), valeur

    def appairer(self):
        statut, _h, rep = self.requete("POST", "/api/appairer",
                                       {"code": self.service.appairage.code, "nom": "Test"})
        self.assertEqual(statut, 200, rep)
        return rep["jeton"]


class Page(AvecServeur):
    def test_page_servie_avec_csp_stricte(self):
        statut, h, corps = self.requete("GET", "/")
        self.assertEqual(statut, 200)
        self.assertTrue(h["content-type"].startswith("text/html"))
        csp = h["content-security-policy"]
        self.assertIn("default-src 'none'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("unsafe-eval", csp)
        # Chaque bloc inline doit être autorisé par son empreinte, sinon le navigateur
        # du téléphone bloquerait la page sans rien dire.
        html = corps.decode()
        for balise in ("script", "style"):
            blocs = re.findall(rf"<{balise}>(.*?)</{balise}>", html, re.S)
            self.assertTrue(blocs, balise)
            for bloc in blocs:
                self.assertIn(T.empreinte_csp(bloc), csp)
        self.assertNotRegex(html, r"<(script|link)[^>]+(src|href)=\"?https?:", "aucun CDN")
        balisage = re.sub(r"<!--.*?-->", "", html, flags=re.S)
        self.assertNotIn(" style=\"", balisage, "un attribut style serait bloqué par la CSP")
        self.assertNotRegex(balisage, r"<[^>]+\son[a-z]+=", "un gestionnaire inline serait bloqué")
        self.assertEqual(h["x-content-type-options"], "nosniff")
        self.assertEqual(h["x-frame-options"], "DENY")
        self.assertEqual(h["referrer-policy"], "no-referrer")
        self.assertNotIn("access-control-allow-origin", h)

    def test_aucun_autre_chemin_servi(self):
        for chemin in ("/page.html", "/hub_telecommande.py", "/../hub_telecommande.py",
                       "/%2e%2e/hub_telecommande.py", "/api", "/api/jetons", "//etc/passwd"):
            statut, h, _ = self.requete("GET", chemin)
            self.assertEqual(statut, 404, chemin)
            self.assertIn("content-security-policy", h)

    def test_host_etranger_refuse(self):
        # Rebinding DNS : une page d'Internet qui ferait pointer son nom sur le HUB.
        statut, _h, _ = self.requete("GET", "/", entetes={"Host": "attaquant.example:8790"})
        self.assertEqual(statut, 421)

    def test_options_sans_cors(self):
        statut, h, _ = self.requete("OPTIONS", "/api/commande",
                                    entetes={"Origin": "http://ailleurs.example",
                                             "Access-Control-Request-Method": "POST"})
        self.assertNotIn("access-control-allow-origin", h)
        self.assertGreaterEqual(statut, 400)


class AppairageHTTP(AvecServeur):
    def test_bon_code_delivre_un_jeton_et_renouvelle_le_code(self):
        ancien = self.service.appairage.code
        jeton = self.appairer()
        self.assertTrue(jeton)
        self.assertNotEqual(self.service.appairage.code, ancien)
        statut, _h, _ = self.requete("POST", "/api/appairer", {"code": ancien})
        self.assertEqual(statut, 403)
        self.assertEqual(len(self.service.jetons.lister()), 1)

    def test_mauvais_code(self):
        faux = "000000" if self.service.appairage.code != "000000" else "111111"
        statut, _h, rep = self.requete("POST", "/api/appairer", {"code": faux})
        self.assertEqual(statut, 403)
        self.assertNotIn("jeton", rep)

    def test_limitation_des_essais(self):
        faux = "000000" if self.service.appairage.code != "000000" else "111111"
        for _ in range(5):
            self.assertEqual(self.requete("POST", "/api/appairer", {"code": faux})[0], 403)
        statut, h, _ = self.requete("POST", "/api/appairer", {"code": self.service.appairage.code})
        self.assertEqual(statut, 429)
        self.assertIn("retry-after", h)

    def test_type_de_contenu_exige(self):
        # Un formulaire d'une autre page (text/plain, sans prévol CORS) ne passe pas.
        statut, _h, _ = self.requete("POST", "/api/appairer",
                                     brut=json.dumps({"code": self.service.appairage.code}).encode(),
                                     entetes={"Content-Type": "text/plain"})
        self.assertEqual(statut, 415)

    def test_corps_trop_gros(self):
        statut, _h, _ = self.requete("POST", "/api/appairer", brut=b"{" + b" " * 10_000 + b"}",
                                     entetes={"Content-Type": "application/json"})
        self.assertEqual(statut, 413)

    def test_fichier_d_etat_pour_la_tv(self):
        etat = json.loads(self.chemins["etat"].read_text())
        self.assertEqual(etat["url"], f"http://127.0.0.1:{self.port}/")
        self.assertEqual(etat["code"], self.service.appairage.code)
        self.assertGreater(etat["expire"], self.horloge() * 1000)
        self.assertEqual(stat.S_IMODE(os.stat(self.chemins["etat"]).st_mode), 0o600)
        self.appairer()
        etat2 = json.loads(self.chemins["etat"].read_text())
        self.assertEqual(etat2["code"], self.service.appairage.code)
        self.assertNotEqual(etat2["code"], etat["code"])
        self.assertEqual(etat2["telephones"], 1)


class Commandes(AvecServeur):
    def test_jeton_requis(self):
        self.assertEqual(self.requete("POST", "/api/commande", {"nom": "ok"})[0], 401)
        self.assertEqual(self.requete("POST", "/api/commande", {"nom": "ok"}, jeton="faux")[0], 401)
        self.assertEqual(self.requete("GET", "/api/etat")[0], 401)

    def test_jeton_revoque_refuse(self):
        jeton = self.appairer()
        ident = self.service.jetons.lister()[0]["id"]
        T.Jetons(self.chemins["jetons"], horloge=self.horloge).revoquer(ident)
        self.assertEqual(self.requete("POST", "/api/commande", {"nom": "ok"}, jeton=jeton)[0], 401)

    def test_oublier_ce_telephone_revoque_son_jeton(self):
        jeton = self.appairer()
        statut, _h, rep = self.requete("POST", "/api/oublier", {}, jeton=jeton)
        self.assertEqual((statut, rep["ok"]), (200, True))
        self.assertEqual(self.requete("GET", "/api/etat", jeton=jeton)[0], 401)
        self.assertEqual(self.service.jetons.lister(), [])

    def test_commandes_hors_liste_refusees(self):
        jeton = self.appairer()
        menu = FauxMenu(self.chemins["socket"])
        try:
            for nom in ("rm -rf", "voix:eveil", "OK", "tv\n", "theme:rose", "volume:100",
                        "../menu", "", None, 3, ["ok"]):
                statut, _h, _ = self.requete("POST", "/api/commande", {"nom": nom}, jeton=jeton)
                self.assertEqual(statut, 400, repr(nom))
            menu.s.settimeout(0.2)
            with self.assertRaises(socket.timeout):
                menu.recevoir()
        finally:
            menu.fermer()

    def test_routage_vers_le_menu(self):
        jeton = self.appairer()
        menu = FauxMenu(self.chemins["socket"])
        try:
            for nom in ("gauche", "ok", "theme:sombre", "tv"):
                statut, _h, rep = self.requete("POST", "/api/commande", {"nom": nom}, jeton=jeton)
                self.assertEqual((statut, rep["cible"]), (200, "menu"))
                self.assertEqual(menu.recevoir(), nom)
            # Accueil n'existe pas dans le protocole du menu : il y devient « retour ».
            self.requete("POST", "/api/commande", {"nom": "accueil"}, jeton=jeton)
            self.assertEqual(menu.recevoir(), "retour")
        finally:
            menu.fermer()

    def test_menu_ferme_rien_d_ouvert_commande_ignoree(self):
        jeton = self.appairer()
        statut, _h, rep = self.requete("POST", "/api/commande", {"nom": "tv"}, jeton=jeton)
        self.assertEqual(statut, 200)
        self.assertFalse(rep["ok"])
        self.assertIsNone(rep["cible"])

    def test_eteindre_jamais_hors_menu(self):
        jeton = self.appairer()
        self.processus = {"gnome-shell", "kodi"}
        _s, _h, rep = self.requete("POST", "/api/commande", {"nom": "eteindre"}, jeton=jeton)
        self.assertFalse(rep["ok"])
        self.assertEqual(self.executes, [])

    def test_volume(self):
        jeton = self.appairer()
        statut, _h, rep = self.requete("POST", "/api/commande", {"nom": "volume:+"}, jeton=jeton)
        self.assertEqual((statut, rep["cible"], rep["volume"]), (200, "volume", 45))
        self.assertIn(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+"], self.executes)
        self.requete("POST", "/api/commande", {"nom": "volume:-"}, jeton=jeton)
        self.assertIn(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%-"], self.executes)

    def test_bureau_accueil_ferme_la_session(self):
        jeton = self.appairer()
        self.processus = {"gnome-shell"}
        _s, _h, rep = self.requete("POST", "/api/commande", {"nom": "accueil"}, jeton=jeton)
        self.assertEqual(rep["cible"], "bureau")
        self.assertIn(["gnome-session-quit", "--logout", "--no-prompt"], self.executes)
        # Un « gauche » sur le bureau n'a pas de destinataire : rien n'est exécuté.
        self.executes.clear()
        _s, _h, rep = self.requete("POST", "/api/commande", {"nom": "gauche"}, jeton=jeton)
        self.assertFalse(rep["ok"])
        self.assertEqual(self.executes, [])

    def test_etat(self):
        jeton = self.appairer()
        statut, _h, rep = self.requete("GET", "/api/etat", jeton=jeton)
        self.assertEqual(statut, 200)
        self.assertEqual(rep["contexte"], None)


JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x42" * 500 + b"\xff\xd9"


class PhotoProfil(AvecServeur):
    def envoyer(self, octets, jeton=None, type_contenu="image/jpeg"):
        return self.requete("POST", "/photo-profil", brut=octets, jeton=jeton,
                            entetes={"Content-Type": type_contenu})

    def photos(self):
        d = self.chemins["photos"]
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []

    def test_jeton_manquant(self):
        self.assertEqual(self.envoyer(JPEG)[0], 401)
        self.assertEqual(self.envoyer(JPEG, jeton="faux")[0], 401)
        self.assertEqual(self.photos(), [])

    def test_png_ou_texte_refuses(self):
        jeton = self.appairer()
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        for octets, type_contenu in ((png, "image/jpeg"), (b"bonjour", "image/jpeg"),
                                     (b"", "image/jpeg"), (JPEG, "image/png"),
                                     (JPEG, "text/plain")):
            statut, _h, _ = self.envoyer(octets, jeton, type_contenu)
            self.assertIn(statut, (400, 415), (octets[:8], type_contenu))
        self.assertEqual(self.photos(), [])

    def test_trop_gros(self):
        jeton = self.appairer()
        gros = JPEG[:4] + b"\x00" * (T.TAILLE_MAX_PHOTO + 1)
        statut, _h, _ = self.envoyer(gros, jeton)
        self.assertEqual(statut, 413)
        self.assertEqual(self.photos(), [])

    def test_jpeg_ecrit_et_menu_prevenu(self):
        jeton = self.appairer()
        menu = FauxMenu(self.chemins["socket"])
        try:
            statut, _h, rep = self.envoyer(JPEG, jeton)
            self.assertEqual(statut, 200, rep)
            self.assertTrue(rep["ok"])
            self.assertRegex(rep["fichier"], r"^telephone-\d{8}-\d{6}\.jpg$")
            self.assertEqual(self.photos(), [rep["fichier"]])
            self.assertEqual((self.chemins["photos"] / rep["fichier"]).read_bytes(), JPEG)
            self.assertEqual(menu.recevoir(), "avatars")
            # Même seconde : le serveur n'écrase pas la photo précédente.
            statut, _h, rep2 = self.envoyer(JPEG, jeton)
            self.assertEqual(statut, 200)
            self.assertNotEqual(rep2["fichier"], rep["fichier"])
            self.assertEqual(len(self.photos()), 2)
        finally:
            menu.fermer()

    def test_sans_menu_la_photo_est_quand_meme_ecrite(self):
        jeton = self.appairer()
        statut, _h, rep = self.envoyer(JPEG, jeton)
        self.assertEqual(statut, 200)
        self.assertEqual(self.photos(), [rep["fichier"]])


class Protocole(unittest.TestCase):
    def test_memes_noms_que_le_menu(self):
        import ast
        source = (ICI.parent / "hub-menu.py").read_text(encoding="utf-8")
        for noeud in ast.walk(ast.parse(source)):
            if isinstance(noeud, ast.Assign) and any(getattr(c, "id", None) == "COMMANDES" for c in noeud.targets):
                self.assertEqual(set(ast.literal_eval(noeud.value)), set(T.COMMANDES_MENU))
                return
        self.fail("COMMANDES introuvable dans hub-menu.py")


class FauxKodi:
    """Le JSON-RPC TCP de Kodi (port 9090) : un objet JSON par requête, réponse par id."""

    def __init__(self):
        self.recues = []
        self.s = socket.socket()
        self.s.bind(("127.0.0.1", 0))
        self.s.listen()
        self.port = self.s.getsockname()[1]
        threading.Thread(target=self._boucle, daemon=True).start()

    def _boucle(self):
        while True:
            try:
                c, _ = self.s.accept()
            except OSError:
                return
            with c:
                donnees = c.recv(65536)
                requete = json.loads(donnees)
                self.recues.append(requete)
                # Kodi pousse aussi des notifications : le client doit les ignorer.
                c.sendall(b'{"jsonrpc":"2.0","method":"Input.OnInputRequested","params":{}}')
                c.sendall(json.dumps({"jsonrpc": "2.0", "id": requete["id"], "result": "OK"}).encode())

    def fermer(self):
        self.s.close()


class RoutageKodi(AvecDossier):
    def setUp(self):
        super().setUp()
        self.kodi = FauxKodi()
        self.routeur = T.Routeur(self.chemins["socket"], executer=lambda *a, **k: None,
                                 processus=lambda noms: [1] if "kodi" in noms else [],
                                 kodi_port=self.kodi.port, kodi_http=None)

    def tearDown(self):
        self.kodi.fermer()
        super().tearDown()

    def test_navigation_et_texte_vers_kodi(self):
        attendu = {"gauche": "Input.Left", "droite": "Input.Right", "haut": "Input.Up",
                   "bas": "Input.Down", "ok": "Input.Select", "retour": "Input.Back"}
        for nom, methode in attendu.items():
            r = self.routeur.executer(nom)
            self.assertEqual((r["ok"], r["cible"]), (True, "kodi"), nom)
            self.assertEqual(self.kodi.recues[-1]["method"], methode)
        r = self.routeur.executer("texte", "Dune")
        self.assertTrue(r["ok"])
        self.assertEqual(self.kodi.recues[-1]["method"], "Input.SendText")
        self.assertEqual(self.kodi.recues[-1]["params"], {"text": "Dune", "done": True})

    def test_accueil_quitte_kodi(self):
        r = self.routeur.executer("accueil")
        self.assertEqual(r["cible"], "kodi")
        self.assertEqual(self.kodi.recues[-1]["method"], "Application.Quit")

    def test_texte_trop_long_ou_vide(self):
        self.assertFalse(self.routeur.executer("texte", "")["ok"])
        self.assertFalse(self.routeur.executer("texte", "x" * (T.TAILLE_MAX_TEXTE + 1))["ok"])


# ── QR code ─────────────────────────────────────────────────────────────────
def _gf_tables():
    exp, log = [0] * 512, [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


EXP, LOG = _gf_tables()


def _gf_mul(a, b):
    return 0 if a == 0 or b == 0 else EXP[LOG[a] + LOG[b]]


def reed_solomon(donnees, n):
    """Codes correcteurs recalculés ici, sans rien emprunter à la bibliothèque JS."""
    generateur = [1]
    for i in range(n):
        suivant = [0] * (len(generateur) + 1)
        for j, c in enumerate(generateur):
            suivant[j] ^= c
            suivant[j + 1] ^= _gf_mul(c, EXP[i])
        generateur = suivant
    reste = list(donnees) + [0] * n
    for i in range(len(donnees)):
        f = reste[i]
        if f:
            for j, g in enumerate(generateur):
                reste[i + j] ^= _gf_mul(g, f)
    return reste[len(donnees):]


# Versions à un seul bloc au niveau M (ISO/IEC 18004, table 9) : (données, correction).
BLOCS_M = {1: (16, 10), 2: (28, 16), 3: (44, 26)}
ALIGNEMENT = {1: None, 2: 18, 3: 22}
MASQUES = [
    lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
]


def format_attendu(niveau, masque):
    donnees = (niveau << 3) | masque
    reste = donnees
    for _ in range(10):
        reste = (reste << 1) ^ ((reste >> 9) * 0x537)
    return ((donnees << 10) | reste) ^ 0x5412


def decoder_qr(m):
    """Décodeur minimal (versions 1 à 3, mode octet) : rend (texte, niveau, masque, version)."""
    taille = len(m)
    version = (taille - 17) // 4
    assert taille == 4 * version + 17 and version in BLOCS_M, f"taille {taille}"

    def bit(x, y):
        return m[y][x]

    # Repères de position : 7×7, anneau sombre, anneau clair, carré 3×3.
    for ox, oy in ((0, 0), (taille - 7, 0), (0, taille - 7)):
        for dy in range(7):
            for dx in range(7):
                sombre = max(abs(dx - 3), abs(dy - 3)) != 2
                assert bit(ox + dx, oy + dy) == sombre, "repère de position abîmé"
    for i in range(8, taille - 8):
        assert bit(i, 6) == (i % 2 == 0) and bit(6, i) == (i % 2 == 0), "motif de synchronisation"
    assert bit(8, taille - 8), "module sombre obligatoire"

    premier = 0
    for i in range(6):
        premier |= bit(8, i) << i
    premier |= bit(8, 7) << 6 | bit(8, 8) << 7 | bit(7, 8) << 8
    for i in range(9, 15):
        premier |= bit(14 - i, 8) << i
    second = 0
    for i in range(8):
        second |= bit(taille - 1 - i, 8) << i
    for i in range(8, 15):
        second |= bit(8, taille - 15 + i) << i
    assert premier == second, "les deux copies du format diffèrent"
    trouve = [(n, k) for n in range(4) for k in range(8) if format_attendu(n, k) == premier]
    assert len(trouve) == 1, "format illisible"
    niveau, masque = trouve[0]

    fonction = [[False] * taille for _ in range(taille)]

    def marquer(x0, y0, l, h):
        for y in range(max(0, y0), min(taille, y0 + h)):
            for x in range(max(0, x0), min(taille, x0 + l)):
                fonction[y][x] = True

    marquer(0, 0, 9, 9)
    marquer(taille - 8, 0, 8, 9)
    marquer(0, taille - 8, 9, 8)
    marquer(0, 6, taille, 1)
    marquer(6, 0, 1, taille)
    if ALIGNEMENT[version]:
        a = ALIGNEMENT[version]
        marquer(a - 2, a - 2, 5, 5)

    bits = []
    droite = taille - 1
    while droite >= 1:
        if droite == 6:
            droite = 5
        for vert in range(taille):
            for j in range(2):
                x = droite - j
                y = taille - 1 - vert if ((droite + 1) & 2) == 0 else vert
                if not fonction[y][x]:
                    bits.append(int(bit(x, y)) ^ int(MASQUES[masque](x, y)))
        droite -= 2

    nb_donnees, nb_correction = BLOCS_M[version]
    octets = [int("".join(map(str, bits[i * 8:i * 8 + 8])), 2) for i in range(nb_donnees + nb_correction)]
    donnees, correction = octets[:nb_donnees], octets[nb_donnees:]
    assert niveau == 0, "niveau M attendu"
    assert reed_solomon(donnees, nb_correction) == correction, "correction d'erreurs fausse"

    flux = "".join(f"{o:08b}" for o in donnees)
    assert flux[:4] == "0100", f"mode {flux[:4]} (octet attendu)"
    longueur = int(flux[4:12], 2)
    corps = bytes(int(flux[12 + 8 * i:20 + 8 * i], 2) for i in range(longueur))
    return corps.decode("utf-8"), niveau, masque, version


def matrice_depuis_svg(svg):
    taille_totale = int(re.search(r'viewBox="0 0 (\d+) (\d+)"', svg).group(1))
    marge = int(re.search(r'data-marge="(\d+)"', svg).group(1))
    n = taille_totale - 2 * marge
    m = [[False] * n for _ in range(n)]
    d = re.search(r'<path[^>]* d="([^"]*)"', svg).group(1)
    for x, y, l in re.findall(r"M(\d+) (\d+)h(\d+)v1h-\d+z", d):
        for dx in range(int(l)):
            m[int(y) - marge][int(x) - marge + dx] = True
    return m


@unittest.skipUnless(shutil.which("node"), "node absent : le QR code JS n'est pas exécutable ici")
class QRCode(unittest.TestCase):
    URL = "http://192.168.1.40:8790/"

    def svg(self, texte, options=None):
        script = (
            "const vm=require('vm'),fs=require('fs');"
            "const ctx={window:{}};vm.createContext(ctx);"
            f"vm.runInContext(fs.readFileSync({json.dumps(str(ICI / 'qrcode.js'))},'utf8'),ctx);"
            "const [t,o]=JSON.parse(process.argv[1]);"
            "process.stdout.write(ctx.window.qrSvg(t,o));"
        )
        return subprocess.run(["node", "-e", script, json.dumps([texte, options])],
                              capture_output=True, text=True, check=True, timeout=20).stdout

    def test_url_typique_decodee(self):
        svg = self.svg(self.URL)
        self.assertTrue(svg.startswith("<svg"))
        texte, _niveau, _masque, version = decoder_qr(matrice_depuis_svg(svg))
        self.assertEqual(texte, self.URL)
        self.assertEqual(version, 2)

    def test_adresse_longue_decodee(self):
        url = "http://192.168.100.200:8790/"
        self.assertEqual(decoder_qr(matrice_depuis_svg(self.svg(url)))[0], url)

    def test_couleurs_non_injectables(self):
        svg = self.svg(self.URL, {"sombre": '"/><script>alert(1)</script>', "clair": "#fff"})
        self.assertNotIn("script", svg)
        self.assertIn('fill="#000"', svg)

    def _image(self, svg, dossier):
        m = matrice_depuis_svg(svg)
        echelle, marge = 8, 4
        n = (len(m) + 2 * marge) * echelle
        pixels = bytearray(b"\xff" * n * n)
        for y, ligne in enumerate(m):
            for x, sombre in enumerate(ligne):
                if sombre:
                    for py in range((y + marge) * echelle, (y + marge + 1) * echelle):
                        debut = py * n + (x + marge) * echelle
                        pixels[debut:debut + echelle] = b"\x00" * echelle
        chemin = Path(dossier) / "qr.pgm"
        chemin.write_bytes(b"P5 %d %d 255\n" % (n, n) + bytes(pixels))
        return chemin

    def test_decodeur_de_l_hote(self):
        """Contre-épreuve par un décodeur tiers, s'il y en a un sur la machine."""
        svg = self.svg(self.URL)
        with tempfile.TemporaryDirectory() as d:
            image = self._image(svg, d)
            if shutil.which("zbarimg"):
                sortie = subprocess.run(["zbarimg", "--raw", "-q", str(image)],
                                        capture_output=True, text=True, timeout=20).stdout.strip()
                self.assertEqual(sortie, self.URL)
                return
            try:
                import zxingcpp
                from PIL import Image
            except ImportError:
                self.skipTest("ni zbarimg ni zxing-cpp : décodage tiers non vérifié")
            resultats = zxingcpp.read_barcodes(Image.open(image))
            self.assertEqual([r.text for r in resultats], [self.URL])


if __name__ == "__main__":
    unittest.main()
