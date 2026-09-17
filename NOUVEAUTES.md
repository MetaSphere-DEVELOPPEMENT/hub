# Nouveautés du HUB

Ce que chaque version apporte, la plus récente en premier, en une ou deux phrases
lisibles depuis le canapé : le menu affiche cette première section sous « Installer »
(Réglages → À propos).

**La première section doit porter le numéro du fichier `VERSION`.** Un test le vérifie
(`tests/test_version.py`). Marche à suivre pour publier : `installer/mise-a-jour/README.md`.

## 1.0.4 — 18 septembre 2026

Le téléphone reste la télécommande quand un mode démarre. Passer au Bureau fermait la
session du HUB, et le service de la télécommande s'arrêtait avec elle : le téléphone
perdait la main juste au moment d'en avoir besoin. Le service traverse maintenant le
changement de session, et la page du téléphone se reconnecte toute seule, sans jamais
redemander le code affiché sur la TV.

Un téléphone relié deux fois ne compte plus deux fois. Le HUB reconnaît l'appareil et
renouvelle son entrée au lieu d'en ajouter une, et les téléphones jamais revus depuis
six mois sont oubliés. Réglages → Télécommande montre désormais les téléphones reliés,
leur dernière utilisation, et permet d'en retirer un.

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
