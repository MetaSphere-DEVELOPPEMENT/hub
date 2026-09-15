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

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

MODES = ("tv", "gaming", "bureau", "eteindre")
COMMANDES = {
    "tv", "gaming", "bureau", "eteindre", "reglages", "aide", "meteo", "profils",
    "retour", "gauche", "droite", "haut", "bas", "ok", "theme:clair", "theme:sombre",
}
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
        "execution": execution,
        "socket": execution / "menu.sock",
        "deja-ouvert": execution / "menu-deja-ouvert",
        "minuteur": execution / "minuteur-fin",
        "telecommande": execution / "telecommande.json",
    }


# ── Fichiers ──────────────────────────────────────────────────────────────
def ecrire_atomique(chemin, texte):
    """Un réglage à moitié écrit (coupure pendant l'écriture) ne doit jamais remplacer
    le précédent : on écrit à côté, puis on renomme."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_name(chemin.name + ".tmp")
    provisoire.write_text(texte, encoding="utf-8")
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


def charger_reglages(c):
    donnees = lire_json(c["reglages"])
    return donnees if reglages_valides(donnees) else None


def enregistrer_reglages(c, donnees):
    if not reglages_valides(donnees):
        return False
    ecrire_atomique(c["reglages"], json.dumps(donnees, ensure_ascii=False, indent=2))
    return True


def dernier_choix(c):
    try:
        choix = Path(c["dernier"]).read_text().strip()
    except OSError:
        return None
    return choix if choix in MODES else None


def retenir(c, choix):
    if choix in MODES and choix != "eteindre":
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
def etat_telecommande(c):
    """Ce que hub-telecommande publie pour l'écran d'appairage ; None s'il ne tourne pas
    (il supprime son fichier en s'arrêtant)."""
    donnees = lire_json(c["telecommande"])
    if not isinstance(donnees, dict) or not isinstance(donnees.get("url"), str) or not isinstance(donnees.get("code"), str):
        return None
    garder = ("url", "code", "expire", "telephones", "appairageLe")
    return {k: donnees.get(k) for k in garder}


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


# ── Interface ─────────────────────────────────────────────────────────────
def lancer():
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
            super().__init__(application_id="fr.boudine.HubMenu")
            self.choix = None
            self.fichier = None
            self.etat_maj = None
            self.vue = None
            self.ecoute = None

        def do_activate(self):
            fenetre = Gtk.ApplicationWindow(application=self, title="HUB")
            page = page_du_menu()
            fenetre.set_child(self.vue_web(page) if WebKit and page else self.vue_simple())
            fenetre.fullscreen()
            fenetre.present()

        def do_shutdown(self):
            if self.ecoute:
                self.ecoute.close()
                Path(c["socket"]).unlink(missing_ok=True)
            Gtk.Application.do_shutdown(self)

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
                "minuteurFin": minuteur_en_cours(c),
                "reprises": reprises_kodi(Path.home() / ".kodi"),
                # Le choix du profil se fait à l'allumage, pas à chaque retour de Kodi.
                "retour": deja_ouvert,
            }
            cache = lire_json(c["meteo"])
            if cache and "donnees" in cache:
                initial["meteo"] = {"donnees": cache["donnees"], "releveLe": cache["releve"] * 1000, "horsLigne": False}
            contenus.add_script(WebKit.UserScript.new(
                f"window.HUB_INITIAL = {json.dumps(initial)};",
                WebKit.UserContentInjectedFrames.TOP_FRAME,
                WebKit.UserScriptInjectionTime.START, None, None))
            try:
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
            self.ecouter_voix()
            self.telecommande = initial["telecommande"]
            GLib.timeout_add_seconds(2, self.surveiller_telecommande)
            return vue

        def suivre_mise_a_jour(self):
            etat = etat_mise_a_jour()
            if etat != self.etat_maj:
                self.etat_maj = etat
                self.vers_page({"type": "maj", "etat": etat})
            return not (etat and etat["etape"] in ("terminee", "echec", "a-jour"))

        def surveiller_telecommande(self):
            etat = etat_telecommande(c)
            if etat != self.telecommande:
                self.telecommande = etat
                self.vers_page({"type": "telecommande", "etat": etat})
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
            if not message:
                return
            genre = message["type"]
            if genre == "choix" and message.get("mode") in MODES:
                self.choix = message["mode"]
                if self.choix == "tv" and isinstance(message.get("fichier"), str) and "\n" not in message["fichier"]:
                    self.fichier = message["fichier"]
                retenir(c, self.choix)
                self.quit()
            elif genre == "reglages":
                try:
                    if enregistrer_reglages(c, message.get("donnees")):
                        appliquer_habillage(message["donnees"])
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
            elif genre == "minuteur" and isinstance(message.get("minutes"), int):
                minutes = max(0, min(message["minutes"], 240))
                self.en_fond(lambda: {"type": "minuteur", "fin": programmer_minuteur(c, minutes)})
            elif genre == "maj-verifier":
                self.en_fond(lambda: {"type": "maj", "verification": verifier_mise_a_jour(), "etat": etat_mise_a_jour()})
            elif genre == "maj-appliquer":
                if lancer_mise_a_jour():
                    self.etat_maj = None
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
    if menu.choix:
        # Première ligne : le mode. Seconde, facultative : le fichier à reprendre
        # (lu par gnome-kiosk-script, qui le passe à hub-kodi-lire).
        print(menu.choix)
        if menu.fichier:
            print(menu.fichier)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(lancer())
