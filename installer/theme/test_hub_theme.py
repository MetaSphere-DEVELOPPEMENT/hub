"""Ce que hub-theme décide sans toucher à la machine : couleurs, commandes, fichiers.

    python3 -m unittest discover -s installer/theme

Aucun test n'appelle le vrai gsettings : l'exécutant est un faux qui garde les
valeurs en mémoire. Le HUB de développement est la machine de travail de
l'utilisateur, on ne change pas son bureau pour vérifier un calcul de couleur.
"""

import datetime
import importlib.machinery
import importlib.util
import json
import re
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

ICI = Path(__file__).resolve().parent
_chargeur = importlib.machinery.SourceFileLoader("hub_theme", str(ICI / "hub-theme"))
_spec = importlib.util.spec_from_loader("hub_theme", _chargeur)
ht = importlib.util.module_from_spec(_spec)
_chargeur.exec_module(ht)

HUB_JS = ICI.parent / "menu" / "hub.js"


class FauxGsettings:
    """Un dconf en mémoire. Une clé absente du dictionnaire n'existe pas, comme une
    clé d'un schéma non installé : `get` échoue."""

    def __init__(self, valeurs, plages=None):
        self.valeurs = dict(valeurs)
        self.plages = plages or {}
        self.ecrits = []

    def __call__(self, argv):
        assert argv[0] == "gsettings", argv
        action, schema, cle = argv[1], argv[2], argv[3]
        if (schema, cle) not in self.valeurs:
            return 1, ""
        if action == "get":
            return 0, self.valeurs[(schema, cle)] + "\n"
        if action == "range":
            return 0, self.plages.get((schema, cle), "type s\n")
        if action == "set":
            self.valeurs[(schema, cle)] = argv[4]
            self.ecrits.append((schema, cle, argv[4]))
            return 0, ""
        raise AssertionError(argv)


def lire_png(chemin):
    """Largeur, hauteur et pixels RVB(A) d'un PNG non entrelacé à filtre nul — ce
    que produit hub-theme. Suffit à vérifier dimensions et couleurs."""
    donnees = Path(chemin).read_bytes()
    assert donnees[:8] == b"\x89PNG\r\n\x1a\n"
    i, idat, entete = 8, b"", None
    while i < len(donnees):
        longueur, genre = struct.unpack(">I4s", donnees[i:i + 8])
        corps = donnees[i + 8:i + 8 + longueur]
        crc = struct.unpack(">I", donnees[i + 8 + longueur:i + 12 + longueur])[0]
        assert zlib.crc32(genre + corps) & 0xFFFFFFFF == crc, genre
        if genre == b"IHDR":
            entete = struct.unpack(">IIBBBBB", corps)
        elif genre == b"IDAT":
            idat += corps
        i += 12 + longueur
    largeur, hauteur, _, type_couleur, *_ = entete
    canaux = 4 if type_couleur == 6 else 3
    brut = zlib.decompress(idat)
    pas = largeur * canaux + 1
    lignes = [brut[y * pas + 1:(y + 1) * pas] for y in range(hauteur)]
    assert all(brut[y * pas] == 0 for y in range(hauteur))
    return largeur, hauteur, canaux, lignes


# ── Couleurs ──────────────────────────────────────────────────────────────
class Couleurs(unittest.TestCase):
    def test_accent_gnome_le_plus_proche_de_chaque_couleur_de_profil(self):
        attendus = {
            "turquoise": "teal", "violet": "purple", "bleu": "blue",
            "vert": "green", "rose": "pink", "corail": "orange", "ambre": "yellow",
        }
        for nom, accent in attendus.items():
            with self.subTest(nom):
                self.assertEqual(ht.accent_gnome(ht.COULEURS_PROFIL[nom]), accent)

    def test_sans_reduire_la_clarte_le_violet_partirait_vers_le_bleu(self):
        # La raison de la pondération : le violet pastel du HUB est plus clair que tous
        # les accents d'Adwaita, et cet écart-là domine si on le compte en entier.
        violet = ht.COULEURS_PROFIL["violet"]

        def brute(k):
            a, b = ht.oklab(violet), ht.oklab(ht.hex_rvb(ht.ACCENTS_GNOME[k]))
            return sum((x - y) ** 2 for x, y in zip(a, b))
        self.assertEqual(min(ht.ACCENTS_GNOME, key=brute), "blue")
        self.assertEqual(ht.accent_gnome(violet), "purple")

    def test_accent_gnome_limite_aux_valeurs_que_le_systeme_accepte(self):
        self.assertEqual(ht.accent_gnome(ht.COULEURS_PROFIL["turquoise"], permis={"blue", "green"}), "green")
        self.assertIsNone(ht.accent_gnome(ht.COULEURS_PROFIL["turquoise"], permis=set()))

    def test_couleur_estuary_la_plus_proche(self):
        attendus = {"turquoise": "teal", "violet": "violet", "vert": "green", "bleu": "midnight",
                    "rose": "rose", "ambre": "orange", "corail": "maroon"}
        for nom, estuary in attendus.items():
            with self.subTest(nom):
                self.assertEqual(ht.couleur_estuary(ht.COULEURS_PROFIL[nom]), estuary)

    def test_couleurs_estuary_lues_dans_le_skin_installe(self):
        with tempfile.TemporaryDirectory() as d:
            couleurs = Path(d) / "skin.estuary" / "colors"
            couleurs.mkdir(parents=True)
            (couleurs / "defaults.xml").write_text('<colors><color name="button_focus">FF12A0C7</color></colors>')
            (couleurs / "lime.xml").write_text('<colors><color name="button_focus">FF3EE0D0</color></colors>')
            (couleurs / "casse.xml").write_text("pas du xml")
            lues = ht.couleurs_estuary([Path(d) / "skin.estuary"])
            self.assertEqual(lues, {"SKINDEFAULT": (0x12, 0xA0, 0xC7), "lime": (0x3E, 0xE0, 0xD0)})
            self.assertEqual(ht.couleur_estuary(ht.COULEURS_PROFIL["turquoise"], lues), "lime")

    def test_sans_skin_installe_la_table_de_kodi_21_sert_de_repli(self):
        self.assertEqual(ht.couleurs_estuary([Path("/nulle/part")]), ht.ESTUARY_KODI_21)
        self.assertEqual(len(ht.ESTUARY_KODI_21), 14)

    def test_variante_yaru_existante_seulement(self):
        dispo = {"Yaru", "Yaru-dark", "Yaru-prussiangreen", "Yaru-prussiangreen-dark", "Yaru-blue"}
        self.assertEqual(ht.variante_yaru(ht.COULEURS_PROFIL["turquoise"], True, dispo), "Yaru-prussiangreen-dark")
        # Le bleu clair existe, le bleu sombre non : on ne pose jamais un thème absent.
        self.assertEqual(ht.variante_yaru(ht.COULEURS_PROFIL["bleu"], False, dispo), "Yaru-blue")
        self.assertNotEqual(ht.variante_yaru(ht.COULEURS_PROFIL["bleu"], True, dispo), "Yaru-blue-dark")
        self.assertIn(ht.variante_yaru(ht.COULEURS_PROFIL["bleu"], True, dispo), dispo)
        self.assertIsNone(ht.variante_yaru(ht.COULEURS_PROFIL["bleu"], True, set()))

    def test_variantes_yaru_exigent_theme_gtk_et_icones(self):
        with tempfile.TemporaryDirectory() as d:
            themes, icones = Path(d) / "themes", Path(d) / "icons"
            for nom in ("Yaru", "Yaru-red", "Yaru-bark"):
                (themes / nom / "gtk-3.0").mkdir(parents=True)
            for nom in ("Yaru", "Yaru-red"):
                (icones / nom).mkdir(parents=True)
                (icones / nom / "index.theme").write_text("[Icon Theme]\n")
            self.assertEqual(ht.variantes_yaru([themes], [icones]), {"Yaru", "Yaru-red"})

    def test_tables_synchronisees_avec_le_menu(self):
        """hub-theme recopie les couleurs de hub.js : un profil recoloré dans le
        menu doit l'être aussi sur le bureau et dans Kodi."""
        source = HUB_JS.read_text(encoding="utf-8")
        bloc = re.search(r"const COULEURS_PROFIL = \{(.*?)\};", source, re.S).group(1)
        js = {n: tuple(int(x) for x in v.split(",")) for n, v in re.findall(r"(\w+): \[([\d, ]+)\]", bloc)}
        self.assertEqual(js, ht.COULEURS_PROFIL)
        for fond, palette in ht.PALETTES.items():
            for theme in ("sombre", "clair"):
                motif = rf"{fond}: \{{.*?{theme}: \{{ base: \"(#[0-9a-f]+)\""
                self.assertEqual(re.search(motif, source, re.S).group(1), palette[theme]["base"], (fond, theme))


# ── Réglages et thème ─────────────────────────────────────────────────────
class Reglages(unittest.TestCase):
    def test_profil_actif_et_repli(self):
        reglages = {"profilActif": "b", "profils": [{"id": "a", "couleur": "vert"}, {"id": "b", "couleur": "rose", "fond": "ocean"}]}
        p = ht.profil_actif(reglages)
        self.assertEqual((p["couleur"], p["fond"], p["theme"]), ("rose", "ocean", "sombre"))
        self.assertEqual(ht.profil_actif({"profilActif": "zz", "profils": [{"id": "a"}]})["id"], "a")
        self.assertEqual(ht.profil_actif(None)["couleur"], "turquoise")
        self.assertEqual(ht.profil_actif({"profils": "n'importe quoi"})["fond"], "aurore")
        self.assertEqual(ht.profil_actif({"profils": [{"id": "a"}]}, "a")["id"], "a")

    def test_theme_force_puis_choisi_puis_auto(self):
        midi = datetime.datetime(2026, 9, 15, 12, 0)
        nuit = datetime.datetime(2026, 9, 15, 23, 0)
        self.assertEqual(ht.resoudre_theme({"theme": "clair"}, "sombre", midi), "sombre")
        self.assertEqual(ht.resoudre_theme({"theme": "clair"}, None, nuit), "clair")
        self.assertEqual(ht.resoudre_theme({"theme": "auto"}, None, midi), "clair")
        self.assertEqual(ht.resoudre_theme({"theme": "auto"}, None, nuit), "sombre")

    def test_auto_suit_le_soleil_du_jour_dans_le_cache_meteo(self):
        meteo = {"donnees": {"daily": {
            "time": ["2026-09-14", "2026-09-15"],
            "sunrise": ["2026-09-14T07:30", "2026-09-15T07:31"],
            "sunset": ["2026-09-14T20:28", "2026-09-15T20:26"],
        }}}
        self.assertEqual(ht.resoudre_theme({"theme": "auto"}, None, datetime.datetime(2026, 9, 15, 7, 45), meteo), "clair")
        # 20 h 27 : le repli 8 h–20 h dirait « sombre » depuis 27 minutes, le soleil aussi
        # mais pour la bonne raison ; 7 h 45 le distingue du repli.
        self.assertEqual(ht.resoudre_theme({"theme": "auto"}, None, datetime.datetime(2026, 9, 15, 20, 27), meteo), "sombre")
        # Un cache d'un autre jour ne dit rien d'aujourd'hui : repli horaire.
        self.assertEqual(ht.resoudre_theme({"theme": "auto"}, None, datetime.datetime(2026, 9, 20, 7, 45), meteo), "sombre")


# ── Fond d'écran ──────────────────────────────────────────────────────────
class Fond(unittest.TestCase):
    def test_svg_valide_aux_bonnes_dimensions_et_couleurs(self):
        svg = ht.fond_svg("aurore", "sombre", ht.COULEURS_PROFIL["violet"])
        racine = ET.fromstring(svg)
        self.assertEqual((racine.get("width"), racine.get("height")), ("3840", "2160"))
        self.assertEqual(racine.get("viewBox"), "0 0 3840 2160")
        self.assertIn("#06070c", svg)
        dessin = ht.nappes("aurore", "sombre", ht.COULEURS_PROFIL["violet"], 3840, 2160)
        self.assertEqual(len(dessin), 4)
        for n in dessin:
            self.assertIn(ht.rvb_hex(n["couleur"]), svg)
        # La première nappe porte l'accent aux trois quarts, comme dans le menu.
        attendu = tuple(round(b + (a - b) * .75) for a, b in zip(ht.COULEURS_PROFIL["violet"], (62, 224, 208)))
        self.assertEqual(dessin[0]["couleur"], attendu)

    def test_svg_de_chaque_fond_et_theme(self):
        for fond in ht.PALETTES:
            for theme in ("sombre", "clair"):
                with self.subTest((fond, theme)):
                    racine = ET.fromstring(ht.fond_svg(fond, theme, (255, 0, 0)))
                    self.assertTrue(racine.tag.endswith("svg"))

    def test_minimal_ne_prend_pas_la_teinte(self):
        self.assertEqual(ht.nappes("minimal", "sombre", (255, 0, 0), 100, 100)[0]["couleur"], (42, 48, 70))

    def test_png_valide_et_couleurs_du_fond(self):
        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "f.png"
            ht.ecrire_png(chemin, *ht.rendre_fond("ocean", "sombre", ht.COULEURS_PROFIL["bleu"], 64, 36))
            largeur, hauteur, canaux, lignes = lire_png(chemin)
            self.assertEqual((largeur, hauteur, canaux), (64, 36, 3))
            pixels = [tuple(l[i:i + 3]) for l in lignes for i in range(0, len(l), 3)]
            # Du bleu domine un fond « océan » sombre teinté de bleu, et il n'est pas noir.
            moyenne = [sum(p[c] for p in pixels) / len(pixels) for c in range(3)]
            self.assertGreater(moyenne[2], moyenne[0])
            self.assertGreater(max(moyenne), 20)

    def test_rendu_clair_reste_clair(self):
        largeur, hauteur, pixels = ht.rendre_fond("minimal", "clair", (0, 0, 0), 32, 18)
        self.assertGreater(min(pixels[len(pixels) // 2]), 200)

    def test_photos_prend_une_image_de_images_hub_ou_se_replie(self):
        with tempfile.TemporaryDirectory() as d:
            dossier = Path(d)
            self.assertIsNone(ht.choisir_photo([dossier], datetime.date(2026, 9, 15)))
            for nom in ("b.jpg", "a.png", "notes.txt"):
                (dossier / nom).write_text("x")
            jour1 = ht.choisir_photo([dossier], datetime.date(2026, 9, 15))
            self.assertIn(jour1.name, {"a.png", "b.jpg"})
            self.assertEqual(jour1, ht.choisir_photo([dossier], datetime.date(2026, 9, 15)))
            self.assertNotEqual(jour1, ht.choisir_photo([dossier], datetime.date(2026, 9, 16)))

    def test_generer_fonds_ecrit_une_fois_et_nettoie_les_anciens(self):
        with tempfile.TemporaryDirectory() as d:
            dossier = Path(d) / "fonds"
            dossier.mkdir()
            (dossier / "hub-vieux.svg").write_text("<svg/>")
            (dossier / "a-moi.svg").write_text("<svg/>")
            a = ht.generer_fond_svg(dossier, "braise", "sombre", (255, 0, 0))
            date = a.stat().st_mtime_ns
            b = ht.generer_fond_svg(dossier, "braise", "sombre", (255, 0, 0))
            self.assertEqual((a, b.stat().st_mtime_ns), (b, date))
            self.assertFalse((dossier / "hub-vieux.svg").exists())
            self.assertTrue((dossier / "a-moi.svg").exists())
            c = ht.generer_fond_svg(dossier, "braise", "sombre", (0, 255, 0))
            self.assertNotEqual(a, c)


# ── Bureau : gsettings ────────────────────────────────────────────────────
ORIGINE = {
    ("org.gnome.desktop.interface", "color-scheme"): "'default'",
    ("org.gnome.desktop.interface", "accent-color"): "'blue'",
    ("org.gnome.desktop.interface", "gtk-theme"): "'Yaru'",
    ("org.gnome.desktop.interface", "icon-theme"): "'Yaru'",
    ("org.gnome.desktop.background", "picture-uri"): "'file:///usr/share/backgrounds/warty-final-ubuntu.png'",
    ("org.gnome.desktop.background", "picture-uri-dark"): "'file:///usr/share/backgrounds/warty-final-ubuntu.png'",
    ("org.gnome.desktop.background", "picture-options"): "'zoom'",
    ("org.gnome.desktop.background", "primary-color"): "'#023c88'",
    ("org.gnome.desktop.screensaver", "picture-uri"): "'file:///usr/share/backgrounds/warty-final-ubuntu.png'",
    ("org.gnome.desktop.screensaver", "picture-options"): "'zoom'",
    ("org.gnome.desktop.screensaver", "primary-color"): "'#023c88'",
}
PLAGE_ACCENT = {("org.gnome.desktop.interface", "accent-color"):
                "enum\n'blue'\n'teal'\n'green'\n'yellow'\n'orange'\n'red'\n'pink'\n'purple'\n'slate'\n"}


class GVariant(unittest.TestCase):
    def test_aller_retour(self):
        for valeur in ["prefer-dark", "l'image", 'a"b', "c\\d", True, False, 0.5, 3]:
            with self.subTest(valeur):
                self.assertEqual(ht.lire_gvariant(ht.formater_gvariant(valeur)), valeur)
        self.assertEqual(ht.lire_gvariant('"l\'image"'), "l'image")
        self.assertEqual(ht.lire_gvariant("uint32 5"), 5)


class Bureau(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        self.origine = self.d / "state" / "theme-origine.json"
        self.voulu = ht.Apparence(theme="sombre", couleur=ht.COULEURS_PROFIL["turquoise"], fond="aurore",
                                  fond_uri="file:///home/hub/.local/share/hub/fonds/hub-aurore.svg", base="#06070c")

    def tearDown(self):
        self._tmp.cleanup()

    def test_valeurs_voulues(self):
        valeurs = ht.valeurs_bureau(self.voulu, accent="teal", yaru="Yaru-prussiangreen-dark")
        self.assertEqual(valeurs[("org.gnome.desktop.interface", "color-scheme")], "prefer-dark")
        self.assertEqual(valeurs[("org.gnome.desktop.interface", "accent-color")], "teal")
        self.assertEqual(valeurs[("org.gnome.desktop.interface", "gtk-theme")], "Yaru-prussiangreen-dark")
        self.assertEqual(valeurs[("org.gnome.desktop.interface", "icon-theme")], "Yaru-prussiangreen-dark")
        for schema, cle in [("org.gnome.desktop.background", "picture-uri"), ("org.gnome.desktop.background", "picture-uri-dark"),
                            ("org.gnome.desktop.screensaver", "picture-uri")]:
            self.assertEqual(valeurs[(schema, cle)], self.voulu.fond_uri)
        clair = ht.valeurs_bureau(self.voulu._replace(theme="clair"), accent=None, yaru=None)
        self.assertEqual(clair[("org.gnome.desktop.interface", "color-scheme")], "default")
        self.assertNotIn(("org.gnome.desktop.interface", "accent-color"), clair)
        self.assertNotIn(("org.gnome.desktop.interface", "gtk-theme"), clair)

    def test_seules_les_cles_qui_changent_et_qui_existent(self):
        voulues = {
            ("org.gnome.desktop.interface", "color-scheme"): "prefer-dark",
            ("org.gnome.desktop.interface", "gtk-theme"): "Yaru",
            ("org.gnome.shell.extensions.dash-to-dock", "background-opacity"): 0.6,
        }
        faux = FauxGsettings(ORIGINE)
        actuelles = ht.lire_cles(faux, voulues)
        self.assertNotIn(("org.gnome.shell.extensions.dash-to-dock", "background-opacity"), actuelles)
        commandes = ht.commandes_gsettings(voulues, actuelles)
        self.assertEqual(commandes, [["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", "'prefer-dark'"]])

    def test_appliquer_deux_fois_n_ecrit_rien_la_seconde(self):
        faux = FauxGsettings(ORIGINE, PLAGE_ACCENT)
        ht.appliquer_bureau(self.voulu, faux, self.origine, yaru_dispo={"Yaru", "Yaru-dark", "Yaru-prussiangreen-dark"})
        self.assertTrue(faux.ecrits)
        self.assertEqual(faux.valeurs[("org.gnome.desktop.interface", "accent-color")], "'teal'")
        self.assertEqual(faux.valeurs[("org.gnome.desktop.interface", "gtk-theme")], "'Yaru-prussiangreen-dark'")
        # picture-options valait déjà « zoom » : pas réécrit.
        self.assertNotIn(("org.gnome.desktop.background", "picture-options", "'zoom'"), faux.ecrits)
        faux.ecrits.clear()
        ht.appliquer_bureau(self.voulu, faux, self.origine, yaru_dispo={"Yaru", "Yaru-dark", "Yaru-prussiangreen-dark"})
        self.assertEqual(faux.ecrits, [])

    def test_accent_hors_plage_pas_ecrit(self):
        faux = FauxGsettings(ORIGINE, {("org.gnome.desktop.interface", "accent-color"): "enum\n'blue'\n"})
        ht.appliquer_bureau(self.voulu, faux, self.origine, yaru_dispo=set())
        self.assertEqual(faux.valeurs[("org.gnome.desktop.interface", "accent-color")], "'blue'")
        self.assertEqual(faux.valeurs[("org.gnome.desktop.interface", "gtk-theme")], "'Yaru'")

    def test_sauvegarde_garde_la_toute_premiere_origine_puis_restaure(self):
        faux = FauxGsettings(ORIGINE, PLAGE_ACCENT)
        ht.appliquer_bureau(self.voulu, faux, self.origine, yaru_dispo=set())
        sauvegarde = json.loads(self.origine.read_text())
        self.assertEqual(sauvegarde["org.gnome.desktop.interface color-scheme"], "'default'")
        # Seules les clés modifiées sont sauvegardées.
        self.assertNotIn("org.gnome.desktop.background picture-options", sauvegarde)

        # Un second passage (autre profil) ne doit pas sauvegarder les valeurs du HUB
        # comme si c'étaient celles de l'utilisateur.
        ht.appliquer_bureau(self.voulu._replace(theme="clair", couleur=ht.COULEURS_PROFIL["rose"]), faux, self.origine, yaru_dispo=set())
        sauvegarde = json.loads(self.origine.read_text())
        self.assertEqual(sauvegarde["org.gnome.desktop.interface color-scheme"], "'default'")
        self.assertEqual(sauvegarde["org.gnome.desktop.interface accent-color"], "'blue'")

        ht.restaurer_bureau(faux, self.origine)
        self.assertEqual(faux.valeurs, ORIGINE)
        self.assertFalse(self.origine.exists())
        faux.ecrits.clear()
        ht.restaurer_bureau(faux, self.origine)
        self.assertEqual(faux.ecrits, [])

    def test_dock_ubuntu_si_present(self):
        valeurs = dict(ORIGINE)
        valeurs.update({
            ("org.gnome.shell.extensions.dash-to-dock", "transparency-mode"): "'DEFAULT'",
            ("org.gnome.shell.extensions.dash-to-dock", "background-opacity"): "0.80000000000000004",
            ("org.gnome.shell.extensions.dash-to-dock", "custom-background-color"): "false",
            ("org.gnome.shell.extensions.dash-to-dock", "background-color"): "'#ffffff'",
        })
        faux = FauxGsettings(valeurs, PLAGE_ACCENT)
        ht.appliquer_bureau(self.voulu, faux, self.origine, yaru_dispo=set())
        self.assertEqual(faux.valeurs[("org.gnome.shell.extensions.dash-to-dock", "custom-background-color")], "true")
        self.assertEqual(faux.valeurs[("org.gnome.shell.extensions.dash-to-dock", "transparency-mode")], "'FIXED'")


# ── Kodi ──────────────────────────────────────────────────────────────────
GUISETTINGS = """<settings version="2">
    <setting id="audiooutput.channels">1</setting>
    <setting id="lookandfeel.skin" default="true">skin.estuary</setting>
    <setting id="lookandfeel.skincolors" default="true">SKINDEFAULT</setting>
    <setting id="locale.language">resource.language.fr_fr</setting>
</settings>
"""


class Kodi(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_edition_sans_perte(self):
        chemin = self.d / "guisettings.xml"
        chemin.write_text(GUISETTINGS)
        self.assertTrue(ht.regler_xml(chemin, {"lookandfeel.skincolors": "teal"}))
        racine = ET.parse(chemin).getroot()
        reglages = {e.get("id"): e for e in racine.iter("setting")}
        self.assertEqual(reglages["lookandfeel.skincolors"].text, "teal")
        self.assertIsNone(reglages["lookandfeel.skincolors"].get("default"))
        self.assertEqual(reglages["audiooutput.channels"].text, "1")
        self.assertEqual(reglages["locale.language"].text, "resource.language.fr_fr")
        self.assertEqual(reglages["lookandfeel.skin"].get("default"), "true")
        self.assertEqual(racine.get("version"), "2")
        date = chemin.stat().st_mtime_ns
        self.assertFalse(ht.regler_xml(chemin, {"lookandfeel.skincolors": "teal"}))
        self.assertEqual(chemin.stat().st_mtime_ns, date)

    def test_fichier_absent_cree_minimal_et_type_pour_le_skin(self):
        chemin = self.d / "addon_data" / "skin.estuary" / "settings.xml"
        ht.regler_xml(chemin, {"HomeFanart.path": "/x/"}, version="1", type_="string")
        racine = ET.parse(chemin).getroot()
        self.assertEqual((racine.tag, racine.get("version")), ("settings", "1"))
        (reglage,) = racine.iter("setting")
        self.assertEqual((reglage.get("id"), reglage.get("type"), reglage.text), ("HomeFanart.path", "string", "/x/"))

    def test_fichier_illisible_n_est_pas_ecrase(self):
        chemin = self.d / "guisettings.xml"
        chemin.write_text("<settings><setting id=")
        with self.assertRaises(ht.ErreurTheme):
            ht.regler_xml(chemin, {"lookandfeel.skincolors": "teal"})
        self.assertEqual(chemin.read_text(), "<settings><setting id=")

    def test_kodi_qui_tourne_detecte_dans_proc(self):
        proc = self.d / "proc"
        for pid, nom in [("12", "bash"), ("40", "kodi.bin"), ("self", "python3")]:
            (proc / pid).mkdir(parents=True)
            (proc / pid / "comm").write_text(nom + "\n")
        self.assertTrue(ht.kodi_tourne(proc))
        (proc / "40" / "comm").write_text("kodi-x\n")
        self.assertFalse(ht.kodi_tourne(proc))

    def test_appliquer_tv_refuse_si_kodi_tourne(self):
        c = ht.chemins(self.d)
        with self.assertRaises(ht.KodiOuvert):
            ht.appliquer_tv(self._apparence(), c, tourne=lambda: True, skins=[])
        self.assertFalse(c["guisettings"].exists())

    def _apparence(self, **k):
        valeurs = dict(theme="sombre", couleur=ht.COULEURS_PROFIL["violet"], fond="nebuleuse", fond_uri="", base="#07050d")
        valeurs.update(k)
        return ht.Apparence(**valeurs)

    def test_appliquer_tv_regle_couleur_et_fond_d_accueil(self):
        c = ht.chemins(self.d)
        c["guisettings"].parent.mkdir(parents=True)
        c["guisettings"].write_text(GUISETTINGS)
        resume = ht.appliquer_tv(self._apparence(), c, tourne=lambda: False, skins=[], taille=(48, 27))
        self.assertEqual(resume["skincolors"], "violet")
        reglages = {e.get("id"): e.text for e in ET.parse(c["guisettings"]).getroot().iter("setting")}
        self.assertEqual(reglages["lookandfeel.skincolors"], "violet")
        self.assertEqual(reglages["audiooutput.channels"], "1")
        skin = {e.get("id"): e.text for e in ET.parse(c["skin_estuary"]).getroot().iter("setting")}
        dossier = Path(skin["HomeFanart.path"])
        self.assertTrue(skin["HomeFanart.path"].endswith("/"))
        # Estuary compose chemin + identifiant de l'entrée + extension : chaque entrée
        # de l'accueil doit trouver son image.
        for entree in ("movies", "tvshows", "music", "weather", "settings", "power"):
            image = dossier / f"{entree}{skin['HomeFanart.ext']}"
            self.assertTrue(image.exists(), entree)
        largeur, hauteur, _, _ = lire_png(dossier / f"movies{skin['HomeFanart.ext']}")
        self.assertEqual((largeur, hauteur), (48, 27))
        # Relancé à l'identique : même dossier, rien de réécrit.
        date = c["guisettings"].stat().st_mtime_ns
        ht.appliquer_tv(self._apparence(), c, tourne=lambda: False, skins=[], taille=(48, 27))
        self.assertEqual(c["guisettings"].stat().st_mtime_ns, date)
        # Nouvelle couleur → nouveau dossier (Kodi garde en cache une image par chemin).
        ht.appliquer_tv(self._apparence(couleur=ht.COULEURS_PROFIL["vert"]), c, tourne=lambda: False, skins=[], taille=(48, 27))
        skin2 = {e.get("id"): e.text for e in ET.parse(c["skin_estuary"]).getroot().iter("setting")}
        self.assertNotEqual(skin2["HomeFanart.path"], skin["HomeFanart.path"])
        self.assertFalse(dossier.exists())

    def test_tv_avec_photo(self):
        c = ht.chemins(self.d)
        photo = self.d / "Images" / "HUB" / "plage.jpg"
        photo.parent.mkdir(parents=True)
        photo.write_bytes(b"\xff\xd8jpeg")
        ht.appliquer_tv(self._apparence(fond="photos", photo=photo), c, tourne=lambda: False, skins=[], taille=(48, 27))
        skin = {e.get("id"): e.text for e in ET.parse(c["skin_estuary"]).getroot().iter("setting")}
        self.assertEqual(skin["HomeFanart.ext"], ".jpg")
        self.assertEqual((Path(skin["HomeFanart.path"]) / "movies.jpg").read_bytes(), b"\xff\xd8jpeg")


# ── Jeux et Plymouth ──────────────────────────────────────────────────────
class Jeux(unittest.TestCase):
    def test_environnement_moonlight(self):
        env = ht.environnement_moonlight(self_apparence())
        self.assertEqual(env["QT_QUICK_CONTROLS_MATERIAL_ACCENT"], "#9e6eff")
        self.assertRegex(env["QT_QUICK_CONTROLS_MATERIAL_PRIMARY"], r"^#[0-9a-f]{6}$")
        self.assertNotIn("QT_QUICK_CONTROLS_MATERIAL_THEME", env)

    def test_appliquer_jeux_ecrit_le_fichier_seulement_si_moonlight_present(self):
        with tempfile.TemporaryDirectory() as d:
            c = ht.chemins(Path(d))
            absent = ht.appliquer_jeux(self_apparence(), c, presence={"moonlight": None, "steam": None})
            self.assertFalse(c["jeux_env"].exists())
            self.assertFalse(absent["moonlight"])
            ht.appliquer_jeux(self_apparence(), c, presence={"moonlight": "/usr/bin/moonlight-qt", "steam": None})
            texte = c["jeux_env"].read_text()
            self.assertIn("QT_QUICK_CONTROLS_MATERIAL_ACCENT='#9e6eff'", texte)


class Plymouth(unittest.TestCase):
    def test_theme_complet(self):
        with tempfile.TemporaryDirectory() as d:
            dossier = Path(d) / "hub"
            ht.generer_plymouth(dossier, self_apparence())
            ini = (dossier / "hub.plymouth").read_text()
            self.assertIn("ModuleName=script", ini)
            self.assertIn("ScriptFile=/usr/share/plymouth/themes/hub/hub.script", ini)
            script = (dossier / "hub.script").read_text()
            self.assertIn("Plymouth.SetRefreshFunction", script)
            self.assertIn('Image("hub.png")', script)
            # Couleur d'accent en flottants 0–1 pour Window.SetBackground… et le point.
            self.assertIn("0.620", script)
            for image in ("hub.png", "point.png"):
                largeur, hauteur, canaux, _ = lire_png(dossier / image)
                self.assertEqual(canaux, 4)
                self.assertGreater(largeur, 0)

    def test_tailles_proportionnelles_a_l_ecran(self):
        # En pixels fixes, le logo faisait 4 % de la hauteur en 4K et le message 16 px.
        with tempfile.TemporaryDirectory() as d:
            dossier = Path(d) / "hub"
            ht.generer_plymouth(dossier, self_apparence())
            script = (dossier / "hub.script").read_text()
            self.assertIn("hauteur_ecran = Window.GetHeight();", script)
            self.assertIn(f"hauteur_ecran * {ht.PLYMOUTH_LOGO}", script)
            self.assertIn(f"hauteur_ecran * {ht.PLYMOUTH_POINT}", script)
            self.assertIn(f'"Sans " + Math.Int(hauteur_ecran * {ht.PLYMOUTH_MESSAGE})', script)
            self.assertNotIn("{", script.split("SetBackgroundTopColor")[0])
            # Images dessinées pour la 4K : Plymouth ne fait que les réduire.
            _, hauteur, _, _ = lire_png(dossier / "hub.png")
            self.assertGreaterEqual(hauteur, round(2160 * ht.PLYMOUTH_LOGO) - 2)
            cote, _, _, _ = lire_png(dossier / "point.png")
            self.assertGreaterEqual(cote, round(2160 * ht.PLYMOUTH_POINT))
            self.assertGreaterEqual(2160 * ht.PLYMOUTH_MESSAGE, 48)


def self_apparence():
    return ht.Apparence(theme="sombre", couleur=ht.COULEURS_PROFIL["violet"], fond="aurore", fond_uri="", base="#06070c")


if __name__ == "__main__":
    unittest.main()
