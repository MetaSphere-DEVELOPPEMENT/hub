#!/usr/bin/env python3
"""Commande vocale du HUB, 100 % hors ligne — /opt/hub-voix/hub-voix.py

On dit « OK HUB » (ou le mot d'éveil choisi dans les réglages : « Salut HUB »,
« Dis HUB », un prénom), puis la commande ; ou tout d'une traite : « OK HUB, lance la
télé ». Rien ne quitte la machine.

POURQUOI VOSK EN GRAMMAIRE RESTREINTE. Le petit modèle français (40 Mo) tourne sur
un cœur de l'i3-8100T sans le saturer, et limité à la liste des phrases du HUB il ne
choisit plus qu'entre elles ou « [unk] ». Whisper (même tiny) transcrit mieux la
parole libre, mais par blocs, avec plusieurs secondes de latence et un cœur plein à
chaque phrase : il faudrait en plus un détecteur de mot d'éveil devant lui. Les
détecteurs de mot d'éveil dédiés (openWakeWord, Porcupine) demandent d'entraîner
« HUB » ou une licence ; Vosk fait éveil et commande avec le même modèle.

CE QUI TOUCHE AU MATÉRIEL EST ICI, LA DÉCISION EST DANS hub_voix_logique.py.

LE MICRO. Le M720q n'en a pas. Le service démarre sans, interroge PipeWire
(pw-dump) toutes les quelques secondes, et capture avec pw-record dès qu'un micro
apparaît. La capture est un processus séparé : si PipeWire ou le pilote USB
déraille, c'est pw-record qui meurt, pas ce service ni la session.

LES CIBLES. Menu ouvert ($XDG_RUNTIME_DIR/hub/menu.sock existe) : chaque événement
lui part en datagramme, il décide. Menu fermé : seul « retour » agit — il quitte
Kodi, ou ferme la session bureau.

Essai sans micro : hub-voix.py --fichier phrase.wav [autre.wav…]
"""

import argparse
import json
import logging
import os
import select
import shutil
import signal
import subprocess
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_voix_logique as L  # noqa: E402

TAUX = 16000
# 0,1 s de son par bloc : assez court pour que la fin de phrase soit vue vite, assez
# long pour ne pas réveiller Python cent fois par seconde.
BLOC = TAUX // 10 * 2

MODELES = {"fr": "vosk-model-small-fr-0.22", "en": "vosk-model-small-en-us-0.15"}
DOSSIER_MODELES = Path(os.environ.get("HUB_VOIX_MODELES", "/opt/hub-voix/modeles"))

# Le service ne doit rien coûter quand il n'y a pas de micro : un pw-dump toutes les
# 3 s suffit à voir un micro branché avant qu'on ait fini de dire « HUB ».
PERIODE_MICRO = 3.0
PERIODE_REGLAGES = 2.0

# Code de sortie « configuration impossible » : l'unité systemd le déclare dans
# RestartPreventExitStatus pour ne pas relancer en boucle un service sans Vosk.
SORTIE_CONFIGURATION = 78

journal = logging.getLogger("hub-voix")


def chemin_socket():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "hub" / "menu.sock"


def chemin_pid_web():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "hub" / "web.pid"


def chemin_etat():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "hub" / "voix.json"


def chemin_reglages():
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "hub" / "reglages.json"


class Reconnaisseur:
    """Un modèle Vosk par langue, chargé à la demande et gardé une fois chargé.

    On garde l'ancien modèle au changement de langue : 40 Mo de mémoire contre une
    seconde de chargement à chaque aller-retour dans les réglages.
    """

    def __init__(self, dossier):
        import vosk  # importé ici : les tests et --aide ne doivent pas en dépendre
        vosk.SetLogLevel(-1)
        self.vosk = vosk
        self.dossier = Path(dossier)
        self.modeles = {}
        self.vocabulaires = {}
        self.langue = None
        self.mot_eveil = None
        self.rec = None

    def disponible(self, langue):
        return (self.dossier / MODELES[langue] / "am" / "final.mdl").is_file()

    def vocabulaire(self, langue):
        """Mots du modèle, lus une fois (0,1 s) : pour refuser un prénom qu'il ne connaît pas."""
        if langue not in self.vocabulaires:
            self.vocabulaires[langue] = L.vocabulaire_vosk(self.dossier / MODELES[langue] / "graph" / "Gr.fst")
        return self.vocabulaires[langue] or None

    def choisir(self, langue, mot_eveil=L.MOT_EVEIL_PAR_DEFAUT):
        if (langue, mot_eveil) == (self.langue, self.mot_eveil) and self.rec:
            return
        if langue not in self.modeles:
            debut = time.monotonic()
            self.modeles[langue] = self.vosk.Model(str(self.dossier / MODELES[langue]))
            journal.info("modèle %s chargé en %.1f s", MODELES[langue], time.monotonic() - debut)
        debut = time.monotonic()
        phrases = json.dumps(L.grammaire(langue, mot_eveil), ensure_ascii=False)
        self.rec = self.vosk.KaldiRecognizer(self.modeles[langue], TAUX, phrases)
        journal.info("grammaire %s « %s » prête en %.2f s", langue, " / ".join(L.eveils(mot_eveil, langue)),
                     time.monotonic() - debut)
        self.langue, self.mot_eveil = langue, mot_eveil

    def accepter(self, octets):
        """Texte d'une phrase terminée, ou None tant que la personne parle."""
        if self.rec.AcceptWaveform(octets):
            return json.loads(self.rec.Result()).get("text", "")
        return None

    def terminer(self):
        return json.loads(self.rec.FinalResult()).get("text", "")


class Actions:
    """Envoie chaque événement là où il a un sens. `simuler` n'exécute rien hors menu."""

    def __init__(self, socket_menu, simuler=False):
        self.socket_menu = Path(socket_menu)
        self.simuler = simuler

    def menu_ouvert(self):
        return self.socket_menu.is_socket()

    def __call__(self, evenement):
        menu = self.menu_ouvert()
        if menu and L.envoyer(self.socket_menu, evenement):
            journal.debug("→ menu : %s", evenement)
            return "menu"
        # Socket présent mais muet (menu tombé sans nettoyer) : on fait comme s'il
        # était fermé, sinon « retour » ne sortirait plus jamais de Kodi.
        est_retour = evenement == "retour"
        cible = L.cible(evenement, menu_ouvert=False,
                        kodi=est_retour and bool(L.processus(L.NOMS_KODI)),
                        bureau=est_retour and bool(L.processus(L.NOMS_BUREAU)),
                        web=est_retour and L.web_en_cours(chemin_pid_web()))
        if cible and self.simuler:
            journal.info("(simulé) %s → %s", evenement, cible)
        elif cible == "web":
            fermer_web()
        elif cible == "kodi":
            quitter_kodi()
        elif cible == "bureau":
            journal.info("retour : fermeture de la session bureau")
            lancer(["gnome-session-quit", "--logout", "--no-prompt"])
        return cible


def lancer(commande):
    try:
        return subprocess.run(commande, timeout=10, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def fermer_web():
    """hub-web ferme lui-même son navigateur : c'est lui qui sait le faire proprement."""
    programme = shutil.which("hub-web") or "/usr/local/bin/hub-web"
    if lancer([programme, "--fermer"]):
        journal.info("retour : service web fermé (hub-web --fermer)")
        return True
    journal.warning("retour : hub-web --fermer a échoué")
    return False


def quitter_kodi():
    """Du plus propre au plus brutal ; chaque étape n'est tentée que si la précédente échoue."""
    if L.quitter_kodi_tcp():
        journal.info("retour : Kodi quitté par JSON-RPC (TCP 9090)")
        return True
    url = os.environ.get("HUB_KODI_HTTP", "http://127.0.0.1:8080/jsonrpc")
    if L.quitter_kodi_http(url, os.environ.get("HUB_KODI_UTILISATEUR"),
                           os.environ.get("HUB_KODI_MOT_DE_PASSE")):
        journal.info("retour : Kodi quitté par JSON-RPC (HTTP)")
        return True
    if shutil.which("kodi-send") and lancer(["kodi-send", "--action=Quit"]):
        journal.info("retour : Kodi quitté par kodi-send")
        return True
    # Dernier recours : Kodi traite SIGTERM comme une demande de sortie (il enregistre
    # ses réglages), c'est ce que fait systemd à l'arrêt. Mieux que rester coincé.
    pids = L.processus(L.NOMS_KODI)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    journal.warning("retour : aucun canal de contrôle Kodi, SIGTERM envoyé à %s", pids)
    return bool(pids)


def micros():
    try:
        sortie = subprocess.run(["pw-dump"], capture_output=True, timeout=5).stdout
        return L.micros_pipewire(json.loads(sortie or b"[]"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


class Service:
    def __init__(self, dossier_modeles, actions, reglages):
        self.actions = actions
        self.reglages = Path(reglages)
        self.dossier_modeles = dossier_modeles
        self.reconnaisseur = None
        self.ecoute = L.Ecoute(L.LANGUE_PAR_DEFAUT)
        self.voix, self.langue = True, L.LANGUE_PAR_DEFAUT
        self.mot_demande = self.mot_eveil = L.MOT_EVEIL_PAR_DEFAUT
        self.refus = None
        self.empreinte_reglages = None
        self.capture = None
        self.micro = None
        self.etat_micro = None
        self.menu_vu = False
        self.fin = False

    # --- état partagé avec le menu -------------------------------------------------

    def signaler_micro(self, present):
        etat = "voix:micro-present" if present else "voix:micro-absent"
        if etat != self.etat_micro:
            self.etat_micro = etat
            journal.info(etat)
            self.actions(etat)

    def surveiller_menu(self):
        # Le menu est relancé à chaque retour d'un mode : il ne sait rien de l'état du
        # micro. On le lui redit dès que son socket apparaît.
        ouvert = self.actions.menu_ouvert()
        if ouvert and not self.menu_vu and self.etat_micro:
            self.actions(self.etat_micro)
            self.actions("voix:repos")
        self.menu_vu = ouvert

    def relire_reglages(self):
        try:
            st = self.reglages.stat()
            empreinte = (st.st_mtime_ns, st.st_size)
        except OSError:
            empreinte = None
        if empreinte == self.empreinte_reglages:
            return
        self.empreinte_reglages = empreinte
        voix, langue = L.lire_reglages(self.reglages)
        mot = L.lire_mot_eveil(self.reglages)
        if (voix, langue, mot) != (self.voix, self.langue, self.mot_demande):
            journal.info("réglages : voix %s, langue %s, mot d'éveil %s",
                         "active" if voix else "coupée", langue, mot)
        self.voix, self.langue, self.mot_demande = voix, langue, mot
        self.valider_mot_eveil()

    def valider_mot_eveil(self):
        """Le mot d'éveil demandé, s'il peut servir dans cette langue ; sinon le défaut.

        Un prénom que le modèle ne connaît pas rendrait le HUB sourd sans un mot : on
        garde le défaut, on le dit au journal et dans voix.json, que le menu peut lire.
        """
        vocabulaire = self.reconnaisseur.vocabulaire(self.langue) \
            if self.reconnaisseur and self.reconnaisseur.disponible(self.langue) else None
        refus = L.refus_mot_eveil(self.mot_demande, self.langue, vocabulaire)
        effectif = L.MOT_EVEIL_PAR_DEFAUT if refus else self.mot_demande
        if refus and refus != self.refus:
            journal.warning("mot d'éveil « %s » refusé (%s) : « %s » gardé",
                            self.mot_demande, refus, " / ".join(L.eveils(effectif, self.langue)))
        self.refus, self.mot_eveil = refus, effectif
        self.ecoute.langue, self.ecoute.mot_eveil = self.langue, effectif
        self.ecrire_etat()

    def ecrire_etat(self):
        etat = {"motEveil": self.mot_eveil, "demande": self.mot_demande, "refus": self.refus,
                "phrases": list(L.eveils(self.mot_eveil, self.langue)), "langue": self.langue}
        try:
            chemin = chemin_etat()
            chemin.parent.mkdir(parents=True, exist_ok=True)
            temporaire = chemin.with_suffix(".tmp")
            temporaire.write_text(json.dumps(etat, ensure_ascii=False), encoding="utf-8")
            temporaire.replace(chemin)
        except OSError:
            pass

    # --- capture -------------------------------------------------------------------

    def ouvrir_capture(self, micro):
        commande = ["pw-record", "--target", micro, "--rate", str(TAUX), "--channels", "1",
                    "--format", "s16", "--media-role", "Communication",
                    "-P", "node.name=hub-voix", "-"]
        try:
            self.capture = subprocess.Popen(commande, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL)
        except OSError as erreur:
            journal.error("pw-record introuvable (%s) : paquet pipewire-bin", erreur)
            self.capture = None
            return False
        self.micro = micro
        journal.info("écoute de %s", micro)
        return True

    def fermer_capture(self):
        if self.capture:
            self.capture.terminate()
            try:
                self.capture.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.capture.kill()
        self.capture = None
        self.micro = None

    def emettre(self, evenements):
        for evenement in evenements:
            journal.info("événement : %s", evenement)
            self.actions(evenement)

    # --- boucle --------------------------------------------------------------------

    def boucle(self):
        prochain_micro = prochain_reglages = 0.0
        modele_absent_signale = None
        while not self.fin:
            maintenant = time.monotonic()
            if maintenant >= prochain_reglages:
                self.relire_reglages()
                self.surveiller_menu()
                prochain_reglages = maintenant + PERIODE_REGLAGES

            if not self.voix:
                if self.capture:
                    journal.info("voix coupée dans les réglages : micro relâché")
                    self.fermer_capture()
                    self.emettre(self.ecoute.tic(float("inf")))
                time.sleep(PERIODE_REGLAGES)
                continue

            if not self.reconnaisseur.disponible(self.langue):
                if modele_absent_signale != self.langue:
                    journal.error("modèle %s absent de %s : lancer telecharger-modele.sh",
                                  MODELES[self.langue], self.dossier_modeles)
                    modele_absent_signale = self.langue
                self.fermer_capture()
                time.sleep(PERIODE_REGLAGES)
                continue
            if modele_absent_signale:
                # Le modèle vient d'arriver : le prénom choisi peut enfin être vérifié.
                self.valider_mot_eveil()
            modele_absent_signale = None
            if (self.reconnaisseur.langue, self.reconnaisseur.mot_eveil) != (self.langue, self.mot_eveil):
                self.reconnaisseur.choisir(self.langue, self.mot_eveil)

            if maintenant >= prochain_micro:
                presents = micros()
                prochain_micro = maintenant + PERIODE_MICRO
                if self.capture and self.micro not in presents:
                    journal.info("micro %s débranché", self.micro)
                    self.fermer_capture()
                if not self.capture and presents:
                    self.ouvrir_capture(presents[0])
                self.signaler_micro(bool(self.capture))

            if not self.capture:
                time.sleep(0.5)
                continue

            pret, _, _ = select.select([self.capture.stdout], [], [], 0.5)
            if pret:
                octets = os.read(self.capture.stdout.fileno(), BLOC)
                if not octets:
                    journal.warning("pw-record s'est arrêté")
                    self.fermer_capture()
                    prochain_micro = 0.0
                    continue
                texte = self.reconnaisseur.accepter(octets)
                if texte is not None:
                    if texte:
                        journal.info("reconnu : %s", texte)
                    self.emettre(self.ecoute.entendre(texte, time.monotonic()))
            self.emettre(self.ecoute.tic(time.monotonic()))
        self.fermer_capture()


def lire_wav(chemin):
    """Octets PCM 16 kHz mono 16 bits ; ffmpeg convertit les autres formats s'il existe."""
    try:
        with wave.open(str(chemin), "rb") as w:
            if (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (TAUX, 1, 2):
                return w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        pass
    sortie = subprocess.run(["ffmpeg", "-v", "error", "-i", str(chemin), "-ac", "1", "-ar",
                             str(TAUX), "-f", "s16le", "-"], capture_output=True, check=True)
    return sortie.stdout


def mode_fichier(fichiers, langue, dossier_modeles, actions, mot_eveil=L.MOT_EVEIL_PAR_DEFAUT):
    """Fait passer des fichiers son par le même chemin que le micro, à la suite.

    Le temps est celui du son, pas de l'horloge : un fichier « hub.wav » suivi de
    « tele.wav » se comporte comme les deux phrases dites à la suite. Chaque ligne
    affichée porte l'instant (en secondes de son) et le temps de calcul cumulé.
    """
    reconnaisseur = Reconnaisseur(dossier_modeles)
    if not reconnaisseur.disponible(langue):
        journal.error("modèle %s absent de %s", MODELES[langue], dossier_modeles)
        return SORTIE_CONFIGURATION
    refus = L.refus_mot_eveil(mot_eveil, langue, reconnaisseur.vocabulaire(langue))
    if refus:
        journal.error("mot d'éveil « %s » refusé (%s)", mot_eveil, refus)
        return SORTIE_CONFIGURATION
    reconnaisseur.choisir(langue, mot_eveil)
    ecoute = L.Ecoute(langue, mot_eveil=mot_eveil)
    position = 0.0
    calcul = 0.0

    def publier(evenements, instant):
        for evenement in evenements:
            cible = actions(evenement)
            print(f"{instant:7.2f}s  calcul {calcul:6.2f}s  {evenement}  → {cible or 'ignoré'}",
                  flush=True)

    for fichier in fichiers:
        octets = lire_wav(fichier)
        print(f"# {fichier} ({len(octets) / 2 / TAUX:.2f} s)", flush=True)
        for debut in range(0, len(octets), BLOC):
            morceau = octets[debut:debut + BLOC]
            t0 = time.process_time()
            texte = reconnaisseur.accepter(morceau)
            calcul += time.process_time() - t0
            position += len(morceau) / 2 / TAUX
            if texte is not None:
                if texte:
                    print(f"{position:7.2f}s  reconnu : {texte}", flush=True)
                publier(ecoute.entendre(texte, position), position)
            publier(ecoute.tic(position), position)
        t0 = time.process_time()
        texte = reconnaisseur.terminer()
        calcul += time.process_time() - t0
        if texte:
            print(f"{position:7.2f}s  reconnu : {texte}", flush=True)
        publier(ecoute.entendre(texte, position), position)
    print(f"# son {position:.2f} s, calcul {calcul:.2f} s, "
          f"facteur temps réel {calcul / max(position, 1e-9):.3f}", flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Commande vocale hors ligne du HUB.")
    parser.add_argument("--fichier", nargs="+", metavar="WAV",
                        help="reconnaître ces fichiers au lieu du micro (essai, mesure)")
    parser.add_argument("--langue", choices=L.LANGUES,
                        help="avec --fichier : langue (défaut : celle des réglages)")
    parser.add_argument("--mot-eveil", help="avec --fichier : ok-hub, salut-hub, dis-hub, hub "
                        "ou un prénom (défaut : celui des réglages)")
    parser.add_argument("--modeles", type=Path, default=DOSSIER_MODELES,
                        help=f"dossier des modèles Vosk (défaut {DOSSIER_MODELES})")
    parser.add_argument("--socket", type=Path, default=None, help="socket du menu")
    parser.add_argument("--reglages", type=Path, default=None, help="reglages.json")
    parser.add_argument("--agir", action="store_true",
                        help="avec --fichier : quitter vraiment Kodi ou le bureau sur « retour »")
    parser.add_argument("-v", "--verbeux", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbeux else logging.INFO,
                        format="%(levelname)s %(message)s", stream=sys.stderr)
    socket_menu = args.socket or chemin_socket()
    reglages = args.reglages or chemin_reglages()

    try:
        import vosk  # noqa: F401
    except ImportError:
        journal.error("module vosk introuvable : voir installer/voix/README.md")
        return SORTIE_CONFIGURATION

    if args.fichier:
        # Par sécurité, un essai sur fichier ne ferme pas la session de celui qui le lance.
        actions = Actions(socket_menu, simuler=not args.agir)
        langue = args.langue or L.lire_reglages(reglages)[1]
        mot = L.nettoyer_mot_eveil(args.mot_eveil) if args.mot_eveil else L.lire_mot_eveil(reglages)
        if not mot:
            journal.error("mot d'éveil illisible : %r", args.mot_eveil)
            return SORTIE_CONFIGURATION
        return mode_fichier(args.fichier, langue, args.modeles, actions, mot)

    service = Service(args.modeles, Actions(socket_menu), reglages)

    def arreter(_signal, _cadre):
        service.fin = True

    signal.signal(signal.SIGTERM, arreter)
    signal.signal(signal.SIGINT, arreter)
    try:
        service.reconnaisseur = Reconnaisseur(args.modeles)
        service.boucle()
    except Exception:  # noqa: BLE001
        # Le journal garde la trace ; systemd relance (Restart=on-failure).
        journal.exception("erreur inattendue")
        service.fermer_capture()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
