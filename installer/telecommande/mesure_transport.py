#!/usr/bin/env python3
"""Mesure du transport de la souris : une requête https par événement, ou un WebSocket.

    python3 installer/telecommande/mesure_transport.py [--json]

POURQUOI CE FICHIER. « Le WebSocket est plus fluide » est une croyance tant qu'on ne l'a
pas chiffrée (CLAUDE.md : ce qu'on mesure plutôt que de le croire). Ce script lance le
vrai service sur 127.0.0.1 (http + https, autorité locale jetable, faux /dev/uinput, faux
logind) et chronomètre, du point de vue d'un client :
  1. l'ancien chemin — un POST /api/commande par événement, en https, une connexion
     par requête (le service répond en HTTP/1.0 et ferme : c'est ce que fait un
     navigateur, poignée de main TLS comprise) ;
  2. le même en http, pour isoler le coût du TLS ;
  3. le WebSocket : aller-retour d'un battement, délai entre l'envoi d'un déplacement et
     son écriture dans le périphérique, à 60 messages par seconde (une page, une image)
     puis sans retenue (débit maximal du service, limites de débit levées pour la mesure).

CE QUE ÇA NE MESURE PAS : le wifi, le téléphone, le compositeur. Sur la boucle locale, le
client et le serveur partagent un seul interpréteur Python : les chiffres sont un
plancher du coût du PROTOCOLE, pas la latence ressentie dans le salon. Pas installé.
"""

import http.client
import json
import os
import socket
import ssl
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_telecommande as T  # noqa: E402
from banc_essai import ClientWS, FauxNoyau  # noqa: E402


class NoyauChronometre(FauxNoyau):
    def __init__(self):
        super().__init__()
        self.dates = []

    def ecrire(self, fd, octets):
        self.dates.append(time.perf_counter())
        return len(octets)


def resume(durees_s):
    ms = sorted(d * 1000 for d in durees_s)
    return {"n": len(ms), "mediane_ms": round(statistics.median(ms), 2),
            "p95_ms": round(ms[int(len(ms) * 0.95) - 1], 2), "max_ms": round(ms[-1], 2)}


def main():
    # Les limites de débit protègent le HUB ; ici elles fausseraient la mesure du transport.
    T.MOUVEMENTS_PAR_S = T.FRAPPES_PAR_S = 10 ** 9
    T.MOUVEMENTS_RESERVE = T.FRAPPES_RESERVE = 10 ** 9
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        chemins = {"etat": d / "run/telecommande.json", "appairage": d / "run/appairage",
                   "socket": d / "run/menu.sock", "jetons": d / "config/jetons.json", "photos": d / "photos",
                   "tls": d / "config/tls", "reglages": d / "config/reglages.json"}

        def lancer(commande, **_kw):
            sortie = ""
            if "list-sessions" in commande:
                sortie = f"2 {os.getuid()} salon seat0 tty2\n"
            elif "show-session" in commande:
                sortie = "Active=yes\nLockedHint=no\nClass=user\nType=wayland\nRemote=no\n"
            elif "gsettings" in commande:
                sortie = "[('xkb', 'fr+oss')]"
            return subprocess.CompletedProcess(commande, 0, stdout=sortie, stderr="")

        routeur = T.Routeur(chemins["socket"], executer=lancer, kodi_http=None,
                            processus=lambda noms: [1] if "gnome-shell" in noms else [], web_en_cours=lambda: False)
        tls = T.AutoriteLocale(chemins["tls"])
        service = T.Service(chemins, routeur=routeur, tls=tls)
        noyau = NoyauChronometre()
        service.pointeur = T.Pointeur(service, fabrique=noyau.peripherique, lancer=lancer, acces=lambda: None)
        chemins["reglages"].parent.mkdir(parents=True, exist_ok=True)
        chemins["reglages"].write_text(json.dumps({"systeme": {"telecommandeSouris": True}}))
        service.fenetre.ouvrir()
        serveurs = T.demarrer_ecoutes(service, "127.0.0.1", 0, 0, sondage=0.05)
        http_port, https_port = (s.server_address[1] for s in serveurs)
        contexte = ssl.create_default_context(cafile=str(tls.racine_crt))

        def requete(methode, chemin, corps, jeton=None, securise=True):
            c = (http.client.HTTPSConnection("127.0.0.1", https_port, timeout=5, context=contexte) if securise
                 else http.client.HTTPConnection("127.0.0.1", http_port, timeout=5))
            h = {"Content-Type": "application/json"}
            if jeton:
                h["Authorization"] = f"Bearer {jeton}"
            c.request(methode, chemin, body=json.dumps(corps).encode(), headers=h)
            r = c.getresponse()
            rendu = json.loads(r.read())
            c.close()
            return rendu

        jeton = requete("POST", "/api/appairer", {"code": service.appairage.code, "nom": "mesure"})["jeton"]
        resultats = {"python": sys.version.split()[0], "openssl": ssl.OPENSSL_VERSION}

        # 1 et 2 : une requête par événement.
        for nom, securise in (("post_https", True), ("post_http", False)):
            if not securise:
                # La souris est refusée en http : on mesure le même aller-retour sur le volume.
                corps = {"nom": "volume:+"}
            else:
                corps = {"nom": "droite"}
            durees = []
            for _ in range(200):
                t0 = time.perf_counter()
                r = requete("POST", "/api/commande", corps, jeton, securise)
                durees.append(time.perf_counter() - t0)
                assert r["ok"], r
            resultats[nom] = {**resume(durees), "par_seconde": round(len(durees) / sum(durees))}

        # 3 : le WebSocket.
        ticket = requete("POST", "/api/pointeur/session", {}, jeton)["ticket"]
        brut = contexte.wrap_socket(socket.create_connection(("127.0.0.1", https_port), timeout=5),
                                    server_hostname="127.0.0.1")
        ws = ClientWS(brut, f"127.0.0.1:{https_port}", ticket=ticket, origine=f"https://127.0.0.1:{https_port}")
        assert ws.statut == 101 and ws.recevoir()["t"] == "pret"
        durees = []
        for n in range(500):
            t0 = time.perf_counter()
            ws.envoyer({"t": "p", "n": n})
            assert ws.recevoir() == {"t": "p", "n": n}
            durees.append(time.perf_counter() - t0)
        resultats["ws_aller_retour"] = resume(durees)

        noyau.dates.clear()
        envois = []
        for _ in range(300):          # cinq secondes à 60 images par seconde
            envois.append(time.perf_counter())
            ws.envoyer({"t": "m", "x": 3, "y": -2})
            time.sleep(max(0, envois[0] + len(envois) / 60 - time.perf_counter()))
        ws.envoyer({"t": "p", "n": 0})
        ws.recevoir()
        assert len(noyau.dates) == len(envois), (len(noyau.dates), len(envois))
        resultats["ws_60_par_seconde_envoi_vers_ecriture"] = resume([e - s for s, e in zip(envois, noyau.dates)])

        noyau.dates.clear()
        t0 = time.perf_counter()
        for _ in range(5000):
            ws.envoyer({"t": "m", "x": 1, "y": 1})
        ws.envoyer({"t": "p", "n": 0})
        ws.recevoir()
        duree = time.perf_counter() - t0
        resultats["ws_debit_max"] = {"n": len(noyau.dates), "par_seconde": round(len(noyau.dates) / duree)}
        ws.fermer()
        service.pointeur.fermer("fin de la mesure")
        for s in serveurs:
            s.shutdown()
            s.server_close()

    if "--json" in sys.argv:
        print(json.dumps(resultats, indent=2, ensure_ascii=False))
        return
    print(f"Python {resultats['python']}, {resultats['openssl']}, boucle locale")
    for cle, libelle in (("post_https", "POST https, une connexion par événement"),
                         ("post_http", "POST http (sans TLS), pour comparaison"),
                         ("ws_aller_retour", "WebSocket : aller-retour d'un battement"),
                         ("ws_60_par_seconde_envoi_vers_ecriture", "WebSocket à 60/s : envoi → écriture uinput")):
        r = resultats[cle]
        debit = f", {r['par_seconde']}/s au plus" if "par_seconde" in r else ""
        print(f"  {libelle:<52} médiane {r['mediane_ms']:>6} ms   p95 {r['p95_ms']:>6} ms   max {r['max_ms']:>6} ms{debit}")
    r = resultats["ws_debit_max"]
    print(f"  {'WebSocket sans retenue':<52} {r['par_seconde']} événements/s ({r['n']} écrits)")


if __name__ == "__main__":
    main()
