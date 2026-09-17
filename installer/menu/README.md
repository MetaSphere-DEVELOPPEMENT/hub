# Menu du HUB

La page (`index.html`, `hub.js`, `hub.css`, et les extensions `temps-ecran.js`,
`allumage.js`, `cadre.js`, `fluidite.js`) est affichée plein écran par `hub-menu`
(WebKitGTK 6.0). Les tests sont dans `tests/menu`.

## Mesurer la fluidité

### D'où l'on part

Le 17/09/2026, sur le M720q branché à la TV : « les animations et transitions ne sont
pas fluides, et le fond n'est pas animé ». Relevé ce jour-là par le propriétaire :
`enable-animations` à true ; profil actif en fond « ocean », animations « completes » ;
rendu GPU Mesa sur l'UHD 630 (`glxinfo`, et « Created gbm renderer » de gnome-kiosk,
EGL) ; écran en 3840×2160 ; `libwebkitgtk-6.0` 2.52.6.

**Pas mesuré :** images par seconde dans le menu, charge CPU de `WebKitWebProcess`,
charge GPU, fréquence réellement négociée (30 ou 60 Hz ; la fiche de la TV annonce
une dalle native 50 Hz, voir ARCHITECTURE.md).

Ce qui a été changé sans pouvoir le mesurer sur la TV (lecture du code, commits du
17/09/2026) : fond redessiné à 30 images/s et arrêté sous les calques, page cachée, au
départ d'un mode et derrière le cadre photo ; mouvements du fond en 12 à 30 s au lieu
de 50 à 160 ; plus de flou animé plein écran ; flous d'arrière-plan réduits aux
cartes et aux panneaux ; liseré tournant sur la seule carte sélectionnée ; boucle des
manettes seulement manette branchée.

### Mesure indicative, hors TV

`cd tests/menu && HUB_NAVIGATEUR=chromium node mesurer-rendu.mjs [copie du dépôt]`,
le 17/09/2026, Chromium 153.0.8010.12 headless de Playwright, **rendu logiciel sur un
Mac (Apple M4)**, 3840×2160, fond océan, images par seconde sur 5 s :

| Écran | Avant (67c6b91) | Après |
|---|---|---|
| accueil | 9,8 | 9,9 |
| réglages ouverts | 3,2 | 59,6 |
| ambiant | 13,9 | 15,6 |

Ce n'est **ni WebKitGTK, ni l'UHD 630, ni un rendu GPU** : ces chiffres comparent deux
versions de la page entre elles, ils ne disent rien de la TV. L'accueil reste lent
dans ce rendu logiciel : le coût du plein écran 4K y domine tout le reste.

### Sur le M720q

Tout se fait par SSH, le menu restant à l'écran. `$XDG_RUNTIME_DIR` vaut en principe
`/run/user/1000` pour l'utilisateur de la session.

**1. La fréquence réelle et ce que WebKit utilise.** Au démarrage, `hub-menu` écrit
une ligne `hub-menu : rendu webkit=… ; acceleration=… ; gsk=… ; ecran=… ;
frequence=… Hz`.

```bash
journalctl --user -b | grep "hub-menu : rendu"     # à vérifier : la sortie d'erreur de la session arrive-t-elle bien là ?
gnome-monitor-config list                          # mode courant et fréquence
sudo cat /sys/kernel/debug/dri/0/i915_display_info | grep -iE "crtc|mode"
```

- [ ] fréquence négociée : ____ Hz (mode ____×____)
- [ ] `acceleration=` : ____ (attendu : always)
- [ ] `gsk=` : ____

**2. Le compteur d'images du menu.** Le fichier le déclenche, la boucle de session
relance le menu qu'on ferme :

```bash
touch "$XDG_RUNTIME_DIR/hub/mesurer-fluidite"
pkill -f /usr/local/bin/hub-menu          # la boucle de gnome-kiosk-script le relance, compteur allumé
journalctl --user -f | grep "hub-menu : fluidité"
# … mesurer …
rm "$XDG_RUNTIME_DIR/hub/mesurer-fluidite"; pkill -f /usr/local/bin/hub-menu
```

Lancé à la main hors session, `HUB_FPS=1 hub-menu` fait de même. Dans un navigateur,
`index.html?fps` (ou `?fps=2` pour une fenêtre de 2 s). Le compteur affiche, en haut
à gauche, les images par seconde sur 5 s, la pire seconde, et les images de plus de
50 ms. Il mesure la cadence de `requestAnimationFrame` dans la page, pas ce que
l'écran affiche.

- [ ] accueil immobile 30 s : ____ images/s, pire seconde ____, images > 50 ms ____
- [ ] accueil, flèches gauche/droite en continu : ____ images/s, pire seconde ____
- [ ] réglages ouverts, parcours du sommaire : ____ images/s, pire seconde ____
- [ ] mode ambiant (touche A) : ____ images/s, pire seconde ____
- [ ] mode ambiant avec cadre photo : ____ images/s, pire seconde ____

**3. Le compteur du compositeur de WebKit.** `WEBKIT_SHOW_FPS=1` dans l'environnement
de `hub-menu`. Non éprouvé ici : la variable ne se transmet pas au menu déjà lancé
par la session, il faut l'ajouter devant `/usr/local/bin/hub-menu` dans
`~/.local/bin/gnome-kiosk-script`, le temps de la mesure. **Attention :** la session
lit le mode choisi sur la sortie standard de `hub-menu` ; si WebKit y écrit ses
compteurs, le choix d'un mode sera faussé pendant ce temps.

- [ ] où s'affiche le compteur (écran, sortie standard, erreur) : ____
- [ ] accueil immobile : ____ images/s

**4. La charge.**

```bash
pgrep -af WebKit                                   # quels processus WebKit tournent
top -d 2 -p "$(pgrep -d, -f WebKitWebProcess)"     # CPU du processus de la page
sudo intel_gpu_top                                 # paquet intel-gpu-tools : « Render/3D » en %
```

- [ ] accueil immobile : CPU WebKitWebProcess ____ %, GPU Render/3D ____ %
- [ ] accueil, flèches en continu : CPU ____ %, GPU ____ %
- [ ] réglages ouverts : CPU ____ %, GPU ____ %

Un GPU à 100 % pendant que le CPU reste bas désigne le remplissage des pixels 4K ; un
CPU saturé sur un cœur désigne la page (peinture, style).

### Pistes évaluées, non activées

- **`hardware-acceleration-policy`.** La documentation de l'API 6.0 (webkitgtk.org,
  « stable », 2.54.0, consultée le 17/09/2026) ne propose plus que `ALWAYS` et `NEVER`,
  `ALWAYS` par défaut : `ON_DEMAND` n'existe plus. Le forcer ne changerait rien ;
  la ligne `rendu` dit ce que la 2.52.6 a réellement.
- **Rendre la page en plus basse résolution.** `webkit_web_view_set_zoom_level`
  agrandit la mise en page mais WebKit peint toujours à la résolution de la fenêtre :
  aucun pixel de moins. La seule réduction réelle est un mode de sortie en 1920×1080
  (quatre fois moins de pixels, la TV agrandit), au prix de la netteté du texte, et
  Kodi règle ses propres modes. À n'envisager que si `intel_gpu_top` montre le GPU
  saturé sur l'accueil.
- **Le grain** (`.grain`, `mix-blend-mode: overlay` plein écran au-dessus du fond
  animé) reste un suspect, gardé parce qu'il fait partie du rendu ; rien n'est mesuré.
- **`will-change`** n'est posé que sur l'accueil pendant qu'il s'efface (départ,
  calque, ambiant). Permanent sur les cartes, il garderait trois calques de plus, avec
  leur flou d'arrière-plan, en mémoire GPU, sans gain démontré.
- **Le cadre photo** (`extensions.css`, flou de 40 px sous un travelling de 30 s) n'a
  pas été touché : à mesurer en ambiant avec des photos avant d'y toucher.
- **Essayer sans reconstruire.** GNOME Web (`epiphany-browser`) utilise, installé en
  paquet deb, la même `libwebkitgtk-6.0` (à vérifier avec `ldd`) et a un inspecteur :
  `file:///usr/local/share/hub/menu/index.html?apercu&fps` en plein écran sur la TV
  permet de désactiver une règle CSS et de lire l'effet sur le compteur.

## Lisibilité à trois mètres et navigation

### Audit de design du 17/09/2026, et après correction

Rendu **Chromium 153 headless (Playwright), pas WebKitGTK**, police Ubuntu Sans chargée
localement, fond aurore. Scripts de l'audit (hors dépôt) : `captures.mjs 1920 3840 1280
--mesures` (taille et contraste de chaque texte sur le fond réellement peint, 95e centile
du fond, sans l'ombre portée du texte), `focus.mjs` (pixels changeant d'au moins 3:1 entre
sélectionné et non sélectionné, rapportés au périmètre de 2 px, WCAG 2.4.13),
`nav-touches.mjs` (vraies touches : flèche puis flèche opposée), `tenue.mjs` (27 écrans,
fr et en, S à XL, débordements). Mêmes scénarios avant (56210f1) et après, taille M, en
français, thème sombre sauf indication.

| Mesure | Avant | Après |
|---|---|---|
| Taille de base en 1080p | 18,6 px (100vmin/58) | 24,5 px (100vmin/44) |
| Textes sous 24 px (équivalent 1080p) | 645 sur 792 (81 %) | 116 sur 786 (15 %), tous à 22,1 px (--t-1) |
| Plus petit texte (équivalent 1080p) | 13,4 px | 22,1 px |
| Tailles de police en dur | 37 | 0 (7 jetons et une taille d'affiche) |
| Textes sous le seuil WCAG 1.4.3, sombre | 138, le pire à 1,67:1 | 0 |
| Textes sous le seuil, clair | 33, le pire à 1,47:1 | 2 (cadre photo sur neige, 3,46–3,5:1 sans l'ombre) |
| Anneau de focus conforme 2.4.13 (9 cibles × 2 thèmes × 3 définitions) | anneaux de 1,5 à 2 px, non conformes | 54 sur 54 |
| Allers-retours non réversibles, accueil (18 cibles) | 24 | 0 |
| Allers-retours non réversibles, éditeur de profil (16 cibles) | 25 | 0 |
| Sorties du contenu vers une autre section des réglages | 67 | 0 |
| Entrées du sommaire inatteignables à l'œil en XL | 3 | 0 (il défile) |

Les trois définitions donnent les mêmes proportions : tout est en rem de 100vmin.

### À vérifier sur la TV

- [ ] WebKitGTK 2.52 : `color-mix()`, `outline` qui suit `border-radius`, `:root[data-taille]`
- [ ] lecture réelle à 3 m en M et en XL ; zone sûre de la TV à 5 et 8 %
- [ ] cadre photo : horloge sur une photo très claire (le dégradé du coin suffit-il ?)
- [ ] télécommande réelle : la touche maintenue envoie-t-elle `repeat` (pas de rotation) ?
