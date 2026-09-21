#!/usr/bin/env python3
"""Tests du clavier-souris virtuel (hub_pointeur.py), sans /dev/uinput ni noyau Linux.

Lancer : python3 -m unittest installer/telecommande/test_pointeur.py

POURQUOI UN FAUX DESCRIPTEUR. La machine de développement n'a pas de /dev/uinput, et
les tests ne doivent jamais injecter une frappe dans la session de celui qui les lance.
Le périphérique reçoit donc de fausses fonctions `ouvrir`, `ioctl`, `ecrire` : on relit
les ioctl demandés et les structures input_event OCTET PAR OCTET, exactement ce que le
noyau recevrait.

LES TABLES DE CLAVIER SONT VÉRIFIÉES CONTRE XKB quand ses fichiers sont là
(/usr/share/X11/xkb/symbols sur le HUB, ou HUB_XKB_SYMBOLES=dossier) : une table
recopiée de mémoire qui enverrait « q » pour « a » ne se verrait sur aucun autre test.
"""

import errno
import io
import os
import re
import struct
import subprocess
import sys
import unittest
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import hub_pointeur as P  # noqa: E402
from banc_essai import FauxNoyau  # noqa: E402


SYN = (P.EV_SYN, P.SYN_REPORT, 0)


class Peripherique(unittest.TestCase):
    def setUp(self):
        self.noyau = FauxNoyau()
        self.p = self.noyau.peripherique()
        self.p.ouvrir()

    def test_creation_bits_puis_setup_puis_create(self):
        requetes = [r for r, _a in self.noyau.ioctls]
        self.assertEqual(requetes[-2:], [P.UI_DEV_SETUP, P.UI_DEV_CREATE],
                         "les bits se déclarent AVANT la création, sinon le noyau les refuse")
        self.assertIn((P.UI_SET_EVBIT, P.EV_KEY), self.noyau.ioctls)
        self.assertIn((P.UI_SET_EVBIT, P.EV_REL), self.noyau.ioctls)
        for axe in (P.REL_X, P.REL_Y, P.REL_WHEEL, P.REL_WHEEL_HI_RES):
            self.assertIn((P.UI_SET_RELBIT, axe), self.noyau.ioctls)
        # Sans BTN_LEFT, udev ne voit pas une souris et libinput ignore REL_X/REL_Y.
        self.assertIn((P.UI_SET_KEYBIT, P.BTN_LEFT), self.noyau.ioctls)
        self.assertEqual(self.noyau.chemin, "/dev/uinput")
        self.assertTrue(self.noyau.drapeaux & os.O_WRONLY)

    def test_numeros_d_ioctl_de_linux_uinput_h(self):
        # _IOW('U', 100, int) = 0x40045564, etc. : recalculés ici, pas recopiés.
        def iow(n, taille):
            return (1 << 30) | (taille << 16) | (ord("U") << 8) | n
        self.assertEqual(P.UI_SET_EVBIT, iow(100, 4))
        self.assertEqual(P.UI_SET_KEYBIT, iow(101, 4))
        self.assertEqual(P.UI_SET_RELBIT, iow(102, 4))
        self.assertEqual(P.UI_DEV_SETUP, iow(3, struct.calcsize(P.FORMAT_SETUP)))
        self.assertEqual(struct.calcsize(P.FORMAT_SETUP), 92)
        self.assertEqual((P.UI_DEV_CREATE, P.UI_DEV_DESTROY), (0x5501, 0x5502))

    def test_setup_nom_et_bus_virtuel(self):
        setup = next(a for r, a in self.noyau.ioctls if r == P.UI_DEV_SETUP)
        bus, _v, _p, _version, nom, ff = struct.unpack(P.FORMAT_SETUP, setup)
        self.assertEqual(bus, P.BUS_VIRTUAL)
        self.assertTrue(nom.rstrip(b"\0").startswith(b"HUB telecommande"))
        self.assertEqual(ff, 0)

    def test_attend_l_adoption_par_le_compositeur(self):
        self.assertEqual(self.noyau.pauses, [P.PeripheriqueVirtuel.DELAI_ADOPTION_S])

    def test_deplacement_octet_par_octet(self):
        self.p.deplacer(12, -3)
        attendu = (struct.pack("llHHi", 0, 0, 2, 0, 12) + struct.pack("llHHi", 0, 0, 2, 1, -3)
                   + struct.pack("llHHi", 0, 0, 0, 0, 0))
        self.assertEqual(self.noyau.ecrits, [attendu])
        if struct.calcsize("l") == 8:
            self.assertEqual(len(attendu), 72, "input_event fait 24 octets en 64 bits")

    def test_axe_nul_omis_et_deplacement_nul_muet(self):
        self.p.deplacer(0, 5)
        self.p.deplacer(0, 0)
        self.assertEqual(self.noyau.evenements(), [[(P.EV_REL, P.REL_Y, 5), SYN]])

    def test_chaque_lot_finit_par_un_seul_syn(self):
        self.p.deplacer(1, 1)
        self.p.clic("gauche")
        self.p.clic("droite")
        self.p.defiler(-240)
        self.p.frapper(P.KEY_ENTER)
        self.p.taper([((P.MAJ,), P.KEY_Q), ((), P.KEY_W)])
        for lot in self.noyau.evenements():
            self.assertEqual(lot[-1], SYN, lot)
            self.assertEqual(lot.count(SYN), 1, lot)
            self.assertGreater(len(lot), 1, "un SYN seul ne sert à rien")

    def test_clic_appui_et_relacher_dans_deux_lots(self):
        self.p.clic("droite")
        self.assertEqual(self.noyau.evenements(),
                         [[(P.EV_KEY, P.BTN_RIGHT, 1), SYN], [(P.EV_KEY, P.BTN_RIGHT, 0), SYN]])

    def test_frappe_avec_modificateurs_relaches_dans_l_ordre_inverse(self):
        self.p.frapper(P.KEY_2, (P.MAJ, P.ALTGR))
        self.assertEqual([lot[0] for lot in self.noyau.evenements()], [
            (P.EV_KEY, P.MAJ, 1), (P.EV_KEY, P.ALTGR, 1), (P.EV_KEY, P.KEY_2, 1),
            (P.EV_KEY, P.KEY_2, 0), (P.EV_KEY, P.ALTGR, 0), (P.EV_KEY, P.MAJ, 0)])

    def test_aucune_touche_tenue_apres_un_texte(self):
        self.p.taper(P.frappes_pour("Été 2026 @HUB ~ ê", ("fr", "oss"))[0])
        tenues = set()
        for lot in self.noyau.evenements():
            for nature, code, valeur in lot[:-1]:
                (tenues.add if valeur else tenues.discard)(code)
        self.assertEqual(tenues, set(), "une touche restée enfoncée se répète à l'infini sur la TV")

    def test_defilement_fin_et_crans_entiers(self):
        self.p.defiler(50)
        self.p.defiler(50)
        self.p.defiler(50)      # 150 : un cran, reste 30
        self.p.defiler(-100)    # reste -70 : pas de cran
        self.p.defiler(-60)     # reste -130 : un cran négatif, reste -10
        lots = self.noyau.evenements()
        self.assertEqual(lots[0], [(P.EV_REL, P.REL_WHEEL_HI_RES, 50), SYN])
        self.assertEqual(lots[2], [(P.EV_REL, P.REL_WHEEL_HI_RES, 50), (P.EV_REL, P.REL_WHEEL, 1), SYN])
        self.assertEqual(lots[3], [(P.EV_REL, P.REL_WHEEL_HI_RES, -100), SYN])
        self.assertEqual(lots[4], [(P.EV_REL, P.REL_WHEEL_HI_RES, -60), (P.EV_REL, P.REL_WHEEL, -1), SYN])

    def test_touche_non_declaree_refusee(self):
        KEY_LEFTCTRL, KEY_LEFTALT, KEY_LEFTMETA, KEY_F3, KEY_SYSRQ, KEY_DELETE = 29, 56, 125, 61, 99, 111
        for code in (KEY_LEFTCTRL, KEY_LEFTALT, KEY_LEFTMETA, KEY_F3, KEY_SYSRQ, KEY_DELETE):
            with self.assertRaises(ValueError):
                self.p.frapper(code)
        self.assertEqual(self.noyau.ecrits, [])

    def test_fermeture_detruit_le_peripherique_puis_refuse_tout(self):
        self.p.fermer()
        self.assertEqual(self.noyau.ioctls[-1][0], P.UI_DEV_DESTROY)
        self.assertEqual(self.noyau.fermes, [99])
        with self.assertRaises(P.PointeurIndisponible):
            self.p.deplacer(1, 1)
        self.p.fermer()  # deux fois : sans effet
        self.assertEqual(self.noyau.fermes, [99])

    def test_ecriture_en_echec_ferme_et_le_dit(self):
        self.noyau.erreur_ecriture = errno.ENODEV
        with self.assertRaises(P.PointeurIndisponible) as c:
            self.p.deplacer(1, 1)
        self.assertEqual(str(c.exception), "uinput-erreur")
        self.assertFalse(self.p.ouvert)


class Garde(unittest.TestCase):
    """Ce que le périphérique NE PEUT PAS émettre, quoi que fasse le reste du programme."""

    def test_ni_ctrl_ni_alt_ni_super_ni_fonctions_ni_sysrq(self):
        # 29/97 Ctrl, 56 Alt gauche, 125/126 Super, 99 SysRq, 111 Suppr, 59-68/87/88 F1-F12.
        interdits = {29, 97, 56, 125, 126, 99, 111} | set(range(59, 69)) | {87, 88}
        self.assertEqual(P.touches_declarees() & interdits, set())
        noyau = FauxNoyau()
        noyau.peripherique().ouvrir()
        declares = {a for r, a in noyau.ioctls if r == P.UI_SET_KEYBIT}
        self.assertEqual(declares, set(P.touches_declarees()) | {P.BTN_LEFT, P.BTN_RIGHT})

    def test_seuls_modificateurs_maj_et_altgr(self):
        modificateurs = {m for d in P.DISPOSITIONS for frappes in P.table_de(d).values()
                         for mods, _code in frappes for m in mods}
        self.assertEqual(modificateurs, {P.MAJ, P.ALTGR})


class Indisponible(unittest.TestCase):
    def raison(self, numero):
        with self.assertRaises(P.PointeurIndisponible) as c:
            FauxNoyau(erreur_ouverture=numero).peripherique().ouvrir()
        return str(c.exception)

    def test_module_absent(self):
        self.assertEqual(self.raison(errno.ENOENT), "uinput-absent")
        self.assertEqual(self.raison(errno.ENODEV), "uinput-absent")

    def test_droits_absents(self):
        self.assertEqual(self.raison(errno.EACCES), "uinput-refuse")

    def test_autre_erreur(self):
        self.assertEqual(self.raison(errno.EMFILE), "uinput-erreur")

    def test_ioctl_refuse_ferme_le_descripteur(self):
        noyau = FauxNoyau()

        def ioctl(fd, requete, argument=0):
            raise OSError(errno.EINVAL, "ioctl")
        p = P.PeripheriqueVirtuel(ouvrir=noyau.ouvrir, ioctl=ioctl, ecrire=noyau.ecrire,
                                  fermer=noyau.fermes.append, dormir=lambda s: None)
        with self.assertRaises(P.PointeurIndisponible):
            p.ouvrir()
        self.assertEqual(noyau.fermes, [99], "un descripteur perdu par essai finirait par tous les prendre")


class Azerty(unittest.TestCase):
    def codes(self, texte, disposition=("fr", "oss")):
        return P.frappes_pour(texte, disposition)

    def test_le_a_n_est_pas_key_a(self):
        frappes, approx, ignores = self.codes("a")
        self.assertEqual(frappes, [((), P.KEY_Q)], "KEY_A en AZERTY écrit « q »")
        self.assertEqual(self.codes("q")[0], [((), P.KEY_A)])
        self.assertEqual(self.codes("zwm")[0], [((), P.KEY_W), ((), P.KEY_Z), ((), P.KEY_SEMICOLON)])
        self.assertEqual((approx, ignores), ([], []))

    def test_chiffres_en_majuscule_et_lettres_accentuees_directes(self):
        self.assertEqual(self.codes("1")[0], [((P.MAJ,), P.KEY_1)])
        self.assertEqual(self.codes("0")[0], [((P.MAJ,), P.KEY_0)])
        self.assertEqual(self.codes("éèçàù")[0], [((), P.KEY_2), ((), P.KEY_7), ((), P.KEY_9),
                                                   ((), P.KEY_0), ((), P.KEY_APOSTROPHE)])

    def test_symboles_altgr(self):
        self.assertEqual(self.codes("@")[0], [((P.ALTGR,), P.KEY_0)])
        self.assertEqual(self.codes("#{[|\\]}~€")[0], [
            ((P.ALTGR,), P.KEY_3), ((P.ALTGR,), P.KEY_4), ((P.ALTGR,), P.KEY_5), ((P.ALTGR,), P.KEY_6),
            ((P.ALTGR,), P.KEY_8), ((P.ALTGR,), P.KEY_MINUS), ((P.ALTGR,), P.KEY_EQUAL),
            ((P.ALTGR,), P.KEY_2), ((P.ALTGR,), P.KEY_E)])

    def test_ponctuation(self):
        self.assertEqual(self.codes(".,;:!?/-_")[0], [
            ((P.MAJ,), P.KEY_COMMA), ((), P.KEY_M), ((), P.KEY_COMMA), ((), P.KEY_DOT), ((), P.KEY_SLASH),
            ((P.MAJ,), P.KEY_M), ((P.MAJ,), P.KEY_DOT), ((), P.KEY_6), ((), P.KEY_8)])

    def test_touche_morte_circonflexe_et_trema(self):
        self.assertEqual(self.codes("ê")[0], [((), P.KEY_LEFTBRACE), ((), P.KEY_E)])
        self.assertEqual(self.codes("ï")[0], [((P.MAJ,), P.KEY_LEFTBRACE), ((), P.KEY_I)])
        self.assertEqual(self.codes("Ô")[0], [((), P.KEY_LEFTBRACE), ((P.MAJ,), P.KEY_O)])
        # L'accent circonflexe SEUL ne passe pas par la touche morte (elle attendrait la
        # lettre suivante et l'avalerait) : AltGr+9 le donne tout de suite.
        self.assertEqual(self.codes("^")[0], [((P.ALTGR,), P.KEY_9)])

    def test_sans_touches_mortes_l_accent_est_approche_et_dit(self):
        frappes, approx, ignores = self.codes("fête", ("fr", "nodeadkeys"))
        self.assertEqual(frappes, [((), P.KEY_F), ((), P.KEY_E), ((), P.KEY_T), ((), P.KEY_E)])
        self.assertEqual((approx, ignores), (["ê→e"], []))

    def test_majuscules_accentuees_selon_la_variante(self):
        self.assertEqual(self.codes("É", ("fr", "oss"))[0], [((P.MAJ, P.ALTGR), P.KEY_2)])
        self.assertEqual(self.codes("É", ("fr", "latin9"))[0], [((P.MAJ, P.ALTGR), P.KEY_2)])
        frappes, approx, _i = self.codes("École", ("fr", ""))
        self.assertEqual(frappes[0], ((P.MAJ,), P.KEY_E), "fr de base n'a pas de É : E, et on le dit")
        self.assertEqual(approx, ["É→E"])

    def test_typographie_du_telephone(self):
        frappes, approx, ignores = self.codes("l’été …")
        self.assertEqual(frappes[1], ((), P.KEY_4), "l'apostrophe courbe devient l'apostrophe droite")
        self.assertEqual(frappes[-3:], [((P.MAJ,), P.KEY_COMMA)] * 3)
        self.assertEqual((approx, ignores), ([], []))

    def test_ce_qui_n_existe_pas_est_rendu_jamais_tape(self):
        frappes, approx, ignores = self.codes("a😀b日")
        self.assertEqual(frappes, [((), P.KEY_Q), ((), P.KEY_B)])
        self.assertEqual(ignores, ["😀", "日"])

    def test_forme_decomposee_recomposee(self):
        self.assertEqual(self.codes("é")[0], [((), P.KEY_2)], "e + accent combinant = é")

    def test_qwerty_americain(self):
        self.assertEqual(self.codes("aQ1!@", ("us", ""))[0], [
            ((), P.KEY_A), ((P.MAJ,), P.KEY_Q), ((), P.KEY_1), ((P.MAJ,), P.KEY_1), ((P.MAJ,), P.KEY_2)])
        self.assertEqual(self.codes("é", ("us", ""))[1], ["é→e"])

    def test_disposition_non_couverte_rien_n_est_devine(self):
        for disposition in (("fr", "bepo"), ("de", ""), ("fr", "afnor"), None, ()):
            with self.assertRaises(ValueError, msg=repr(disposition)):
                P.frappes_pour("a", disposition)

    def test_tout_ascii_imprimable_est_couvert_en_francais(self):
        ascii_imprimable = "".join(chr(c) for c in range(32, 127))
        for variante in ("", "oss"):
            _f, approx, ignores = self.codes(ascii_imprimable, ("fr", variante))
            self.assertEqual((approx, ignores), ([], []), variante)
        # latin9 : AltGr+7 y est une touche morte, l'accent grave seul n'a pas de touche.
        self.assertEqual(self.codes(ascii_imprimable, ("fr", "latin9"))[2], ["`"])

    def test_toutes_les_touches_des_tables_sont_declarees(self):
        for disposition in P.DISPOSITIONS:
            for frappes in P.table_de(disposition).values():
                for _mods, code in frappes:
                    self.assertIn(code, P.touches_declarees())


# ── Vérification contre les vrais fichiers xkb ──────────────────────────────
NOMS_XKB = {
    "AE01": P.KEY_1, "AE02": P.KEY_2, "AE03": P.KEY_3, "AE04": P.KEY_4, "AE05": P.KEY_5, "AE06": P.KEY_6,
    "AE07": P.KEY_7, "AE08": P.KEY_8, "AE09": P.KEY_9, "AE10": P.KEY_0, "AE11": P.KEY_MINUS, "AE12": P.KEY_EQUAL,
    "AD01": P.KEY_Q, "AD02": P.KEY_W, "AD03": P.KEY_E, "AD04": P.KEY_R, "AD05": P.KEY_T, "AD06": P.KEY_Y,
    "AD07": P.KEY_U, "AD08": P.KEY_I, "AD09": P.KEY_O, "AD10": P.KEY_P, "AD11": P.KEY_LEFTBRACE,
    "AD12": P.KEY_RIGHTBRACE, "AC01": P.KEY_A, "AC02": P.KEY_S, "AC03": P.KEY_D, "AC04": P.KEY_F,
    "AC05": P.KEY_G, "AC06": P.KEY_H, "AC07": P.KEY_J, "AC08": P.KEY_K, "AC09": P.KEY_L,
    "AC10": P.KEY_SEMICOLON, "AC11": P.KEY_APOSTROPHE, "TLDE": P.KEY_GRAVE, "BKSL": P.KEY_BACKSLASH,
    "LSGT": P.KEY_102ND, "SPCE": P.KEY_SPACE, "AB01": P.KEY_Z, "AB02": P.KEY_X, "AB03": P.KEY_C, "AB04": P.KEY_V,
    "AB05": P.KEY_B, "AB06": P.KEY_N, "AB07": P.KEY_M, "AB08": P.KEY_COMMA, "AB09": P.KEY_DOT,
    "AB10": P.KEY_SLASH,
}
SYMBOLES = {
    "ampersand": "&", "eacute": "é", "quotedbl": '"', "apostrophe": "'", "parenleft": "(", "minus": "-",
    "egrave": "è", "underscore": "_", "ccedilla": "ç", "agrave": "à", "parenright": ")", "equal": "=",
    "asciitilde": "~", "numbersign": "#", "braceleft": "{", "bracketleft": "[", "bar": "|", "grave": "`",
    "backslash": "\\", "asciicircum": "^", "at": "@", "bracketright": "]", "braceright": "}",
    "degree": "°", "plus": "+", "EuroSign": "€", "dollar": "$", "sterling": "£", "ugrave": "ù",
    "percent": "%", "asterisk": "*", "mu": "µ", "less": "<", "greater": ">", "comma": ",",
    "question": "?", "semicolon": ";", "period": ".", "colon": ":", "slash": "/", "exclam": "!",
    "section": "§", "twosuperior": "²", "Eacute": "É", "Egrave": "È", "Ccedilla": "Ç", "Agrave": "À",
    "Ugrave": "Ù", "oe": "œ", "OE": "Œ", "ae": "æ", "AE": "Æ", "guillemotleft": "«",
    "guillemotright": "»", "guillemetleft": "«", "guillemetright": "»", "quoteleft": "`",
    "quoteright": "'", "space": " ",
    "dead_circumflex": "̂", "dead_diaeresis": "̈",
}


def lire_xkb(dossier, fichier, variante=None, deja=None):
    """{code Linux: [symbole niveau 1, 2, 3, 4]} d'une disposition xkb, inclusions suivies
    (fusion « override » : un niveau redéfini remplace, un niveau absent reste)."""
    texte = re.sub(r"//[^\n]*", "", (Path(dossier) / fichier).read_text(encoding="utf-8", errors="replace"))
    blocs = re.findall(r'((?:default\s+)?(?:\w+\s+)*)xkb_symbols\s+"([^"]+)"\s*\{(.*?)\n\};', texte, re.S)
    if variante is None:
        variante = next((nom for prefixe, nom, _c in blocs if "default" in prefixe), blocs[0][1])
    corps = next(c for _p, nom, c in blocs if nom == variante)
    touches = {}
    for instruction in re.finditer(r'include\s+"([^"(]+)(?:\(([^)]+)\))?"|key\s*<(\w+)>\s*\{(.*?)\}\s*;', corps, re.S):
        inclus, sa_variante, nom, contenu = instruction.groups()
        if inclus:
            if (Path(dossier) / inclus).is_file() and inclus in ("fr", "us", "latin"):
                for code, niveaux in lire_xkb(dossier, inclus, sa_variante).items():
                    touches[code] = niveaux
            continue
        if nom not in NOMS_XKB:
            continue
        contenu = re.sub(r'type\s*\[[^\]]*\]\s*=\s*"[^"]*"\s*,', "", contenu)
        groupe = re.search(r"\[([^\]]*)\]", re.sub(r"symbols\s*\[[^\]]*\]\s*=", "", contenu))
        if not groupe:
            continue
        niveaux = [s.strip() for s in groupe.group(1).split(",")]
        ancien = touches.get(NOMS_XKB[nom], [])
        touches[NOMS_XKB[nom]] = niveaux + ancien[len(niveaux):]
    return touches


def caractere_xkb(symbole):
    if symbole in SYMBOLES:
        return SYMBOLES[symbole]
    if len(symbole) == 1:
        return symbole
    m = re.fullmatch(r"(?:U|0x100)([0-9A-Fa-f]{4,6})", symbole)
    return chr(int(m.group(1), 16)) if m else None


def dossier_xkb():
    for candidat in (os.environ.get("HUB_XKB_SYMBOLES"), "/usr/share/X11/xkb/symbols"):
        if candidat and (Path(candidat) / "fr").is_file():
            return candidat
    return None


@unittest.skipUnless(dossier_xkb(), "fichiers xkb absents (HUB_XKB_SYMBOLES=dossier pour les fournir)")
class TablesContreXkb(unittest.TestCase):
    def test_chaque_caractere_de_chaque_table_est_bien_sur_cette_touche_a_ce_niveau(self):
        verifies = 0
        for (disposition, variante), (lignes, mortes) in P.DISPOSITIONS.items():
            # symbols/pc porte ce que toutes les dispositions partagent (espace, < >).
            a_pc = (Path(dossier_xkb()) / "pc").is_file()
            xkb = lire_xkb(dossier_xkb(), "pc") if a_pc else {}
            xkb.update(lire_xkb(dossier_xkb(), disposition, variante or None))
            for code, niveaux in lignes:
                if not a_pc and code in (P.KEY_SPACE, P.KEY_102ND):
                    continue
                for niveau, attendu in enumerate(niveaux):
                    if attendu == "\0":
                        continue
                    symboles = xkb.get(code, [])
                    lu = caractere_xkb(symboles[niveau]) if niveau < len(symboles) else None
                    self.assertEqual(lu, attendu, f"{disposition}({variante}) code {code} niveau {niveau + 1} : "
                                                  f"xkb dit {symboles}")
                    verifies += 1
            for code, niveau, combinant in mortes:
                self.assertEqual(caractere_xkb(xkb[code][niveau]), combinant, f"{disposition}({variante})")
                verifies += 1
        self.assertGreater(verifies, 600)

    def test_les_variantes_sans_touches_mortes_n_en_ont_vraiment_pas(self):
        for variante in ("nodeadkeys", "oss_nodeadkeys", "latin9_nodeadkeys"):
            xkb = lire_xkb(dossier_xkb(), "fr", variante)
            self.assertFalse(xkb[P.KEY_LEFTBRACE][0].startswith("dead_"), variante)


# ── Disposition active ──────────────────────────────────────────────────────
def faux_lanceur(reponses):
    """reponses : {fragment de commande: (code, sortie)} ; tout le reste échoue."""
    def lancer(commande):
        for fragment, (code, sortie) in reponses.items():
            if fragment in " ".join(commande):
                return subprocess.CompletedProcess(commande, code, stdout=sortie, stderr="")
        return None
    return lancer


class Disposition(unittest.TestCase):
    def test_source_courante_de_gnome(self):
        lancer = faux_lanceur({" sources": (0, "[('xkb', 'us'), ('xkb', 'fr+oss')]\n"),
                               "mru-sources": (0, "[('xkb', 'fr+oss'), ('xkb', 'us')]\n")})
        self.assertEqual(P.lire_disposition(lancer), ("fr", "oss"))

    def test_mru_vide_premiere_source(self):
        lancer = faux_lanceur({" sources": (0, "[('xkb', 'fr')]\n"), "mru-sources": (0, "@a(ss) []\n")})
        self.assertEqual(P.lire_disposition(lancer), ("fr", ""))

    def test_mru_perime_ignore(self):
        lancer = faux_lanceur({" sources": (0, "[('xkb', 'fr+latin9')]"), "mru-sources": (0, "[('xkb', 'de')]")})
        self.assertEqual(P.lire_disposition(lancer), ("fr", "latin9"))

    def test_source_ibus_pas_de_table(self):
        lancer = faux_lanceur({" sources": (0, "[('ibus', 'anthy')]"), "mru-sources": (0, "[]")})
        self.assertIsNone(P.lire_disposition(lancer))

    def test_sans_gnome_disposition_du_systeme(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".keyboard", delete=False) as f:
            f.write('# KEYBOARD CONFIGURATION FILE\nXKBMODEL="pc105"\nXKBLAYOUT="fr,us"\nXKBVARIANT="oss,"\n')
        try:
            lancer = faux_lanceur({" sources": (0, "@a(ss) []\n")})
            self.assertEqual(P.lire_disposition(lancer, f.name), ("fr", "oss"))
            self.assertEqual(P.lire_disposition(lambda c: None, f.name), ("fr", "oss"))
            self.assertIsNone(P.lire_disposition(lambda c: None, f.name + ".absent"))
        finally:
            os.unlink(f.name)


# ── Session au premier plan, déverrouillée ──────────────────────────────────
UID = "1000"
LISTE = "     2 1000 salon seat0 tty2 active no -\n    c1  120 gdm   seat0 tty1 online no -\n     5 1000 salon -     -    active no -\n"


def bloc(**p):
    base = {"Active": "yes", "LockedHint": "no", "Class": "user", "Type": "wayland", "Remote": "no"}
    return "\n".join(f"{k}={v}" for k, v in {**base, **p}.items())


class SessionPilotable(unittest.TestCase):
    def verdict(self, *blocs, liste=LISTE, code=0):
        lancer = faux_lanceur({"list-sessions": (0, liste), "show-session": (code, "\n\n".join(blocs) + "\n")})
        return P.session_pilotable(lancer, uid=UID)

    def test_session_graphique_active_et_deverrouillee(self):
        self.assertEqual(self.verdict(bloc(), bloc(Class="manager", Type="unspecified")), (True, None))

    def test_ecran_verrouille(self):
        self.assertEqual(self.verdict(bloc(LockedHint="yes")), (False, "session-verrouillee"))

    def test_ecran_de_connexion_devant(self):
        # GDM au premier plan : notre session existe encore, mais n'est plus active.
        self.assertEqual(self.verdict(bloc(Active="no")), (False, "session-en-arriere-plan"))

    def test_seule_une_session_graphique_locale_compte(self):
        self.assertFalse(self.verdict(bloc(Type="tty"))[0], "une console n'est pas la TV")
        self.assertFalse(self.verdict(bloc(Remote="yes"))[0], "ni une session distante")
        self.assertFalse(self.verdict(bloc(Class="greeter"))[0])
        self.assertFalse(self.verdict(bloc(Class="manager", Type="unspecified"))[0])

    def test_seules_nos_sessions_sont_interrogees(self):
        vues = []

        def lancer(commande):
            vues.append(commande)
            sortie = LISTE if "list-sessions" in commande else bloc()
            return subprocess.CompletedProcess(commande, 0, stdout=sortie, stderr="")
        P.session_pilotable(lancer, uid=UID)
        self.assertEqual(vues[1][:4], ["loginctl", "show-session", "2", "5"], "jamais la session de gdm")

    def test_dans_le_doute_c_est_non(self):
        self.assertEqual(P.session_pilotable(lambda c: None, uid=UID), (False, "session-inconnue"))
        self.assertEqual(self.verdict(bloc(), code=1), (False, "session-inconnue"))
        self.assertEqual(self.verdict(bloc(), liste=""), (False, "session-inconnue"))
        self.assertEqual(self.verdict("Active=yes"), (False, "session-en-arriere-plan"), "champ manquant = non")


# ── Débit et trames ─────────────────────────────────────────────────────────
class Debit(unittest.TestCase):
    def test_seau(self):
        t = [0.0]
        seau = P.Seau(debit=10, capacite=20, horloge=lambda: t[0])
        self.assertTrue(all(seau.prendre() for _ in range(20)))
        self.assertFalse(seau.prendre(), "la réserve vidée, plus rien ne passe")
        t[0] += 0.5
        self.assertTrue(all(seau.prendre() for _ in range(5)))
        self.assertFalse(seau.prendre())
        t[0] += 3600
        self.assertTrue(seau.prendre(20))
        self.assertFalse(seau.prendre(1), "une heure de calme ne donne pas plus que la capacité")

    def test_un_texte_plus_gros_que_le_seau_ne_passe_jamais(self):
        seau = P.Seau(debit=1, capacite=10, horloge=lambda: 0.0)
        self.assertFalse(seau.prendre(11))
        self.assertTrue(seau.prendre(10), "et un refus ne coûte rien")


def trame_client(opcode, contenu, masque=b"\x01\x02\x03\x04", fin=True, masquee=True):
    entete = bytes([(0x80 if fin else 0) | opcode])
    n = len(contenu)
    bit = 0x80 if masquee else 0
    entete += bytes([bit | n]) if n < 126 else bytes([bit | 126]) + struct.pack("!H", n)
    if not masquee:
        return entete + contenu
    return entete + masque + bytes(o ^ masque[i & 3] for i, o in enumerate(contenu))


class Trames(unittest.TestCase):
    def test_cle_de_la_norme(self):
        # L'exemple de la RFC 6455, section 1.3.
        self.assertEqual(P.cle_acceptee("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_trame_masquee_lue(self):
        flux = io.BytesIO(trame_client(P.OP_TEXTE, b'{"t":"m","x":3,"y":-4}') + trame_client(P.OP_PING, b"x" * 200))
        self.assertEqual(P.lire_trame(flux, 2048), (P.OP_TEXTE, b'{"t":"m","x":3,"y":-4}'))
        self.assertEqual(P.lire_trame(flux, 2048), (P.OP_PING, b"x" * 200))
        with self.assertRaises(EOFError):
            P.lire_trame(flux, 2048)

    def test_trame_non_masquee_refusee(self):
        with self.assertRaises(P.TrameRefusee) as c:
            P.lire_trame(io.BytesIO(trame_client(P.OP_TEXTE, b"{}", masquee=False)), 2048)
        self.assertEqual(c.exception.code, 1002)

    def test_trame_fragmentee_refusee(self):
        with self.assertRaises(P.TrameRefusee):
            P.lire_trame(io.BytesIO(trame_client(P.OP_TEXTE, b"{}", fin=False)), 2048)

    def test_trop_grosse_refusee_avant_lecture(self):
        with self.assertRaises(P.TrameRefusee) as c:
            P.lire_trame(io.BytesIO(trame_client(P.OP_TEXTE, b"x" * 3000)[:8]), 2048)
        self.assertEqual(c.exception.code, 1009)
        geante = bytes([0x81, 0x80 | 127]) + struct.pack("!Q", 1 << 40)
        with self.assertRaises(P.TrameRefusee):
            P.lire_trame(io.BytesIO(geante), 2048)

    def test_trame_serveur(self):
        self.assertEqual(P.trame(P.OP_TEXTE, b"ok"), b"\x81\x02ok")
        longue = P.trame(P.OP_TEXTE, b"y" * 300)
        self.assertEqual(longue[:4], b"\x81\x7e\x01\x2c")


if __name__ == "__main__":
    unittest.main()
