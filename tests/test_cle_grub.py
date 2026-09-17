"""Le menu GRUB de la clé : ce qu'Entrée lance par défaut, et ce que la TV en montre.

GRUB ne se lance pas dans un test : on refait ici ses calculs (grub-core/gfxmenu/
gui_list.c, theme_loader.c) sur cle/grub.cfg et cle/theme-grub/theme.txt. Le rendu
réel reste à voir sur le M720q.
"""
import re
import unittest
from pathlib import Path

CLE = Path(__file__).resolve().parent.parent / "cle"
GRUB = (CLE / "grub.cfg").read_text(encoding="utf-8")
THEME = (CLE / "theme-grub" / "theme.txt").read_text(encoding="utf-8")
GENERER = (CLE / "theme-grub" / "generer.py").read_text(encoding="utf-8")

# Propriétés reconnues par gui_list.c (list_set_property) et gui_label.c : une faute de
# frappe n'est pas une erreur pour GRUB, elle est ignorée en silence.
PROPRIETES = {
    "boot_menu": {"left", "top", "width", "height", "item_font", "selected_item_font", "item_color",
                  "selected_item_color", "icon_width", "icon_height", "item_height", "item_padding",
                  "item_icon_space", "item_spacing", "visible", "menu_pixmap_style", "item_pixmap_style",
                  "selected_item_pixmap_style", "scrollbar_frame", "scrollbar_thumb", "scrollbar_width",
                  "scrollbar", "id"},
    "label": {"left", "top", "width", "height", "text", "font", "color", "align", "visible", "id"},
    "image": {"left", "top", "width", "height", "file", "id"},
}
# Rayon des morceaux de pastille dans generer.py : ce qu'une pastille dépasse en haut et en bas.
BORD = 14


def entrees():
    return [{"titre": m[1], "options": m[2], "corps": m[3]}
            for m in re.finditer(r'menuentry\s+"([^"]+)"([^{]*)\{(.*?)\n\}', GRUB, re.S)]


def composants():
    sans_commentaires = re.sub(r"(?m)^\s*#.*$", "", THEME)
    return [(m[1], dict(re.findall(r'(\w+)\s*=\s*"?([^"\n]*?)"?\s*$', m[2], re.M)))
            for m in re.finditer(r"\+\s*(\w+)\s*\{([^}]*)\}", sans_commentaires)]


def position(spec, total):
    """parse_proportional_spec : « 50%-64 » → pixels, négatif ramené à 0."""
    valeur = sum(float(t[:-1]) / 100 * total if t.endswith("%") else float(t)
                 for t in re.findall(r"[+-]?[\d.]+%?", spec.replace(" ", "")))
    return max(0, int(valeur))


def menu():
    return next(p for t, p in composants() if t == "boot_menu")


class EntreeParDefaut(unittest.TestCase):
    def test_entree_par_defaut_n_efface_rien(self):
        defaut = re.search(r"(?m)^set default=(\S+)", GRUB)[1]
        liste = entrees()
        if defaut.isdigit():
            choisie = liste[int(defaut)]
        else:
            choisie = next(e for e in liste if re.search(rf"--id\s+{re.escape(defaut)}\b", e["options"]))
        self.assertNotIn("autoinstall", choisie["corps"])
        self.assertIn("Aperçu", choisie["titre"])

    def test_jamais_de_demarrage_seul(self):
        self.assertRegex(GRUB, r"(?m)^set timeout=-1$")

    def test_installation_derniere_et_marquee(self):
        # L'avertissement du thème est placé sous la dernière pastille : l'installation doit y être.
        liste = entrees()
        destructives = [e for e in liste if "autoinstall" in e["corps"]]
        self.assertEqual(len(destructives), 1)
        self.assertIs(destructives[0], liste[-1])
        self.assertIn("--class efface", destructives[0]["options"])
        self.assertIn('"icons"', GENERER)
        self.assertIn("efface.png", GENERER)


class Theme(unittest.TestCase):
    def test_proprietes_connues_de_grub(self):
        for type_, proprietes in composants():
            self.assertLessEqual(set(proprietes), PROPRIETES[type_], type_)

    def test_polices_chargees(self):
        chargees = set(re.search(r"for police in ([^;]+);", GRUB)[1].split())
        for police in re.findall(r'font\s*[:=]\s*"([^"]+)"', THEME):
            nom = police.lower().replace(" ", "-")
            self.assertIn(nom, chargees, police)

    def test_quatre_entrees_visibles_en_720p(self):
        p = menu()
        hauteur = position(p["height"], 720)
        pas = int(p["item_height"]) + int(p["item_spacing"])
        visibles = (hauteur + int(p["item_spacing"]) - 2 * int(p["item_padding"]) - 2 * BORD) // pas
        self.assertGreaterEqual(visibles, len(entrees()))
        # 16 px d'air visibles entre deux pastilles.
        self.assertEqual(int(p["item_spacing"]) - 2 * BORD, 16)

    def test_rien_ne_se_chevauche_en_720p(self):
        haut = 720
        p = menu()
        menu_haut = position(p["top"], haut)
        self.assertGreaterEqual(menu_haut, 0)
        blocs = []
        for type_, q in composants():
            if type_ == "boot_menu":
                continue
            y = position(q["top"], haut)
            blocs.append((y, y + position(q["height"], haut), q.get("text", q.get("file"))))
        pas = int(p["item_height"]) + int(p["item_spacing"])
        n = len(entrees())
        pastilles_bas = menu_haut + int(p["item_padding"]) + (n - 1) * pas + int(p["item_height"]) + 2 * BORD
        blocs.append((menu_haut + int(p["item_padding"]), pastilles_bas, "menu"))
        blocs.sort()
        for (h1, b1, n1), (h2, b2, n2) in zip(blocs, blocs[1:]):
            self.assertLessEqual(b1, h2, f"{n1} chevauche {n2}")
        self.assertLessEqual(blocs[-1][1], haut)

    def test_avertissement_sous_l_installation(self):
        p = menu()
        n = len(entrees())
        for haut in (720, 1080, 2160):
            pas = int(p["item_height"]) + int(p["item_spacing"])
            bas = position(p["top"], haut) + int(p["item_padding"]) + (n - 1) * pas + int(p["item_height"]) + 2 * BORD
            alerte = next(q for t, q in composants() if t == "label" and "efface" in q.get("text", "").lower())
            ecart = position(alerte["top"], haut) - bas
            self.assertTrue(0 <= ecart <= 12, f"{haut} p : {ecart} px entre l'entrée et l'avertissement")
            self.assertGreaterEqual(int(re.search(r"(\d+)$", alerte["font"])[1]), 26)


if __name__ == "__main__":
    unittest.main()
