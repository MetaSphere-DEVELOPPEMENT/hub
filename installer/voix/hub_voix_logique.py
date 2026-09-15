"""Logique de la commande vocale du HUB : ce qu'on fait du texte reconnu.

POURQUOI UN MODULE À PART. Tout ce qui décide (mot d'éveil, synonymes, fenêtre
d'écoute, vers qui envoyer la commande) se teste sans micro, sans modèle et sans
Vosk : test_hub_voix.py le fait en une seconde. hub-voix.py ne garde que ce qui
touche au matériel — le micro, le reconnaisseur, les processus.

Aucune dépendance hors de la bibliothèque standard : ce fichier doit s'importer
partout, y compris sur une machine où Vosk n'est pas installé.
"""

import json
import os
import socket
import unicodedata
import urllib.request
from pathlib import Path

LANGUES = ("fr", "en")
LANGUE_PAR_DEFAUT = "fr"

# Taille bornée du texte renvoyé au menu : un datagramme Unix a une limite, et un
# menu n'a rien à faire d'un paragraphe de [unk].
TAILLE_MAX_ENTENDU = 200

INCONNU = "[unk]"

# Mots d'éveil, du plus long au plus court : « ok hub » doit être reconnu avant
# « hub », sinon le « ok » resterait en tête de la commande.
EVEILS = {
    "fr": ("okay hub", "ok hub", "hub"),
    "en": ("hey hub", "okay hub", "ok hub", "hub"),
}

# Les commandes, écrites comme le vocabulaire de Vosk les connaît (avec accents) :
# ces phrases servent aussi à construire la grammaire du reconnaisseur. Chaque mot a
# été vérifié présent dans vosk-model-small-fr-0.22 et vosk-model-small-en-us-0.15
# (un mot absent est ignoré par Vosk avec un simple avertissement : la phrase
# deviendrait fausse sans bruit).
COMMANDES = {
    "fr": {
        "tv": ("télé", "télévision", "tv", "films", "film", "kodi"),
        "gaming": ("jeux", "jeu", "jeux vidéo", "jouer"),
        "bureau": ("bureau", "ordinateur", "travailler"),
        "eteindre": ("éteins", "éteindre", "éteins le hub", "éteindre le hub", "éteins tout"),
        "reglages": ("réglages", "paramètres"),
        "aide": ("aide",),
        "meteo": ("météo", "la météo", "quel temps"),
        "profils": ("profils", "profil", "changer de profil", "utilisateurs"),
        "retour": ("retour", "retour au hub", "accueil", "retour à l'accueil"),
        "gauche": ("gauche", "à gauche"),
        "droite": ("droite", "à droite"),
        "haut": ("haut", "en haut"),
        "bas": ("bas", "en bas"),
        "ok": ("ok", "okay", "valide", "valider", "ouvre", "entrée"),
        "theme:clair": ("thème clair", "mode clair"),
        "theme:sombre": ("thème sombre", "mode sombre"),
    },
    "en": {
        "tv": ("tv", "television", "movies", "films", "kodi"),
        "gaming": ("games", "gaming", "play", "video games"),
        "bureau": ("desktop", "computer", "work"),
        "eteindre": ("turn off", "shut down", "power off", "turn off the hub", "shut down the hub"),
        "reglages": ("settings",),
        "aide": ("help",),
        "meteo": ("weather", "forecast"),
        "profils": ("profiles", "profile", "switch profile", "users"),
        "retour": ("back", "go back", "home", "back to the hub", "go home"),
        "gauche": ("left",),
        "droite": ("right",),
        "haut": ("up",),
        "bas": ("down",),
        "ok": ("ok", "okay", "select", "open", "enter"),
        "theme:clair": ("light theme", "light mode"),
        "theme:sombre": ("dark theme", "dark mode"),
    },
}

# « avatars » n'y figure pas exprès : ce datagramme du protocole est réservé à la
# télécommande (installer/telecommande), aucune phrase ne doit le produire.

# Les « lance la », « ouvre les » qu'on dit naturellement devant une destination.
# Ils ne sont admis dans la grammaire que devant les destinations : « lance la
# gauche » n'a pas de sens, et chaque phrase de plus est une occasion de plus pour le
# bruit de la TV de ressembler à une commande.
AMORCES = {
    "fr": ("lance", "lance la", "lance le", "lance les", "mets", "mets la", "mets le",
           "mets les", "ouvre", "ouvre la", "ouvre le", "ouvre les", "va sur"),
    "en": ("launch", "launch the", "open", "open the", "start", "start the", "go to"),
}
DESTINATIONS = ("tv", "gaming", "bureau", "reglages", "aide", "meteo", "profils")

# Petits mots qu'on retire en tête pour retrouver la commande quand la phrase n'est
# pas une forme exacte : couvre les amorces ci-dessus et les variantes d'articles
# qu'un texte libre (tests, --texte) peut contenir.
MOTS_OUTILS = {
    "fr": {"lance", "lancer", "mets", "mettre", "ouvre", "ouvrir", "va", "aller", "sur",
           "passe", "en", "mode", "la", "le", "les", "l", "a", "au", "du", "des", "de"},
    "en": {"launch", "start", "open", "go", "to", "the", "switch", "a"},
}


def _sans_accents(texte):
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


def _mots(texte):
    """Mots normalisés ; les [unk] de Vosk deviennent le jeton INCONNU."""
    texte = texte.replace(INCONNU, " \x00 ")
    texte = _sans_accents(texte.lower())
    propre = "".join(c if c.isalnum() or c == "\x00" else " " for c in texte)
    return [INCONNU if m == "\x00" else m for m in propre.split()]


def normaliser(texte):
    return " ".join(m for m in _mots(texte) if m != INCONNU)


def _langue(langue):
    return langue if langue in LANGUES else LANGUE_PAR_DEFAUT


def _index(langue):
    return {normaliser(phrase): commande
            for commande, phrases in COMMANDES[langue].items() for phrase in phrases}


_INDEX = {langue: _index(langue) for langue in LANGUES}


# Jusqu'où « hub » peut être précédé de mots parasites et rester un mot d'éveil. Le
# décodeur colle volontiers « va le la » sur le souffle d'avant la parole ;
# plus loin, « hub » est dans la phrase (« retour au hub »), pas en tête.
PARASITES_AVANT_EVEIL = 3

# Mot que le petit modèle rend à la place de « HUB » : relevé sur le corpus de
# synthèse (voix siwis et tom, 13 septembre 2026), « heub » sort « aide » dans la
# majorité des phrases « HUB, <commande> ». On ne le prend pour l'éveil que suivi
# d'une autre commande : seul, « aide » reste la commande d'aide.
EVEILS_CONFONDUS = {"fr": ("aide",), "en": ()}


def _trouver_eveil(mots, langue):
    """Indice juste après le mot d'éveil, ou None."""
    outils = MOTS_OUTILS[langue] | {"ok", "okay", "hey", INCONNU}
    for position in range(len(mots)):
        for phrase in EVEILS[langue]:
            attendu = phrase.split()
            if mots[position:position + len(attendu)] == attendu:
                return position + len(attendu)
        parasites = mots[:position + 1]
        if mots[position] not in outils or \
                sum(m != INCONNU for m in parasites) > PARASITES_AVANT_EVEIL:
            return None
    return None


def _commande(mots, langue):
    """La commande contenue dans `mots`, si elle est seule et sans mot étranger."""
    connus = [m for m in mots if m != INCONNU]
    index = _INDEX[langue]
    outils = MOTS_OUTILS[langue]
    # D'abord la phrase exacte, en retirant les mots outils de tête un à un :
    # « mode sombre » est une commande, « ouvre » seul aussi — retirer « mode » ou
    # « ouvre » avant d'essayer les détruirait.
    essai = connus
    while essai:
        if essai and " ".join(essai) in index:
            return index[" ".join(essai)]
        if essai[0] not in outils:
            break
        essai = essai[1:]

    # Sinon, chercher les commandes n'importe où, les plus longues d'abord. Retenue
    # seulement si une seule commande apparaît et que tout le reste est outil ou
    # mot d'éveil : « hub kodi réglages » est du bruit, pas un choix.
    tolere = outils | {m for phrase in EVEILS[langue] for m in phrase.split()}
    libres = [True] * len(connus)
    trouvees = set()
    longueur_max = max(len(p.split()) for p in index)
    for longueur in range(min(longueur_max, len(connus)), 0, -1):
        for i in range(len(connus) - longueur + 1):
            if all(libres[i:i + longueur]):
                commande = index.get(" ".join(connus[i:i + longueur]))
                if commande:
                    trouvees.add(commande)
                    libres[i:i + longueur] = [False] * longueur
    restes = [m for m, libre in zip(connus, libres) if libre]
    if len(trouvees) == 1 and all(m in tolere for m in restes):
        return trouvees.pop()
    return None


def _analyse_detaillee(texte, langue):
    """(éveil entendu, commande ou None, reste non vide après l'éveil)."""
    langue = _langue(langue)
    mots = _mots(texte)

    apres = _trouver_eveil(mots, langue)
    if apres is None:
        # « aide télé » : « HUB » mal entendu, suivi d'une vraie commande.
        # Exigences strictes, parce que « Aide-moi à porter ces cartons » existe : pas
        # de [unk] (une vraie phrase autour), et la commande nue, sans mot outil —
        # sur le corpus, « aide mode bureau » venait de la TV, « aide bureau » d'un HUB.
        if len(mots) >= 2 and mots[0] in EVEILS_CONFONDUS[langue] and INCONNU not in mots:
            commande = _INDEX[langue].get(" ".join(mots[1:]))
            if commande and commande != "aide":
                return True, commande, True
        return False, _commande(mots, langue), bool(mots)

    reste = mots[apres:]
    return True, _commande(reste, langue), bool(reste)


def analyser(texte, langue):
    """(éveil entendu, commande reconnue ou None)."""
    eveil, commande, _reste = _analyse_detaillee(texte, langue)
    return eveil, commande


def grammaire(langue):
    """Liste des phrases admises par le reconnaisseur Vosk, [unk] compris.

    POURQUOI UNE GRAMMAIRE. En dictée libre, le petit modèle transcrit n'importe quoi
    en mots français plausibles, et « télé » se perd parmi 300 000 mots. Restreint à
    quelques centaines de phrases, il ne choisit plus qu'entre elles ou [unk] : c'est
    ce qui rend la reconnaissance fiable et légère sur l'i3-8100T.
    """
    langue = _langue(langue)
    commandes = []
    for commande, phrases in COMMANDES[langue].items():
        for phrase in phrases:
            commandes.append(phrase)
            if commande in DESTINATIONS:
                commandes.extend(f"{amorce} {phrase}" for amorce in AMORCES[langue])
    resultat = []
    for eveil in ("",) + EVEILS[langue]:
        if eveil:
            resultat.append(eveil)
        resultat.extend(f"{eveil} {c}".strip() for c in commandes)
    resultat.append(INCONNU)
    vus = set()
    return [p for p in resultat if not (p in vus or vus.add(p))]


def _entendu(texte):
    brut = " ".join(texte.split()).encode("utf-8")[:TAILLE_MAX_ENTENDU]
    return "voix:entendu:" + brut.decode("utf-8", errors="ignore")


class Ecoute:
    """Machine à états du mot d'éveil. Reçoit le texte reconnu, rend les événements.

    Les événements sont exactement les datagrammes du protocole du menu : une commande
    (« tv », « theme:clair »…) ou un état « voix:… ». Le temps est passé en argument
    plutôt que lu à l'horloge, pour que les tests et le mode --fichier le maîtrisent.
    """

    def __init__(self, langue, delai_eveil=6.0):
        self.langue = langue
        self.delai_eveil = delai_eveil
        self.fin_eveil = None

    def _attentif(self, maintenant):
        return self.fin_eveil is not None and maintenant <= self.fin_eveil

    def tic(self, maintenant):
        if self.fin_eveil is not None and maintenant > self.fin_eveil:
            self.fin_eveil = None
            return ["voix:repos"]
        return []

    def entendre(self, texte, maintenant):
        if not _mots(texte):
            # Résultat vide : Vosk en rend sur les bruits brefs. Ce n'est pas une
            # tentative de commande, la fenêtre d'écoute reste ouverte.
            return self.tic(maintenant)
        eveil, commande, reste = _analyse_detaillee(texte, self.langue)

        if eveil or self._attentif(maintenant):
            if commande:
                self.fin_eveil = None
                return [_entendu(texte), commande, "voix:repos"]
            if eveil and not reste:
                self.fin_eveil = maintenant + self.delai_eveil
                return [_entendu(texte), "voix:eveil"]
            if eveil:
                # « HUB » suivi d'autre chose : on dit qu'on n'a pas compris, et on
                # reste à l'écoute pour que la personne n'ait qu'à répéter la commande.
                self.fin_eveil = maintenant + self.delai_eveil
                return [_entendu(texte), "voix:incompris", "voix:eveil"]
            # Déjà à l'écoute : le bruit ne prolonge pas la fenêtre, sinon une TV
            # bavarde la tiendrait ouverte indéfiniment.
            return [_entendu(texte), "voix:incompris"]

        mots = _mots(texte)
        if len(mots) == 1 and mots[0] in EVEILS_CONFONDUS[_langue(self.langue)]:
            # « aide » seul, au repos : sur le corpus, c'est ainsi que sort « HUB » dit
            # seul. Ouvrir l'écoute ne coûte rien ; « aide » redit ensuite ouvre l'aide.
            # « aide [unk] » en revanche est une phrase qui commence par « aide ».
            self.fin_eveil = maintenant + self.delai_eveil
            return [_entendu(texte), "voix:eveil"]

        # Ni éveil ni écoute en cours : c'est la TV ou une conversation. On se tait.
        return self.tic(maintenant)


def cible(commande, menu_ouvert, kodi, bureau):
    """Où va l'événement : « menu », « kodi », « bureau » ou None (ignoré).

    Menu ouvert : il reçoit tout, c'est lui qui décide (et qui demande confirmation
    avant d'éteindre). Menu fermé : seul « retour » a un sens, il ferme le mode en
    cours. « eteindre » hors menu est ignoré exprès : éteindre la machine sans écran
    de confirmation parce que la TV a dit « éteins », c'est inacceptable.
    """
    if menu_ouvert:
        return "menu"
    if commande != "retour":
        return None
    # Kodi d'abord : lancé depuis le bureau, c'est lui qu'on regarde.
    if kodi:
        return "kodi"
    if bureau:
        return "bureau"
    return None


def lire_reglages(chemin):
    """(voix active, langue) depuis reglages.json écrit par le menu.

    Tout ce qui manque ou est mal formé retombe sur les défauts (voix active,
    français) : un réglage abîmé ne doit pas rendre le HUB sourd.
    """
    voix, langue = True, LANGUE_PAR_DEFAUT
    try:
        donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return voix, langue
    if not isinstance(donnees, dict):
        return voix, langue

    systeme = donnees.get("systeme")
    if isinstance(systeme, dict) and isinstance(systeme.get("voix"), bool):
        voix = systeme["voix"]

    profils = [p for p in donnees.get("profils") or [] if isinstance(p, dict)] \
        if isinstance(donnees.get("profils"), list) else []
    actif = next((p for p in profils if p.get("id") == donnees.get("profilActif")), None)
    if actif is None and profils:
        actif = profils[0]
    if actif and actif.get("langue") in LANGUES:
        langue = actif["langue"]
    return voix, langue


def micros_pipewire(dump):
    """Noms des sources micro réelles dans la sortie de pw-dump, les meilleures d'abord.

    POURQUOI PAS « TOUTE SOURCE AUDIO ». Le M720q expose une source analogique même
    sans rien dans la prise jack (relevé du 13 septembre 2026) : l'écouter donnerait
    un faux « micro présent » et un silence éternel. La carte dit si la prise est
    occupée (EnumRoute, available « no ») : on l'écarte tant qu'elle est vide. Un
    micro USB ou Bluetooth passe devant la prise, parce que c'est lui qu'on a branché
    pour la commande vocale.
    """
    appareils = {}
    for objet in dump:
        if isinstance(objet, dict) and objet.get("type") == "PipeWire:Interface:Device":
            appareils[objet.get("id")] = objet.get("info") or {}

    trouves = []
    for objet in dump:
        if not isinstance(objet, dict) or objet.get("type") != "PipeWire:Interface:Node":
            continue
        props = (objet.get("info") or {}).get("props") or {}
        if props.get("media.class") != "Audio/Source" or not props.get("node.name"):
            continue
        appareil = appareils.get(props.get("device.id"), {})
        routes = [r for r in (appareil.get("params") or {}).get("EnumRoute") or []
                  if isinstance(r, dict) and r.get("direction") == "Input"]
        if routes and all(r.get("available") == "no" for r in routes):
            continue
        attributs = appareil.get("props") or {}
        amovible = attributs.get("device.bus") in ("usb", "bluetooth") \
            or attributs.get("device.api") == "bluez5" or props.get("device.api") == "bluez5"
        trouves.append((0 if amovible else 1, props["node.name"]))
    return [nom for _rang, nom in sorted(trouves, key=lambda t: t[0])]


def envoyer(chemin, texte):
    """Un datagramme au menu. Faux si personne n'écoute ; jamais d'exception."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.sendto(texte.encode("utf-8"), str(chemin))
        return True
    except OSError:
        return False


def quitter_kodi_tcp(hote="127.0.0.1", port=9090, delai=1.5):
    """Application.Quit par le JSON-RPC TCP de Kodi (port 9090).

    POURQUOI CE CANAL EN PREMIER. Il est actif dès que « Autoriser le contrôle à
    distance par des applications sur ce système » l'est (services.esenabled, vrai par
    défaut), n'écoute que la machine locale et ne demande aucun mot de passe —
    contrairement au serveur web, éteint par défaut et protégé par identifiants.
    """
    requete = {"jsonrpc": "2.0", "method": "Application.Quit", "id": 1}
    try:
        with socket.create_connection((hote, port), timeout=delai) as s:
            s.sendall(json.dumps(requete).encode())
            try:
                reponse = s.recv(4096)
            except socket.timeout:
                # Kodi a pu fermer sa boucle avant de répondre : la requête est partie.
                return True
        return not reponse or b'"result"' in reponse
    except OSError:
        return False


def quitter_kodi_http(url="http://127.0.0.1:8080/jsonrpc", utilisateur=None, mot_de_passe=None,
                      delai=1.5):
    """Application.Quit par le serveur web de Kodi, s'il a été activé."""
    corps = json.dumps({"jsonrpc": "2.0", "method": "Application.Quit", "id": 1}).encode()
    requete = urllib.request.Request(url, data=corps, headers={"Content-Type": "application/json"})
    if utilisateur:
        import base64
        jeton = base64.b64encode(f"{utilisateur}:{mot_de_passe or ''}".encode()).decode()
        requete.add_header("Authorization", "Basic " + jeton)
    try:
        with urllib.request.urlopen(requete, timeout=delai) as reponse:
            return reponse.status == 200
    except (OSError, ValueError):
        return False


def processus(noms, racine="/proc", uid=None):
    """PID des processus de l'utilisateur dont le nom court est dans `noms`."""
    uid = os.getuid() if uid is None else uid
    trouves = []
    try:
        entrees = os.listdir(racine)
    except OSError:
        return trouves
    for entree in entrees:
        if not entree.isdigit():
            continue
        dossier = os.path.join(racine, entree)
        try:
            if os.stat(dossier).st_uid != uid:
                continue
            with open(os.path.join(dossier, "comm"), encoding="utf-8", errors="replace") as f:
                if f.read().strip() in noms:
                    trouves.append(int(entree))
        except OSError:
            continue
    return trouves


# Noms courts (/proc/<pid>/comm, 15 caractères au plus) des binaires Kodi selon le
# fenêtrage, et du compositeur du bureau GNOME — la session kiosque, elle, tourne
# sous gnome-kiosk : sa présence ne doit pas faire croire au bureau.
NOMS_KODI = {"kodi", "kodi.bin", "kodi-wayland", "kodi-x11", "kodi-gbm"}
NOMS_BUREAU = {"gnome-shell"}
