#!/usr/bin/env python3
"""Enceinte réseau du HUB : Spotify Connect, AirPlay (son) et recopie d'écran AirPlay.

TROIS RÉCEPTEURS, UN COORDINATEUR. librespot (Spotify), shairport-sync (AirPlay son)
et UxPlay (recopie d'écran) tournent chacun dans leur unité systemd utilisateur : si
l'un plante, systemd le relance sans toucher aux autres. Ce programme ne joue aucun
son. Il :

  - fabrique leurs lignes de commande et leurs configurations à partir des réglages
    du menu (`lancer <source>`), pour qu'un seul endroit décide des ports et du nom ;
  - dit à systemd si un récepteur est désactivé (`actif <source>`, en ExecCondition) ;
  - rassemble ce qu'ils racontent (crochet de librespot, tube de métadonnées de
    shairport-sync, journal d'UxPlay) en UN état de lecture, écrit dans
    $XDG_RUNTIME_DIR/hub/lecture.json, que le menu relaie à sa page (`servir`) ;
  - applique la règle de priorité avec Kodi (voir `Lecture`).

LA RÈGLE DE PRIORITÉ. La dernière source qui démarre gagne, Kodi compris :
  - une source réseau qui passe en lecture met Kodi en pause (JSON-RPC, 127.0.0.1:9090)
    et arrête les autres sources réseau qui jouaient ;
  - Kodi qui (re)lance une lecture arrête les sources réseau qui jouaient.
Deux sons superposés n'ont jamais de sens dans un salon, et « qui a appuyé en dernier »
est la seule intention qu'on peut lire sans rien demander.

Bibliothèque standard seule : ce fichier se teste sans rien installer
(installer/enceinte/test_hub_enceinte.py).
"""

import base64
import binascii
import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

SOURCES = ("spotify", "airplay", "ecran")
UNITES = {
    "spotify": "hub-spotify.service",
    "airplay": "hub-airplay.service",
    "ecran": "hub-airplay-ecran.service",
}
ETATS = ("lecture", "pause", "arret")

# Ports FIXES : le pare-feu de l'installateur les ouvre au réseau local, un port choisi
# au hasard à chaque démarrage ne pourrait pas l'être. UxPlay est décalé à 7000 parce
# que ses ports historiques (UDP 6000-6001) chevauchent ceux de shairport-sync.
PORT_SPOTIFY = 5390
PORT_AIRPLAY = 5000
PORTS_UDP_AIRPLAY = (6001, 10)       # base, étendue
PORT_ECRAN = 7000                    # TCP et UDP 7000, 7001, 7002

LIBRESPOT = os.environ.get("HUB_LIBRESPOT", "/opt/hub-enceinte/librespot")
SHAIRPORT = os.environ.get("HUB_SHAIRPORT", "/usr/bin/shairport-sync")
UXPLAY = os.environ.get("HUB_UXPLAY", "/usr/bin/uxplay")
MOI = "/usr/local/bin/hub-enceinte"

NOM_DEFAUT = "HUB"
# Le cache audio de Spotify grossit sans fin si on ne le borne pas ; 500 Mo gardent
# quelques albums écoutés souvent, sans remplir un NVMe de 238 Go à la longue.
CACHE_SPOTIFY = "500M"
KODI = ("127.0.0.1", 9090)
TAILLE_POCHETTE_MAX = 2_000_000


def dossier(variable, defaut):
    return Path(os.environ.get(variable) or defaut)


def chemins():
    maison = Path.home()
    execution = dossier("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}") / "hub"
    config = dossier("XDG_CONFIG_HOME", maison / ".config") / "hub"
    return {
        "reglages": config / "reglages.json",
        "config": config / "enceinte",
        "cache": dossier("XDG_CACHE_HOME", maison / ".cache") / "hub" / "spotify",
        "etat-spotify": dossier("XDG_STATE_HOME", maison / ".local/state") / "hub" / "spotify",
        "execution": execution,
        "socket": execution / "enceinte.sock",
        "lecture": execution / "lecture.json",
        "pochettes": execution / "pochettes",
        "tube-airplay": execution / "airplay-metadonnees",
        "conf-airplay": execution / "shairport-sync.conf",
        "applique": execution / "enceinte-applique.json",
    }


def ecrire_atomique(chemin, texte):
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_name(chemin.name + ".tmp")
    provisoire.write_text(texte, encoding="utf-8")
    os.replace(provisoire, chemin)


# ── Réglages ──────────────────────────────────────────────────────────────
def nom_propre(nom):
    """Le nom affiché dans Spotify et sur l'iPhone. Les caractères de contrôle cassent
    l'annonce mDNS, et 40 caractères suffisent à toute liste d'appareils."""
    if not isinstance(nom, str):
        return NOM_DEFAUT
    nom = "".join(ch for ch in nom if ch.isprintable()).strip()[:40].strip()
    return nom or NOM_DEFAUT


def reglages_enceinte(reglages):
    """systeme.enceinte de ~/.config/hub/reglages.json, complété. Tout est actif par
    défaut : l'installateur a posé les récepteurs pour qu'ils servent."""
    brut = ((reglages or {}).get("systeme") or {}).get("enceinte") if isinstance(reglages, dict) else None
    brut = brut if isinstance(brut, dict) else {}
    return {
        "spotify": brut.get("spotify") is not False,
        "airplay": brut.get("airplay") is not False,
        "ecran": brut.get("ecran") is not False,
        "nom": nom_propre(brut.get("nom", NOM_DEFAUT)),
    }


def lire_reglages(c):
    try:
        return reglages_enceinte(json.loads(Path(c["reglages"]).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return reglages_enceinte(None)


def nom_ecran(nom):
    # Deux récepteurs AirPlay sur la même machine : des noms distincts, sinon Avahi
    # renomme le second « HUB #2 » et l'iPhone montre deux « HUB » indiscernables.
    return f"{nom} Écran"


def signature(r, source):
    """Ce qui, dans les réglages, oblige à relancer un récepteur quand ça change."""
    return {"actif": r[source], "nom": r["nom"]}


# ── Lignes de commande et configurations ──────────────────────────────────
def arguments_librespot(r, c, programme=LIBRESPOT, moi=MOI):
    return [
        programme,
        "--name", r["nom"],
        "--device-type", "speaker",
        # PipeWire par sa couche PulseAudio : le son rejoint la sortie choisie pour la
        # session (jack ou HDMI), et le volume du HUB s'applique par-dessus.
        "--backend", "pulseaudio",
        # Volume logiciel : le curseur du téléphone agit sur librespot seul, jamais sur
        # le volume général du HUB que Kodi et le menu partagent.
        "--mixer", "softvol",
        "--volume-ctrl", "log",
        "--initial-volume", "60",
        "--bitrate", "320",
        "--cache", str(c["cache"]),
        "--system-cache", str(c["etat-spotify"]),
        "--cache-size-limit", CACHE_SPOTIFY,
        "--zeroconf-port", str(PORT_SPOTIFY),
        "--zeroconf-backend", "avahi",
        # librespot découpe la commande sur les espaces : pas de guillemets possibles,
        # d'où un chemin sans espace.
        "--onevent", f"{moi} evenement spotify",
    ]


def chaine_libconfig(texte):
    return '"' + texte.replace("\\", "\\\\").replace('"', '\\"') + '"'


def config_shairport(r, c):
    base, etendue = PORTS_UDP_AIRPLAY
    return f"""// Écrit par hub-enceinte à chaque démarrage de hub-airplay : ne pas modifier ici,
// changer le nom dans le menu (Réglages → Enceinte réseau).
general = {{
  name = {chaine_libconfig(r["nom"])};
  output_backend = "pa";
  mdns_backend = "avahi";
  port = {PORT_AIRPLAY};
  udp_port_base = {base};
  udp_port_range = {etendue};
  // Interfaces D-Bus sur le bus de la SESSION : c'est là que hub-enceinte peut
  // demander une pause (MPRIS) sans droits particuliers.
  dbus_service_bus = "session";
  mpris_service_bus = "session";
}};
sessioncontrol = {{
  // Un autre téléphone de la maison peut prendre la main sans attendre deux minutes.
  allow_session_interruption = "yes";
  session_timeout = 20;
}};
pa = {{
  application_name = "HUB AirPlay";
}};
metadata = {{
  enabled = "yes";
  include_cover_art = "yes";
  cover_art_cache_directory = "";
  pipe_name = {chaine_libconfig(str(c["tube-airplay"]))};
  pipe_timeout = 5000;
}};
"""


def arguments_uxplay(r, c, programme=UXPLAY):
    return [
        programme,
        "-n", nom_ecran(r["nom"]),
        "-nh",
        "-p", str(PORT_ECRAN),
        # Plein écran par Wayland : la session kiosque n'a pas de X11.
        "-vs", "waylandsink", "-fs",
        "-as", "pulsesink",
        # Un second appareil remplace le premier au lieu d'être refusé : dans un salon,
        # celui qui vient d'appuyer veut voir son écran.
        "-nohold",
        "-scrsv", "1",
        # Clé gardée : sans elle, l'iPhone voit un nouvel appareil à chaque démarrage.
        "-key", str(c["config"] / "uxplay.pem"),
        # Niveau 1 : les messages de connexion sans le détail des paquets. C'est la
        # seule façon de savoir quand une recopie commence et finit (voir ligne_uxplay).
        "-d", "1",
    ]


# ── Ce que racontent les récepteurs ───────────────────────────────────────
def evenement_librespot(env):
    """Variables d'environnement du crochet --onevent de librespot 0.8 → événement."""
    genre = env.get("PLAYER_EVENT", "")
    ev = {"source": "spotify"}
    if genre == "track_changed":
        artistes = [a for a in env.get("ARTISTS", "").split("\n") if a]
        couvertures = [u for u in env.get("COVERS", "").split("\n") if u.startswith("https://")]
        ev.update({
            "nouvellePiste": True,
            "piste": env.get("TRACK_ID") or None,
            "titre": env.get("NAME") or None,
            # Un épisode de podcast n'a pas d'artiste : son émission en tient lieu.
            "artiste": ", ".join(artistes) or env.get("SHOW_NAME") or None,
            "album": env.get("ALBUM") or None,
            "pochetteUrl": couvertures[0] if couvertures else None,
        })
        return ev
    if genre == "playing":
        return {**ev, "etat": "lecture"}
    if genre == "paused":
        return {**ev, "etat": "pause"}
    if genre in ("stopped", "session_disconnected"):
        return {**ev, "etat": "arret"}
    if genre == "session_client_changed" and env.get("CLIENT_NAME"):
        return {**ev, "appareil": env["CLIENT_NAME"]}
    return None


class MetadonneesAirplay:
    """Lit le tube de métadonnées de shairport-sync (format XML simple, données en base64).

    Les éléments arrivent par morceaux et peuvent être coupés n'importe où : on garde le
    reste et on ne décode que les <item> complets."""

    ELEMENT = re.compile(
        rb"<item><type>([0-9a-f]{8})</type><code>([0-9a-f]{8})</code><length>(\d+)</length>"
        rb"(?:\s*<data encoding=\"base64\">\s*(.*?)</data>)?\s*</item>", re.S)

    def __init__(self):
        self.reste = b""
        self.piste = 0

    def nourrir(self, octets):
        self.reste += octets
        evenements = []
        fin = 0
        for m in self.ELEMENT.finditer(self.reste):
            fin = m.end()
            ev = self.traduire(bytes.fromhex(m.group(1).decode()), bytes.fromhex(m.group(2).decode()), m.group(4))
            if ev:
                evenements.append(ev)
        self.reste = self.reste[fin:].lstrip()
        # Un flux corrompu ne doit pas faire grossir le tampon sans fin (une pochette
        # tient largement dans 4 Mo une fois en base64).
        if len(self.reste) > 4_000_000:
            self.reste = b""
        return evenements

    def traduire(self, genre, code, donnees_b64):
        try:
            donnees = base64.b64decode(donnees_b64 or b"", validate=False)
        except (binascii.Error, ValueError):
            return None
        texte = lambda: donnees.decode("utf-8", "replace").strip() or None  # noqa: E731
        ev = {"source": "airplay"}
        if genre == b"ssnc":
            if code in (b"pbeg", b"prsm"):
                return {**ev, "etat": "lecture"}
            if code == b"pfls":
                return {**ev, "etat": "pause"}
            if code in (b"pend", b"aend"):
                return {**ev, "etat": "arret"}
            if code == b"mdst":
                self.piste += 1
                return {**ev, "nouvellePiste": True, "piste": f"a{self.piste}"}
            if code == b"PICT" and donnees:
                return {**ev, "pochetteOctets": donnees, "piste": f"a{self.piste}"}
            if code == b"snam":
                return {**ev, "appareil": texte()}
        elif genre == b"core":
            champ = {b"minm": "titre", b"asar": "artiste", b"asal": "album"}.get(code)
            if champ:
                return {**ev, champ: texte()}
        return None


RE_UXPLAY_DEBUT = re.compile(r"connection request from (.+?) \((.*?)\) with deviceID")
RE_UXPLAY_CONNEXIONS = re.compile(r"Open connections: (\d+)")


def ligne_uxplay(ligne):
    """UxPlay 1.73 n'a pas de crochet : son journal (-d 1) dit quand un appareil demande
    la recopie, et quand la dernière connexion se ferme."""
    m = RE_UXPLAY_DEBUT.search(ligne)
    if m:
        return {"source": "ecran", "etat": "lecture", "appareil": m.group(1).strip() or None}
    m = RE_UXPLAY_CONNEXIONS.search(ligne)
    if m and int(m.group(1)) == 0:
        return {"source": "ecran", "etat": "arret"}
    return None


# ── L'état de lecture et la règle de priorité ─────────────────────────────
CHAMPS = ("titre", "artiste", "album", "appareil")


class Lecture:
    """État de chaque source et décisions de priorité. Aucune entrée-sortie : les
    actions rendues (« mettre Kodi en pause », « arrêter spotify ») sont exécutées par
    le coordinateur, ce qui permet de tester la règle sans Kodi ni systemd."""

    def __init__(self):
        self.sources = {}

    def appliquer(self, ev, maintenant=None):
        maintenant = time.time() if maintenant is None else maintenant
        s = ev.get("source")
        if s not in SOURCES:
            return []
        etat = self.sources.setdefault(s, {"etat": "arret"})
        avant = etat["etat"]
        if ev.get("nouvellePiste"):
            for k in (*CHAMPS[:3], "pochette"):
                etat.pop(k, None)
            etat["piste"] = ev.get("piste")
        for k in CHAMPS:
            if k in ev:
                etat[k] = ev[k][:200] if isinstance(ev[k], str) else None
        # Une pochette téléchargée après coup ne vaut que pour la piste qui l'a demandée.
        if "pochette" in ev and etat.get("piste") in (None, ev.get("piste")):
            etat["pochette"] = ev["pochette"]
        actions = []
        nouveau = ev.get("etat")
        if nouveau == "arret":
            # Une source arrêtée n'a plus rien à montrer ; sa prochaine lecture repartira
            # de ses propres métadonnées.
            del self.sources[s]
        elif nouveau in ETATS:
            etat["etat"] = nouveau
            if nouveau != avant:
                etat["depuis"] = maintenant
            if nouveau == "lecture" and avant != "lecture":
                actions.append(("kodi-pause",))
                actions += self.arreter_sauf(s)
        return actions

    def arreter_sauf(self, garder=None):
        arretees = [s for s, e in self.sources.items() if s != garder and e["etat"] == "lecture"]
        for s in arretees:
            del self.sources[s]
        return [("arreter", s) for s in arretees]

    def kodi_lecture(self):
        return self.arreter_sauf()

    def publique(self):
        """Ce que le menu affiche : la source qui joue (la plus récente), sinon celle en
        pause la plus récente, sinon rien."""
        rang = {"lecture": 1, "pause": 0}
        visibles = [kv for kv in self.sources.items() if kv[1]["etat"] in rang]
        if not visibles:
            return None
        s, e = max(visibles, key=lambda kv: (rang[kv[1]["etat"]], kv[1].get("depuis", 0)))
        return {
            "source": s,
            "etat": e["etat"],
            "titre": e.get("titre"),
            "artiste": e.get("artiste"),
            "album": e.get("album"),
            "appareil": e.get("appareil"),
            "pochette": e.get("pochette"),
            "ecran": self.sources.get("ecran", {}).get("etat") == "lecture",
        }


# ── Kodi par JSON-RPC ─────────────────────────────────────────────────────
ID_JOUEURS = 7001
DECODEUR = json.JSONDecoder()


def decouper_json(tampon):
    """Le port TCP de Kodi enchaîne des objets JSON sans séparateur."""
    objets, i = [], 0
    texte = tampon.decode("utf-8", "replace")
    while True:
        while i < len(texte) and texte[i].isspace():
            i += 1
        if i >= len(texte):
            return objets, b""
        try:
            objet, i = DECODEUR.raw_decode(texte, i)
        except ValueError:
            return objets, texte[i:].encode("utf-8")
        objets.append(objet)


def requete_kodi(methode, params=None, ident=None):
    r = {"jsonrpc": "2.0", "method": methode}
    if params is not None:
        r["params"] = params
    if ident is not None:
        r["id"] = ident
    return json.dumps(r).encode()


def reponse_kodi(objet):
    """Un objet reçu de Kodi → ce qu'il faut faire : (« kodi-lecture »,) quand Kodi
    lance ou reprend une lecture, ou les requêtes de pause des joueurs actifs."""
    if not isinstance(objet, dict):
        return None, []
    if objet.get("method") in ("Player.OnPlay", "Player.OnResume"):
        return "kodi-lecture", []
    if objet.get("id") == ID_JOUEURS and isinstance(objet.get("result"), list):
        # play: false est une pause idempotente : un joueur déjà en pause y reste.
        return None, [requete_kodi("Player.PlayPause", {"playerid": j["playerid"], "play": False}, 7002)
                      for j in objet["result"] if isinstance(j, dict) and "playerid" in j]
    return None, []


# ── Le coordinateur ───────────────────────────────────────────────────────
class Coordinateur:
    def __init__(self, c, executer=subprocess.run, kodi=KODI):
        self.c = c
        self.adresse_kodi = kodi
        self.lecture = Lecture()
        self.executer = executer
        self.selecteur = selectors.DefaultSelector()
        self.kodi = None
        self.kodi_tampon = b""
        self.kodi_essai = 0
        self.airplay = MetadonneesAirplay()
        self.publiee = "absent"

    # Entrées ─────────────────────────────────────────────────────────────
    def ouvrir(self):
        ex = Path(self.c["execution"])
        ex.mkdir(parents=True, exist_ok=True, mode=0o700)
        Path(self.c["socket"]).unlink(missing_ok=True)
        self.ecoute = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.ecoute.bind(str(self.c["socket"]))
        os.chmod(self.c["socket"], 0o600)
        self.ecoute.setblocking(False)
        self.selecteur.register(self.ecoute, selectors.EVENT_READ, self.datagramme)
        tube = Path(self.c["tube-airplay"])
        if tube.exists() and not stat.S_ISFIFO(tube.stat().st_mode):
            tube.unlink()
        if not tube.exists():
            os.mkfifo(tube, 0o600)
        self.tube = os.open(tube, os.O_RDONLY | os.O_NONBLOCK)
        # Un écrivain gardé ouvert par nous-mêmes : sans lui, chaque fois que
        # shairport-sync ferme le tube, la lecture rendrait « fin de fichier » en boucle.
        self.tube_ecrivain = os.open(tube, os.O_WRONLY | os.O_NONBLOCK)
        self.selecteur.register(self.tube, selectors.EVENT_READ, self.metadonnees)
        self.publier()

    def datagramme(self, _):
        while True:
            try:
                brut = self.ecoute.recv(65536)
            except BlockingIOError:
                return
            try:
                ev = json.loads(brut)
            except ValueError:
                continue
            if isinstance(ev, dict):
                self.traiter(ev)

    def metadonnees(self, _):
        try:
            octets = os.read(self.tube, 262144)
        except BlockingIOError:
            return
        for ev in self.airplay.nourrir(octets):
            self.traiter(ev)

    def traiter(self, ev):
        # Les octets d'une pochette AirPlay deviennent un fichier avant d'entrer dans l'état.
        if "pochetteOctets" in ev:
            ev = {"source": ev["source"], "piste": ev.get("piste"),
                  "pochette": self.poser_pochette(ev["source"], ev.pop("pochetteOctets"))}
        url = ev.pop("pochetteUrl", None)
        for action in self.lecture.appliquer(ev):
            self.agir(action)
        if url:
            threading.Thread(target=self.telecharger_pochette, args=(ev["source"], ev.get("piste"), url), daemon=True).start()
        self.publier()

    # Pochettes ───────────────────────────────────────────────────────────
    def poser_pochette(self, source, octets):
        if not octets or len(octets) > TAILLE_POCHETTE_MAX:
            return None
        ext = ".png" if octets.startswith(b"\x89PNG") else ".jpg"
        dossier_p = Path(self.c["pochettes"])
        dossier_p.mkdir(parents=True, exist_ok=True)
        fichier = dossier_p / f"{source}-{hashlib.sha1(octets).hexdigest()[:16]}{ext}"
        for ancien in dossier_p.glob(f"{source}-*"):
            if ancien != fichier:
                ancien.unlink(missing_ok=True)
        if not fichier.exists():
            fichier.write_bytes(octets)
        return fichier.as_uri()

    def telecharger_pochette(self, source, piste, url):
        try:
            requete = urllib.request.Request(url, headers={"User-Agent": "HUB-enceinte"})
            with urllib.request.urlopen(requete, timeout=6) as r:
                if not r.headers.get("Content-Type", "").startswith("image/"):
                    return
                octets = r.read(TAILLE_POCHETTE_MAX + 1)
        except (OSError, ValueError):
            return
        uri = self.poser_pochette(source, octets)
        if uri:
            # Retour par notre propre socket : l'état ne se modifie que dans la boucle.
            envoyer({"source": source, "piste": piste, "pochette": uri}, self.c)

    # Sorties ─────────────────────────────────────────────────────────────
    def publier(self):
        etat = self.lecture.publique()
        if etat == self.publiee:
            return
        self.publiee = etat
        if etat is None:
            Path(self.c["lecture"]).unlink(missing_ok=True)
        else:
            ecrire_atomique(self.c["lecture"], json.dumps(etat, ensure_ascii=False))

    def agir(self, action):
        if action[0] == "kodi-pause":
            self.kodi_pause()
        elif action[0] == "arreter":
            threading.Thread(target=arreter_source, args=(action[1], self.executer), daemon=True).start()

    def kodi_connecter(self, delai=0.3):
        if self.kodi:
            return True
        try:
            s = socket.create_connection(self.adresse_kodi, timeout=delai)
        except OSError:
            return False
        s.setblocking(False)
        self.kodi, self.kodi_tampon = s, b""
        self.selecteur.register(s, selectors.EVENT_READ, self.kodi_lire)
        return True

    def kodi_fermer(self):
        if self.kodi:
            self.selecteur.unregister(self.kodi)
            self.kodi.close()
            self.kodi = None

    def kodi_pause(self):
        # Kodi ne tourne pas : il n'y a rien à mettre en pause, et ce n'est pas une erreur.
        if self.kodi_connecter():
            try:
                self.kodi.sendall(requete_kodi("Player.GetActivePlayers", ident=ID_JOUEURS))
            except OSError:
                self.kodi_fermer()

    def kodi_lire(self, _):
        try:
            octets = self.kodi.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            octets = b""
        if not octets:
            self.kodi_fermer()
            return
        objets, self.kodi_tampon = decouper_json(self.kodi_tampon + octets)
        for objet in objets:
            genre, requetes = reponse_kodi(objet)
            for r in requetes:
                try:
                    self.kodi.sendall(r)
                except OSError:
                    self.kodi_fermer()
                    return
            if genre == "kodi-lecture":
                for action in self.lecture.kodi_lecture():
                    self.agir(action)
                self.publier()

    def tourner_une_fois(self, delai=1):
        # Kodi va et vient avec le mode TV : on se reconnecte pour entendre ses
        # « Player.OnPlay », sans le lancer ni l'attendre.
        if not self.kodi and time.monotonic() - self.kodi_essai > 3:
            self.kodi_essai = time.monotonic()
            self.kodi_connecter()
        for cle, _ in self.selecteur.select(timeout=delai):
            cle.data(cle)

    def fermer(self):
        Path(self.c["lecture"]).unlink(missing_ok=True)
        Path(self.c["socket"]).unlink(missing_ok=True)

    def servir(self):
        self.ouvrir()
        arret = []
        signal.signal(signal.SIGTERM, lambda *_: arret.append(1))
        try:
            while not arret:
                self.tourner_une_fois()
        finally:
            self.fermer()


def arreter_source(source, executer=subprocess.run):
    """Arrêter une source réseau. AirPlay sait se mettre en pause (MPRIS, relayé à
    l'iPhone par DACP) ; Spotify Connect n'offre aucune commande locale à librespot, et
    UxPlay non plus : on relance leur unité, ce qui coupe la session proprement — le
    téléphone voit l'appareil disparaître et s'arrête."""
    if source == "airplay":
        r = executer(["gdbus", "call", "--session", "--dest", "org.mpris.MediaPlayer2.ShairportSync",
                      "--object-path", "/org/mpris/MediaPlayer2", "--method", "org.mpris.MediaPlayer2.Player.Pause"],
                     capture_output=True, timeout=5)
        if getattr(r, "returncode", 1) == 0:
            return
    executer(["systemctl", "--user", "restart", UNITES[source]], capture_output=True, timeout=30)


def envoyer(ev, c=None):
    c = c or chemins()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(json.dumps(ev).encode(), str(c["socket"]))
        return True
    except OSError:
        return False


# ── Appliquer les réglages ────────────────────────────────────────────────
def a_relancer(r, applique):
    """Les sources dont le réglage a changé depuis leur dernier lancement."""
    applique = applique if isinstance(applique, dict) else {}
    return [s for s in SOURCES if applique.get(s) != signature(r, s)]


def noter_lancement(c, r, source):
    try:
        applique = json.loads(Path(c["applique"]).read_text())
    except (OSError, ValueError):
        applique = {}
    applique[source] = signature(r, source)
    ecrire_atomique(c["applique"], json.dumps(applique))


def appliquer(c, executer=subprocess.run):
    r = lire_reglages(c)
    try:
        applique = json.loads(Path(c["applique"]).read_text())
    except (OSError, ValueError):
        applique = {}
    relances = a_relancer(r, applique)
    for s in relances:
        # restart réévalue ExecCondition : une source désactivée s'arrête et ne repart
        # pas, une source réactivée démarre.
        executer(["systemctl", "--user", "restart", UNITES[s]], capture_output=True, timeout=30)
        if not r[s]:
            applique[s] = signature(r, s)
    ecrire_atomique(c["applique"], json.dumps(applique))
    return relances


# ── Lanceurs ──────────────────────────────────────────────────────────────
def environnement_uxplay(env):
    """UxPlay 1.73 plante (std::string construite depuis NULL) quand -scrsv trouve un bus
    de session mais pas XDG_CURRENT_DESKTOP — vu en conteneur le 15/09/2026. Une unité
    utilisateur n'hérite de cette variable que si la session l'a importée : on ne parie pas."""
    env = dict(env)
    env.setdefault("XDG_CURRENT_DESKTOP", "GNOME")
    return env


def lancer_ecran(c, r):
    Path(c["config"]).mkdir(parents=True, exist_ok=True)
    enfant = subprocess.Popen(arguments_uxplay(r, c), env=environnement_uxplay(os.environ),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors="replace", bufsize=1)
    signal.signal(signal.SIGTERM, lambda *_: enfant.terminate())
    actif = False
    for ligne in enfant.stdout:
        sys.stdout.write(ligne)
        ev = ligne_uxplay(ligne)
        if ev and (ev["etat"] == "lecture" or actif):
            actif = ev["etat"] == "lecture"
            envoyer(ev, c)
    code = enfant.wait()
    envoyer({"source": "ecran", "etat": "arret"}, c)
    return code


def principal(argv):
    c = chemins()
    commande = argv[1] if len(argv) > 1 else ""
    source = argv[2] if len(argv) > 2 else ""
    if commande == "servir":
        Coordinateur(c).servir()
        return 0
    if commande == "evenement" and source in SOURCES:
        # Explicite (ExecStopPost : « evenement spotify arret »), sinon l'environnement
        # du crochet de librespot.
        if len(argv) > 3 and argv[3] in ETATS:
            ev = {"source": source, "etat": argv[3]}
        else:
            ev = evenement_librespot(os.environ) if source == "spotify" else None
        if ev:
            envoyer(ev, c)
        return 0
    if commande == "actif" and source in SOURCES:
        programme = {"spotify": LIBRESPOT, "airplay": SHAIRPORT, "ecran": UXPLAY}[source]
        # 1 : ExecCondition saute l'unité sans la marquer en échec.
        return 0 if lire_reglages(c)[source] and shutil.which(programme) else 1
    if commande == "lancer" and source in SOURCES:
        r = lire_reglages(c)
        noter_lancement(c, r, source)
        if source == "spotify":
            for d in (c["cache"], c["etat-spotify"]):
                Path(d).mkdir(parents=True, exist_ok=True)
            args = arguments_librespot(r, c)
            os.execv(args[0], args)
        if source == "airplay":
            ecrire_atomique(c["conf-airplay"], config_shairport(r, c))
            os.execv(SHAIRPORT, [SHAIRPORT, "-c", str(c["conf-airplay"])])
        return lancer_ecran(c, r)
    if commande == "appliquer":
        print(" ".join(appliquer(c)) or "rien à relancer")
        return 0
    if commande == "config" and source in SOURCES:
        r = lire_reglages(c)
        sortie = {"spotify": lambda: " ".join(arguments_librespot(r, c)),
                  "airplay": lambda: config_shairport(r, c),
                  "ecran": lambda: " ".join(arguments_uxplay(r, c))}[source]()
        print(sortie)
        return 0
    print("usage : hub-enceinte servir | lancer SOURCE | actif SOURCE | evenement SOURCE [ETAT]\n"
          "                     | appliquer | config SOURCE        (SOURCE : spotify, airplay, ecran)",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(principal(sys.argv))
