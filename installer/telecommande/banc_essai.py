#!/usr/bin/env python3
"""Banc d'essai de la télécommande pour les tests navigateur (test_navigateur.mjs).

Lance le vrai service sur 127.0.0.1 (ports choisis par le noyau) avec des chemins
dans DOSSIER, et un faux socket de menu qui écrit chaque datagramme reçu, une ligne
par datagramme, dans DOSSIER/menu.txt. Écrit ensuite une ligne JSON sur la sortie
standard ({"http": port, ...}) et tourne jusqu'à ce que son entrée standard se ferme.

POURQUOI UN BANC PLUTÔT QUE LE SERVICE TEL QUEL. Le test navigateur doit lire le
code (fichier d'état), voir ce qui arrive au menu et ne rien exécuter sur la machine
(ni wpctl ni gnome-session-quit) : c'est exactement ce que remplace ce fichier, et
rien d'autre. Ce n'est pas installé sur le HUB.
"""

import base64
import json
import os
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_pointeur as P  # noqa: E402
import hub_telecommande as T  # noqa: E402


class FauxNoyau:
    """Ce que /dev/uinput verrait : les ioctl dans l'ordre, et les octets écrits."""

    def __init__(self, erreur_ouverture=None, erreur_ecriture=None, journal=None):
        self.ioctls, self.ecrits, self.fermes, self.pauses = [], [], [], []
        self.erreur_ouverture, self.erreur_ecriture = erreur_ouverture, erreur_ecriture
        # Pour les tests navigateur : chaque lot écrit, une ligne JSON, dans ce fichier.
        self.journal = journal

    def ouvrir(self, chemin, drapeaux):
        if self.erreur_ouverture:
            raise OSError(self.erreur_ouverture, os.strerror(self.erreur_ouverture))
        self.chemin, self.drapeaux = chemin, drapeaux
        return 99

    def ioctl(self, fd, requete, argument=0):
        self.ioctls.append((requete, argument))
        return 0

    def ecrire(self, fd, octets):
        if self.erreur_ecriture:
            raise OSError(self.erreur_ecriture, "écriture")
        self.ecrits.append(octets)
        if self.journal:
            with open(self.journal, "a", encoding="utf-8") as f:
                f.write(json.dumps(self.evenements()[-1]) + "\n")
        return len(octets)

    def peripherique(self):
        return P.PeripheriqueVirtuel(ouvrir=self.ouvrir, ioctl=self.ioctl, ecrire=self.ecrire,
                                     fermer=self.fermes.append, dormir=self.pauses.append)

    def evenements(self):
        """[(type, code, valeur), …] de tout ce qui a été écrit, lot par lot."""
        lots = []
        for octets in self.ecrits:
            self_taille = struct.calcsize(P.FORMAT_EVENEMENT)
            assert len(octets) % self_taille == 0, "écriture qui coupe une structure"
            lots.append([struct.unpack(P.FORMAT_EVENEMENT, octets[i:i + self_taille])[2:]
                         for i in range(0, len(octets), self_taille)])
        return lots


class ClientWS:
    """Le WebSocket vu du téléphone, pour les tests et la mesure : poignée de main telle
    que la page la fait (protocoles « hub-pointeur » + « ticket.… »), trames masquées.
    Écrit ici plutôt que pris dans une bibliothèque : le HUB n'en a aucune, et le test
    doit pouvoir envoyer aussi ce qu'une page honnête n'envoie jamais."""

    def __init__(self, connexion, hote, ticket=None, origine=None, protocoles=None, entetes=None):
        self.s = connexion
        self.code_fermeture = None
        if protocoles is None:
            protocoles = ["hub-pointeur"] + ([f"ticket.{ticket}"] if ticket else [])
        h = {"Host": hote, "Upgrade": "websocket", "Connection": "Upgrade",
             "Sec-WebSocket-Key": base64.b64encode(os.urandom(16)).decode(), "Sec-WebSocket-Version": "13"}
        if origine:
            h["Origin"] = origine
        if protocoles:
            h["Sec-WebSocket-Protocol"] = ", ".join(protocoles)
        h.update(entetes or {})
        self.s.sendall(("GET /api/pointeur HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in h.items())
                        + "\r\n").encode())
        self.f = self.s.makefile("rb")
        ligne = self.f.readline().decode("latin-1").split()
        self.statut = int(ligne[1]) if len(ligne) > 1 else 0
        self.entetes = {}
        while True:
            ligne = self.f.readline().decode("latin-1").strip()
            if not ligne:
                break
            cle, _sep, valeur = ligne.partition(":")
            self.entetes[cle.strip().lower()] = valeur.strip()
        self.corps = None
        if self.statut != 101:
            self.corps = self.f.read(int(self.entetes.get("content-length") or 0))

    def envoyer_brut(self, contenu, opcode=1):
        masque = os.urandom(4)
        n = len(contenu)
        entete = bytes([0x80 | opcode]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack("!H", n))
        self.s.sendall(entete + masque + bytes(o ^ masque[i & 3] for i, o in enumerate(contenu)))

    def envoyer(self, message):
        self.envoyer_brut(json.dumps(message, ensure_ascii=False).encode("utf-8"))

    def recevoir(self, delai=5):
        """Le prochain message (dict), ou None quand le serveur a fermé."""
        self.s.settimeout(delai)
        while True:
            try:
                b0, b1 = self.f.read(2)
            except (ValueError, OSError):
                return None
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self.f.read(2))[0]
            contenu = self.f.read(n)
            if b0 & 0x0F == 0x8:
                self.code_fermeture = struct.unpack("!H", contenu[:2])[0] if len(contenu) >= 2 else None
                return None
            if b0 & 0x0F == 0x1:
                return json.loads(contenu)

    def fermer(self):
        try:
            self.envoyer_brut(struct.pack("!H", 1000), opcode=8)
        except OSError:
            pass
        try:
            self.s.close()
        except OSError:
            pass


class DicteurParEnergie:
    """Sans Vosk sur la machine : « télé » si le son reçu contient de la voix (énergie
    au-dessus du bruit), rien sinon. Suffit à prouver que la page a capturé, rééchan-
    tillonné et envoyé un vrai son ; la reconnaissance elle-même est testée à part
    (test_telecommande.py, TravailleurDictee, avec le vrai modèle)."""

    def __init__(self, dossier):
        self.dossier = dossier

    def reconnaitre(self, pcm, langue):
        echantillons = memoryview(pcm).cast("h")
        energie = max((abs(x) for x in echantillons), default=0)
        (self.dossier / "dictee.json").write_text(json.dumps(
            {"secondes": len(echantillons) / 16000, "crete": energie, "langue": langue}))
        return "télé" if energie > 3000 else ""

    def entretien(self):
        pass

    def arreter(self):
        pass


def choisir_dicteur(dossier):
    if os.environ.get("HUB_VOIX_PYTHON") and os.environ.get("HUB_VOIX_MODELES"):
        return T.Dicteur(script=Path(__file__).resolve().parent.parent / "voix" / "hub-voix.py")
    return DicteurParEnergie(dossier)


def main():
    dossier = Path(sys.argv[1])
    options = set(sys.argv[2:])
    chemins = {
        "etat": dossier / "run" / "telecommande.json",
        "appairage": dossier / "run" / "telecommande-appairage",
        "socket": dossier / "run" / "menu.sock",
        "jetons": dossier / "config" / "telecommande-jetons.json",
        "photos": dossier / "photos",
        "reglages": dossier / "config" / "reglages.json",
        "tls": dossier / "config" / "telecommande-tls",
    }
    chemins["socket"].parent.mkdir(parents=True, exist_ok=True)
    menu = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    menu.bind(str(chemins["socket"]))
    journal_menu = dossier / "menu.txt"
    journal_menu.write_text("")

    def ecouter():
        while True:
            try:
                texte = menu.recv(4096).decode()
            except OSError:
                return
            with journal_menu.open("a") as f:
                f.write(texte + "\n")

    threading.Thread(target=ecouter, daemon=True).start()

    def executer(commande, **_kw):
        sortie = "Volume: 0.40\n" if "get-volume" in commande else ""
        # Un logind et un GNOME de théâtre : session active et déverrouillée (sauf si
        # DOSSIER/verrou existe), clavier français. Rien n'est lancé sur la machine.
        if "list-sessions" in commande:
            sortie = f"2 {os.getuid()} salon seat0 tty2 active no -\n"
        elif "show-session" in commande:
            verrou = "yes" if (dossier / "verrou").exists() else "no"
            sortie = f"Active=yes\nLockedHint={verrou}\nClass=user\nType=wayland\nRemote=no\n"
        elif "gsettings" in commande:
            sortie = "[('xkb', 'fr+oss')]\n"
        return subprocess.CompletedProcess(commande, 0, stdout=sortie, stderr="")

    # DOSSIER/contexte dit ce qui est « à l'écran » : menu (défaut), web, bureau, kodi.
    # Hors du menu, son socket est mis de côté, comme quand hub-menu s'est fermé.
    fichier_contexte = dossier / "contexte"

    def contexte():
        try:
            return fichier_contexte.read_text().strip() or "menu"
        except OSError:
            return "menu"

    def suivre_contexte():
        ailleurs = chemins["socket"].with_suffix(".ailleurs")
        while True:
            try:
                if contexte() != "menu" and chemins["socket"].exists():
                    chemins["socket"].rename(ailleurs)
                elif contexte() == "menu" and ailleurs.exists():
                    ailleurs.rename(chemins["socket"])
            except OSError:
                pass
            threading.Event().wait(0.05)

    threading.Thread(target=suivre_contexte, daemon=True).start()
    routeur = T.Routeur(chemins["socket"], executer=executer, kodi_http=None,
                        processus=lambda noms: [1] if contexte() == "bureau" and "gnome-shell" in noms else [],
                        web_en_cours=lambda: contexte() == "web")
    tls = T.AutoriteLocale(chemins["tls"]) if "--https" in options else None
    service = T.Service(chemins, routeur=routeur, tls=tls, dicteur=choisir_dicteur(dossier))
    # Le faux /dev/uinput : chaque lot qu'aurait reçu le noyau, une ligne de DOSSIER/pointeur.jsonl.
    noyau = FauxNoyau(journal=dossier / "pointeur.jsonl")
    service.pointeur = T.Pointeur(service, fabrique=noyau.peripherique, lancer=executer, acces=lambda: None)
    service.pointeur.PERIODE_GARDIEN_S = 0.1
    service.pointeur.DUREE_GARDE_S = 0.1
    # Le faux menu garde l'écran d'appairage affiché : il retouche la fenêtre comme le
    # vrai menu, sinon une suite de tests plus longue que la fenêtre refuserait les codes.
    def garder_fenetre_ouverte():
        while True:
            service.fenetre.ouvrir()
            threading.Event().wait(T.FENETRE_APPAIRAGE_S / 5)

    threading.Thread(target=garder_fenetre_ouverte, daemon=True).start()
    serveurs = T.demarrer_ecoutes(service, "127.0.0.1", 0, 0 if tls else None, sondage=0.05)
    ports = {"http": serveurs[0].server_address[1]}
    if len(serveurs) > 1:
        ports["https"] = serveurs[1].server_address[1]
        ports["racine"] = str(tls.racine_crt)
    print(json.dumps(ports), flush=True)
    sys.stdin.read()


if __name__ == "__main__":
    main()
