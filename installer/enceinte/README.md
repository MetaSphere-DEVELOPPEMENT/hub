# Enceinte réseau

Le HUB apparaît comme enceinte sur les téléphones de la maison :

- **Spotify Connect** : appareil « HUB » dans l'app Spotify (librespot) ;
- **AirPlay, le son** : « HUB » dans le sélecteur AirPlay d'un iPhone ou d'un Mac
  (shairport-sync) ;
- **AirPlay, la recopie d'écran** : « HUB Écran » (UxPlay), affiché plein écran
  par-dessus le menu ou Kodi, qui reprennent la main à la fin.

Le menu montre ce qui joue (titre, artiste, pochette) sur l'accueil et en mode ambiant,
et **Réglages → Enceinte réseau** active ou coupe chaque service et change le nom.

## Fichiers

| Fichier | Rôle |
|---|---|
| `hub_enceinte.py` | coordinateur, lanceurs, crochets (bibliothèque standard seule) |
| `hub-enceinte.service` | le coordinateur : état de lecture et priorité avec Kodi |
| `hub-spotify.service` | librespot |
| `hub-airplay.service` | shairport-sync |
| `hub-airplay-ecran.service` | UxPlay |
| `test_hub_enceinte.py` | `python3 -m unittest installer/enceinte/test_hub_enceinte.py` |
| `preuve/` | image Docker et script de la preuve en conteneur (plus bas) |

Toutes les unités sont **utilisateur**, attachées à `graphical-session.target` comme la
voix et la télécommande : le son passe par le PipeWire de la session, la fenêtre d'UxPlay
par son Wayland, et un service système n'aurait accès à aucun des deux.

## Les choix, et pourquoi

### Spotify : librespot 0.8.0, binaire du paquet raspotify 0.48.2

Vérifié le 15 septembre 2026 dans un conteneur `ubuntu:26.04` (universe, multiverse
activés) : **ni `librespot`, ni `spotifyd`, ni `raspotify` ne sont empaquetés** pour
Ubuntu 26.04.

| | librespot (projet) | spotifyd 0.4.2 | raspotify 0.48.2 |
|---|---|---|---|
| binaire publié | **aucun** (sources seules) | tar.gz + sha512 | .deb amd64, empreinte GitHub |
| dernière version | 0.8.0, 10/11/2025 | 19/11/2025 | **18/07/2026** (librespot 0.8.0 recompilé) |
| annonce mDNS | — | **libmdns** embarqué : un second répondeur sur le port 5353, à côté d'Avahi | **Avahi** (seul backend compilé) |
| métadonnées | `--onevent` | MPRIS + crochet | `--onevent` (variables NAME, ARTISTS, COVERS…) |

Retenu : le **binaire `librespot` extrait du .deb raspotify**. C'est la construction la
plus récente, et elle s'annonce par l'Avahi d'Ubuntu au lieu d'un répondeur mDNS de plus.
On **n'installe pas le paquet** : son `postinst` active et démarre un service *système*
en root sur ALSA, qui prendrait la carte son à PipeWire. L'installateur télécharge le
.deb, vérifie son **SHA-256** (`7f2c232a…b539733`), en extrait `/usr/bin/librespot` vers
`/opt/hub-enceinte/librespot` et rien d'autre. Dépendances d'exécution (`libpulse0`,
`libasound2t64`, `avahi-daemon`) : déjà sur Ubuntu Desktop, posées quand même.

Réglages (`arguments_librespot`) : sortie `pulseaudio` (PipeWire), **volume logiciel**
(le curseur du téléphone ne touche pas le volume du HUB), 320 kb/s, **cache audio limité à
500 Mo** dans `~/.cache/hub/spotify`, identifiants dans `~/.local/state/hub/spotify`,
découverte sur le **port fixe 5390/tcp**.

**Compte Premium obligatoire.** Spotify refuse la lecture sur un appareil Connect tiers
aux comptes gratuits : l'appareil apparaît, mais la lecture échoue
(`PremiumAccountRequired` dans le journal).

**N'importe quel téléphone du réseau peut jouer sur « HUB ».** C'est Spotify Connect tel
que Spotify le conçoit : l'app découvre l'appareil (mDNS) et lui passe les identifiants de
*son* compte, sans code. On le garde. `--disable-discovery` (librespot 0.8.0,
`src/main.rs`) ferait disparaître le HUB de l'app de tous, y compris de la maison, et
imposerait des identifiants enregistrés d'avance ; `--zeroconf-interface` attend une
adresse IP, qui change avec le DHCP. Risque résiduel, accepté : un appareil du réseau
local (pas d'Internet : pare-feu) peut lancer de la musique et, par la règle de priorité,
mettre Kodi en pause. librespot est en Rust et tourne dans le bac à sable (plus bas).

Risque connu : Spotify change parfois son protocole et casse librespot jusqu'à la version
suivante. Monter de version = changer l'URL, l'empreinte et `LIBRESPOT_VERSION` (version
et commit, sans la date de compilation) dans `hub-installer.sh`, puis relancer la preuve :
elle lit ces trois valeurs dans l'installateur.

### AirPlay son : shairport-sync 4.3.7 d'Ubuntu, AirPlay 1

Ubuntu 26.04 livre `shairport-sync 4.3.7-1build1`, compilé
`OpenSSL-Avahi-ALSA-jack-pa-dummy-stdout-pipe-soxr-convolution-metadata-mqtt-dbus-mpris`
(`shairport-sync -V`) : **sans AirPlay 2**. AirPlay 2 demande shairport-sync compilé
`--with-airplay-2` **et** `nqptp`, qui n'est pas empaqueté et doit écouter les ports 319 et
320 (privilégiés) en service système. Compiler deux démons depuis les sources sur un
appareil qu'on veut réparer un soir de panne : non, pas proprement. Ce qu'on perd :
multiroom AirPlay 2 et l'apparition dans l'app Maison ; iOS diffuse toujours vers une
enceinte AirPlay 1 depuis le Centre de contrôle et l'app Musique.

Le paquet active un **service système** sur ALSA : l'installateur le **masque avant
d'installer** le paquet. `hub-airplay` le lance en utilisateur, sortie `pa` (PipeWire),
port **5000/tcp**, **6001-6010/udp**, métadonnées et pochettes dans un tube lu par le
coordinateur, MPRIS sur le bus de session (pour la pause).

**Pas de mot de passe**, décidé le 17/09/2026. shairport-sync 4.3.7 en a un
(`general.password`, « AirPlay 1 only », `scripts/shairport-sync.conf`), mais c'est un
condensé HTTP Digest MD5 vérifié à chaque connexion, sans limite d'essais (`rtsp.c`,
`rtsp_auth`), et un seul mot de passe pour toute la maison et les invités. Qu'iOS le
retienne ou le redemande à chaque fois : **pas trouvé de source**, à relever sur un iPhone
avant d'y revenir. Ce qu'il protégerait se borne à « jouer du son et mettre Kodi en
pause » ; le pare-feu borne déjà l'accès au réseau local, le bac à sable ce qu'une faille
atteindrait.

**`allow_session_interruption = "no"`** (c'était `yes`) : c'est le défaut de
shairport-sync. Un appareil qui arrive pendant qu'un autre joue est refusé
(`get_play_lock`, `rtsp.c`) au lieu de couper la musique en cours. Ce qu'on perd : un
second téléphone de la maison ne prend plus la main d'autorité ; le premier doit choisir
une autre sortie AirPlay, ou quitter le réseau (la session tombe après 20 s,
`session_timeout`). La règle de priorité avec Kodi n'en dépend pas : elle met AirPlay en
pause par MPRIS.

### Recopie d'écran : UxPlay 1.73.2 d'Ubuntu

Le paquet `uxplay` d'Ubuntu (1.73.2), sans service. Nom « HUB Écran » (deux récepteurs
AirPlay sur une machine doivent avoir des noms distincts), `waylandsink` plein écran, son
par `pulsesink`, ports **7000-7002 tcp et udp** (les ports historiques d'UxPlay, UDP
6000-6001, chevauchent ceux de shairport-sync), clé gardée dans
`~/.config/hub/enceinte/uxplay.pem` (sinon l'iPhone voit un nouvel appareil à chaque
démarrage), `-nohold` (un second appareil remplace le premier).

**Pourquoi par-dessus, et pas un « mode » du menu.** Le menu, Kodi et UxPlay sont des
fenêtres du même compositeur kiosque. UxPlay attend en tâche de fond ; à la connexion d'un
iPhone il ouvre sa fenêtre, que le compositeur met plein écran au premier plan ; à la fin de
la recopie il la ferme, et ce qui était dessous — menu ou Kodi — réapparaît. Aucune boucle
de session à interrompre, rien à relancer. Ce « mode temporaire » n'existe que dans l'état
de lecture (`ecran: true`) : le coordinateur met Kodi en pause au début, et le menu, quand
la recopie finit, se représente (`present()`) pour reprendre le clavier.

### Qui peut recopier son écran

Avant le 17/09/2026, **n'importe quel appareil du réseau** prenait la TV plein écran, Kodi
mis en pause — de quoi afficher un faux pavé de saisie à un invité. Deux verrous :

**Un code à quatre chiffres, une fois par appareil.** UxPlay 1.73.2 : `-pin nnnn` (code
fixe) déclenche l'appairage à code d'Apple la première fois qu'un appareil se connecte ;
l'iPhone garde ensuite le HUB en confiance tant que la clé du serveur (`-key`) ne change
pas. **`-reg` est indispensable** : sans registre, « returning clients that skip
pin-authentication are trusted and not checked » (README d'UxPlay, `-reg`) — un client
qui prétend être déjà appairé passerait sans code. Le registre est
`~/.config/hub/enceinte/uxplay-appareils`.

UxPlay n'affiche le code **que dans son journal** (`display_pin` écrit des chiffres en
ASCII dans la console, `uxplay.cpp`), pas à l'écran. D'où :

- un code **fixe**, tiré au hasard (ni 1111, ni 1234, ni 9876) à l'installation, gardé en
  0600 dans `~/.config/hub/enceinte/code-recopie`, lisible dans le menu à tout moment ;
- quand un appareil le demande (`client sent PAIR-PIN-START request`), le coordinateur le
  **montre sur la TV** 60 s : le menu par `recopie-code.json` (protocole plus bas) et, si
  Kodi est à l'écran, une notification Kodi. Le modèle de l'Apple TV : qui voit la TV peut
  appairer ; un appareil ailleurs sur le réseau ne voit rien. En mode Jeux, Web ou bureau,
  rien ne s'affiche : le code est dans Réglages → Enceinte réseau ;
- **cinq codes faux en un quart d'heure ferment la recopie un quart d'heure**
  (`pair-pin-setup (step 3): client authentication failed`). UxPlay ne limite pas les
  essais, et rien n'empêche un programme d'essayer les 10 000 codes à la chaîne ;
- `hub-enceinte code nouveau` tire un autre code **et oublie tous les appareils**
  (registre et clé effacés : un iPhone qui garde l'ancienne clé en confiance ne
  redemanderait rien).

Risques résiduels : le code passe en argument à UxPlay (`/proc/…/cmdline`, lisible des
autres comptes de la machine — le HUB n'en a qu'un) et UxPlay l'écrit dans le journal de
l'utilisateur.

**Aucune recopie pour un profil encadré.** La recopie ne passe pas par `hub-temps-ecran`
et n'était jamais décomptée : un enfant recopiait son iPhone quel que soit son profil. Le
coordinateur ne la compte pas à son tour — il la **refuse** quand le profil actif a une
règle de temps d'écran, **quel que soit le jour** (une limite un seul jour de la semaine,
ou une plage horaire, suffit ; sinon la recopie se rouvrirait à minuit sans que personne
l'ait décidé). Profil actif et règles se lisent comme `hub-temps-ecran` les lit
(`profilActif`, `profils[].tempsEcran.limites|debut|fin`). `reglages.json` illisible :
recopie refusée (on ne sait pas qui regarde), musique gardée.

Mécanisme : `hub-enceinte actif ecran` (l'`ExecCondition`) répond non, et le coordinateur
**surveille `reglages.json`** (date, taille, inode, à chaque tour de boucle) : le menu ne
lance `hub-enceinte appliquer` que si Réglages → Enceinte réseau change, pas au changement
de profil. Au changement vu, `appliquer` relance `hub-airplay-ecran`, dont la condition
arrête une recopie en cours ou la relance pour un profil libre. Un menu et un coordinateur
qui appliquent au même instant passent l'un après l'autre (`flock`), chaque relance est
notée aussitôt : la musique n'est pas coupée deux fois.

Pas couvert : un enfant qui choisit le profil d'un parent **sans code de profil** a la
recopie. Protéger les profils des parents par un code (menu).

## La règle de priorité

**La dernière source qui démarre gagne, Kodi compris.**

| ce qui démarre | effet |
|---|---|
| Spotify, AirPlay ou recopie | Kodi en pause (`Player.PlayPause play:false` sur chaque joueur actif, JSON-RPC `127.0.0.1:9090`) ; les autres sources réseau **qui jouent** sont arrêtées |
| Kodi (`Player.OnPlay` / `Player.OnResume`) | les sources réseau qui jouent sont arrêtées |

Une source en pause n'est jamais arrêtée. Arrêter : AirPlay par **MPRIS `Pause`** (relayé
à l'iPhone) ; Spotify et UxPlay n'ont aucune commande locale, on **relance leur unité** —
le téléphone voit l'appareil disparaître et s'arrête. Kodi éteint : rien à mettre en pause,
le coordinateur se reconnecte toutes les 3 s pour entendre le prochain film.

Pas couvert : le mode web (Netflix dans le navigateur) n'a pas d'interface de pause ; une
musique lancée pendant un film en streaming se superpose.

## Le protocole avec le menu

Le coordinateur écrit `$XDG_RUNTIME_DIR/hub/lecture.json` (absent quand rien ne joue) :

```json
{"source": "spotify", "etat": "lecture", "titre": "…", "artiste": "…", "album": "…",
 "appareil": "iPhone de Samuel", "pochette": "file:///run/user/1000/hub/pochettes/spotify-….jpg",
 "ecran": false}
```

`source` ∈ `spotify airplay ecran`, `etat` ∈ `lecture pause`. `hub-menu` le relit chaque
seconde et envoie à la page `{"type": "lecture", "etat": {…} | null}` ; l'état initial est
dans `HUB_INITIAL.lecture`. Les pochettes sont téléchargées (Spotify, https, 2 Mo au plus)
ou écrites (AirPlay) dans le dossier d'exécution : la page n'a jamais besoin du réseau.

### Le code de la recopie d'écran (contrat pour le menu)

Deux choses à afficher, rien d'autre à décider côté menu :

1. **Réglages → Enceinte réseau**, sous l'interrupteur de la recopie : « Code de recopie :
   `NNNN` ». Le lire par **`hub-enceinte code`** (sortie : quatre chiffres et un saut de
   ligne, code 0 ; le code est créé s'il n'existe pas encore). Le fichier
   `~/.config/hub/enceinte/code-recopie` (0600, même contenu) peut être lu directement,
   mais la commande couvre le premier démarrage. Un bouton « Changer le code » lance
   **`hub-enceinte code nouveau`** (nouveau code sur la sortie ; tous les iPhone
   appairés devront le saisir de nouveau ; la recopie est relancée). Si le profil actif
   est encadré (`hub-enceinte actif ecran` sort en 1 alors que l'interrupteur est
   allumé), dire « Recopie désactivée pour ce profil (temps d'écran) ».
2. **Pendant un appairage**, `$XDG_RUNTIME_DIR/hub/recopie-code.json` (0600) existe :

   ```json
   {"code": "4821", "jusqua": 1789500000}
   ```

   `code` : quatre chiffres (`^\d{4}$`, à vérifier avant affichage) ; `jusqua` : heure
   Unix après laquelle ne plus l'afficher. Le fichier disparaît quand l'appareil est
   appairé (la recopie commence), à la fin du délai (60 s) ou à l'arrêt du coordinateur.
   Le menu l'affiche en grand par-dessus l'accueil : « Recopie d'écran — code à saisir
   sur l'appareil : 4821 ». Même lecture chaque seconde que `lecture.json`.

Les récepteurs parlent au coordinateur par un socket datagramme
`$XDG_RUNTIME_DIR/hub/enceinte.sock` (0600) : `hub-enceinte evenement spotify` est le
crochet `--onevent` de librespot, et chaque unité envoie `evenement <source> arret` en
s'arrêtant, pour que le bandeau disparaisse même après un plantage.

## Réglages

Dans `~/.config/hub/reglages.json` (écrit par le menu), tout actif par défaut :

```json
"systeme": {"enceinte": {"spotify": true, "airplay": true, "ecran": true, "nom": "HUB"}}
```

Chaque unité a `ExecCondition=hub-enceinte actif <source>` : désactivée, elle est sautée
sans échec. Quand le réglage change, le menu lance `hub-enceinte appliquer`, qui relance les
seules unités dont le réglage (actif, nom) diffère de leur dernier lancement. Pour la
recopie, « actif » veut dire aussi « profil actif non encadré » ; le coordinateur relance
`appliquer` de lui-même quand `reglages.json` change (voir « Qui peut recopier »).

## Pare-feu

`ufw` est **inactif sur une Ubuntu neuve** : tout ce qui écoute était joignable de partout
où le HUB l'est. L'installateur (étape 14, fonction `pare_feu`) l'active désormais :
entrée refusée par défaut, sortie permise, et n'ouvre **qu'au réseau local** :

| port | pour |
|---|---|
| 22/tcp | SSH |
| 8790/tcp, 8791/tcp | télécommande (page, HTTPS de la dictée) |
| 5353/udp | mDNS : les téléphones trouvent le HUB |
| 5390/tcp | Spotify Connect |
| 5000/tcp, 6001:6010/udp | AirPlay son |
| 7000:7002/tcp et /udp | recopie d'écran |

« Réseau local », c'est deux sources : le **réseau IPv4 de l'interface qui porte la route
par défaut** (`reseau_local`), et **`fe80::/10`**, les adresses de lien IPv6, qui ne
franchissent pas un routeur. Pas `ufw allow in on <interface>`, pourtant plus court et
valable en IPv4 comme en IPv6 : il ouvrirait aussi ce qui arrive **d'Internet en IPv6
global** par cette interface, si la box le laisse entrer. Un appareil qui ne joindrait le
HUB qu'en IPv6 global est refusé ; iOS et Android essaient aussi l'IPv4.

Sans couper la session SSH en cours : les règles SSH sont posées **avant**
`ufw --force enable`, et toute session SSH établie depuis ailleurs que le réseau local
(VPN…) reçoit sa propre règle (`ss`, processus `sshd`/`sshd-session`). Les connexions
établies devraient de toute façon survivre à l'activation (les règles de base d'ufw
acceptent l'état ESTABLISHED) : pas éprouvé.
Rejouable : les règles existantes sont reconnues (`ufw show added`, valable pare-feu
inactif). Réseau local introuvable (pas de route IPv4 par défaut) : **ufw n'est pas
activé**, une alerte le dit. ufw déjà actif : politique d'entrée laissée telle quelle,
règles ajoutées. Qui gère son pare-feu lui-même : `sudo HUB_PARE_FEU=non ./hub-installer.sh
--pour-de-vrai`.

**À vérifier sur la Freebox** : le pare-feu IPv6 (Freebox OS → Paramètres → Réseau
local / IPv6, selon le modèle) doit refuser les connexions entrantes. ufw protège le HUB,
pas les autres appareils de la maison.

Kodi : son serveur web, UPnP (serveur, lecteur), AirPlay et zeroconf sont **désactivés
explicitement** par l'installateur (étape 5, `services.webserver`, `services.upnp`,
`services.upnpserver`, `services.upnprenderer`, `services.airplay`, `services.zeroconf`
à `false`, identifiants de `system/settings/settings.xml`, Kodi 21.3). Seul reste le
contrôle JSON-RPC sur localhost:9090.

## Bac à sable

Les récepteurs sont du code réseau C, C++ et Rust qui tourne sous le compte de
l'utilisateur. Les quatre unités (commentaires dans `hub-enceinte.service`) ajoutent à
`NoNewPrivileges` :

| réglage | effet | en unité utilisateur |
|---|---|---|
| `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK` | ni AF_PACKET, ni Bluetooth, ni le reste | seccomp : **appliqué** |
| `RestrictNamespaces=yes`, `LockPersonality=yes`, `SystemCallArchitectures=native` | | seccomp : **appliqué** |
| `ProtectHome=tmpfs` + `BindReadOnlyPaths=%t -%h/.config/hub` | dossier personnel et `/run/user` vides, sauf la session (sockets) et les réglages en lecture | espace de noms : **à vérifier** |
| `BindPaths=-%t/hub`, `ConfigurationDirectory=hub/enceinte` (UxPlay), `CacheDirectory=`/`StateDirectory=hub/spotify` (librespot), `CacheDirectory=hub/uxplay` | ce que chacun écrit, et rien d'autre | création des dossiers : appliquée ; montage : à vérifier |
| `InaccessiblePaths=` autorité TLS et jetons de la télécommande ; code de recopie (Spotify, AirPlay son) | | à vérifier |
| `PrivateTmp=yes` | | à vérifier |

**Pourquoi « à vérifier ».** En unité utilisateur, tout ce qui monte des fichiers demande
un espace de noms utilisateur non privilégié (systemd.exec(5), « only available for system
services, or for services running in per-user instances … in which case PrivateUsers= is
implicitly enabled »). Ubuntu restreint ces espaces de noms par AppArmor
(`kernel.apparmor_restrict_unprivileged_userns`). Lu dans les sources de systemd 258
(`src/core/exec-invoke.c`, `apply_mount_namespace`) : si l'espace de noms est refusé,
systemd **continue sans** ces réglages plutôt que d'échouer, tant qu'aucun ne *déplace* de
fichiers (`insist_on_sandboxing` : pas de `TemporaryFileSystem=`, pas de montage dont la
source diffère de la destination). Les unités sont écrites pour rester dans ce cas : un
refus rend le bac à sable inopérant, jamais le service mort. Pas éprouvé : le Mac n'a ni
systemd ni conteneur, et `systemd-analyze verify` n'a pas tourné sur ces versions.

`MemoryDenyWriteExecute=` n'est pas mis : GStreamer (ORC) génère du code à l'exécution
pour UxPlay, et on ne l'a pas mesuré pour les autres. `RestrictRealtime=` non plus :
PipeWire peut demander le temps réel pour les fils audio.

Ce qui reste joignable de l'intérieur, par nécessité : le bus D-Bus de session (MPRIS,
Avahi), PipeWire, Wayland, et les sockets de `/run/user/UID` — y compris celui du menu.

## Limites

- **Latence.** AirPlay 1 fonctionne avec un tampon d'environ 2 s (88 200 trames à
  44,1 kHz, la latence par défaut du protocole que shairport-sync applique) : parfait pour
  la musique, inutilisable pour une vidéo envoyée en « son seul » depuis une app qui ne
  compense pas. La latence de la recopie d'écran n'est **pas mesurée** : à relever, et à
  ne pas promettre pour un jeu.
- **DRM.** Netflix, Disney+, Apple TV+ et Prime Video **bloquent la recopie** (écran noir
  ou refus sur l'iPhone) : UxPlay n'est pas un récepteur agréé (FairPlay).
- **Wi-Fi.** Le wifi USB du M720q est **2,4 GHz seulement, 5 à 8 Mb/s utiles mesurés le
  12/09/2026** (ARCHITECTURE.md). La musique passe (Spotify ≤ 320 kb/s, AirPlay ALAC
  ~1,4 Mb/s, débit du format sans perte 44,1 kHz/16 bits) ; le débit de la recopie
  1080p n'est pas mesuré, mais il approche ou dépasse ce que la liaison tient : attendre
  des saccades en wifi. **Le HUB en Ethernet**, et
  le téléphone sur le 5 GHz de la box.
- **mDNS** ne traverse pas un réseau invité ni un répéteur mal réglé : téléphone et HUB
  sur le même réseau.
- **4K** : UxPlay demande 1080p (pas de `-h265`) ; l'UHD 630 ne décode pas l'AV1 et la
  liaison ne tiendrait pas.

## Preuves

**Conteneur, 15 septembre 2026** (`preuve/`, Ubuntu 26.04, sans systemd : les commandes
des unités lancées à la main dans une session D-Bus avec PipeWire, Avahi et un Weston
sans écran) :

```bash
docker build -t hub-enceinte-preuve installer/enceinte/preuve
docker run --rm -v "$PWD":/depot:ro hub-enceinte-preuve bash /depot/installer/enceinte/preuve/preuve.sh
```

- [x] le .deb raspotify téléchargé correspond à l'empreinte ; `librespot 0.8.0 9c7d7561`
      — **mal relevé** : la ligne complète est `librespot 0.8.0 9c7d7561 (Built on
      2026-07-18, Build ID: PxD46HQ7, Profile: release)`. La preuve l'affichait sans la
      comparer, l'installateur exigeait la ligne courte et a refusé ce binaire sur le
      M720q le 17/09/2026. Depuis, la preuve échoue si la vérification de
      `hub-installer.sh` (`librespot_attendu`, testée par
      `tests/test_hub_installer_librespot.py`) refuse le binaire.
- [x] `systemd-analyze verify --user` sur les quatre unités, sans erreur
- [x] `hub-enceinte lancer spotify|airplay|ecran` : librespot écoute 5390/tcp,
      shairport-sync 5000/tcp, UxPlay 7001/tcp
- [x] `avahi-browse` voit `_spotify-connect._tcp` « HUB Preuve » (5390), `_raop._tcp`
      « …@HUB Preuve » (5000), `_raop._tcp` et `_airplay._tcp` « HUB Preuve Écran » (7001)
- [x] le crochet librespot écrit `lecture.json` via le coordinateur
- [x] shairport-sync publie `org.mpris.MediaPlayer2.ShairportSync` sur le bus de session
- [x] **défaut trouvé** : UxPlay 1.73.2 plante au démarrage (`basic_string: construction
      from null`) avec `-scrsv 1` quand `XDG_CURRENT_DESKTOP` manque ; le lanceur la pose
- [x] tests : priorité, tube AirPlay coupé en morceaux, faux Kodi JSON-RPC, pochettes

**À éprouver sur le M720q**, dans l'ordre :

- [ ] Spotify (Premium) : « HUB » visible, lecture, volume du téléphone, bandeau et pochette
- [ ] iPhone : « HUB » en AirPlay, titre et pochette dans le bandeau, pause depuis Kodi
- [ ] recopie : la fenêtre UxPlay passe **devant** le menu et devant Kodi dans
      gnome-kiosk, plein écran ; à la fin, le menu reprend le clavier
- [ ] les messages d'UxPlay (`connection request from…`, `Open connections: 0`) marquent
      bien le début et la fin d'une recopie ; une simple ouverture du sélecteur AirPlay
      sur l'iPhone ne met pas Kodi en pause
- [ ] `WAYLAND_DISPLAY` et `XDG_CURRENT_DESKTOP` présents dans `systemctl --user show-environment`
      de la session kiosque
- [ ] film dans Kodi + Spotify lancé → Kodi en pause ; reprise du film → Spotify s'arrête
- [ ] décodage matériel H.264 de la recopie (`vah264dec`), charge du i3-8100T
- [ ] latence AirPlay mesurée avec les enceintes branchées (section Audio)
- [ ] `systemd-analyze verify --user` sur les quatre unités (systemd de la 26.04) : les
      nouveaux réglages du bac à sable sont reconnus
- [ ] bac à sable effectif ? `systemctl --user show hub-spotify -p ExecMainPID`, puis
      `sudo ls /proc/<pid>/root/home/samuel` : vide sauf `.cache`, `.config/hub`,
      `.local/state` si l'espace de noms a pris ; tout le dossier sinon. Et
      `journalctl --user -u hub-spotify -b | grep -i namespac`
- [ ] les quatre unités démarrent et jouent **avec** le bac à sable effectif (sinon, dire
      lequel des réglages casse quoi avant d'en retirer un)
- [ ] recopie : l'iPhone demande le code une fois, `recopie-code.json` et la notification
      Kodi apparaissent, puis plus de code à la connexion suivante ; `hub-enceinte code
      nouveau` le fait redemander
- [ ] recopie : un code faux cinq fois → UxPlay fermé 15 min (`journalctl --user -u
      hub-airplay-ecran`)
- [ ] profil avec limite de temps d'écran choisi dans le menu → `hub-airplay-ecran`
      inactif en moins de 2 s, une recopie en cours coupée ; profil libre → il redémarre
- [ ] AirPlay son avec `allow_session_interruption = "no"` : second iPhone refusé tant que
      le premier est connecté ; l'est-il encore après une pause de plusieurs minutes ?
- [ ] mot de passe AirPlay 1 : iOS le retient-il ? (avant de revenir sur la décision)
- [ ] pare-feu : `sudo ufw status verbose` après l'installateur ; Spotify, AirPlay,
      recopie, télécommande et SSH marchent depuis le réseau local ; `nmap -6` depuis
      l'extérieur (4G) sur l'IPv6 globale du HUB ne voit aucun port ouvert
- [ ] Kodi : Paramètres → Services, serveur web, UPnP, AirPlay et zeroconf désactivés
