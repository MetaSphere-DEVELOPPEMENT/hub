#!/usr/bin/env python3
"""Clavier et souris virtuels de la télécommande : le téléphone pilote la session.

Hors du menu et de Kodi (service web en plein écran, bureau GNOME), rien n'écoute la
télécommande : ni socket, ni JSON-RPC. Il ne reste que ce qu'une session comprend
toujours — un clavier et une souris.

POURQUOI UINPUT, ET RIEN D'AUTRE.
- xdotool et XTEST parlent à un serveur X : sous Wayland (la session kiosque comme le
  bureau d'Ubuntu), ils n'atteignent que les fenêtres XWayland, donc ni le compositeur
  ni Chrome lancé en --ozone-platform=wayland.
- Le portail RemoteDesktop (libei) est la voie « officielle », mais il demande un
  consentement À L'ÉCRAN à chaque session : sur une TV sans clavier, personne ne peut
  cliquer « Autoriser ». Le moyen de piloter ne peut pas exiger d'être déjà piloté.
- /dev/uinput crée un périphérique au niveau du noyau : libinput le voit comme un
  clavier USB de plus, quel que soit le compositeur. Aucune dépendance : trois ioctl et
  des structures input_event écrites à la main (fcntl + struct).

CE QUE ÇA COÛTE. Un périphérique noyau ne sait pas À QUI il parle : ses frappes vont à
ce qui est au premier plan, écran de connexion et écran verrouillé compris. D'où
`session_pilotable` (logind), consulté avant d'ouvrir et pendant toute la durée
d'ouverture, et un périphérique qui n'existe QUE pendant qu'un téléphone autorisé s'en
sert : fermé, plus rien ne peut être injecté, par personne.

UINPUT ENVOIE DES TOUCHES, PAS DES CARACTÈRES. KEY_A est « la touche à droite de
Verr. Maj » : sur un HUB en AZERTY elle écrit « q ». Le texte passe donc par une table
de la disposition active de la session (`lire_disposition`, `frappes_pour`) ; ce qui
n'y figure pas n'est jamais tapé au hasard, mais rendu à la page pour qu'elle le dise.

Bibliothèque standard seule, comme hub_telecommande.py. Se charge sans rien ouvrir.
"""

import base64
import errno
import fcntl
import hashlib
import os
import re
import struct
import time
import unicodedata

# ── Le protocole du noyau (linux/input-event-codes.h, linux/uinput.h) ─────────
EV_SYN, EV_KEY, EV_REL = 0x00, 0x01, 0x02
SYN_REPORT = 0
REL_X, REL_Y, REL_HWHEEL, REL_WHEEL, REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES = 0x00, 0x01, 0x06, 0x08, 0x0B, 0x0C
BTN_LEFT, BTN_RIGHT = 0x110, 0x111

KEY_ESC, KEY_1, KEY_2, KEY_3, KEY_4, KEY_5, KEY_6, KEY_7, KEY_8, KEY_9, KEY_0 = range(1, 12)
KEY_MINUS, KEY_EQUAL, KEY_BACKSPACE, KEY_TAB = 12, 13, 14, 15
KEY_Q, KEY_W, KEY_E, KEY_R, KEY_T, KEY_Y, KEY_U, KEY_I, KEY_O, KEY_P = range(16, 26)
KEY_LEFTBRACE, KEY_RIGHTBRACE, KEY_ENTER = 26, 27, 28
KEY_A, KEY_S, KEY_D, KEY_F, KEY_G, KEY_H, KEY_J, KEY_K, KEY_L = range(30, 39)
KEY_SEMICOLON, KEY_APOSTROPHE, KEY_GRAVE, KEY_LEFTSHIFT, KEY_BACKSLASH = 39, 40, 41, 42, 43
KEY_Z, KEY_X, KEY_C, KEY_V, KEY_B, KEY_N, KEY_M = range(44, 51)
KEY_COMMA, KEY_DOT, KEY_SLASH = 51, 52, 53
KEY_SPACE = 57
KEY_102ND = 86
KEY_RIGHTALT = 100
KEY_UP, KEY_LEFT, KEY_RIGHT, KEY_DOWN = 103, 105, 106, 108
KEY_PLAYPAUSE, KEY_REWIND, KEY_FASTFORWARD = 164, 168, 208

# _IOW('U', n, int), _IOW('U', 3, struct uinput_setup), _IO('U', n)
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT = 0x40045564, 0x40045565, 0x40045566
UI_DEV_SETUP, UI_DEV_CREATE, UI_DEV_DESTROY = 0x405C5503, 0x5501, 0x5502
BUS_VIRTUAL = 0x06
# struct input_id { u16 bustype, vendor, product, version } ; char name[80] ; u32 ff_effects_max
FORMAT_SETUP = "HHHH80sI"
# struct input_event { struct timeval ; u16 type ; u16 code ; s32 value } — en format
# natif : 24 octets sur le HUB (x86-64). L'horodatage reste à zéro, le noyau le pose.
FORMAT_EVENEMENT = "llHHi"
NOM_PERIPHERIQUE = b"HUB telecommande (clavier et souris virtuels)"

# Les touches nommées que la page peut demander. « retour » = Échap : c'est la touche
# que hub-web donne déjà au bouton B de la manette, celle que YouTube TV, Netflix et
# les lecteurs web prennent pour « revenir » ou « quitter le plein écran », et celle qui
# ferme un menu sur le bureau. Alt+Gauche (précédent du navigateur) ferait sortir d'un
# service en plein écran vers sa page de connexion — et ce serait une combinaison.
TOUCHES_NOMMEES = {
    "haut": KEY_UP, "bas": KEY_DOWN, "gauche": KEY_LEFT, "droite": KEY_RIGHT,
    "ok": KEY_ENTER, "retour": KEY_ESC, "effacer": KEY_BACKSPACE, "tab": KEY_TAB,
    "lecture": KEY_PLAYPAUSE, "recul": KEY_REWIND, "avance": KEY_FASTFORWARD,
}
BOUTONS = {"gauche": BTN_LEFT, "droite": BTN_RIGHT}
MAJ, ALTGR = KEY_LEFTSHIFT, KEY_RIGHTALT
# Niveau xkb → modificateurs tenus. Ce sont les SEULS modificateurs que le périphérique
# déclare : ni Ctrl, ni Alt, ni Super, ni touches de fonction. Le noyau jette tout
# événement d'une touche non déclarée : Ctrl+Alt+F3 (changer de console) ou Alt+Impr
# écran (SysRq) ne peuvent pas sortir d'ici, même par une erreur de ce programme. Ce
# n'est PAS une barrière contre un téléphone malveillant (la souris ouvre un terminal,
# le texte y tape ce qu'il veut) : la barrière, c'est l'appairage et l'interrupteur.
NIVEAUX = ((), (MAJ,), (ALTGR,), (MAJ, ALTGR))


class PointeurIndisponible(Exception):
    """str(erreur) est une raison courte, rendue telle quelle à la page."""


# ── Dispositions de clavier ─────────────────────────────────────────────────
# Une ligne par touche : (code, caractères du niveau 1, 2, 3, 4) ; « \0 » = niveau non
# utilisé. Recopié de xkeyboard-config (symbols/fr, symbols/us) et vérifié contre ces
# fichiers par test_pointeur.py quand ils sont là (/usr/share/X11/xkb sur le HUB).
_ = "\0"
_FR_COMMUN = (
    (KEY_1, "&1"), (KEY_2, "é2~"), (KEY_3, "\"3#"), (KEY_4, "'4{"), (KEY_5, "(5["),
    (KEY_6, "-6|"), (KEY_7, "è7"), (KEY_8, "_8\\"), (KEY_9, "ç9^"), (KEY_0, "à0@"),
    (KEY_MINUS, ")°]"), (KEY_EQUAL, "=+}"),
    (KEY_Q, "aA"), (KEY_W, "zZ"), (KEY_E, "eE€"), (KEY_R, "rR"), (KEY_T, "tT"), (KEY_Y, "yY"),
    (KEY_U, "uU"), (KEY_I, "iI"), (KEY_O, "oO"), (KEY_P, "pP"), (KEY_RIGHTBRACE, "$£"),
    (KEY_A, "qQ"), (KEY_S, "sS"), (KEY_D, "dD"), (KEY_F, "fF"), (KEY_G, "gG"), (KEY_H, "hH"),
    (KEY_J, "jJ"), (KEY_K, "kK"), (KEY_L, "lL"), (KEY_SEMICOLON, "mM"), (KEY_APOSTROPHE, "ù%"),
    (KEY_BACKSLASH, "*µ"),
    (KEY_102ND, "<>"), (KEY_Z, "wW"), (KEY_X, "xX"), (KEY_C, "cC"), (KEY_V, "vV"), (KEY_B, "bB"),
    (KEY_N, "nN"), (KEY_M, ",?"), (KEY_COMMA, ";."), (KEY_DOT, ":/"), (KEY_SLASH, "!§"),
    (KEY_SPACE, " "),
)
# Les majuscules accentuées n'existent QUE dans ces variantes (niveau 4) ; la
# disposition « fr » de base n'en a aucune, d'où les approximations de frappes_pour.
_FR_MAJUSCULES = ((KEY_2, _ * 3 + "É"), (KEY_7, _ * 3 + "È"), (KEY_9, _ * 3 + "Ç"),
                  (KEY_0, _ * 3 + "À"), (KEY_APOSTROPHE, _ * 3 + "Ù"),
                  (KEY_Z, _ * 2 + "«"), (KEY_X, _ * 2 + "»"))
_FR_BASE = ((KEY_GRAVE, "²"), (KEY_7, _ * 2 + "`"), (KEY_W, _ * 2 + "«"), (KEY_X, _ * 2 + "»"),
            (KEY_Q, _ * 2 + "æÆ"))
_FR_OSS = _FR_MAJUSCULES + ((KEY_GRAVE, "²"), (KEY_7, _ * 2 + "`"), (KEY_O, _ * 2 + "œŒ"),
                            (KEY_Q, _ * 2 + "æÆ"))
_FR_LATIN9 = _FR_MAJUSCULES + ((KEY_GRAVE, "œŒ"),)
# Touches mortes : (code, niveau) → diacritique combinant. Les lettres accentuées qui
# en sortent sont calculées (NFC), pas recopiées.
_FR_MORTES = ((KEY_LEFTBRACE, 0, "̂"), (KEY_LEFTBRACE, 1, "̈"))

_US = (
    (KEY_GRAVE, "`~"), (KEY_1, "1!"), (KEY_2, "2@"), (KEY_3, "3#"), (KEY_4, "4$"), (KEY_5, "5%"),
    (KEY_6, "6^"), (KEY_7, "7&"), (KEY_8, "8*"), (KEY_9, "9("), (KEY_0, "0)"), (KEY_MINUS, "-_"),
    (KEY_EQUAL, "=+"),
    (KEY_Q, "qQ"), (KEY_W, "wW"), (KEY_E, "eE"), (KEY_R, "rR"), (KEY_T, "tT"), (KEY_Y, "yY"),
    (KEY_U, "uU"), (KEY_I, "iI"), (KEY_O, "oO"), (KEY_P, "pP"), (KEY_LEFTBRACE, "[{"),
    (KEY_RIGHTBRACE, "]}"),
    (KEY_A, "aA"), (KEY_S, "sS"), (KEY_D, "dD"), (KEY_F, "fF"), (KEY_G, "gG"), (KEY_H, "hH"),
    (KEY_J, "jJ"), (KEY_K, "kK"), (KEY_L, "lL"), (KEY_SEMICOLON, ";:"), (KEY_APOSTROPHE, "'\""),
    (KEY_BACKSLASH, "\\|"),
    (KEY_Z, "zZ"), (KEY_X, "xX"), (KEY_C, "cC"), (KEY_V, "vV"), (KEY_B, "bB"), (KEY_N, "nN"),
    (KEY_M, "mM"), (KEY_COMMA, ",<"), (KEY_DOT, ".>"), (KEY_SLASH, "/?"), (KEY_SPACE, " "),
)

# (disposition, variante) → (lignes, touches mortes). Une variante absente d'ici n'est
# PAS devinée : bépo, AFNOR ou Dvorak déplacent les lettres, et taper « au plus proche »
# écrirait un autre mot de passe que celui qu'on lit sur le téléphone.
DISPOSITIONS = {
    ("fr", ""): (_FR_COMMUN + _FR_BASE, _FR_MORTES),
    ("fr", "oss"): (_FR_COMMUN + _FR_OSS, _FR_MORTES),
    ("fr", "latin9"): (_FR_COMMUN + _FR_LATIN9, _FR_MORTES),
    ("fr", "nodeadkeys"): (_FR_COMMUN + _FR_BASE, ()),
    ("fr", "oss_nodeadkeys"): (_FR_COMMUN + _FR_OSS, ()),
    ("fr", "latin9_nodeadkeys"): (_FR_COMMUN + _FR_LATIN9, ()),
    ("us", ""): (_US, ()),
}

# Ce qu'un clavier de téléphone glisse dans le texte sans qu'on l'ait demandé :
# apostrophe et guillemets typographiques, tirets longs, espaces insécables.
_TYPOGRAPHIE = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-",
                "—": "-", "…": "...", " ": " ", " ": " ", " ": " "}


def table_de(disposition):
    """{caractère: [(modificateurs, code), …]} pour une disposition connue, sinon None."""
    connue = DISPOSITIONS.get(tuple(disposition or ()))
    if connue is None:
        return None
    lignes, mortes = connue
    table = {}
    for code, niveaux in lignes:
        for niveau, caractere in enumerate(niveaux):
            if caractere != _:
                table.setdefault(caractere, [(NIVEAUX[niveau], code)])
    for code, niveau, combinant in mortes:
        for lettre in "aeiouyAEIOUY":
            compose = unicodedata.normalize("NFC", lettre + combinant)
            if len(compose) == 1 and lettre in table:
                table.setdefault(compose, [(NIVEAUX[niveau], code)] + table[lettre])
    table["\n"] = [((), KEY_ENTER)]
    return table


def frappes_pour(texte, disposition):
    """(frappes, approximations, ignores) ; frappes = [(modificateurs, code), …].

    Rien n'est tapé « à peu près » en silence. Un caractère absent de la disposition
    est d'abord cherché sans son accent (« É » → « E » sur un clavier qui n'a pas de É) et
    noté dans `approximations` ; sinon il est laissé de côté et noté dans `ignores`.
    La page affiche les deux. Lève ValueError si la disposition n'est pas couverte.
    """
    table = table_de(disposition)
    if table is None:
        raise ValueError("disposition-non-couverte")
    frappes, approximations, ignores = [], [], []
    for caractere in unicodedata.normalize("NFC", texte):
        for c in _TYPOGRAPHIE.get(caractere, caractere):
            if c in table:
                frappes += table[c]
                continue
            nu = unicodedata.normalize("NFD", c)[0]
            if nu != c and nu in table:
                frappes += table[nu]
                approximations.append(f"{c}→{nu}")
            else:
                ignores.append(c)
    return frappes, approximations, ignores


_SOURCE_XKB = re.compile(r"\(\s*'(\w+)'\s*,\s*'([^']*)'\s*\)")


def _sources(texte):
    return [(nature, nom) for nature, nom in _SOURCE_XKB.findall(texte or "")]


def lire_disposition(lancer, fichier_systeme="/etc/default/keyboard"):
    """(disposition, variante) de la session, par exemple ("fr", "oss"), ou None.

    GNOME (bureau et kiosque) applique à TOUS les claviers la source d'entrée courante :
    la première de mru-sources si elle figure dans sources, sinon la première de
    sources. Liste vide (cas d'un compte jamais passé par les réglages) : il retombe sur
    la disposition du système, celle de /etc/default/keyboard — on fait pareil. Une
    source « ibus » (saisie du japonais…) n'est pas une table de touches : None.
    """
    def lire(cle):
        r = lancer(["gsettings", "get", "org.gnome.desktop.input-sources", cle])
        return _sources(getattr(r, "stdout", "")) if r is not None and getattr(r, "returncode", 1) == 0 else []

    sources = lire("sources")
    if sources:
        courante = next((s for s in lire("mru-sources") if s in sources), sources[0])
        if courante[0] != "xkb":
            return None
        disposition, _plus, variante = courante[1].partition("+")
        return disposition, variante
    try:
        with open(fichier_systeme, encoding="utf-8") as f:
            lignes = dict(re.findall(r'^\s*(XKB\w+)\s*=\s*"?([^"\n]*)"?\s*$', f.read(), re.M))
    except OSError:
        return None
    disposition = (lignes.get("XKBLAYOUT") or "").split(",")[0].strip()
    variante = (lignes.get("XKBVARIANT") or "").split(",")[0].strip()
    return (disposition, variante) if disposition else None


# ── La session est-elle devant, et déverrouillée ? ──────────────────────────
def session_pilotable(lancer, uid=None):
    """(True, None), ou (False, raison) : « session-verrouillee », « session-en-arriere-plan »
    (écran de connexion, autre utilisateur, console) ou « session-inconnue ».

    Le périphérique virtuel parle à ce qui est au premier plan DU SIÈGE, pas à « notre »
    session : pendant que GDM affiche l'écran de connexion (passage du HUB au bureau) ou
    que l'écran est verrouillé, une frappe irait dans le champ du mot de passe. logind
    sait les deux (Active, LockedHint — GNOME Shell tient ce dernier à jour). Dans le
    doute, c'est non : une télécommande muette vaut mieux qu'un clavier devant GDM.
    """
    uid = str(os.getuid() if uid is None else uid)
    r = lancer(["loginctl", "list-sessions", "--no-legend"])
    if r is None or getattr(r, "returncode", 1) != 0:
        return False, "session-inconnue"
    sessions = [champs[0] for champs in (l.split() for l in (r.stdout or "").splitlines())
                if len(champs) >= 2 and champs[1] == uid]
    if not sessions:
        return False, "session-inconnue"
    r = lancer(["loginctl", "show-session", *sessions, "-p", "Active", "-p", "LockedHint",
                "-p", "Class", "-p", "Type", "-p", "Remote"])
    if r is None or getattr(r, "returncode", 1) != 0:
        return False, "session-inconnue"
    raison = "session-en-arriere-plan"
    for bloc in re.split(r"\n\s*\n", (r.stdout or "").strip()):
        p = dict(l.split("=", 1) for l in bloc.splitlines() if "=" in l)
        if p.get("Class") != "user" or p.get("Type") not in ("wayland", "x11", "mir") or p.get("Remote") == "yes":
            continue
        if p.get("Active") != "yes":
            continue
        if p.get("LockedHint") != "no":
            raison = "session-verrouillee"
            continue
        return True, None
    return False, raison


# ── Le périphérique ─────────────────────────────────────────────────────────
def _evenement(nature, code, valeur):
    return struct.pack(FORMAT_EVENEMENT, 0, 0, nature, code, valeur)


_SYN = _evenement(EV_SYN, SYN_REPORT, 0)


def touches_declarees():
    """Tout ce que le périphérique peut émettre, et rien d'autre (voir NIVEAUX)."""
    codes = set(TOUCHES_NOMMEES.values()) | {MAJ, ALTGR}
    for lignes, mortes in DISPOSITIONS.values():
        codes |= {code for code, _niveaux in lignes} | {code for code, _n, _c in mortes}
    return frozenset(codes)


class PeripheriqueVirtuel:
    """Un clavier-souris /dev/uinput. `ouvrir`, `ioctl`, `ecrire`, `fermer`, `dormir` sont
    injectables : les tests vérifient les octets écrits sans noyau Linux."""

    # Le compositeur met un instant à adopter un périphérique qui vient d'apparaître
    # (udev, puis libinput) : les événements écrits avant sont perdus sans erreur.
    DELAI_ADOPTION_S = 0.4
    # Entre deux frappes d'un texte. Sans pause, tout part dans la même milliseconde et
    # certaines applis (champs de recherche qui filtrent à chaque touche) en perdent.
    DELAI_FRAPPE_S = 0.004

    def __init__(self, chemin="/dev/uinput", ouvrir=os.open, ioctl=fcntl.ioctl, ecrire=os.write,
                 fermer=os.close, dormir=time.sleep):
        self.chemin = chemin
        self._ouvrir, self._ioctl, self._ecrire, self._fermer, self._dormir = ouvrir, ioctl, ecrire, fermer, dormir
        self._fd = None
        self._reste_molette = [0, 0]

    @property
    def ouvert(self):
        return self._fd is not None

    def ouvrir(self):
        if self._fd is not None:
            return
        try:
            fd = self._ouvrir(self.chemin, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as erreur:
            # Deux pannes qu'on sait nommer, parce qu'elles ont chacune leur remède :
            # module pas chargé (ou noyau sans uinput), groupe pas encore effectif.
            if erreur.errno in (errno.ENOENT, errno.ENODEV, errno.ENXIO):
                raise PointeurIndisponible("uinput-absent") from None
            if erreur.errno in (errno.EACCES, errno.EPERM):
                raise PointeurIndisponible("uinput-refuse") from None
            raise PointeurIndisponible("uinput-erreur") from None
        try:
            for nature in (EV_KEY, EV_REL):
                self._ioctl(fd, UI_SET_EVBIT, nature)
            for code in sorted(touches_declarees() | set(BOUTONS.values())):
                self._ioctl(fd, UI_SET_KEYBIT, code)
            for axe in (REL_X, REL_Y, REL_WHEEL, REL_HWHEEL, REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES):
                self._ioctl(fd, UI_SET_RELBIT, axe)
            self._ioctl(fd, UI_DEV_SETUP, struct.pack(FORMAT_SETUP, BUS_VIRTUAL, 0x4855, 0x4201, 1,
                                                      NOM_PERIPHERIQUE, 0))
            self._ioctl(fd, UI_DEV_CREATE)
        except OSError:
            self._fermer(fd)
            raise PointeurIndisponible("uinput-erreur") from None
        self._fd = fd
        self._reste_molette = [0, 0]
        self._dormir(self.DELAI_ADOPTION_S)

    def fermer(self):
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            self._ioctl(fd, UI_DEV_DESTROY)
        except OSError:
            pass
        self._fermer(fd)

    def _lot(self, *evenements):
        """Un lot = ses événements PUIS un EV_SYN, en une seule écriture : sans le SYN, le
        noyau garde le lot en attente et la souris ne bouge qu'au lot suivant."""
        if self._fd is None:
            raise PointeurIndisponible("uinput-ferme")
        try:
            self._ecrire(self._fd, b"".join(_evenement(*e) for e in evenements) + _SYN)
        except OSError:
            self.fermer()
            raise PointeurIndisponible("uinput-erreur") from None

    def deplacer(self, dx, dy):
        lot = [(EV_REL, axe, v) for axe, v in ((REL_X, dx), (REL_Y, dy)) if v]
        if lot:
            self._lot(*lot)

    def defiler(self, vertical, horizontal=0):
        """En 120es de cran (la « haute résolution » de libinput) : le défilement suit le
        doigt au lieu de sauter de trois lignes. REL_WHEEL part quand un cran entier est
        atteint, pour les applis qui ne lisent que lui."""
        lot = []
        for i, (fin, cran, valeur) in enumerate(((REL_WHEEL_HI_RES, REL_WHEEL, vertical),
                                                  (REL_HWHEEL_HI_RES, REL_HWHEEL, horizontal))):
            if not valeur:
                continue
            lot.append((EV_REL, fin, valeur))
            self._reste_molette[i] += valeur
            crans = int(self._reste_molette[i] / 120)
            if crans:
                self._reste_molette[i] -= crans * 120
                lot.append((EV_REL, cran, crans))
        if lot:
            self._lot(*lot)

    def clic(self, bouton="gauche"):
        code = BOUTONS[bouton]
        self._lot((EV_KEY, code, 1))
        self._lot((EV_KEY, code, 0))

    def frapper(self, code, modificateurs=()):
        """Appui puis relâcher, chacun dans son lot : dans le même, le compositeur ne
        verrait qu'un état final « touche levée »."""
        if code not in touches_declarees():
            raise ValueError(code)
        for m in modificateurs:
            self._lot((EV_KEY, m, 1))
        self._lot((EV_KEY, code, 1))
        self._lot((EV_KEY, code, 0))
        for m in reversed(modificateurs):
            self._lot((EV_KEY, m, 0))

    def taper(self, frappes, continuer=lambda: True):
        """`continuer` est consulté avant chaque caractère : un long texte s'arrête net
        quand l'écran se verrouille, au lieu de finir sa phrase dans le champ du mot de
        passe. Une frappe commencée est toujours finie (aucune touche ne reste tenue)."""
        for modificateurs, code in frappes:
            if not continuer():
                raise PointeurIndisponible("interrompu")
            self.frapper(code, modificateurs)
            self._dormir(self.DELAI_FRAPPE_S)


# ── Débit ───────────────────────────────────────────────────────────────────
class Seau:
    """Seau à jetons : `debit` par seconde, `capacite` d'avance. Un téléphone qui suit la
    page n'en voit jamais le fond ; un programme qui martèle la route est ralenti au
    rythme d'un humain au lieu de remplir la file du compositeur."""

    def __init__(self, debit, capacite, horloge=time.monotonic):
        self.debit, self.capacite, self.horloge = debit, capacite, horloge
        self._niveau, self._date = float(capacite), horloge()

    def prendre(self, n=1):
        maintenant = self.horloge()
        self._niveau = min(self.capacite, self._niveau + (maintenant - self._date) * self.debit)
        self._date = maintenant
        if n > self._niveau:
            return False
        self._niveau -= n
        return True


# ── WebSocket (RFC 6455), juste ce qu'il faut ───────────────────────────────
_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_TEXTE, OP_FIN, OP_PING, OP_PONG = 0x1, 0x8, 0x9, 0xA


class TrameRefusee(Exception):
    """code : le code de fermeture WebSocket à rendre (1002 protocole, 1003 type, 1009 taille)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def cle_acceptee(cle):
    return base64.b64encode(hashlib.sha1(cle.encode("ascii") + _GUID).digest()).decode("ascii")


def _lire(flux, n):
    octets = flux.read(n)
    if octets is None or len(octets) != n:
        raise EOFError
    return octets


def lire_trame(flux, maximum):
    """(opcode, contenu) d'une trame CLIENT. Refuse ce qu'une page honnête n'envoie pas :
    trame non masquée (la norme l'impose aux clients), fragmentée, ou plus grosse que
    `maximum` — la longueur est lue AVANT le contenu, rien de trop gros n'est alloué."""
    b0, b1 = _lire(flux, 2)
    if not b0 & 0x80 or b0 & 0x70 or not b1 & 0x80:
        raise TrameRefusee(1002)
    opcode, longueur = b0 & 0x0F, b1 & 0x7F
    if longueur == 126:
        longueur = struct.unpack("!H", _lire(flux, 2))[0]
    elif longueur == 127:
        raise TrameRefusee(1009)
    if longueur > maximum:
        raise TrameRefusee(1009)
    masque = _lire(flux, 4)
    contenu = bytes(o ^ masque[i & 3] for i, o in enumerate(_lire(flux, longueur)))
    return opcode, contenu


def trame(opcode, contenu=b""):
    """Une trame SERVEUR (jamais masquée), contenu de moins de 64 Kio."""
    n = len(contenu)
    entete = bytes([0x80 | opcode, n]) if n < 126 else bytes([0x80 | opcode, 126]) + struct.pack("!H", n)
    return entete + contenu
