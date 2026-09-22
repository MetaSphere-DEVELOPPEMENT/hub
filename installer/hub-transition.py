#!/usr/bin/env python3
"""Écran d'attente plein écran pendant une bascule de session — /usr/local/bin/hub-transition

    hub-transition [--titre TEXTE] [--detail TEXTE] [--accent R,V,B]

POURQUOI CE PROGRAMME EXISTE. Passer au bureau ferme la session du HUB : le menu
disparaît, puis GDM reconnecte et GNOME démarre. Entre les deux, la TV reste noire
plusieurs secondes sans rien dire, et l'utilisateur croit que la machine a planté
(défaut signalé en usage réel).

Le menu ne peut pas tenir cet écran lui-même : gnome-kiosk-script lit son choix par
substitution de commande, `sortie=$(hub-menu)`, et le shell ATTEND LA FIN DU
PROCESSUS, pas seulement la fermeture de sa sortie standard (vérifié : fermer le
descripteur 1 ne débloque pas le shell). Le menu doit donc mourir avant que la suite
s'exécute — d'où un programme distinct, lancé par hub-vers-bureau, qui prend l'écran
juste après et le garde jusqu'à ce que la session soit démontée.

CE QU'IL NE PEUT PAS COUVRIR. Une fois la session fermée, plus aucun client ne peut
dessiner : le temps de GDM puis du démarrage de GNOME reste hors de notre portée.
Ce programme couvre la première partie (habillage, choix de session, démontage), et
le fond du bureau est posé AVANT la déconnexion pour que la reprise soit déjà aux
couleurs du HUB plutôt qu'un noir brut.

Il ne dépend que de GTK 4, déjà requis par le menu : une dépendance de plus serait
une raison de plus de laisser la TV sur un écran noir.
"""

import sys

TITRE_DEFAUT = "Ouverture du bureau…"
DETAIL_DEFAUT = "Le HUB revient en fermant la session du bureau."
# Ambre du mode Bureau, repris du menu (COULEURS_MODE.bureau dans menu/hub.js) : la
# carte qu'on vient de presser et cet écran portent la même couleur.
ACCENT_DEFAUT = (255, 181, 71)
FOND = (11, 13, 18)


def analyser(arguments):
    """Analyse sans argparse : ce programme doit démarrer le plus vite possible, et
    une option mal formée ne doit jamais empêcher l'écran d'apparaître."""
    options = {"titre": TITRE_DEFAUT, "detail": DETAIL_DEFAUT, "accent": ACCENT_DEFAUT}
    attendus = {"--titre": "titre", "--detail": "detail", "--accent": "accent"}
    i = 0
    while i < len(arguments) - 1:
        cle = attendus.get(arguments[i])
        if cle:
            valeur = arguments[i + 1]
            if cle == "accent":
                valeur = couleur(valeur) or options["accent"]
            options[cle] = valeur
            i += 2
        else:
            i += 1
    return options


def couleur(texte):
    """« 255,181,71 » ou « #ffb547 » → (255, 181, 71). None si illisible : l'appelant
    garde alors l'ambre par défaut plutôt que d'échouer."""
    texte = (texte or "").strip()
    if texte.startswith("#"):
        texte = texte[1:]
        if len(texte) == 6:
            try:
                return tuple(int(texte[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                return None
        return None
    morceaux = texte.split(",")
    if len(morceaux) != 3:
        return None
    try:
        valeurs = [int(m) for m in morceaux]
    except ValueError:
        return None
    return tuple(valeurs) if all(0 <= v <= 255 for v in valeurs) else None


def css(accent):
    r, v, b = accent
    fr, fv, fb = FOND
    return f"""
    window, .fond {{ background-color: rgb({fr},{fv},{fb}); }}
    .titre {{ color: #f2f4f8; font-size: 34pt; font-weight: 300; }}
    .detail {{ color: rgba(242,244,248,.55); font-size: 15pt; }}
    .pastille {{
      background-color: rgb({r},{v},{b});
      border-radius: 999px;
      min-width: 14px; min-height: 14px;
    }}
    """.encode("utf-8")


def lancer(arguments=None):
    options = analyser(arguments if arguments is not None else sys.argv[1:])

    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, GLib, Gtk

    class Transition(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="fr.boudine.HubTransition")
            self.pastilles = []
            self.pas = 0

        def do_activate(self):
            fenetre = Gtk.ApplicationWindow(application=self, title="HUB")
            fenetre.set_child(self.contenu())
            fenetre.fullscreen()
            fenetre.present()
            # Trois pastilles qui respirent à tour de rôle : une animation sobre, sans
            # barre de progression — nous ne savons pas combien de temps ça prendra, et
            # une barre qui ment est pire que pas de barre.
            GLib.timeout_add(380, self.battre)

        def contenu(self):
            fournisseur = Gtk.CssProvider()
            fournisseur.load_from_data(css(options["accent"]))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), fournisseur, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

            colonne = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
            colonne.add_css_class("fond")
            colonne.set_halign(Gtk.Align.CENTER)
            colonne.set_valign(Gtk.Align.CENTER)

            titre = Gtk.Label(label=options["titre"])
            titre.add_css_class("titre")
            colonne.append(titre)

            detail = Gtk.Label(label=options["detail"])
            detail.add_css_class("detail")
            detail.set_wrap(True)
            detail.set_justify(Gtk.Justification.CENTER)
            colonne.append(detail)

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

    return Transition().run([])


if __name__ == "__main__":
    sys.exit(lancer())
