#!/usr/bin/env python3
"""Menu d'accueil du HUB : les modes, les réglages, la météo.

POURQUOI UN PROGRAMME GRAPHIQUE. La première version était un script bash qui lisait
le clavier dans un terminal. Éprouvée sur Ubuntu 26.04 (Wayland seul, plus de
serveur Xorg), elle ne pouvait rien afficher : une session graphique n'a pas de
terminal. Ce menu tourne dans la session kiosque de GNOME
(gnome-kiosk-script-session), qui l'affiche en plein écran.

POURQUOI WEBKIT. L'interface (menu/) veut du verre dépoli, des fonds animés et des
cartes qui réagissent au choix. GTK n'a pas de flou d'arrière-plan ; WebKitGTK, si.
La page est locale : seule la météo a besoin du réseau. Si WebKit manque, le menu
retombe sur des boutons GTK simples plutôt que de laisser la TV sur un écran noir.

CE QU'IL FAIT. Il affiche la page, lui passe les réglages au démarrage, et répond à
ses demandes (enregistrer les réglages, météo, minuteur, infos machine). Il relaie
aussi les commandes de hub-voix, reçues sur un socket. Quand un mode est choisi, il
l'écrit sur la sortie standard et se termine : c'est le script de session qui lance
le mode puis, à sa fin, relance ce menu.

Ce fichier n'importe GTK qu'au lancement : ses fonctions se testent sans écran
(tests/test_hub_menu.py).
"""

import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

MODES = ("tv", "gaming", "bureau", "eteindre", "web")
# « web:<service> » : « HUB, lance Netflix ». Le nom seul voyage, jamais une adresse ;
# hub-web a la liste blanche qui le traduit (tests/test_hub_web.py vérifie l'accord).
# Écrit en littéral : installer/telecommande en recopie la liste et la compare.
COMMANDES = {
    "tv", "gaming", "bureau", "eteindre", "reglages", "aide", "meteo", "profils",
    "retour", "gauche", "droite", "haut", "bas", "ok", "theme:clair", "theme:sombre",
    "web:youtube", "web:netflix", "web:primevideo", "web:disneyplus", "web:canalplus",
    "web:twitch", "web:arte", "web:francetv", "web:geforcenow", "web:xcloud",
    "web:boosteroid", "web:steam", "web:moonlight",
}
SERVICES_WEB = frozenset(c[4:] for c in COMMANDES if c.startswith("web:"))
ETATS_VOIX = {"eveil", "repos", "incompris", "micro-absent", "micro-present"}

URL_METEO = (
    "https://api.open-meteo.com/v1/forecast?current=temperature_2m,apparent_temperature,"
    "weather_code,is_day,wind_speed_10m,relative_humidity_2m&hourly=temperature_2m,"
    "weather_code,precipitation_probability,is_day&daily=weather_code,temperature_2m_max,"
    "temperature_2m_min,sunrise,sunset,precipitation_probability_max&timezone=auto&forecast_days=7"
)
URL_GEOCODAGE = "https://geocoding-api.open-meteo.com/v1/search"
METEO_FRAICHE_S = 15 * 60
UNITE_MINUTEUR = "hub-minuteur"


def dossier(variable, defaut):
    return Path(os.environ.get(variable) or defaut)


def chemins():
    maison = Path.home()
    execution = dossier("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}") / "hub"
    return {
        "reglages": dossier("XDG_CONFIG_HOME", maison / ".config") / "hub" / "reglages.json",
        "dernier": dossier("XDG_STATE_HOME", maison / ".local/state") / "hub" / "dernier-choix",
        "meteo": dossier("XDG_CACHE_HOME", maison / ".cache") / "hub" / "meteo.json",
        "pin-echecs": dossier("XDG_STATE_HOME", maison / ".local/state") / "hub" / "pin-echecs.json",
        "execution": execution,
        "socket": execution / "menu.sock",
        "deja-ouvert": execution / "menu-deja-ouvert",
        "minuteur": execution / "minuteur-fin",
        "telecommande": execution / "telecommande.json",
        "telecommande-appairage": execution / "telecommande-appairage",
        "lecture": execution / "lecture.json",
        "recopie-code": execution / "recopie-code.json",
    }


# ── Fichiers ──────────────────────────────────────────────────────────────
def ecrire_atomique(chemin, texte, droits=None):
    """Un réglage à moitié écrit (coupure pendant l'écriture) ne doit jamais remplacer
    le précédent : on écrit à côté, puis on renomme.

    droits (0o600…) : posés sur le provisoire avant la première écriture, pour que le
    contenu ne soit jamais lisible, même un instant, avec les droits de l'umask."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_name(chemin.name + ".tmp")
    if droits is None:
        provisoire.write_text(texte, encoding="utf-8")
    else:
        # Un nom par fil : la vérification d'un code (en arrière-plan) peut réécrire les
        # réglages pendant que la page les enregistre.
        provisoire = chemin.with_name(f"{chemin.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        provisoire.unlink(missing_ok=True)
        descripteur = os.open(provisoire, os.O_WRONLY | os.O_CREAT | os.O_EXCL, droits)
        with os.fdopen(descripteur, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), droits)
            f.write(texte)
    os.replace(provisoire, chemin)


def lire_json(chemin):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def reglages_valides(donnees):
    return (
        isinstance(donnees, dict)
        and isinstance(donnees.get("profils"), list)
        and 0 < len(donnees["profils"]) <= 12
        and all(isinstance(p, dict) and isinstance(p.get("id"), str) for p in donnees["profils"])
        and len(json.dumps(donnees)) < 256_000
    )


# reglages.json porte les empreintes des codes PIN : lisible par le seul utilisateur du
# HUB. hub-allumage le lit en root, hub-temps-ecran et hub-cec en tant que cet
# utilisateur : aucun autre compte n'en a besoin.
DROITS_REGLAGES = 0o600


def restreindre_droits(chemin, droits=DROITS_REGLAGES):
    """Un fichier écrit par une version antérieure (0644 selon l'umask) est resserré."""
    try:
        if os.stat(chemin).st_mode & 0o777 != droits:
            os.chmod(chemin, droits)
    except OSError:
        pass


def charger_reglages(c):
    restreindre_droits(c["reglages"])
    donnees = lire_json(c["reglages"])
    return donnees if reglages_valides(donnees) else None


def enregistrer_reglages(c, donnees):
    if not reglages_valides(donnees):
        return False
    ecrire_atomique(c["reglages"], json.dumps(donnees, ensure_ascii=False, indent=2), droits=DROITS_REGLAGES)
    return True


# ── Codes PIN des profils ─────────────────────────────────────────────────
# POURQUOI ICI ET PAS DANS LA PAGE. La page comparait elle-même sha256(sel:code) à
# l'empreinte des réglages, et comptait les échecs en mémoire : relancer le menu
# remettait le compteur à zéro, et un téléphone appairé pouvait taper les 10 000 codes
# par /api/commande. Maintenant la page envoie la saisie, hub-menu vérifie, et tient
# le compte des échecs sur disque, avec un délai qui double.
#
# CE QUE ÇA NE FAIT PAS. Un code à 4 chiffres reste un verrou familial. Quiconque a
# un shell sous le compte du HUB (mode Bureau, terminal) lit reglages.json et essaie
# les 10 000 codes hors ligne : PBKDF2 le ralentit (0,24 s par essai mesurés ci-dessous,
# soit une quarantaine de minutes sur un cœur, moins avec plusieurs ou un GPU), il ne
# l'empêche pas ; il peut aussi effacer le compteur. Le fermer demande que les
# empreintes et le compteur appartiennent à un autre compte que celui du Bureau
# (service système qui vérifie pour le menu) : chantier d'architecture laissé pour
# plus tard.
PIN_ALGO = "pbkdf2-sha256"
# 600 000 : recommandation OWASP 2023 pour PBKDF2-HMAC-SHA256. Mesuré le 17/09/2026
# sur le Mac de développement (python3 -c "hashlib.pbkdf2_hmac(...)") : 0,24 s. La
# machine du HUB n'est pas mesurée ; la vérification tourne hors du fil graphique.
PIN_ITERATIONS = 600_000
PIN_ITERATIONS_MAX = 10_000_000
PIN_ESSAIS_LIBRES = 4
PIN_DELAI_S = 30
# Plafonné : un enfant qui s'acharne ne doit pas priver les parents du HUB une soirée.
PIN_DELAI_MAX_S = 15 * 60
_verrou_pin = threading.Lock()


def code_pin_valide(code):
    return isinstance(code, str) and len(code) == 4 and code.isascii() and code.isdigit()


def hacher_pin(code, sel=None, iterations=None):
    iterations = iterations or PIN_ITERATIONS
    sel = sel if sel is not None else os.urandom(16)
    empreinte = hashlib.pbkdf2_hmac("sha256", code.encode(), sel, iterations)
    return {"algo": PIN_ALGO, "iterations": iterations, "sel": sel.hex(), "empreinte": empreinte.hex()}


def pin_correct(pin, code):
    """Deux formats : PBKDF2 (actuel) et l'ancien sha256("sel:code") calculé par la page."""
    if not isinstance(pin, dict) or not code_pin_valide(code) or not isinstance(pin.get("empreinte"), str):
        return False
    if pin.get("algo") == PIN_ALGO:
        iterations = pin.get("iterations")
        if not isinstance(iterations, int) or isinstance(iterations, bool) or not 0 < iterations <= PIN_ITERATIONS_MAX:
            return False
        try:
            sel = bytes.fromhex(pin.get("sel") or "")
        except (TypeError, ValueError):
            return False
        calcule = hashlib.pbkdf2_hmac("sha256", code.encode(), sel, iterations).hex()
    elif "algo" not in pin and isinstance(pin.get("sel"), str):
        calcule = hashlib.sha256(f"{pin['sel']}:{code}".encode()).hexdigest()
    else:
        return False
    return hmac.compare_digest(calcule, pin["empreinte"].lower())


def pin_a_rehacher(pin):
    return pin.get("algo") != PIN_ALGO or pin.get("iterations", 0) < PIN_ITERATIONS


def _lire_echecs(chemin):
    donnees = lire_json(chemin)
    if not isinstance(donnees, dict):
        return {"echecs": 0, "jusqua": 0}
    echecs, jusqua = donnees.get("echecs"), donnees.get("jusqua")
    return {"echecs": echecs if isinstance(echecs, int) and echecs >= 0 else 0,
            "jusqua": jusqua if isinstance(jusqua, (int, float)) else 0}


def attente_pin(chemin, maintenant=None):
    """Secondes avant le prochain essai permis (0 : on peut essayer)."""
    maintenant = maintenant or time.time()
    # Une horloge revenue en arrière ne doit pas bloquer plus longtemps que le plafond.
    reste = min(_lire_echecs(chemin)["jusqua"] - maintenant, PIN_DELAI_MAX_S)
    return max(0, int(-(-reste // 1)))


def noter_echec_pin(chemin, maintenant=None):
    """Quatre essais libres, puis 30 s, 60 s, 120 s… jusqu'à 15 min après chaque échec.
    Un seul compteur pour tout le HUB : changer de profil ne redonne pas d'essais."""
    maintenant = maintenant or time.time()
    etat = _lire_echecs(chemin)
    etat["echecs"] += 1
    depassement = etat["echecs"] - PIN_ESSAIS_LIBRES
    if depassement > 0:
        etat["jusqua"] = maintenant + min(PIN_DELAI_MAX_S, PIN_DELAI_S * 2 ** min(depassement - 1, 16))
    try:
        ecrire_atomique(chemin, json.dumps(etat), droits=0o600)
    except OSError as erreur:
        print(f"hub-menu : compteur d'échecs du code non enregistré ({erreur})", file=sys.stderr)
    return attente_pin(chemin, maintenant)


def verifier_pin(c, profils, code, maintenant=None):
    """La page demande : ce code ouvre-t-il l'un de ces profils ? (« l'un » : n'importe
    quel parent accorde du temps d'écran). Les empreintes sont relues sur disque, pas
    reçues de la page. Réponse : {"resultat": "ok" | "refus" | "bloque", "attente"}, et
    pour « ok » le profil ouvert et, si l'empreinte a été refaite, la nouvelle."""
    chemin = c["pin-echecs"]
    with _verrou_pin:
        attente = attente_pin(chemin, maintenant)
        if attente:
            return {"resultat": "bloque", "attente": attente}
        ids = [i for i in profils if isinstance(i, str)][:12] if isinstance(profils, list) else []
        reglages = charger_reglages(c) or {"profils": []}
        for p in reglages["profils"]:
            if p.get("id") in ids and pin_correct(p.get("pin"), code):
                try:
                    Path(chemin).unlink(missing_ok=True)
                except OSError:
                    pass
                reponse = {"resultat": "ok", "attente": 0, "profil": p["id"]}
                if pin_a_rehacher(p["pin"]):
                    # Migration transparente : l'ancien sha256 se retrouve en un instant ;
                    # on profite du code en clair, juste vérifié, pour le refaire en PBKDF2.
                    p["pin"] = hacher_pin(code)
                    try:
                        enregistrer_reglages(c, reglages)
                        reponse["pin"] = p["pin"]
                    except OSError:
                        pass
                return reponse
        return {"resultat": "refus", "attente": noter_echec_pin(chemin, maintenant)}


def creer_pin(code):
    if not code_pin_valide(code):
        return {"resultat": "refus"}
    return {"resultat": "hache", "pin": hacher_pin(code)}


def dernier_choix(c):
    try:
        choix = Path(c["dernier"]).read_text().strip()
    except OSError:
        return None
    return choix if choix in MODES else None


def retenir(c, choix):
    # « web » n'a pas de carte à resélectionner au retour : le menu reprend la dernière.
    if choix in MODES and choix not in ("eteindre", "web"):
        try:
            ecrire_atomique(c["dernier"], choix + "\n")
        except OSError:
            pass


def dossiers_images(sous_dossier):
    candidats = [Path.home() / "Images" / sous_dossier, Path.home() / "Pictures" / sous_dossier]
    try:
        images = subprocess.run(["xdg-user-dir", "PICTURES"], capture_output=True, text=True, timeout=2).stdout.strip()
        if images:
            candidats.insert(0, Path(images) / sous_dossier)
    except (OSError, subprocess.SubprocessError):
        pass
    vus, dossiers = set(), []
    for d in candidats:
        if d.is_dir() and d.resolve() not in vus:
            vus.add(d.resolve())
            dossiers.append(d)
    return dossiers


def images_de(dossiers, limite=200, recentes_d_abord=False):
    fichiers = [
        f for d in dossiers for f in d.iterdir()
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} and f.is_file()
    ]
    if recentes_d_abord:
        fichiers.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    else:
        fichiers.sort()
    return [f.resolve().as_uri() for f in fichiers[:limite]]


def photos(dossiers=None):
    """Les images de Images/HUB (ou Pictures/HUB) deviennent un fond possible."""
    return images_de(dossiers if dossiers is not None else dossiers_images("HUB"))


def avatars(dossiers=None):
    """Les photos de profil possibles : Images/HUB/profils, la plus récente d'abord,
    pour qu'une photo envoyée depuis le téléphone soit en tête de liste."""
    return images_de(dossiers if dossiers is not None else dossiers_images(str(Path("HUB") / "profils")), limite=40, recentes_d_abord=True)


# ── Cadre photo du mode ambiant ───────────────────────────────────────────
EXTENSIONS_PHOTO = {".jpg", ".jpeg", ".png", ".webp"}
# Les photos de profil vivent dans Images/HUB/profils : ce ne sont pas des souvenirs.
DOSSIERS_HORS_CADRE = {"profils"}


def albums_cadre(dossiers=None):
    """Les sous-dossiers d'Images/HUB qui contiennent au moins une photo : un album = un dossier."""
    noms = set()
    for d in dossiers if dossiers is not None else dossiers_images("HUB"):
        try:
            for sous in d.iterdir():
                if sous.is_dir() and not sous.name.startswith(".") and sous.name not in DOSSIERS_HORS_CADRE \
                        and any(f.suffix.lower() in EXTENSIONS_PHOTO for f in sous.rglob("*")):
                    noms.add(sous.name)
        except OSError:
            continue
    return sorted(noms, key=str.casefold)


def photos_cadre(dossiers=None, album=None, limite=500):
    """Toutes les photos (sous-dossiers compris), ou celles d'un album. Le nom d'album
    vient de la page : un nom de dossier seulement, jamais un chemin."""
    if album and (album != Path(album).name or album.startswith(".") or album in DOSSIERS_HORS_CADRE):
        return []
    fichiers = []
    for d in dossiers if dossiers is not None else dossiers_images("HUB"):
        racine = d / album if album else d
        if not racine.is_dir():
            continue
        for chemin, sous_dossiers, noms in os.walk(racine):
            profondeur_racine = Path(chemin) == racine
            sous_dossiers[:] = sorted(s for s in sous_dossiers if not s.startswith(".")
                                      and not (profondeur_racine and not album and s in DOSSIERS_HORS_CADRE))
            fichiers += [Path(chemin) / n for n in sorted(noms) if Path(n).suffix.lower() in EXTENSIONS_PHOTO]
            if len(fichiers) >= limite:
                return fichiers[:limite]
    return fichiers


def date_exif(chemin, lecture_max=256_000):
    """Date de prise de vue d'un JPEG, lue dans son bloc EXIF sans bibliothèque.

    Pillow est bien dans le manifeste d'Ubuntu 26.04.1 Desktop (python3-pil 12.1.1,
    relevé le 15/09/2026), mais une installation minimale ou un retrait l'ôterait sans
    bruit, et on n'a besoin que d'une chaîne de 19 caractères. On lit donc le TIFF
    embarqué : DateTimeOriginal (0x9003) du sous-IFD Exif, sinon DateTime (0x0132).
    Tout ce qui ne ressemble pas à ce qu'on attend rend None, jamais une exception."""
    import struct
    try:
        with open(chemin, "rb") as f:
            donnees = f.read(lecture_max)
    except OSError:
        return None
    if donnees[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 4 <= len(donnees):
        if donnees[i] != 0xFF:
            return None
        marqueur = donnees[i + 1]
        if marqueur in (0xDA, 0xD9):
            return None
        longueur = struct.unpack(">H", donnees[i + 2:i + 4])[0]
        segment = donnees[i + 4:i + 2 + longueur]
        if marqueur == 0xE1 and segment[:6] == b"Exif\x00\x00":
            return _date_tiff(segment[6:])
        i += 2 + longueur
    return None


def _date_tiff(tiff):
    import struct
    if tiff[:4] == b"II*\x00":
        o = "<"
    elif tiff[:4] == b"MM\x00*":
        o = ">"
    else:
        return None

    def entrees(offset):
        if offset < 8 or offset + 2 > len(tiff):
            return {}
        n = struct.unpack(o + "H", tiff[offset:offset + 2])[0]
        resultat = {}
        for k in range(min(n, 512)):
            debut = offset + 2 + 12 * k
            if debut + 12 > len(tiff):
                break
            resultat[struct.unpack(o + "H", tiff[debut:debut + 2])[0]] = tiff[debut + 2:debut + 12]
        return resultat

    def texte(brut):
        genre, compte, valeur = struct.unpack(o + "HII", brut)
        if genre != 2 or compte < 19:
            return None
        octets = brut[6:6 + compte] if compte <= 4 else tiff[valeur:valeur + compte]
        try:
            return datetime.strptime(octets[:19].decode("ascii"), "%Y:%m:%d %H:%M:%S")
        except (UnicodeDecodeError, ValueError):
            return None

    ifd0 = entrees(struct.unpack(o + "I", tiff[4:8])[0])
    if 0x8769 in ifd0:
        exif = entrees(struct.unpack(o + "I", ifd0[0x8769][6:10])[0])
        if 0x9003 in exif:
            date = texte(exif[0x9003])
            if date:
                return date
    return texte(ifd0[0x0132]) if 0x0132 in ifd0 else None


def souvenirs(fichiers, aujourdhui, cache_chemin):
    """Les photos prises le même jour et le même mois, les années précédentes, la plus
    récente d'abord. Les dates lues sont gardées (chemin, date de modification, taille) :
    le menu revient de Kodi dix fois par soir, il ne relit pas 500 en-têtes à chaque fois."""
    cache = lire_json(cache_chemin)
    cache = cache if isinstance(cache, dict) else {}
    nouveau, trouves = {}, []
    for f in fichiers:
        try:
            infos = f.stat()
        except OSError:
            continue
        cle = str(f)
        empreinte = [int(infos.st_mtime), infos.st_size]
        connu = cache.get(cle)
        if isinstance(connu, list) and connu[:2] == empreinte:
            texte = connu[2]
        else:
            d = date_exif(f) if f.suffix.lower() in {".jpg", ".jpeg"} else None
            texte = d.strftime("%Y-%m-%d") if d else None
        nouveau[cle] = empreinte + [texte]
        if texte:
            annee, mois, jour = (int(x) for x in texte.split("-"))
            if (mois, jour) == (aujourdhui.month, aujourdhui.day) and annee < aujourdhui.year:
                trouves.append({"uri": f.resolve().as_uri(), "annee": annee})
    if nouveau != cache:
        try:
            ecrire_atomique(cache_chemin, json.dumps(nouveau))
        except OSError:
            pass
    trouves.sort(key=lambda s: s["annee"], reverse=True)
    return trouves


def cadre(album=None, avec_souvenirs=False, dossiers=None, cache_chemin=None, aujourdhui=None):
    """Ce que la page demande pour son diaporama."""
    dossiers = dossiers if dossiers is not None else dossiers_images("HUB")
    fichiers = photos_cadre(dossiers, album or None)
    reponse = {"type": "cadre", "albums": albums_cadre(dossiers), "album": album or None,
               "photos": [f.resolve().as_uri() for f in fichiers], "souvenirs": []}
    if avec_souvenirs:
        tout = fichiers if not album else photos_cadre(dossiers)
        cache = cache_chemin or dossier("XDG_CACHE_HOME", Path.home() / ".cache") / "hub" / "exif.json"
        reponse["souvenirs"] = souvenirs(tout, aujourdhui or datetime.now().date(), cache)
    return reponse


# ── Kodi : reprendre la lecture ───────────────────────────────────────────
def base_kodi(dossier, prefixe):
    """La base la plus récente : Kodi crée MyVideos131.db, puis MyVideos137.db à la
    version suivante, sans effacer l'ancienne."""
    def version(f):
        chiffres = "".join(ch for ch in f.stem if ch.isdigit())
        return int(chiffres or 0)
    bases = sorted(Path(dossier).glob(f"{prefixe}*.db"), key=version)
    return bases[-1] if bases else None


def reprises_kodi(dossier_kodi, limite=6):
    """Films et épisodes commencés dans Kodi, du plus récent au plus ancien.

    Lu directement dans la base de Kodi, en lecture seule : Kodi ne tourne pas quand
    le menu est affiché, et on ne veut ni activer son serveur web ni le lancer pour
    savoir où on en était. Toute surprise de schéma donne une liste vide, jamais une
    erreur à l'écran."""
    import sqlite3

    donnees = Path(dossier_kodi) / "userdata"
    base = base_kodi(donnees / "Database", "MyVideos")
    if not base:
        return []
    miniatures = {}
    textures = base_kodi(donnees / "Database", "Textures")
    requetes = {
        "film": "SELECT idMovie, c00, NULL, NULL, NULL, strPath, strFileName, resumeTimeInSeconds, totalTimeInSeconds, lastPlayed "
                "FROM movie_view WHERE resumeTimeInSeconds > 0",
        "episode": "SELECT idEpisode, c00, strTitle, c12, c13, strPath, strFileName, resumeTimeInSeconds, totalTimeInSeconds, lastPlayed "
                   "FROM episode_view WHERE resumeTimeInSeconds > 0",
    }
    elements = []
    try:
        with sqlite3.connect(f"{base.as_uri()}?mode=ro", uri=True) as bd:
            for genre, requete in requetes.items():
                for ident, titre, serie, saison, episode, chemin, fichier, position, duree, vu in bd.execute(requete):
                    if not fichier or not duree:
                        continue
                    art = bd.execute(
                        "SELECT url FROM art WHERE media_id = ? AND media_type = ? AND type IN ('poster', 'thumb') "
                        "ORDER BY type = 'poster' DESC LIMIT 1", (ident, "movie" if genre == "film" else "episode")).fetchone()
                    elements.append({
                        "genre": genre,
                        "titre": serie or titre,
                        "sousTitre": f"S{int(saison):02d} E{int(episode):02d} · {titre}" if genre == "episode" and str(saison).isdigit() and str(episode).isdigit() else None,
                        # Kodi range les URL (smb://, nfs://, chemins locaux) déjà complètes.
                        "fichier": fichier if "://" in fichier or fichier.startswith("/") else (chemin or "") + fichier,
                        "position": float(position),
                        "duree": float(duree),
                        "vuLe": vu or "",
                        "art": art[0] if art else None,
                    })
    except sqlite3.Error:
        return []
    elements.sort(key=lambda e: e["vuLe"], reverse=True)
    elements = elements[:limite]

    if textures and any(e["art"] for e in elements):
        try:
            with sqlite3.connect(f"{textures.as_uri()}?mode=ro", uri=True) as bd:
                for e in elements:
                    if e["art"]:
                        ligne = bd.execute("SELECT cachedurl FROM texture WHERE url = ?", (e["art"],)).fetchone()
                        if ligne:
                            miniatures[e["art"]] = (donnees / "Thumbnails" / ligne[0])
        except sqlite3.Error:
            pass
    for e in elements:
        image = miniatures.get(e.pop("art"))
        e["image"] = image.as_uri() if image and image.is_file() else None
    return elements


# ── Services web ──────────────────────────────────────────────────────────
def services_disponibles(chemin=None):
    """Ce que hub-web saura lancer (navigateur présent, Steam ou Moonlight installés).

    hub-web est importé plutôt qu'exécuté : un processus Python de plus à chaque retour
    au menu se sentirait. Absent ou cassé, le menu montre les tuiles quand même et
    hub-web dira son erreur ; un lanceur manquant ne doit pas faire tomber le menu."""
    import importlib.machinery
    import importlib.util
    chemin = Path(chemin or Path(__file__).resolve().parent / "hub-web")
    try:
        chargeur = importlib.machinery.SourceFileLoader("hub_web", str(chemin))
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader("hub_web", chargeur))
        chargeur.exec_module(module)
        return module.disponibles()
    except Exception as erreur:  # noqa: BLE001 — n'importe quelle panne du lanceur
        print(f"hub-menu : services web inconnus ({erreur})", file=sys.stderr)
        return None


def service_choisi(message):
    service = message.get("service")
    return service if isinstance(service, str) and service in SERVICES_WEB else None


# ── Météo ─────────────────────────────────────────────────────────────────
def telecharger_json(url, delai=8):
    requete = urllib.request.Request(url, headers={"User-Agent": "HUB-menu"})
    with urllib.request.urlopen(requete, timeout=delai) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def meteo(c, lat, lon, maintenant=None, telecharger=telecharger_json):
    """Relevé frais si possible, sinon le dernier en cache marqué « hors ligne ».

    Le cache évite d'interroger Open-Meteo à chaque retour au menu (on revient de
    Kodi dix fois par soirée) et donne encore quelque chose à afficher sans réseau."""
    maintenant = maintenant or time.time()
    cache = lire_json(c["meteo"])
    meme_lieu = cache and abs(cache.get("lat", 999) - lat) < .01 and abs(cache.get("lon", 999) - lon) < .01
    if meme_lieu and maintenant - cache.get("releve", 0) < METEO_FRAICHE_S:
        return {"donnees": cache["donnees"], "releve": cache["releve"], "horsLigne": False}
    try:
        donnees = telecharger(f"{URL_METEO}&latitude={lat}&longitude={lon}")
        if not isinstance(donnees, dict) or "current" not in donnees:
            raise ValueError("réponse météo inattendue")
        ecrire_atomique(c["meteo"], json.dumps({"lat": lat, "lon": lon, "releve": maintenant, "donnees": donnees}))
        return {"donnees": donnees, "releve": maintenant, "horsLigne": False}
    except (OSError, ValueError):
        if meme_lieu:
            return {"donnees": cache["donnees"], "releve": cache["releve"], "horsLigne": True}
        return None


def geocodage(nom, langue, telecharger=telecharger_json):
    requete = urllib.parse.urlencode({"name": nom[:60], "count": 6, "language": langue if langue in ("fr", "en") else "fr"})
    try:
        resultats = telecharger(f"{URL_GEOCODAGE}?{requete}").get("results") or []
    except (OSError, ValueError, AttributeError):
        return []
    garder = ("id", "name", "latitude", "longitude", "admin1", "country_code")
    return [{k: r.get(k) for k in garder} for r in resultats if "latitude" in r and "longitude" in r]


# ── Minuteur de mise en veille ────────────────────────────────────────────
def commande_minuteur(minutes):
    """Un minuteur systemd de l'utilisateur, et non un délai dans ce menu : le menu se
    ferme dès qu'on lance Kodi, alors que l'extinction doit survenir pendant le film."""
    if minutes <= 0:
        return None
    return [
        "systemd-run", "--user", f"--unit={UNITE_MINUTEUR}", f"--on-active={minutes}m",
        "--timer-property=AccuracySec=5s", "--description=HUB : minuteur de mise en veille",
        "/bin/sh", "-c", "systemctl poweroff || gnome-session-quit --power-off --no-prompt",
    ]


def programmer_minuteur(c, minutes, executer=subprocess.run, maintenant=None):
    executer(["systemctl", "--user", "stop", f"{UNITE_MINUTEUR}.timer"], capture_output=True)
    commande = commande_minuteur(minutes)
    if not commande:
        Path(c["minuteur"]).unlink(missing_ok=True)
        return None
    resultat = executer(commande, capture_output=True)
    if getattr(resultat, "returncode", 1) != 0:
        return None
    fin = int(((maintenant or time.time()) + minutes * 60) * 1000)
    ecrire_atomique(c["minuteur"], str(fin))
    return fin


def minuteur_en_cours(c, maintenant=None):
    try:
        fin = int(Path(c["minuteur"]).read_text().strip())
    except (OSError, ValueError):
        return None
    return fin if fin > (maintenant or time.time()) * 1000 else None


# ── Infos machine ─────────────────────────────────────────────────────────
def duree_lisible(secondes):
    minutes = int(secondes // 60)
    jours, minutes = divmod(minutes, 24 * 60)
    heures, minutes = divmod(minutes, 60)
    if jours:
        return f"{jours} j {heures} h"
    if heures:
        return f"{heures} h {minutes:02d}"
    return f"{minutes} min"


def adresse_ip():
    # Connecter un socket UDP n'envoie rien : cela demande seulement au noyau quelle
    # interface il utiliserait, donc l'adresse du HUB sur le réseau local.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def infos():
    systeme = None
    try:
        for ligne in Path("/etc/os-release").read_text().splitlines():
            if ligne.startswith("PRETTY_NAME="):
                systeme = ligne.split("=", 1)[1].strip('"')
    except OSError:
        pass
    try:
        allume = duree_lisible(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        allume = None
    libre = shutil.disk_usage("/").free
    version = None
    for chemin in ("/usr/local/share/hub/VERSION", Path(__file__).resolve().parent.parent / "VERSION"):
        try:
            version = Path(chemin).read_text().strip()
            break
        except OSError:
            continue
    return {
        "machine": socket.gethostname(),
        "systeme": systeme,
        "adresse": adresse_ip(),
        "allumeDepuis": allume,
        "disqueLibre": f"{libre / 1e9:.0f} Go",
        "version": version or "dev",
    }


# ── Télécommande ──────────────────────────────────────────────────────────
# Les champs de telecommande.json que l'écran d'appairage affiche, chacun avec ce qu'il
# doit être ; une valeur qui ne l'est pas arrive à la page comme None. Un champ de plus
# au contrat de hub-telecommande = une ligne ici et une dans LIGNES_APPAIRAGE (hub.js).
CHAMPS_TELECOMMANDE = {
    "url": lambda v: isinstance(v, str),
    "code": lambda v: isinstance(v, str),
    "expire": lambda v: True,
    "telephones": lambda v: True,
    "appairageLe": lambda v: True,
    "https": lambda v: isinstance(v, str),
    # Le code n'est utilisable que fenêtre ouverte (voir ouvrir_appairage) ; sinon la
    # TV dit « ouverture… » plutôt qu'un code que le service refuserait.
    "appairageOuvert": lambda v: isinstance(v, bool),
    "appairageJusque": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    # SHA-256 du certificat racine : le téléphone demande de la comparer avec la TV avant
    # d'installer le certificat. Le début, « 3A9F 12C0 4481 7BE2 », est ce qu'on lit ;
    # l'empreinte entière, en paires « AB:CD:… », est donnée en petit.
    "empreinteRacineCourte": lambda v: isinstance(v, str) and re.fullmatch(r"[0-9A-F]{4}( [0-9A-F]{4}){3}", v) is not None,
    "empreinteRacine": lambda v: isinstance(v, str) and re.fullmatch(r"[0-9A-F]{2}(:[0-9A-F]{2}){31}", v) is not None,
}


def etat_telecommande(c):
    """Ce que hub-telecommande publie pour l'écran d'appairage ; None s'il ne tourne pas
    (il supprime son fichier en s'arrêtant)."""
    donnees = lire_json(c["telecommande"])
    if not isinstance(donnees, dict) or not isinstance(donnees.get("url"), str) or not isinstance(donnees.get("code"), str):
        return None
    return {k: donnees.get(k) if valide(donnees.get(k)) else None for k, valide in CHAMPS_TELECOMMANDE.items()}


# La fenêtre d'appairage : hub-telecommande n'accepte un nouveau téléphone que pendant
# que l'écran d'appairage est affiché sur la TV, c'est-à-dire tant que ce fichier a été
# touché il y a moins de 5 minutes. Le menu le touche à l'ouverture de l'écran, toutes
# les 30 s tant qu'il reste affiché, et l'efface en le quittant ; si le menu tombe, la
# fenêtre se ferme seule au bout des 5 minutes.
RETOUCHE_APPAIRAGE_S = 30


def ouvrir_appairage(c):
    chemin = Path(c["telecommande-appairage"])
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        # Le service ignore un lien symbolique : on le remplace par un vrai fichier
        # plutôt que de toucher ce qu'il désigne.
        if chemin.is_symlink():
            chemin.unlink()
        descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(descripteur, 0o600)
            os.utime(descripteur if os.utime in os.supports_fd else chemin)
        finally:
            os.close(descripteur)
    except OSError as erreur:
        print(f"hub-menu : fenêtre d'appairage non ouverte ({erreur})", file=sys.stderr)
        return False
    return True


def fermer_appairage(c):
    try:
        Path(c["telecommande-appairage"]).unlink(missing_ok=True)
    except OSError:
        pass


def suivre_appairage(c, affiche, touche_le, maintenant=None):
    """Appelé à chaque tour de surveillance : rend la date du dernier toucher (None :
    fenêtre fermée)."""
    maintenant = maintenant or time.time()
    if not affiche:
        if touche_le is not None:
            fermer_appairage(c)
        return None
    if touche_le is None or maintenant - touche_le >= RETOUCHE_APPAIRAGE_S or maintenant < touche_le:
        return maintenant if ouvrir_appairage(c) else None
    return touche_le


# ── Enceinte réseau : ce qui joue ─────────────────────────────────────────
SOURCES_LECTURE = ("spotify", "airplay", "ecran")


def etat_lecture(c):
    """Ce que hub-enceinte publie quand Spotify, AirPlay ou une recopie d'écran joue ;
    None sinon (il supprime le fichier). Le fichier est relu à chaque seconde : on ne
    transmet à la page que des champs connus, bornés, et une pochette qui vient du
    dossier d'exécution — jamais une adresse arbitraire qu'une page locale chargerait."""
    donnees = lire_json(c.get("lecture") or Path(c["execution"]) / "lecture.json")
    if not isinstance(donnees, dict) or donnees.get("source") not in SOURCES_LECTURE \
            or donnees.get("etat") not in ("lecture", "pause"):
        return None
    etat = {"source": donnees["source"], "etat": donnees["etat"], "ecran": donnees.get("ecran") is True}
    for champ in ("titre", "artiste", "album", "appareil"):
        valeur = donnees.get(champ)
        etat[champ] = valeur[:200] if isinstance(valeur, str) and valeur.strip() else None
    pochette, etat["pochette"] = donnees.get("pochette"), None
    dossier_pochettes = (Path(c["execution"]) / "pochettes").resolve()
    if isinstance(pochette, str) and pochette.startswith("file://"):
        fichier = Path(urllib.parse.unquote(pochette[7:]))
        if fichier.resolve().parent == dossier_pochettes and fichier.is_file():
            etat["pochette"] = fichier.resolve().as_uri()
    return etat


# ── Recopie d'écran : le code à saisir sur l'iPhone ou le Mac ─────────────
# hub-enceinte protège la recopie (UxPlay) par un code à 4 chiffres. Le menu ne connaît
# ni son fichier ni ses options : il demande à hub-enceinte, avec des arguments fixés
# ici, et ne transmet à la page qu'une valeur qui a la forme d'un code.
CODE_RECOPIE = re.compile(r"[0-9]{4}")


def code_recopie(nouveau=False, executer=subprocess.run):
    """Le code actuel (hub-enceinte le crée au besoin), ou un nouveau : tous les
    appareils devront le ressaisir. None si hub-enceinte ne répond pas un code."""
    commande = ["hub-enceinte", "code"] + (["nouveau"] if nouveau else [])
    try:
        r = executer(commande, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    sortie = (r.stdout or "").strip() if getattr(r, "returncode", 1) == 0 else ""
    return sortie if CODE_RECOPIE.fullmatch(sortie) else None


def recopie_permise(executer=subprocess.run):
    """hub-enceinte actif ecran : 0 permise, 1 coupée (réglage, ou temps d'écran du
    profil) ; None si on n'a pas pu le demander."""
    try:
        r = executer(["hub-enceinte", "actif", "ecran"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(getattr(r, "returncode", None))


def etat_code_recopie(c, maintenant=None):
    """Pendant qu'un appareil demande à recopier, hub-enceinte publie le code à afficher
    sur la TV ; relu chaque seconde, comme lecture.json. None hors appairage."""
    donnees = lire_json(c.get("recopie-code") or Path(c["execution"]) / "recopie-code.json")
    if not isinstance(donnees, dict):
        return None
    code, jusqua = donnees.get("code"), donnees.get("jusqua")
    if not isinstance(code, str) or not CODE_RECOPIE.fullmatch(code) \
            or not isinstance(jusqua, (int, float)) or isinstance(jusqua, bool):
        return None
    return {"code": code, "jusqua": jusqua} if jusqua > (maintenant or time.time()) else None


def reglage_enceinte(donnees):
    enceinte = ((donnees or {}).get("systeme") or {}).get("enceinte") if isinstance(donnees, dict) else None
    return enceinte if isinstance(enceinte, dict) else {}


def appliquer_enceinte(avant, donnees, executer=subprocess.Popen):
    """Réglages → Enceinte réseau : seul hub-enceinte sait quelle unité relancer. On ne le
    réveille que si ce réglage a changé, pas à chaque changement de thème ou de profil."""
    apres = reglage_enceinte(donnees)
    if apres == reglage_enceinte(avant):
        return False
    try:
        executer(["hub-enceinte", "appliquer"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    return True


# ── Habillage d'Ubuntu et de Kodi ─────────────────────────────────────────
def marqueur_habillage():
    return dossier("XDG_CONFIG_HOME", Path.home() / ".config") / "hub" / "habillage-desactive"


def appliquer_habillage(donnees, executer=subprocess.Popen, marqueur=None):
    """Suit le réglage « Ubuntu et Kodi aux couleurs du HUB ».

    Activé : on régénère en arrière-plan les fonds du profil (hub-theme apercu), pour
    que le bureau et Kodi s'ouvrent déjà habillés. Désactivé : on remet l'apparence
    d'origine une fois, et le marqueur dit aux scripts de session de ne plus habiller."""
    marqueur = Path(marqueur or marqueur_habillage())
    actif = (donnees.get("systeme") or {}).get("habillage", True) is not False
    etait_actif = not marqueur.exists()
    try:
        if actif:
            marqueur.unlink(missing_ok=True)
            executer(["hub-theme", "apercu"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        else:
            if etait_actif:
                ecrire_atomique(marqueur, "1\n")
                executer(["hub-theme", "restaurer"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    return True


# ── Mise à jour ───────────────────────────────────────────────────────────
ETAT_MISE_A_JOUR = Path("/run/hub-mise-a-jour/etat.json")


def verifier_mise_a_jour(executer=subprocess.run):
    """Demande à hub-mise-a-jour s'il existe une version plus récente (sans rien installer)."""
    try:
        r = executer(["hub-mise-a-jour", "verifier"], capture_output=True, text=True, timeout=90)
        reponse = json.loads(r.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError) as erreur:
        return {"erreur": "indisponible", "detail": str(erreur)[:200]}
    return reponse if isinstance(reponse, dict) else {"erreur": "indisponible"}


def lancer_mise_a_jour(executer=subprocess.run):
    # Le service tourne en root ; une règle polkit autorise l'utilisateur du HUB à le
    # démarrer, lui et rien d'autre. --no-block : le menu suit la progression lui-même.
    r = executer(["systemctl", "start", "--no-block", "hub-mise-a-jour.service"], capture_output=True, text=True)
    return r.returncode == 0


def etat_mise_a_jour(chemin=ETAT_MISE_A_JOUR):
    donnees = lire_json(chemin)
    return donnees if isinstance(donnees, dict) and isinstance(donnees.get("etape"), str) else None


# ── Temps d'écran et allumage ─────────────────────────────────────────────
def programme_voisin(nom):
    """hub-temps-ecran et hub-allumage sont des programmes à part (l'un tourne autour des
    modes, l'autre en root) ; le menu réutilise leur logique au lieu de la recopier.
    Installés à côté de hub-menu dans /usr/local/bin ; dans le dépôt, à côté aussi ou
    dans leur dossier."""
    import importlib.machinery
    import importlib.util
    ici = Path(__file__).resolve().parent
    for chemin in (ici / nom, ici / "allumage" / nom):
        if chemin.is_file():
            chargeur = importlib.machinery.SourceFileLoader(nom.replace("-", "_"), str(chemin))
            module = importlib.util.module_from_spec(importlib.util.spec_from_loader(chargeur.name, chargeur))
            try:
                chargeur.exec_module(module)
            except (OSError, SyntaxError):
                return None
            return module
    return None


def temps_ecran(maintenant=None):
    te = programme_voisin("hub-temps-ecran")
    if not te:
        return None
    return te.resume(te.lire_etat(te.chemins()["etat"]), maintenant or time.time())


def prolonger_temps(profil, minutes, maintenant=None):
    """Accordé après un code parent vérifié par verifier_pin (verrou familial, comme les
    profils) ; ici on borne seulement ce qui peut s'écrire."""
    if not isinstance(profil, str) or not 0 < len(profil) <= 64 or minutes not in (15, 30, 60) or isinstance(minutes, bool):
        return None
    te = programme_voisin("hub-temps-ecran")
    if not te:
        return None
    maintenant = maintenant or time.time()
    chemin = te.chemins()["etat"]
    te.modifier_etat(chemin, lambda e: te.prolonger(e, profil, minutes, maintenant), maintenant)
    return te.resume(te.lire_etat(chemin), maintenant)


ETAT_ALLUMAGE = Path("/var/lib/hub/allumage.json")
SIGNAL_REVEIL = Path("/run/hub-allumage/reveil")


def reveil_programme(signal=SIGNAL_REVEIL, deja_ouvert=False):
    """Allumé par le réveil programmé : le premier menu ouvre le mode ambiant."""
    return not deja_ouvert and Path(signal).is_file()


def etat_allumage(chemin=ETAT_ALLUMAGE):
    al = programme_voisin("hub-allumage")
    etat = lire_json(chemin)
    etat = etat if isinstance(etat, dict) else {}
    return {
        "reveil": etat.get("reveil"),
        "extinction": etat.get("extinction"),
        "erreur": etat.get("erreur"),
        "ethernet": al.cartes_ethernet() if al else [],
    }


def appliquer_allumage(executer=subprocess.run):
    # Même modèle que la mise à jour : service root, démarrable par le groupe hub seul.
    try:
        r = executer(["systemctl", "start", "--no-block", "hub-allumage.service"], capture_output=True, text=True)
    except OSError:
        return False
    return r.returncode == 0


# ── Messages ──────────────────────────────────────────────────────────────
def message_voix(datagramme):
    """Traduit un datagramme de hub-voix en message pour la page, ou None."""
    try:
        texte = datagramme.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    if texte == "avatars":
        return {"type": "avatars"}
    if texte.startswith("texte:"):
        return {"type": "texte", "texte": texte[6:200]}
    if texte.startswith("voix:"):
        etat, _, reste = texte[5:].partition(":")
        if etat == "entendu":
            return {"type": "voix", "etat": "entendu", "texte": reste[:120]}
        return {"type": "voix", "etat": etat} if etat in ETATS_VOIX else None
    return {"type": "commande", "nom": texte} if texte in COMMANDES else None


def lire_message_page(brut):
    """La page envoie du JSON ; les premières versions envoyaient le mode seul."""
    if brut in MODES:
        return {"type": "choix", "mode": brut}
    try:
        message = json.loads(brut)
    except ValueError:
        return None
    return message if isinstance(message, dict) and isinstance(message.get("type"), str) else None


def page_du_menu():
    for chemin in (
        os.environ.get("HUB_MENU_PAGE"),
        Path(__file__).resolve().parent / "menu" / "index.html",
        "/usr/local/share/hub/menu/index.html",
    ):
        if chemin and Path(chemin).is_file():
            return Path(chemin)
    return None


# ── Mode ambiant seul, sur le bureau Ubuntu ───────────────────────────────
# Sur le bureau, le menu est fermé : hub-veille-bureau (installer/veille) lance
# « hub-menu --ambiant » après l'inactivité réglée. Cette fenêtre ne doit rien pouvoir
# faire d'autre qu'afficher : ni choisir un mode (la session Bureau n'a pas de boucle
# gnome-kiosk-script pour le lancer, et « bureau » fermerait la session en cours), ni
# écrire les réglages, ni ouvrir l'appairage. D'où une liste de ce qu'elle accepte,
# plutôt qu'une liste de ce qu'elle refuse : un message ajouté plus tard au menu reste
# fermé ici tant qu'on ne l'a pas voulu.
MESSAGES_AMBIANT = frozenset({"meteo", "cadre", "ambiant-fin"})
# La fenêtre qui apparaît sous le pointeur reçoit du compositeur une entrée et parfois
# un petit mouvement : ce n'est pas quelqu'un qui revient. On laisse passer ces
# premiers instants et les frôlements ; une touche, un clic, la molette réveillent tout de suite.
REVEIL_GRACE_S = 1.5
REVEIL_MOUVEMENT_PX = 24


def analyser_arguments(arguments):
    """Sans argument : le menu. « --ambiant » seul : le mode ambiant. Autre chose : None."""
    arguments = list(arguments)
    if not arguments:
        return {"ambiant": False}
    if arguments == ["--ambiant"]:
        return {"ambiant": True}
    return None


def message_permis(genre, ambiant):
    if ambiant:
        return genre in MESSAGES_AMBIANT
    return genre != "ambiant-fin"


def reveil_ambiant(genre, depuis_s, deplacement_px=0):
    """genre : « touche », « clic », « molette », « toucher », « mouvement » ou autre."""
    if genre in ("touche", "clic", "molette", "toucher"):
        return True
    if genre == "mouvement":
        return depuis_s >= REVEIL_GRACE_S and deplacement_px >= REVEIL_MOUVEMENT_PX
    return False


# ── Interface ─────────────────────────────────────────────────────────────
def lancer(arguments=None):
    options = analyser_arguments(sys.argv[1:] if arguments is None else arguments)
    if options is None:
        print("usage : hub-menu [--ambiant]", file=sys.stderr)
        return 2
    ambiant = options["ambiant"]

    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, GLib, Gtk

    try:
        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit
    except (ValueError, ImportError):
        WebKit = None

    c = chemins()

    class Menu(Gtk.Application):
        def __init__(self):
            # Un identifiant à part pour l'ambiant : GTK n'en laisse tourner qu'une
            # instance par session, une seconde se contente d'activer la première.
            super().__init__(application_id="fr.boudine.HubMenu.Ambiant" if ambiant else "fr.boudine.HubMenu")
            self.ambiant = ambiant
            self.choix = None
            self.fichier = None
            self.etat_maj = None
            self.suivi_maj = False
            self.vue = None
            self.ecoute = None

        def do_activate(self):
            if getattr(self, "fenetre", None):
                self.fenetre.present()
                return
            page = page_du_menu()
            if self.ambiant and not (WebKit and page):
                # Le repli GTK n'a que des boutons de modes : rien à montrer ici.
                print("hub-menu : pas de page WebKit, pas de mode ambiant", file=sys.stderr)
                self.quit()
                return
            fenetre = Gtk.ApplicationWindow(application=self, title="HUB")
            self.fenetre = fenetre
            if self.ambiant:
                self.capter_reveil(fenetre)
            fenetre.set_child(self.vue_web(page) if WebKit and page else self.vue_simple())
            fenetre.fullscreen()
            fenetre.present()

        def do_shutdown(self):
            # Le menu se ferme (un mode démarre) : plus d'écran d'appairage à la TV.
            fermer_appairage(c)
            if self.ecoute:
                self.ecoute.close()
                Path(c["socket"]).unlink(missing_ok=True)
            Gtk.Application.do_shutdown(self)

        def capter_reveil(self, fenetre):
            """Clavier, souris et toucher arrêtés avant WebKit (phase de capture) : la
            touche qui réveille ferme la fenêtre et n'arrive à personne."""
            fenetre.set_cursor_from_name("none")
            ouverture, depart = time.monotonic(), []
            genres = {
                Gdk.EventType.KEY_PRESS: "touche", Gdk.EventType.BUTTON_PRESS: "clic",
                Gdk.EventType.SCROLL: "molette", Gdk.EventType.TOUCH_BEGIN: "toucher",
                Gdk.EventType.MOTION_NOTIFY: "mouvement",
            }

            def evenement(_controleur, ev):
                genre = genres.get(ev.get_event_type())
                deplacement = 0
                if genre == "mouvement":
                    trouve, x, y = ev.get_position()
                    if trouve:
                        depart[:] = depart or [x, y]
                        deplacement = ((x - depart[0]) ** 2 + (y - depart[1]) ** 2) ** .5
                if reveil_ambiant(genre, time.monotonic() - ouverture, deplacement):
                    self.quit()
                return True

            capteur = Gtk.EventControllerLegacy()
            capteur.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            capteur.connect("event", evenement)
            fenetre.add_controller(capteur)

        # La page ──────────────────────────────────────────────────────────
        def vue_web(self, page):
            contenus = WebKit.UserContentManager()
            contenus.register_script_message_handler("hub", None)
            contenus.connect("script-message-received::hub", self.message_recu)

            deja_ouvert = Path(c["deja-ouvert"]).exists()
            initial = {
                "reglages": charger_reglages(c),
                "dernier": dernier_choix(c),
                "photos": photos(),
                "avatars": avatars(),
                "telecommande": etat_telecommande(c),
                "lecture": etat_lecture(c),
                "recopieCode": etat_code_recopie(c),
                "minuteurFin": minuteur_en_cours(c),
                "reprises": reprises_kodi(Path.home() / ".kodi"),
                "services": services_disponibles(),
                # Le choix du profil se fait à l'allumage, pas à chaque retour de Kodi.
                "retour": deja_ouvert,
                "tempsEcran": temps_ecran(),
                "allumage": etat_allumage(),
                "reveilProgramme": reveil_programme(deja_ouvert=deja_ouvert),
            }
            cache = lire_json(c["meteo"])
            if cache and "donnees" in cache:
                initial["meteo"] = {"donnees": cache["donnees"], "releveLe": cache["releve"] * 1000, "horsLigne": False}
            if self.ambiant:
                # « retour » : ni intro, ni choix du profil, ni code à l'ouverture.
                initial.update(retour=True, reveilProgramme=False, ambiantSeul=True)
            contenus.add_script(WebKit.UserScript.new(
                f"window.HUB_INITIAL = {json.dumps(initial)};",
                WebKit.UserContentInjectedFrames.TOP_FRAME,
                WebKit.UserScriptInjectionTime.START, None, None))
            try:
                # Pas pour l'ambiant : le prochain vrai menu croirait revenir d'un mode
                # et sauterait le choix du profil et son code.
                if not self.ambiant:
                    ecrire_atomique(c["deja-ouvert"], "1")
            except OSError:
                pass

            vue = WebKit.WebView(user_content_manager=contenus)
            fond = Gdk.RGBA()
            fond.parse("#06070c")
            vue.set_background_color(fond)
            vue.connect("context-menu", lambda *_: True)
            reglages = vue.get_settings()
            reglages.set_enable_developer_extras(False)
            reglages.set_allow_file_access_from_file_urls(True)
            reglages.set_media_playback_requires_user_gesture(False)
            vue.load_uri(page.as_uri())
            vue.grab_focus()
            self.vue = vue
            if not self.ambiant:
                self.ecouter_voix()
            self.telecommande = initial["telecommande"]
            self.appairage_affiche, self.appairage_touche = False, None
            # Un menu tombé pendant l'appairage a pu laisser le fichier : l'écran n'est pas affiché.
            fermer_appairage(c)
            self.suivre_si_en_cours()
            GLib.timeout_add_seconds(2, self.surveiller_telecommande)
            self.lecture = initial["lecture"]
            self.recopie_code = initial["recopieCode"]
            self.reglages_enceinte = initial["reglages"]
            # Chaque seconde : un bandeau « en cours de lecture » en retard de deux
            # secondes sur le téléphone se remarque.
            GLib.timeout_add_seconds(1, self.surveiller_lecture)
            return vue

        def suivre_si_en_cours(self):
            # Une mise à jour lancée ailleurs (télécommande, SSH) se suit aussi depuis le menu.
            etat = etat_mise_a_jour()
            if etat and etat["etape"] not in ("terminee", "echec", "a-jour") and not self.suivi_maj:
                self.suivi_maj = True
                self.etat_maj = etat
                GLib.timeout_add_seconds(2, self.suivre_mise_a_jour)

        def suivre_mise_a_jour(self):
            etat = etat_mise_a_jour()
            if etat != self.etat_maj:
                self.etat_maj = etat
                self.vers_page({"type": "maj", "etat": etat})
            fini = bool(etat and etat["etape"] in ("terminee", "echec", "a-jour"))
            if fini:
                self.suivi_maj = False
            return not fini

        def surveiller_telecommande(self):
            self.appairage_touche = suivre_appairage(c, self.appairage_affiche, self.appairage_touche)
            etat = etat_telecommande(c)
            if etat != self.telecommande:
                self.telecommande = etat
                self.vers_page({"type": "telecommande", "etat": etat})
            return True

        def surveiller_lecture(self):
            code = etat_code_recopie(c)
            if code != self.recopie_code:
                self.recopie_code = code
                self.vers_page({"type": "recopie-appairage", "etat": code})
            etat = etat_lecture(c)
            if etat != self.lecture:
                recopie_finie = bool(self.lecture and self.lecture.get("ecran")) and not (etat and etat.get("ecran"))
                self.lecture = etat
                self.vers_page({"type": "lecture", "etat": etat})
                if recopie_finie:
                    # La fenêtre d'UxPlay vient de se fermer : le menu reprend le clavier
                    # au lieu de le laisser au compositeur.
                    self.fenetre.present()
            return True

        def vers_page(self, message):
            if self.vue:
                script = f"window.hub && window.hub.recevoir({json.dumps(message)});"
                self.vue.evaluate_javascript(script, -1, None, None, None, None, None)
            return False

        def en_fond(self, travail, *args):
            """Réseau et systemd hors du fil graphique : le menu ne gèle jamais."""
            def executer():
                reponse = travail(*args)
                if reponse:
                    GLib.idle_add(self.vers_page, reponse)
            threading.Thread(target=executer, daemon=True).start()

        def message_recu(self, _contenus, valeur):
            message = lire_message_page(valeur.to_string())
            if not message or not message_permis(message["type"], self.ambiant):
                return
            genre = message["type"]
            if genre == "ambiant-fin":
                self.quit()
            elif genre == "choix" and message.get("mode") == "web":
                # La seconde ligne porte le service ; inconnu, on ne ferme pas le menu.
                if service_choisi(message):
                    self.choix, self.fichier = "web", service_choisi(message)
                    self.quit()
            elif genre == "choix" and message.get("mode") in MODES:
                self.choix = message["mode"]
                if self.choix == "tv" and isinstance(message.get("fichier"), str) and "\n" not in message["fichier"]:
                    self.fichier = message["fichier"]
                retenir(c, self.choix)
                self.quit()
            elif genre == "reglages":
                try:
                    if enregistrer_reglages(c, message.get("donnees")):
                        appliquer_habillage(message["donnees"])
                        appliquer_enceinte(getattr(self, "reglages_enceinte", None), message["donnees"])
                        self.reglages_enceinte = message["donnees"]
                except OSError as erreur:
                    print(f"hub-menu : réglages non enregistrés ({erreur})", file=sys.stderr)
            elif genre == "meteo":
                lat, lon = message.get("lat"), message.get("lon")
                if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                    def releve():
                        r = meteo(c, lat, lon)
                        return r and {"type": "meteo", "donnees": r["donnees"], "releveLe": r["releve"] * 1000, "horsLigne": r["horsLigne"]}
                    self.en_fond(releve)
            elif genre == "geocodage" and isinstance(message.get("nom"), str):
                self.en_fond(lambda: {"type": "geocodage", "resultats": geocodage(message["nom"], message.get("langue", "fr"))})
            elif genre == "appairage":
                self.appairage_affiche = message.get("affiche") is True
                self.appairage_touche = suivre_appairage(c, self.appairage_affiche, None if self.appairage_affiche else self.appairage_touche)
                if self.appairage_affiche:
                    # Le service publie l'ouverture en quelques secondes : on relit sans attendre le tour suivant.
                    GLib.timeout_add_seconds(1, lambda: self.surveiller_telecommande() and False)
            elif genre == "recopie-code":
                nouveau = message.get("nouveau") is True
                self.en_fond(lambda: {"type": "recopie-code", "code": code_recopie(nouveau), "permise": recopie_permise(), "nouveau": nouveau})
            elif genre == "pin-verifier":
                demande, profils, code = message.get("demande"), message.get("profils"), message.get("code")
                self.en_fond(lambda: {"type": "pin", "demande": demande, **verifier_pin(c, profils, code)})
            elif genre == "pin-creer":
                demande, code = message.get("demande"), message.get("code")
                self.en_fond(lambda: {"type": "pin", "demande": demande, **creer_pin(code)})
            elif genre == "minuteur" and isinstance(message.get("minutes"), int):
                minutes = max(0, min(message["minutes"], 240))
                self.en_fond(lambda: {"type": "minuteur", "fin": programmer_minuteur(c, minutes)})
            elif genre == "maj-verifier":
                self.en_fond(lambda: {"type": "maj", "verification": verifier_mise_a_jour(), "etat": etat_mise_a_jour()})
            elif genre == "maj-etat":
                self.vers_page({"type": "maj", "etat": etat_mise_a_jour()})
                self.suivre_si_en_cours()
            elif genre == "maj-appliquer":
                if lancer_mise_a_jour():
                    self.etat_maj = None
                    if not self.suivi_maj:
                        self.suivi_maj = True
                        GLib.timeout_add_seconds(2, self.suivre_mise_a_jour)
                else:
                    self.vers_page({"type": "maj", "etat": {"etape": "echec", "raison": "lancement"}})
            elif genre == "relancer":
                # Sortir sans choix : le script de session relance le menu, dans sa nouvelle version.
                self.quit()
            elif genre == "avatars":
                self.en_fond(lambda: {"type": "avatars", "liste": avatars()})
            elif genre == "infos":
                self.en_fond(lambda: {"type": "infos", **infos()})
            elif genre == "temps-ecran":
                self.en_fond(lambda: {"type": "temps-ecran", "etat": temps_ecran()})
            elif genre == "temps-prolonger":
                profil, minutes = message.get("profil"), message.get("minutes")
                self.en_fond(lambda: {"type": "temps-ecran", "etat": prolonger_temps(profil, minutes) or temps_ecran()})
            elif genre == "cadre":
                album = message.get("album") if isinstance(message.get("album"), str) else None
                self.en_fond(lambda: cadre(album, message.get("souvenirs") is True))
            elif genre == "allumage-appliquer":
                def armer():
                    lance = appliquer_allumage()
                    # Le service tourne en quelques dixièmes de seconde : on relit après.
                    time.sleep(2)
                    return {"type": "allumage", "lance": lance, **etat_allumage()}
                self.en_fond(armer)
            elif genre == "allumage-etat":
                self.en_fond(lambda: {"type": "allumage", **etat_allumage()})

        # La voix ──────────────────────────────────────────────────────────
        def ecouter_voix(self):
            try:
                Path(c["execution"]).mkdir(parents=True, exist_ok=True)
                Path(c["socket"]).unlink(missing_ok=True)
                s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                s.bind(str(c["socket"]))
                s.setblocking(False)
            except OSError as erreur:
                print(f"hub-menu : pas de socket pour la voix ({erreur})", file=sys.stderr)
                return
            self.ecoute = s
            GLib.io_add_watch(s.fileno(), GLib.IO_IN, self.datagramme_recu)

        def datagramme_recu(self, *_):
            try:
                while True:
                    message = message_voix(self.ecoute.recv(4096))
                    if message == {"type": "avatars"}:
                        # Une photo vient d'arriver (télécommande) : la liste est relue ici.
                        message = {"type": "avatars", "liste": avatars()}
                    if message:
                        self.vers_page(message)
            except BlockingIOError:
                pass
            except OSError:
                return False
            return True

        # Repli sans WebKit ────────────────────────────────────────────────
        def vue_simple(self):
            colonne = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
            colonne.set_halign(Gtk.Align.CENTER)
            colonne.set_valign(Gtk.Align.CENTER)
            premier = None
            for cle, nom in zip(MODES, ("TV", "Jeux", "Bureau", "Éteindre")):
                bouton = Gtk.Button(label=nom)
                bouton.connect("clicked", self.choisir, cle)
                colonne.append(bouton)
                premier = premier or bouton
            premier.grab_focus()
            return colonne

        def choisir(self, _bouton, cle):
            self.choix = cle
            retenir(c, cle)
            self.quit()

    menu = Menu()
    menu.run(None)
    if ambiant:
        return 0
    if menu.choix:
        # Première ligne : le mode. Seconde, facultative : le fichier à reprendre
        # (lu par gnome-kiosk-script, qui le passe à hub-kodi-lire), ou le service
        # pour « web » (passé à hub-web, qui le refuse s'il n'est pas dans sa liste).
        print(menu.choix)
        if menu.fichier:
            print(menu.fichier)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(lancer())
