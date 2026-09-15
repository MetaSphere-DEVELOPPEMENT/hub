# Commande vocale

On dit **« HUB »** (prononcé « heub ») ou **« OK HUB »**, puis la commande ; ou d'une
traite : « HUB, lance la télé ». Français ou anglais selon la langue du profil actif.
**Rien ne quitte la machine** : reconnaissance Vosk hors ligne, aucun appel réseau.

## Fichiers

| Fichier | Rôle |
|---|---|
| `hub-voix.py` | le service : micro (PipeWire), reconnaisseur Vosk, envoi des événements |
| `hub_voix_logique.py` | tout ce qui décide, sans dépendance : synonymes, mot d'éveil, cible, réglages, détection du micro |
| `test_hub_voix.py` | tests sans micro, sans modèle, sans Vosk : `python3 -m unittest installer/voix/test_hub_voix.py` (depuis `installer/voix`) ou `pytest installer/voix` |
| `hub-voix.service` | unité systemd **utilisateur** |
| `telecharger-modele.sh` | télécharge les deux modèles et vérifie leur empreinte sha256 |

## Pourquoi Vosk, et en grammaire restreinte

- **Vosk** (Kaldi) : modèles « small » de 40 Mo, flux continu, résultat à la fin de
  chaque phrase. Sur l'i3-8100T, **6 % d'un cœur** en écoute (mesures plus bas).
- **Grammaire restreinte** : le reconnaisseur ne reçoit que la liste des phrases du
  HUB (1 388 en français, 920 en anglais, `grammaire()`) et `[unk]`. Il ne transcrit
  plus du français libre, il choisit parmi nos mots.
  **Constat mesuré** : Vosk en tire un *vocabulaire pondéré*, pas un ordre imposé ;
  il rend des suites comme « hub éteindre le va hub ». L'analyse le tolère (une seule
  commande dans la phrase, le reste en mots outils). Donner la simple liste des mots
  au lieu des phrases a été essayé : moins bon (siwis 21/30 contre 25/30, upmc
  11/30 contre 15/30, même analyse, 15 septembre 2026).
- Écartés : **Whisper** (même *tiny*) transcrit mieux mais par blocs, avec plusieurs
  secondes de latence et un cœur plein par phrase, et il lui faudrait un détecteur
  d'éveil devant. **openWakeWord / Porcupine** : il faut entraîner « HUB » ou
  accepter une licence. Vosk fait l'éveil et la commande avec un seul modèle.

## Commandes

Après « HUB » / « OK HUB » (anglais : aussi « hey hub »). Les amorces « lance la »,
« mets les », « ouvre les », « va sur » (« launch the », « open », « go to »…) sont
admises devant les destinations.

| envoyé | français | anglais |
|---|---|---|
| `tv` | télé, télévision, tv, films, film, kodi | tv, television, movies, films, kodi |
| `gaming` | jeux, jeu, jeux vidéo, jouer | games, gaming, play, video games |
| `bureau` | bureau, ordinateur, travailler | desktop, computer, work |
| `eteindre` | éteins, éteindre, éteins le hub, éteindre le hub, éteins tout | turn off, shut down, power off, … the hub |
| `reglages` | réglages, paramètres | settings |
| `aide` | aide | help |
| `meteo` | météo, la météo, quel temps | weather, forecast |
| `profils` | profils, profil, changer de profil, utilisateurs | profiles, profile, switch profile, users |
| `retour` | retour, retour au hub, accueil, retour à l'accueil | back, go back, home, go home, back to the hub |
| `gauche` `droite` `haut` `bas` | (à) gauche, (à) droite, (en) haut, (en) bas | left, right, up, down |
| `ok` | ok, okay, valide, valider, ouvre, entrée | ok, okay, select, open, enter |
| `theme:clair` `theme:sombre` | thème / mode clair, sombre | light / dark theme, mode |
| `web:youtube` `web:netflix` `web:twitch` `web:arte` `web:steam` `web:moonlight` | youtube, netflix, twitch, arte, steam, moonlight | idem |
| `web:primevideo` | prime vidéo, amazon prime, amazon | prime video, amazon prime, amazon |
| `web:disneyplus` `web:canalplus` | disney plus, disney · canal plus | idem |
| `web:francetv` | france télé, france télévisions, france tv | france tv, france television |
| `web:geforcenow` `web:xcloud` | geforce now, geforce · xbox, xbox cloud | idem |
| `web:boosteroid` | booster | booster |

Les noms de services sont vérifiés présents dans la table de mots des deux petits
modèles (`graph/Gr.fst`, 15 septembre 2026). « boosteroid » n'y est pas : on dit
« booster ». Les amorces (« lance netflix », « va sur youtube ») sont admises.

`avatars` n'est jamais produit : ce datagramme est réservé à la télécommande.

**Fenêtre d'écoute.** « HUB » seul ouvre 6 s d'écoute (`voix:eveil`) ; la commande
qui suit la consomme (`voix:repos`). Sans éveil, une commande est **ignorée** : c'est
la protection contre le son de la TV. Un bruit pendant la fenêtre donne
`voix:incompris` sans la prolonger.

**Particularité française, mesurée.** Le petit modèle confond « heub » avec « aide ».
D'où deux règles, étroites parce que « Aide-moi à porter ces cartons » existe :
« aide » *immédiatement suivi d'une commande nue* (« aide bureau », sans mot outil ni
`[unk]`) vaut « HUB bureau » ; et « aide » *seul*, au repos, ouvre l'écoute (redire
« aide » ouvre alors l'aide).

## Protocole avec le menu

Menu ouvert = `$XDG_RUNTIME_DIR/hub/menu.sock` existe (socket Unix datagramme). Un
datagramme UTF-8 par événement : les commandes ci-dessus, et `voix:eveil`,
`voix:repos`, `voix:entendu:<texte reconnu>` (borné à 200 octets), `voix:incompris`,
`voix:micro-absent`, `voix:micro-present`. L'état du micro est renvoyé, suivi de
`voix:repos`, **chaque fois que le socket réapparaît** (le menu est relancé à chaque
retour d'un mode et ne sait rien du micro).

Menu fermé (un mode tourne) : seul `retour` agit.

1. **Kodi tourne** (`kodi.bin`, `kodi`, `kodi-wayland`… de l'utilisateur) : le quitter,
   du plus propre au plus brutal :
   1. JSON-RPC **TCP `127.0.0.1:9090`** `Application.Quit` — actif si
      `services.esenabled=true` (défaut de Kodi ; `hub-installer.sh` le pose déjà,
      avec `services.esallinterfaces=false`). Aucun mot de passe.
   2. JSON-RPC **HTTP** (`HUB_KODI_HTTP`, défaut `http://127.0.0.1:8080/jsonrpc`,
      identifiants `HUB_KODI_UTILISATEUR` / `HUB_KODI_MOT_DE_PASSE`) — seulement si le
      serveur web de Kodi a été activé (`services.webserver`) ; **inutile d'activer**
      tant que le 1 marche.
   3. `kodi-send --action=Quit` s'il existe (paquet `kodi-eventclients-kodi-send`,
      facultatif).
   4. `SIGTERM` au processus Kodi, que Kodi traite comme une demande de sortie.
2. **Service web** (`$XDG_RUNTIME_DIR/hub/web.pid` désigne un `hub-web` vivant — un
   fichier resté après un arrêt brutal ne compte pas) : `hub-web --fermer`. Il passe
   avant Kodi, parce qu'il s'ouvre par-dessus la session du HUB.
3. **Bureau GNOME** (`gnome-shell` de l'utilisateur ; la session kiosque tourne sous
   `gnome-kiosk`, qui ne compte pas) : `gnome-session-quit --logout --no-prompt`.
   `hub-session-par-defaut` a déjà remis le HUB comme session suivante.
4. Tout le reste est ignoré hors menu, **`eteindre` compris** : éteindre sans écran de
   confirmation parce que la TV a dit « éteins » serait inacceptable.

Un socket présent mais muet (menu tombé sans nettoyer) est traité comme fermé.

## Réglages

`~/.config/hub/reglages.json`, relu toutes les 2 s (date et taille du fichier) :
`systeme.voix` à `false` **relâche le micro** (pw-record arrêté) ; la `langue` du
profil `profilActif` choisit le modèle (`fr` ou `en`, chargé à la demande puis gardé).
Fichier absent ou abîmé : voix active, français.

## Le micro

Le M720q n'en a pas. Le service démarre sans, lit `pw-dump` toutes les 3 s et capture
avec `pw-record` (16 kHz mono) dès qu'un micro apparaît.

- **La prise jack vide n'est pas un micro.** PipeWire expose la source analogique
  interne même sans rien de branché (relevé du 13 septembre 2026). On l'écarte tant
  que ses routes d'entrée sont `available: no`. Un micro USB ou Bluetooth passe
  devant la prise.
- La capture est un **processus séparé** : un pilote USB qui déraille tue pw-record,
  pas le service ni la session. Micro débranché → `voix:micro-absent` en ~2 s.

## Installation sur Ubuntu 26.04 — ce que l'installateur doit faire

Paquets vérifiés dans l'archive `resolute` (API Launchpad, 15 septembre 2026).
Vosk **n'est pas empaqueté** par Ubuntu (`python3-vosk` absent) : pip dans un venv.

1. Paquets :
   ```sh
   apt-get install -y python3-venv pipewire-bin curl unzip
   ```
   `pipewire-bin` fournit `pw-record` et `pw-dump` (déjà là sur Ubuntu Desktop).
2. Fichiers :
   ```sh
   install -d /opt/hub-voix
   install -m 0755 installer/voix/hub-voix.py /opt/hub-voix/hub-voix.py
   install -m 0644 installer/voix/hub_voix_logique.py /opt/hub-voix/hub_voix_logique.py
   ```
   Les deux fichiers **côte à côte** : `hub-voix.py` importe le module de son dossier.
3. Venv et Vosk, **version figée** :
   ```sh
   python3 -m venv /opt/hub-voix/venv
   /opt/hub-voix/venv/bin/pip install vosk==0.3.45
   ```
   La roue `vosk-0.3.45-py3-none-manylinux_2_12_x86_64` (sha256
   `25e025093c4399d7278f543568ed8cc5460ac3a4bf48c23673ace1e25d26619f`) ne dépend pas
   de la version de Python ; ses dépendances (`cffi`, `requests`, `srt`, `tqdm`,
   `websockets`) ont des roues pour Python 3.14. Toutes sont importées par
   `import vosk`, même si seul `cffi` sert ici.
   _Variante sans pip pour les dépendances : `apt-get install python3-cffi
   python3-requests python3-srt python3-tqdm python3-websockets`, venv créé avec
   `--system-site-packages`, puis `pip install --no-deps vosk==0.3.45`._
4. Modèles (≈ 80 Mo, 1 min 30 mesurée sur la liaison du 15 septembre) :
   ```sh
   sh installer/voix/telecharger-modele.sh /opt/hub-voix/modeles
   ```
   Rejouable : saute ce qui est présent, refuse une empreinte inattendue (vérifié :
   code de sortie 1, rien d'installé).
5. Unité utilisateur pour toutes les sessions :
   ```sh
   install -m 0644 installer/voix/hub-voix.service /etc/systemd/user/hub-voix.service
   systemctl --global enable hub-voix.service
   ```
6. Kodi : `services.esenabled=true` dans `guisettings.xml` (déjà fait par l'étape Kodi
   de `hub-installer.sh`). Rien d'autre.

Journal : `journalctl --user -u hub-voix -f`. Code de sortie 78 = Vosk absent, pas de
relance en boucle (`RestartPreventExitStatus`). Modèle absent : le service reste en
vie et le dit une fois dans le journal.

**Non vérifié** : que la session kiosque (`gnome-kiosk-script-session`) atteigne
`graphical-session.target`, ce dont dépend `WantedBy=`. À constater en VM avec
`systemctl --user status hub-voix` depuis la session HUB.

## Essai sans micro

```sh
hub-voix.py --modeles DOSSIER --langue fr --socket /tmp/faux.sock --fichier a.wav b.wav
```

Les fichiers passent par le même chemin que le micro, à la suite (le temps est celui
du son). Chaque ligne donne l'instant, le texte reconnu, l'événement et sa cible. Hors
menu, `retour` est **simulé** sauf `--agir` : un essai ne ferme pas la session de
celui qui le lance.

## Mesures

Sur le M720q (i3-8100T), Ubuntu 24.04 de travail, Python 3.12, vosk 0.3.45,
**13–15 septembre 2026**. Aucun humain : voix de synthèse **Piper** (4 voix
françaises, 3 anglaises), faute de micro et de locuteur. Scripts de mesure hors dépôt
(`corpus.py`, `live.py` du bloc-notes de la session).

### Service réel, faux micro PipeWire

`pw-loopback` crée une source `Audio/Source` ; `pw-play` y joue les phrases ; un faux
menu écoute le socket.

| mesure | valeur |
|---|---|
| CPU sans micro (attente, `pw-dump` / 3 s) | 0,3 % d'un cœur |
| CPU micro présent, silence | 6,1 % d'un cœur (+ pw-record) |
| mémoire (RSS), modèle français chargé | 160 Mo |
| chargement d'un modèle | 0,6 à 1,2 s |
| micro apparu → `voix:micro-present` | 2,8 s |
| micro retiré → `voix:micro-absent` | 2,3 s |
| **fin de la parole → commande reçue par le menu** | **0,44 à 0,70 s** |
| phrases jouées (fr 5, en 3) | 8/8 reçues, 1 phrase hors commande : rien d'envoyé |
| langue changée dans reglages.json | modèle anglais chargé, commandes anglaises reçues |
| `systeme.voix` à false puis true | pw-record arrêté, puis relancé |

### Corpus de synthèse (`--fichier`)

Par voix : 30 commandes en français (28 en anglais), dont 5 en deux temps (« HUB. » …
« Télé. ») ; 15 phrases de TV ou de conversation **sans** « HUB » mais pleines de nos
mots (« Ce soir à la télé, un grand film »). « HUB » est fait prononcer `[[ˈœb]]`.
Bruit : bruit rose ajouté, ≈ 20 dB sous la parole.

Résultat attendu : **la commande exacte, une seule fois** ; pour les phrases sans
« HUB », **aucune commande**. Mesuré le 15 septembre 2026, analyse dans son état
commité.

| voix Piper | commandes, propre | commandes, bruit | sans « HUB » : rien envoyé (propre / bruit) |
|---|---|---|---|
| fr_FR-siwis-medium | 29/30 | 29/30 | 15/15 · 15/15 |
| fr_FR-tom-medium | 28/30 | 27/30 | **14/15** · 15/15 |
| fr_FR-upmc-medium | 15/30 | 16/30 | 15/15 · 15/15 |
| fr_FR-gilles-low | 15/30 | 15/30 | 15/15 · 15/15 |
| **français** | **87/120 (72 %)** | **87/120 (72 %)** | **59/60 · 60/60** |
| en_US-lessac-medium | 28/28 | 28/28 | 15/15 · 15/15 |
| en_US-ryan-medium | 23/28 | 23/28 | 15/15 · 15/15 |
| en_GB-alan-medium | 28/28 | 28/28 | 15/15 · 15/15 |
| **anglais** | **79/84 (94 %)** | **79/84 (94 %)** | **45/45 · 45/45** |

- Calcul : **facteur temps réel 0,034 à 0,041** (1 s de son coûte 35 à 40 ms d'un cœur).
- Le seul faux positif : tom, « On regarde un film ce soir ? » rendu « ok hub à film
  sur » → `tv`. Des « HUB » isolés entendus dans les phrases de TV : 0 à 2 par série
  de 15, sans suite puisqu'aucune commande ne venait dans les 6 s.
- Les échecs français sont presque tous **« HUB » non reconnu** : upmc le rend
  « thème », « sur », « à » ; gilles (voix basse qualité) mélange tout. Les échecs
  anglais : ryan, « Hub. » dit seul, entendu « help ».
- Avant la tolérance aux mots parasites et la règle « aide » : siwis 20/30, tom 23/30,
  upmc 13/30, gilles 13/30 (13 septembre).

### Ce que ces chiffres ne disent pas

- **Pas de voix humaine, pas de vrai micro, pas de pièce.** Une télécommande à micro
  collée à la bouche sera plus propre que la synthèse bruitée ; un micro USB à 3 m
  d'une TV allumée, bien pire. À remesurer avec le vrai micro, les vraies voix.
- **« HUB » est le point faible en français** : le modèle ne connaît pas ce mot anglais
  prononcé à la française, et le rend selon la voix par « aide », « thème », « sur »…
  Si l'essai réel le confirme, un mot d'éveil plus français (« Salut HUB », ou
  entraîner openWakeWord) serait la suite.
- **La TV qui parle** n'est testée qu'avec des phrases isolées. Une émission qui dit
  « hub » puis « films » dans les 6 s enverrait `tv` au menu ; hors menu, rien.
