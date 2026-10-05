#!/usr/bin/env python3
"""Écran d'attente plein écran entre deux sessions, ou quand le menu ne démarre pas.
/usr/local/bin/hub-transition

    hub-transition                      « Ouverture du bureau… », jusqu'à ce qu'on l'arrête
    hub-transition --secours SECONDES   « Le menu du HUB ne démarre pas », compte à rebours, puis se ferme
    hub-transition --titre T --detail D --accent R,V,B

POURQUOI. Passer au bureau ferme la session du HUB : le menu disparaît, puis GDM
reconnecte et GNOME démarre. Entre les deux, la TV restait noire plusieurs secondes sans
rien dire, et on croyait la machine plantée. Même chose quand le menu meurt au démarrage :
la boucle de session le relançait chaque seconde — écran noir qui clignote, sans un mot.

Le menu ne peut pas tenir cet écran lui-même : gnome-kiosk-script lit son choix par
substitution de commande, `sortie=$(hub-menu)`, et le shell attend la FIN DU PROCESSUS,
pas la fermeture de sa sortie standard (vérifié : fermer le descripteur 1 ne débloque pas
le shell). Le menu doit donc mourir avant la suite — d'où ce programme à part, lancé par
hub-vers-bureau ou par la boucle de session, qui prend l'écran juste après.

CE QU'IL NE COUVRE PAS. Une fois la session fermée, plus aucun client ne dessine : le
temps de GDM puis du démarrage de GNOME reste hors de portée. hub-vers-bureau pose le fond
du bureau AVANT la déconnexion, pour que la reprise soit déjà aux couleurs du HUB.

Trois pastilles qui respirent plutôt qu'une barre de progression : la durée dépend de GDM
et de GNOME, et une barre qui ment est pire que pas de barre. Les textes suivent la langue
du profil actif (reglages.json), comme le menu. GTK 4 seul, déjà requis par le menu ; il
n'est importé que dans lancer(), pour que le reste se teste sans écran.
"""

import json
import os
import sys
from pathlib import Path

# Couleurs du menu (COULEURS_MODE dans menu/hub.js) : la carte « Bureau » qu'on vient de
# presser et l'écran qui suit portent le même ambre ; le secours, le rouge de l'arrêt.
ACCENT_BUREAU = (255, 181, 71)
ACCENT_SECOURS = (255, 107, 107)
FOND = (11, 13, 18)
LANGUES = ("fr", "en")
TEXTES = {
    "fr": {
        "bureau": ("Ouverture du bureau…", "Le HUB revient en fermant la session du bureau."),
        "secours": ("Le menu du HUB ne démarre pas",
                    "Nouvel essai dans {s} s. Si ça continue : éteindre puis rallumer le HUB, ou relancer l'installateur."),
    },
    "en": {
        "bureau": ("Opening the desktop…", "The HUB comes back when you log out of the desktop."),
        "secours": ("The HUB menu is not starting",
                    "Trying again in {s} s. If it keeps happening: power the HUB off and on, or run the installer again."),
    },
}


def chemin_reglages():
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "hub" / "reglages.json"


def langue_du_profil(chemin):
    """La langue du profil actif, « fr » à défaut : un fichier absent ou abîmé ne doit pas
    empêcher l'écran d'apparaître."""
    try:
        donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
        actif = donnees.get("profilActif")
        for profil in donnees.get("profils") or []:
            if isinstance(profil, dict) and profil.get("id") == actif and profil.get("langue") in LANGUES:
                return profil["langue"]
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return "fr"


def textes(mode, langue, secondes=None):
    titre, detail = TEXTES.get(langue, TEXTES["fr"])[mode]
    return titre, detail.replace("{s}", str(secondes)) if secondes is not None else detail


def couleur(texte):
    """« 255,181,71 » ou « #ffb547 » → (255, 181, 71). None si illisible : l'appelant garde
    alors l'accent par défaut plutôt que d'échouer."""
    texte = (texte or "").strip()
    if texte.startswith("#"):
        texte = texte[1:]
        if len(texte) != 6:
            return None
        try:
            return tuple(int(texte[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return None
    morceaux = texte.split(",")
    if len(morceaux) != 3:
        return None
    try:
        valeurs = [int(m) for m in morceaux]
    except ValueError:
        return None
    return tuple(valeurs) if all(0 <= v <= 255 for v in valeurs) else None


def analyser(arguments, langue="fr"):
    """Analyse à la main, sans argparse : ce programme doit démarrer le plus vite possible,
    et une option mal formée ne doit jamais empêcher l'écran d'apparaître."""
    options = {"mode": "bureau", "secondes": None, "accent": ACCENT_BUREAU}
    i = 0
    while i < len(arguments):
        cle, valeur = arguments[i], arguments[i + 1] if i + 1 < len(arguments) else None
        if cle == "--secours":
            options["mode"] = "secours"
            options["accent"] = ACCENT_SECOURS
            try:
                options["secondes"] = max(1, min(int(valeur), 3600))
            except (TypeError, ValueError):
                options["secondes"] = 10
            i += 2
        elif cle in ("--titre", "--detail", "--accent") and valeur is not None:
            if cle == "--accent":
                options["accent"] = couleur(valeur) or options["accent"]
            else:
                options[cle[2:]] = valeur
            i += 2
        else:
            i += 1
    titre, detail = textes(options["mode"], langue, options["secondes"])
    options.setdefault("titre", titre)
    options.setdefault("detail", detail)
    return options


def css(accent):
    r, v, b = accent
    fr, fv, fb = FOND
    return (
        f"window, .fond {{ background-color: rgb({fr},{fv},{fb}); }}\n"
        ".titre { color: #f2f4f8; font-size: 34pt; font-weight: 300; }\n"
        ".detail { color: rgba(242,244,248,.55); font-size: 15pt; }\n"
        f".pastille {{ background-color: rgb({r},{v},{b}); border-radius: 999px; min-width: 14px; min-height: 14px; }}\n"
    )


def lancer(arguments=None):
    options = analyser(arguments if arguments is not None else sys.argv[1:], langue_du_profil(chemin_reglages()))

    import gi
    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, GLib, Gtk

    class Transition(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="fr.boudine.HubTransition")
            self.pastilles = []
            self.pas = 0
            self.reste = options["secondes"]
            self.detail = None

        def do_activate(self):
            fenetre = Gtk.ApplicationWindow(application=self, title="HUB")
            fenetre.set_child(self.contenu())
            fenetre.fullscreen()
            fenetre.present()
            GLib.timeout_add(380, self.battre)
            if self.reste is not None:
                GLib.timeout_add_seconds(1, self.decompter)

        def contenu(self):
            fournisseur = Gtk.CssProvider()
            # load_from_string depuis GTK 4.12 ; load_from_data y est déprécié mais reste le repli.
            if hasattr(fournisseur, "load_from_string"):
                fournisseur.load_from_string(css(options["accent"]))
            else:
                fournisseur.load_from_data(css(options["accent"]).encode("utf-8"))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), fournisseur, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            colonne = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
            colonne.add_css_class("fond")
            colonne.set_halign(Gtk.Align.CENTER)
            colonne.set_valign(Gtk.Align.CENTER)
            titre = Gtk.Label(label=options["titre"])
            titre.add_css_class("titre")
            colonne.append(titre)
            self.detail = Gtk.Label(label=options["detail"])
            self.detail.add_css_class("detail")
            self.detail.set_wrap(True)
            self.detail.set_justify(Gtk.Justification.CENTER)
            colonne.append(self.detail)
            rangee = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            rangee.set_halign(Gtk.Align.CENTER)
            rangee.set_margin_top(14)
            for _ in range(3):
                pastille = Gtk.Box()
                pastille.add_css_class("pastille")
                pastille.set_opacity(.25)
                rangee.append(pastille)
                self.pastilles.append(pastille)
            colonne.append(rangee)
            return colonne

        def battre(self):
            for i, pastille in enumerate(self.pastilles):
                pastille.set_opacity(1 if i == self.pas % len(self.pastilles) else .25)
            self.pas += 1
            return GLib.SOURCE_CONTINUE

        def decompter(self):
            self.reste -= 1
            if self.reste <= 0:
                self.quit()
                return GLib.SOURCE_REMOVE
            self.detail.set_label(textes(options["mode"], langue_du_profil(chemin_reglages()), self.reste)[1])
            return GLib.SOURCE_CONTINUE

    return Transition().run([])


if __name__ == "__main__":
    sys.exit(lancer())
