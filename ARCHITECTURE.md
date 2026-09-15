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
négociée à 65 Mb/s avec un signal à −64 dBm.

**Mesuré le 12 septembre 2026, et bien pire que le débit négocié le laissait
croire : 0,6 à 1,0 Mio/s, soit 5 à 8 Mb/s utiles.** Quatre miroirs Ubuntu testés
tour à tour donnent le même ordre de grandeur — le goulot est la liaison, pas le
serveur d'en face. Une estimation antérieure de « 30 à 35 Mb/s » figurait ici :
elle était cinq fois trop optimiste, tirée du débit négocié au lieu d'être
mesurée.

À 7 Mb/s, la 4K est hors de portée et le 1080p est déjà juste. Le streaming de
jeu, qui veut un débit *stable* et une latence régulière plus qu'un débit de
pointe, est exclu.

_Réserve : un seul relevé, un soir, sur une machine qui faisait tourner d'autres
travaux. À refaire avec `audit/audit.sh` une fois la machine à sa place._

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

## La TV, relevée le 13 septembre 2026

Sony **« KD55XG670 »** d'après le propriétaire. Aucune fiche exacte à ce nom : le
modèle le plus proche est la **KD-55XG7005** (Bravia XG70, 2019). **À confirmer sur
l'étiquette.** Fiche Sony (sony.fr, caractéristiques de la KD-55XG7005) :

- 4K 3840×2160 ; entrée HDMI en 2160p à **24, 25, 30, 50 et 60 Hz** ;
- **3 HDMI**, HDCP 2.3 ;
- **HDR10 et HLG**, pas de Dolby Vision ;
- dalle **native 50 Hz** (« Motionflow XR 200 Hz » est de l'interpolation) ;
- son 2.0, 2 × 10 W.

**Non vérifié :** HDMI-CEC (« BRAVIA Sync ») et la prise ARC ne figurent pas dans la
fiche consultée. À lire dans le mode d'emploi.

### Ce que ça implique

1. **4K à 60 Hz par l'HDMI du M720q : probablement non.** Le M720q a 2 DisplayPort
   1.2 (4K 60 Hz) et 1 HDMI dont la version n'est pas publiée ; sur UHD 630, l'HDMI
   native est en général en 1.4, soit 4K **30 Hz**. **À mesurer au branchement**
   (`audit.sh` relève les modes offerts par la TV). Si c'est confirmé : adaptateur
   **actif DisplayPort → HDMI 2.0**.
2. **La télécommande Sony ne pilote rien sans adaptateur USB-CEC** : le M720q n'a
   pas de CEC (contrainte n° 3).
3. **Kodi : ajustement automatique de la fréquence** à activer. Dalle 50 Hz, TV
   française en 50 Hz, films en 24 i/s.
4. **HDR : pas une promesse.** Il dépend de la sortie vidéo réellement utilisée.

## Ce qui est déjà bon

**La machine démarre sans clavier** : la racine n'est pas chiffrée, et le volume
de travail est monté avec `nofail` — s'il ne s'ouvre pas, le démarrage continue.
C'est exactement ce qu'il faut pour un appareil de salon, et c'était vérifiable
avant de le supposer.

15 Go de RAM, NVMe, PipeWire en place, trois sorties HDMI avec audio : la base est
saine. Le i3-8100T est modeste, mais c'est un « T » — il chauffe peu et se fait
oublier dans un meuble.

## Amorçage, relevé le 12 septembre 2026

Le système est installé **directement sur le NVMe interne** — `/` sur `nvme0n1p2`
(ext4, 237 Go d'un seul tenant, pas de `/home` séparé) et la partition EFI sur
`nvme0n1p1`. Le firmware amorce `\EFI\UBUNTU\SHIMX64.EFI`. Aucune clé USB
n'intervient ; le SSD externe ne porte que des données.

`BootOrder : 000D, 0000, 000C, 000B, 0009, 0004, 0002, 0005, 0001`

| entrée | | |
|---|---|---|
| `Boot000D` | (marque masquée) | le SSD externe, **en tête** — sans chargeur, donc sans effet |
| `Boot0000` | Ubuntu | ce qui démarre réellement |
| `Boot0004` | Generic Usb Device | **sixième** : la clé d'installation ne démarrera pas seule |
| `Boot0002` | Fedora | fantôme, plus aucun système correspondant |
| `Boot0001` | Windows Boot Manager | fantôme, idem |

Les deux fantômes sont sans conséquence. Aucun double amorçage n'existe : le disque
ne porte que la partition EFI et la racine.

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
| **TV** | Kodi, lancé dans la session HUB | Kodi quitte (Accueil ou F12) |
| **Gaming** | client de streaming en plein écran | le client quitte |
| **Desktop** | session GNOME normale | déconnexion |

Aucun mode ne dépend des autres : si Kodi casse, le HUB et le reste vivent. Et le
retour au HUB n'est pas un bricolage — c'est le comportement du gestionnaire de
session, qu'on ne réécrit pas.

## La session kiosque, éprouvée en machine virtuelle

Ce qui suit a été vu, pas supposé : Ubuntu 26.04.1 installée automatiquement dans
la VM d'essai (`vm/lancer-vm.sh`), puis `installer/hub-installer.sh --pour-de-vrai`.
Le détail des preuves est plus bas.

### Ce qui ne marche plus, et pourquoi on n'insiste pas

**Ubuntu 26.04 est Wayland seul.** Plus de serveur Xorg : `/usr/share/xsessions` ne
sert à rien, et un menu écrit en bash dans un terminal n'a nulle part où s'afficher.
La première version de l'installateur visait exactement cela.

### La forme retenue

| Pièce | Où | Pourquoi |
|---|---|---|
| Session `gnome-kiosk-script-wayland` | paquet `gnome-kiosk-script-session` | fournie par GNOME : un compositeur plein écran qui exécute un script, rien d'autre — pas de couche maison |
| `~/.local/bin/gnome-kiosk-script` | `installer/gnome-kiosk-script` | la boucle menu → mode → `exec "$0"`, motif de l'exemple de GNOME : revenir au menu, c'est la fin du mode |
| Menu | `/usr/local/bin/hub-menu` + `/usr/local/share/hub/menu/` | page locale dans WebKitGTK (`python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-webkit-6.0`) ; écrit le choix et se termine |
| Réglages du menu | `~/.config/hub/reglages.json` | écrit par le menu ; l'installateur ne l'écrase jamais |
| Kodi | `kodi --windowing=wayland` dans la session | client Wayland ordinaire, mis plein écran par le compositeur |
| Retour depuis Kodi | `~/.kodi/userdata/keymaps/hub.xml` | Accueil et F12 → `Quit` ; noms de touches lus dans les sources de Kodi 21.3 |
| Bureau | `hub-vers-bureau` | le bureau GNOME ne tourne pas dans un kiosque : on choisit la session `ubuntu` pour la connexion suivante (AccountsService `SetSession`) et on ferme la session HUB |
| Retour du bureau | `hub-session-par-defaut` en autostart (`OnlyShowIn=ubuntu`) | remet le HUB par défaut dès l'ouverture du bureau, quelle que soit la façon d'en sortir ensuite |

### Les pièges rencontrés

- **GDM : connexion automatique ET temporisée.** `AutomaticLogin` ne vaut qu'une
  fois par démarrage ; sans `TimedLoginEnable=true`, `TimedLogin`, `TimedLoginDelay=1`,
  la déconnexion du bureau laisse l'écran de connexion.
- **`X-GNOME-Autostart-Phase` fait ignorer l'entrée** par GNOME 50 : l'autostart du
  bureau n'en porte pas.
- **« Help Improve Ubuntu » recouvre le menu.** `gnome-initial-setup` s'ouvre à la
  première connexion et après une montée de version, y compris dans le kiosque, et
  attend une souris. Il faut `~/.config/gnome-initial-setup-done` **et**
  `~/.config/gnome-initial-setup/upgrade-<VERSION_ID>-done` ; l'installateur dérive
  le numéro de `/etc/os-release`.
- **Kodi demandait « Disabled add-ons — enable Spectrum? »** au premier lancement.
  Le paquet `kodi` recommande `kodi-visualization-spectrum` ; installé par apt, cet
  add-on n'est pas dans le manifeste de Kodi (`/usr/share/kodi/system/addon-manifest.xml`),
  qui l'inscrit désactivé et pose la question (`CApplication::ConfigureAndEnableAddons`,
  sources 21.3). Le manifeste est unique et appartient au paquet : on n'y touche
  pas. L'installateur installe Kodi **sans recommandations** ; une visualisation
  musicale n'a rien à faire sur le HUB. Tout add-on binaire ajouté plus tard par apt
  reposera la question une fois — c'est le comportement voulu par Kodi.

### Ce que la VM ne prouve pas

Le rendu réel (UHD 630, HDMI, fréquence), l'audio, le démarrage à froid du M720q, et
le pilotage autrement qu'au clavier. La VM n'a ni GPU 3D ni sortie audio.

## Audio

### Le matériel

- **Enceintes PC 2.1** : deux satellites et un caisson, entrée analogique (jack).
  Modèle et entrées exactes : **non relevés**.
- **TV Sony** annoncée « KD55XG670 », sans doute **KD-55XG7005** (voir plus haut,
  à confirmer sur l'étiquette). Ses sorties audio — prise casque, optique, ARC — ne
  sont **pas vérifiées** dans la fiche consultée.

### Les deux branchements possibles

| | Jack analogique du M720q → enceintes | HDMI → TV → sortie casque ou optique de la TV → enceintes |
|---|---|---|
| Latence | aucune ajoutée par la TV : le son part avant l'image | la TV retarde son propre son pour l'aligner sur l'image qu'elle traite |
| Volume | celui du HUB ou des enceintes ; **la télécommande de la TV ne le règle pas** | un seul volume, celui de la TV — si sa sortie casque suit la télécommande |
| Dépendances | la sortie jack du M720q (qualité, souffle : non mesurés) | les réglages de la TV (sortie casque « variable » ou « fixe », haut-parleurs coupés ou non) ; l'optique demande un convertisseur si les enceintes n'ont qu'un jack |
| Sources autres que le HUB | n'ont pas de son sur les enceintes | tout ce qui passe par la TV sort sur les enceintes |

**Rien n'est tranché.** Les deux se défendent, et la réponse dépend de mesures qui
n'existent que devant la TV.

### Lip-sync

Si le son est en avance ou en retard, Kodi a un **décalage audio** réglable pendant
la lecture (menu audio de la vidéo, « Décalage audio »), par pas de 25 ms. On le
règle après mesure, pas avant : avec le jack analogique, c'est l'image qui risque
d'être en retard (traitement de la TV) ; avec la sortie de la TV, elle compense en
principe elle-même.

### Contenus 5.1

Les enceintes sont 2.1 : **aucune sortie séparée pour le caisson.** Le caisson reçoit
son grave par le filtre des enceintes, à partir des deux canaux. Kodi doit donc
**mixer en stéréo** : Réglages → Système → Audio → *Nombre de canaux* = **2.0**. Sans
cela, un film 5.1 envoyé tel quel peut perdre les dialogues (canal central) sur une
sortie qui n'en a pas. Le passthrough (Dolby, DTS) n'a pas de sens vers ces
enceintes.

### À mesurer, dans l'ordre

- [ ] relever le modèle des enceintes et leurs entrées (jack, RCA, optique ?)
- [ ] relever les sorties audio de la TV et si sa sortie casque suit la télécommande
- [ ] jack du M720q : souffle à volume nul, niveau suffisant
- [ ] sortie de la TV : même écoute, et comportement des haut-parleurs de la TV
- [ ] décalage son/image mesuré sur chaque branchement (vidéo de synchronisation,
      clap), et valeur du décalage audio Kodi retenue
- [ ] film 5.1 en *Nombre de canaux* 2.0 : dialogues audibles, grave présent
- [ ] **trancher le branchement**, et l'écrire ici avec la date et les mesures

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
- [ ] **Appuyer sur F12 au démarrage** pour choisir la clé. Le firmware ne la prendra
      pas de lui-même : l'ordre d'amorçage relevé le 12 septembre place le SSD externe
      (`Boot000D* (marque masquée)`) en premier, Ubuntu en deuxième, et « Generic Usb Device »
      en sixième. Sans F12, la machine redémarre sur l'Ubuntu qu'on veut remplacer.
- [ ] **Ne pas** activer le chiffrement du disque système.
