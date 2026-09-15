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

Risque connu : Spotify change parfois son protocole et casse librespot jusqu'à la version
suivante. Monter de version = changer l'URL et l'empreinte dans `hub-installer.sh`.

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
seules unités dont le réglage (actif, nom) diffère de leur dernier lancement.

## Pare-feu

`ufw` est inactif sur une Ubuntu neuve. S'il est actif, l'installateur ouvre **au seul
réseau local** (celui de l'interface qui porte la route par défaut) : 5353/udp (mDNS),
5390/tcp (Spotify), 5000/tcp et 6001:6010/udp (AirPlay), 7000:7002/tcp et /udp (UxPlay).

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
