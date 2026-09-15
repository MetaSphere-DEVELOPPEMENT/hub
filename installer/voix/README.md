# Commande vocale

On dit **« OK HUB »**, puis la commande ; ou d'une traite : « OK HUB, lance la télé ».
Le mot d'éveil se choisit dans les réglages (`systeme.motEveil` : « OK HUB », « Salut
HUB », « Dis HUB », « HUB » seul, ou un prénom). Français ou anglais selon la langue du
profil actif. **Rien ne quitte la machine** : reconnaissance Vosk hors ligne, aucun
appel réseau.

## Fichiers

| Fichier | Rôle |
|---|---|
| `hub-voix.py` | le service : micro (PipeWire), reconnaisseur Vosk, envoi des événements |
| `hub_voix_logique.py` | tout ce qui décide, sans dépendance : synonymes, mot d'éveil, cible, réglages, détection du micro |
| `test_hub_voix.py` | tests sans micro, sans modèle, sans Vosk : `python3 -m unittest installer/voix/test_hub_voix.py` (depuis `installer/voix`) ou `pytest installer/voix` |
| `hub-voix.service` | unité systemd **utilisateur** |
| `telecharger-modele.sh` | télécharge les deux modèles et vérifie leur empreinte sha256 |
| `remplissage-fr.txt` `remplissage-en.txt` | les 2 000 mots courants ajoutés à la grammaire (voir plus bas) |
| `generer-remplissage.py` | refabrique ces listes depuis une liste de fréquences et le modèle |
| `mesure/banc.py` `mesure/phrases.py` | le banc qui produit les chiffres de « Mesures » (Piper + Vosk, hors ligne) |

## Pourquoi Vosk, et en grammaire restreinte

- **Vosk** (Kaldi) : modèles « small » de 40 Mo, flux continu, résultat à la fin de
  chaque phrase. Sur l'i3-8100T, **6 % d'un cœur** en écoute (mesures plus bas).
- **Grammaire restreinte** : le reconnaisseur ne reçoit que la liste des phrases du
  HUB (`grammaire()`) et `[unk]`. Il ne transcrit plus du français libre, il choisit
  parmi nos mots.
  **Constat mesuré** : Vosk en tire un *vocabulaire pondéré*, pas un ordre imposé ;
  il rend des suites comme « hub éteindre le va hub ». L'analyse le tolère (une seule
  commande dans la phrase, le reste en mots outils). Donner la simple liste des mots
  au lieu des phrases a été essayé : moins bon (siwis 21/30 contre 25/30, upmc
  11/30 contre 15/30, même analyse, 15 septembre 2026).
- **Et 2 000 mots courants à côté** (`remplissage-<langue>.txt` ; la grammaire
  française compte 2 049 phrases de commande et 4 009 entrées au total). Restreint à nos seules phrases, le décodeur **force** toute
  parole dans nos mots : « Lyon veut devenir un hub européen de la logistique »
  devenait « hub de la le steam », et **60 phrases de TV sur 2 904 lançaient une
  commande** (2 %). `[unk]` n'absorbe pas une vraie phrase. Avec les mots courants,
  la TV est transcrite en mots ordinaires, que l'analyse refuse (un mot hors commande
  et hors mots outils annule la phrase) : **0 sur 2 904**. Coût mesuré : facteur temps
  réel 0,030 → 0,034, mémoire 162 → 177 Mo.
  Les mots viennent des listes de fréquences **OpenSubtitles 2018**
  (hermitdave/FrequencyWords) — de la langue parlée, des dialogues de films —,
  filtrés par le vocabulaire du modèle (`generer-remplissage.py`). Aucun mot ne vient
  du corpus de mesure.
- Écartés, et pourquoi :
  - **Whisper** (même *tiny*) transcrit mieux mais par blocs, avec plusieurs secondes
    de latence et un cœur plein par phrase, et il lui faudrait un détecteur d'éveil.
  - **Seuil de confiance Vosk** sur le mot d'éveil (`SetWords(True)`) : **mesuré, sans
    valeur**. Sur 938 « hub » reconnus, la confiance médiane est 1,00 pour les vraies
    commandes et 0,88 pour les phrases de TV ; un seuil à 0,9 garderait 252 vraies sur
    304 et laisserait encore passer 298 fausses sur 634. Les mots de remplissage font
    ce travail bien mieux.
  - **Écoute raccourcie après que la TV a parlé** : rien à gagner, la TV ne produit
    plus une seule commande (flux de 348 phrases enchaînées, 0), et cela gênerait
    quelqu'un qui parle par-dessus la TV.
  - **Double validation des commandes risquées** : `eteindre` passe déjà par l'écran de
    confirmation du menu, et hors menu seul `retour` agit — rien à ajouter.
  - **openWakeWord / Porcupine** : Porcupine demande une licence ; openWakeWord
    demanderait un second modèle (onnxruntime), un entraînement local et surtout des
    dizaines de gigaoctets d'exemples négatifs pour apprendre « HUB ». **Non mesuré** :
    Vosk atteint l'objectif (94 %, 0 faux positif) avec le modèle déjà chargé.

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

**Fenêtre d'écoute.** Le mot d'éveil seul ouvre 6 s d'écoute (`voix:eveil`) ; la commande
qui suit la consomme (`voix:repos`). Sans éveil, une commande est **ignorée** : c'est
la protection contre le son de la TV. Un bruit pendant la fenêtre donne
`voix:incompris` sans la prolonger.

## Le mot d'éveil (`systeme.motEveil`)

| réglage | français | anglais |
|---|---|---|
| `ok-hub` (**défaut**) | « OK HUB », « Okay HUB » | « OK / Okay hub » |
| `salut-hub` | « Salut HUB » | « Hey hub » |
| `dis-hub` | « Dis HUB » | « Hey hub » |
| `hub` | « HUB », « OK HUB » | « hub », « hey / ok hub » |
| un prénom (« Nestor », « Dis Hélène ») | tel quel | tel quel |

**Pourquoi un mot d'éveil à deux mots, mesuré.** Le petit modèle ne connaît pas
« heub » : selon la voix il le rend « aide », « eux », « hum », « hommes », ou le perd.
Avec « HUB » seul, 75 % des commandes françaises passent ; précédé d'un mot que le
modèle connaît bien, l'ancre tient même quand « hub » est massacré — 94 % avec
« OK HUB », 95 % avec « Salut HUB » (tableau des mesures). D'où la règle : après
l'ancre (« ok », « salut », « dis »), **jusqu'à deux mots quelconques sont sautés**
avant la commande ; l'ancre seule, au repos, ouvre l'écoute ; pendant l'écoute, « ok »
redevient la commande qui valide. Une seule commande doit rester dans la phrase, le
reste en mots outils : c'est ce qui empêche une phrase de TV commençant par « Salut »
de lancer quoi que ce soit.

**Un prénom choisi.** Un ou deux mots, lettres seulement. Refusé (et le défaut gardé,
avec la raison dans `voix.json` et le journal) s'il est **inconnu du modèle** — le
service lit la table de mots de `graph/Gr.fst` — ou s'il est **déjà une commande**
(« Télé », « Netflix »). « Nestor » mesuré : 93 % des commandes, 1 éveil intempestif
sur 2 904 phrases de TV.

**Ce que le menu doit proposer** (Réglages → Voix → « Mot d'éveil ») : une liste de
quatre choix — « OK HUB » (conseillé), « Salut HUB », « Dis HUB », « HUB » seul
(déconseillé, chiffres ci-dessous) — et « Un prénom… » avec un champ texte. Écrire
dans `systeme.motEveil` la valeur `ok-hub`, `salut-hub`, `dis-hub`, `hub`, ou le
prénom tel quel. Le menu peut relire `voix.json` une seconde plus tard pour afficher
« ce prénom est inconnu du modèle, « OK HUB » a été gardé » (`refus` = `inconnu`),
« ce mot est déjà une commande » (`commande`) ou « un ou deux mots, lettres
seulement » (`forme`).

**Ce que le menu peut lire.** `$XDG_RUNTIME_DIR/hub/voix.json`, réécrit à chaque
changement : `{"motEveil", "demande", "refus": null|"forme"|"commande"|"inconnu",
"phrases": ["okay hub", "ok hub"], "langue"}`.

**Reste de l'ancienne règle française.** Avec `hub` seul, « aide » suivi d'une commande
nue vaut « HUB <commande> », et « aide » seul au repos ouvre l'écoute : le modèle rend
« heub » par « aide ». Avec les autres mots d'éveil, cette règle ne sert plus.

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
`systeme.voix` à `false` **relâche le micro** (pw-record arrêté) ; `systeme.motEveil`
choisit le mot d'éveil (grammaire refabriquée en 0,01 s, sans recharger le modèle) ; la
`langue` du profil `profilActif` choisit le modèle (`fr` ou `en`, chargé à la demande
puis gardé). Fichier absent ou abîmé : voix active, français, « OK HUB ».

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
**15 et 16 septembre 2026**. Aucun humain : voix de synthèse **Piper**, faute de micro
et de locuteur. Le banc est dans `mesure/` (son en-tête dit comment l'installer) :

```sh
HUB_BANC_DOSSIER=/mnt/ssd/hub-banc venv/bin/python mesure/banc.py \
    /mnt/ssd/projets/hub/installer/voix fr ok-hub --flux --detail
```

### Le corpus (`mesure/phrases.py`)

- **400 commandes** par voix et par condition : 36 commandes du menu (dont 6 en deux
  temps, « OK HUB. » … « Télé. ») et 14 services web, avec le mot d'éveil mesuré.
- **348 phrases de TV et de conversation** qui ne doivent **rien** déclencher, écrites
  exprès pleines de nos mots (télé, films, jeux, bureau, gauche, retour, aide, éteins,
  netflix, arte…), des ancres (« Salut, tu vas bien ? », « Ok, d'accord », « Dis, tu as
  pensé au pain ? ») et de « hub » au sens courant (« le premier hub d'Air France »).
- Deux conditions : **propre**, et **bruit rose 20 dB sous la parole**.
- `--flux` : les 348 phrases enchaînées (0,4 s entre elles) dans un seul reconnaisseur,
  sans jamais de silence long — la TV qui parle sans arrêt.

### Français, 4 voix Piper (siwis, tom, upmc, gilles-low)

288 commandes du menu + 112 services web, 2 904 phrases de TV (348 × 4 voix × 2 conditions).

| mot d'éveil | commandes | services web | faux positifs | éveils sur la TV | flux TV |
|---|---|---|---|---|---|
| **avant** (grammaire sans remplissage, « HUB ») | 236/288 (**82 %**) | 92/112 | **60/2 904** | 171 | **43 commandes** |
| `hub` | 216/288 (75 %) | 86/112 | 0/2 904 | 34 | 0 |
| `dis-hub` | 250/288 (87 %) | 104/112 | 0/2 904 | 9 | 0 |
| prénom « Nestor » | 268/288 (93 %) | 106/112 | 0/2 904 | 1 | 0 |
| **`ok-hub` (retenu)** | **272/288 (94,4 %)** | **107/112 (96 %)** | **0/2 904** | **2** | **0** |
| `salut-hub` | 274/288 (95,1 %) | 105/112 | 0/2 904 | 18 | 0 |

Par voix avec `ok-hub` (commandes + web) : siwis 99/100, tom 98/100, upmc 93/100,
gilles-low 89/100. **Objectif atteint** : 379/400 (**94,8 %**) et **zéro faux positif**,
contre 328/400 (82 %) et 60 faux positifs avant.

`salut-hub` fait jeu égal sur les commandes ; `ok-hub` réveille neuf fois moins souvent
sur la TV (2 contre 18 éveils sans suite), d'où le défaut.

### Voix jamais utilisées pour régler quoi que ce soit

upmc (2ᵉ locuteur), siwis-low, tom ralenti (×1,25), siwis accéléré (×0,8) :

| | commandes + web | faux positifs |
|---|---|---|
| avant (grammaire sans remplissage, « HUB ») | 353/400 (88 %) | 60/2 904, flux : 54 commandes |
| **`ok-hub`** | **383/400 (96 %)** | **0/2 904**, flux : 0 |
| `salut-hub` | 382/400 (96 %) | 0/2 904, flux : 0 |

Une cinquième voix, `fr_FR-mls_1840-low`, a été **écartée** : Vosk ne la comprend pas
même en dictée libre (« OK hub, bureau » y devient « un fils ont besoin »). Avec elle,
`ok-hub` tombe à 277/360 commandes et 3 faux positifs sur 3 630 — c'est la limite de
l'exercice, pas celle du HUB.

### Anglais, 3 voix Piper (lessac, ryan, alan) — non dégradé

180 commandes + 54 services web, 324 phrases de TV.

| mot d'éveil | commandes | web | faux positifs |
|---|---|---|---|
| avant | 176/180 (98 %) | 46/54 | **12/324**, flux : 8 commandes |
| `hub` | 170/180 (94 %) | 46/54 | 0/324 |
| **`ok-hub`** | **180/180 (100 %)** | 46/54 | **0/324**, flux : 0 |
| `salut-hub` (« hey hub ») | 180/180 (100 %) | 48/54 | 0/324 |

Les échecs anglais restants sont des noms de services que le modèle épelle autrement :
« Xbox cloud » sort « eggs xbox cloud », « GeForce » sort « chief force ».

### Service réel, faux micro PipeWire (13–15 septembre 2026)

`pw-loopback` crée une source `Audio/Source` ; `pw-play` y joue les phrases ; un faux
menu écoute le socket. Ces chiffres datent d'avant le remplissage, sauf les deux
dernières lignes, remesurées le 16.

| mesure | valeur |
|---|---|
| CPU sans micro (attente, `pw-dump` / 3 s) | 0,3 % d'un cœur |
| CPU micro présent, silence | 6,1 % d'un cœur (+ pw-record) |
| micro apparu → `voix:micro-present` | 2,8 s |
| micro retiré → `voix:micro-absent` | 2,3 s |
| **fin de la parole → commande reçue par le menu** | **0,44 à 0,70 s** |
| langue changée dans reglages.json | modèle anglais chargé, commandes anglaises reçues |
| `systeme.voix` à false puis true | pw-record arrêté, puis relancé |
| mémoire (RSS), modèle français chargé | **177 Mo** (162 Mo sans le remplissage) |
| facteur temps réel (1 s de son) | **0,034** (0,030 sans le remplissage) |
| grammaire refabriquée (changement de mot d'éveil) | 0,01 s, sans recharger le modèle |

### Ce que ces chiffres ne disent pas

- **Pas de voix humaine, pas de vrai micro, pas de pièce.** Une télécommande à micro
  collée à la bouche sera plus propre que la synthèse bruitée ; un micro USB à 3 m
  d'une TV allumée, bien pire. À remesurer avec le vrai micro, les vraies voix.
- Le corpus de TV est **écrit**, pas enregistré : des phrases de journal, de publicité,
  de fiction et de salon, dites par les mêmes quatre voix que les commandes.
- La TV qui parle **pendant** qu'on dit le mot d'éveil n'est pas mesurée : ici, le
  bruit est un bruit rose, pas une autre voix.
- **La synthèse Piper est aléatoire** (`noise_scale`) : refaire le corpus déplace un
  cas ou deux sur 400 (constaté entre deux passages : 27/28 puis 28/28 sur les services
  web de siwis). Les chiffres sont à ±1, pas au cas près.
- `gilles-low` (voix de basse qualité, nasales absentes de son jeu de phonèmes) tire la
  moyenne vers le bas : c'est voulu, elle tient lieu de mauvaise condition.
