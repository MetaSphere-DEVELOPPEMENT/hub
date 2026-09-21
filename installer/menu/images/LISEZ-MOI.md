# Les images des modes — et leurs variantes claires

Chaque jeu (`jeu-1`, `jeu-2`, `jeu-3`) a trois photos, une par mode : `mode-tv.webp`,
`mode-jeux.webp`, `mode-bureau.webp`. Elles sont **sombres**, faites pour le thème sombre.
En thème clair, le menu est obligé de les retenir à 55 % d'opacité (46 % pour le jeu 2) pour
qu'elles ne fassent pas une tache noire sur le fond pâle, et elles paraissent voilées.

Pour que le thème clair ait de vraies images, dépose à côté de chaque photo sa **variante
claire** : le même nom, avec `-clair` avant l'extension. Rien d'autre à faire, aucun réglage.

## Les neuf fichiers attendus

| Jeu | Mode TV | Mode Jeux | Mode Bureau |
|---|---|---|---|
| 1 | `jeu-1/mode-tv-clair.webp` | `jeu-1/mode-jeux-clair.webp` | `jeu-1/mode-bureau-clair.webp` |
| 2 | `jeu-2/mode-tv-clair.webp` | `jeu-2/mode-jeux-clair.webp` | `jeu-2/mode-bureau-clair.webp` |
| 3 | `jeu-3/mode-tv-clair.webp` | `jeu-3/mode-jeux-clair.webp` | `jeu-3/mode-bureau-clair.webp` |

Les noms sont exacts : minuscules, tirets, extension `.webp` (le menu ne cherche aucun autre
format). Pour convertir un PNG ou un JPEG : `cwebp -q 82 image.png -o mode-tv-clair.webp`.

**Tu peux n'en déposer qu'une partie.** Chaque fichier compte pour lui seul : en thème
clair, le mode qui a sa variante la montre entière (100 % d'opacité, plus de voile) ; celui
qui ne l'a pas garde sa photo sombre retenue, exactement comme aujourd'hui. En thème sombre,
les variantes claires ne sont jamais lues. Un fichier absent n'est pas une erreur.

## Dimensions et proportions

- **Paysage 16/9, 2400 × 1350 pixels.** C'est le bon compromis pour la TV en 3840 × 2160, où
  l'image occupe un cadre de 2246 × 2030 pixels. Minimum raisonnable : 1600 × 900 (la taille
  du jeu 2). Du 3/2 convient aussi (le jeu 1 fait 1168 × 784) ; évite le carré et le portrait.
- **Poids : vise 150 à 300 Ko par image, jamais plus de 500 Ko.** Les neuf photos actuelles
  pèsent 356 Ko à elles toutes. Elles sont lues à chaque allumage et voyagent avec chaque
  mise à jour du HUB ; une image claire et douce se compresse très bien à `-q 80`.

## Le cadrage : ce que le menu fait de ton image

L'image est posée dans un cadre presque carré (104 × 94 % de la hauteur de l'écran), collé
en haut à droite. Elle le remplit en hauteur et **se cale à droite : c'est son côté gauche
qui est coupé**. D'un 16/9, on ne voit que les 62 % de droite ; d'un 3/2, les 74 % de droite.
Puis trois fondus, peints par le menu :

```
 0 %            38 %          60 %                    100 %   ← largeur d'une image 16/9
  ┌──────────────┬─────────────┬───────────────────────┐
  │              │░░░░░░░░░░░░░│▒▒▒▒ ombre de l'en-tête ▒│  0 → 20 % de la hauteur :
  │   coupé :    │░ se fond  ░░│                        │  la date, l'heure et le profil
  │   jamais     │░ dans le  ░░│        LE SUJET        │  s'écrivent ici
  │   visible    │░ fond     ░░│    (centré vers 80 %   │
  │              │░ du menu  ░░│     de la largeur)     │
  │              │░░░░░░░░░░░░░│▒▒▒ s'éteint vers le bas ▒│  80 → 100 % de la hauteur
  └──────────────┴─────────────┴───────────────────────┘
```

- **Le sujet à droite** : entre 60 % et 100 % de la largeur, centré vers 80 % ; en hauteur,
  entre 20 % et 80 %. Tout ce qui compte doit tenir dans ce rectangle. C'est le cadrage des
  photos sombres actuelles : garde le même, les deux thèmes se répondront.
- **La partie gauche, calme et claire.** De 38 % à 60 % de la largeur, l'image se dissout
  dans le fond du menu, qui en thème clair est un gris-bleu très pâle (`#e9edf5`, ou un
  voisin selon la couleur d'arrière-plan choisie). Un détail, une ombre ou un bord net à cet
  endroit ne disparaît pas : il reste en fantôme, à moitié effacé, au milieu de l'écran —
  juste à côté du titre du mode. Un fond uni et clair (blanc cassé, gris perle, proche de
  `#e9edf5`) s'y fond sans qu'on voie où l'image commence. À gauche de 38 %, rien n'est
  visible : inutile d'y soigner quoi que ce soit.
- **Le haut, clair lui aussi.** La date, l'heure et le nom du profil sont écrits en encre
  foncée par-dessus les 20 % du haut. Le menu y pose un voile clair, mais un objet sombre à
  cet endroit gênera quand même la lecture.
- **Le bas s'éteint** : les 20 % du bas disparaissent en fondu sous les rangées de tuiles.
  Rien d'important là non plus.
- **Une image vraiment claire.** Elle est montrée telle quelle, à pleine opacité, sur un
  écran pâle : de grands aplats noirs y feraient la tache que le menu évitait jusqu'ici. Un
  sujet coloré et lumineux sur fond clair, comme une photo de produit.

## Où les déposer

Dans ce dossier du dépôt (`installer/menu/images/jeu-N/`), puis publier une version : la
mise à jour du HUB les installe avec le menu (`/usr/local/share/hub/menu/images/`). Pour
essayer sans attendre, ouvre `installer/menu/index.html?theme=clair&sans-intro` dans un
navigateur. Les noms et les chemins sont écrits une seule fois, dans `sourceVisuel`
(`hub.js`) ; la suite de tests fabrique ses propres variantes factices
(`tests/menu/visuels-clairs.test.js`) et vérifie que ce dossier ne contient que de vraies
images, chacune à côté de sa photo sombre.
