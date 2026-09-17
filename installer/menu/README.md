# Menu du HUB

La page (`index.html`, `hub.js`, `hub.css`, et les extensions `temps-ecran.js`,
`allumage.js`, `cadre.js`, `fluidite.js`) est affichée plein écran par `hub-menu`
(WebKitGTK 6.0). Les tests sont dans `tests/menu`.

## Les images des modes

`images/jeu-1/`, `images/jeu-2/` et `images/jeu-3/` contiennent chacun `mode-tv.webp`,
`mode-jeux.webp` et `mode-bureau.webp` : trois jeux d'images fournis par le propriétaire du
HUB et commités dans ce dépôt public. L'accueil montre celle du mode choisi à droite, sur le
motif cinéma. Neuf fichiers, 356 Ko en tout.

Le jeu se choisit par profil dans **Réglages → Arrière-plan → Visuels des modes**, qui offre
cinq choix : les trois jeux, `pictogramme` (le grand pictogramme du mode en filigrane, comme
avant les images) et `aucun` (rien à droite, le fond animé et sa teinte de mode suffisent).
Défaut : `jeu-1` ; un profil enregistré sans la clé `visuels`, ou avec une valeur inconnue,
y revient. Seul le jeu choisi est chargé — trois fichiers, jamais les neuf — et il l'est une
fois pour toutes : changer de mode ne fait ensuite que croiser deux opacités.

Les images sont en paysage (du 3/2 au 16/9), sujet à droite sur fond noir, avec un dégradé
vers le noir à gauche : c'est lui qui les fond dans l'arrière-plan sombre. Pour en changer,
remplacer le fichier en gardant son nom et ce cadrage ; la boîte à l'écran est plus haute que
large, l'image est cadrée à droite et c'est son côté gauche, vide, qui est mangé. Une image
absente ou illisible n'est pas une panne : le pictogramme en filigrane reprend sa place. Les
noms et les chemins sont écrits une seule fois, dans `JEUX_VISUELS` et `sourceVisuel`
(`hub.js`).

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

### Motifs de fond et accueil « Cinéma » (17/09/2026)

Retour sur la TV : « le fond n'est toujours pas animé et décoré, les cartes sont trop bord
à bord ». Le fond est devenu un motif × une couleur (`hub.js`, « Fonds animés ») ; l'accueil
suit la maquette C. Ce que chaque image coûte, par motif (lecture du code, **pas mesuré sur
la TV**) :

| Motif | Toile floue | Toile des traits (960 px de large, transparente) | Calque en plus |
|---|---|---|---|
| nappes (celui d'avant) | 192×108, 5 remplissages | — | — |
| cinéma (défaut d'un profil neuf) | 320×180, 4 remplissages | — (les 3 cercles sont partis le 18/09/2026) | image du mode : calque fixe, masque peint une fois |
| aurore boréale | 320×180, ~320 bandes de 3 px | 150 étoiles (sombre) | — |
| profondeur | 320×180, 3 remplissages | ~45 traits, 3 orbes | — |
| faisceaux | 320×180, 9 coins | 90 grains de poussière | — |

Tout est au rythme du fond (30 i/s au plus), s'arrête avec lui (calque, page cachée, départ,
cadre photo), ralentit en ambiant et se fige en animations réduites. Aucun filtre ni masque
animé ; le `saturate()` de la toile ne reste que sur les nappes. L'accueil n'a plus aucun
`backdrop-filter` : les trois cartes de verre en recalculaient chacune un à chaque image du
fond. La toile des traits ajoute un envoi de 960×540 pixels par image au GPU.

L'image du mode (17/09/2026) remplace le filigrane, qui était le seul calque que le fond
déplaçait à chaque image : elle, elle ne bouge pas. Son coût est un calque de plus à
recomposer par-dessus le fond, large de 104vh et haut de 88vh sur la droite de l'écran —
soit, en 4K, une texture de 2 246 × 1 901 pixels mélangée à chaque image. Rien n'y est
recalculé : le cadrage, les deux dégradés de masque (un par élément : `mask-composite` n'est
pas éprouvé sur la WebKitGTK de la TV) et l'opacité sont fixes, le changement de mode ne
croise que deux opacités (160 ms), et les trois images du jeu choisi sont décodées une fois
pour toutes au chargement (de 74 à 177 Ko de WebP selon le jeu, 11 à 17 Mo décodés). Aucun
`filter`, aucun masque animé.

- [ ] motif cinéma, accueil immobile 30 s : ____ images/s, pire seconde ____
- [ ] motif aurore boréale (le plus de dessin) : ____ images/s ; CPU WebKitWebProcess ____ %
- [ ] motif profondeur : les traits du sol restent-ils nets en 4K, sans scintiller ?
- [ ] nappes (profil d'avant) : rendu identique à la version précédente ?

### Ce que la TV a corrigé (retour du 17/09/2026, version installée)

Une TV rend bien plus contrasté qu'un écran de bureau, et trois défauts ne se voyaient que
là-bas. Les trois sont mesurés par `tests/menu/fonds.test.js`, sur le fond seul, sans le
contenu.

**Les fonds paraissaient figés.** Mesuré sur place : la TV plafonne à **30 Hz en 4K** (son
EDID n'annonce pas de 2160p60, le lien est en HDMI 1.4), et le menu y rend 29,4 images sur
les 30 possibles — rien n'était en panne, le mouvement était simplement trop lent. Un
aller-retour de 25 s avance d'un millième d'écran par image : l'œil ne le voit pas. Toutes
les périodes ont été raccourcies de moitié environ — nappes de 12–29 s à 10–16 s, cinéma de
9–28 s à 6–14 s, rubans de 5–29 s à 4–15 s, profondeur de 6–30 s à 4–15 s, faisceaux de
3–30 s à 2,5–16 s — et les amplitudes des nappes élargies d'un cinquième. Elles restent
toutes différentes les unes des autres, et aucune ne dépasse 30 s. Part de l'image qui change
en 1 s (les 30 images de la TV), moyenne sur huit instants du cycle : **1,9 → 24,8 %** pour
les nappes, 11,9 → 26,1 % pour cinéma, 9,9 → 16,2 % pour profondeur ; et en 5 s au pire
instant du cycle, **9,2 → 18,6 %** pour profondeur. Le propriétaire a depuis basculé la TV en
1920×1080 à 60 Hz, où le menu rend 60 images/s : le plafond de 30 images par seconde, la
suspension sous un calque, le ralenti en ambiant et l'image fixe en animations réduites n'ont
pas bougé, et la zone du héros reste sombre (luminance médiane au plus .07 sur tout un cycle,
comme avant).

**Le sol de « profondeur » passait devant le contenu.** La grille était l'élément le plus
lumineux de l'écran ; la rangée d'onglets et les tuiles semblaient posées dessus. Le trait
du sol est moins blanchi (16 % de blanc au lieu de 35 %), moitié moins opaque, et s'éteint
en descendant : la bande basse (72 % à 100 % de la hauteur), là où vivent les rangées et le
pied, est passée de **.126 à .023** de luminance (98e centile, thème sombre). Le voile du
sol est plus dense, et le soleil de l'horizon respire plus largement — c'est lui, maintenant,
qui porte le mouvement du motif. Même examen sur les autres : les faisceaux s'éteignent
avant le bas de l'écran (bande basse .036 → .027) et leur poussière est plus discrète ;
rubans et nappes n'avaient rien à corriger (leur bas était déjà à .033 et .020).

**Les six couleurs du motif cinéma se ressemblaient toutes.** La teinte du mode, mêlée à
92 % dans la grande tache, mangeait la palette : la planche motif × couleur montrait six
vignettes violettes. La couleur choisie tient maintenant la grande tache (un quart de teinte
du mode) et la tache de droite porte franchement la couleur du mode. Écart chromatique
minimal entre deux couleurs, côté droit de l'écran :
**.024 → .232** avec le violet des Jeux, **.055 → .304** avec le turquoise de la TV.

- [ ] sur la TV : le sol de « profondeur » reste-t-il derrière les onglets et les tuiles ?
- [ ] sur la TV : les six couleurs se reconnaissent-elles d'un coup d'œil, à trois mètres ?
- [ ] sur la TV : faisceaux et rubans, rien de trop clair en bas de l'écran ?
- [ ] sur la TV, en 30 Hz comme en 60 Hz : les fonds bougent-ils assez pour qu'on le voie —
      et pas trop pour qu'on les oublie derrière le texte ?

### Les cercles retirés, l'image rendue nette (18/09/2026)

Retour sur photo de la TV, motif cinéma, jeu d'images 3, mode Bureau : « retire les cercles
animés, elles cassent l'immersion, et la couleur du fond qui passe sur la totalité de
l'image fait que l'image ne se voit pas bien ». Sur la photo, les trois ondes concentriques
traversaient le bureau, et la teinte du fond posait un voile coloré où l'on ne distinguait
plus l'écran, la lampe ni le clavier.

**Les ondes concentriques sont parties.** `lignesCinema`, le jeton `onde` de ses rythmes et
le repère `FILIGRANE` ont été supprimés, pas mis en sommeil ; le motif cinéma ne figure plus
parmi ceux qui tracent, et sa toile des lignes reste cachée — `peindreFond` ne l'efface même
plus (518 000 pixels de moins par image). Il n'a pas fallu accélérer les taches pour
autant : remesuré sans les ondes, le motif change encore **23 % de l'image en 1 s** et 35 %
en 5 s au pire instant du cycle (seuils des tests : 12 % et 15 %), plus que les trois autres
motifs. Un test refuse désormais tout arc, toute ellipse et tout trait tracés par le motif
cinéma sur un cycle entier de 30 s.

**Le fond passe maintenant derrière l'image.** `#visuel-mode` est le dernier des calques de
fond dans `index.html` : le motif, sa teinte et le voile du bas (`.vignette`) sont sous
elle, et non plus dessus. En thème sombre la photo est entière (opacité 1, le jeu 2 compris),
et ce sont ses deux dégradés de masque — éteinte jusqu'à 9 % de sa hauteur, pleine de 24 à
80 %, éteinte à 95 % — qui la retirent sous l'en-tête et sous les rangées, là où le voile
s'en chargeait. Aucun bord, aucun cadre : les fondus sont les mêmes qu'avant, seulement
resserrés à gauche (pleine à 54 % de la boîte au lieu de 64 %).

Mesuré au cœur de l'image (283 × 380 px en 1920×1080, thème sombre), en photographiant deux
fois la même vue sur deux palettes opposées — l'aurore turquoise et la braise orange :

| Vue | Contraste (p95/p5) | Saturation, aurore → braise | Écart entre les deux captures |
|---|---|---|---|
| jeu 3, Bureau (la vue de la photo) | **2,50 → 7,44** | .553 → .276 devient .589 → .589 | 7,7 → **0** |
| jeu 3, TV | 11,69 → 12,91 | .266 → .554 devient .537 → .537 | 7,8 → **0** |
| jeu 1, Bureau | 1,61 → 2,20 | .585 → .369 devient .654 → .654 | 7,7 → **0** |
| jeu 2, Jeux | 3,48 → 4,51 | .569 → .458 devient .612 → .612 | 20,4 → **0** |

Avant, changer la couleur du fond changeait la photo : sa saturation doublait d'une palette
à l'autre. Aujourd'hui les deux captures sont identiques au pixel près — la photo a ses
couleurs, pas celles du fond. En thème clair, où l'image est volontairement retenue pour ne
pas peser sur un fond pâle, elle est passée de .24 à .55 d'opacité : contraste **1,62 →
2,86** (jeu 3, Bureau) et écart entre palettes 24,7 → 14,6.

Rien ne change pour « Aucun » et « Filigrane » : le fond, son voile et le pictogramme sont
exactement ce qu'ils étaient. Les textes du héros, l'en-tête, les onglets et les tuiles
restent au-dessus de 4,5:1 sur les trois jeux, les cinq motifs et les deux thèmes.

- [ ] sur la TV : plus aucun cercle sur l'image, et le motif cinéma bouge-t-il encore assez ?
- [ ] sur la TV : l'écran, la lampe et le clavier du jeu 3 se distinguent-ils de trois mètres ?
- [ ] sur la TV : le bord gauche de l'image reste-t-il invisible, sans arête ni cadre ?
- [ ] sur la TV, thème clair : l'image se voit-elle sans faire une tache sur le fond pâle ?

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

Même mesure, motif cinéma cette fois, avant et après l'image du mode et l'accélération des
mouvements (17/09/2026, même Chromium, 3840×2160, sur 6 s) : accueil immobile 16,9 → 16,8
images/s, et après trois changements de mode 16,9 → 17,4. L'écart est dans le bruit de cette
machine : ni le calque en plus, ni des périodes deux fois plus courtes (le même dessin, à un
autre instant) ne coûtent quoi que ce soit de mesurable ici — ce qui ne dit toujours rien de
l'UHD 630.

### Sur le M720q

Tout se fait par SSH, le menu restant à l'écran. `$XDG_RUNTIME_DIR` vaut en principe
`/run/user/1000` pour l'utilisateur de la session.

**1. La fréquence réelle et ce que WebKit utilise.** Au démarrage, `hub-menu` écrit
une ligne `hub-menu : rendu webkit=… ; acceleration=… ; gsk=… ; ecran=… ;
frequence=… Hz`.

```bash
journalctl --user -b | grep "hub-menu : rendu"     # à vérifier : la sortie d'erreur de la session arrive-t-elle bien là ?
gdctl show                                         # mode courant et fréquence (mutter)
sudo cat /sys/kernel/debug/dri/0/i915_display_info | grep -iE "crtc|mode"
```

- [x] fréquence négociée : **30** Hz (mode **3840**×**2160**), le 17/09/2026 ; la TV
      n'offre aucun 4K à 60 Hz (voir « Le mode de l'écran », plus bas)
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

## Le mode de l'écran : Réglages → Affichage

### Ce qui a été mesuré sur la TV, le 17/09/2026

La TV est une Sony branchée en HDMI-2. **Son EDID ne propose aucun 3840×2160 à 60 Hz** :
le 4K y plafonne à 30 Hz, faute d'un lien HDMI 2.0 (câble). Relevés du compteur du menu :

| Mode | Images/s | Images > 50 ms |
|---|---|---|
| 3840×2160 à 30 Hz | 29,4 | 3 |
| 1920×1080 à 60 Hz | 60,0 | 0 |

D'où le réglage : le propriétaire choisit lui-même entre la netteté du 4K et la fluidité
du 1080p, sans SSH. Pour retrouver le 4K **à 60 Hz**, il faut un câble HDMI 2.0 (ou mieux)
**et** le « Format amélioré » (« HDMI signal format » → « Enhanced ») de l'entrée HDMI dans
les réglages de la TV ; sans les deux, le mode n'apparaît même pas dans la liste.

### Où c'est, et ce que ça fait

Réglages → **Affichage**, juste sous Apparence (`installer/menu/affichage.js`, section
enregistrée par `extensions.sections`). La section montre, en clair, la définition et la
fréquence en cours (« 3840×2160 à 30 Hz — le mouvement paraît saccadé »), puis les modes
proposés par l'écran, du plus confortable au moins bon : 50 Hz et plus d'abord, puis la
plus grande définition. Le mode actif porte une coche, le mot « Actif » et `aria-current`.

**Le filet.** Un mode que la TV refuse laisse l'écran noir : personne ne peut plus
répondre. Après chaque application, une question « Garder ce mode ? » et 15 s de compte à
rebours. Sans « Garder », la page redemande le mode précédent ; `hub-menu` fait de même
quatre secondes plus tard si la page ne répond plus, et à sa fermeture si un mode a été
lancé entre-temps. Le mode gardé est écrit dans les réglages ; « Rétablir au démarrage »
(actif par défaut) le réapplique à chaque allumage, au cas où la TV revienne au sien.

### En ligne de commande, si l'écran reste noir

Tout passe par `gdctl` (livré avec mutter ; `gnome-randr` et `wlr-randr` sont absents
d'Ubuntu 26.04, et `xrandr` ne sert plus à rien en Wayland). Par SSH, le menu restant à
l'écran :

```bash
gdctl show --verbose | grep -A4 -E '^ *[│├└ ]*──[0-9]+x[0-9]+@'   # les modes et leurs propriétés
gdctl show                                                        # le mode courant seul
gdctl set --persistent --logical-monitor --primary \
          --monitor HDMI-2 --mode 1920x1080@60.000                # revenir à un mode sûr
```

`--persistent` écrit le choix dans `~/.config/monitors.xml` : il survit au redémarrage.
Sans cette option, mutter revient seul au mode précédent au bout d'une vingtaine de
secondes si personne ne confirme — la fenêtre « Conserver ces réglages ? » de GNOME Shell,
que la session kiosque n'a pas et que `gdctl` n'appelle jamais. C'est pourquoi le menu
applique pour de bon et tient son filet lui-même.

- [ ] `gdctl show --verbose` : la sortie est-elle bien celle que lit `lire_modes` ?
- [ ] 1920×1080 à 60 Hz appliqué depuis le menu : le compteur monte-t-il à 60 i/s ?
- [ ] mode refusé par la TV (écran noir) : le retour se fait-il bien tout seul ?
- [ ] après redémarrage : le mode gardé revient-il (monitors.xml, ou « Rétablir au démarrage ») ?
- [ ] Kodi règle ses propres modes : le mode du menu revient-il au retour du mode TV ?

### Pistes évaluées, non activées

- **`hardware-acceleration-policy`.** La documentation de l'API 6.0 (webkitgtk.org,
  « stable », 2.54.0, consultée le 17/09/2026) ne propose plus que `ALWAYS` et `NEVER`,
  `ALWAYS` par défaut : `ON_DEMAND` n'existe plus. Le forcer ne changerait rien ;
  la ligne `rendu` dit ce que la 2.52.6 a réellement.
- **Rendre la page en plus basse résolution.** `webkit_web_view_set_zoom_level`
  agrandit la mise en page mais WebKit peint toujours à la résolution de la fenêtre :
  aucun pixel de moins. La seule réduction réelle est un mode de sortie en 1920×1080
  (quatre fois moins de pixels, la TV agrandit), au prix de la netteté du texte, et
  Kodi règle ses propres modes. C'est devenu un réglage à part entière (« Le mode de
  l'écran », plus bas) : sur cette TV, il y gagne aussi 30 images par seconde.
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
- [ ] image du mode : `mask-image` en dégradé et `object-fit: cover` rendus par WebKitGTK ;
      aucune arête à gauche vue du canapé ; le fondu au changement de mode reste court
- [ ] image du mode en thème clair : assez présente pour se voir, assez effacée pour ne pas
      faire une tache sur le fond pâle
- [ ] lecture réelle à 3 m en M et en XL ; zone sûre de la TV à 5 et 8 %
- [ ] cadre photo : horloge sur une photo très claire (le dégradé du coin suffit-il ?)
- [ ] télécommande réelle : la touche maintenue envoie-t-elle `repeat` (pas de rotation) ?
