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

# Mots d'éveil proposés dans les réglages (systeme.motEveil), et ce qu'ils deviennent
# dans chaque langue. Dans chaque tuple, du plus long au plus court : « ok hub » doit
# être reconnu avant « hub », sinon le « ok » resterait en tête de la commande.
#
# POURQUOI « OK HUB » PAR DÉFAUT. Mesuré sur 4 voix françaises, 400 commandes et
# 2 904 phrases de TV (README, 15 septembre 2026) : « HUB » seul, le petit modèle le
# rend « aide », « eux », « hum » selon la voix ; précédé d'un mot qu'il connaît bien,
# l'ancre tient même quand « hub » est mal entendu. « OK HUB » et « Salut HUB » font
# jeu égal sur les commandes ; « OK HUB » réveille dix fois moins souvent sur la TV.
MOT_EVEIL_PAR_DEFAUT = "ok-hub"
MOTS_EVEIL = {
    "ok-hub": {"fr": ("okay hub", "ok hub"), "en": ("okay hub", "ok hub")},
    "salut-hub": {"fr": ("salut hub",), "en": ("hey hub",)},
    "dis-hub": {"fr": ("dis hub",), "en": ("hey hub",)},
    "hub": {"fr": ("okay hub", "ok hub", "hub"), "en": ("hey hub", "okay hub", "ok hub", "hub")},
}

# Un prénom choisi : un ou deux mots, lettres seulement (« Nestor », « Dis Nestor »).
MOTS_PRENOM_MAX = 2
LONGUEUR_PRENOM_MAX = 24

# Services de streaming et de jeu (« web:<service> », lancés par hub-web). Chaque nom
# est dans le vocabulaire des deux petits modèles, vérifié dans leur table de mots
# (Gr.fst) : youtube, netflix, twitch, arte, xbox, geforce, steam, moonlight y sont
# tels quels. « boosteroid » n'y est pas : « booster » est le mot le plus proche
# qu'il connaisse. « France TV » a ses deux formes parlées : on dit « France Télé ».
WEB_FR = {
    "youtube": ("youtube",),
    "netflix": ("netflix",),
    "primevideo": ("prime vidéo", "amazon prime", "amazon"),
    "disneyplus": ("disney plus", "disney"),
    "canalplus": ("canal plus",),
    "twitch": ("twitch",),
    "arte": ("arte",),
    "francetv": ("france télé", "france télévisions", "france tv"),
    "geforcenow": ("geforce now", "geforce", "g force now"),
    "xcloud": ("xbox", "xbox cloud"),
    "boosteroid": ("booster",),
    "steam": ("steam",),
    "moonlight": ("moonlight",),
}
WEB_EN = {
    "youtube": ("youtube",),
    "netflix": ("netflix",),
    "primevideo": ("prime video", "amazon prime", "amazon"),
    "disneyplus": ("disney plus", "disney"),
    "canalplus": ("canal plus",),
    "twitch": ("twitch",),
    "arte": ("arte",),
    "francetv": ("france tv", "france television"),
    "geforcenow": ("geforce now", "geforce", "g force now"),
    "xcloud": ("xbox", "xbox cloud"),
    "boosteroid": ("booster",),
    "steam": ("steam",),
    "moonlight": ("moonlight",),
}

# Les commandes, écrites comme le vocabulaire de Vosk les connaît (avec accents) :
# ces phrases servent aussi à construire la grammaire du reconnaisseur. Chaque mot a
# été vérifié présent dans vosk-model-small-fr-0.22 et vosk-model-small-en-us-0.15
# (un mot absent est ignoré par Vosk avec un simple avertissement : la phrase
# deviendrait fausse sans bruit).
COMMANDES = {
    "fr": {
        # « télévisions », « réglage », « paramètre » : mêmes sons que le singulier ou le
        # pluriel, et le modèle choisit l'orthographe au hasard (« hub télévisions »,
        # relevé sur le corpus du 15 septembre 2026).
        "tv": ("télé", "télévision", "télévisions", "tv", "films", "film", "kodi"),
        "gaming": ("jeux", "jeu", "jeux vidéo", "jouer"),
        "bureau": ("bureau", "ordinateur", "travailler"),
        "eteindre": ("éteins", "éteindre", "éteins le hub", "éteindre le hub", "éteins tout"),
        "reglages": ("réglages", "réglage", "paramètres", "paramètre"),
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
        **{f"web:{service}": phrases for service, phrases in WEB_FR.items()},
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
        **{f"web:{service}": phrases for service, phrases in WEB_EN.items()},
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
DESTINATIONS = ("tv", "gaming", "bureau", "reglages", "aide", "meteo", "profils") + \
    tuple(f"web:{service}" for service in WEB_FR)

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


# Jusqu'où le mot d'éveil peut être précédé de mots parasites et rester un mot
# d'éveil. Le décodeur colle volontiers « va le la » sur le souffle d'avant la parole ;
# plus loin, « hub » est dans la phrase (« retour au hub »), pas en tête.
PARASITES_AVANT_EVEIL = 3

# Mot que le petit modèle rend à la place de « HUB » : relevé sur le corpus de
# synthèse (voix siwis et tom, 13 septembre 2026), « heub » sort « aide » dans la
# majorité des phrases « HUB, <commande> ».
EVEILS_CONFONDUS = {"fr": ("aide",), "en": ()}

# Mots tolérés entre l'ancre d'un mot d'éveil à deux mots (« ok », « salut », « dis »)
# et la commande. MESURÉ : « hub » derrière l'ancre sort « aide », « hommes », « va
# hub », ou disparaît, selon la voix ; exiger « hub » exact laissait 81 % des commandes
# (« OK HUB »), en tolérer deux en fait passer 94 %, sans un seul faux positif sur les
# 2 904 phrases de TV. L'ancre seule ne suffit pas : il faut encore qu'une commande, et
# une seule, termine la phrase.
JOKER_APRES_ANCRE = 2


def nettoyer_mot_eveil(valeur):
    """Valeur de systeme.motEveil → identifiant de préréglage, prénom en minuscules, ou None.

    Un prénom : 1 ou 2 mots, lettres (accents compris), trait d'union ou apostrophe.
    Tout le reste est refusé : ce texte finit dans la grammaire du reconnaisseur.
    """
    if not isinstance(valeur, str):
        return None
    if valeur in MOTS_EVEIL:
        return valeur
    propre = " ".join(valeur.lower().split())
    mots = propre.split()
    if not mots or len(mots) > MOTS_PRENOM_MAX or len(propre) > LONGUEUR_PRENOM_MAX:
        return None
    if not all(all(c.isalpha() or c in "-'" for c in m) and any(c.isalpha() for c in m) for m in mots):
        return None
    return propre


def eveils(mot_eveil, langue):
    """Les phrases d'éveil de `mot_eveil` dans `langue`, telles que la grammaire les écrit."""
    langue = _langue(langue)
    propre = nettoyer_mot_eveil(mot_eveil)
    if propre is None:
        propre = MOT_EVEIL_PAR_DEFAUT
    if propre in MOTS_EVEIL:
        return MOTS_EVEIL[propre][langue]
    return (propre,)


def refus_mot_eveil(mot_eveil, langue, vocabulaire=None):
    """Pourquoi ce mot d'éveil ne peut pas servir (texte court), ou None s'il convient.

    `vocabulaire` : les mots du modèle (vocabulaire_vosk). Un mot absent serait ignoré
    par Vosk avec un simple avertissement, et le HUB deviendrait sourd sans dire pourquoi.
    """
    propre = nettoyer_mot_eveil(mot_eveil)
    if propre is None:
        return "forme"
    if propre in MOTS_EVEIL:
        return None
    langue = _langue(langue)
    mots = _mots(propre)
    reserves = set(MOTS_OUTILS[langue]) | {m for p in _INDEX[langue] for m in p.split()}
    if any(m in reserves for m in mots):
        # « Télé » ou « Retour » comme prénom : chaque commande réveillerait le HUB.
        return "commande"
    if vocabulaire is not None and any(m not in vocabulaire for m in propre.split()):
        return "inconnu"
    return None


def _trouver_eveil(mots, langue, phrases):
    """Indice juste après le mot d'éveil, ou None."""
    outils = MOTS_OUTILS[langue] | {"ok", "okay", "hey", INCONNU}
    for position in range(len(mots)):
        for phrase in phrases:
            attendu = _mots(phrase)
            if mots[position:position + len(attendu)] == attendu:
                return position + len(attendu)
        parasites = mots[:position + 1]
        if mots[position] not in outils or \
                sum(m != INCONNU for m in parasites) > PARASITES_AVANT_EVEIL:
            return None
    return None


def _trouver_ancre(mots, langue, phrases):
    """Indice juste après l'ancre (1er mot d'un mot d'éveil à deux mots), ou None."""
    ancres = {_mots(p)[0] for p in phrases if len(_mots(p)) >= 2}
    if not ancres:
        return None
    outils = MOTS_OUTILS[langue] | {"ok", "okay", "hey", INCONNU}
    for position, mot in enumerate(mots):
        if mot in ancres:
            return position + 1
        if mot not in outils or sum(m != INCONNU for m in mots[:position + 1]) > PARASITES_AVANT_EVEIL:
            return None
    return None


def _commande(mots, langue, phrases=()):
    """La commande contenue dans `mots`, si elle est seule et sans mot étranger."""
    connus = [m for m in mots if m != INCONNU]
    index = _INDEX[langue]
    outils = MOTS_OUTILS[langue]
    # D'abord la phrase exacte, en retirant les mots outils de tête un à un :
    # « mode sombre » est une commande, « ouvre » seul aussi — retirer « mode » ou
    # « ouvre » avant d'essayer les détruirait.
    essai = connus
    while essai:
        if " ".join(essai) in index:
            return index[" ".join(essai)]
        if essai[0] not in outils:
            break
        essai = essai[1:]

    # Sinon, chercher les commandes n'importe où, les plus longues d'abord. Retenue
    # seulement si une seule commande apparaît et que tout le reste est outil ou
    # mot d'éveil : « hub kodi réglages » est du bruit, pas un choix. Les mots de
    # remplissage de la grammaire (« pour », « maman »…) ne sont pas tolérés : ce sont
    # eux qui disent qu'une vraie phrase entoure le mot de commande.
    tolere = outils | {m for phrase in phrases for m in _mots(phrase)}
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


def _analyse_detaillee(texte, langue, mot_eveil=MOT_EVEIL_PAR_DEFAUT):
    """(éveil entendu, commande ou None, reste non vide après l'éveil)."""
    langue = _langue(langue)
    mots = _mots(texte)
    phrases = eveils(mot_eveil, langue)

    apres = _trouver_eveil(mots, langue, phrases)
    if apres is None:
        ancre = _trouver_ancre(mots, langue, phrases)
        if ancre is not None:
            connus = [m for m in mots[ancre:] if m != INCONNU]
            # « ok aide » : « OK HUB » dit seul, « hub » entendu « aide ». Ce n'est pas
            # la commande d'aide, qui se dirait « OK HUB, aide ».
            if len(connus) == 1 and connus[0] in EVEILS_CONFONDUS[langue]:
                return True, None, False
            for saut in range(JOKER_APRES_ANCRE + 1):
                commande = _commande(connus[saut:], langue, phrases)
                if commande:
                    return True, commande, True
            if 1 <= len(connus) <= JOKER_APRES_ANCRE:
                # « ok hum », « salut hommes » : l'ancre et le mot d'éveil mal entendu.
                # L'ancre toute seule ne réveille pas : « ok » est aussi la commande
                # qui valide, et doit le rester pendant l'écoute.
                return True, None, False
        if eveils(mot_eveil, langue) != MOTS_EVEIL["hub"][langue]:
            return False, _commande(mots, langue, phrases), bool(mots)
        # « aide télé » : « HUB » mal entendu, suivi d'une vraie commande. Seulement
        # avec le mot d'éveil « HUB » seul, et avec des exigences strictes, parce que
        # « Aide-moi à porter ces cartons » existe : pas de [unk] (une vraie phrase
        # autour), et la commande nue, sans mot outil — sur le corpus, « aide mode
        # bureau » venait de la TV, « aide bureau » d'un HUB.
        if len(mots) >= 2 and mots[0] in EVEILS_CONFONDUS[langue] and INCONNU not in mots:
            commande = _INDEX[langue].get(" ".join(mots[1:]))
            if commande and commande != "aide":
                return True, commande, True
        return False, _commande(mots, langue, phrases), bool(mots)

    reste = mots[apres:]
    return True, _commande(reste, langue, phrases), bool(reste)


def analyser(texte, langue, mot_eveil=MOT_EVEIL_PAR_DEFAUT):
    """(éveil entendu, commande reconnue ou None)."""
    eveil, commande, _reste = _analyse_detaillee(texte, langue, mot_eveil)
    return eveil, commande


# Mots de remplissage : les plus fréquents de la langue parlée, connus du modèle.
# Fichier remplissage-<langue>.txt à côté de ce module (voir generer-remplissage.py).
NOMBRE_REMPLISSAGE = 2000


def remplissage(langue, dossier=None, nombre=NOMBRE_REMPLISSAGE):
    """Les mots de remplissage de la langue ; [] si le fichier manque (grammaire d'avant)."""
    chemin = Path(dossier or Path(__file__).resolve().parent) / f"remplissage-{_langue(langue)}.txt"
    try:
        mots = chemin.read_text(encoding="utf-8").split()
    except OSError:
        return []
    return mots[:nombre]


def grammaire(langue, mot_eveil=MOT_EVEIL_PAR_DEFAUT, mots_remplissage=None):
    """Liste des phrases admises par le reconnaisseur Vosk, [unk] compris.

    POURQUOI UNE GRAMMAIRE. En dictée libre, le petit modèle transcrit n'importe quoi
    en mots français plausibles, et « télé » se perd parmi 300 000 mots. Restreint à
    nos phrases, il ne choisit plus qu'entre elles : c'est ce qui rend la
    reconnaissance fiable et légère sur l'i3-8100T.

    POURQUOI DES MOTS DE REMPLISSAGE. Restreint à nos seules phrases, le décodeur
    force toute parole dans nos mots : la TV qui dit « Lyon veut devenir un hub
    européen » devenait « hub de la le steam », et 60 phrases de TV sur 2 904 lançaient
    une commande (2 %, mesuré). [unk] ne suffit pas à absorber une vraie phrase.
    Avec les 2 000 mots les plus fréquents de la langue parlée à côté des commandes,
    la TV est transcrite en mots ordinaires, que l'analyse refuse : 0 sur 2 904.
    `mots_remplissage` : None = le fichier livré, [] = aucun.
    """
    langue = _langue(langue)
    commandes = []
    for commande, phrases in COMMANDES[langue].items():
        for phrase in phrases:
            commandes.append(phrase)
            if commande in DESTINATIONS:
                commandes.extend(f"{amorce} {phrase}" for amorce in AMORCES[langue])
    resultat = []
    for eveil in ("",) + eveils(mot_eveil, langue):
        if eveil:
            resultat.append(eveil)
        resultat.extend(f"{eveil} {c}".strip() for c in commandes)
    # Un mot de remplissage qui est aussi un mot de nos phrases n'y est pas ajouté seul :
    # « aide » ou « ok » isolés gardent le poids que leur donnent nos phrases.
    reserves = {m for phrase in resultat for m in phrase.split()}
    if mots_remplissage is None:
        mots_remplissage = remplissage(langue)
    resultat.extend(m for m in mots_remplissage if m not in reserves)
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

    def __init__(self, langue, delai_eveil=6.0, mot_eveil=MOT_EVEIL_PAR_DEFAUT):
        self.langue = langue
        self.delai_eveil = delai_eveil
        self.mot_eveil = mot_eveil
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
        eveil, commande, reste = _analyse_detaillee(texte, self.langue, self.mot_eveil)

        if eveil or self._attentif(maintenant):
            if commande:
                self.fin_eveil = None
                return [_entendu(texte), commande, "voix:repos"]
            if eveil and not reste:
                self.fin_eveil = maintenant + self.delai_eveil
                return [_entendu(texte), "voix:eveil"]
            if eveil:
                # Mot d'éveil suivi d'autre chose : on dit qu'on n'a pas compris, et on
                # reste à l'écoute pour que la personne n'ait qu'à répéter la commande.
                self.fin_eveil = maintenant + self.delai_eveil
                return [_entendu(texte), "voix:incompris", "voix:eveil"]
            # Déjà à l'écoute : le bruit ne prolonge pas la fenêtre, sinon une TV
            # bavarde la tiendrait ouverte indéfiniment.
            return [_entendu(texte), "voix:incompris"]

        mots = _mots(texte)
        if eveils(self.mot_eveil, self.langue) == MOTS_EVEIL["hub"][_langue(self.langue)] and \
                len(mots) == 1 and mots[0] in EVEILS_CONFONDUS[_langue(self.langue)]:
            # « aide » seul, au repos, avec le mot d'éveil « HUB » : sur le corpus, c'est
            # ainsi que sort « HUB » dit seul. Ouvrir l'écoute ne coûte rien ; « aide »
            # redit ensuite ouvre l'aide. « aide [unk] » est une phrase qui commence par « aide ».
            self.fin_eveil = maintenant + self.delai_eveil
            return [_entendu(texte), "voix:eveil"]

        # Ni éveil ni écoute en cours : c'est la TV ou une conversation. On se tait.
        return self.tic(maintenant)


def cible(commande, menu_ouvert, kodi, bureau, web=False):
    """Où va l'événement : « menu », « web », « kodi », « bureau » ou None (ignoré).

    Menu ouvert : il reçoit tout, c'est lui qui décide (et qui demande confirmation
    avant d'éteindre). Menu fermé : seul « retour » a un sens, il ferme le mode en
    cours. « eteindre » hors menu est ignoré exprès : éteindre la machine sans écran
    de confirmation parce que la TV a dit « éteins », c'est inacceptable.
    """
    if menu_ouvert:
        return "menu"
    if commande != "retour":
        return None
    # Un service web (hub-web) s'ouvre par-dessus la session du HUB : quand il tourne,
    # c'est lui qu'on regarde. Kodi ensuite : lancé depuis le bureau, c'est lui qu'on
    # regarde plutôt que le bureau derrière.
    if web:
        return "web"
    if kodi:
        return "kodi"
    if bureau:
        return "bureau"
    return None


def web_en_cours(chemin_pid, racine="/proc"):
    """Vrai si le fichier pid de hub-web désigne un hub-web vivant.

    POURQUOI VÉRIFIER LE PROCESSUS. hub-web tué net laisse son fichier pid : se fier au
    fichier seul ferait prendre chaque « retour » pour la fermeture d'un navigateur
    disparu, et Kodi ou le bureau ne se fermeraient plus jamais à la voix. Même
    vérification que `hub-web --fermer` (le pid peut avoir été repris par un autre
    programme).
    """
    try:
        pid = int(Path(chemin_pid).read_text().strip())
        ligne = Path(racine, str(pid), "cmdline").read_bytes()
    except (OSError, ValueError):
        return False
    return b"hub-web" in ligne


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


def lire_mot_eveil(chemin):
    """systeme.motEveil depuis reglages.json : identifiant, prénom nettoyé, ou le défaut."""
    try:
        donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return MOT_EVEIL_PAR_DEFAUT
    systeme = donnees.get("systeme") if isinstance(donnees, dict) else None
    valeur = systeme.get("motEveil") if isinstance(systeme, dict) else None
    return nettoyer_mot_eveil(valeur) or MOT_EVEIL_PAR_DEFAUT


def vocabulaire_vosk(chemin_gr_fst):
    """Les mots d'un petit modèle Vosk, lus dans la table de symboles de graph/Gr.fst.

    POURQUOI LIRE LE FST. Les petits modèles ne livrent pas de words.txt : la table est
    enregistrée dans Gr.fst (format binaire OpenFst : en-tête, puis table de symboles
    au nombre magique 0x7eb2fb74, chaque entrée = longueur int32, octets, clé int64).
    C'est la seule façon de savoir, avant de construire la grammaire, qu'un prénom
    choisi existe pour le modèle. Lecture en ~0,1 s (135 774 mots en français).
    Rend un ensemble vide si le fichier est illisible.
    """
    import struct
    try:
        with open(chemin_gr_fst, "rb") as f:
            def chaine():
                (n,) = struct.unpack("<i", f.read(4))
                if not 0 <= n <= 4096:
                    raise ValueError("longueur")
                return f.read(n)
            f.read(4)                    # magique du FST
            chaine(); chaine()           # type, type d'arc
            f.read(4 + 4 + 8 + 8 + 8 + 8)  # version, drapeaux, propriétés, départ, états, arcs
            if struct.unpack("<I", f.read(4))[0] != 0x7EB2FB74:
                return set()
            chaine()                     # nom de la table
            f.read(8)                    # prochaine clé libre
            (taille,) = struct.unpack("<q", f.read(8))
            mots = set()
            for _ in range(taille):
                mots.add(chaine().decode("utf-8", errors="replace"))
                f.read(8)
            return mots
    except (OSError, ValueError, struct.error):
        return set()


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
