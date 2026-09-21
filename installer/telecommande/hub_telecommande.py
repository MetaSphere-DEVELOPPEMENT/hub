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
jeton ne s'obtient qu'avec le code affiché sur la TV, donc en étant dans la pièce, et
seulement pendant que l'écran d'appairage est ouvert. Le code change à chaque
démarrage, après chaque usage, toutes les 5 minutes et à la fermeture de l'écran ;
5 essais par minute par adresse, et un délai croissant après chaque code faux, toutes
adresses confondues. Les commandes sont une liste blanche, la page est la seule chose
servie, et l'en-tête Host est vérifié contre le rebinding DNS.

OÙ VONT LES COMMANDES. Menu ouvert : au socket du menu, exactement comme la voix.
Menu fermé : à Kodi (navigation, texte, quitter) s'il tourne, sinon à la session
bureau (« Accueil » la ferme). « Éteindre » ne part jamais ailleurs qu'au menu, qui
demande confirmation sur la TV.

HORS DU MENU ET DE KODI (service web en plein écran, bureau), plus rien n'écoute : le
téléphone devient alors un clavier et une souris (hub_pointeur.py, /dev/uinput). C'est
le plus gros pouvoir que ce service donne, et il n'est donné qu'à toutes ces conditions
réunies (classe Pointeur) : interrupteur allumé sur la TV, connexion https, jeton obtenu
en tapant le code de la TV en https, CE téléphone autorisé nommément depuis Réglages →
Télécommande (refusé par défaut à l'appairage), session au premier plan et déverrouillée.
"""

import argparse
import base64
import fcntl
import hashlib
import hmac
import importlib.util
import io
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import select
import shutil
import signal
import socket
import ssl
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
import zlib
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ICI = Path(__file__).resolve().parent

# 8790 : libre sur Ubuntu (ni Kodi 8080/9090, ni CUPS, ni rien d'enregistré à l'IANA
# qu'on trouverait sur une machine de salon). Fixe, parce que l'URL finit dans les
# favoris des téléphones — et le jeton est lié à l'origine http://ip:port.
PORT = 8790
# Le HTTPS sur le port suivant. Un second port plutôt qu'une bascule du premier : le
# QR code et les favoris existants (http://ip:8790) doivent continuer de marcher sur
# un téléphone qui n'a pas installé le certificat — c'est le cas le plus courant.
PORT_HTTPS = 8791

DUREE_CODE_S = 5 * 60
ESSAIS_PAR_MINUTE = 5
# Cinq essais par adresse ne protègent rien contre un appareil qui en prend deux cents
# sur le réseau (audit du 17/09/2026 : ~50 % de chances en 9 h). La vraie limite est
# donc globale : après ECHECS_LIBRES codes faux, toutes adresses confondues, chaque
# essai suivant attend 2, 4, 8… jusqu'à DELAI_MAX_S secondes. Au plus une douzaine
# d'essais par fenêtre d'appairage de 5 minutes, soit ~1 chance sur 80 000 ; une faute
# de frappe en famille ne coûte, elle, que quelques secondes.
ECHECS_LIBRES = 3
DELAI_MAX_S = 60
# Une série d'échecs s'oublie après un quart d'heure calme : l'invité maladroit d'hier
# ne ralentit pas l'appairage d'aujourd'hui.
OUBLI_ECHECS_S = 15 * 60
# Renouveler le code change peu aux chances d'un attaquant, mais un code qui a subi
# vingt essais n'a plus rien à faire à l'écran.
ECHECS_AVANT_RENOUVELLEMENT = 20
# L'appairage n'est accepté que pendant une fenêtre ouverte par le menu (l'écran
# « Télécommande » affiché) ou par `hub-telecommande --appairage` : le reste du temps,
# un code deviné ne sert à rien. Le menu (re)touche le fichier tant que l'écran est
# affiché ; oublié, le fichier ne vaut plus rien au bout de ce délai.
FENETRE_APPAIRAGE_S = 5 * 60
# Au-delà de ce nombre de photos ou de cette taille (celles écrites par ce service
# seulement), on refuse : un téléphone appairé ne doit pas pouvoir remplir le disque.
# Une photo de profil pèse 60 à 150 Ko : 50 photos, c'est des années de profils.
PHOTOS_MAX = 50
PHOTOS_TAILLE_MAX = 50 * 1024 * 1024
# Et jamais quand il resterait moins que ceci : Kodi, les journaux et les mises à jour
# ont besoin du disque plus que la dixième photo de profil.
ESPACE_LIBRE_MIN = 512 * 1024 * 1024
# Des fils de connexion bornés : sans plafond, un appareil qui ouvre des milliers de
# connexions muettes fait créer autant de fils (mémoire, puis plus rien ne répond).
# 8 par adresse : un téléphone en ouvre 2 ou 3 à la fois (page, sonde, icônes).
MAX_CONNEXIONS = 32
MAX_CONNEXIONS_PAR_IP = 8
TAILLE_MAX_CORPS = 2048
# Une photo recadrée à 512 px en JPEG 0,88 pèse 60 à 150 Ko : 2 Mio laisse de la marge
# à un navigateur qui compresse mal, sans laisser remplir le disque par rafales.
TAILLE_MAX_PHOTO = 2 * 1024 * 1024
TAILLE_MAX_TEXTE = 300
TAILLE_MAX_NOM = 40
# Réécrire le fichier des jetons à chaque appui userait le disque pour rien : la date
# de dernier usage ne sert qu'à reconnaître un vieux téléphone à révoquer.
PRECISION_VU_S = 3600
# Un téléphone jamais revu depuis six mois n'est celui de personne : il part au ménage,
# plutôt que d'allonger la liste pour toujours. Six mois, parce qu'un téléphone de
# vacances qu'on ressort l'été suivant doit encore s'y retrouver.
OUBLI_TELEPHONE_S = 180 * 24 * 3600
# Et jamais plus que ceci : au-delà, le moins récemment vu part. Une famille et ses
# invités tiennent largement ; une liste qui déborde cache les vrais téléphones.
TELEPHONES_MAX = 20
# Un même téléphone tient deux jetons à la fois : celui de http://ip:8790 et celui de
# https://nom:8791 (deux origines pour le navigateur, un seul appareil). Quatre laisse
# la place à un favori resté sur l'ancien nom, sans faire une liste de jetons morts.
EMPREINTES_PAR_TELEPHONE = 4

# ── Souris et clavier (hors du menu et de Kodi) ──
# Le ticket qui ouvre le WebSocket : un navigateur ne peut pas joindre d'en-tête
# Authorization à un WebSocket, et un jeton dans l'URL finirait dans les journaux.
# La page échange donc son jeton contre un ticket à usage unique, qu'elle présente
# aussitôt : trente secondes suffisent, même sur un wifi lent.
DUREE_TICKET_POINTEUR_S = 30
# Une page envoie au plus un déplacement par image (60 par seconde) : 120 laisse passer
# un écran à 120 Hz, et la réserve absorbe une rafale après un à-coup du wifi. Au-delà,
# ce n'est pas un doigt, et les déplacements en trop sont jetés (jamais mis en file :
# une souris qui rattrape son retard est pire qu'une souris qui saute).
MOUVEMENTS_PAR_S = 120
MOUVEMENTS_RESERVE = 240
# Frappes, clics et caractères d'un texte partagent ce seau : 30 par seconde, c'est
# trois fois un très bon dactylo ; la réserve laisse passer d'un coup le plus long
# texte permis (TAILLE_MAX_TEXTE) avec ses touches mortes.
FRAPPES_PAR_S = 30
FRAPPES_RESERVE = 400
# Un déplacement par message : borné, pour qu'un message forgé ne fasse pas traverser
# quatre écrans au pointeur (un glissement réel fait au plus ~150 points par image).
DEPLACEMENT_MAX = 400
DEFILEMENT_MAX = 1200
# Le plus gros message légitime est un texte de 300 caractères (4 octets chacun au pire).
TRAME_POINTEUR_MAX = 2048
# Quelques messages mal formés, c'est une vieille page en cache ; davantage, ce n'est
# pas la page.
ERREURS_POINTEUR_MAX = 5
SESSIONS_POINTEUR_MAX = 4

OK, MAUVAIS, TROP, FERME = "ok", "mauvais", "trop", "ferme"

# Les noms du protocole du socket du menu (hub-menu.py, COMMANDES), recopiés et non
# importés : importer hub-menu.py tirerait sa logique entière dans un service réseau.
# test_telecommande.py vérifie qu'ils sont identiques.
COMMANDES_MENU = frozenset({
    "tv", "gaming", "bureau", "eteindre", "reglages", "aide", "meteo", "profils",
    "retour", "gauche", "droite", "haut", "bas", "ok", "theme:clair", "theme:sombre",
    "web:youtube", "web:netflix", "web:primevideo", "web:disneyplus", "web:canalplus",
    "web:twitch", "web:arte", "web:francetv", "web:geforcenow", "web:xcloud",
    "web:boosteroid", "web:steam", "web:moonlight",
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


def _charger_pointeur():
    """hub_pointeur.py, posé à côté de ce fichier. Absent (installation à moitié mise à
    jour) ou illisible : la télécommande vit sans souris, et la page dit pourquoi."""
    if "hub_pointeur" in sys.modules:
        # Déjà chargé (les tests l'importent avant) : le même module, sinon ses
        # exceptions ne seraient pas celles qu'on attrape ici.
        return sys.modules["hub_pointeur"]
    fichier = ICI / "hub_pointeur.py"
    try:
        spec = importlib.util.spec_from_file_location("hub_pointeur", fichier)
        module = importlib.util.module_from_spec(spec)
        sys.modules["hub_pointeur"] = module
        spec.loader.exec_module(module)
        return module
    except Exception as erreur:  # noqa: BLE001
        sys.modules.pop("hub_pointeur", None)
        journal.warning("hub_pointeur illisible (%s) : ni souris ni clavier", erreur)
        return None


POINTEUR = _charger_pointeur()


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


# ── Dictée : la reconnaissance de hub-voix, dans un processus à part ──────────
# POURQUOI « MAINTENIR POUR PARLER » ET VOSK SUR LE HUB, PLUTÔT QUE LA RECONNAISSANCE
# DU NAVIGATEUR (Web Speech API).
# - Même chemin sur Android et iPhone : la page capture le son (Web Audio), le HUB
#   reconnaît. La Web Speech API envoie la voix aux serveurs de Google (Chrome) ou
#   d'Apple (Safari), et sur iPhone elle est capricieuse dans une app d'écran d'accueil.
# - Hors ligne et fidèle au HUB : même modèle, même grammaire restreinte et même
#   analyse que la commande vocale du salon (installer/voix), donc les mêmes phrases.
# - Les deux exigent de toute façon le contexte sécurisé (le micro) : HTTPS local.
#
# POURQUOI UN PROCESSUS À PART. Vosk vit dans le venv de hub-voix (/opt/hub-voix/venv),
# pas dans le Python du système qui fait tourner ce service ; et un modèle de 150 Mo
# en mémoire n'a rien à faire dans le service réseau quand personne ne dicte. Le
# travailleur est ce même fichier lancé par le Python du venv, qui importe hub-voix.py
# (sa classe Reconnaisseur) ; il est démarré à la première dictée et arrêté après
# 5 minutes sans.
TAUX_DICTEE = 16000
DUREE_MAX_DICTEE_S = 10
TAILLE_MAX_DICTEE = TAUX_DICTEE * 2 * DUREE_MAX_DICTEE_S + 4096
DUREE_MIN_DICTEE_S = 0.25
INACTIVITE_DICTEE_S = 300
# Le premier appel charge le modèle : ~1 s sur la machine de développement, bien plus
# sur un HUB occupé à décoder une vidéo.
DELAI_DICTEE_S = 30


class DicteeIndisponible(Exception):
    pass


def _fichier_voix(nom):
    for dossier in (os.environ.get("HUB_VOIX_DOSSIER"), ICI.parent / "voix", "/usr/local/lib/hub/voix",
                    "/opt/hub-voix"):
        if dossier and (Path(dossier) / nom).is_file():
            return Path(dossier) / nom
    return None


def _python_voix():
    for candidat in (os.environ.get("HUB_VOIX_PYTHON"), "/opt/hub-voix/venv/bin/python"):
        if candidat and os.access(candidat, os.X_OK):
            return candidat
    return sys.executable


def pcm_de_wav(octets):
    """PCM 16 kHz mono 16 bits d'un WAV, ou ValueError. La page n'envoie que ce format :
    rien à convertir, donc ni ffmpeg ni décodeur de conteneur exposé au réseau."""
    try:
        with wave.open(io.BytesIO(octets), "rb") as w:
            if (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getcomptype()) != \
                    (TAUX_DICTEE, 1, 2, "NONE"):
                raise ValueError("format")
            pcm = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as erreur:
        raise ValueError(str(erreur)) from None
    if len(pcm) % 2:
        raise ValueError("format")
    return pcm


class Dicteur:
    def __init__(self, python=None, script=None, modeles=None, horloge=time.monotonic):
        self.python = python or _python_voix()
        self.script = script or _fichier_voix("hub-voix.py")
        self.modeles = modeles or os.environ.get("HUB_VOIX_MODELES")
        self.horloge = horloge
        self._verrou = threading.Lock()
        self._processus = None
        self._dernier = 0.0

    def _lancer(self):
        if not self.script:
            raise DicteeIndisponible("hub-voix-absent")
        commande = [self.python, str(ICI / "hub_telecommande.py"), "--travailleur-dictee", str(self.script)]
        if self.modeles:
            commande += ["--modeles", str(self.modeles)]
        try:
            self._processus = subprocess.Popen(commande, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        except OSError as erreur:
            raise DicteeIndisponible(f"lancement : {erreur}") from None
        journal.info("dictée : reconnaisseur lancé (%s)", self.python)

    def _arreter(self):
        p, self._processus = self._processus, None
        if p is None:
            return
        try:
            p.stdin.close()
            p.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            p.kill()

    def reconnaitre(self, pcm, langue):
        with self._verrou:
            self._dernier = self.horloge()
            if self._processus is None or self._processus.poll() is not None:
                self._processus = None
                self._lancer()
            p = self._processus
            try:
                p.stdin.write(json.dumps({"langue": langue, "octets": len(pcm)}).encode() + b"\n" + pcm)
                p.stdin.flush()
                pret, _, _ = select.select([p.stdout], [], [], DELAI_DICTEE_S)
                ligne = p.stdout.readline() if pret else b""
            except OSError:
                ligne = b""
            if not ligne:
                # Mort ou muet : on le remplace à la prochaine dictée plutôt que de
                # laisser un travailleur coincé répondre au mauvais appel.
                self._arreter()
                raise DicteeIndisponible("reconnaisseur-muet")
            reponse = json.loads(ligne)
            if "erreur" in reponse:
                if reponse["erreur"] == "vosk-absent":
                    self._arreter()
                raise DicteeIndisponible(reponse["erreur"])
            return reponse.get("texte") or ""

    def entretien(self):
        with self._verrou:
            if self._processus and self.horloge() - self._dernier > INACTIVITE_DICTEE_S:
                journal.info("dictée : reconnaisseur arrêté (inactif)")
                self._arreter()

    def arreter(self):
        with self._verrou:
            self._arreter()


def travailleur_dictee(script, modeles=None):
    """Boucle du processus reconnaisseur : une ligne JSON {langue, octets} suivie des
    octets PCM, une ligne JSON {texte} ou {erreur} en réponse."""
    entree, sortie = sys.stdin.buffer, sys.stdout.buffer

    def repondre(valeur):
        sortie.write(json.dumps(valeur, ensure_ascii=False).encode("utf-8") + b"\n")
        sortie.flush()

    erreur, voix, reconnaisseur = None, None, None
    try:
        spec = importlib.util.spec_from_file_location("hub_voix", script)
        voix = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(voix)
        reconnaisseur = voix.Reconnaisseur(modeles or voix.DOSSIER_MODELES)
    except ImportError:
        erreur = "vosk-absent"
    except Exception as e:  # noqa: BLE001
        erreur = f"hub-voix : {e}"
    while True:
        ligne = entree.readline()
        if not ligne:
            return 0
        try:
            demande = json.loads(ligne)
            pcm = entree.read(int(demande["octets"]))
        except (ValueError, KeyError, TypeError):
            return 1  # flux désynchronisé : le service relancera un travailleur propre
        if erreur:
            repondre({"erreur": erreur})
            continue
        langue = demande.get("langue") if demande.get("langue") in voix.L.LANGUES else voix.L.LANGUE_PAR_DEFAUT
        if not reconnaisseur.disponible(langue):
            repondre({"erreur": "modele-absent"})
            continue
        reconnaisseur.choisir(langue)
        textes = []
        # Par blocs de 0,2 s, exactement comme le micro du salon : même découpage des
        # phrases, donc mêmes résultats que hub-voix.py --fichier.
        for debut in range(0, len(pcm), voix.BLOC):
            texte = reconnaisseur.accepter(pcm[debut:debut + voix.BLOC])
            if texte:
                textes.append(texte)
        fin = reconnaisseur.terminer()
        if fin:
            textes.append(fin)
        repondre({"texte": " ".join(textes)})


# ── Fichiers ────────────────────────────────────────────────────────────────
def chemins_par_defaut():
    maison = Path.home()
    execution = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "hub"
    config = Path(os.environ.get("XDG_CONFIG_HOME") or maison / ".config") / "hub"
    return {
        "etat": execution / "telecommande.json",
        # Fenêtre d'appairage : présent et touché depuis moins de FENETRE_APPAIRAGE_S.
        "appairage": execution / "telecommande-appairage",
        "socket": execution / "menu.sock",
        "jetons": config / "telecommande-jetons.json",
        # Autorité locale et certificat du HUB. Dans ~/.config et non /etc : le service
        # est une unité utilisateur, et la clé ne doit appartenir qu'à cet utilisateur.
        "tls": config / "telecommande-tls",
        "reglages": config / "reglages.json",
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


def appareil_propre(valeur):
    """L'identifiant d'appareil présenté par le téléphone, ou None s'il n'a pas la
    forme attendue. Ce n'est PAS une preuve d'identité : c'est un secret de 128 bits
    tiré par le HUB puis rendu au téléphone, qui le range à côté de son jeton. Il sert
    seulement à reconnaître « le même téléphone » quand celui-ci a perdu son jeton et
    retape le code de la TV ; rien ne l'accepte sans cette preuve-là."""
    return valeur if isinstance(valeur, str) and re.fullmatch(r"[0-9a-f]{32}", valeur) else None


def _entree_lue(t):
    """Une ligne du fichier, normalisée, ou None si elle n'ouvre rien.

    Les fichiers d'avant le 18/09/2026 portaient une empreinte unique (« empreinte »)
    et pas d'appareil : ils continuent de marcher, le téléphone garde son entrée."""
    if not isinstance(t, dict) or not isinstance(t.get("id"), str) or not t["id"]:
        return None
    empreintes = t.get("empreintes")
    if not isinstance(empreintes, list):
        empreintes = [t.get("empreinte")]
    empreintes = [e for e in empreintes if isinstance(e, str) and e][:EMPREINTES_PAR_TELEPHONE]
    if not empreintes:
        return None
    # « sures » : les empreintes des jetons délivrés contre le code de la TV tapé EN
    # HTTPS (voir Jetons.creer). Absent des fichiers d'avant : aucun jeton n'est sûr.
    sures = t.get("sures") if isinstance(t.get("sures"), list) else []
    # « pointeurAutorise » : le droit à la souris et au clavier, accordé À CE TÉLÉPHONE
    # depuis Réglages → Télécommande — pas seulement « ce téléphone peut, s'il retape le
    # code en https » (ça, c'est `sures`). Absent des fichiers d'avant cette version, et
    # pour tout nouveau téléphone : refusé, jusqu'à un geste explicite devant la TV. Le
    # premier terrain, être dans la pièce pour lire le code, protège l'appairage ; celui-
    # ci protège le clavier, le plus gros pouvoir de ce service (voir Pointeur, plus bas).
    return {"id": t["id"], "nom": t.get("nom"), "appareil": appareil_propre(t.get("appareil")),
            "cree": t.get("cree"), "vu": t.get("vu"), "empreintes": empreintes,
            "sures": [e for e in sures if e in empreintes],
            "pointeurAutorise": t.get("pointeurAutorise") is True}


class Jetons:
    """Les téléphones appairés, relus dès que le fichier change.

    Relire à chaque vérification (un stat, rien de plus s'il n'a pas bougé) rend la
    révocation immédiate : `--revoquer` écrit le fichier, le service en cours le voit
    à la requête suivante, sans redémarrage.

    UNE ENTRÉE PAR TÉLÉPHONE, PAS PAR APPAIRAGE. Ré-appairer le même téléphone
    renouvelle son secret dans son entrée (même identifiant, même date d'appairage) au
    lieu d'en ajouter une : sinon un téléphone qu'on relie trois fois compte trois fois
    et remplit la liste. Le « même téléphone » n'est jamais cru sur parole : c'est
    celui qui présente son jeton précédent, ou celui dont l'identifiant d'appareil
    accompagne un code juste lu sur la TV (voir `creer`).
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
            liste = [e for e in (_entree_lue(t) for t in donnees.get("telephones", [])) if e]
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

    @staticmethod
    def _oubliees(liste, maintenant):
        """Ce qui reste après l'oubli des téléphones jamais revus depuis six mois."""
        limite = maintenant - OUBLI_TELEPHONE_S * 1000
        return [t for t in liste if int(t.get("vu") or t.get("cree") or 0) >= limite]

    @staticmethod
    def _plafonnee(liste, garder):
        """Au-delà du plafond, le moins récemment vu part — jamais celui qu'on vient
        de reconnaître, sinon appairer un téléphone pourrait l'effacer lui-même."""
        trop = len(liste) - TELEPHONES_MAX
        if trop <= 0:
            return liste
        ordre = sorted(liste, key=lambda t: (t is garder, int(t.get("vu") or 0)))
        partent = {id(t) for t in ordre[:trop]}
        return [t for t in liste if id(t) not in partent]

    def _copie(self):
        return [dict(t, empreintes=list(t["empreintes"]), sures=list(t["sures"])) for t in self._lire()]

    def menage(self):
        """Nombre de téléphones oubliés. Appelé au démarrage du service et à chaque
        appairage : la liste ne grandit pas toute seule pour l'éternité."""
        maintenant = int(self.horloge() * 1000)
        with self._verrou, self._verrou_fichier():
            self._signature = None
            liste = self._copie()
            reste = self._oubliees(liste, maintenant)
            if len(reste) == len(liste):
                return 0
            self._ecrire(reste)
            return len(liste) - len(reste)

    def creer(self, nom, remplace=None, appareil=None, ajouter=False, sure=False, presente=None):
        """(identifiant, jeton, appareil) du téléphone appairé.

        `remplace` : l'identifiant d'une entrée dont l'appelant a la preuve — le jeton
        précédent présenté à l'appairage, ou le ticket de transfert http → https.
        `appareil` : l'identifiant rendu au téléphone au dernier appairage, qu'il
        renvoie après avoir retapé le code de la TV. Dans les deux cas l'entrée est
        renouvelée sur place (même identifiant, même date d'appairage) ; sinon, et
        seulement sinon, une entrée de plus. `ajouter` garde les jetons déjà délivrés
        à cet appareil au lieu de les remplacer : c'est le passage http → https, où le
        téléphone garde les deux origines.

        `sure` : le jeton est délivré contre le code de la TV, tapé en HTTPS. Lui seul
        n'a jamais voyagé en clair, ni rien de ce qui a servi à l'obtenir : c'est la
        condition du clavier et de la souris. Un jeton http se lit sur le wifi, et le
        ticket de transfert est rendu en http à qui présente ce jeton-là — ni l'un ni
        l'autre ne sont sûrs. `presente` : l'empreinte du jeton qui accompagne ce code ;
        il est alors le SEUL remplacé. Sans cela, retaper le code sur la page https
        (pour obtenir la souris) tuait le jeton du favori http du même téléphone, qui
        redemandait un code, qui tuait le jeton https… un téléphone, deux origines,
        jamais les deux à la fois.
        """
        jeton = secrets.token_urlsafe(32)
        maintenant = int(self.horloge() * 1000)
        with self._verrou, self._verrou_fichier():
            self._signature = None
            liste = self._oubliees(self._copie(), maintenant)
            entree = None
            if remplace is not None:
                entree = next((t for t in liste if t["id"] == remplace), None)
            if entree is None and appareil:
                entree = next((t for t in liste if t["appareil"] == appareil), None)
            if entree is None:
                entree = {"id": secrets.token_hex(3), "nom": nom,
                          "appareil": appareil or secrets.token_hex(16),
                          "cree": maintenant, "vu": maintenant, "empreintes": [],
                          # Refusé par défaut : un appairage seul (être dans la pièce)
                          # ne donne pas le clavier, il faut le geste en plus, devant
                          # la TV (Réglages → Télécommande).
                          "pointeurAutorise": False}
                liste.append(entree)
            else:
                entree["nom"] = nom
                entree["vu"] = maintenant
                entree["appareil"] = entree["appareil"] or appareil or secrets.token_hex(16)
            if ajouter:
                gardees = entree["empreintes"]
            elif presente in entree["empreintes"]:
                gardees = [e for e in entree["empreintes"] if e != presente]
            else:
                gardees = []
            entree["empreintes"] = (gardees + [_empreinte(jeton)])[-EMPREINTES_PAR_TELEPHONE:]
            entree["sures"] = [e for e in entree.get("sures", []) if e in entree["empreintes"]] \
                + ([_empreinte(jeton)] if sure else [])
            self._ecrire(self._plafonnee(liste, entree))
        return entree["id"], jeton, entree["appareil"]

    def valide(self, jeton):
        """Identifiant du téléphone, ou None."""
        return self.valide_detail(jeton)[0]

    def valide_detail(self, jeton):
        """(identifiant, sûr) — (None, False) si le jeton n'ouvre rien."""
        if not isinstance(jeton, str) or not 20 <= len(jeton) <= 200:
            return None, False
        empreinte = _empreinte(jeton)
        with self._verrou:
            trouve = None
            for t in self._lire():
                if any(hmac.compare_digest(e, empreinte) for e in t["empreintes"]):
                    trouve = t
            if trouve is None:
                return None, False
            sure = empreinte in trouve["sures"]
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
            return trouve["id"], sure

    def lister(self):
        with self._verrou:
            return [{k: t.get(k) for k in ("id", "nom", "cree", "vu", "pointeurAutorise")}
                    for t in self._lire()]

    def identifiants(self):
        with self._verrou:
            return {t["id"] for t in self._lire()}

    def avec_clavier(self):
        """Les téléphones qui tiennent un jeton sûr (pour --lister)."""
        with self._verrou:
            return {t["id"] for t in self._lire() if t["sures"]}

    def pointeur_autorise(self, ident):
        """Ce téléphone a-t-il reçu le droit à la souris et au clavier ? Un téléphone
        inconnu (révoqué, jamais vu) n'a jamais ce droit."""
        with self._verrou:
            return any(t["id"] == ident and t["pointeurAutorise"] for t in self._lire())

    def autoriser_pointeur(self, ident, autorise):
        """Accorde ou retire le droit à la souris et au clavier pour ce téléphone,
        sans toucher à ses jetons ni à sa date d'appairage. Faux si le téléphone
        n'existe plus (révoqué entre-temps, ou identifiant forgé)."""
        with self._verrou, self._verrou_fichier():
            self._signature = None
            liste = self._lire()
            if not any(t["id"] == ident for t in liste):
                return False
            liste = [dict(t, pointeurAutorise=bool(autorise)) if t["id"] == ident else t for t in liste]
            self._ecrire(liste)
            return True

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
class FenetreAppairage:
    """Le fichier qui dit « l'écran d'appairage est affiché sur la TV ».

    Un fichier plutôt qu'un message au service : le menu l'écrit sans connaître le
    service (démarré avant ou après lui), la ligne de commande aussi, et il survit à
    un redémarrage de l'un ou de l'autre. Seule sa date compte : rien à analyser.
    Dans $XDG_RUNTIME_DIR (0700) : seul l'utilisateur de la session peut l'ouvrir.
    """

    def __init__(self, chemin, horloge=time.time):
        self.chemin = Path(chemin) if chemin else None
        self.horloge = horloge

    def _date(self):
        if self.chemin is None:
            return None
        try:
            st = os.lstat(self.chemin)
        except OSError:
            return None
        # Un lien ou un fichier d'un autre utilisateur n'ouvre rien.
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            return None
        return st.st_mtime

    def ouverte(self):
        date = self._date()
        if date is None:
            return False
        age = self.horloge() - date
        # Une date dans le futur (horloge recalée par NTP) ne doit pas ouvrir pour des heures.
        return -60 <= age < FENETRE_APPAIRAGE_S

    def jusqua_ms(self):
        date = self._date()
        return int((date + FENETRE_APPAIRAGE_S) * 1000) if date is not None and self.ouverte() else None

    def ouvrir(self):
        self.chemin.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.close(os.open(self.chemin, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600))
        maintenant = self.horloge()
        os.utime(self.chemin, (maintenant, maintenant))

    def fermer(self):
        if self.chemin:
            self.chemin.unlink(missing_ok=True)


class Appairage:
    """Le code à 6 chiffres affiché sur la TV, la fenêtre et les limites d'essais."""

    def __init__(self, horloge=time.time, au_changement=None, ouverte=lambda: False):
        self.horloge = horloge
        self.au_changement = au_changement
        # Fermée par défaut : oublier de brancher la fenêtre ne doit rien ouvrir.
        self.ouverte = ouverte
        self._verrou = threading.RLock()
        self._essais = {}
        self._echecs = 0
        self._serie = 0
        self._dernier_echec = 0.0
        self._bloque_jusqua = 0.0
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
            # Fenêtre fermée : on ne compare même pas. Rien à apprendre, rien à compter.
            if not self.ouverte():
                return FERME
            if len(self._essais) > 1000:
                self._essais = {k: v for k, v in self._essais.items() if v and v[-1] > maintenant - 60}
            recents = self._essais.setdefault(ip, deque())
            while recents and recents[0] <= maintenant - 60:
                recents.popleft()
            # Compter AVANT de comparer, et compter aussi les réussites : sinon le
            # sixième essai d'une rafale serait encore évalué.
            if len(recents) >= ESSAIS_PAR_MINUTE or maintenant < self._bloque_jusqua:
                return TROP
            recents.append(maintenant)
            if isinstance(code, str) and re.fullmatch(r"\d{6}", code) \
                    and hmac.compare_digest(code, self.code):
                self._serie, self._bloque_jusqua = 0, 0.0
                self.renouveler()
                return OK
            if maintenant - self._dernier_echec > OUBLI_ECHECS_S:
                self._serie = 0
            self._serie += 1
            self._dernier_echec = maintenant
            if self._serie > ECHECS_LIBRES:
                self._bloque_jusqua = maintenant + min(DELAI_MAX_S, 2 ** (self._serie - ECHECS_LIBRES))
            self._echecs += 1
            if self._echecs >= ECHECS_AVANT_RENOUVELLEMENT:
                journal.warning("%d codes faux : code renouvelé", self._echecs)
                self.renouveler()
            return MAUVAIS

    def attente_s(self, ip):
        with self._verrou:
            maintenant = self.horloge()
            attente = self._bloque_jusqua - maintenant
            recents = self._essais.get(ip)
            if recents and len(recents) >= ESSAIS_PAR_MINUTE:
                attente = max(attente, recents[0] + 60 - maintenant)
            return max(1, math.ceil(attente))


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
def _web_en_cours(chemin_pid, racine="/proc"):
    """Vrai si le fichier pid de hub-web désigne un hub-web vivant (même vérification
    que la voix et que `hub-web --fermer` : un fichier resté après un arrêt brutal, ou
    un pid repris par un autre programme, ne font pas croire à un service ouvert)."""
    if VOIX and hasattr(VOIX, "web_en_cours"):
        return VOIX.web_en_cours(chemin_pid)
    try:
        pid = int(Path(chemin_pid).read_text().strip())
        return b"hub-web" in Path(racine, str(pid), "cmdline").read_bytes()
    except (OSError, ValueError):
        return False


class Routeur:
    """Décide où va une commande validée, et l'y envoie."""

    def __init__(self, socket_menu, executer=subprocess.run, processus=_processus,
                 kodi_hote="127.0.0.1", kodi_port=9090,
                 kodi_http=os.environ.get("HUB_KODI_HTTP", "http://127.0.0.1:8080/jsonrpc"),
                 kodi_identifiants=(os.environ.get("HUB_KODI_UTILISATEUR"),
                                    os.environ.get("HUB_KODI_MOT_DE_PASSE")),
                 tuer=os.kill, web_en_cours=None):
        self.socket_menu = Path(socket_menu)
        # hub-web écrit son pid à côté du socket du menu ($XDG_RUNTIME_DIR/hub/).
        self.web = web_en_cours or (lambda: _web_en_cours(self.socket_menu.parent / "web.pid"))
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
        # Même ordre que la voix (hub_voix_logique.cible) : un service web s'ouvre
        # par-dessus la session du HUB, c'est lui qu'on regarde.
        if self.web():
            return "web"
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

        if self.web():
            if nom == "accueil":
                # Avant, « Accueil » répondait « rien à piloter » devant Netflix : la voix
                # et la télécommande CEC savaient fermer le service, pas le téléphone.
                # hub-web ferme lui-même son navigateur : lui seul sait le faire proprement.
                r = self.lancer([shutil.which("hub-web") or "/usr/local/bin/hub-web", "--fermer"])
                return {"ok": r is not None and getattr(r, "returncode", 1) == 0, "cible": "web"}
            return {"ok": False, "cible": "web", "raison": "sans-effet-dans-le-web"}

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


# ── Souris et clavier ───────────────────────────────────────────────────────
# Là où rien n'écoute la télécommande, et là seulement. Dans le menu et dans Kodi, les
# flèches gardent leur chemin (socket, JSON-RPC) : il est plus sûr — aucune frappe ne
# peut tomber à côté — et il marche sans rien de tout ceci.
CONTEXTES_POINTEUR = ("web", "bureau")
# Les commandes de la liste blanche qui deviennent des touches dans ces contextes. Les
# autres (modes, réglages, thème…) n'ont de sens que pour le menu et restent sans effet.
TOUCHES_COMMANDE = ("haut", "bas", "gauche", "droite", "ok", "retour")


def _entier(valeur):
    # bool est un int en Python : {"x": true} ne doit pas déplacer la souris d'un point.
    return isinstance(valeur, int) and not isinstance(valeur, bool)


def _borne(valeur, maximum):
    return max(-maximum, min(maximum, valeur))


class SessionPointeur:
    """Un WebSocket ouvert par un téléphone autorisé."""

    def __init__(self, ident):
        self.ident = ident
        self.raison_fin = None
        self.erreurs = 0
        self.jetes = 0
        self.recus = 0

    def arreter(self, raison):
        # Seul le fil de la connexion écrit sur le socket : on lève un drapeau, qu'il
        # lit à sa prochaine demi-seconde. Fermer le socket d'ici couperait le TLS sous
        # ses pieds (et SSLSocket.shutdown repasse le socket EN CLAIR pour la suite).
        if self.raison_fin is None:
            self.raison_fin = raison


class Pointeur:
    """Qui a droit au clavier et à la souris, quand, et à quel rythme.

    TOUTES ces conditions, à chaque ouverture, et revérifiées chaque seconde tant que
    le périphérique existe (`_surveiller`) :
      1. l'interrupteur « Souris et clavier » est allumé dans les réglages du HUB — il
         est éteint par défaut, et tout ce qui n'est pas exactement `true` vaut éteint ;
      2. la requête arrive en https : en http, le jeton se lit sur le wifi ;
      3. le jeton est « sûr » (Jetons.creer) : obtenu en tapant le code de la TV en
         https. Un jeton http volé, ou le transfert qu'il permet de demander, ne donnent
         donc jamais le clavier ;
      4. CE téléphone a reçu le droit nommément, depuis Réglages → Télécommande
         (Jetons.pointeur_autorise) — refusé par défaut à l'appairage : lire le code
         sur la TV ouvre la télécommande, pas le clavier ; celui-ci veut un second
         geste, devant la TV, pour ce téléphone précis ;
      5. le contexte est un service web ou le bureau ;
      6. /dev/uinput est accessible ;
      7. la session est au premier plan et déverrouillée (logind) : ni GDM, ni écran
         verrouillé — le périphérique parle à ce qui est devant, quoi que ce soit.
    Le périphérique n'existe que pendant l'usage : fermé, il est DÉTRUIT, et plus rien
    ne peut être injecté dans la session par ce service.
    """

    # Le gardien repasse deux fois par seconde et ne se fie jamais à une réponse de
    # logind plus vieille que 0,4 s : entre le verrouillage de l'écran et la destruction
    # du périphérique, il s'écoule au plus une seconde, appels à loginctl compris.
    PERIODE_GARDIEN_S = 0.5
    DUREE_GARDE_S = 0.4
    # Sans session ouverte (téléphone en disposition « Boutons », qui passe par
    # /api/commande), le périphérique reste une minute : le recréer à chaque flèche
    # coûterait 0,4 s d'adoption par le compositeur à chaque appui.
    INACTIVITE_S = 60
    # La page envoie un battement toutes les 10 s : trois manqués, elle n'est plus là
    # (téléphone en veille, wifi perdu) et la session ne doit pas rester armée.
    DELAI_MUET_S = 30
    PERIODE_NOTIFICATION_S = 60

    def __init__(self, service, fabrique=None, lancer=None, acces=None, horloge=time.monotonic):
        self.service = service
        self.fabrique = fabrique or (lambda: POINTEUR.PeripheriqueVirtuel())
        self.lancer = lancer or service.routeur.lancer
        self.acces = acces or self._acces_uinput
        self.horloge = horloge
        self.disposition = None
        self._verrou = threading.RLock()
        self._peripherique = None
        self._arret = threading.Event()
        self._sessions = []
        self._seaux = {}
        self._garde = None
        self._dernier_usage = 0.0
        self._derniere_notification = None

    @property
    def ouvert(self):
        return self._peripherique is not None

    # ── Les conditions ──
    def active(self):
        """L'interrupteur des réglages du HUB. Relu à chaque fois : l'éteindre sur la
        TV coupe la souris dans la seconde, sans redémarrer quoi que ce soit."""
        try:
            donnees = json.loads(Path(self.service.chemins["reglages"]).read_text(encoding="utf-8"))
            return donnees["systeme"]["telecommandeSouris"] is True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    @staticmethod
    def _acces_uinput(chemin="/dev/uinput"):
        if not os.path.exists(chemin):
            return "uinput-absent"
        return None if os.access(chemin, os.W_OK) else "uinput-refuse"

    def _session_refusee(self):
        maintenant = self.horloge()
        if self._garde is None or maintenant - self._garde[0] > self.DUREE_GARDE_S:
            pilotable, raison = POINTEUR.session_pilotable(self.lancer)
            self._garde = (maintenant, None if pilotable else raison)
        return self._garde[1]

    def _refus_systeme(self, contexte=None):
        if not self.active():
            return "desactive"
        if (contexte or self.service.routeur.contexte()) not in CONTEXTES_POINTEUR:
            return "contexte"
        return self.acces() or self._session_refusee()

    def refus(self, ident, sure, securise, contexte=None):
        """None si ce téléphone, par cette connexion, a droit au clavier et à la souris
        maintenant ; sinon la raison, que la page affiche."""
        if POINTEUR is None:
            return "module-absent"
        if not self.active():
            return "desactive"
        if not securise:
            return "connexion-non-securisee"
        if not ident or not sure:
            return "jeton-non-sur"
        # Un jeton sûr prouve qu'on a lu le code sur la TV ; ça ne suffit plus à donner
        # le clavier depuis cette version — il faut en plus le geste explicite, devant
        # la TV, Réglages → Télécommande → ce téléphone. Une famille qui a toujours dit
        # oui à l'interrupteur global n'était protégée que par « être entré une fois
        # dans le salon » ; un invité de passage entrait dans le même lot pour toujours.
        if not self.service.jetons.pointeur_autorise(ident):
            return "non-autorise"
        return self._refus_systeme(contexte)

    # ── Le périphérique ──
    def _ouvrir(self):
        if self._peripherique is None:
            peripherique = self.fabrique()
            peripherique.ouvrir()
            self._peripherique = peripherique
            self.disposition = POINTEUR.lire_disposition(self.lancer)
            self._arret = threading.Event()
            threading.Thread(target=self._surveiller, args=(self._arret,), daemon=True).start()
            journal.info("souris et clavier : périphérique virtuel créé (clavier %s)",
                         "+".join(filter(None, self.disposition)) if self.disposition else "non reconnu : pas de texte")
        return self._peripherique

    def agir(self, ident, action, frappes=0, mouvements=0):
        """None si l'action est partie, sinon la raison (« debit », « uinput-… »)."""
        seaux = self._seaux.get(ident)
        if seaux is None:
            seaux = self._seaux[ident] = (POINTEUR.Seau(MOUVEMENTS_PAR_S, MOUVEMENTS_RESERVE),
                                          POINTEUR.Seau(FRAPPES_PAR_S, FRAPPES_RESERVE))
        if (mouvements and not seaux[0].prendre(mouvements)) or (frappes and not seaux[1].prendre(frappes)):
            return "debit"
        with self._verrou:
            try:
                action(self._ouvrir())
            except POINTEUR.PointeurIndisponible as erreur:
                return str(erreur)
            self._dernier_usage = self.horloge()
        return None

    def taper(self, ident, texte):
        if not isinstance(texte, str) or not texte.strip() or len(texte) > TAILLE_MAX_TEXTE:
            return {"ok": False, "raison": "texte-invalide"}
        with self._verrou:
            try:
                self._ouvrir()
                frappes, approximations, ignores = POINTEUR.frappes_pour(texte, self.disposition)
            except POINTEUR.PointeurIndisponible as erreur:
                return {"ok": False, "raison": str(erreur)}
            except ValueError:
                return {"ok": False, "raison": "disposition-non-couverte"}
        arret = self._arret
        raison = self.agir(ident, lambda p: p.taper(frappes, continuer=lambda: not arret.is_set()),
                           frappes=max(1, len(frappes)))
        if raison:
            return {"ok": False, "raison": raison}
        return {"ok": True, "approximations": approximations, "ignores": ignores}

    def fermer(self, raison):
        self._arret.set()
        for session in list(self._sessions):
            session.arreter(raison)
        with self._verrou:
            peripherique, self._peripherique = self._peripherique, None
            if peripherique is not None:
                peripherique.fermer()
                journal.info("souris et clavier : périphérique virtuel détruit (%s)", raison)

    def _surveiller(self, arret):
        while not arret.wait(self.PERIODE_GARDIEN_S):
            try:
                raison = self._refus_systeme()
                if raison:
                    return self.fermer(raison)
                # Un téléphone retiré depuis la TV — entièrement, ou juste son droit à
                # la souris — perd la main tout de suite, pas à sa prochaine requête :
                # sa session est déjà ouverte, plus rien n'y passe par la vérification
                # du jeton.
                connus = self.service.jetons.identifiants()
                for session in list(self._sessions):
                    if session.ident not in connus:
                        session.arreter("revoque")
                    elif not self.service.jetons.pointeur_autorise(session.ident):
                        session.arreter("non-autorise")
                if not self._sessions and self.horloge() - self._dernier_usage > self.INACTIVITE_S:
                    return self.fermer("inactif")
            except Exception:  # noqa: BLE001
                # Un gardien mort laisserait un clavier sans surveillance : on ferme.
                journal.exception("souris et clavier : surveillance en échec")
                return self.fermer("erreur")

    # ── Les sessions ──
    def ouvrir_session(self, ident):
        """(session, None) ou (None, raison). Ouvre le périphérique : s'il doit
        échouer, c'est avant d'avoir dit oui à la page."""
        if len(self._sessions) >= SESSIONS_POINTEUR_MAX:
            return None, "trop-de-sessions"
        raison = self.agir(ident, lambda p: None)
        if raison:
            return None, raison
        for ancienne in list(self._sessions):
            if ancienne.ident == ident:
                ancienne.arreter("remplacee")
        session = SessionPointeur(ident)
        self._sessions.append(session)
        journal.info("souris et clavier : session ouverte par le téléphone %s", ident)
        self._notifier()
        return session, None

    def retirer_session(self, session):
        if session in self._sessions:
            self._sessions.remove(session)
            # Ni le texte ni les touches : ce qui est tapé peut être un mot de passe.
            journal.info("souris et clavier : session fermée (téléphone %s, %s, %d messages, %d jetés)",
                         session.ident, session.raison_fin or "page fermée", session.recus, session.jetes)
        if not self._sessions:
            self.fermer("plus de session")

    def _notifier(self):
        """Le témoin côté TV : sur le bureau, une notification dit qu'un téléphone a
        pris la souris. Rien dans la session kiosque (gnome-kiosk n'affiche pas de
        notifications) : là, c'est le pointeur qui bouge qui le dit."""
        maintenant = self.horloge()
        if self._derniere_notification is not None and \
                maintenant - self._derniere_notification < self.PERIODE_NOTIFICATION_S:
            return
        self._derniere_notification = maintenant
        if self.service.routeur.contexte() == "bureau":
            self.lancer(["notify-send", "--app-name=HUB", "--icon=input-mouse", "HUB",
                         "Un téléphone pilote la souris et le clavier."])

    def message(self, session, contenu):
        """Traite un message de la page ; rend la réponse à lui envoyer, ou None."""
        session.recus += 1
        try:
            m = json.loads(contenu.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            m = None
        nature = m.get("t") if isinstance(m, dict) else None
        raison = None
        if nature == "p":
            return {"t": "p", "n": m.get("n") if _entier(m.get("n")) else None}
        if nature == "m" and _entier(m.get("x", 0)) and _entier(m.get("y", 0)):
            dx, dy = _borne(m.get("x", 0), DEPLACEMENT_MAX), _borne(m.get("y", 0), DEPLACEMENT_MAX)
            raison = self.agir(session.ident, lambda p: p.deplacer(dx, dy), mouvements=1)
        elif nature == "d" and _entier(m.get("x", 0)) and _entier(m.get("y", 0)):
            dx, dy = _borne(m.get("x", 0), DEFILEMENT_MAX), _borne(m.get("y", 0), DEFILEMENT_MAX)
            raison = self.agir(session.ident, lambda p: p.defiler(dy, dx), mouvements=1)
        elif nature == "c" and isinstance(m.get("b"), str) and m["b"] in POINTEUR.BOUTONS:
            raison = self.agir(session.ident, lambda p: p.clic(m["b"]), frappes=1)
        elif nature == "k" and isinstance(m.get("n"), str) and m["n"] in POINTEUR.TOUCHES_NOMMEES:
            raison = self.agir(session.ident, lambda p: p.frapper(POINTEUR.TOUCHES_NOMMEES[m["n"]]), frappes=1)
        elif nature == "x":
            return {"t": "r", **self.taper(session.ident, m.get("s"))}
        else:
            session.erreurs += 1
            return None
        if raison == "debit":
            session.jetes += 1
        elif raison:
            session.arreter(raison)
        return None


class _FluxPointeur:
    """Lecture du WebSocket par demi-secondes : entre deux, on regarde si la session a
    été arrêtée (verrouillage, révocation…) ou si la page se tait depuis trop longtemps.
    Pas `rfile` : un délai dépassé au milieu d'une lecture le rend inutilisable."""

    def __init__(self, connexion, session, pointeur, deja=b""):
        self.connexion, self.session, self.pointeur = connexion, session, pointeur
        self.tampon = deja
        self.dernier = time.monotonic()

    def read(self, n):
        while len(self.tampon) < n:
            if self.session.raison_fin:
                raise EOFError
            try:
                morceau = self.connexion.recv(4096)
            except socket.timeout:
                if time.monotonic() - self.dernier > self.pointeur.DELAI_MUET_S:
                    self.session.arreter("muet")
                continue
            except OSError:
                raise EOFError from None
            if not morceau:
                raise EOFError
            self.dernier = time.monotonic()
            self.tampon += morceau
        rendu, self.tampon = self.tampon[:n], self.tampon[n:]
        return rendu


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
        # Le manifeste relève de manifest-src, qui retombe sinon sur default-src 'none'.
        "manifest-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ])
    return html.encode("utf-8"), csp


# ── HTTPS local ─────────────────────────────────────────────────────────────
# POURQUOI. Micro (getUserMedia) et reconnaissance vocale du navigateur n'existent
# qu'en « contexte sécurisé » : HTTPS, ou localhost. Un téléphone qui joint
# http://192.168.1.50 n'y a pas droit. Aucune autorité publique ne signe une adresse
# privée : le HUB devient sa propre petite autorité, que le téléphone installe une
# fois (page « Dictée et connexion sécurisée »).
#
# POURQUOI LA LIGNE DE COMMANDE openssl. La bibliothèque standard sait servir du TLS
# mais pas fabriquer une clé ni un certificat. openssl est « important » dans Ubuntu
# (présent partout, même en installation minimale) ; python3-cryptography ne l'est pas.
#
# CE QUI LIMITE LES DÉGÂTS SI LA CLÉ FUIT. racine.key est lisible par tout programme
# de la session (Kodi, UxPlay, Chrome…) : elle doit donc valoir le moins possible. La
# racine porte des contraintes de nom (RFC 5280, critiques) réduites au strict
# nécessaire : l'adresse actuelle du HUB (/32), hub.local et nom-machine.local. Volée,
# elle ne permet d'usurper que le HUB lui-même — ce que hub.key, forcément présente et
# lisible pareil, permet déjà. Chrome, Safari et OpenSSL appliquent ces contraintes.
#
# LE PRIX. Une autre adresse (bail DHCP) ou un autre nom de machine exigent une autre
# racine, donc de la réinstaller sur chaque téléphone : réserver l'adresse du HUB sur
# la box. Écarté : garder la racine et supprimer sa clé après signature. Le certificat
# serveur (397 jours) ne pourrait plus être renouvelé sans réinstaller, et hub.key
# resterait de toute façon aussi exposée.
#
# MIGRATION. Les racines d'avant le 17/09/2026 couvraient 10/8, 172.16/12, 192.168/16,
# 169.254/16, 127/8 et .local : volée, une telle clé interceptait le téléphone vers
# toute adresse privée de n'importe quel réseau. preparer() relit les contraintes de la
# racine existante et la remplace dès qu'elles diffèrent de celles attendues.
DUREE_RACINE_J = 3650
# 397 jours : sous la limite d'Apple (825 j pour un certificat serveur) et de celle,
# plus stricte, des autorités publiques (398 j), au cas où un navigateur finirait
# par l'appliquer aussi aux racines installées à la main. Renouvelé tout seul, sans
# rien à refaire sur le téléphone : seule la racine y est installée.
DUREE_CERTIFICAT_J = 397
RENOUVELER_AVANT_S = 30 * 86400
# Les seules adresses pour lesquelles on accepte de créer une autorité : un HUB exposé
# sur une adresse publique n'est pas le cas prévu. 127/8 pour les essais.
RESEAUX_PERMIS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
                  "127.0.0.0/8")
# Avant l'heure réseau, une machine peut se croire en 1970 ou en 2019 : un certificat
# émis alors serait « pas encore valide » ou déjà expiré pour le téléphone.
HORLOGE_PLAUSIBLE = 1_767_225_600  # 1er janvier 2026


class ErreurTLS(Exception):
    pass


def _nom_dns(nom):
    nom = (nom or "").strip().lower()
    return nom if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", nom) else None


def contraintes_attendues(adresse, noms):
    """Les sous-arbres permis de la racine, sous la forme qu'imprime `openssl x509 -text`."""
    return {f"IP:{adresse}/255.255.255.255", *(f"DNS:{n}" for n in noms)}


def lire_contraintes(texte):
    """Les sous-arbres permis lus dans la sortie de `openssl x509 -noout -text`, ou None
    si la racine n'a pas de contraintes de nom (une telle racine est à remplacer)."""
    lignes = texte.splitlines()
    for i, ligne in enumerate(lignes):
        if "Name Constraints" not in ligne:
            continue
        titre = len(ligne) - len(ligne.lstrip())
        permis, section = set(), None
        for suite in lignes[i + 1:]:
            propre = suite.strip()
            # Fin du bloc : ligne vide (LibreSSL) ou extension suivante, au même retrait.
            if not propre or len(suite) - len(suite.lstrip()) <= titre:
                break
            if propre in ("Permitted:", "Excluded:"):
                section = propre
            elif section == "Permitted:":
                permis.add(propre)
        return permis
    return None


def empreinte_courte(empreinte):
    """Les 8 premières paires de l'empreinte en 4 groupes : « 3A9F 12C0 4481 7BE2 ».

    Ce que la TV affiche en grand : 64 bits suffisent contre quelqu'un du wifi (il
    faudrait des dizaines d'années de calcul pour fabriquer un certificat de même
    début), et c'est lisible d'un canapé. Le téléphone montre l'empreinte entière,
    on compare son début."""
    if not empreinte:
        return None
    paires = empreinte.split(":")[:8]
    return " ".join("".join(paires[i:i + 2]) for i in range(0, 8, 2))


def noms_du_hub(nom_machine=None):
    """Les noms mDNS couverts par le certificat : hub.local, et nom-machine.local."""
    noms = ["hub.local"]
    propre = _nom_dns(nom_machine if nom_machine is not None else socket.gethostname().split(".")[0])
    if propre and f"{propre}.local" not in noms:
        noms.append(f"{propre}.local")
    return noms


class AutoriteLocale:
    """La racine du HUB (10 ans) et le certificat du service (397 jours).

    racine.key et hub.key : 0600, dans un dossier 0700. Aucune route HTTP ne lit ce
    dossier ; seul le certificat racine (public) est servi, depuis sa forme DER.
    """

    def __init__(self, dossier, openssl=None, horloge=time.time, nom_machine=None):
        self.dossier = Path(dossier)
        self.openssl = openssl if openssl is not None else shutil.which("openssl")
        self.horloge = horloge
        self.nom_machine = nom_machine
        self._verrou = threading.Lock()
        self.racine_cle = self.dossier / "racine.key"
        self.racine_crt = self.dossier / "racine.crt"
        self.cle = self.dossier / "hub.key"
        self.crt = self.dossier / "hub.crt"
        self.fiche = self.dossier / "hub.json"

    # -- outils --------------------------------------------------------------------
    def _commande(self, *args):
        try:
            return subprocess.run([self.openssl, *map(str, args)], check=True, capture_output=True,
                                  text=True, timeout=60).stdout
        except subprocess.CalledProcessError as erreur:
            raise ErreurTLS(f"openssl {args[0]} : {(erreur.stderr or '').strip()[:300]}") from None
        except (OSError, subprocess.SubprocessError) as erreur:
            raise ErreurTLS(f"openssl {args[0]} : {erreur}") from None

    def _nouvelle_cle(self, chemin):
        # Le fichier existe en 0600 AVANT qu'openssl y écrive : il garde ce mode, et la
        # clé n'est jamais lisible par un autre, même le temps d'un instant.
        provisoire = chemin.with_name(f".{chemin.name}.{secrets.token_hex(4)}")
        os.close(os.open(provisoire, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        try:
            self._commande("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256",
                           "-out", provisoire)
            os.chmod(provisoire, 0o600)
        except BaseException:
            provisoire.unlink(missing_ok=True)
            raise
        return provisoire

    @staticmethod
    def _serie():
        # Série aléatoire de 128 bits, positive : deux certificats du même HUB (ou de
        # deux HUB) ne se confondent jamais dans le magasin du téléphone.
        return "0x" + secrets.token_hex(16).lstrip("0").rjust(1, "1")

    # -- racine ----------------------------------------------------------------------
    def contraintes(self):
        """Les sous-arbres permis de la racine existante (None : elle n'en a pas).

        Un openssl qui échoue lève ErreurTLS au lieu de rendre None : un raté passager
        ne doit pas détruire une racine installée sur tous les téléphones."""
        return lire_contraintes(self._commande("x509", "-in", self.racine_crt, "-noout", "-text"))

    def _creer_racine(self, temp, adresse, noms):
        nom = _nom_dns(self.nom_machine if self.nom_machine is not None
                       else socket.gethostname().split(".")[0]) or "hub"
        date = time.strftime("%Y-%m-%d", time.gmtime(self.horloge()))
        contraintes = [f"permitted;IP.0 = {adresse}/255.255.255.255"]
        contraintes += [f"permitted;DNS.{i} = {n}" for i, n in enumerate(noms)]
        config = Path(temp) / "racine.cnf"
        config.write_text("\n".join([
            "[req]", "distinguished_name = dn", "prompt = no", "utf8 = yes", "string_mask = utf8only",
            "[dn]", "O = HUB",
            # Nom et date dans le sujet : le téléphone qui a connu deux HUB (ou une
            # réinstallation) affiche deux entrées qu'on distingue pour révoquer l'ancienne.
            f"CN = HUB autorité locale ({nom}, {adresse}, {date})",
            "[v3]", "basicConstraints = critical,CA:TRUE,pathlen:0",
            "keyUsage = critical,keyCertSign,cRLSign", "subjectKeyIdentifier = hash",
            "nameConstraints = critical,@contraintes", "[contraintes]", *contraintes, ""]),
            encoding="utf-8")
        cle = self._nouvelle_cle(self.racine_cle)
        crt = Path(temp) / "racine.crt"
        try:
            self._commande("req", "-x509", "-new", "-key", cle, "-config", config, "-extensions", "v3",
                           "-days", DUREE_RACINE_J, "-sha256", "-set_serial", self._serie(), "-out", crt)
        except BaseException:
            cle.unlink(missing_ok=True)
            raise
        os.replace(cle, self.racine_cle)
        shutil.copyfile(crt, self.racine_crt)
        os.chmod(self.racine_crt, 0o644)
        # Une nouvelle racine rend l'ancien certificat du HUB orphelin.
        self.fiche.unlink(missing_ok=True)
        journal.info("autorité locale créée, empreinte SHA-256 %s", self.empreinte())

    # -- certificat du HUB -------------------------------------------------------------
    def _emettre(self, temp, adresse, noms):
        config = Path(temp) / "hub.cnf"
        alternatifs = [f"IP.0 = {adresse}"] + [f"DNS.{i} = {n}" for i, n in enumerate(noms)]
        config.write_text("\n".join([
            "[req]", "distinguished_name = dn", "prompt = no",
            "[dn]", "O = HUB", f"CN = {noms[0]}",
            "[v3]", "basicConstraints = critical,CA:FALSE", "keyUsage = critical,digitalSignature",
            "extendedKeyUsage = serverAuth", "subjectKeyIdentifier = hash",
            "authorityKeyIdentifier = keyid", "subjectAltName = @noms", "[noms]", *alternatifs, ""]),
            encoding="utf-8")
        cle = self._nouvelle_cle(self.cle)
        demande, crt = Path(temp) / "hub.csr", Path(temp) / "hub.crt"
        try:
            self._commande("req", "-new", "-key", cle, "-config", config, "-out", demande)
            self._commande("x509", "-req", "-in", demande, "-CA", self.racine_crt, "-CAkey", self.racine_cle,
                           "-set_serial", self._serie(), "-days", DUREE_CERTIFICAT_J, "-sha256",
                           "-extfile", config, "-extensions", "v3", "-out", crt)
            # Contre-épreuve avant de servir quoi que ce soit : la chaîne doit être
            # valide pour OpenSSL, contraintes de nom comprises.
            self._commande("verify", "-CAfile", self.racine_crt, "-purpose", "sslserver", crt)
        except BaseException:
            cle.unlink(missing_ok=True)
            raise
        os.replace(cle, self.cle)
        shutil.copyfile(crt, self.crt)
        fin = self._commande("x509", "-in", self.crt, "-noout", "-enddate").strip()
        expire = ssl.cert_time_to_seconds(fin.split("=", 1)[1])
        ecrire_prive(self.fiche, json.dumps({"adresse": adresse, "noms": noms, "expire": expire,
                                             "racine": self.empreinte()}))
        journal.info("certificat du HUB émis pour %s, %s (jusqu'au %s)", adresse, ", ".join(noms),
                     time.strftime("%Y-%m-%d", time.localtime(expire)))

    def _fiche(self):
        try:
            return json.loads(self.fiche.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def a_jour(self, adresse):
        fiche = self._fiche()
        return bool(fiche) and self.crt.is_file() and self.cle.is_file() and self.racine_crt.is_file() \
            and fiche.get("adresse") == adresse and fiche.get("noms") == noms_du_hub(self.nom_machine) \
            and fiche.get("racine") == self.empreinte() \
            and float(fiche.get("expire") or 0) - self.horloge() > RENOUVELER_AVANT_S

    def preparer(self, adresse):
        """Crée la racine si besoin, et (ré)émet le certificat du HUB s'il ne couvre pas
        `adresse`, change de nom ou expire dans moins de 30 jours. Vrai si émis."""
        if not self.openssl:
            raise ErreurTLS("openssl introuvable")
        if self.horloge() < HORLOGE_PLAUSIBLE:
            raise ErreurTLS("horloge pas encore à l'heure")
        ip = ipaddress.ip_address(adresse)
        if not any(ip in ipaddress.ip_network(r) for r in RESEAUX_PERMIS):
            # La racine refuserait de couvrir cette adresse : mieux vaut le dire que
            # servir une chaîne que tous les téléphones rejetteront.
            raise ErreurTLS(f"{adresse} n'est pas une adresse privée : HTTPS local impossible")
        with self._verrou:
            self.dossier.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.dossier, 0o700)
            noms = noms_du_hub(self.nom_machine)
            with tempfile.TemporaryDirectory(dir=self.dossier) as temp:
                if self.racine_cle.is_file() and self.racine_crt.is_file() \
                        and self.contraintes() != contraintes_attendues(adresse, noms):
                    # Racine d'avant le 17/09/2026 (tout le privé), autre adresse ou autre
                    # nom : elle ne signerait pas, ou signerait trop. L'ancienne clé est
                    # détruite ; les téléphones devront installer la nouvelle racine.
                    journal.warning("autorité locale remplacée (adresse %s, noms %s) : réinstaller le "
                                    "certificat sur les téléphones et retirer l'ancien", adresse, ", ".join(noms))
                    self.racine_cle.unlink(missing_ok=True)
                    self.racine_crt.unlink(missing_ok=True)
                if not (self.racine_cle.is_file() and self.racine_crt.is_file()):
                    self._creer_racine(temp, adresse, noms)
                if self.a_jour(adresse):
                    return False
                self._emettre(temp, adresse, noms)
                return True

    def a_renouveler(self):
        fiche = self._fiche()
        return not fiche or float(fiche.get("expire") or 0) - self.horloge() <= RENOUVELER_AVANT_S

    def contexte(self):
        contexte = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        contexte.minimum_version = ssl.TLSVersion.TLSv1_2
        contexte.load_cert_chain(self.crt, self.cle)
        return contexte

    def racine_der(self):
        try:
            return ssl.PEM_cert_to_DER_cert(self.racine_crt.read_text(encoding="ascii"))
        except (OSError, ValueError):
            return None

    def empreinte(self):
        """SHA-256 du certificat racine, en paires hexadécimales : la forme qu'affichent
        les réglages d'iOS (« Plus de détails ») et d'Android, à comparer avec la TV."""
        der = self.racine_der()
        if der is None:
            return None
        return ":".join(f"{o:02X}" for o in hashlib.sha256(der).digest())


# Un ticket de transfert fait passer un téléphone déjà relié en http vers l'origine
# https sans retaper de code. Usage unique, deux minutes, 256 bits : il peut transiter
# dans l'URL (fragment, jamais envoyé au serveur par le navigateur) sans valoir un jeton.
DUREE_TICKET_S = 120


# ── « Comme une app » : manifeste et icônes ─────────────────────────────────
# Couleurs du HUB (page.html : --encre, --tv). Le manifeste et les méta de la page
# doivent dire la même chose, sinon la barre d'état change de teinte au lancement.
ENCRE = (6, 7, 12)
TURQUOISE = (62, 224, 208)

MANIFESTE = {
    "name": "HUB · Télécommande",
    "short_name": "HUB",
    "description": "Télécommande du HUB sur le réseau de la maison",
    "lang": "fr",
    "dir": "ltr",
    # Chemins relatifs à l'origine : le même manifeste sert http://ip:8790 et
    # https://ip:8791, deux « apps » distinctes pour le téléphone.
    "id": "/",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#06070c",
    "theme_color": "#06070c",
    "icons": [
        {"src": "/icone-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        # L'icône est pleine page et le carré tient dans le cercle sûr (80 %) : la même
        # image supporte le découpage d'Android (rond, goutte, carré arrondi).
        {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

# Tailles servies : 192 et 512 (exigées par Chrome pour l'installation), 180
# (apple-touch-icon, taille native de l'iPhone), 32 (onglet).
ICONES = {"/icone-192.png": 192, "/icone-512.png": 512, "/apple-touch-icon.png": 180,
          "/icone-32.png": 32}


def _png(largeur, hauteur, lignes_rgb):
    def bloc(nature, donnees):
        return (struct.pack(">I", len(donnees)) + nature + donnees
                + struct.pack(">I", zlib.crc32(nature + donnees)))
    entete = struct.pack(">IIBBBBB", largeur, hauteur, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", entete)
            + bloc(b"IDAT", zlib.compress(bytes(lignes_rgb), 9)) + bloc(b"IEND", b""))


def icone_png(taille):
    """L'icône du HUB : un carré arrondi turquoise, lumineux, sur l'encre.

    Dessinée ici plutôt que livrée en fichiers : pas de binaire dans le dépôt, pas de
    Pillow, et une couleur changée dans ce fichier change toutes les tailles. Chaque
    pixel vient de la distance signée au carré arrondi : bord anti-crénelé, halo en
    exponentielle décroissante, dégradé plus clair en haut comme une touche éclairée.
    """
    clair = (196, 255, 248)
    cote = 0.46 * taille
    demi, rayon, halo = cote / 2, 0.11 * taille, 0.07 * taille
    interieur, centre = demi - rayon, taille / 2
    lignes = bytearray()
    for y in range(taille):
        py = y + 0.5 - centre
        ay = abs(py) - interieur
        lignes.append(0)  # filtre PNG « aucun »
        k = 0.55 * (1 - min(1.0, max(0.0, (py + demi) / cote))) ** 2
        plein = [v + (c - v) * k for v, c in zip(TURQUOISE, clair)]
        for x in range(taille):
            ax = abs(x + 0.5 - centre) - interieur
            d = math.hypot(max(ax, 0), max(ay, 0)) + min(max(ax, ay), 0) - rayon
            fond = ENCRE
            if d > 0:
                g = 0.5 * math.exp(-d / halo)
                fond = [e + (v - e) * g for e, v in zip(ENCRE, TURQUOISE)]
            couverture = min(1.0, max(0.0, 0.5 - d))
            lignes.extend(round(f + (p - f) * couverture) for f, p in zip(fond, plein))
    return _png(taille, taille, lignes)


class Ressources:
    """Icônes calculées à la première demande, puis gardées : 1 s de calcul pour la
    grande, qu'on ne paie ni au démarrage ni deux fois."""

    def __init__(self):
        self._verrou = threading.Lock()
        self._cache = {}
        self.manifeste = json.dumps(MANIFESTE, ensure_ascii=False).encode("utf-8")

    def icone(self, chemin):
        taille = ICONES.get(chemin)
        if taille is None:
            return None
        with self._verrou:
            if taille not in self._cache:
                self._cache[taille] = icone_png(taille)
            return self._cache[taille]


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
    def __init__(self, chemins, routeur=None, horloge=time.time, page=None, tls=None, dicteur=None):
        self.chemins = chemins
        self.dicteur = dicteur or Dicteur()
        self.horloge = horloge
        # None : HTTPS désactivé. Sinon une AutoriteLocale, prête ou non (tls_pret).
        self.tls = tls
        self.tls_pret = False
        self.url_https = None
        self.port_https = None
        self._tickets = {}
        self._verrou_tickets = threading.Lock()
        self.jetons = Jetons(chemins["jetons"], horloge=horloge)
        self.routeur = routeur or Routeur(chemins["socket"])
        self.pointeur = Pointeur(self)
        self.page, self.csp = charger_page(page)
        self.ressources = Ressources()
        self.url = None
        self.hotes_admis = frozenset()
        self.appairage_le = None
        self._verrou_etat = threading.Lock()
        self._verrou_photos = threading.Lock()
        self.fenetre = FenetreAppairage(chemins.get("appairage"), horloge=horloge)
        self._fenetre_ouverte = False
        self.appairage = Appairage(horloge=horloge, au_changement=self.ecrire_etat,
                                   ouverte=self.fenetre.ouverte)

    def verifier_fenetre(self):
        """À appeler régulièrement : publie l'ouverture et la fermeture de la fenêtre
        d'appairage. À la fermeture, le code change : celui qu'on a pu lire par-dessus
        une épaule ne servira pas à la prochaine ouverture."""
        ouverte = self.fenetre.ouverte()
        if ouverte == self._fenetre_ouverte:
            return False
        self._fenetre_ouverte = ouverte
        journal.info("fenêtre d'appairage %s", "ouverte" if ouverte else "fermée")
        if ouverte:
            self.ecrire_etat()
        else:
            self.appairage.renouveler()
        return True

    def publier(self, adresse, port, port_https=None):
        self.url = f"http://{adresse}:{port}/"
        self.port_https = port_https if self.tls_pret else None
        self.url_https = f"https://{adresse}:{port_https}/" if self.port_https else None
        nom = socket.gethostname().lower()
        hotes = {f"{adresse}:{port}", f"{nom}:{port}", f"{nom}.local:{port}", f"hub.local:{port}"}
        if self.port_https:
            # Les noms du certificat, et eux seuls, sur le port HTTPS.
            hotes |= {f"{adresse}:{port_https}"} | {f"{n}:{port_https}" for n in noms_du_hub()}
        self.hotes_admis = frozenset(hotes)
        self.ecrire_etat()

    def creer_ticket(self, ident=None, nature="transfert", duree=None):
        """Le ticket porte l'identifiant du téléphone qui l'a demandé : c'est lui qui
        prouve, sur l'origine https où le jeton http n'existe pas, que c'est le même
        appareil — sans quoi le passage à la version sécurisée créerait un doublon.

        `nature` : « transfert » ou « pointeur ». Un ticket ne vaut que pour ce pour quoi
        il a été délivré : celui qui ouvre la souris ne doit pas pouvoir appairer, ni
        l'inverse (le ticket de transfert s'obtient en http)."""
        ticket = secrets.token_urlsafe(32)
        maintenant = self.horloge()
        with self._verrou_tickets:
            self._tickets = {k: v for k, v in self._tickets.items() if v[0] > maintenant}
            if len(self._tickets) >= 20:
                return None
            self._tickets[_empreinte(ticket)] = (maintenant + (duree or DUREE_TICKET_S), ident, nature)
        return ticket

    def consommer_ticket(self, ticket, nature="transfert"):
        """{"id": identifiant du téléphone} si le ticket vaut encore, sinon None. Présenté
        au mauvais guichet, il est brûlé quand même."""
        if not isinstance(ticket, str) or not 20 <= len(ticket) <= 200:
            return None
        with self._verrou_tickets:
            trouve = self._tickets.pop(_empreinte(ticket), None)
        if trouve is None or trouve[0] <= self.horloge() or trouve[2] != nature:
            return None
        return {"id": trouve[1]}

    def executer_commande(self, nom, texte, ident, sure, securise):
        """Une commande de la liste blanche. Hors du menu et de Kodi, les flèches, OK,
        Retour et le texte deviennent des touches — aux conditions de Pointeur.refus,
        les mêmes que pour la souris : la route des boutons n'est pas une porte de
        derrière. Refusées, la réponse dit pourquoi (« pointeur-… »)."""
        contexte = self.routeur.contexte()
        if contexte not in CONTEXTES_POINTEUR or (nom not in TOUCHES_COMMANDE and nom != "texte"):
            return self.routeur.executer(nom, texte)
        raison = self.pointeur.refus(ident, sure, securise, contexte)
        if raison is None and nom == "texte":
            resultat = self.pointeur.taper(ident, texte)
            if resultat["ok"]:
                return {**resultat, "cible": contexte}
            raison = resultat["raison"]
        elif raison is None:
            raison = self.pointeur.agir(ident, lambda p: p.frapper(POINTEUR.TOUCHES_NOMMEES[nom]), frappes=1)
        if raison is None:
            return {"ok": True, "cible": contexte}
        return {"ok": False, "cible": contexte, "raison": f"pointeur-{raison}"}

    def ecrire_etat(self):
        """Ce que la TV affiche : URL (pour le QR code), code, expiration."""
        if not self.url:
            return
        empreinte = self.tls.empreinte() if self.tls and self.tls_pret else None
        # La liste, et pas seulement le compte : Réglages → Télécommande montre quels
        # téléphones sont reliés et depuis quand on les a vus, pour en retirer un.
        # Rien de secret n'y passe (ni jeton, ni identifiant d'appareil).
        telephones = sorted(self.jetons.lister(), key=lambda t: -(t.get("vu") or 0))
        etat = {"url": self.url, "code": self.appairage.code, "expire": self.appairage.expire_ms,
                "telephones": len(telephones), "listeTelephones": telephones,
                "appairageLe": self.appairage_le,
                # Le code ne vaut rien tant que ceci est faux : le menu le dit plutôt que
                # de laisser taper un code refusé.
                "appairageOuvert": self.fenetre.ouverte(),
                "appairageJusque": self.fenetre.jusqua_ms(),
                "https": self.url_https,
                # À afficher sur la TV : c'est le SEUL endroit d'où l'empreinte fait foi.
                # Le téléphone la compare à celle que montrent ses propres réglages
                # (détails du certificat installé), jamais à ce que dit la page http.
                "empreinteRacine": empreinte,
                "empreinteRacineCourte": empreinte_courte(empreinte)}
        with self._verrou_etat:
            try:
                ecrire_prive(self.chemins["etat"], json.dumps(etat))
            except OSError as erreur:
                journal.error("état non écrit (%s) : la TV n'affichera pas le code", erreur)

    def traiter_dictee(self, texte, langue):
        """Le texte reconnu devient une commande, routée comme un appui ; le menu
        affiche ce qui a été entendu, comme pour la voix du salon."""
        entendu = " ".join(m for m in (texte or "").split() if m != "[unk]")
        commande = VOIX.analyser(texte or "", langue)[1] if VOIX else None
        socket_menu = Path(self.chemins["socket"])
        menu = socket_menu.is_socket()
        if menu and entendu:
            borne = entendu.encode("utf-8")[:200].decode("utf-8", errors="ignore")
            _envoyer_menu(socket_menu, "voix:entendu:" + borne)
        if commande not in COMMANDES:
            if menu:
                _envoyer_menu(socket_menu, "voix:incompris")
                _envoyer_menu(socket_menu, "voix:repos")
            return {"ok": False, "cible": None, "raison": "incompris", "texte": entendu, "commande": None}
        resultat = self.routeur.executer(commande)
        if menu:
            _envoyer_menu(socket_menu, "voix:repos")
        return {**resultat, "texte": entendu, "commande": commande}

    def effacer_etat(self):
        # Un QR code vers un service arrêté enverrait le téléphone dans le vide.
        Path(self.chemins["etat"]).unlink(missing_ok=True)


class PhotoRefusee(Exception):
    """raison : « quota » (trop de photos du téléphone) ou « espace » (disque presque plein)."""


def _espace_libre(dossier):
    return shutil.disk_usage(dossier).free


def enregistrer_photo(dossier, octets, maintenant, espace_libre=_espace_libre):
    """Nom du fichier écrit. Le nom vient d'ici, jamais du téléphone : aucun chemin
    fourni par le réseau ne touche le disque. PhotoRefusee au-delà des quotas.

    L'appelant sérialise les envois : sinon dix envois simultanés passeraient tous le
    contrôle du quota avant qu'aucun n'écrive."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    # Seules les photos de ce service comptent : celles copiées à la main dans le
    # dossier ne doivent pas bloquer, ni être comptées contre le téléphone.
    nombre, taille = 0, 0
    for photo in dossier.glob("telephone-*.jpg"):
        try:
            taille += photo.stat().st_size
            nombre += 1
        except OSError:
            continue
    if nombre >= PHOTOS_MAX or taille + len(octets) > PHOTOS_TAILLE_MAX:
        raise PhotoRefusee("quota")
    if espace_libre(dossier) - len(octets) < ESPACE_LIBRE_MIN:
        raise PhotoRefusee("espace")
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

        def setup(self):
            # La poignée de main TLS a lieu ici, dans le fil de la connexion et sous son
            # délai : un client lent ou qui parle http au port https ne bloque pas accept().
            if isinstance(self.request, ssl.SSLSocket):
                self.request.settimeout(self.timeout)
                self.request.do_handshake()
            super().setup()

        @property
        def securise(self):
            return isinstance(self.request, ssl.SSLSocket)

        def log_message(self, fmt, *args):
            journal.debug("%s %s", self.client_address[0], fmt % args)

        def end_headers(self):
            # Sur TOUTES les réponses, y compris les erreurs produites par http.server.
            self.send_header("Content-Security-Policy", self._csp())
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Resource-Policy", getattr(self, "corp", "same-origin"))
            # Le micro pour cette origine seule (la dictée) ; ni caméra (la photo passe par
            # le sélecteur de fichiers du système, pas par getUserMedia) ni position.
            self.send_header("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _hote(self):
            entetes = getattr(self, "headers", None)
            hote = (entetes.get("Host") or "").strip().lower() if entetes else ""
            return hote if hote in service.hotes_admis else None

        def _origine_https(self):
            """https://même-nom:port-https, pour la page servie en http."""
            hote = self._hote()
            if not hote or not service.port_https:
                return None
            nom = hote.rsplit(":", 1)[0]
            if f"{nom}:{service.port_https}" not in service.hotes_admis:
                nom = service.url_https.split("//", 1)[1].rsplit(":", 1)[0]
            return f"https://{nom}:{service.port_https}"

        def _csp(self):
            # La page http peut sonder l'origine https (le certificat est-il installé ?) :
            # cette origine-là, et aucune autre, s'ajoute à connect-src.
            if self.securise:
                # Le WebSocket de la souris. « 'self' » devrait le couvrir (CSP 3), mais
                # les Safari d'avant 15.4 ne l'étendaient pas à wss: — on nomme donc
                # cette origine-ci, vérifiée contre la liste des hôtes admis.
                hote = self._hote()
                origine = f"wss://{hote}" if hote else None
            else:
                origine = self._origine_https()
            if not origine:
                return service.csp
            return service.csp.replace("connect-src 'self'", f"connect-src 'self' {origine}", 1)

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
            # Une navigation de premier niveau vers la page reste permise : c'est ainsi
            # qu'arrive le passage http → https (schéma différent = autre « site »), ou
            # un lien. Elle ne porte ni jeton ni corps, et la page ne se laisse pas
            # encadrer (frame-ancestors). Tout le reste venu d'ailleurs : 403.
            navigation = (self.command in ("GET", "HEAD") and self._chemin() == "/"
                          and self.headers.get("Sec-Fetch-Mode") == "navigate"
                          and self.headers.get("Sec-Fetch-Dest") == "document")
            if self.headers.get("Sec-Fetch-Site") == "cross-site" and not navigation:
                self._json(403, {"erreur": "origine"})
                return False
            return True

        def _chemin(self):
            return self.path.split("?", 1)[0]

        def _jeton(self):
            return self._jeton_detail()[0]

        def _jeton_detail(self):
            """(identifiant du téléphone, jeton sûr ?) — voir Jetons.creer."""
            entete = self.headers.get("Authorization") or ""
            if not entete.startswith("Bearer "):
                return None, False
            return service.jetons.valide_detail(entete[7:].strip())

        def do_GET(self):
            if self._chemin() == "/sonde" and self.securise and self._hote():
                # Sondée depuis la page http (autre « site » : Sec-Fetch-Site
                # cross-site) pour savoir si le téléphone fait confiance au certificat.
                # Une réponse vide, lisible par personne (no-cors) : elle ne prouve que
                # la poignée de main TLS réussie.
                self.corp = "cross-origin"
                return self._repondre(204, b"", "text/plain")
            if not self._admis():
                return
            chemin = self._chemin()
            if chemin == "/":
                return self._repondre(200, service.page, "text/html; charset=utf-8")
            if chemin == "/hub-racine.crt":
                der = service.tls.racine_der() if service.tls and service.tls_pret else None
                if der is None:
                    return self._json(404, {"erreur": "https-desactive"})
                # Ce type déclenche l'installation de profil sur iPhone et le
                # téléchargement du certificat sur Android. Public par nature : c'est
                # la clé privée, jamais servie, qui compte.
                return self._repondre(200, der, "application/x-x509-ca-cert", {
                    "Content-Disposition": 'attachment; filename="HUB-autorite-locale.crt"'})
            if chemin == "/api/certificat":
                pret = bool(service.tls and service.tls_pret)
                origine = (f"https://{self._hote()}" if self.securise else self._origine_https()) if pret else None
                # Pas d'empreinte ici : venue par le même canal http que le certificat,
                # elle serait remplacée avec lui. Elle ne fait foi que lue sur la TV.
                return self._json(200, {"disponible": pret, "securise": self.securise,
                                        "https": origine + "/" if origine else None})
            if chemin == "/manifest.webmanifest":
                return self._repondre(200, service.ressources.manifeste,
                                      "application/manifest+json; charset=utf-8")
            if chemin in ICONES:
                return self._repondre(200, service.ressources.icone(chemin), "image/png")
            if chemin == "/api/etat":
                ident, sure = self._jeton_detail()
                if not ident:
                    return self._json(401, {"erreur": "jeton"})
                contexte = service.routeur.contexte()
                # La page bascule seule entre « Navigation » et « Souris », et quand la
                # souris manque là où elle servirait, elle dit pourquoi : pas de panne muette.
                raison = service.pointeur.refus(ident, sure, self.securise, contexte)
                return self._json(200, {"ok": True, "contexte": contexte,
                                        "pointeur": {"permis": raison is None, "raison": raison}})
            if chemin == "/api/pointeur":
                return self._pointeur()
            self._json(404, {"erreur": "introuvable"})

        def _pointeur(self):
            """Le WebSocket de la souris et du clavier. Rien ne s'ouvre sans un ticket
            délivré à l'instant, en https, à un téléphone qui y avait droit."""
            protocoles = [p.strip() for p in (self.headers.get("Sec-WebSocket-Protocol") or "").split(",")]
            ticket = next((p[7:] for p in protocoles if p.startswith("ticket.")), None)
            porteur = service.consommer_ticket(ticket, "pointeur")
            if porteur is None or porteur["id"] not in service.jetons.identifiants():
                return self._json(401, {"erreur": "ticket"})
            cle = self.headers.get("Sec-WebSocket-Key") or ""
            if (self.command != "GET" or (self.headers.get("Upgrade") or "").lower() != "websocket"
                    or "upgrade" not in (self.headers.get("Connection") or "").lower()
                    or self.headers.get("Sec-WebSocket-Version") != "13"
                    or not re.fullmatch(r"[A-Za-z0-9+/]{22}==", cle) or "hub-pointeur" not in protocoles):
                return self._json(400, {"erreur": "websocket"})
            # Un WebSocket échappe à CORS : n'importe quelle page peut en ouvrir un vers
            # le HUB. L'origine doit donc être la nôtre, exactement — en plus du Host
            # (rebinding) et de Sec-Fetch-Site, déjà vérifiés par _admis.
            if not self.securise or self.headers.get("Origin") != f"https://{self._hote()}":
                return self._json(403, {"erreur": "pointeur", "raison": "connexion-non-securisee"
                                        if not self.securise else "origine"})
            # Le ticket a trente secondes : ce qui était permis en le demandant peut ne
            # plus l'être (écran verrouillé entre-temps). Il a été délivré à un jeton sûr.
            raison = service.pointeur.refus(porteur["id"], True, True)
            session = None
            if raison is None:
                session, raison = service.pointeur.ouvrir_session(porteur["id"])
            if session is None:
                return self._json(403, {"erreur": "pointeur", "raison": raison})
            self.close_connection = True
            # Écrit à la main : http.server répondrait « HTTP/1.0 101 », que les
            # navigateurs refusent pour un WebSocket.
            self.connection.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                                     "Connection: Upgrade\r\nSec-WebSocket-Protocol: hub-pointeur\r\n"
                                     f"Sec-WebSocket-Accept: {POINTEUR.cle_acceptee(cle)}\r\n\r\n").encode("ascii"))
            self._servir_pointeur(session)

        def _servir_pointeur(self, session):
            def envoyer(message):
                self.connection.sendall(POINTEUR.trame(POINTEUR.OP_TEXTE, json.dumps(
                    message, ensure_ascii=False).encode("utf-8")))

            code = 1000
            try:
                self.connection.settimeout(0.5)
                flux = _FluxPointeur(self.connection, session, service.pointeur)
                disposition = service.pointeur.disposition
                envoyer({"t": "pret", "texte": bool(disposition and POINTEUR.table_de(disposition))})
                while True:
                    opcode, contenu = POINTEUR.lire_trame(flux, TRAME_POINTEUR_MAX)
                    if opcode == POINTEUR.OP_FIN:
                        break
                    if opcode == POINTEUR.OP_PING:
                        self.connection.sendall(POINTEUR.trame(POINTEUR.OP_PONG, contenu[:125]))
                    elif opcode == POINTEUR.OP_TEXTE:
                        reponse = service.pointeur.message(session, contenu)
                        if reponse is not None:
                            envoyer(reponse)
                        if session.erreurs > ERREURS_POINTEUR_MAX:
                            raise POINTEUR.TrameRefusee(1008)
                    elif opcode != POINTEUR.OP_PONG:
                        raise POINTEUR.TrameRefusee(1003)
            except POINTEUR.TrameRefusee as refus:
                code = refus.code
                session.arreter(f"trame-{code}")
            except (EOFError, OSError):
                pass
            finally:
                try:
                    if session.raison_fin and code == 1000:
                        envoyer({"t": "fin", "raison": session.raison_fin})
                    self.connection.sendall(POINTEUR.trame(POINTEUR.OP_FIN, struct.pack("!H", code)))
                except OSError:
                    pass
                service.pointeur.retirer_session(session)

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
            if chemin == "/api/transfert":
                return self._transfert()
            if chemin == "/api/dictee":
                return self._dictee()
            if chemin == "/api/pointeur/session":
                return self._session_pointeur()
            self._json(404, {"erreur": "introuvable"})

        def _session_pointeur(self):
            ident, sure = self._jeton_detail()
            if not ident:
                return self._json(401, {"erreur": "jeton"})
            if self._corps() is None:
                return
            raison = service.pointeur.refus(ident, sure, self.securise)
            if raison:
                return self._json(403, {"erreur": "pointeur", "raison": raison})
            ticket = service.creer_ticket(ident, nature="pointeur", duree=DUREE_TICKET_POINTEUR_S)
            if ticket is None:
                return self._json(429, {"erreur": "trop"}, {"Retry-After": str(DUREE_TICKET_POINTEUR_S)})
            self._json(200, {"ticket": ticket})

        def _appairer(self):
            corps = self._corps()
            if corps is None:
                return
            ip = self.client_address[0]
            if "transfert" in corps:
                # Seulement sur l'origine https : c'est tout l'objet du transfert.
                porteur = service.consommer_ticket(corps.get("transfert")) if self.securise else None
                if porteur is None:
                    journal.info("transfert refusé depuis %s", ip)
                    return self._json(403, {"erreur": "transfert"})
                # Le même téléphone, sur son autre origine : il garde son entrée ET son
                # jeton http, qui reste valable pour le raccourci déjà posé.
                return self._delivrer(corps, ip, remplace=porteur["id"], ajouter=True)
            resultat = service.appairage.essayer(ip, corps.get("code"))
            if resultat == FERME:
                journal.info("appairage refusé depuis %s : écran d'appairage fermé", ip)
                return self._json(403, {"erreur": "appairage-ferme"})
            if resultat == TROP:
                attente = service.appairage.attente_s(ip)
                journal.warning("appairage : trop d'essais depuis %s", ip)
                return self._json(429, {"erreur": "trop", "attente": attente},
                                  {"Retry-After": str(attente)})
            if resultat != OK:
                journal.info("appairage : code faux depuis %s", ip)
                return self._json(403, {"erreur": "code"})
            # Le code de la TV vient d'être donné : ce qui suit ne sert plus qu'à savoir
            # QUELLE entrée renouveler. Le jeton précédent passe avant l'identifiant
            # d'appareil — un téléphone appairé ne renouvelle jamais que le sien.
            # Code de la TV tapé en https : le jeton qui en sort n'aura jamais voyagé en
            # clair, c'est le seul à qui le clavier et la souris seront ouverts.
            entete = self.headers.get("Authorization") or ""
            presente = _empreinte(entete[7:].strip()) if entete.startswith("Bearer ") else None
            return self._delivrer(corps, ip, remplace=self._jeton(),
                                  appareil=appareil_propre(corps.get("appareil")),
                                  sure=self.securise, presente=presente)

        def _delivrer(self, corps, ip, remplace=None, appareil=None, ajouter=False, sure=False, presente=None):
            nom = nom_du_telephone(corps.get("nom"), self.headers.get("User-Agent"))
            connus = {t["id"] for t in service.jetons.lister()}
            ident, jeton, appareil = service.jetons.creer(nom, remplace=remplace, appareil=appareil,
                                                          ajouter=ajouter, sure=sure, presente=presente)
            service.appairage_le = int(service.horloge() * 1000)
            service.ecrire_etat()
            journal.info("appairage : %s (%s) depuis %s%s", nom, ident, ip,
                         "" if ident not in connus else " — entrée renouvelée, pas de doublon")
            self._json(200, {"jeton": jeton, "id": ident, "nom": nom, "appareil": appareil})

        def _dictee(self):
            if not self._jeton():
                return self._json(401, {"erreur": "jeton"})
            # audio/wav n'est pas un type « simple » : même garde CORS que le JSON.
            if self._type() != "audio/wav":
                return self._json(415, {"erreur": "type"})
            longueur = self._longueur(TAILLE_MAX_DICTEE)
            if longueur is None:
                return
            octets = self.rfile.read(longueur)
            try:
                pcm = pcm_de_wav(octets)
            except ValueError:
                return self._json(400, {"erreur": "format"})
            if len(pcm) < DUREE_MIN_DICTEE_S * TAUX_DICTEE * 2:
                return self._json(400, {"erreur": "trop-court"})
            if VOIX is None:
                return self._json(503, {"erreur": "voix-indisponible", "raison": "hub_voix_logique-absent"})
            langue = VOIX.lire_reglages(service.chemins["reglages"])[1]
            try:
                texte = service.dicteur.reconnaitre(pcm, langue)
            except DicteeIndisponible as erreur:
                journal.warning("dictée impossible : %s", erreur)
                return self._json(503, {"erreur": "voix-indisponible", "raison": str(erreur)})
            resultat = service.traiter_dictee(texte, langue)
            journal.info("dictée : « %s » → %s", resultat["texte"], resultat["commande"])
            self._json(200, resultat)

        def _transfert(self):
            ident = self._jeton()
            if not ident:
                return self._json(401, {"erreur": "jeton"})
            if self._corps() is None:
                return
            origine = self._origine_https()
            if not origine:
                return self._json(404, {"erreur": "https-desactive"})
            ticket = service.creer_ticket(ident)
            if ticket is None:
                return self._json(429, {"erreur": "trop"}, {"Retry-After": str(DUREE_TICKET_S)})
            self._json(200, {"url": f"{origine}/#transfert={ticket}"})

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
                with service._verrou_photos:
                    nom = enregistrer_photo(service.chemins["photos"], octets, service.horloge())
            except PhotoRefusee as refus:
                journal.warning("photo refusée (%s)", refus)
                return self._json(507, {"erreur": str(refus)})
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
            ident, sure = self._jeton_detail()
            if not ident:
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
                resultat = service.executer_commande(nom, texte if nom == "texte" else None,
                                                     ident, sure, self.securise)
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

    def __init__(self, *args, **kwargs):
        self.max_connexions = MAX_CONNEXIONS
        self.max_par_ip = MAX_CONNEXIONS_PAR_IP
        self._verrou_places = threading.Lock()
        self._places = {}
        super().__init__(*args, **kwargs)

    def _reserver(self, ip):
        with self._verrou_places:
            if sum(self._places.values()) >= self.max_connexions or self._places.get(ip, 0) >= self.max_par_ip:
                return False
            self._places[ip] = self._places.get(ip, 0) + 1
            return True

    def _liberer(self, ip):
        with self._verrou_places:
            reste = self._places.get(ip, 0) - 1
            if reste > 0:
                self._places[ip] = reste
            else:
                self._places.pop(ip, None)

    def process_request(self, request, client_address):
        # Au-delà du plafond, la connexion est fermée tout de suite, sans fil : un
        # appareil qui en ouvre des centaines ne prive pas les autres téléphones, au
        # pire de lui-même. Le délai de 10 s par lecture libère les muettes.
        ip = client_address[0]
        if not self._reserver(ip):
            journal.debug("%s : trop de connexions, refusée", ip)
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._liberer(ip)
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._liberer(client_address[0])

    def handle_error(self, request, client_address):
        # Poignée de main TLS ratée (certificat pas encore installé, http sur le port
        # https), client parti : le quotidien d'un service réseau, pas une trace de pile.
        erreur = sys.exc_info()[1]
        journal.debug("%s : connexion abandonnée (%s)", client_address[0], erreur)


class ServeurTLS(Serveur):
    def __init__(self, adresse, gestionnaire, contexte):
        self.contexte = contexte
        super().__init__(adresse, gestionnaire)

    def get_request(self):
        connexion, adresse = self.socket.accept()
        return self.contexte.wrap_socket(connexion, server_side=True,
                                         do_handshake_on_connect=False), adresse


def creer_serveur(service, adresse, port):
    serveur = Serveur((adresse, port), _gestionnaire(service))
    service.publier(adresse, serveur.server_address[1])
    return serveur


def demarrer_ecoutes(service, adresse, port, port_https=None, sondage=0.5):
    """Ouvre http (obligatoire) et https (si possible), publie l'état, lance les fils.

    Rend la liste des serveurs ouverts. Un échec du HTTPS (openssl absent, horloge,
    port pris) est journalisé et n'empêche pas la télécommande http de servir.
    """
    serveurs = [Serveur((adresse, port), _gestionnaire(service))]
    port_http = serveurs[0].server_address[1]
    service.tls_pret = False
    if service.tls is not None and port_https is not None:
        try:
            service.tls.preparer(adresse)
            serveur_tls = ServeurTLS((adresse, port_https), _gestionnaire(service), service.tls.contexte())
            serveurs.append(serveur_tls)
            port_https = serveur_tls.server_address[1]
            service.tls_pret = True
        except (ErreurTLS, OSError, ssl.SSLError) as erreur:
            journal.error("HTTPS indisponible (%s) : télécommande en http seul, sans dictée", erreur)
    service.publier(adresse, port_http, port_https if service.tls_pret else None)
    for serveur in serveurs:
        threading.Thread(target=serveur.serve_forever, args=(sondage,), daemon=True).start()
    return serveurs


# ── Ligne de commande ───────────────────────────────────────────────────────
def _date(ms):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime((ms or 0) / 1000)) if ms else "—"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Télécommande téléphone du HUB.")
    parser.add_argument("--port", type=int, default=PORT, help=f"port d'écoute (défaut {PORT})")
    parser.add_argument("--adresse", help="adresse d'écoute forcée (défaut : celle du réseau local)")
    parser.add_argument("--port-https", type=int, default=PORT_HTTPS,
                        help=f"port HTTPS (défaut {PORT_HTTPS})")
    parser.add_argument("--sans-https", action="store_true",
                        help="ne pas ouvrir le HTTPS local (ni autorité locale, ni dictée)")
    parser.add_argument("--empreinte", action="store_true",
                        help="empreinte SHA-256 du certificat racine à comparer sur le téléphone")
    parser.add_argument("--appairage", action="store_true",
                        help=f"ouvrir l'appairage {FENETRE_APPAIRAGE_S // 60} minutes (sans le menu) et afficher le code")
    parser.add_argument("--lister", action="store_true", help="téléphones appairés")
    parser.add_argument("--revoquer", metavar="ID", help="retirer un téléphone")
    parser.add_argument("--revoquer-tout", action="store_true", help="retirer tous les téléphones")
    parser.add_argument("--autoriser-souris", metavar="ID",
                        help="donner à ce téléphone le droit à la souris et au clavier")
    parser.add_argument("--interdire-souris", metavar="ID",
                        help="retirer à ce téléphone le droit à la souris et au clavier")
    parser.add_argument("--travailleur-dictee", metavar="HUB_VOIX_PY", help=argparse.SUPPRESS)
    parser.add_argument("--modeles", help=argparse.SUPPRESS)
    parser.add_argument("-v", "--verbeux", action="store_true")
    args = parser.parse_args(argv)
    if args.travailleur_dictee:
        return travailleur_dictee(args.travailleur_dictee, args.modeles)
    logging.basicConfig(level=logging.DEBUG if args.verbeux else logging.INFO,
                        format="%(levelname)s %(message)s", stream=sys.stderr)
    chemins = chemins_par_defaut()

    if args.empreinte:
        empreinte = AutoriteLocale(chemins["tls"]).empreinte()
        print(empreinte or "pas encore d'autorité locale (créée au premier démarrage du service)")
        return 0 if empreinte else 1

    if args.appairage:
        # Le recours d'un soir de panne, par SSH : le menu ne s'affiche pas, on veut
        # quand même relier un téléphone.
        FenetreAppairage(chemins["appairage"]).ouvrir()
        print(f"appairage ouvert {FENETRE_APPAIRAGE_S // 60} minutes")
        # Le service publie la fenêtre et le code au plus 5 s plus tard.
        for _ in range(20):
            try:
                etat = json.loads(Path(chemins["etat"]).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                etat = {}
            if etat.get("appairageOuvert"):
                print(f"adresse : {etat.get('url')}\ncode : {etat.get('code')}")
                return 0
            time.sleep(0.5)
        print("service hub-telecommande injoignable (pas de fichier d'état) : est-il lancé ?", file=sys.stderr)
        return 1

    if args.lister or args.revoquer or args.revoquer_tout or args.autoriser_souris or args.interdire_souris:
        jetons = Jetons(chemins["jetons"])
        if args.revoquer:
            if not jetons.revoquer(args.revoquer):
                print(f"aucun téléphone « {args.revoquer} »", file=sys.stderr)
                return 1
            print(f"téléphone {args.revoquer} révoqué")
        if args.revoquer_tout:
            print(f"{jetons.revoquer_tout()} téléphone(s) révoqué(s)")
        if args.autoriser_souris:
            if not jetons.autoriser_pointeur(args.autoriser_souris, True):
                print(f"aucun téléphone « {args.autoriser_souris} »", file=sys.stderr)
                return 1
            print(f"téléphone {args.autoriser_souris} : souris et clavier autorisés")
        if args.interdire_souris:
            if not jetons.autoriser_pointeur(args.interdire_souris, False):
                print(f"aucun téléphone « {args.interdire_souris} »", file=sys.stderr)
                return 1
            print(f"téléphone {args.interdire_souris} : souris et clavier retirés")
        if args.lister:
            liste = jetons.lister()
            if not liste:
                print("aucun téléphone appairé")
            clavier = jetons.avec_clavier()
            for t in liste:
                print(f"{t['id']}  {t['nom'] or '?':<20}  appairé {_date(t['cree'])}  vu {_date(t['vu'])}"
                      f"{'  [souris et clavier possibles]' if t['id'] in clavier else ''}"
                      f"{'  [souris et clavier autorisés]' if t['pointeurAutorise'] else ''}")
        return 0

    if not VOIX:
        journal.warning("hub_voix_logique introuvable : seul le menu est pilotable "
                        "(ni Kodi ni le bureau quand le menu est fermé)")
    service = Service(chemins, tls=None if args.sans_https else AutoriteLocale(chemins["tls"]))
    # Un HUB qui n'appaire plus rien ne ferait jamais le ménage : on l'ouvre ici aussi.
    oublies = service.jetons.menage()
    if oublies:
        journal.info("%d téléphone(s) jamais revu(s) depuis %d jours : oublié(s)",
                     oublies, OUBLI_TELEPHONE_S // 86400)
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
            serveurs = demarrer_ecoutes(service, adresse, args.port,
                                        None if args.sans_https else args.port_https)
        except OSError as erreur:
            journal.error("écoute impossible sur %s:%s (%s)", adresse, args.port, erreur)
            service.effacer_etat()
            arret.wait(5)
            continue
        journal.info("télécommande sur %s%s", service.url,
                     f" et {service.url_https}" if service.url_https else "")
        prochain_certificat = time.monotonic() + 3600
        while not arret.wait(5):
            service.appairage.verifier_expiration()
            service.verifier_fenetre()
            service.dicteur.entretien()
            # Un HUB peut tourner des mois sans redémarrer : le certificat se renouvelle
            # 30 jours avant son terme, en rouvrant l'écoute avec le nouveau.
            if service.tls_pret and time.monotonic() > prochain_certificat:
                prochain_certificat = time.monotonic() + 3600
                if service.tls.a_renouveler():
                    journal.info("certificat du HUB bientôt expiré : renouvellement")
                    break
            # Bail DHCP renouvelé sur une autre adresse : on rouvre l'écoute dessus,
            # sinon le QR code montrerait une adresse morte jusqu'au prochain démarrage.
            if not args.adresse and adresse_locale() != adresse:
                journal.info("l'adresse a changé : réouverture de l'écoute")
                break
        service.pointeur.fermer("arrêt de l'écoute")
        for serveur in serveurs:
            serveur.shutdown()
            serveur.server_close()
    service.effacer_etat()
    service.dicteur.arreter()
    return 0


if __name__ == "__main__":
    sys.exit(main())
