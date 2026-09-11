# Architecture du HUB

État au 12 septembre 2026. Repose sur `audit/rapport-2026-09-12-machine-de-travail.md`,
mesuré avant la réinstallation.

## La machine

Lenovo **ThinkCentre M720q** Tiny — i3-8100T (4 cœurs, 35 W), 15 Go, Intel UHD 630,
NVMe 238 Go. Aujourd'hui machine de travail ; elle devient le HUB. Le travail part
sur un Mac mini.

## Les cinq contraintes mesurées, et ce qu'elles imposent

### 1. Le réseau — réglé par la place du meuble

Le wifi est une **clé USB Realtek RTL8192EU, 802.11 b/g/n, 2,4 GHz uniquement**,
négociée à 65 Mb/s avec un signal à −64 dBm. Compter 30 à 35 Mb/s utiles, sur la
bande la plus encombrée qui soit : insuffisant pour du streaming de jeu, qui veut
un débit *stable* et une latence régulière plus qu'un débit de pointe.

Le port **Ethernet Intel I219-V** existe. La TV est à portée de câble de la box.

> **Décision : le HUB se branche en Ethernet.** Le wifi devient un secours, pas le
> chemin normal. Cela retire la contrainte la plus lourde de l'audit.

### 2. Aucun Bluetooth

Le noyau ne voit **aucun contrôleur**. Ni manette, ni télécommande, ni casque sans
fil. Une clé USB Bluetooth les débloque tous les trois d'un coup.

### 3. Aucun HDMI-CEC

Pas de `/dev/cec*`, le M720q n'en a pas. **La télécommande de la TV ne pilotera
rien** sans adaptateur USB-CEC.

> Ce point décide de l'interface : on ne dessine pas le même menu pour une croix
> directionnelle que pour une souris. **À trancher avant de dessiner quoi que ce
> soit.**

### 4. Pas de décodage AV1

UHD 630 (CoffeeLake) décode H.264, HEVC et VP9 en matériel. **Pas AV1** — apparu
avec Tiger Lake. Or YouTube et Netflix le poussent massivement. Le repli se fait
sur le processeur, et un i3-8100T à 35 W ne tiendra pas la 4K AV1.

> Conséquence : la 4K AV1 n'est pas une promesse à faire. Le reste passe.

### 5. Pas de jeu local

UHD 630. Le mode Gaming sera du **streaming**, pas du jeu exécuté sur la machine.

> **Question ouverte, et c'est la seule qui reste entière : streamer depuis quoi ?**
> Il n'y a pas de PC de jeu, et un Mac mini ne fait pas tourner les jeux Windows.
> Sans source locale, « Gaming » se réduit à un service en ligne — architecture
> très différente. À trancher avant le prototype.

## Ce qui est déjà bon

**La machine démarre sans clavier** : la racine n'est pas chiffrée, et le volume
de travail est monté avec `nofail` — s'il ne s'ouvre pas, le démarrage continue.
C'est exactement ce qu'il faut pour un appareil de salon, et c'était vérifiable
avant de le supposer.

15 Go de RAM, NVMe, PipeWire en place, trois sorties HDMI avec audio : la base est
saine. Le i3-8100T est modeste, mais c'est un « T » — il chauffe peu et se fait
oublier dans un meuble.

## Le système

**Ubuntu 26.04 LTS « Resolute Raccoon », Desktop, 64 bits.**

Lu dans `/usr/share/distro-info/ubuntu.csv` le 12 septembre 2026 :

| version | sortie | fin de support |
|---|---|---|
| 24.04 LTS Noble Numbat | 2024-04-25 | **2029-05-31** |
| **26.04 LTS Resolute Raccoon** | **2026-04-23** | **2031-05-29** |
| 26.10 Stonking Stingray | 2026-10-15 | 2027-07-15 |

C'est à la fois **la dernière version sortie** et une LTS : le meilleur des deux.
La 26.10 arrive en octobre mais n'est supportée que neuf mois — sur un appareil
qu'on branche et qu'on oublie, ce serait une réinstallation programmée pour
l'été 2027.

**Desktop et non Server** : le mode Desktop exige GNOME de toute façon. Remonter
un bureau depuis Server serait la couche compliquée inutile qu'on s'interdit.

## La forme retenue : un mode est une session

Ubuntu sait déjà lancer des sessions différentes au démarrage. Chaque mode en est
une ; « revenir au HUB » est la fin normale d'une session.

| Mode | Ce qui tourne | Retour au HUB |
|---|---|---|
| **HUB** | un menu plein écran, lancé automatiquement | — |
| **TV** | session autonome de Kodi | Kodi quitte |
| **Gaming** | client de streaming en plein écran | le client quitte |
| **Desktop** | session GNOME normale | déconnexion |

Aucun mode ne dépend des autres : si Kodi casse, le HUB et le reste vivent. Et le
retour au HUB n'est pas un bricolage — c'est le comportement du gestionnaire de
session, qu'on ne réécrit pas.

## Ce qui reste à trancher avant le prototype

1. **Avec quoi pilote-t-on ?** Clé Bluetooth (manette, télécommande), adaptateur
   USB-CEC (télécommande de la TV), ou clavier sans fil. Décide l'interface.
2. **Le mode Gaming streame depuis quoi ?** Aucune réponse aujourd'hui.

## Ce qui n'est pas encore mesuré

Trois choses n'existent qu'une fois la machine à sa place, et elles ne se
supposent pas :

- [ ] résolution et fréquence réellement négociées avec la TV
- [ ] sortie audio HDMI : présence, canaux, passthrough
- [ ] débit Ethernet réel, mesuré vers la box

## Avant la réinstallation

- [x] Sauvegarde de `/home` archivée sur le disque externe
      (`(chemin masqué)`, 1,8 Go,
      intégrité vérifiée) — données personnelles.
- [ ] **Débrancher le SSD externe** pendant l'installation : il porte les projets
      et cette sauvegarde, il n'a rien à faire près d'un installateur qui propose
      de partitionner.
- [ ] Brancher l'Ethernet **avant** de démarrer sur la clé.
- [ ] **Ne pas** activer le chiffrement du disque système.
