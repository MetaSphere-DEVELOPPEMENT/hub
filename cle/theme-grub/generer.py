#!/usr/bin/env python3
"""Images du thème GRUB de la clé : fond « aurore » du HUB et pastilles de sélection.

Le menu de démarrage est la première chose que la TV montre : il doit déjà ressembler
au HUB. Les couleurs reprennent la palette aurore et l'accent turquoise de hub.js.

    python3 theme-grub/generer.py theme-grub/sortie
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

LARGEUR, HAUTEUR = 1920, 1080
ENCRE = (6, 7, 12)
TURQUOISE = (62, 224, 208)


def fond():
    y, x = np.mgrid[0:HAUTEUR, 0:LARGEUR].astype(np.float32)
    image = np.zeros((HAUTEUR, LARGEUR, 3), np.float32) + ENCRE
    for cx, cy, rayon, couleur, force in (
        (.16, .20, .55, TURQUOISE, .38),
        (.88, .14, .45, (110, 90, 255), .26),
        (.70, 1.0, .55, (62, 140, 255), .24),
        (.05, .95, .45, (30, 40, 90), .45),
    ):
        d = np.hypot(x - cx * LARGEUR, y - cy * HAUTEUR) / (rayon * LARGEUR)
        poids = np.clip(1 - d, 0, 1) ** 2 * force
        image += poids[..., None] * np.array(couleur, np.float32)
    # Vignette : le centre, où est le menu, reste lisible.
    d = np.hypot((x - LARGEUR / 2) / LARGEUR, (y - HAUTEUR * .45) / HAUTEUR)
    image *= np.clip(1.15 - d * 1.1, .35, 1)[..., None]
    grain = np.random.default_rng(7).normal(0, 2.2, (HAUTEUR, LARGEUR, 1))
    return Image.fromarray(np.clip(image + grain, 0, 255).astype(np.uint8))


def pastilles(dossier, nom, remplissage, bordure, rayon=14):
    """Les neuf morceaux qu'attend GRUB pour dessiner un rectangle arrondi extensible."""
    t = rayon * 3
    carre = Image.new("RGBA", (t, t), (0, 0, 0, 0))
    ImageDraw.Draw(carre).rounded_rectangle((0, 0, t - 1, t - 1), rayon, fill=remplissage, outline=bordure, width=2)
    r = rayon
    morceaux = {
        "nw": (0, 0, r, r), "n": (r, 0, 2 * r, r), "ne": (2 * r, 0, t, r),
        "w": (0, r, r, 2 * r), "c": (r, r, 2 * r, 2 * r), "e": (2 * r, r, t, 2 * r),
        "sw": (0, 2 * r, r, t), "s": (r, 2 * r, 2 * r, t), "se": (2 * r, 2 * r, t, t),
    }
    for suffixe, boite in morceaux.items():
        carre.crop(boite).save(dossier / f"{nom}_{suffixe}.png")


def main():
    dossier = Path(sys.argv[1] if len(sys.argv) > 1 else "sortie")
    dossier.mkdir(parents=True, exist_ok=True)
    fond().save(dossier / "fond.png", optimize=True)
    pastilles(dossier, "choix", (*TURQUOISE, 255), (190, 255, 248, 255))
    pastilles(dossier, "entree", (255, 255, 255, 18), (255, 255, 255, 40))
    pastilles(dossier, "cadre", (14, 16, 26, 170), (255, 255, 255, 34), rayon=22)
    # Le logo : le carré lumineux du HUB, flouté pour le halo.
    logo = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rounded_rectangle((40, 40, 80, 80), 11, fill=(*TURQUOISE, 255))
    halo = logo.filter(ImageFilter.GaussianBlur(14))
    halo.alpha_composite(logo)
    halo.save(dossier / "logo.png")


if __name__ == "__main__":
    main()
