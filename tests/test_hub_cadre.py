"""Cadre photo du mode ambiant : albums, lecture EXIF maison, souvenirs du jour.

    python3 -m unittest tests/test_hub_cadre.py
"""

import importlib.util
import os
import struct
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("hub_menu_cadre", RACINE / "installer" / "hub-menu.py")
hub_menu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub_menu)


def jpeg_exif(date_texte=None, boutisme="<", dans_ifd0=False, bourrage=b""):
    """Un JPEG minimal portant DateTimeOriginal (0x9003) dans le sous-IFD Exif, ou
    DateTime (0x0132) dans l'IFD0 — ce que produisent téléphones et appareils."""
    o = boutisme
    entete = (b"II*\x00" if o == "<" else b"MM\x00*") + struct.pack(o + "I", 8)
    valeur = (date_texte or "").encode() + b"\x00"
    if dans_ifd0:
        ifd0 = struct.pack(o + "H", 1) + struct.pack(o + "HHII", 0x0132, 2, len(valeur), 8 + 2 + 12 + 4) + struct.pack(o + "I", 0)
        tiff = entete + ifd0 + valeur
    else:
        exif_ifd = 8 + 2 + 12 + 4
        ifd0 = struct.pack(o + "H", 1) + struct.pack(o + "HHII", 0x8769, 4, 1, exif_ifd) + struct.pack(o + "I", 0)
        donnees = exif_ifd + 2 + 12 + 4
        sous = struct.pack(o + "H", 1) + struct.pack(o + "HHII", 0x9003, 2, len(valeur), donnees) + struct.pack(o + "I", 0)
        tiff = entete + ifd0 + sous + valeur
    app1 = b"Exif\x00\x00" + tiff
    # Un segment APP0 (JFIF) avant : le lecteur doit savoir sauter les segments.
    app0 = b"JFIF\x00" + bourrage
    return (b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", len(app0) + 2) + app0
            + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xda\x00\x02" + b"\x00" * 64 + b"\xff\xd9")


class Exif(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def ecrire(self, nom, contenu):
        f = self.d / nom
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(contenu)
        return f

    def test_date_de_prise_de_vue_petit_boutiste(self):
        f = self.ecrire("a.jpg", jpeg_exif("2019:09:15 18:42:07"))
        self.assertEqual(hub_menu.date_exif(f), datetime(2019, 9, 15, 18, 42, 7))

    def test_grand_boutiste(self):
        f = self.ecrire("b.jpg", jpeg_exif("2021:12:24 20:00:00", boutisme=">"))
        self.assertEqual(hub_menu.date_exif(f), datetime(2021, 12, 24, 20, 0, 0))

    def test_repli_sur_datetime_de_l_ifd0(self):
        f = self.ecrire("c.jpg", jpeg_exif("2020:01:02 03:04:05", dans_ifd0=True))
        self.assertEqual(hub_menu.date_exif(f), datetime(2020, 1, 2, 3, 4, 5))

    def test_sans_exif_ou_abime(self):
        self.assertIsNone(hub_menu.date_exif(self.ecrire("sans.jpg", b"\xff\xd8\xff\xda\x00\x02" + b"\x00" * 10)))
        self.assertIsNone(hub_menu.date_exif(self.ecrire("pas-jpeg.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 30)))
        self.assertIsNone(hub_menu.date_exif(self.ecrire("tronque.jpg", jpeg_exif("2019:09:15 18:42:07")[:40])))
        self.assertIsNone(hub_menu.date_exif(self.ecrire("zeros.jpg", jpeg_exif("0000:00:00 00:00:00"))))
        self.assertIsNone(hub_menu.date_exif(self.d / "absent.jpg"))

    def test_offsets_absurdes_ne_bouclent_pas(self):
        contenu = bytearray(jpeg_exif("2019:09:15 18:42:07"))
        i = contenu.find(b"II*\x00")
        contenu[i + 4:i + 8] = struct.pack("<I", 0xFFFFFF00)
        self.assertIsNone(hub_menu.date_exif(self.ecrire("offset.jpg", bytes(contenu))))

    def test_albums_et_photos(self):
        self.ecrire("HUB/plage.jpg", jpeg_exif())
        self.ecrire("HUB/Vacances 2024/a.jpg", jpeg_exif())
        self.ecrire("HUB/Vacances 2024/jour 2/b.jpeg", jpeg_exif())
        self.ecrire("HUB/Noël/c.png", b"x")
        self.ecrire("HUB/profils/moi.jpg", b"x")
        self.ecrire("HUB/.cache/x.jpg", b"x")
        self.ecrire("HUB/Vide/notes.txt", b"x")
        dossiers = [self.d / "HUB"]
        self.assertEqual(hub_menu.albums_cadre(dossiers), ["Noël", "Vacances 2024"])
        tout = [p.name for p in hub_menu.photos_cadre(dossiers)]
        self.assertEqual(sorted(tout), ["a.jpg", "b.jpeg", "c.png", "plage.jpg"], "ni photos de profil ni dossiers cachés")
        self.assertEqual(sorted(p.name for p in hub_menu.photos_cadre(dossiers, "Vacances 2024")), ["a.jpg", "b.jpeg"])
        self.assertEqual(hub_menu.photos_cadre(dossiers, "../../etc"), [], "un album est un nom, pas un chemin")

    def test_souvenirs_du_meme_jour_les_annees_precedentes(self):
        f1 = self.ecrire("HUB/2019.jpg", jpeg_exif("2019:09:15 10:00:00"))
        self.ecrire("HUB/autre-jour.jpg", jpeg_exif("2019:09:14 10:00:00"))
        self.ecrire("HUB/cette-annee.jpg", jpeg_exif("2026:09:15 08:00:00"))
        f2 = self.ecrire("HUB/2023.jpg", jpeg_exif("2023:09:15 21:00:00"))
        cache = self.d / "cache/exif.json"
        fichiers = hub_menu.photos_cadre([self.d / "HUB"])
        s = hub_menu.souvenirs(fichiers, date(2026, 9, 15), cache)
        self.assertEqual(s, [{"uri": f2.resolve().as_uri(), "annee": 2023}, {"uri": f1.resolve().as_uri(), "annee": 2019}])
        self.assertTrue(cache.exists(), "les dates lues sont gardées : relire 500 photos à chaque retour de Kodi serait lent")

    def test_le_cache_suit_les_fichiers_modifies(self):
        f = self.ecrire("HUB/x.jpg", jpeg_exif("2019:09:15 10:00:00"))
        cache = self.d / "cache/exif.json"
        self.assertEqual(len(hub_menu.souvenirs([f], date(2026, 9, 15), cache)), 1)
        f.write_bytes(jpeg_exif("2019:03:01 10:00:00", bourrage=b"plus long"))
        os.utime(f, (1, 1))
        self.assertEqual(hub_menu.souvenirs([f], date(2026, 9, 15), cache), [])


if __name__ == "__main__":
    unittest.main()
