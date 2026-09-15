#!/usr/bin/env python3
"""Télécommande de la TV par HDMI-CEC — /usr/local/lib/hub/cec/hub-cec.py

La télécommande Sony pilote le HUB : flèches, OK et Retour dans le menu, dans Kodi ;
Retour tenu ramène à l'accueil. Le HUB allume la TV au démarrage et la met en veille
quand il s'éteint.

POURQUOI UN ADAPTATEUR USB. Le M720q n'a pas de CEC (pas de /dev/cec*, audit du
13 septembre 2026). L'adaptateur Pulse-Eight se glisse sur le câble HDMI et parle CEC
par USB ; libcec le pilote, cec-client (paquet cec-utils) en est l'outil en ligne de
commande.

POURQUOI cec-client ET PAS UNE BIBLIOTHÈQUE PYTHON. Ubuntu 26.04 livre libcec7 et
cec-utils (7.1.1, universe) mais pas de python3-cec (vérifié dans l'archive
« resolute », API Launchpad, 15 septembre 2026). cec-client écrit chaque trame reçue
et accepte des ordres sur son entrée : un processus séparé, qu'on relance s'il meurt,
sans rien compiler.

QUI TIENT L'ADAPTATEUR. Un seul programme à la fois (verrou exclusif de libcec).
Mode « relais » (défaut) : ce service le garde toujours, et transmet les touches à
Kodi par JSON-RPC ; le CEC propre de Kodi est désactivé par l'installateur. Mode
« ceder » : le service ferme cec-client quand Kodi démarre et le rouvre quand il
quitte. Voir hub_cec_logique.tenir_adaptateur.

Ordres à la TV depuis un autre programme : hub-cec.py --tv allumer|veille|entree
"""

import argparse
import importlib.util
import json
import logging
import os
import select
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import hub_cec_logique as C  # noqa: E402

journal = logging.getLogger("hub-cec")

PERIODE_ADAPTATEUR = 5.0
# Au-delà, un cec-client qui ne dit pas « waiting for input » est coincé.
DELAI_OUVERTURE = 30.0


def execution():
    return Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "hub"


def chemin_reglages():
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "hub" / "reglages.json"


def charger_logique_voix():
    """hub_voix_logique sait reconnaître Kodi, le bureau, hub-web, et quitter Kodi.

    Mêmes emplacements que la télécommande téléphone. Absent : seul le menu est piloté.
    """
    for dossier in (os.environ.get("HUB_VOIX_DOSSIER"), ICI.parent / "voix",
                    "/usr/local/lib/hub/voix", "/opt/hub-voix"):
        fichier = Path(dossier) / "hub_voix_logique.py" if dossier else None
        if fichier and fichier.is_file():
            spec = importlib.util.spec_from_file_location("hub_voix_logique", fichier)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    return None


def appeler_kodi(methode, parametres=None, hote="127.0.0.1", port=None, delai=1.0):
    """Requête JSON-RPC sur le TCP 9090 de Kodi, sans attendre la réponse au-delà du délai.

    Une touche n'a pas besoin de confirmation : attendre la réponse ralentirait la
    navigation, et Kodi pousse ses notifications dans la même connexion.
    """
    port = port or int(os.environ.get("HUB_KODI_PORT", "9090"))
    requete = {"jsonrpc": "2.0", "method": methode, "id": 1}
    if parametres is not None:
        requete["params"] = parametres
    try:
        with socket.create_connection((hote, port), timeout=delai) as s:
            s.sendall(json.dumps(requete).encode())
            try:
                s.recv(4096)
            except socket.timeout:
                pass
        return True
    except OSError:
        return False


class CecClient:
    """Le processus cec-client : lancé, lu ligne à ligne, arrêté proprement."""

    def __init__(self, commande):
        self.commande = commande
        self.processus = None
        self.tampon = b""
        self.ouvert = False
        self.lance_a = 0.0

    def lancer(self):
        try:
            self.processus = subprocess.Popen(self.commande, stdin=subprocess.PIPE,
                                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except OSError as erreur:
            journal.error("cec-client ne se lance pas (%s) : paquet cec-utils", erreur)
            self.processus = None
            return False
        self.tampon, self.ouvert, self.lance_a = b"", False, time.monotonic()
        journal.info("cec-client lancé : %s", " ".join(self.commande))
        return True

    def vivant(self):
        return self.processus is not None and self.processus.poll() is None

    def ordre(self, texte):
        if not self.vivant():
            return False
        try:
            self.processus.stdin.write(texte.encode() + b"\n")
            self.processus.stdin.flush()
            journal.info("ordre à la TV : %s", texte)
            return True
        except OSError:
            return False

    def lignes(self):
        """Lignes complètes disponibles ; [] si rien, None si le processus a fermé."""
        morceau = os.read(self.processus.stdout.fileno(), 65536)
        if not morceau:
            return None
        self.tampon += morceau
        *completes, self.tampon = self.tampon.split(b"\n")
        return [l.decode("utf-8", errors="replace") for l in completes]

    def arreter(self, delai=3.0):
        if not self.processus:
            return
        # « q » : cec-client ferme la connexion libcec proprement (le verrou du port
        # est relâché tout de suite, pas au bon vouloir du noyau).
        self.ordre("q")
        try:
            self.processus.wait(timeout=delai)
        except subprocess.TimeoutExpired:
            self.processus.terminate()
            try:
                self.processus.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.processus.kill()
                self.processus.wait()
        self.fermer_tuyaux()
        self.processus, self.ouvert = None, False

    def fermer_tuyaux(self):
        for tuyau in (self.processus.stdin, self.processus.stdout):
            try:
                tuyau.close()
            except OSError:
                pass


class Service:
    def __init__(self, programme="cec-client", reglages=None, dossier_execution=None,
                 racine_usb="/sys/bus/usb/devices", voix="charger", horloge=time.monotonic):
        self.programme = programme
        self.reglages_chemin = Path(reglages or chemin_reglages())
        self.execution = Path(dossier_execution or execution())
        self.racine_usb = racine_usb
        self.horloge = horloge
        self.voix = charger_logique_voix() if voix == "charger" else voix
        self.reglages = C.lire_reglages(self.reglages_chemin)
        self.empreinte = None
        self.clavier = C.Clavier()
        self.client = None
        self.controle = None
        self.kodi_tourne = False
        self.reprendre_source = False
        self.fin = False

    # --- ce qui est à l'écran -------------------------------------------------------
    def ou(self):
        menu = (self.execution / "menu.sock").is_socket()
        if menu or not self.voix:
            return C.contexte(menu, False, False, False)
        return C.contexte(False, self.voix.web_en_cours(self.execution / "web.pid"),
                          bool(self.voix.processus(self.voix.NOMS_KODI)),
                          bool(self.voix.processus(self.voix.NOMS_BUREAU)))

    def agir(self, nom):
        ou = self.ou()
        action = C.destination(nom, ou, self.reglages["partage"])
        journal.info("touche %s (%s) → %s", nom, ou or "rien", action[0] if action else "ignorée")
        if not action:
            return None
        if action[0] == "menu":
            if not C.envoyer(self.execution / "menu.sock", action[1]):
                journal.warning("menu muet : %s perdu", action[1])
        elif action[0] == "kodi":
            appeler_kodi(action[1], action[2])
        elif action[0] == "kodi-quitter":
            if not (self.voix and self.voix.quitter_kodi_tcp()):
                appeler_kodi("Application.Quit")
        elif action[0] == "web-fermer":
            programme = shutil.which("hub-web") or "/usr/local/bin/hub-web"
            try:
                subprocess.run([programme, "--fermer"], timeout=10,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError) as erreur:
                journal.warning("hub-web --fermer : %s", erreur)
        return action

    # --- réglages, socket de contrôle ----------------------------------------------
    def relire_reglages(self):
        try:
            st = self.reglages_chemin.stat()
            empreinte = (st.st_mtime_ns, st.st_size)
        except OSError:
            empreinte = None
        if empreinte == self.empreinte:
            return False
        self.empreinte = empreinte
        nouveaux = C.lire_reglages(self.reglages_chemin)
        change = nouveaux != self.reglages
        port_change = nouveaux["port_hdmi"] != self.reglages["port_hdmi"]
        self.reglages = nouveaux
        if port_change and self.client:
            journal.info("port HDMI changé : cec-client relancé")
            self.fermer_client()
        return change

    def ouvrir_controle(self):
        chemin = self.execution / "cec.sock"
        self.execution.mkdir(parents=True, exist_ok=True)
        try:
            chemin.unlink()
        except FileNotFoundError:
            pass
        self.controle = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.controle.bind(str(chemin))
        # Le socket n'est pas plus ouvert que l'utilisateur : n'importe quel programme
        # d'un autre compte ne doit pas éteindre la TV.
        os.chmod(chemin, 0o600)

    def ordre_tv(self, ordre):
        if ordre not in C.ORDRES_TV:
            journal.warning("ordre inconnu : %r", ordre)
            return False
        if not (self.client and self.client.ouvert):
            journal.warning("%s : adaptateur CEC non ouvert", ordre)
            return False
        return all(self.client.ordre(o) for o in C.ORDRES_TV[ordre])

    # --- cycle de vie de cec-client ------------------------------------------------
    def fermer_client(self):
        if self.client:
            self.client.arreter()
        self.client = None

    def a_l_ouverture(self):
        drapeau = self.execution / "cec-tv-allumee"
        if self.reglages["allumer_tv"] and not drapeau.exists():
            # Une seule fois par démarrage : $XDG_RUNTIME_DIR est vidé à l'arrêt. Sans ce
            # drapeau, chaque changement de mode (nouvelle session, service relancé)
            # ramènerait la TV sur le HUB même si l'on venait de choisir une autre entrée.
            self.ordre_tv("tv:allumer")
            try:
                drapeau.touch()
            except OSError:
                pass
        elif self.reprendre_source:
            # Kodi, en quittant, envoie « Inactive Source » : la TV repartirait sur son
            # tuner. On reprend l'entrée pour le menu qui revient.
            self.ordre_tv("tv:entree")
        self.reprendre_source = False

    def traiter_ligne(self, ligne, maintenant):
        evenement = C.lire_ligne(ligne)
        if not evenement:
            return []
        if evenement["type"] == "ouvert":
            self.client.ouvert = True
            journal.info("adaptateur CEC ouvert")
            self.a_l_ouverture()
            return []
        if evenement["type"] == "echec":
            journal.warning("cec-client : %s", evenement.get("texte"))
            return []
        if evenement["opcode"] == C.STANDBY and evenement["source"] == 0:
            journal.info("la TV s'est mise en veille")
        return [self.agir(nom) for nom in self.clavier.trame(evenement, maintenant)]

    def etape(self, attente=0.25):
        """Un tour de boucle. Rend les actions effectuées (pour les tests)."""
        maintenant = self.horloge()
        actions = []
        if self.relire_reglages():
            journal.info("réglages CEC : %s", self.reglages)

        if self.reglages["partage"] == "ceder" and self.voix:
            kodi = bool(self.voix.processus(self.voix.NOMS_KODI))
            if self.kodi_tourne and not kodi:
                self.reprendre_source = True
            self.kodi_tourne = kodi
        else:
            self.kodi_tourne = False

        tenir = C.tenir_adaptateur(self.reglages["partage"], self.kodi_tourne)
        if self.client and not tenir:
            journal.info("Kodi démarre : adaptateur CEC cédé")
            self.fermer_client()
        if self.client and not self.client.vivant():
            journal.warning("cec-client s'est arrêté (code %s)", self.client.processus.returncode)
            self.client.fermer_tuyaux()
            self.client = None
            self.prochain_essai = maintenant + PERIODE_ADAPTATEUR
        if self.client and not self.client.ouvert and maintenant - self.client.lance_a > DELAI_OUVERTURE:
            journal.warning("cec-client n'ouvre pas l'adaptateur : relance")
            self.fermer_client()
        if tenir and not self.client and maintenant >= getattr(self, "prochain_essai", 0.0):
            self.prochain_essai = maintenant + PERIODE_ADAPTATEUR
            if C.adaptateur_present(self.racine_usb):
                client = CecClient(C.commande_cec_client(self.programme, self.reglages["port_hdmi"]))
                if client.lancer():
                    self.client = client

        lecteurs = [self.controle] if self.controle else []
        if self.client:
            lecteurs.append(self.client.processus.stdout)
        prets, _, _ = select.select(lecteurs, [], [], attente) if lecteurs else ([], [], [])
        if not lecteurs:
            time.sleep(attente)
        for lecteur in prets:
            if lecteur is self.controle:
                ordre = self.controle.recv(256).decode("utf-8", errors="replace").strip()
                actions.append(("ordre", ordre, self.ordre_tv(ordre)))
            elif self.client:
                lignes = self.client.lignes()
                if lignes is None:
                    continue
                for ligne in lignes:
                    actions += [a for a in self.traiter_ligne(ligne, self.horloge()) if a]
        actions += [a for a in (self.agir(n) for n in self.clavier.tic(self.horloge())) if a]
        return actions

    def arret(self):
        if self.client and self.client.ouvert and self.reglages["veille_tv"] and systeme_s_arrete():
            # Seulement quand la machine s'éteint : un service arrêté parce qu'on change
            # de mode ne doit pas éteindre la TV qu'on regarde.
            self.ordre_tv("tv:veille")
            time.sleep(1.0)
        self.fermer_client()
        if self.controle:
            self.controle.close()
            try:
                (self.execution / "cec.sock").unlink()
            except OSError:
                pass

    def boucle(self):
        self.ouvrir_controle()
        while not self.fin:
            self.etape()
        self.arret()


def systeme_s_arrete():
    try:
        etat = subprocess.run(["systemctl", "is-system-running"], capture_output=True,
                              text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    return etat == "stopping"


def main():
    parser = argparse.ArgumentParser(description="Télécommande de la TV par HDMI-CEC.")
    parser.add_argument("--tv", choices=("allumer", "veille", "entree"),
                        help="envoyer un ordre à la TV par le service en cours, puis sortir")
    parser.add_argument("--cec-client", default=os.environ.get("HUB_CEC_CLIENT", "cec-client"))
    parser.add_argument("--usb", default=os.environ.get("HUB_CEC_USB", "/sys/bus/usb/devices"),
                        help="racine sysfs où chercher l'adaptateur (essais)")
    parser.add_argument("-v", "--verbeux", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbeux else logging.INFO,
                        format="%(levelname)s %(message)s", stream=sys.stderr)

    if args.tv:
        ok = C.envoyer(execution() / "cec.sock", f"tv:{args.tv}")
        if not ok:
            print("hub-cec : le service n'écoute pas (systemctl --user status hub-cec)", file=sys.stderr)
        return 0 if ok else 1

    if not shutil.which(args.cec_client) and not Path(args.cec_client).is_file():
        journal.error("%s introuvable : apt-get install cec-utils", args.cec_client)
        return 78

    service = Service(programme=args.cec_client, racine_usb=args.usb)

    def arreter(_signal, _cadre):
        service.fin = True

    signal.signal(signal.SIGTERM, arreter)
    signal.signal(signal.SIGINT, arreter)
    try:
        service.boucle()
    except Exception:  # noqa: BLE001
        journal.exception("erreur inattendue")
        service.fermer_client()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
