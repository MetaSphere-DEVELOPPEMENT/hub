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
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
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
            "appairage": self.dossier / "run" / "hub" / "telecommande-appairage",
            "socket": self.dossier / "run" / "hub" / "menu.sock",
            "jetons": self.dossier / "config" / "hub" / "telecommande-jetons.json",
            "photos": self.dossier / "Images" / "HUB" / "profils",
            "tls": self.dossier / "config" / "hub" / "telecommande-tls",
            "reglages": self.dossier / "config" / "hub" / "reglages.json",
        }
        self.horloge = Horloge()

    def tearDown(self):
        self._tmp.cleanup()


# ── Appairage (logique) ─────────────────────────────────────────────────────
class Appairage(AvecDossier):
    def nouveau(self, ouverte=True):
        changements = []
        self.ouverte = ouverte
        a = T.Appairage(horloge=self.horloge, au_changement=lambda: changements.append(a.code),
                        ouverte=lambda: self.ouverte)
        return a, changements

    @staticmethod
    def faux(a):
        return "000000" if a.code != "000000" else "111111"

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
        self.assertEqual(a.essayer("10.0.0.2", self.faux(a)), T.MAUVAIS)
        self.assertEqual(a.essayer("10.0.0.2", "abc"), T.MAUVAIS)
        self.assertEqual(a.essayer("10.0.0.2", None), T.MAUVAIS)

    def test_fenetre_fermee_rien_n_est_compare_ni_compte(self):
        a, _ = self.nouveau(ouverte=False)
        self.assertEqual(a.essayer("10.0.0.2", a.code), T.FERME, "le bon code ne sert à rien écran fermé")
        for _ in range(50):
            self.assertEqual(a.essayer("10.0.0.2", self.faux(a)), T.FERME)
        self.ouverte = True
        self.assertEqual(a.essayer("10.0.0.2", a.code), T.OK, "les essais écran fermé ne pénalisent personne")

    def test_par_defaut_la_fenetre_est_fermee(self):
        a = T.Appairage(horloge=self.horloge)
        self.assertEqual(a.essayer("10.0.0.2", a.code), T.FERME)

    def test_cinq_essais_par_minute_par_ip(self):
        a, _ = self.nouveau()
        # Chaque essai attend le délai global : seule la limite par adresse doit jouer ici.
        for _ in range(5):
            self.horloge.t = max(self.horloge.t, a._bloque_jusqua)
            self.assertEqual(a.essayer("10.0.0.2", self.faux(a)), T.MAUVAIS)
        self.horloge.t = max(self.horloge.t, a._bloque_jusqua)
        self.assertLess(self.horloge.t, 1_800_000_000 + 60)
        # Le sixième est refusé même avec le bon code : sinon la limite ne limite rien.
        self.assertEqual(a.essayer("10.0.0.2", a.code), T.TROP)
        self.assertGreater(a.attente_s("10.0.0.2"), 1)
        # Une autre IP n'est pas punie par la limite de la première.
        self.assertEqual(a.essayer("10.0.0.9", a.code), T.OK)

    def test_delai_global_croissant_toutes_adresses_confondues(self):
        # L'attaque de l'audit : une adresse différente à chaque essai.
        a, _ = self.nouveau()
        for i in range(T.ECHECS_LIBRES):
            self.assertEqual(a.essayer(f"10.0.1.{i}", self.faux(a)), T.MAUVAIS, "fautes de frappe libres")
        delais = []
        for i in range(8):
            self.assertEqual(a.essayer(f"10.0.2.{i}", self.faux(a)), T.MAUVAIS)
            attente = a.attente_s(f"10.0.3.{i}")
            # Pendant l'attente, une adresse neuve est refusée, même avec le bon code.
            self.assertEqual(a.essayer(f"10.0.3.{i}", a.code), T.TROP)
            delais.append(attente)
            self.horloge.t += attente
        self.assertEqual(delais, [2, 4, 8, 16, 32, 60, 60, 60])
        # Combien d'essais dans une fenêtre de 5 minutes, toutes adresses confondues ?
        b, _ = self.nouveau()
        debut, essais = self.horloge.t, 0
        while self.horloge.t < debut + T.FENETRE_APPAIRAGE_S:
            if b.essayer(f"10.9.{essais // 250}.{essais % 250}", self.faux(b)) == T.MAUVAIS:
                essais += 1
            self.horloge.t += 0.5
        self.assertLessEqual(essais, 15)

    def test_la_serie_s_oublie_apres_un_moment_calme(self):
        a, _ = self.nouveau()
        for _ in range(T.ECHECS_LIBRES + 2):
            a.essayer("10.0.0.2", self.faux(a))
            self.horloge.t += 61
        self.horloge.t += T.OUBLI_ECHECS_S + 1
        self.assertEqual(a.essayer("10.0.0.3", self.faux(a)), T.MAUVAIS)
        self.assertEqual(a.essayer("10.0.0.3", a.code), T.OK, "plus de délai après un quart d'heure calme")

    def test_une_reussite_remet_le_compteur_a_zero(self):
        a, _ = self.nouveau()
        for _ in range(T.ECHECS_LIBRES + 1):
            a.essayer("10.0.0.2", self.faux(a))
        self.horloge.t += 61
        self.assertEqual(a.essayer("10.0.0.2", a.code), T.OK)
        self.assertEqual(a.essayer("10.0.0.2", self.faux(a)), T.MAUVAIS)
        self.assertEqual(a.essayer("10.0.0.2", a.code), T.OK, "pas de délai hérité d'avant la réussite")

    def test_code_expire_est_renouvele(self):
        a, changements = self.nouveau()
        ancien = a.code
        self.horloge.t += T.DUREE_CODE_S + 1
        a.verifier_expiration()
        self.assertNotEqual((a.code, len(changements)), (ancien, 0))
        self.assertEqual(a.essayer("10.0.0.2", ancien) if a.code != ancien else T.MAUVAIS, T.MAUVAIS)

    def test_trop_d_echecs_toutes_ip_confondues_renouvelle_le_code(self):
        a, _ = self.nouveau()
        ancien = a.code
        for i in range(T.ECHECS_AVANT_RENOUVELLEMENT):
            a.essayer(f"10.0.1.{i}", "000000" if ancien != "000000" else "111111")
            self.horloge.t += T.DELAI_MAX_S
        self.assertNotEqual(a.code, ancien)


class FenetreAppairage(AvecDossier):
    def fenetre(self):
        return T.FenetreAppairage(self.chemins["appairage"], horloge=self.horloge)

    def test_ouverte_seulement_si_touchee_recemment(self):
        f = self.fenetre()
        self.assertFalse(f.ouverte())
        self.assertIsNone(f.jusqua_ms())
        f.ouvrir()
        self.assertTrue(f.ouverte())
        self.assertEqual(f.jusqua_ms(), int((self.horloge() + T.FENETRE_APPAIRAGE_S) * 1000))
        self.assertEqual(stat.S_IMODE(os.stat(self.chemins["appairage"]).st_mode), 0o600)
        self.horloge.t += T.FENETRE_APPAIRAGE_S - 1
        self.assertTrue(f.ouverte())
        self.horloge.t += 2
        self.assertFalse(f.ouverte(), "un menu tombé sans nettoyer ne laisse pas l'appairage ouvert")
        f.ouvrir()
        self.assertTrue(f.ouverte(), "le menu prolonge la fenêtre en retouchant le fichier")
        f.fermer()
        self.assertFalse(f.ouverte())

    def test_date_future_ou_lien_n_ouvrent_rien(self):
        f = self.fenetre()
        f.ouvrir()
        t = self.horloge() + 3600
        os.utime(self.chemins["appairage"], (t, t))
        self.assertFalse(f.ouverte())
        self.chemins["appairage"].unlink()
        cible = self.dossier / "cible"
        cible.write_text("")
        os.utime(cible, (self.horloge(), self.horloge()))
        self.chemins["appairage"].symlink_to(cible)
        self.assertFalse(f.ouverte())

    def test_sans_chemin_toujours_fermee(self):
        self.assertFalse(T.FenetreAppairage(None).ouverte())


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
        self.service.fenetre.ouvrir()
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


class Connexions(AvecServeur):
    def test_plafond_par_adresse_puis_liberation(self):
        self.serveur.max_par_ip = 3
        muettes = [socket.create_connection(("127.0.0.1", self.port), timeout=5) for _ in range(3)]
        try:
            # Laisser le serveur accepter les trois avant la quatrième.
            fin = time.monotonic() + 5
            while sum(self.serveur._places.values()) < 3 and time.monotonic() < fin:
                time.sleep(0.01)
            with socket.create_connection(("127.0.0.1", self.port), timeout=5) as refusee:
                refusee.sendall(b"GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
                try:
                    recu = refusee.recv(100)
                except ConnectionResetError:  # fermée avant d'avoir lu la requête
                    recu = b""
                self.assertEqual(recu, b"", "au-delà du plafond, fermée sans réponse")
        finally:
            for m in muettes:
                m.close()
        fin = time.monotonic() + 5
        while self.serveur._places and time.monotonic() < fin:
            time.sleep(0.01)
        self.assertEqual(self.serveur._places, {}, "chaque fil rend sa place")
        self.assertEqual(self.requete("GET", "/")[0], 200)

    def test_plafond_global(self):
        self.serveur.max_connexions = 2
        self.assertTrue(self.serveur._reserver("10.0.0.1"))
        self.assertTrue(self.serveur._reserver("10.0.0.2"))
        self.assertFalse(self.serveur._reserver("10.0.0.3"))
        self.serveur._liberer("10.0.0.1")
        self.assertTrue(self.serveur._reserver("10.0.0.3"))


class CommeUneApp(AvecServeur):
    """Manifeste et icônes : ce que Chrome et Safari lisent pour l'écran d'accueil."""

    def test_manifeste_servi_et_complet(self):
        statut, h, m = self.requete("GET", "/manifest.webmanifest")
        self.assertEqual(statut, 200)
        self.assertTrue(h["content-type"].startswith("application/manifest+json"))
        self.assertIn("content-security-policy", h)
        # Les critères d'installation de Chrome : nom, start_url, display, 192 et 512.
        self.assertTrue(m["name"] and m["short_name"])
        self.assertEqual((m["start_url"], m["scope"], m["display"]), ("/", "/", "standalone"))
        tailles = {i["sizes"] for i in m["icons"]}
        self.assertTrue({"192x192", "512x512"} <= tailles)
        self.assertTrue(any("maskable" in i["purpose"] for i in m["icons"]))
        self.assertFalse(m.get("prefer_related_applications"))
        for icone in m["icons"]:
            self.assertEqual(self.requete("GET", icone["src"])[0], 200, icone["src"])

    def test_icones_png_valides_aux_bonnes_tailles(self):
        import struct
        import zlib
        for chemin, taille in T.ICONES.items():
            statut, h, png = self.requete("GET", chemin)
            self.assertEqual((statut, h["content-type"]), (200, "image/png"), chemin)
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            largeur, hauteur = struct.unpack(">II", png[16:24])
            self.assertEqual((largeur, hauteur), (taille, taille))
            # Relire l'image : centre turquoise, coin à l'encre (fond opaque exigé par iOS).
            debut = png.index(b"IDAT") + 4
            longueur = struct.unpack(">I", png[debut - 8:debut - 4])[0]
            brut = zlib.decompress(png[debut:debut + longueur])
            ligne = 1 + 3 * taille
            self.assertEqual(len(brut), ligne * taille)
            coin = tuple(brut[1:4])
            milieu = brut[ligne * (taille // 2):ligne * (taille // 2 + 1)]
            centre = tuple(milieu[1 + 3 * (taille // 2):4 + 3 * (taille // 2)])
            self.assertEqual(coin, T.ENCRE)
            self.assertGreater(centre[1], 200, chemin)

    def test_la_page_annonce_manifeste_icone_et_plein_ecran(self):
        _s, h, corps = self.requete("GET", "/")
        html = corps.decode()
        self.assertIn('<link rel="manifest" href="/manifest.webmanifest">', html)
        self.assertIn('rel="apple-touch-icon"', html)
        self.assertIn('name="apple-mobile-web-app-capable" content="yes"', html)
        self.assertIn('name="theme-color" content="#06070c"', html)
        self.assertIn("manifest-src 'self'", h["content-security-policy"])
        self.assertEqual(T.MANIFESTE["theme_color"], "#06070c")


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
        self.service.fenetre.ouvrir()
        faux = "000000" if self.service.appairage.code != "000000" else "111111"
        statut, _h, rep = self.requete("POST", "/api/appairer", {"code": faux})
        self.assertEqual((statut, rep["erreur"]), (403, "code"))
        self.assertNotIn("jeton", rep)

    def test_ecran_d_appairage_ferme(self):
        statut, _h, rep = self.requete("POST", "/api/appairer", {"code": self.service.appairage.code})
        self.assertEqual((statut, rep["erreur"]), (403, "appairage-ferme"))
        self.assertEqual(self.service.jetons.lister(), [])
        etat = json.loads(self.chemins["etat"].read_text())
        self.assertEqual((etat["appairageOuvert"], etat["appairageJusque"]), (False, None))

    def test_ouverture_et_fermeture_publiees_code_change_a_la_fermeture(self):
        self.service.fenetre.ouvrir()
        self.assertTrue(self.service.verifier_fenetre())
        etat = json.loads(self.chemins["etat"].read_text())
        self.assertTrue(etat["appairageOuvert"])
        self.assertEqual(etat["appairageJusque"], int((self.horloge() + T.FENETRE_APPAIRAGE_S) * 1000))
        self.assertFalse(self.service.verifier_fenetre(), "rien à publier sans changement")
        self.service.fenetre.fermer()
        self.assertTrue(self.service.verifier_fenetre())
        etat2 = json.loads(self.chemins["etat"].read_text())
        self.assertFalse(etat2["appairageOuvert"])
        self.assertNotEqual(etat2["code"], etat["code"], "le code vu à l'écran ne sert pas à la prochaine ouverture")

    def test_limitation_des_essais(self):
        self.service.fenetre.ouvrir()
        faux = "000000" if self.service.appairage.code != "000000" else "111111"
        for _ in range(T.ECHECS_LIBRES + 1):
            self.assertEqual(self.requete("POST", "/api/appairer", {"code": faux})[0], 403)
        statut, h, rep = self.requete("POST", "/api/appairer", {"code": self.service.appairage.code})
        self.assertEqual(statut, 429)
        self.assertEqual(h["retry-after"], "2")
        self.assertEqual(rep["attente"], 2)

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
        self.assertEqual((etat2["https"], etat2["empreinteRacine"], etat2["empreinteRacineCourte"]),
                         (None, None, None), "sans HTTPS, pas d'empreinte")


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

    def test_quota_de_photos_nombre_et_taille(self):
        jeton = self.appairer()
        dossier = self.chemins["photos"]
        dossier.mkdir(parents=True)
        # Une photo déposée à la main ne compte pas contre le téléphone.
        (dossier / "vacances.jpg").write_bytes(b"x" * 10_000)
        for i in range(T.PHOTOS_MAX):
            (dossier / f"telephone-20260101-0000{i:02d}.jpg").write_bytes(JPEG)
        statut, _h, rep = self.envoyer(JPEG, jeton)
        self.assertEqual((statut, rep["erreur"]), (507, "quota"))
        self.assertEqual(len(list(dossier.glob("telephone-*.jpg"))), T.PHOTOS_MAX)
        for photo in list(dossier.glob("telephone-*.jpg"))[1:]:
            photo.unlink()
        self.assertEqual(self.envoyer(JPEG, jeton)[0], 200)
        # Taille totale : deux photos déjà là pèsent presque tout le quota.
        for photo in dossier.glob("telephone-*.jpg"):
            photo.unlink()
        (dossier / "telephone-20260101-000000.jpg").write_bytes(b"\xff" * (T.PHOTOS_TAILLE_MAX - 100))
        statut, _h, rep = self.envoyer(JPEG, jeton)
        self.assertEqual((statut, rep["erreur"]), (507, "quota"))

    def test_disque_presque_plein(self):
        with self.assertRaises(T.PhotoRefusee) as refus:
            T.enregistrer_photo(self.chemins["photos"], JPEG, self.horloge(),
                                espace_libre=lambda d: T.ESPACE_LIBRE_MIN + len(JPEG) - 1)
        self.assertEqual(str(refus.exception), "espace")
        self.assertEqual(self.photos(), [])
        self.assertTrue(T.enregistrer_photo(self.chemins["photos"], JPEG, self.horloge(),
                                            espace_libre=lambda d: T.ESPACE_LIBRE_MIN + len(JPEG)))

    def test_envois_simultanes_ne_depassent_pas_le_quota(self):
        jeton = self.appairer()
        dossier = self.chemins["photos"]
        dossier.mkdir(parents=True)
        for i in range(T.PHOTOS_MAX - 2):
            (dossier / f"telephone-20260101-0000{i:02d}.jpg").write_bytes(JPEG)
        statuts = []
        fils = [threading.Thread(target=lambda: statuts.append(self.envoyer(JPEG, jeton)[0])) for _ in range(6)]
        for f in fils:
            f.start()
        for f in fils:
            f.join()
        self.assertEqual(sorted(statuts), [200, 200, 507, 507, 507, 507])
        self.assertEqual(len(list(dossier.glob("telephone-*.jpg"))), T.PHOTOS_MAX)

    def test_sans_menu_la_photo_est_quand_meme_ecrite(self):
        jeton = self.appairer()
        statut, _h, rep = self.envoyer(JPEG, jeton)
        self.assertEqual(statut, 200)
        self.assertEqual(self.photos(), [rep["fichier"]])


# ── HTTPS local ─────────────────────────────────────────────────────────────
@unittest.skipUnless(shutil.which("openssl"), "openssl absent")
class AutoriteLocaleTLS(AvecDossier):
    def autorite(self, **kw):
        return T.AutoriteLocale(self.chemins["tls"], nom_machine="salon", **kw)

    def test_racine_et_certificat_crees_cles_privees(self):
        a = self.autorite()
        self.assertTrue(a.preparer("192.168.1.40"))
        self.assertEqual(stat.S_IMODE(os.stat(self.chemins["tls"]).st_mode), 0o700)
        for cle in (a.racine_cle, a.cle):
            self.assertEqual(stat.S_IMODE(os.stat(cle).st_mode), 0o600, cle.name)
        self.assertEqual([p.name for p in self.chemins["tls"].iterdir() if p.name.startswith(".")], [],
                         "aucun fichier provisoire laissé")
        texte = subprocess.run(["openssl", "x509", "-in", str(a.crt), "-noout", "-text"],
                               capture_output=True, text=True, check=True).stdout
        self.assertIn("IP Address:192.168.1.40", texte)
        self.assertIn("DNS:hub.local", texte)
        self.assertIn("DNS:salon.local", texte)
        self.assertIn("TLS Web Server Authentication", texte)
        racine = subprocess.run(["openssl", "x509", "-in", str(a.racine_crt), "-noout", "-text"],
                                capture_output=True, text=True, check=True).stdout
        self.assertRegex(racine, r"Name Constraints: critical")
        self.assertIn("CA:TRUE, pathlen:0", racine)
        # Le strict nécessaire : l'adresse du HUB et ses deux noms, rien d'autre.
        self.assertEqual(a.contraintes(), {"IP:192.168.1.40/255.255.255.255", "DNS:hub.local", "DNS:salon.local"})
        self.assertRegex(a.empreinte(), r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")

    def test_duree_du_certificat_sous_les_limites_d_apple(self):
        a = self.autorite()
        a.preparer("192.168.1.40")
        fiche = json.loads(a.fiche.read_text())
        jours = (fiche["expire"] - time.time()) / 86400
        self.assertTrue(390 < jours <= 398, jours)

    def test_chaine_valide_et_contraintes_de_nom_appliquees(self):
        a = self.autorite()
        a.preparer("192.168.1.40")
        verifie = subprocess.run(["openssl", "verify", "-CAfile", str(a.racine_crt), "-purpose", "sslserver",
                                  str(a.crt)], capture_output=True, text=True)
        self.assertEqual(verifie.returncode, 0, verifie.stderr)
        # La clé racine volée signe pour un site public, pour une autre adresse privée
        # (la box, un NAS, le réseau d'un hôtel) ou un autre nom .local : tout est refusé.
        d = self.dossier
        for i, alternatifs in enumerate(("DNS:banque.example,IP:8.8.8.8", "IP:192.168.1.1",
                                         "IP:10.0.0.5", "DNS:nas.local")):
            cn = alternatifs.split(",")[0].split(":", 1)[1]
            (d / "faux.cnf").write_text(f"[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN={cn}\n"
                                        f"[v3]\nsubjectAltName={alternatifs}\n")
            subprocess.run(["openssl", "req", "-new", "-key", str(a.cle), "-config", str(d / "faux.cnf"),
                            "-out", str(d / "faux.csr")], check=True, capture_output=True)
            subprocess.run(["openssl", "x509", "-req", "-in", str(d / "faux.csr"), "-CA", str(a.racine_crt),
                            "-CAkey", str(a.racine_cle), "-set_serial", str(7 + i), "-days", "2",
                            "-extfile", str(d / "faux.cnf"), "-extensions", "v3", "-out", str(d / "faux.crt")],
                           check=True, capture_output=True)
            refuse = subprocess.run(["openssl", "verify", "-CAfile", str(a.racine_crt), str(d / "faux.crt")],
                                    capture_output=True, text=True)
            self.assertNotEqual(refuse.returncode, 0, alternatifs)
            self.assertIn("permitted subtree violation", refuse.stdout + refuse.stderr, alternatifs)

    def test_reemission_seulement_si_necessaire_racine_conservee(self):
        horloge = Horloge(time.time())
        a = self.autorite(horloge=horloge)
        a.preparer("192.168.1.40")
        racine, serie = a.empreinte(), a.crt.read_bytes()
        self.assertFalse(a.preparer("192.168.1.40"))
        self.assertEqual(a.crt.read_bytes(), serie)
        horloge.t += 370 * 86400
        self.assertTrue(a.a_renouveler())
        self.assertTrue(a.preparer("192.168.1.40"), "échéance proche : nouveau certificat")
        self.assertEqual(a.empreinte(), racine, "la racine installée sur les téléphones ne change pas")

    def test_nouvelle_adresse_nouvelle_racine(self):
        # Le prix de la racine /32 : un autre bail DHCP exige de réinstaller le certificat.
        a = self.autorite()
        a.preparer("192.168.1.40")
        ancienne, ancienne_cle = a.empreinte(), a.racine_cle.read_bytes()
        self.assertTrue(a.preparer("192.168.1.41"))
        self.assertNotEqual(a.empreinte(), ancienne)
        self.assertNotEqual(a.racine_cle.read_bytes(), ancienne_cle, "l'ancienne clé est détruite")
        self.assertEqual(a.contraintes(), {"IP:192.168.1.41/255.255.255.255", "DNS:hub.local", "DNS:salon.local"})
        verifie = subprocess.run(["openssl", "verify", "-CAfile", str(a.racine_crt), "-purpose", "sslserver",
                                  str(a.crt)], capture_output=True, text=True)
        self.assertEqual(verifie.returncode, 0, verifie.stderr)

    def test_ancienne_racine_trop_large_remplacee(self):
        """Migration : une racine d'avant le 17/09/2026 (tout le privé et .local)."""
        a = self.autorite()
        self.chemins["tls"].mkdir(parents=True, mode=0o700)
        d = self.dossier
        (d / "ancienne.cnf").write_text("\n".join([
            "[req]", "distinguished_name = dn", "prompt = no", "[dn]", "O = HUB", "CN = HUB autorité locale",
            "[v3]", "basicConstraints = critical,CA:TRUE,pathlen:0", "keyUsage = critical,keyCertSign,cRLSign",
            "nameConstraints = critical,@c", "[c]",
            "permitted;IP.0 = 10.0.0.0/255.0.0.0", "permitted;IP.1 = 172.16.0.0/255.240.0.0",
            "permitted;IP.2 = 192.168.0.0/255.255.0.0", "permitted;IP.3 = 169.254.0.0/255.255.0.0",
            "permitted;IP.4 = 127.0.0.0/255.0.0.0", "permitted;DNS.0 = local", ""]))
        subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256",
                        "-out", str(a.racine_cle)], check=True, capture_output=True)
        subprocess.run(["openssl", "req", "-x509", "-new", "-key", str(a.racine_cle), "-config", str(d / "ancienne.cnf"),
                        "-extensions", "v3", "-days", "3650", "-out", str(a.racine_crt)], check=True, capture_output=True)
        self.assertEqual(len(a.contraintes()), 6)
        ancienne = a.empreinte()
        # Un ancien service avait aussi émis son certificat, encore valable des mois.
        a.fiche.write_text(json.dumps({"adresse": "192.168.1.40", "noms": T.noms_du_hub("salon"),
                                       "expire": time.time() + 300 * 86400, "racine": ancienne}))
        a.crt.write_text("ancien")
        a.cle.write_text("ancienne")
        self.assertTrue(a.preparer("192.168.1.40"))
        self.assertNotEqual(a.empreinte(), ancienne)
        self.assertEqual(a.contraintes(), {"IP:192.168.1.40/255.255.255.255", "DNS:hub.local", "DNS:salon.local"})
        self.assertEqual(json.loads(a.fiche.read_text())["racine"], a.empreinte())
        self.assertFalse(a.preparer("192.168.1.40"), "remplacée une fois, pas à chaque démarrage")

    def test_openssl_en_panne_ne_detruit_pas_la_racine(self):
        a = self.autorite()
        a.preparer("192.168.1.40")
        racine = a.racine_cle.read_bytes()
        casse = self.autorite(openssl=str(self.dossier / "openssl-absent"))
        with self.assertRaises(T.ErreurTLS):
            casse.preparer("192.168.1.40")
        self.assertEqual(a.racine_cle.read_bytes(), racine)

    def test_racine_sans_contraintes_remplacee(self):
        a = self.autorite()
        self.chemins["tls"].mkdir(parents=True, mode=0o700)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                        "-nodes", "-keyout", str(a.racine_cle), "-subj", "/CN=nue", "-days", "2",
                        "-out", str(a.racine_crt)], check=True, capture_output=True)
        self.assertIsNone(a.contraintes())
        a.preparer("192.168.1.40")
        self.assertEqual(len(a.contraintes()), 3)

    def test_refus_adresse_publique_horloge_fausse_openssl_absent(self):
        with self.assertRaises(T.ErreurTLS):
            self.autorite().preparer("8.8.8.8")
        with self.assertRaises(T.ErreurTLS):
            self.autorite(horloge=lambda: 1_000_000_000).preparer("192.168.1.40")
        with self.assertRaises(T.ErreurTLS):
            self.autorite(openssl="").preparer("192.168.1.40")
        self.assertFalse(self.chemins["tls"].exists() and any(self.chemins["tls"].glob("*.key")))


class LectureDesContraintes(unittest.TestCase):
    """Sans openssl : la lecture du texte qu'il imprime (OpenSSL 3 et LibreSSL)."""

    OPENSSL3 = """        X509v3 extensions:
            X509v3 Basic Constraints: critical
                CA:TRUE, pathlen:0
            X509v3 Name Constraints: critical
                Permitted:
                  IP:192.168.1.40/255.255.255.255
                  DNS:hub.local
                  DNS:salon.local
            X509v3 Subject Key Identifier:
                CA:72:97
"""
    LIBRESSL_ANCIENNE = """            X509v3 Name Constraints: critical
                Permitted:
                  IP:10.0.0.0/255.0.0.0
                  DNS:local
                Excluded:
                  DNS:exclu.local

            X509v3 Subject Key Identifier:
"""

    def test_lecture(self):
        self.assertEqual(T.lire_contraintes(self.OPENSSL3),
                         T.contraintes_attendues("192.168.1.40", ["hub.local", "salon.local"]))
        self.assertEqual(T.lire_contraintes(self.LIBRESSL_ANCIENNE), {"IP:10.0.0.0/255.0.0.0", "DNS:local"})
        self.assertIsNone(T.lire_contraintes("            X509v3 Basic Constraints: critical\n"))

    def test_empreinte_courte(self):
        empreinte = ":".join(f"{i:02X}" for i in range(0x3A, 0x3A + 32))
        self.assertEqual(T.empreinte_courte(empreinte), "3A3B 3C3D 3E3F 4041")
        self.assertIsNone(T.empreinte_courte(None))


@unittest.skipUnless(shutil.which("openssl"), "openssl absent")
class ServiceHTTPS(AvecDossier):
    def setUp(self):
        super().setUp()
        routeur = T.Routeur(self.chemins["socket"], executer=lambda c, **k: subprocess.CompletedProcess(c, 0, "", ""),
                            processus=lambda noms: [], kodi_http=None)
        self.tls = T.AutoriteLocale(self.chemins["tls"])
        self.service = T.Service(self.chemins, routeur=routeur, tls=self.tls)
        self.service.fenetre.ouvrir()
        self.serveurs = T.demarrer_ecoutes(self.service, "127.0.0.1", 0, 0, sondage=0.05)
        self.http, self.https = (s.server_address[1] for s in self.serveurs)

    def tearDown(self):
        for s in self.serveurs:
            s.shutdown()
            s.server_close()
        super().tearDown()

    def contexte_client(self):
        return ssl.create_default_context(cafile=str(self.tls.racine_crt))

    def requete(self, methode, chemin, corps=None, jeton=None, entetes=None, securise=False,
                nom_serveur="127.0.0.1"):
        if securise:
            c = http.client.HTTPSConnection("127.0.0.1", self.https, timeout=5, context=self.contexte_client())
            if nom_serveur != "127.0.0.1":
                # Joindre 127.0.0.1 en vérifiant le nom hub.local, comme un téléphone
                # qui a résolu hub.local par mDNS.
                brut = socket.create_connection(("127.0.0.1", self.https), timeout=5)
                c.sock = self.contexte_client().wrap_socket(brut, server_hostname=nom_serveur)
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

    def test_page_servie_en_https_chaine_verifiee_par_python(self):
        statut, h, corps = self.requete("GET", "/", securise=True)
        self.assertEqual(statut, 200)
        self.assertIn(b"<html", corps)
        self.assertIn("default-src 'none'", h["content-security-policy"])
        # Le nom mDNS du certificat est accepté aussi par un client qui vérifie.
        statut, _h, _ = self.requete("GET", "/", securise=True, nom_serveur="hub.local",
                                     entetes={"Host": f"hub.local:{self.https}"})
        self.assertEqual(statut, 200)

    def test_client_sans_la_racine_refuse(self):
        c = http.client.HTTPSConnection("127.0.0.1", self.https, timeout=5, context=ssl.create_default_context())
        with self.assertRaises(ssl.SSLCertVerificationError):
            c.request("GET", "/")
        c.close()
        # Le service survit à la poignée de main ratée.
        self.assertEqual(self.requete("GET", "/", securise=True)[0], 200)

    def test_http_sur_le_port_https_ne_fait_pas_tomber_le_service(self):
        with socket.create_connection(("127.0.0.1", self.https), timeout=5) as s:
            s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            s.recv(100)
        self.assertEqual(self.requete("GET", "/", securise=True)[0], 200)

    def test_cle_privee_jamais_servie(self):
        secrets_pem = [p.read_bytes() for p in self.chemins["tls"].glob("*.key")]
        self.assertEqual(len(secrets_pem), 2)
        noyaux = [b"".join(k.split(b"\n")[1:-2])[:40] for k in secrets_pem]
        chemins = ["/hub.key", "/racine.key", "/hub-racine.key", "/telecommande-tls/racine.key",
                   "/../telecommande-tls/hub.key", "/%2e%2e/racine.key", "/hub.crt", "/racine.crt",
                   "/hub-racine.crt", "/api/certificat", "/", "/manifest.webmanifest", "/hub.json"]
        for securise in (False, True):
            for chemin in chemins:
                statut, _h, corps = self.requete("GET", chemin, securise=securise)
                brut = corps if isinstance(corps, bytes) else json.dumps(corps).encode()
                self.assertNotIn(b"PRIVATE KEY", brut, chemin)
                for noyau in noyaux:
                    self.assertNotIn(noyau, brut, chemin)
                if chemin not in ("/hub-racine.crt", "/api/certificat", "/", "/manifest.webmanifest"):
                    self.assertEqual(statut, 404, chemin)

    def test_certificat_racine_servi_en_http_empreinte_seulement_pour_la_tv(self):
        statut, h, der = self.requete("GET", "/hub-racine.crt")
        self.assertEqual((statut, h["content-type"]), (200, "application/x-x509-ca-cert"))
        self.assertEqual(der, ssl.PEM_cert_to_DER_cert(self.tls.racine_crt.read_text()))
        empreinte = ":".join(f"{o:02X}" for o in __import__("hashlib").sha256(der).digest())
        # L'empreinte ne passe jamais par le canal http du certificat : elle ne prouverait rien.
        _s, _h, info = self.requete("GET", "/api/certificat")
        self.assertEqual(info, {"disponible": True, "securise": False, "https": f"https://127.0.0.1:{self.https}/"})
        _s, _h, page = self.requete("GET", "/")
        self.assertNotIn(b'id="empreinte"', page)
        etat = json.loads(self.chemins["etat"].read_text())
        self.assertEqual((etat["https"], etat["empreinteRacine"]), (f"https://127.0.0.1:{self.https}/", empreinte))
        self.assertEqual(etat["empreinteRacineCourte"], " ".join(
            empreinte.replace(":", "")[i:i + 4] for i in range(0, 16, 4)))

    def test_csp_http_autorise_la_seule_origine_https_et_sonde(self):
        _s, h, _ = self.requete("GET", "/")
        self.assertIn(f"connect-src 'self' https://127.0.0.1:{self.https};", h["content-security-policy"])
        _s, h, _ = self.requete("GET", "/", securise=True)
        self.assertIn("connect-src 'self';", h["content-security-policy"])
        statut, h, _ = self.requete("GET", "/sonde", securise=True, entetes={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual((statut, h["cross-origin-resource-policy"]), (204, "cross-origin"))
        # Rien de tel en http, ni ailleurs en https pour une requête intersite.
        self.assertEqual(self.requete("GET", "/sonde")[0], 404)
        self.assertEqual(self.requete("GET", "/", securise=True, entetes={"Sec-Fetch-Site": "cross-site"})[0], 403)
        # Mais la navigation depuis la page http (autre schéma, donc « cross-site ») passe.
        navigation = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        self.assertEqual(self.requete("GET", "/", securise=True, entetes=navigation)[0], 200)
        for chemin in ("/api/etat", "/hub-racine.crt", "/api/certificat"):
            self.assertEqual(self.requete("GET", chemin, securise=True, entetes=navigation)[0], 403, chemin)
        self.assertEqual(self.requete("POST", "/api/appairer", {"transfert": "x" * 43}, securise=True,
                                      entetes=navigation)[0], 403)
        self.assertEqual(self.requete("GET", "/sonde", securise=True, entetes={"Host": "evil.example:1"})[0], 421)

    def test_transfert_http_vers_https_usage_unique(self):
        _s, _h, rep = self.requete("POST", "/api/appairer", {"code": self.service.appairage.code})
        jeton_http = rep["jeton"]
        self.assertEqual(self.requete("POST", "/api/transfert", {})[0], 401)
        statut, _h, rep = self.requete("POST", "/api/transfert", {}, jeton=jeton_http)
        self.assertEqual(statut, 200)
        self.assertTrue(rep["url"].startswith(f"https://127.0.0.1:{self.https}/#transfert="))
        ticket = rep["url"].split("=", 1)[1]
        # Le ticket ne vaut rien en http, ni comme jeton.
        self.assertEqual(self.requete("POST", "/api/appairer", {"transfert": ticket})[0], 403)
        self.assertEqual(self.requete("GET", "/api/etat", jeton=ticket, securise=True)[0], 401)
        statut, _h, rep = self.requete("POST", "/api/appairer", {"transfert": ticket, "nom": "Pixel"}, securise=True)
        self.assertEqual(statut, 200, "le ticket a été consommé par la tentative http ?")
        self.assertEqual(self.requete("GET", "/api/etat", jeton=rep["jeton"], securise=True)[0], 200)
        self.assertEqual(self.requete("POST", "/api/appairer", {"transfert": ticket}, securise=True)[0], 403)

    def test_ticket_expire(self):
        ticket = self.service.creer_ticket()
        self.service.horloge = lambda: time.time() + T.DUREE_TICKET_S + 1
        self.assertFalse(self.service.consommer_ticket(ticket))


# ── Dictée ──────────────────────────────────────────────────────────────────
def wav(secondes=1.0, taux=16000, canaux=1, largeur=2):
    import io
    import math
    import wave
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(canaux)
        w.setsampwidth(largeur)
        w.setframerate(taux)
        n = int(secondes * taux)
        w.writeframes(b"".join(int(8000 * math.sin(i / 8)).to_bytes(2, "little", signed=True) * canaux
                               for i in range(n)) if largeur == 2 else b"\x80" * n)
    return tampon.getvalue()


class FauxDicteur:
    def __init__(self, texte="télé", erreur=None):
        self.texte, self.erreur, self.appels = texte, erreur, []

    def reconnaitre(self, pcm, langue):
        self.appels.append((len(pcm), langue))
        if self.erreur:
            raise T.DicteeIndisponible(self.erreur)
        return self.texte

    def entretien(self):
        pass


@unittest.skipUnless(T.VOIX, "hub_voix_logique introuvable")
class Dictee(AvecServeur):
    def setUp(self):
        super().setUp()
        self.dicteur = FauxDicteur()
        self.service.dicteur = self.dicteur

    def dicter(self, octets, jeton, type_contenu="audio/wav"):
        return self.requete("POST", "/api/dictee", brut=octets, jeton=jeton,
                            entetes={"Content-Type": type_contenu})

    def test_jeton_type_et_format_exiges(self):
        self.assertEqual(self.dicter(wav(), None)[0], 401)
        jeton = self.appairer()
        self.assertEqual(self.dicter(wav(), jeton, "text/plain")[0], 415)
        for mauvais in (wav(taux=8000), wav(canaux=2), wav(largeur=1), b"RIFF\x00\x00", JPEG):
            self.assertEqual(self.dicter(mauvais, jeton)[0], 400)
        self.assertEqual(self.dicter(wav(0.1), jeton)[2]["erreur"], "trop-court")
        self.assertEqual(self.dicter(b"RIFF" + b"\x00" * (T.TAILLE_MAX_DICTEE + 1), jeton)[0], 413)
        self.assertEqual(self.dicteur.appels, [], "rien d'invalide n'atteint le reconnaisseur")

    def test_commande_reconnue_datagrammes_au_menu(self):
        jeton = self.appairer()
        menu = FauxMenu(self.chemins["socket"])
        try:
            statut, _h, rep = self.dicter(wav(1.2), jeton)
            self.assertEqual(statut, 200, rep)
            self.assertEqual((rep["ok"], rep["commande"], rep["cible"], rep["texte"]), (True, "tv", "menu", "télé"))
            self.assertEqual([menu.recevoir() for _ in range(3)], ["voix:entendu:télé", "tv", "voix:repos"])
            self.assertEqual(self.dicteur.appels, [(int(1.2 * 16000) * 2, "fr")])
        finally:
            menu.fermer()

    def test_phrase_hors_grammaire_incomprise(self):
        jeton = self.appairer()
        self.dicteur.texte = "bureau jouer films ouvre"
        menu = FauxMenu(self.chemins["socket"])
        try:
            _s, _h, rep = self.dicter(wav(), jeton)
            self.assertEqual((rep["ok"], rep["raison"], rep["commande"]), (False, "incompris", None))
            self.assertEqual([menu.recevoir() for _ in range(3)],
                             ["voix:entendu:bureau jouer films ouvre", "voix:incompris", "voix:repos"])
        finally:
            menu.fermer()

    def test_langue_du_profil_actif(self):
        self.chemins["reglages"].parent.mkdir(parents=True, exist_ok=True)
        self.chemins["reglages"].write_text(json.dumps({"profilActif": "b", "profils": [
            {"id": "a", "langue": "fr"}, {"id": "b", "langue": "en"}]}))
        jeton = self.appairer()
        self.dicteur.texte = "go home"
        _s, _h, rep = self.dicter(wav(), jeton)
        self.assertEqual(self.dicteur.appels[-1][1], "en")
        self.assertEqual(rep["commande"], "retour")

    def test_eteindre_dicte_menu_ferme_refuse(self):
        jeton = self.appairer()
        self.processus = {"kodi", "gnome-shell"}
        self.dicteur.texte = "éteins"
        _s, _h, rep = self.dicter(wav(), jeton)
        self.assertEqual((rep["commande"], rep["ok"]), ("eteindre", False))
        self.assertEqual(self.executes, [])

    def test_reconnaisseur_indisponible(self):
        jeton = self.appairer()
        self.service.dicteur = FauxDicteur(erreur="vosk-absent")
        statut, _h, rep = self.dicter(wav(), jeton)
        self.assertEqual((statut, rep["erreur"], rep["raison"]), (503, "voix-indisponible", "vosk-absent"))

    def test_micro_permis_a_cette_origine_seule(self):
        _s, h, _ = self.requete("GET", "/")
        self.assertIn("microphone=(self)", h["permissions-policy"])
        self.assertIn("camera=()", h["permissions-policy"])


class TravailleurDictee(AvecDossier):
    def test_sans_vosk_erreur_propre(self):
        d = T.Dicteur(python=sys.executable if not _vosk_importable(sys.executable) else "/bin/false",
                      script=ICI.parent / "voix" / "hub-voix.py")
        try:
            with self.assertRaises(T.DicteeIndisponible):
                d.reconnaitre(b"\x00" * 16000, "fr")
        finally:
            d.arreter()

    @unittest.skipUnless(os.environ.get("HUB_VOIX_PYTHON") and os.environ.get("HUB_VOIX_MODELES")
                         and os.environ.get("HUB_TEST_DICTEE_WAV"),
                         "vrai Vosk : HUB_VOIX_PYTHON, HUB_VOIX_MODELES et HUB_TEST_DICTEE_WAV (« télé »)")
    def test_vrai_vosk_de_bout_en_bout(self):
        """Le vrai modèle, le vrai travailleur et le vrai service : « télé » → datagramme tv."""
        routeur = T.Routeur(self.chemins["socket"], executer=lambda *a, **k: None,
                            processus=lambda n: [], kodi_http=None)
        service = T.Service(self.chemins, routeur=routeur, dicteur=T.Dicteur(script=ICI.parent / "voix" / "hub-voix.py"))
        serveur = T.creer_serveur(service, "127.0.0.1", 0)
        threading.Thread(target=serveur.serve_forever, args=(0.05,), daemon=True).start()
        menu = FauxMenu(self.chemins["socket"])
        try:
            port = serveur.server_address[1]
            def post(chemin, corps, entetes):
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=40)
                c.request("POST", chemin, body=corps, headers={"Host": f"127.0.0.1:{port}", **entetes})
                r = c.getresponse()
                return r.status, json.loads(r.read())
            _s, rep = post("/api/appairer", json.dumps({"code": service.appairage.code}).encode(),
                           {"Content-Type": "application/json"})
            statut, rep = post("/api/dictee", Path(os.environ["HUB_TEST_DICTEE_WAV"]).read_bytes(),
                               {"Content-Type": "audio/wav", "Authorization": f"Bearer {rep['jeton']}"})
            self.assertEqual((statut, rep["commande"], rep["cible"]), (200, "tv", "menu"), rep)
            self.assertEqual([menu.recevoir() for _ in range(3)], ["voix:entendu:télé", "tv", "voix:repos"])
        finally:
            menu.fermer()
            service.dicteur.arreter()
            serveur.shutdown()
            serveur.server_close()


def _vosk_importable(python):
    return subprocess.run([python, "-c", "import vosk"], capture_output=True).returncode == 0


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
