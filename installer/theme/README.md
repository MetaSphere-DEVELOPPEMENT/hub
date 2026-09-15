# hub-theme — le bureau, Kodi et le mode Jeux aux couleurs du profil

Le menu du HUB a un profil actif : une couleur, un thème (sombre, clair, auto), un fond
(aurore, nébuleuse, océan, braise, minimal, photos). `hub-theme` traduit ce profil pour
chaque logiciel qui s'ouvre après le menu. Python 3, bibliothèque standard seulement.

```
hub-theme bureau              # GNOME : clair/sombre, accent, Yaru, fond, verrouillage, dock
hub-theme tv                  # Kodi/Estuary : couleur du skin, fond de l'accueil
hub-theme jeux                # Moonlight : fichier d'environnement ~/.config/hub/jeux.env
hub-theme apercu              # génère le fond SVG du profil, n'applique rien
hub-theme etat                # ce qui serait appliqué (accent, Yaru, Estuary, Kodi ouvert ?)
hub-theme restaurer           # remet les réglages GNOME d'origine
hub-theme plymouth DOSSIER    # écrit le thème de démarrage dans DOSSIER
  --theme sombre|clair        # forcer, au lieu du thème du profil
  --profil ID                 # un autre profil que le profil actif
  --simuler                   # bureau/restaurer : lire, afficher les écritures sans les faire
```

Sortie : résumé JSON. Codes : 0 fait, 1 erreur, 2 usage, **3 Kodi ouvert (rien écrit)**.

Ce qui compte dans le profil : `couleur`, `theme`, `fond`, `teinteMode`. `photo` est la
photo de **profil** (l'avatar) : elle n'est pas prise comme fond d'écran. Avec
`fond: "photos"`, le fond est une image de `Images/HUB` (ou `Pictures/HUB`), qui change
chaque jour et reste la même toute la journée ; sans image, l'aurore, comme le menu.

Tests : `python3 -m unittest discover -s installer/theme` (36 tests, aucun n'appelle le
vrai gsettings ni ne touche au bureau de la machine).

## Ce que fait chaque commande

### `bureau`

| Clé | Valeur |
|---|---|
| `org.gnome.desktop.interface color-scheme` | `prefer-dark` ou `default` |
| `org.gnome.desktop.interface accent-color` | la valeur de GNOME la plus proche de la couleur du profil (voir « Couleurs ») |
| `org.gnome.desktop.interface gtk-theme`, `icon-theme` | la variante Yaru la plus proche, **seulement si le thème GTK 3 et les icônes existent sur le disque** |
| `org.gnome.desktop.background picture-uri`, `picture-uri-dark` | le fond généré (ou la photo) |
| `org.gnome.desktop.background picture-options`, `primary-color` | `zoom`, couleur de base du fond |
| `org.gnome.desktop.screensaver picture-uri`, `picture-options`, `primary-color` | idem : l'écran de verrouillage |
| `org.gnome.shell.extensions.dash-to-dock` | `transparency-mode FIXED`, couleur de base du fond, opacité 0,6 (sombre) / 0,7 (clair) |

- **N'écrit que ce qui change.** Chaque clé est lue d'abord ; une clé illisible (schéma
  absent : dock désinstallé, GNOME sans `accent-color`) est laissée de côté. La valeur
  d'`accent-color` est aussi bornée par `gsettings range`.
- **Sauvegarde** dans `~/.local/state/hub/theme-origine.json`, avant d'écrire, et
  seulement la **première** valeur jamais vue de chaque clé : un second passage ne
  sauve pas les couleurs du HUB comme si c'étaient celles de l'utilisateur.
  `hub-theme restaurer` les remet et efface la sauvegarde.
- Le fond est un **SVG 3840×2160** dans `~/.local/share/hub/fonds/`, nommé par
  l'empreinte de son contenu (GNOME ne recharge pas une adresse inchangée). Les anciens
  `hub-*.svg` sont supprimés.

### `tv`

- **Refuse si Kodi tourne** (code 3) : Kodi réécrit `guisettings.xml` et les réglages du
  skin en quittant.
- `lookandfeel.skincolors` ← la couleur Estuary la plus proche. La liste est relue dans
  `/usr/share/kodi/addons/skin.estuary/colors/*.xml` (champ `button_focus`) ; à défaut,
  table de Kodi 21 : SKINDEFAULT, brown, charcoal, chartreuse, concrete, gold, green,
  maroon, midnight, orange, pink, rose, teal, violet. N'est posé que si le skin est
  Estuary (ou pas encore choisi).
- `lookandfeel.skintheme` n'est **pas** touché : Estuary n'a que `SKINDEFAULT`, `curial`
  et `flat`, qui changent les textures, pas la clarté. **Estuary n'a pas de thème clair.**
- Fond de l'accueil : réglage du skin `HomeFanart.path` / `HomeFanart.ext` dans
  `~/.kodi/userdata/addon_data/skin.estuary/settings.xml`. Estuary compose
  `chemin + identifiant de l'entrée + extension` (Variables.xml, `HomeFanartVar`) :
  hub-theme crée donc un dossier avec un lien par entrée (movies, tvshows, music…,
  weather, settings, power) vers un PNG 960×540 tramé, toujours dans la version sombre.
  Le dossier porte l'empreinte du contenu : Kodi garde une texture en cache par chemin.
  Estuary pose ce fond à **19 % d'opacité** (`bg_overlay`) : c'est une teinte, pas une
  image franche. Le réglage `no_fanart` de l'utilisateur, s'il est coché, l'emporte.
- Édition XML : les autres réglages sont gardés, `default="true"` retiré de ce qu'on
  change, écriture atomique, fichier absent → créé minimal, fichier illisible → erreur
  et fichier laissé tel quel.

### `jeux`

Le logiciel n'est pas choisi. Ce qui est thémable, lu dans les sources et la documentation :

| | Thémable | Pas thémable |
|---|---|---|
| **Moonlight-qt** | accent et couleur primaire Material : `QT_QUICK_CONTROLS_MATERIAL_ACCENT` et `QT_QUICK_CONTROLS_MATERIAL_PRIMARY` ne sont posés par `app/main.cpp` que s'ils sont absents de l'environnement (valeurs `#rrggbb` acceptées) | le thème (forcé à `Dark`), le fond (aucun), la disposition ; aucun de ces choix n'est dans `Moonlight.conf` |
| **Steam Big Picture** | la vidéo de démarrage : un **WebM** de moins de 30 s dans `~/.steam/root/config/uioverrides/movies/` puis choix dans Réglages → Personnalisation | couleurs, fond, thème : l'interface est web depuis 2023 et n'offre aucun réglage de ce genre ; seuls des injecteurs CSS tiers le font, hors de la règle « pas de couche exotique » |

`hub-theme jeux` détecte Moonlight (`moonlight-qt`, `moonlight`, ou le flatpak
`com.moonlight_stream.Moonlight`) et écrit `~/.config/hub/jeux.env` :

```
QT_QUICK_CONTROLS_MATERIAL_ACCENT='#9e6eff'
QT_QUICK_CONTROLS_MATERIAL_PRIMARY='#473173'
```

Pour Steam, rien n'est écrit : générer un WebM demanderait ffmpeg.

### `plymouth DOSSIER`

Écrit `hub.plymouth`, `hub.script`, `hub.png` (le mot HUB dessiné en traits, sans
police : l'initramfs n'en garantit aucune) et `point.png` (disque à la couleur du
profil). Module `script` : fond sombre de la palette, HUB en fondu, trois points qui
respirent l'un après l'autre ; les messages (fsck…) s'affichent en couleur d'accent si
le greffon `label` est présent, sinon rien ne casse. Toujours sombre. Les couleurs sont
celles du profil **au moment de la génération** : Plymouth tourne avant toute session.

## Couleurs

Distance **OKLab, clarté comptée au tiers** : les couleurs de profil sont des pastels
faits pour un fond noir, les accents des logiciels des teintes moyennes ; l'écart de
clarté est systématique et ne dit rien de la teinte. Comptée en entier, le violet part
vers le bleu d'Adwaita ; à la moitié, le turquoise part vers le vert menthe d'Estuary.

| Profil | GNOME | Yaru (26.04) | Estuary |
|---|---|---|---|
| turquoise | teal | prussiangreen | teal |
| violet | purple | purple | violet |
| ambre | yellow | yellow | orange |
| corail | orange | Yaru (orange) | maroon |
| bleu | blue | blue | midnight |
| vert | green | olive (viridian serait plus proche mais **n'existe plus en 26.04**) | green |
| rose | pink | magenta | rose |

**Yaru en 26.04**, liste des fichiers de `yaru-theme-gtk` et `yaru-theme-icon` pour
« resolute » sur packages.ubuntu.com (relevée le 15/09/2026) : Yaru, Yaru-dark, et
blue, magenta, olive, prussiangreen, purple, red, sage, wartybrown, yellow en clair et
sombre. **Ni bark ni viridian.** hub-theme vérifie de toute façon le disque.
`accent-color` : énumération de `gsettings-desktop-schemas` (blue, teal, green, yellow,
orange, red, pink, purple, slate), bornée à l'exécution par `gsettings range`.

## Branchements à faire

Ces fichiers appartiennent à d'autres ; rien n'y est modifié ici.

### `installer/hub-installer.sh`

```sh
install -m 755 installer/theme/hub-theme /usr/local/bin/hub-theme

# Plymouth (root). Générer en tant que l'utilisateur du HUB, pour prendre SON profil :
sudo -u "$UTILISATEUR" /usr/local/bin/hub-theme plymouth /tmp/hub-plymouth
install -d /usr/share/plymouth/themes/hub
install -m 644 /tmp/hub-plymouth/* /usr/share/plymouth/themes/hub/
update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth \
  /usr/share/plymouth/themes/hub/hub.plymouth 200
update-alternatives --set default.plymouth /usr/share/plymouth/themes/hub/hub.plymouth
# Ubuntu 26.04 construit l'initramfs avec dracut (plus update-initramfs) :
dracut --force --regenerate-all
```

La ligne de noyau doit garder `splash` (présent par défaut sur Ubuntu Desktop).

### `installer/gnome-kiosk-script`

```sh
  tv)
    # Avant Kodi, jamais pendant : Kodi réécrit ses réglages en quittant. Un échec du
    # thème ne doit pas empêcher la TV : pas de « && ».
    /usr/local/bin/hub-theme tv >/dev/null 2>&1
    ...kodi ou hub-kodi-lire, inchangé...
    ;;
  gaming)
    /usr/local/bin/hub-theme jeux >/dev/null 2>&1
    [ -f "$HOME/.config/hub/jeux.env" ] && { set -a; . "$HOME/.config/hub/jeux.env"; set +a; }
    # moonlight-qt   (flatpak : flatpak run com.moonlight_stream.Moonlight, l'environnement passe)
    ;;
```

### `installer/hub-vers-bureau` (de préférence) ou `installer/hub-session-par-defaut`

Appliquer **avant** de fermer la session HUB évite que le bureau s'ouvre une seconde
avec l'ancien fond (dconf est commun aux deux sessions) :

```sh
/usr/local/bin/hub-theme bureau >/dev/null 2>&1   # juste avant le SetSession ubuntu
```

Et/ou à l'ouverture du bureau, dans `hub-session-par-defaut`, avant le `exec busctl` :
`/usr/local/bin/hub-theme bureau >/dev/null 2>&1 &` — le thème « auto » y est réévalué
à l'heure d'ouverture.

### `installer/hub-menu.py`

- À l'enregistrement des réglages (message `reglages`), lancer `hub-theme apercu` en
  arrière-plan (`subprocess.Popen`) : le fond est prêt au moment de choisir un mode.
  Il écrit dans `fonds/apercu/`, jamais dans le dossier qu'utilise le bureau.
- Proposer « Remettre le bureau Ubuntu d'origine » → `hub-theme restaurer`.

## Ce qui n'est prouvé qu'en machine virtuelle ou devant la TV

Prouvé ici (tests, et exécution sur un `HOME` jetable) : choix des couleurs, commandes
gsettings (seulement les clés qui changent, lecture réelle sur GNOME 46 avec
`--simuler` : `accent-color` absente y est bien ignorée), sauvegarde/restauration,
édition de `guisettings.xml` et des réglages du skin sans perte, SVG valide aux bonnes
dimensions, PNG valides, rendu SVG de librsvg conforme au rendu Python.

À vérifier en VM Ubuntu 26.04 :

- [ ] GNOME 50 affiche un fond **SVG** (chargeur glycin/librsvg) en fond et au verrouillage ;
- [ ] `accent-color` et `gtk-theme Yaru-*` ensemble : pas de conflit avec le sélecteur
      d'accent d'Ubuntu dans Paramètres → Apparence ;
- [ ] les clés du dock Ubuntu (`dash-to-dock`) existent encore et rendent bien ;
- [ ] Estuary : fond de l'accueil visible, `lookandfeel.skincolors` pris au lancement ;
- [ ] Plymouth : thème inclus par dracut, animation visible (`splash` sur la ligne de noyau).
- [ ] Moonlight : accent pris depuis `jeux.env` (paquet ou flatpak).
