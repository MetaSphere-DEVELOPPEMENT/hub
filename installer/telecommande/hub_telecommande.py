#!/usr/bin/env python3
"""Télécommande téléphone du HUB : une page web sur le réseau local.

On scanne le QR code affiché sur la TV, on tape le code à 6 chiffres, et le téléphone
devient une télécommande : croix directionnelle, OK, retour, modes, volume, texte.

POURQUOI UNE PAGE WEB. Le M720q n'a ni Bluetooth ni HDMI-CEC (ARCHITECTURE.md,
contraintes 2 et 3) : la télécommande de la TV ne pilote rien. Tout le monde a un
téléphone sur le wifi de la maison, et un navigateur n'a rien à installer.

POURQUOI LA BIBLIOTHÈQUE STANDARD SEULE. Un appareil de salon qu'on doit savoir
réparer un soir de panne : pas de pip, pas de framework, un seul fichier Python,
une page, une unité systemd.

LA SÉCURITÉ, EN BREF (détails dans README.md). Rien n'est accepté sans jeton ; un
jeton ne s'obtient qu'avec le code affiché sur la TV, donc en étant dans la pièce.
Le code change à chaque démarrage, après chaque usage, toutes les 5 minutes et après
trop d'échecs ; 5 essais par minute par adresse. Les commandes sont une liste
blanche, la page est la seule chose servie, et l'en-tête Host est vérifié contre le
rebinding DNS.

OÙ VONT LES COMMANDES. Menu ouvert : au socket du menu, exactement comme la voix.
Menu fermé : à Kodi (navigation, texte, quitter) s'il tourne, sinon à la session
bureau (« Accueil » la ferme). « Éteindre » ne part jamais ailleurs qu'au menu, qui
demande confirmation sur la TV.
"""

import argparse
import base64
import fcntl
import hashlib
import hmac
import importlib.util
import ipaddress
import json
import logging
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ICI = Path(__file__).resolve().parent

# 8790 : libre sur Ubuntu (ni Kodi 8080/9090, ni CUPS, ni rien d'enregistré à l'IANA
# qu'on trouverait sur une machine de salon). Fixe, parce que l'URL finit dans les
# favoris des téléphones — et le jeton est lié à l'origine http://ip:port.
PORT = 8790

DUREE_CODE_S = 5 * 60
ESSAIS_PAR_MINUTE = 5
# Au-delà, toutes adresses confondues, le code change : cinq essais par adresse ne
# protègent rien contre quelqu'un qui en utilise cinquante.
ECHECS_AVANT_RENOUVELLEMENT = 20
TAILLE_MAX_CORPS = 2048
# Une photo recadrée à 512 px en JPEG 0,88 pèse 60 à 150 Ko : 2 Mio laisse de la marge
# à un navigateur qui compresse mal, sans laisser remplir le disque par rafales.
TAILLE_MAX_PHOTO = 2 * 1024 * 1024
TAILLE_MAX_TEXTE = 300
TAILLE_MAX_NOM = 40
# Réécrire le fichier des jetons à chaque appui userait le disque pour rien : la date
# de dernier usage ne sert qu'à reconnaître un vieux téléphone à révoquer.
PRECISION_VU_S = 3600

OK, MAUVAIS, TROP = "ok", "mauvais", "trop"

# Les noms du protocole du socket du menu (hub-menu.py, COMMANDES), recopiés et non
# importés : importer hub-menu.py tirerait sa logique entière dans un service réseau.
# test_telecommande.py vérifie qu'ils sont identiques.
COMMANDES_MENU = frozenset({
    "tv", "gaming", "bureau", "eteindre", "reglages", "aide", "meteo", "profils",
    "retour", "gauche", "droite", "haut", "bas", "ok", "theme:clair", "theme:sombre",
})
# « accueil » n'existe pas dans le protocole du menu : la télécommande le traduit
# (« retour » dans le menu, quitter Kodi, fermer le bureau).
COMMANDES = COMMANDES_MENU | {"accueil", "volume:+", "volume:-", "texte"}

KODI_NAVIGATION = {
    "gauche": "Input.Left", "droite": "Input.Right", "haut": "Input.Up", "bas": "Input.Down",
    "ok": "Input.Select", "retour": "Input.Back",
}

journal = logging.getLogger("hub-telecommande")


# ── La logique de la voix, réutilisée ───────────────────────────────────────
def _charger_logique_voix():
    """hub_voix_logique.py sait déjà parler au menu et reconnaître Kodi et le bureau.

    Importé depuis son fichier plutôt que par sys.path : on ne veut que ce module-là,
    pas n'importe quel homonyme trouvé en chemin.
    """
    candidats = [os.environ.get("HUB_VOIX_DOSSIER"), ICI.parent / "voix",
                 "/usr/local/lib/hub/voix", "/opt/hub-voix"]
    for dossier in candidats:
        if not dossier:
            continue
        fichier = Path(dossier) / "hub_voix_logique.py"
        if not fichier.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location("hub_voix_logique", fichier)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception as erreur:  # noqa: BLE001
            journal.warning("hub_voix_logique illisible (%s) : %s", fichier, erreur)
    return None


VOIX = _charger_logique_voix()


def _envoyer_menu(chemin, texte):
    if VOIX:
        return VOIX.envoyer(chemin, texte)
    # Sans le module de la voix, la télécommande garde au moins le menu : c'est le
    # cas le plus courant, et aucun mode ne doit dépendre d'un autre pour vivre.
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(texte.encode("utf-8"), str(chemin))
        return True
    except OSError:
        return False


def _processus(noms):
    return VOIX.processus(noms) if VOIX else []


NOMS_KODI = frozenset(VOIX.NOMS_KODI) if VOIX else frozenset({"kodi", "kodi.bin"})
NOMS_BUREAU = frozenset(VOIX.NOMS_BUREAU) if VOIX else frozenset({"gnome-shell"})


# ── Fichiers ────────────────────────────────────────────────────────────────
def chemins_par_defaut():
    maison = Path.home()
    execution = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "hub"
    config = Path(os.environ.get("XDG_CONFIG_HOME") or maison / ".config") / "hub"
    return {
        "etat": execution / "telecommande.json",
        "socket": execution / "menu.sock",
        "jetons": config / "telecommande-jetons.json",
        # Là où le menu cherche déjà ses images (hub-menu.py, photos()).
        "photos": maison / "Images" / "HUB" / "profils",
    }


def ecrire_prive(chemin, texte):
    """Écriture atomique en 0600 : le fichier n'existe jamais, même un instant, lisible
    par d'autres ni à moitié écrit."""
    chemin = Path(chemin)
    chemin.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    provisoire = chemin.with_name(f".{chemin.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(provisoire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texte)
        os.replace(provisoire, chemin)
    except BaseException:
        Path(provisoire).unlink(missing_ok=True)
        raise


def _empreinte(jeton):
    # On ne garde que l'empreinte : une copie du fichier (sauvegarde, dépôt par erreur)
    # ne donne pas la télécommande. Un jeton de 256 bits n'a pas besoin de sel.
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


class Jetons:
    """Les téléphones appairés, relus dès que le fichier change.

    Relire à chaque vérification (un stat, rien de plus s'il n'a pas bougé) rend la
    révocation immédiate : `--revoquer` écrit le fichier, le service en cours le voit
    à la requête suivante, sans redémarrage.
    """

    def __init__(self, chemin, horloge=time.time):
        self.chemin = Path(chemin)
        self.horloge = horloge
        self._verrou = threading.Lock()
        self._signature = None
        self._liste = []

    def _verrou_fichier(self):
        # Le service et la ligne de commande écrivent le même fichier : un verrou
        # consultatif évite qu'une révocation soit écrasée par une mise à jour de « vu ».
        self.chemin.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.chemin.with_suffix(".verrou"), os.O_WRONLY | os.O_CREAT, 0o600)
        f = os.fdopen(fd, "w")
        fcntl.flock(f, fcntl.LOCK_EX)
        return f

    def _lire(self):
        try:
            st = self.chemin.stat()
            signature = (st.st_ino, st.st_mtime_ns, st.st_size)
        except OSError:
            self._signature, self._liste = None, []
            return self._liste
        if signature == self._signature:
            return self._liste
        try:
            donnees = json.loads(self.chemin.read_text(encoding="utf-8"))
            liste = [t for t in donnees.get("telephones", [])
                     if isinstance(t, dict) and isinstance(t.get("empreinte"), str)
                     and isinstance(t.get("id"), str)]
        except (OSError, ValueError, AttributeError):
            # Fichier abîmé : personne n'entre. Ré-appairer vaut mieux que deviner.
            journal.warning("%s illisible : aucun téléphone reconnu", self.chemin)
            liste = []
        self._signature, self._liste = signature, liste
        return liste

    def _ecrire(self, liste):
        ecrire_prive(self.chemin, json.dumps({"telephones": liste}, ensure_ascii=False, indent=2))
        self._signature = None
        self._lire()

    def creer(self, nom):
        jeton = secrets.token_urlsafe(32)
        ident = secrets.token_hex(3)
        maintenant = int(self.horloge() * 1000)
        with self._verrou, self._verrou_fichier():
            self._signature = None
            liste = list(self._lire())
            liste.append({"id": ident, "nom": nom, "empreinte": _empreinte(jeton),
                          "cree": maintenant, "vu": maintenant})
            self._ecrire(liste)
        return ident, jeton

    def valide(self, jeton):
        """Identifiant du téléphone, ou None."""
        if not isinstance(jeton, str) or not 20 <= len(jeton) <= 200:
            return None
        empreinte = _empreinte(jeton)
        with self._verrou:
            trouve = None
            for t in self._lire():
                if hmac.compare_digest(t["empreinte"], empreinte):
                    trouve = t
            if trouve is None:
                return None
            maintenant = int(self.horloge() * 1000)
            if maintenant - int(trouve.get("vu") or 0) > PRECISION_VU_S * 1000:
                try:
                    with self._verrou_fichier():
                        self._signature = None
                        liste = [dict(t, vu=maintenant) if t["id"] == trouve["id"] else t
                                 for t in self._lire()]
                        if any(t["id"] == trouve["id"] for t in liste):
                            self._ecrire(liste)
                except OSError:
                    pass  # ne pas refuser un appui parce que le disque est plein
            return trouve["id"]

    def lister(self):
        with self._verrou:
            return [{k: t.get(k) for k in ("id", "nom", "cree", "vu")} for t in self._lire()]

    def revoquer(self, ident):
        with self._verrou, self._verrou_fichier():
            self._signature = None
            liste = self._lire()
            reste = [t for t in liste if t["id"] != ident]
            if len(reste) == len(liste):
                return False
            self._ecrire(reste)
            return True

    def revoquer_tout(self):
        with self._verrou, self._verrou_fichier():
            self._signature = None
            nombre = len(self._lire())
            self._ecrire([])
            return nombre


# ── Appairage ───────────────────────────────────────────────────────────────
class Appairage:
    """Le code à 6 chiffres affiché sur la TV, et la limite d'essais."""

    def __init__(self, horloge=time.time, au_changement=None):
        self.horloge = horloge
        self.au_changement = au_changement
        self._verrou = threading.RLock()
        self._essais = {}
        self._echecs = 0
        self.code = None
        self.expire_ms = 0
        # Pas de notification ici : le propriétaire n'est pas encore prêt à écrire
        # l'état (il n'a pas d'adresse). Il le publie lui-même une fois en écoute.
        self._tirer()

    def _tirer(self):
        ancien = self.code
        while self.code == ancien:
            self.code = f"{secrets.randbelow(1_000_000):06d}"
        self.expire_ms = int((self.horloge() + DUREE_CODE_S) * 1000)
        self._echecs = 0

    def renouveler(self):
        with self._verrou:
            self._tirer()
            if self.au_changement:
                self.au_changement()

    def verifier_expiration(self):
        with self._verrou:
            if self.horloge() * 1000 >= self.expire_ms:
                self.renouveler()
                return True
        return False

    def essayer(self, ip, code):
        with self._verrou:
            maintenant = self.horloge()
            self.verifier_expiration()
            if len(self._essais) > 1000:
                self._essais = {k: v for k, v in self._essais.items() if v and v[-1] > maintenant - 60}
            recents = self._essais.setdefault(ip, deque())
            while recents and recents[0] <= maintenant - 60:
                recents.popleft()
            # Compter AVANT de comparer, et compter aussi les réussites : sinon le
            # sixième essai d'une rafale serait encore évalué.
            if len(recents) >= ESSAIS_PAR_MINUTE:
                return TROP
            recents.append(maintenant)
            if isinstance(code, str) and re.fullmatch(r"\d{6}", code) \
                    and hmac.compare_digest(code, self.code):
                self.renouveler()
                return OK
            self._echecs += 1
            if self._echecs >= ECHECS_AVANT_RENOUVELLEMENT:
                journal.warning("%d codes faux : code renouvelé", self._echecs)
                self.renouveler()
            return MAUVAIS

    def attente_s(self, ip):
        with self._verrou:
            recents = self._essais.get(ip)
            if not recents:
                return 0
            return max(1, int(recents[0] + 60 - self.horloge()) + 1)


# ── Kodi ────────────────────────────────────────────────────────────────────
def appeler_kodi(methode, params=None, hote="127.0.0.1", port=9090, http=None,
                 identifiants=(None, None), delai=1.5, sans_reponse_ok=False):
    """Vrai si Kodi a accepté la requête JSON-RPC.

    TCP 9090 d'abord, pour la raison donnée dans hub_voix_logique.quitter_kodi_tcp :
    actif par défaut, local, sans mot de passe. Le serveur web (HTTP) ensuite, s'il
    a été activé. Sur TCP, Kodi pousse aussi ses notifications dans la même
    connexion : on lit jusqu'à la réponse qui porte notre identifiant.
    """
    ident = secrets.randbelow(1 << 30)
    requete = {"jsonrpc": "2.0", "method": methode, "id": ident}
    if params is not None:
        requete["params"] = params
    corps = json.dumps(requete).encode()
    try:
        with socket.create_connection((hote, port), timeout=delai) as s:
            s.sendall(corps)
            tampon, decodeur = "", json.JSONDecoder()
            fin = time.monotonic() + delai
            while time.monotonic() < fin:
                try:
                    morceau = s.recv(65536)
                except socket.timeout:
                    break
                if not morceau:
                    break
                tampon += morceau.decode("utf-8", errors="replace")
                while tampon.strip():
                    tampon = tampon.lstrip()
                    try:
                        objet, position = decodeur.raw_decode(tampon)
                    except ValueError:
                        break  # objet incomplet : lire la suite
                    tampon = tampon[position:]
                    if isinstance(objet, dict) and objet.get("id") == ident:
                        return "result" in objet
        # Kodi a pu se fermer avant de répondre à Application.Quit : la requête est partie.
        return sans_reponse_ok
    except OSError:
        pass
    if not http:
        return False
    entetes = {"Content-Type": "application/json"}
    utilisateur, mot_de_passe = identifiants
    if utilisateur:
        paire = f"{utilisateur}:{mot_de_passe or ''}".encode()
        entetes["Authorization"] = "Basic " + base64.b64encode(paire).decode()
    try:
        r = urllib.request.Request(http, data=corps, headers=entetes)
        with urllib.request.urlopen(r, timeout=delai) as reponse:
            return "result" in json.loads(reponse.read().decode("utf-8"))
    except (OSError, ValueError):
        return False


# ── Routage ─────────────────────────────────────────────────────────────────
class Routeur:
    """Décide où va une commande validée, et l'y envoie."""

    def __init__(self, socket_menu, executer=subprocess.run, processus=_processus,
                 kodi_hote="127.0.0.1", kodi_port=9090,
                 kodi_http=os.environ.get("HUB_KODI_HTTP", "http://127.0.0.1:8080/jsonrpc"),
                 kodi_identifiants=(os.environ.get("HUB_KODI_UTILISATEUR"),
                                    os.environ.get("HUB_KODI_MOT_DE_PASSE")),
                 tuer=os.kill):
        self.socket_menu = Path(socket_menu)
        self._executer = executer
        self.processus = processus
        self.kodi = dict(hote=kodi_hote, port=kodi_port, http=kodi_http,
                         identifiants=kodi_identifiants)
        self.tuer = tuer

    def lancer(self, commande):
        try:
            r = self._executer(commande, capture_output=True, text=True, timeout=5)
            return r
        except (OSError, subprocess.SubprocessError):
            return None

    def contexte(self):
        if self.socket_menu.is_socket():
            return "menu"
        if self.processus(NOMS_KODI):
            return "kodi"
        if self.processus(NOMS_BUREAU):
            return "bureau"
        return None

    def volume(self, sens):
        # -l 1.0 : jamais au-delà de 100 %. Au-delà, PipeWire amplifie en numérique et
        # sature — sur des enceintes de salon, c'est un grésillement à fond.
        r = self.lancer(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"5%{sens}"])
        if r is None or getattr(r, "returncode", 1) != 0:
            return {"ok": False, "cible": "volume", "raison": "volume-indisponible"}
        lu = self.lancer(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
        niveau = None
        trouve = re.search(r"Volume:\s*([0-9.]+)", getattr(lu, "stdout", "") or "")
        if trouve:
            niveau = round(float(trouve.group(1)) * 100)
        return {"ok": True, "cible": "volume", "volume": niveau,
                "muet": "[MUTED]" in (getattr(lu, "stdout", "") or "")}

    def quitter_kodi(self):
        """Du plus propre au plus brutal, comme hub-voix."""
        if appeler_kodi("Application.Quit", sans_reponse_ok=True, **self.kodi):
            return True
        # Kodi traite SIGTERM comme une demande de sortie (il enregistre ses réglages).
        pids = self.processus(NOMS_KODI)
        for pid in pids:
            try:
                self.tuer(pid, signal.SIGTERM)
            except OSError:
                pass
        return bool(pids)

    def executer(self, nom, texte=None):
        if nom not in COMMANDES:
            raise ValueError(nom)
        if nom in ("volume:+", "volume:-"):
            return self.volume(nom[-1])

        if self.socket_menu.is_socket():
            if nom == "texte":
                return {"ok": False, "cible": "menu", "raison": "texte-hors-kodi"}
            message = "retour" if nom == "accueil" else nom
            if _envoyer_menu(self.socket_menu, message):
                return {"ok": True, "cible": "menu"}
            # Socket présent mais muet : le menu est tombé sans nettoyer. On continue
            # comme s'il était fermé, sinon plus rien ne sortirait de Kodi.

        if nom == "eteindre":
            # Éteindre sans l'écran de confirmation du menu : jamais.
            return {"ok": False, "cible": None, "raison": "eteindre-depuis-le-menu"}

        if self.processus(NOMS_KODI):
            if nom in KODI_NAVIGATION:
                ok = appeler_kodi(KODI_NAVIGATION[nom], **self.kodi)
            elif nom == "texte":
                propre = "".join(c for c in (texte or "") if c.isprintable())
                if not propre.strip() or len(propre) > TAILLE_MAX_TEXTE:
                    return {"ok": False, "cible": "kodi", "raison": "texte-invalide"}
                # done=True valide le clavier de Kodi : c'est le geste attendu d'une
                # recherche (taper, puis lancer), et ça évite un OK de plus au pouce.
                ok = appeler_kodi("Input.SendText", {"text": propre, "done": True}, **self.kodi)
            elif nom == "accueil":
                ok = self.quitter_kodi()
            else:
                return {"ok": False, "cible": "kodi", "raison": "sans-effet-dans-kodi"}
            return {"ok": ok, "cible": "kodi", **({} if ok else {"raison": "kodi-injoignable"})}

        if self.processus(NOMS_BUREAU):
            if nom == "accueil":
                r = self.lancer(["gnome-session-quit", "--logout", "--no-prompt"])
                ok = r is not None and getattr(r, "returncode", 1) == 0
                return {"ok": ok, "cible": "bureau"}
            return {"ok": False, "cible": "bureau", "raison": "sans-effet-sur-le-bureau"}

        return {"ok": False, "cible": None, "raison": "rien-a-piloter"}


# ── La page ─────────────────────────────────────────────────────────────────
def empreinte_csp(bloc):
    return "'sha256-" + base64.b64encode(hashlib.sha256(bloc.encode("utf-8")).digest()).decode() + "'"


def charger_page(chemin=None):
    """(octets de la page, en-tête CSP). Lue une fois : rien d'autre ne vient du disque."""
    html = Path(chemin or ICI / "page.html").read_text(encoding="utf-8")
    sans_commentaires = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    scripts = re.findall(r"<script>(.*?)</script>", sans_commentaires, re.S)
    styles = re.findall(r"<style>(.*?)</style>", sans_commentaires, re.S)
    # Empreintes plutôt que 'unsafe-inline' : même si un texte renvoyé par le HUB
    # finissait un jour injecté dans la page, aucun script étranger ne s'exécuterait.
    csp = "; ".join([
        "default-src 'none'",
        "script-src " + " ".join(empreinte_csp(s) for s in scripts),
        "style-src " + " ".join(empreinte_csp(s) for s in styles),
        "connect-src 'self'",
        "img-src 'self' data:",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ])
    return html.encode("utf-8"), csp


def adresse_locale():
    """L'adresse IPv4 du HUB sur le réseau de la maison, ou None.

    Connecter un socket UDP n'envoie rien : le noyau choisit seulement l'interface de
    la route par défaut. Ce n'est ni docker0 ni la boucle locale, et c'est celle que
    le téléphone joint. On écoute sur elle seule plutôt que sur 0.0.0.0 : une autre
    interface (VPN, pont de VM) n'expose pas la télécommande.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            adresse = s.getsockname()[0]
    except OSError:
        return None
    ip = ipaddress.ip_address(adresse)
    return None if ip.is_loopback or ip.is_unspecified else adresse


def nom_du_telephone(nom, agent):
    if isinstance(nom, str):
        propre = "".join(c for c in nom if c.isprintable()).strip()[:TAILLE_MAX_NOM]
        if propre:
            return propre
    agent = agent or ""
    for motif, libelle in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
                           ("Macintosh", "Mac"), ("Windows", "Windows"), ("Linux", "Linux")):
        if motif in agent:
            return libelle
    return "Téléphone"


# ── Le service ──────────────────────────────────────────────────────────────
class Service:
    def __init__(self, chemins, routeur=None, horloge=time.time, page=None):
        self.chemins = chemins
        self.horloge = horloge
        self.jetons = Jetons(chemins["jetons"], horloge=horloge)
        self.routeur = routeur or Routeur(chemins["socket"])
        self.page, self.csp = charger_page(page)
        self.url = None
        self.hotes_admis = frozenset()
        self.appairage_le = None
        self._verrou_etat = threading.Lock()
        self.appairage = Appairage(horloge=horloge, au_changement=self.ecrire_etat)

    def publier(self, adresse, port):
        self.url = f"http://{adresse}:{port}/"
        nom = socket.gethostname().lower()
        self.hotes_admis = frozenset({f"{adresse}:{port}", f"{nom}:{port}", f"{nom}.local:{port}"})
        self.ecrire_etat()

    def ecrire_etat(self):
        """Ce que la TV affiche : URL (pour le QR code), code, expiration."""
        if not self.url:
            return
        etat = {"url": self.url, "code": self.appairage.code, "expire": self.appairage.expire_ms,
                "telephones": len(self.jetons.lister()), "appairageLe": self.appairage_le}
        with self._verrou_etat:
            try:
                ecrire_prive(self.chemins["etat"], json.dumps(etat))
            except OSError as erreur:
                journal.error("état non écrit (%s) : la TV n'affichera pas le code", erreur)

    def effacer_etat(self):
        # Un QR code vers un service arrêté enverrait le téléphone dans le vide.
        Path(self.chemins["etat"]).unlink(missing_ok=True)


def enregistrer_photo(dossier, octets, maintenant):
    """Nom du fichier écrit. Le nom vient d'ici, jamais du téléphone : aucun chemin
    fourni par le réseau ne touche le disque."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    base = time.strftime("telephone-%Y%m%d-%H%M%S", time.localtime(maintenant))
    provisoire = dossier / f".{base}.{secrets.token_hex(4)}.tmp"
    fd = os.open(provisoire, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(octets)
            f.flush()
            os.fsync(f.fileno())
        # link() échoue si le nom existe : deux photos dans la même seconde ne
        # s'écrasent pas, et le menu ne voit jamais un fichier à moitié écrit.
        for rang in range(1, 100):
            nom = f"{base}.jpg" if rang == 1 else f"{base}-{rang}.jpg"
            try:
                os.link(provisoire, dossier / nom)
                return nom
            except FileExistsError:
                continue
        raise OSError("trop de photos dans la même seconde")
    finally:
        provisoire.unlink(missing_ok=True)


def _gestionnaire(service):
    class Gestionnaire(BaseHTTPRequestHandler):
        server_version = "HUB"
        sys_version = ""
        # Un client qui ouvre une connexion et n'envoie rien ne doit pas garder un fil.
        timeout = 10

        def log_message(self, fmt, *args):
            journal.debug("%s %s", self.client_address[0], fmt % args)

        def end_headers(self):
            # Sur TOUTES les réponses, y compris les erreurs produites par http.server.
            self.send_header("Content-Security-Policy", service.csp)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _repondre(self, statut, corps, type_contenu, entetes=None):
            self.send_response(statut)
            self.send_header("Content-Type", type_contenu)
            self.send_header("Content-Length", str(len(corps)))
            for cle, valeur in (entetes or {}).items():
                self.send_header(cle, valeur)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(corps)

        def _json(self, statut, valeur, entetes=None):
            self._repondre(statut, json.dumps(valeur, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8", entetes)

        def _admis(self):
            # Rebinding DNS : un site d'Internet peut faire pointer son nom sur l'IP du
            # HUB, et sa page parlerait alors à la télécommande depuis le navigateur
            # d'un téléphone de la maison. Son Host reste le sien : on le refuse.
            hote = (self.headers.get("Host") or "").strip().lower()
            if hote not in service.hotes_admis:
                self._json(421, {"erreur": "hote"})
                return False
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                self._json(403, {"erreur": "origine"})
                return False
            return True

        def _chemin(self):
            return self.path.split("?", 1)[0]

        def _jeton(self):
            entete = self.headers.get("Authorization") or ""
            if not entete.startswith("Bearer "):
                return None
            return service.jetons.valide(entete[7:].strip())

        def do_GET(self):
            if not self._admis():
                return
            chemin = self._chemin()
            if chemin == "/":
                return self._repondre(200, service.page, "text/html; charset=utf-8")
            if chemin == "/api/etat":
                if not self._jeton():
                    return self._json(401, {"erreur": "jeton"})
                return self._json(200, {"ok": True, "contexte": service.routeur.contexte()})
            self._json(404, {"erreur": "introuvable"})

        def do_HEAD(self):
            self.do_GET()

        def _refuser_methode(self):
            self._json(405, {"erreur": "methode"}, {"Allow": "GET, POST"})

        do_OPTIONS = do_PUT = do_DELETE = do_PATCH = _refuser_methode

        def _longueur(self, maximum):
            """Longueur annoncée du corps, ou None après avoir répondu l'erreur."""
            try:
                longueur = int(self.headers.get("Content-Length") or "")
            except ValueError:
                self._json(411, {"erreur": "longueur"})
                return None
            if longueur < 0 or longueur > maximum:
                # On vide un corps modérément trop gros pour que le client lise la
                # réponse au lieu d'une connexion coupée ; au-delà, on coupe.
                if 0 < longueur <= 4 * maximum:
                    restant = longueur
                    while restant > 0:
                        lu = self.rfile.read(min(restant, 65536))
                        if not lu:
                            break
                        restant -= len(lu)
                self.close_connection = True
                self._json(413, {"erreur": "trop-gros"})
                return None
            return longueur

        def _type(self):
            return (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()

        def _corps(self):
            """Le JSON du corps, ou None après avoir répondu l'erreur."""
            # application/json impose un prévol CORS à toute page étrangère ; ce
            # service n'y répond jamais favorablement. Un formulaire HTML ne peut pas
            # envoyer ce type : il n'atteint donc pas la logique.
            if self._type() != "application/json":
                self._json(415, {"erreur": "type"})
                return None
            longueur = self._longueur(TAILLE_MAX_CORPS)
            if longueur is None:
                return None
            try:
                valeur = json.loads(self.rfile.read(longueur).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._json(400, {"erreur": "json"})
                return None
            if not isinstance(valeur, dict):
                self._json(400, {"erreur": "json"})
                return None
            return valeur

        def do_POST(self):
            if not self._admis():
                return
            chemin = self._chemin()
            if chemin == "/api/appairer":
                return self._appairer()
            if chemin == "/api/commande":
                return self._commande()
            if chemin == "/photo-profil":
                return self._photo()
            if chemin == "/api/oublier":
                return self._oublier()
            self._json(404, {"erreur": "introuvable"})

        def _appairer(self):
            corps = self._corps()
            if corps is None:
                return
            ip = self.client_address[0]
            resultat = service.appairage.essayer(ip, corps.get("code"))
            if resultat == TROP:
                attente = service.appairage.attente_s(ip)
                journal.warning("appairage : trop d'essais depuis %s", ip)
                return self._json(429, {"erreur": "trop", "attente": attente},
                                  {"Retry-After": str(attente)})
            if resultat != OK:
                journal.info("appairage : code faux depuis %s", ip)
                return self._json(403, {"erreur": "code"})
            nom = nom_du_telephone(corps.get("nom"), self.headers.get("User-Agent"))
            ident, jeton = service.jetons.creer(nom)
            service.appairage_le = int(service.horloge() * 1000)
            service.ecrire_etat()
            journal.info("appairage : %s (%s) depuis %s", nom, ident, ip)
            self._json(200, {"jeton": jeton, "id": ident, "nom": nom})

        def _oublier(self):
            # « Oublier ce téléphone » révoque vraiment son jeton : effacer seulement le
            # localStorage laisserait un jeton valide dans une sauvegarde du navigateur.
            ident = self._jeton()
            if not ident:
                return self._json(401, {"erreur": "jeton"})
            if self._corps() is None:
                return
            service.jetons.revoquer(ident)
            service.ecrire_etat()
            journal.info("téléphone %s oublié à sa demande", ident)
            self._json(200, {"ok": True})

        def _photo(self):
            if not self._jeton():
                return self._json(401, {"erreur": "jeton"})
            # image/jpeg n'est pas un type « simple » pour CORS : même garde que le JSON.
            if self._type() != "image/jpeg":
                return self._json(415, {"erreur": "type"})
            longueur = self._longueur(TAILLE_MAX_PHOTO)
            if longueur is None:
                return
            octets = self.rfile.read(longueur)
            # Les octets magiques et rien d'autre : le type annoncé ne prouve rien, et
            # le menu affichera ce fichier. Le téléphone réencode toujours en JPEG,
            # donc un PNG ou un HEIC ici n'est pas un téléphone qui suit la page.
            if len(octets) != longueur or not octets.startswith(b"\xff\xd8\xff"):
                return self._json(400, {"erreur": "jpeg"})
            try:
                nom = enregistrer_photo(service.chemins["photos"], octets, service.horloge())
            except OSError as erreur:
                journal.error("photo non enregistrée : %s", erreur)
                return self._json(500, {"erreur": "disque"})
            journal.info("photo de profil reçue : %s (%d octets)", nom, len(octets))
            socket_menu = Path(service.chemins["socket"])
            if socket_menu.is_socket():
                # Le menu relit ses images et la nouvelle apparaît dans l'éditeur de profil.
                _envoyer_menu(socket_menu, "avatars")
            self._json(200, {"ok": True, "fichier": nom})

        def _commande(self):
            if not self._jeton():
                return self._json(401, {"erreur": "jeton"})
            corps = self._corps()
            if corps is None:
                return
            nom, texte = corps.get("nom"), corps.get("texte")
            if not isinstance(nom, str) or nom not in COMMANDES:
                return self._json(400, {"erreur": "commande"})
            if nom == "texte" and not isinstance(texte, str):
                return self._json(400, {"erreur": "texte"})
            try:
                resultat = service.routeur.executer(nom, texte if nom == "texte" else None)
            except Exception:  # noqa: BLE001
                journal.exception("commande %s", nom)
                return self._json(500, {"erreur": "interne"})
            journal.debug("commande %s → %s", nom, resultat)
            self._json(200, resultat)

    return Gestionnaire


class Serveur(ThreadingHTTPServer):
    daemon_threads = True
    # Pas de SO_REUSEPORT : un second service lancé par erreur doit échouer bruyamment
    # plutôt que se partager les requêtes avec le premier.
    allow_reuse_address = True


def creer_serveur(service, adresse, port):
    serveur = Serveur((adresse, port), _gestionnaire(service))
    service.publier(adresse, serveur.server_address[1])
    return serveur


# ── Ligne de commande ───────────────────────────────────────────────────────
def _date(ms):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime((ms or 0) / 1000)) if ms else "—"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Télécommande téléphone du HUB.")
    parser.add_argument("--port", type=int, default=PORT, help=f"port d'écoute (défaut {PORT})")
    parser.add_argument("--adresse", help="adresse d'écoute forcée (défaut : celle du réseau local)")
    parser.add_argument("--lister", action="store_true", help="téléphones appairés")
    parser.add_argument("--revoquer", metavar="ID", help="retirer un téléphone")
    parser.add_argument("--revoquer-tout", action="store_true", help="retirer tous les téléphones")
    parser.add_argument("-v", "--verbeux", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbeux else logging.INFO,
                        format="%(levelname)s %(message)s", stream=sys.stderr)
    chemins = chemins_par_defaut()

    if args.lister or args.revoquer or args.revoquer_tout:
        jetons = Jetons(chemins["jetons"])
        if args.revoquer:
            if not jetons.revoquer(args.revoquer):
                print(f"aucun téléphone « {args.revoquer} »", file=sys.stderr)
                return 1
            print(f"téléphone {args.revoquer} révoqué")
        if args.revoquer_tout:
            print(f"{jetons.revoquer_tout()} téléphone(s) révoqué(s)")
        if args.lister:
            liste = jetons.lister()
            if not liste:
                print("aucun téléphone appairé")
            for t in liste:
                print(f"{t['id']}  {t['nom'] or '?':<20}  appairé {_date(t['cree'])}  vu {_date(t['vu'])}")
        return 0

    if not VOIX:
        journal.warning("hub_voix_logique introuvable : seul le menu est pilotable "
                        "(ni Kodi ni le bureau quand le menu est fermé)")
    service = Service(chemins)
    arret = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: arret.set())
    signal.signal(signal.SIGINT, lambda *_: arret.set())

    signale_sans_reseau = False
    while not arret.is_set():
        adresse = args.adresse or adresse_locale()
        if not adresse:
            # Au démarrage de la session, le réseau n'est souvent pas encore là.
            if not signale_sans_reseau:
                journal.info("pas encore d'adresse sur le réseau local : on attend")
                signale_sans_reseau = True
            service.effacer_etat()
            arret.wait(5)
            continue
        signale_sans_reseau = False
        try:
            serveur = creer_serveur(service, adresse, args.port)
        except OSError as erreur:
            journal.error("écoute impossible sur %s:%s (%s)", adresse, args.port, erreur)
            service.effacer_etat()
            arret.wait(5)
            continue
        fil = threading.Thread(target=serveur.serve_forever, daemon=True)
        fil.start()
        journal.info("télécommande sur %s", service.url)
        while not arret.wait(5):
            service.appairage.verifier_expiration()
            # Bail DHCP renouvelé sur une autre adresse : on rouvre l'écoute dessus,
            # sinon le QR code montrerait une adresse morte jusqu'au prochain démarrage.
            if not args.adresse and adresse_locale() != adresse:
                journal.info("l'adresse a changé : réouverture de l'écoute")
                break
        serveur.shutdown()
        serveur.server_close()
    service.effacer_etat()
    return 0


if __name__ == "__main__":
    sys.exit(main())
