#!/usr/bin/env python3
"""Menu d'accueil du HUB : trois modes, un bouton pour éteindre.

POURQUOI UN PROGRAMME GRAPHIQUE. La première version était un script bash qui lisait
le clavier dans un terminal. Éprouvée sur Ubuntu 26.04 (Wayland seul, plus de
serveur Xorg), elle ne pouvait rien afficher : une session graphique n'a pas de
terminal. Ce menu tourne dans la session kiosque de GNOME
(gnome-kiosk-script-session), qui l'affiche en plein écran.

POURQUOI WEBKIT. L'interface (menu/index.html) veut du verre dépoli, un fond animé et
des cartes qui réagissent au choix. GTK n'a pas de flou d'arrière-plan ; WebKitGTK,
si. La page est locale : aucun réseau n'est nécessaire. Si WebKit manque, le menu
retombe sur des boutons GTK simples plutôt que de laisser la TV sur un écran noir.

CE QU'IL FAIT. Il affiche les modes, attend un choix, écrit ce choix sur la sortie
standard et se termine. Il ne lance rien lui-même : c'est le script de session qui
lance le mode puis, quand le mode se termine, relance ce menu. Le dernier choix est
retenu pour que le retour au menu remette la sélection là où on l'avait laissée.
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlencode

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

try:
    gi.require_version("WebKit", "6.0")
    from gi.repository import WebKit  # noqa: E402
except (ValueError, ImportError):
    WebKit = None

MODES = ("tv", "gaming", "bureau", "eteindre")
ETAT = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hub" / "dernier-choix"


def page_du_menu():
    """La page installée, ou celle du dépôt quand on lance le menu depuis les sources."""
    for chemin in (
        os.environ.get("HUB_MENU_PAGE"),
        Path(__file__).resolve().parent / "menu" / "index.html",
        "/usr/local/share/hub/menu/index.html",
    ):
        if chemin and Path(chemin).is_file():
            return Path(chemin)
    return None


def dernier_choix():
    try:
        choix = ETAT.read_text().strip()
    except OSError:
        return None
    return choix if choix in MODES else None


def retenir(choix):
    if choix == "eteindre":
        return
    try:
        ETAT.parent.mkdir(parents=True, exist_ok=True)
        ETAT.write_text(choix + "\n")
    except OSError:
        pass


class Menu(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="fr.boudine.HubMenu")
        self.choix = None

    def do_activate(self):
        fenetre = Gtk.ApplicationWindow(application=self, title="HUB")
        page = page_du_menu()
        if WebKit and page:
            fenetre.set_child(self.vue_web(page))
        else:
            fenetre.set_child(self.vue_simple())
        fenetre.fullscreen()
        fenetre.present()

    def vue_web(self, page):
        contenus = WebKit.UserContentManager()
        contenus.register_script_message_handler("hub", None)
        contenus.connect("script-message-received::hub", self.message_recu)

        vue = WebKit.WebView(user_content_manager=contenus)
        # Même encre que la page : pas d'éclair blanc avant le premier dessin.
        fond = Gdk.RGBA()
        fond.parse("#06070c")
        vue.set_background_color(fond)
        vue.connect("context-menu", lambda *_: True)
        reglages = vue.get_settings()
        reglages.set_enable_developer_extras(False)
        # Le rendu par le processeur graphique rend le verre et les animations fluides,
        # mais sans pilote 3D (machine virtuelle) il laisse l'écran gris : on ne le
        # demande que si le noyau expose un nœud de rendu.
        if not any(Path("/dev/dri").glob("renderD*")):
            reglages.set_hardware_acceleration_policy(WebKit.HardwareAccelerationPolicy.NEVER)

        dernier = dernier_choix()
        adresse = page.as_uri() + ("?" + urlencode({"dernier": dernier}) if dernier else "")
        vue.load_uri(adresse)
        vue.grab_focus()
        return vue

    def message_recu(self, _contenus, valeur):
        choix = valeur.to_string()
        if choix in MODES:
            self.choisir(None, choix)

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
        retenir(cle)
        self.quit()


def main():
    menu = Menu()
    menu.run(None)
    if menu.choix:
        print(menu.choix)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
