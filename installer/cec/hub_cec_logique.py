"""Logique de la télécommande de la TV (HDMI-CEC) : ce qu'on fait de ce que dit cec-client.

POURQUOI UN MODULE À PART. Le M720q n'a pas de CEC ; tant que l'adaptateur USB n'est
pas branché, rien ne peut s'éprouver sur le matériel. Tout ce qui décide (lire une
ligne de cec-client, reconnaître un appui long, choisir entre menu, Kodi et service
web, savoir qui tient l'adaptateur) vit donc ici, sans dépendance, et
test_hub_cec.py le vérifie sur des traces au format exact de libcec 7.1.1.

POURQUOI LIRE LE TRAFIC BRUT PLUTÔT QUE « key pressed: … ». Les lignes « TRAFFIC »
sont les trames CEC elles-mêmes (« >> 04:44:01 » : la TV, adresse 0, envoie à
l'adresse 4 « User Control Pressed », touche 0x01). Leur format est fixé par la
norme ; les lignes « DEBUG key pressed » sont du texte de libcec, et sa logique de
touches combinées (Stop + OK = Exit) les réécrit. On lit les trames.
"""

import json
import os
import re
import socket
from pathlib import Path

# Identifiants USB de l'adaptateur Pulse-Eight (libcec les reconnaît tous deux ;
# Kodi 21 les liste dans system/peripherals.xml : « 2548:1001,2548:1002 »).
PULSE_EIGHT = {("2548", "1001"), ("2548", "1002")}

# Opcodes CEC utiles (norme HDMI-CEC 1.4, repris dans cectypes.h de libcec).
USER_CONTROL_PRESSED = 0x44
USER_CONTROL_RELEASED = 0x45
STANDBY = 0x36
ACTIVE_SOURCE = 0x82
SET_STREAM_PATH = 0x86

# Touches de la télécommande → noms internes. Seules les touches que la TV relaie
# vraiment ont un sens ; les codes viennent de cec_user_control_code (cectypes.h).
TOUCHES = {
    0x00: "ok",        # SELECT
    0x01: "haut",
    0x02: "bas",
    0x03: "gauche",
    0x04: "droite",
    0x0D: "retour",    # EXIT : c'est ce qu'envoient les Sony pour « BACK »
    0x91: "retour",    # AN_RETURN : le « retour » des Samsung, pour une autre TV
    0x2B: "ok",        # ENTER
    0x44: "lecture",
    0x46: "pause",
    0x61: "lecture-pause",
    0x45: "stop",
    0x48: "arriere",
    0x49: "avant",
}

# Les noms que le menu comprend (sous-ensemble de COMMANDES de hub-menu.py, vérifié
# par le test).
VERS_MENU = {"ok", "haut", "bas", "gauche", "droite", "retour"}

# Kodi piloté par son JSON-RPC (mode « relais »). Les mêmes méthodes que la
# télécommande téléphone (installer/telecommande, KODI_NAVIGATION).
VERS_KODI = {
    "haut": ("Input.Up", None), "bas": ("Input.Down", None),
    "gauche": ("Input.Left", None), "droite": ("Input.Right", None),
    "ok": ("Input.Select", None), "retour": ("Input.Back", None),
    "lecture": ("Input.ExecuteAction", {"action": "play"}),
    "pause": ("Input.ExecuteAction", {"action": "pause"}),
    "lecture-pause": ("Input.ExecuteAction", {"action": "playpause"}),
    "stop": ("Input.ExecuteAction", {"action": "stop"}),
    "arriere": ("Input.ExecuteAction", {"action": "rewind"}),
    "avant": ("Input.ExecuteAction", {"action": "fastforward"}),
}

# Touches qui se répètent quand on les tient : faire défiler une liste. « retour »
# n'en fait pas partie : tenu, il devient « accueil ».
REPETABLES = {"haut", "bas", "gauche", "droite"}

# Tenir « retour » plus longtemps que ceci, c'est demander l'accueil du HUB (quitter
# Kodi, fermer le service web). 1,2 s : plus long qu'un appui franc (100 à 300 ms),
# assez court pour qu'on n'ait pas l'impression que rien ne se passe.
APPUI_LONG_S = 1.2
# Sans trame depuis ce délai, la touche est considérée relâchée : certaines TV
# n'envoient jamais « User Control Released ». La norme CEC 1.4 fait répéter
# « User Control Pressed » toutes les 200 à 500 ms quand on tient une touche : 0,8 s
# laisse une marge à une répétition en retard sans confondre deux appuis.
RELACHE_IMPLICITE_S = 0.8

MODES_PARTAGE = ("relais", "ceder")
PARTAGE_PAR_DEFAUT = "relais"

_TRAFIC = re.compile(r"^TRAFFIC:\s*\[\s*\d+\]\s*>>\s*([0-9a-fA-F]{2})((?::[0-9a-fA-F]{2})*)\s*$")


def lire_ligne(ligne):
    """Une ligne de cec-client → dict décrivant l'événement, ou None.

    Trame reçue : {"type": "trame", "source": 0, "destination": 4, "opcode": 0x44,
    "donnees": [1]}. États de la connexion : {"type": "ouvert"} (« waiting for input »),
    {"type": "echec"} (autodétection ratée, port verrouillé par un autre programme).
    """
    ligne = ligne.rstrip("\r\n")
    m = _TRAFIC.match(ligne)
    if m:
        adresses = int(m.group(1), 16)
        octets = [int(x, 16) for x in m.group(2).split(":")[1:]]
        if not octets:
            # Trame d'interrogation (« poll ») : aucun opcode.
            return {"type": "trame", "source": adresses >> 4, "destination": adresses & 0xF,
                    "opcode": None, "donnees": []}
        return {"type": "trame", "source": adresses >> 4, "destination": adresses & 0xF,
                "opcode": octets[0], "donnees": octets[1:]}
    texte = ligne.split("\t", 1)[-1].strip()
    if texte == "waiting for input":
        return {"type": "ouvert"}
    if texte.startswith("unable to open the device") or texte in ("FAILED", "autodetect FAILED") \
            or ligne.strip().endswith("autodetect: FAILED") or "Couldn't lock the serial port" in texte:
        return {"type": "echec", "texte": texte}
    return None


class Clavier:
    """Appuis de la TV → événements « touche », avec l'appui long sur « retour ».

    Le temps est passé en argument (secondes, horloge monotone du service) : les tests
    le maîtrisent, et les horodatages de cec-client (millisecondes depuis son propre
    démarrage) ne servent pas à mesurer une attente entre deux lectures.
    """

    def __init__(self, appui_long=APPUI_LONG_S, relache=RELACHE_IMPLICITE_S):
        self.appui_long = appui_long
        self.relache = relache
        self.courante = None
        self.debut = 0.0
        self.derniere = 0.0
        self.long_emis = False

    def _relacher(self):
        nom, long_emis = self.courante, self.long_emis
        self.courante, self.long_emis = None, False
        # « retour » n'est envoyé qu'au relâcher : on ne sait qu'alors si c'était un
        # appui long. Un appui long a déjà produit « accueil » ; il ne produit rien de plus.
        if nom == "retour" and not long_emis:
            return ["retour"]
        return []

    def trame(self, trame, maintenant):
        if trame.get("type") != "trame":
            return []
        opcode = trame.get("opcode")
        if opcode == USER_CONTROL_RELEASED:
            if self.courante is None:
                return []
            evenements = self._verifier_long(maintenant)
            return evenements + self._relacher()
        if opcode != USER_CONTROL_PRESSED or not trame.get("donnees"):
            return []
        nom = TOUCHES.get(trame["donnees"][0])
        evenements = []
        if self.courante is not None and (nom != self.courante or
                                          maintenant - self.derniere > self.relache):
            evenements += self._relacher()
        if nom is None:
            return evenements
        if self.courante is None:
            self.courante, self.debut, self.long_emis = nom, maintenant, False
            self.derniere = maintenant
            if nom != "retour":
                evenements.append(nom)
            return evenements
        # Même touche tenue : la TV répète la trame.
        self.derniere = maintenant
        if nom in REPETABLES:
            evenements.append(nom)
        return evenements + self._verifier_long(maintenant)

    def _verifier_long(self, maintenant):
        if self.courante == "retour" and not self.long_emis and \
                maintenant - self.debut >= self.appui_long:
            self.long_emis = True
            return ["accueil"]
        return []

    def tic(self, maintenant):
        """À appeler régulièrement : appui long atteint, ou relâcher jamais reçu."""
        if self.courante is None:
            return []
        evenements = self._verifier_long(maintenant)
        if maintenant - self.derniere > self.relache:
            # Une TV qui ne répète pas la trame et n'envoie pas « released » : on ne
            # peut pas savoir si la touche est tenue. Relâchée, par prudence.
            evenements += self._relacher()
        return evenements


def contexte(menu_ouvert, web, kodi, bureau):
    """Ce qui est à l'écran, dans l'ordre où hub-voix le décide (hub_voix_logique.cible)."""
    if menu_ouvert:
        return "menu"
    if web:
        return "web"
    if kodi:
        return "kodi"
    if bureau:
        return "bureau"
    return None


def destination(nom, ou, partage=PARTAGE_PAR_DEFAUT):
    """Que faire de la touche `nom` là où l'on est.

    Rend un tuple : ("menu", datagramme), ("kodi", méthode, paramètres),
    ("kodi-quitter",), ("web-fermer",) — ou None (rien à faire).

    - Menu : les touches de navigation, « accueil » vaut « retour ».
    - Service web (Chrome plein écran) : la page n'a pas d'interface qu'on pourrait
      piloter de l'extérieur ; seul l'appui long sur « retour » agit, il ferme le
      service. Un appui court ne fait rien plutôt que fermer Netflix par erreur.
    - Kodi : en mode « relais », ses touches passent par JSON-RPC ; en mode « ceder »,
      Kodi tient lui-même l'adaptateur et le service n'entend rien.
    - Bureau : rien. Une touche de TV qui fermerait la session ferait perdre un travail.
    """
    if ou == "menu":
        if nom == "accueil":
            return ("menu", "retour")
        return ("menu", nom) if nom in VERS_MENU else None
    if ou == "web":
        return ("web-fermer",) if nom == "accueil" else None
    if ou == "kodi":
        if partage != "relais":
            return None
        if nom == "accueil":
            return ("kodi-quitter",)
        if nom in VERS_KODI:
            methode, parametres = VERS_KODI[nom]
            return ("kodi", methode, parametres)
    return None


def tenir_adaptateur(partage, kodi_tourne):
    """Le service doit-il avoir l'adaptateur ouvert ?

    POURQUOI UN SEUL PROPRIÉTAIRE. libcec pose un verrou exclusif sur le port série
    (flock LOCK_EX | LOCK_NB, platform/posix/serialport.cpp) : le second programme
    échoue avec « Couldn't lock the serial port ». En mode « ceder », on ferme
    cec-client dès que Kodi apparaît ; libcec réessaie d'ouvrir pendant 10 s
    (CEC_DEFAULT_CONNECT_TIMEOUT, CECProcessor.cpp), ce qui laisse à Kodi le temps de
    le prendre. En mode « relais », Kodi ne doit pas l'ouvrir (installateur :
    peripheral_data/cec_2548_100x.xml, enabled=0).
    """
    return not (partage == "ceder" and kodi_tourne)


def adaptateur_present(racine="/sys/bus/usb/devices"):
    """Vrai si un adaptateur Pulse-Eight est branché (sysfs, sans ouvrir le port)."""
    try:
        entrees = os.listdir(racine)
    except OSError:
        return False
    for entree in entrees:
        dossier = os.path.join(racine, entree)
        try:
            with open(os.path.join(dossier, "idVendor"), encoding="ascii") as f:
                vendeur = f.read().strip().lower()
            with open(os.path.join(dossier, "idProduct"), encoding="ascii") as f:
                produit = f.read().strip().lower()
        except OSError:
            continue
        if (vendeur, produit) in PULSE_EIGHT:
            return True
    return False


def commande_cec_client(programme="cec-client", port_hdmi=None, type_appareil="r", nom="HUB"):
    """Ligne de commande de cec-client.

    -t r (« recording device ») : c'est le défaut de cec-client, et le type auquel les
    TV Sony relaient le plus de touches (conseil repris par la documentation de Kodi
    pour les Bravia ; à confirmer sur la KD-55XG70). -d 13 : erreurs, notices et
    trafic — pas le « DEBUG » bavard. -p : numéro de l'entrée HDMI de la TV, utile
    seulement si libcec ne trouve pas seul l'adresse physique.
    """
    commande = [programme, "-t", type_appareil, "-o", nom, "-d", "13"]
    if isinstance(port_hdmi, int) and 1 <= port_hdmi <= 15:
        commande += ["-p", str(port_hdmi)]
    return commande


# Ordres à la TV (adresse logique 0). « as » : le HUB devient la source active, la TV
# bascule sur son entrée HDMI (et s'allume sur la plupart des modèles).
ORDRES_TV = {
    "tv:allumer": ["on 0", "as"],
    "tv:veille": ["standby 0"],
    "tv:entree": ["as"],
}


def lire_reglages(chemin):
    """Réglages CEC depuis reglages.json : {"partage", "port_hdmi", "allumer_tv", "veille_tv"}.

    Tout ce qui manque ou est faux retombe sur les défauts : un réglage abîmé ne doit
    pas priver le salon de sa télécommande.
    """
    reglages = {"partage": PARTAGE_PAR_DEFAUT, "port_hdmi": None,
                "allumer_tv": True, "veille_tv": True}
    try:
        donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return reglages
    systeme = donnees.get("systeme") if isinstance(donnees, dict) else None
    cec = systeme.get("cec") if isinstance(systeme, dict) else None
    if not isinstance(cec, dict):
        return reglages
    if cec.get("partage") in MODES_PARTAGE:
        reglages["partage"] = cec["partage"]
    port = cec.get("portHdmi")
    if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 15:
        reglages["port_hdmi"] = port
    for cle, nom in (("allumerTv", "allumer_tv"), ("veilleTv", "veille_tv")):
        if isinstance(cec.get(cle), bool):
            reglages[nom] = cec[cle]
    return reglages


def envoyer(chemin, texte):
    """Un datagramme. Faux si personne n'écoute ; jamais d'exception."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(texte.encode("utf-8"), str(chemin))
        return True
    except OSError:
        return False
