# HUB — Ubuntu, trois modes

Machine de salon branchée à la TV : un menu d'accueil, et trois modes qui en
partent et y reviennent. **TV** (Kodi), **Gaming** (streaming de jeu), **Desktop**
(Ubuntu normal).

## La règle qui prime sur tout le reste

**L'audit matériel précède toute installation.** Pas une discussion sur l'audit :
l'audit, exécuté, mesuré, écrit.

```bash
./audit/audit.sh > audit/rapport-$(date +%F)-<où-en-est-la-machine>.md
```

À chaque session de travail sur ce projet, on commence par là. Et on le relance à
chaque changement d'état de la machine — après réinstallation, après le
branchement de la TV, après l'arrivée du câble réseau. Un audit vieux d'une étape
décrit une machine qui n'existe plus.

Trois mesures n'existent qu'une fois la machine à sa place définitive, et elles
décident de l'architecture : la résolution réellement négociée avec la TV,
l'audio HDMI, et le débit Ethernet réel. Tant qu'elles manquent, le rapport les
laisse en cases à cocher vides. **Ne les remplis pas au jugé.**

## Ce qu'on ne fait pas

- **Pas de double amorçage.** Une seule Ubuntu.
- **Pas de couche exotique.** On se sert de ce qu'Ubuntu fournit : des sessions,
  un gestionnaire de connexion, systemd. Si une solution demande un empilement
  qu'on ne saurait pas réparer un soir de panne, elle est mauvaise pour un
  appareil de salon.
- **Pas d'installation proposée avant d'avoir mesuré** ce qu'elle suppose.
- **Rien qui empêche de démarrer sans clavier.** Pas de chiffrement du disque
  système, pas de saisie au démarrage. Le HUB doit s'allumer comme une TV.

## La forme du HUB

Le HUB n'est pas un système : **c'est une session**. Ubuntu sait déjà lancer des
sessions différentes au démarrage. Chaque mode en est une, et « revenir au HUB »
est la fin normale d'une session — pas un bricolage.

Conséquence voulue : aucun mode ne dépend des autres. Si Kodi casse, le HUB et
les deux autres modes vivent.

## Style

Français partout : commentaires, commits, messages, documents.

Les commentaires disent **pourquoi**, jamais quoi. Un commentaire qui paraphrase
la ligne suivante est du bruit ; celui qui explique la décision qu'on ne peut pas
lire dans le code a de la valeur.

Les titres de commit disent **le défaut réglé**, pas la tâche accomplie.

## Ce qu'on mesure plutôt que de le croire

Ce projet a une dette de confiance envers les chiffres : sur les autres dépôts de
cette machine, cinq documents d'audit annonçaient des valeurs fausses que
personne n'avait remesurées. Ici, toute affirmation chiffrée porte sa date et la
commande qui l'a produite. Quand on ne sait pas, on écrit qu'on ne sait pas.
