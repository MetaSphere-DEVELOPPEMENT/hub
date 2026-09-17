# Nouveautés du HUB

Ce que chaque version apporte, la plus récente en premier, en une ou deux phrases
lisibles depuis le canapé : le menu affiche cette première section sous « Installer »
(Réglages → À propos).

**La première section doit porter le numéro du fichier `VERSION`.** Un test le vérifie
(`tests/test_version.py`). Marche à suivre pour publier : `installer/mise-a-jour/README.md`.

## 1.0.9 — 18 septembre 2026

Même cause, deuxième moitié : le test comparait aussi les nouveautés affichées à celles
du dépôt, alors que le menu montre celles de la version installée. Les mises à jour
échouaient encore à l'étape des tests.

## 1.0.8 — 18 septembre 2026

Les mises à jour échouaient à l'étape des tests sur un HUB déjà installé : un test
exigeait que le menu affiche le numéro du dépôt, alors qu'il doit afficher celui de la
version installée, forcément plus ancienne pendant une mise à jour.

## 1.0.7 — 18 septembre 2026

L'image du mode, à droite de l'accueil, n'est presque plus rognée : la lueur du fond ne
mord plus que sur un liseré, et on voit le sujet en entier.

Ce qu'il fallait garder lisible par-dessus — l'heure, la date, le profil — l'est mieux
qu'avant, grâce à une ombre discrète sous l'en-tête plutôt qu'un grand dégradé.

## 1.0.6 — 18 septembre 2026

Le HUB cherche les mises à jour toutes les 45 minutes au lieu de toutes les six heures :
une version publiée le soir se voit dans l'heure, sans appuyer sur Rechercher.

## 1.0.5 — 18 septembre 2026

Le téléphone reste la télécommande quand un mode démarre. Passer au Bureau fermait la
session du HUB, et le service de la télécommande s'arrêtait avec elle : le téléphone
perdait la main juste au moment d'en avoir besoin. Le service traverse maintenant le
changement de session, et la page du téléphone se reconnecte toute seule, sans jamais
redemander le code affiché sur la TV.

Un téléphone relié deux fois ne compte plus deux fois. Le HUB reconnaît l'appareil et
renouvelle son entrée au lieu d'en ajouter une, et les téléphones jamais revus depuis
six mois sont oubliés. Réglages → Télécommande montre désormais les téléphones reliés,
leur dernière utilisation, et permet d'en retirer un.

## 1.0.4 — 18 septembre 2026

Le bouton Éteindre ouvre un menu au lieu d'un interrupteur : éteindre, redémarrer, mettre
le HUB en veille (l'écran s'éteint, la télécommande réveille), passer en écran permanent
(Always-On Display : horloge, météo et cadre photo, sans rien arrêter) ou changer de
profil. Chaque entrée dit en une ligne ce qu'elle fait, Annuler est sélectionné d'emblée,
et éteindre comme redémarrer demandent confirmation.

## 1.0.3 — 18 septembre 2026

Les cercles qui s'agrandissaient sur l'accueil « Cinéma » ont disparu : le fond vit
maintenant par ses seules nappes de couleur, sans rien qui traverse l'image.

L'image du mode, à droite, n'est plus recouverte par la couleur du fond : elle passe
devant lui et garde ses vraies couleurs, nette de trois mètres.
## 1.0.2 — 17 septembre 2026

Un HUB installé avant les numéros de version affichait « version inconnue » à côté de
l'empreinte de son commit, et ses mises à jour échouaient à l'étape des tests.

## 1.0.1 — 17 septembre 2026

Le bouton Installer réapparaît quand une version plus récente sort, même si une mise à jour s'est déjà installée depuis le dernier démarrage.

## 1.0.0 — 17 septembre 2026

Première version numérotée. Jusqu'ici le HUB ne se désignait que par l'empreinte de son
commit (« a03afa7 »), illisible : le menu, l'annonce de mise à jour et l'état publié
portent désormais « Version 1.0.0 », l'empreinte restant affichée en petit, là où elle
sert — c'est elle que la signature protège.

Réglages → Affichage : choisir la définition et la fréquence de l'écran à la
télécommande. Sur la TV du salon, le 4K plafonne à 30 Hz et le menu y saccade
(29,4 images/s contre 60,0 en 1920×1080 à 60 Hz). Un mode refusé par la TV revient tout
seul au précédent au bout de 15 secondes.
