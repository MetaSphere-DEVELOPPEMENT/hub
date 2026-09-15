"""Ce que hub-web décide sans navigateur : liste blanche, profils, arguments, script.

    python3 -m unittest discover -s tests

Le lancement réel (Chrome, tuyau DevTools, F12) est éprouvé par `hub-web --essai`,
qui ouvre une petite fenêtre deux secondes ; ce test le lance seulement si
HUB_ESSAI_NAVIGATEUR=1, pour ne pas ouvrir de fenêtre à chaque passage des tests.
"""

import importlib.machinery
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
_chargeur = importlib.machinery.SourceFileLoader("hub_web", str(RACINE / "installer" / "hub-web"))
_spec = importlib.util.spec_from_loader("hub_web", _chargeur)
hub_web = importlib.util.module_from_spec(_spec)
_chargeur.exec_module(hub_web)


class ListeBlanche(unittest.TestCase):
    def test_services_connus_seulement(self):
        self.assertEqual(hub_web.service("netflix")["url"], "https://www.netflix.com/browse")
        for mauvais in ("https://exemple.org", "../netflix", "", None, "NETFLIX", "netflix\nsteam", 42):
            self.assertIsNone(hub_web.service(mauvais), mauvais)

    def test_toutes_les_adresses_sont_en_https(self):
        for ident, fiche in hub_web.SERVICES.items():
            self.assertIn(fiche["categorie"], ("streaming", "jeux"), ident)
            self.assertTrue(re.match(r"^[a-z0-9]{1,24}$", ident), ident)
            if "url" in fiche:
                self.assertTrue(fiche["url"].startswith("https://"), ident)
            else:
                self.assertIn("appli", fiche, f"{ident} n'a ni page ni appli")

    def test_service_inconnu_refuse_avant_tout_lancement(self):
        r = subprocess.run([sys.executable, RACINE / "installer" / "hub-web", "https://exemple.org"],
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 2)
        self.assertIn("service inconnu", r.stderr)

    def test_essai_n_ouvre_que_du_local(self):
        for bonne in ("file:///tmp/a.html", "http://127.0.0.1:8000/", "http://localhost/x", "data:text/html,<p>"):
            self.assertTrue(hub_web.url_locale(bonne), bonne)
        for mauvaise in ("https://netflix.com", "http://localhost.exemple.org/", "http://127.0.0.1.nip.io/",
                         "javascript:alert(1)", "file://serveur/partage", None):
            self.assertFalse(hub_web.url_locale(mauvaise), mauvaise)
        r = subprocess.run([sys.executable, RACINE / "installer" / "hub-web", "--essai", "https://exemple.org"],
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 2)

    def test_memes_services_que_le_menu_et_le_protocole(self):
        # Le menu (hub.js) dessine les tuiles, hub-menu.py relaie la voix : un service
        # ajouté ici sans eux serait injoignable, ou l'inverse une tuile qui ne lance rien.
        source = (RACINE / "installer" / "menu" / "hub.js").read_text(encoding="utf-8")
        bloc = source[source.index("const SERVICES = ["):]
        bloc = bloc[:bloc.index("];")]
        self.assertEqual(set(re.findall(r'\bid: "([a-z0-9]+)"', bloc)), set(hub_web.SERVICES))
        categories = dict(re.findall(r'\bid: "([a-z0-9]+)", categorie: "([a-z]+)"', bloc))
        self.assertEqual(categories, {i: f["categorie"] for i, f in hub_web.SERVICES.items()})
        spec = importlib.util.spec_from_file_location("hub_menu_services", RACINE / "installer" / "hub-menu.py")
        menu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(menu)
        self.assertEqual({c[4:] for c in menu.COMMANDES if c.startswith("web:")}, set(hub_web.SERVICES))


class Profils(unittest.TestCase):
    def test_profil_actif_et_langue(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "reglages.json"
            f.write_text(json.dumps({"profilActif": "alix", "profils": [{"id": "samuel"}, {"id": "alix", "langue": "en"}]}))
            self.assertEqual(hub_web.lire_profil(f), ("alix", "en"))

    def test_reglages_absents_ou_hostiles(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "reglages.json"
            self.assertEqual(hub_web.lire_profil(f), ("defaut", "fr"))
            f.write_text(json.dumps({"profilActif": "../../etc", "profils": [{"id": "../../etc"}]}))
            self.assertEqual(hub_web.lire_profil(f)[0], "defaut")
            f.write_text("[1, 2")
            self.assertEqual(hub_web.lire_profil(f), ("defaut", "fr"))

    def test_un_dossier_de_navigateur_par_profil(self):
        ancien = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = "/donnees"
        try:
            self.assertEqual(hub_web.dossier_profil("samuel"), Path("/donnees/hub/navigateur/samuel"))
            self.assertNotEqual(hub_web.dossier_profil("samuel"), hub_web.dossier_profil("alix"))
            self.assertEqual(hub_web.dossier_profil("../samuel"), Path("/donnees/hub/navigateur/defaut"))
        finally:
            if ancien is None:
                os.environ.pop("XDG_DATA_HOME")
            else:
                os.environ["XDG_DATA_HOME"] = ancien


class Disponibles(unittest.TestCase):
    def test_sans_navigateur_ni_appli_rien_n_est_propose(self):
        d = hub_web.disponibles(which=lambda nom: None, flatpak=lambda i: False)
        self.assertIsNone(d["navigateur"])
        self.assertFalse(any(s["disponible"] for s in d["services"].values()))

    def test_chrome_ouvre_les_pages_steam_seulement_s_il_est_installe(self):
        chrome = lambda nom: "/usr/bin/x" if nom == "google-chrome-stable" else None
        d = hub_web.disponibles(which=chrome, flatpak=lambda i: False)
        self.assertEqual(d["navigateur"], "google-chrome-stable")
        self.assertEqual(d["services"]["netflix"], {"disponible": True, "via": "navigateur"})
        self.assertFalse(d["services"]["steam"]["disponible"])
        self.assertFalse(d["services"]["moonlight"]["disponible"])

    def test_l_appli_native_passe_devant_la_page(self):
        tout = lambda nom: f"/usr/bin/{nom}" if nom in ("google-chrome-stable", "flatpak") else None
        d = hub_web.disponibles(which=tout, flatpak=lambda i: i in ("com.nvidia.geforcenow", "com.moonlight_stream.Moonlight"))
        self.assertEqual(d["services"]["geforcenow"]["via"], "appli")
        self.assertEqual(d["services"]["moonlight"]["via"], "appli")
        self.assertEqual(hub_web.commande_appli(hub_web.SERVICES["moonlight"], tout, lambda i: True),
                         ["flatpak", "run", "com.moonlight_stream.Moonlight"])

    def test_flatpak_utilisateur_ou_systeme(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "com.nvidia.geforcenow" / "current").mkdir(parents=True)
            self.assertTrue(hub_web.flatpak_installe("com.nvidia.geforcenow", [Path(d)]))
            self.assertFalse(hub_web.flatpak_installe("com.moonlight_stream.Moonlight", [Path(d)]))


class Arguments(unittest.TestCase):
    def args(self, ident, **k):
        return hub_web.arguments_navigateur("google-chrome-stable", hub_web.SERVICES.get(ident, {}), Path("/p/samuel"), **k)

    def test_kiosque_profil_tuyau_et_page_vierge(self):
        a = self.args("netflix")
        self.assertIn("--kiosk", a)
        self.assertIn("--user-data-dir=/p/samuel", a)
        self.assertIn("--remote-debugging-pipe", a)
        self.assertIn("--password-store=basic", a)
        self.assertEqual(a[-1], "about:blank", "le service est ouvert après la pose du script de retour")
        self.assertFalse(any(x.startswith("--remote-debugging-port") for x in a), "aucun port réseau")
        self.assertFalse(any("netflix.com" in x for x in a))

    def test_vaapi_et_wayland(self):
        a = self.args("youtube")
        self.assertTrue(any(x.startswith("--enable-features=") and "AcceleratedVideoDecodeLinuxGL" in x for x in a))
        self.assertIn("--ozone-platform=wayland", a)
        self.assertNotIn("--ozone-platform=wayland", self.args("youtube", wayland=False))

    def test_agent_tv_pour_youtube_seulement(self):
        self.assertTrue(any(x.startswith("--user-agent=") and "Leanback" in x for x in self.args("youtube")))
        self.assertFalse(any(x.startswith("--user-agent=") for x in self.args("xcloud")))

    def test_essai_en_fenetre(self):
        a = self.args("netflix", essai=True)
        self.assertNotIn("--kiosk", a)
        self.assertIn("--window-size=640,360", a)


class ScriptInjecte(unittest.TestCase):
    def test_options_par_service(self):
        self.assertIn('"sansAv1": true', hub_web.script_injecte(hub_web.SERVICES["youtube"]))
        self.assertIn('"touches": false', hub_web.script_injecte(hub_web.SERVICES["geforcenow"]))
        self.assertIn("F12", hub_web.script_injecte({}))

    def test_la_page_ne_peut_demander_que_retour_ou_une_fleche(self):
        self.assertEqual(hub_web.lire_message_page('{"type":"retour"}'), {"type": "retour"})
        self.assertEqual(hub_web.lire_message_page('{"type":"touche","cle":"ArrowUp","x":1}'), {"type": "touche", "cle": "ArrowUp"})
        for brut in ('{"type":"touche","cle":"F12"}', '{"type":"touche","cle":"a"}', '{"type":"url","url":"https://x"}',
                     "pas du json", "[1]", None):
            self.assertIsNone(hub_web.lire_message_page(brut), brut)

    def test_touches_reelles(self):
        bas, haut = hub_web.evenements_touche("Enter")
        self.assertEqual((bas["type"], haut["type"]), ("rawKeyDown", "keyUp"))
        self.assertEqual(bas["windowsVirtualKeyCode"], 13)


class FauxChrome(unittest.TestCase):
    """Le tuyau DevTools avec un faux Chrome en Python : ce que hub-web lui envoie, et
    comment il réagit à un appel de la page."""

    FAUX = r"""
import json, os, sys
entree, sortie = 3, 4
def lire():
    tampon = b""
    while True:
        while b"\0" not in tampon:
            m = os.read(entree, 65536)
            if not m: return
            tampon += m
        brut, _, tampon = tampon.partition(b"\0")
        yield json.loads(brut)
def ecrire(o): os.write(sortie, json.dumps(o).encode() + b"\0")
recus = []
for m in lire():
    recus.append(m["method"])
    if m["method"] == "Target.setAutoAttach":
        ecrire({"method": "Target.attachedToTarget", "params": {"sessionId": "S1", "targetInfo": {"type": "page"}}})
    if m["method"] == "Page.navigate":
        ecrire({"method": "Runtime.bindingCalled", "sessionId": "S1", "params": {"name": "hubHub", "payload": '{"type":"touche","cle":"ArrowLeft"}'}})
        ecrire({"method": "Runtime.bindingCalled", "sessionId": "S1", "params": {"name": "hubHub", "payload": '{"type":"url","url":"https://x"}'}})
        ecrire({"method": "Runtime.bindingCalled", "sessionId": "S1", "params": {"name": "hubHub", "payload": '{"type":"retour"}'}})
    if m["method"] == "Browser.close":
        open(sys.argv[1], "w").write(json.dumps(recus))
        break
"""

    def test_page_navigue_touche_relayee_puis_retour(self):
        with tempfile.TemporaryDirectory() as d:
            faux = Path(d) / "chrome.py"
            faux.write_text(self.FAUX)
            rapport = Path(d) / "recus.json"
            processus, tuyau = hub_web.demarrer([sys.executable, str(faux), str(rapport)])
            ancien = signal.getsignal(signal.SIGTERM)
            try:
                retour = hub_web.piloter(processus, tuyau, hub_web.SERVICES["netflix"], "https://www.netflix.com/browse")
            finally:
                signal.signal(signal.SIGTERM, ancien)
            self.assertTrue(retour)
            recus = json.loads(rapport.read_text())
        self.assertLess(recus.index("Page.addScriptToEvaluateOnNewDocument"), recus.index("Page.navigate"))
        self.assertLess(recus.index("Runtime.addBinding"), recus.index("Page.navigate"))
        self.assertEqual(recus.count("Input.dispatchKeyEvent"), 2, "une flèche : appui et relâche, rien pour l'URL")
        self.assertEqual(recus[-1], "Browser.close")


class Fermer(unittest.TestCase):
    def test_signale_seulement_un_hub_web(self):
        with tempfile.TemporaryDirectory() as d:
            pid = Path(d) / "web.pid"
            self.assertFalse(hub_web.fermer_en_cours(pid))
            autre = subprocess.Popen(["sleep", "30"])
            try:
                pid.write_text(str(autre.pid))
                self.assertFalse(hub_web.fermer_en_cours(pid), "un pid recyclé par un autre programme n'est pas tué")
                self.assertIsNone(autre.poll())
            finally:
                autre.kill()
                autre.wait()
            lanceur = Path(d) / "hub-web"
            lanceur.write_text("import time\ntime.sleep(30)\n")
            vrai = subprocess.Popen([sys.executable, str(lanceur)])
            try:
                time.sleep(.2)
                pid.write_text(str(vrai.pid))
                self.assertTrue(hub_web.fermer_en_cours(pid))
                self.assertEqual(vrai.wait(timeout=5), -signal.SIGTERM)
            finally:
                if vrai.poll() is None:
                    vrai.kill()


@unittest.skipUnless(os.environ.get("HUB_ESSAI_NAVIGATEUR") == "1", "HUB_ESSAI_NAVIGATEUR=1 pour ouvrir Chrome")
class EssaiReel(unittest.TestCase):
    def test_essai_sur_une_page_locale(self):
        with tempfile.TemporaryDirectory() as d:
            page = Path(d) / "index.html"
            page.write_text("<!doctype html><title>Essai</title><h1>HUB</h1>")
            env = {**os.environ, "XDG_DATA_HOME": d}
            r = subprocess.run([sys.executable, RACINE / "installer" / "hub-web", "--essai", page.as_uri()],
                               capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("essai réussi", r.stderr)


if __name__ == "__main__":
    unittest.main()
