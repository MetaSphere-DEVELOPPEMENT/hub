#!/usr/bin/env python3
"""Menu d'accueil du HUB : trois modes, un bouton pour éteindre.

POURQUOI UN PROGRAMME GRAPHIQUE. La première version était un script bash qui lisait
le clavier dans un terminal. Éprouvée sur Ubuntu 26.04 (Wayland seul, plus de
serveur Xorg), elle ne pouvait rien afficher : une session graphique n'a pas de
terminal. Ce menu tourne dans la session kiosque de GNOME
(gnome-kiosk-script-session), qui l'affiche en plein écran.

CE QU'IL FAIT. Il affiche les modes, attend un choix, écrit ce choix sur la sortie
standard et se termine. Il ne lance rien lui-même : c'est le script de session qui
lance le mode puis, quand le mode se termine, relance ce menu. Le retour au HUB est
donc une boucle du script, pas une fonction de ce programme.

PILOTAGE. Flèches et Entrée suffisent : c'est ce qu'envoient un clavier sans fil,
une télécommande HDMI-CEC relayée par un adaptateur, et la plupart des manettes une
fois associées. Aucun geste ne demande une souris.
"""

import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

MODES = (
    ("tv", "TV", "Kodi — films, séries, musique"),
    ("gaming", "Jeux", "Streaming de jeux"),
    ("bureau", "Bureau", "Ubuntu, pour travailler"),
    ("eteindre", "Éteindre", ""),
)

# Lisible à trois mètres : c'est une TV, pas un écran de bureau.
STYLE = b"""
window { background: #0d1117; }
.titre { color: #e6edf3; font-size: 64px; font-weight: 800; letter-spacing: 12px; }
.mode {
  background: #161b22; color: #e6edf3; border: 3px solid #30363d;
  border-radius: 10px; padding: 36px 48px; min-width: 520px;
}
.mode:focus-visible, .mode:hover { border-color: #58a6ff; background: #1f2937; }
.nom { font-size: 44px; font-weight: 700; }
.detail { font-size: 22px; color: #8b949e; }
.eteindre { background: transparent; border-color: #3a2a2a; min-width: 260px; padding: 18px 32px; }
.eteindre .nom { font-size: 26px; color: #f0a8a0; }
"""


class Menu(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="fr.boudine.HubMenu")
        self.choix = None

    def do_activate(self):
        fournisseur = Gtk.CssProvider()
        fournisseur.load_from_data(STYLE)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), fournisseur, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        fenetre = Gtk.ApplicationWindow(application=self, title="HUB")
        colonne = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28)
        colonne.set_halign(Gtk.Align.CENTER)
        colonne.set_valign(Gtk.Align.CENTER)

        titre = Gtk.Label(label="HUB")
        titre.add_css_class("titre")
        colonne.append(titre)

        premier = None
        for cle, nom, detail in MODES:
            bouton = Gtk.Button()
            bouton.add_css_class("mode")
            if cle == "eteindre":
                bouton.add_css_class("eteindre")
                bouton.set_halign(Gtk.Align.CENTER)
            contenu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            etiquette = Gtk.Label(label=nom, xalign=0)
            etiquette.add_css_class("nom")
            contenu.append(etiquette)
            if detail:
                sous = Gtk.Label(label=detail, xalign=0)
                sous.add_css_class("detail")
                contenu.append(sous)
            bouton.set_child(contenu)
            bouton.connect("clicked", self.choisir, cle)
            colonne.append(bouton)
            premier = premier or bouton

        fenetre.set_child(colonne)
        fenetre.fullscreen()
        fenetre.present()
        # Le focus sur le premier mode : sans lui, Entrée ne ferait rien au démarrage
        # et on croirait le menu figé.
        premier.grab_focus()

    def choisir(self, _bouton, cle):
        self.choix = cle
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
