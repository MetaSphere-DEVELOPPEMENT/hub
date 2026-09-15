# Télécommande téléphone

Le téléphone devient la télécommande du HUB : on scanne le QR code affiché sur la TV,
on tape le code à 6 chiffres, et la page offre un pavé tactile (ou la croix
directionnelle), OK, Retour, Accueil, les modes, le volume, la dictée d'une commande,
l'envoi de texte (recherche dans Kodi) et l'envoi d'une photo de profil. Elle
s'ajoute à l'écran d'accueil et s'ouvre alors comme une app.

**Pourquoi.** Le M720q n'a ni Bluetooth ni HDMI-CEC (ARCHITECTURE.md, contraintes 2
et 3) : la télécommande de la TV ne pilote rien. Un téléphone sur le wifi de la
maison n'a rien à installer.

## Fichiers

| Fichier | Rôle |
|---|---|
| `hub_telecommande.py` | le service (bibliothèque standard seule) et la ligne de commande de révocation |
| `page.html` | la page du téléphone, CSS et JS inclus, aucune ressource externe |
| `hub-telecommande.service` | unité systemd **utilisateur** |
| `qrcode.js` | générateur de QR code pour le menu (MIT, vendorisé, voir l'en-tête) |
| `test_telecommande.py` | tests : `python3 -m unittest installer/telecommande/test_telecommande.py` |
| `test_navigateur.mjs` | tests dans Chrome en vue téléphone (voir « Ce qui est prouvé ») |
| `banc_essai.py` | le service sur 127.0.0.1 avec un faux menu, pour `test_navigateur.mjs` — **pas installé** |

## Installation — ce que `hub-installer.sh` doit faire

```bash
install -D -m 0755 telecommande/hub_telecommande.py  /usr/local/lib/hub/telecommande/hub_telecommande.py
install -D -m 0644 telecommande/page.html            /usr/local/lib/hub/telecommande/page.html
install -D -m 0644 telecommande/README.md            /usr/local/lib/hub/telecommande/README.md
install -D -m 0644 telecommande/hub-telecommande.service /usr/local/lib/systemd/user/hub-telecommande.service
install -D -m 0644 telecommande/qrcode.js            /usr/local/share/hub/menu/qrcode.js
ln -sfn /usr/local/lib/hub/telecommande/hub_telecommande.py /usr/local/bin/hub-telecommande
systemctl --global enable hub-telecommande.service
```

- `page.html` doit rester **à côté** de `hub_telecommande.py` : c'est là qu'il la lit
  (le lien de `/usr/local/bin` est résolu).
- **Logique de la voix.** Le service réutilise `hub_voix_logique.py` (envoi au socket
  du menu, détection de Kodi et du bureau). Il le cherche dans `$HUB_VOIX_DOSSIER`,
  `../voix` (le dépôt), `/usr/local/lib/hub/voix/`, puis `/opt/hub-voix/`.
  L'installateur doit donc poser `voix/hub_voix_logique.py` dans l'un d'eux — il ne
  le fait pas aujourd'hui (seul `hub-voix.py` est copié). Sans ce module, la
  télécommande pilote encore le menu et le volume, mais ni Kodi ni le bureau menu
  fermé ; le journal le signale au démarrage.
- **Pare-feu.** `ufw` est inactif par défaut sur Ubuntu. S'il est activé :
  `ufw allow from 192.168.0.0/16 to any port 8790 proto tcp` (adapter au réseau).
- **Pare-feu, HTTPS.** Ouvrir aussi 8791 (l'installateur le fait pour les deux ports).
- **Dictée.** Rien à ajouter si la commande vocale est installée (étape 10) : le
  service trouve `hub-voix.py` dans `/opt/hub-voix/`, lance son travailleur avec
  `/opt/hub-voix/venv/bin/python` et les modèles de `/opt/hub-voix/modeles`
  (`HUB_VOIX_DOSSIER`, `HUB_VOIX_PYTHON`, `HUB_VOIX_MODELES` pour forcer). Sans elle,
  la dictée répond « non installée » et tout le reste marche.
- **Le menu doit afficher l'empreinte** `empreinteRacine` du fichier d'état à côté du
  code (voir plus bas) : c'est ce que le téléphone compare avant de faire confiance
  au certificat. Tant qu'il ne le fait pas : `hub-telecommande --empreinte`.
- Aucune dépendance à installer : `python3`, `openssl`, `wpctl` (paquet
  `wireplumber`) et `gnome-session-quit` sont déjà sur Ubuntu Desktop.

Essai sans installer : `python3 installer/telecommande/hub_telecommande.py -v`.

## Port et adresse

**Port 8790, fixe** : l'URL finit en favori sur les téléphones, et le jeton est lié à
l'origine `http://ip:8790`. **Port 8791 : le même service en HTTPS** (dictée). Deux
origines distinctes pour le navigateur : le passage de l'une à l'autre se fait par un
ticket (« Ouvrir la version sécurisée »), sans retaper de code.

Le service écoute **sur l'adresse du réseau local seule**, pas sur `0.0.0.0` : celle de
l'interface qui porte la route par défaut (Ethernet sur le HUB). Une interface de VM,
Docker ou VPN n'expose donc pas la télécommande. Tant qu'il n'y a pas d'adresse (au
démarrage de la session), il attend ; si l'adresse change (bail DHCP), il rouvre
l'écoute dessus et met à jour le fichier d'état. `--adresse` et `--port` forcent.

**À faire sur la box : réserver l'adresse du HUB en DHCP.** Si elle change, le
téléphone voit une autre origine, son jeton (dans son `localStorage`) n'y est plus, et
il faut ré-appairer.

## Sécurité

Réseau local d'un particulier : on ne se défend pas contre un attaquant déjà sur le
wifi qui écoute le trafic (HTTP en clair, protégé seulement par le WPA du wifi), mais
la télécommande n'est ouverte ni à un invité, ni à une page web étrangère.

- **Appairage.** Code à 6 chiffres affiché sur la TV : il faut être dans la pièce.
  Renouvelé à chaque démarrage, après chaque appairage réussi, toutes les 5 minutes,
  et après 20 codes faux toutes adresses confondues.
- **Limite d'essais.** 5 essais par minute par adresse IP (réussites comprises),
  réponse 429 avec `Retry-After` au-delà.
- **Jeton.** `secrets.token_urlsafe(32)` (256 bits), gardé par le téléphone dans
  `localStorage`. Le HUB n'en garde que l'**empreinte SHA-256**, dans
  `~/.config/hub/telecommande-jetons.json` (0600). Envoyé en `Authorization: Bearer`,
  jamais en cookie : pas de CSRF possible.
- **Liste blanche.** `tv gaming bureau eteindre reglages aide meteo profils retour
  gauche droite haut bas ok theme:clair theme:sombre` (les noms du socket du menu, un
  test vérifie qu'ils sont identiques à `hub-menu.py`) plus `accueil volume:+
  volume:- texte`. Tout le reste : 400.
- **Rien d'autre n'est servi** que `/` (la page, lue une fois au démarrage), le
  manifeste, les icônes (calculées en mémoire), le certificat **racine** (public) et
  l'API. Les clés privées ne sont lues par aucune route (test sur les deux ports).
  Aucun chemin reçu du réseau ne touche le disque : le nom des photos est fabriqué
  par le serveur.
- **En-têtes.** CSP `default-src 'none'`, script et style autorisés **par empreinte**
  (pas de `unsafe-inline`), `connect-src 'self'`, `frame-ancestors 'none'` ;
  `manifest-src 'self'` ; sur la page http seulement, `connect-src` admet aussi
  l'origine `https://même-nom:8791` (sonde du certificat) ;
  `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Cache-Control: no-store`, `Permissions-Policy: microphone=(self), camera=()`.
  **Aucun en-tête CORS.**
- **Rebinding DNS.** L'en-tête `Host` doit être `ip:8790`, `nom-machine:8790` ou
  `nom-machine.local:8790`, sinon 421. Les POST exigent `application/json` (ou
  `image/jpeg` pour la photo) : une page étrangère ne peut les envoyer sans prévol
  CORS, auquel on ne répond jamais favorablement. `Sec-Fetch-Site: cross-site` : 403,
  sauf une **navigation de premier niveau vers `/`** (c'est ce qu'envoie le passage
  http → https, schéma différent donc « autre site ») et `/sonde` en https (204 vide).
- **Éteindre** ne part qu'au menu, qui demande confirmation sur la TV. Menu fermé,
  c'est refusé.
- Corps limités à 2 Kio (JSON), 2 Mio (photo) et 10 s de son (dictée, WAV 16 kHz
  mono 16 bits exigé, rien d'autre n'atteint le reconnaisseur) ; délai de 10 s par
  connexion, poignée de main TLS comprise.
- **Ticket de transfert** http → https : 256 bits, usage unique, 2 minutes, accepté
  sur l'origine https seulement ; il voyage dans le fragment de l'URL (jamais envoyé
  au serveur par le navigateur) et la page l'efface de l'adresse avant tout.

### Autorité locale (HTTPS)

Créée au premier démarrage dans `~/.config/hub/telecommande-tls/` (dossier 0700) :

| Fichier | |
|---|---|
| `racine.key` (0600) · `racine.crt` | ECDSA P-256, 10 ans, `CA:TRUE, pathlen:0` |
| `hub.key` (0600) · `hub.crt` | 397 jours, `serverAuth`, SAN : IP du HUB, `hub.local`, `nom-machine.local` |
| `hub.json` | adresse, noms, échéance, empreinte de la racine qui l'a signé |

- **Contraintes de nom critiques** sur la racine : 10/8, 172.16/12, 192.168/16,
  169.254/16, 127/8 et `.local`. Même volée, la clé ne signe rien qu'un téléphone
  accepterait pour un site public (test : un certificat `banque.example` signé par la
  racine est refusé, « permitted subtree violation »).
- Le certificat du HUB est **réémis tout seul** si l'adresse DHCP ou le nom change,
  ou 30 jours avant l'échéance (vérifié toutes les heures) ; la racine, seule chose
  installée sur les téléphones, ne change pas. Adresse non privée, horloge avant
  2026 ou openssl absent : pas de HTTPS, la télécommande http continue.
- 397 jours : sous la limite d'Apple (825 j) et sous celle des autorités publiques
  (398 j), si un navigateur l'étendait un jour aux racines installées à la main.
- Réinitialiser : arrêter le service, supprimer le dossier, relancer — puis
  réinstaller la nouvelle racine sur chaque téléphone (et retirer l'ancienne).
- Le téléchargement de la racine passe en **http** : quelqu'un sur le wifi pourrait
  la remplacer. D'où l'empreinte SHA-256 affichée sur la TV (fichier d'état), à
  comparer avec celle que montre le téléphone avant d'activer la confiance.

## Révoquer un téléphone

```bash
hub-telecommande --lister            # id, nom, date d'appairage, dernier usage
hub-telecommande --revoquer 2ab063   # un téléphone
hub-telecommande --revoquer-tout     # tous
```

Effet immédiat, sans redémarrer le service : il relit le fichier dès qu'il change. Le
téléphone révoqué revient tout seul à l'écran d'appairage. Depuis le téléphone,
« ⋯ → Oublier ce téléphone » révoque aussi son propre jeton côté HUB.

## Où vont les commandes

| Situation | Destination |
|---|---|
| socket du menu présent et joignable | datagramme au menu (`accueil` y devient `retour`) ; `texte` refusé (le menu n'a pas ce message) |
| menu fermé, Kodi lancé | JSON-RPC : `Input.Left/Right/Up/Down/Select/Back`, `Input.SendText` (avec `done: true`), `accueil` = `Application.Quit` puis SIGTERM en dernier recours |
| menu fermé, bureau GNOME | `accueil` = `gnome-session-quit --logout --no-prompt` ; le reste est sans effet |
| n'importe où | `volume:+` / `volume:-` = `wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%±` (plafonné à 100 %) |

Kodi est joint en **TCP 9090** (actif si « Autoriser le contrôle à distance par des
applications sur ce système » l'est, vrai par défaut), puis par son serveur web
(`HUB_KODI_HTTP`, `HUB_KODI_UTILISATEUR`, `HUB_KODI_MOT_DE_PASSE`, mêmes variables
que `hub-voix`). `Input.SendText` n'a d'effet que si un clavier est ouvert dans Kodi
(champ de recherche).

## API HTTP

| Requête | Jeton | Réponse |
|---|---|---|
| `GET /` | non | la page |
| `POST /api/appairer` `{"code":"123456","nom":"Pixel 8"}` | non | 200 `{"jeton","id","nom"}` · 403 code faux · 429 trop d'essais |
| `POST /api/commande` `{"nom":"gauche"}` ou `{"nom":"texte","texte":"Dune"}` | oui | 200 `{"ok","cible","raison"?,"volume"?}` · 400 hors liste · 401 |
| `GET /api/etat` | oui | `{"ok":true,"contexte":"menu"\|"kodi"\|"bureau"\|null}` |
| `POST /api/oublier` `{}` | oui | révoque le jeton présenté |
| `POST /photo-profil` (corps JPEG brut, `Content-Type: image/jpeg`) | oui | 200 `{"ok":true,"fichier":"telephone-AAAAMMJJ-HHMMSS.jpg"}` · 400 pas un JPEG · 413 > 2 Mio · 415 |
| `GET /manifest.webmanifest`, `/icone-32.png`, `/icone-192.png`, `/icone-512.png`, `/apple-touch-icon.png` | non | manifeste, icônes |
| `GET /hub-racine.crt` | non | la racine en DER (`application/x-x509-ca-cert`) · 404 si HTTPS désactivé |
| `GET /api/certificat` | non | `{"disponible","securise","https":"https://nom:8791/","empreinte"}` |
| `GET /sonde` (https) | non | 204 vide, lisible en `no-cors` : prouve que le téléphone fait confiance |
| `POST /api/transfert` `{}` | oui | `{"url":"https://nom:8791/#transfert=…"}` |
| `POST /api/appairer` `{"transfert":"…","nom":…}` (https) | non | comme avec le code · 403 ticket faux, usé, expiré ou reçu en http |
| `POST /api/dictee` (WAV 16 kHz mono 16 bits, `Content-Type: audio/wav`) | oui | 200 `{"ok","cible","commande","texte","raison"?}` · 400 format ou < 0,25 s · 413 > 10 s · 415 · 503 `voix-indisponible` |

## Photo de profil

Le téléphone recadre au centre en carré de 512 px et réencode en JPEG qualité 0,88
(aperçu rond avant l'envoi). Le serveur n'accepte que des octets commençant par
`FF D8 FF`, écrit de façon atomique dans `~/Images/HUB/profils/telephone-AAAAMMJJ-HHMMSS.jpg`
(suffixe `-2`, `-3`… si deux photos arrivent dans la même seconde, jamais
d'écrasement), puis envoie le datagramme `avatars` au socket du menu s'il existe.

## Intégration dans le menu

### Fichier d'état

`$XDG_RUNTIME_DIR/hub/telecommande.json` (0600), réécrit à chaque changement de code ou
d'adresse, **supprimé** quand le service s'arrête ou n'a pas d'adresse :

```json
{"url": "http://192.168.1.40:8790/", "code": "123456", "expire": 1789308639458,
 "telephones": 1, "appairageLe": 1789308300000,
 "https": "https://192.168.1.40:8791/",
 "empreinteRacine": "3A:9F:…:C2"}
```

`expire` et `appairageLe` en millisecondes epoch ; `telephones` = nombre de
téléphones appairés ; `appairageLe` change quand un téléphone vient d'être relié
(pour afficher « Téléphone relié » sur la TV). Le menu doit relire le fichier quand il
change (Gio.FileMonitor, ou toutes les 2 s tant que l'écran est affiché) et masquer
QR code et code si le fichier est absent. `https` et `empreinteRacine` valent `null`
quand le HTTPS n'est pas disponible ; sinon **afficher l'empreinte** (en petit, sous
le code, par exemple en 8 groupes de 4 paires) : le téléphone la compare avant de
faire confiance au certificat.

### `qrcode.js`

```html
<script src="qrcode.js"></script>
```

```js
const svg = window.qrSvg(texte, { sombre: "#000", clair: "#fff", marge: 4 });
conteneur.innerHTML = svg;   // chaîne "<svg …>…</svg>"
```

- `texte` : chaîne quelconque, encodée en UTF-8, mode octet, correction **M**
  (version choisie automatiquement : une URL du HUB tient en version 2 ou 3).
- `options` (facultatif) : `sombre` et `clair` = couleur CSS simple (`#hex`, nom,
  `rgb()/rgba()`, `clair: "none"` pour un fond transparent) — toute autre valeur est
  remplacée par le défaut, ce qui rend l'`innerHTML` sûr ; `marge` = zone calme en
  modules, entier de 0 à 16, défaut 4 (minimum de la norme : ne pas descendre en
  dessous si le fond autour n'est pas clair).
- Le SVG a un `viewBox` en modules et pas de taille : le dimensionner en CSS
  (`width: 16rem`). Garder **sombre sur clair** : beaucoup de lecteurs ne lisent pas
  un QR code inversé.
- Le fichier définit aussi le global `qrcode` de la bibliothèque d'origine.

## Comme une app : ce que les téléphones acceptent vraiment

La page déclare un manifeste (`standalone`, portrait, couleurs du HUB), les icônes
192/512 (aussi `maskable` : le carré tient dans le cercle sûr), `apple-touch-icon`
180, `apple-mobile-web-app-capable` et `theme-color`. **Aucun service worker** : il
n'existe qu'en contexte sécurisé, et la télécommande n'a rien à faire hors ligne.
Un encart (masquable, rappelé dans ⋯) donne les gestes selon le téléphone.

| | en http://ip:8790 | en https://ip:8791 (racine installée) |
|---|---|---|
| **Android, Chrome** | « Ajouter à l'écran d'accueil » crée un **raccourci** : l'installation d'app exige HTTPS, donc la page peut s'ouvrir avec la barre de Chrome | contexte sécurisé : critères d'installation remplis sans service worker depuis Chrome 108 (menu ⋮ → « Installer l'application »), **plein écran** ; l'invite automatique, elle, exige encore un service worker et ne viendra pas |
| **iPhone, Safari** | « Partager → Sur l'écran d'accueil » : depuis iOS 26, « Ouvrir comme app web » est proposé et activé **pour tout site**, http compris → plein écran | idem |

- **iPhone : l'app d'écran d'accueil ne partage pas le stockage de Safari** (WebKit,
  bug 181849, comportement voulu). Le jeton de Safari n'y est pas : il faut retaper un
  code de la TV à la première ouverture de l'icône. L'encart le dit.
- Conseil donné : installer d'abord le certificat, puis ajouter la version **https**
  à l'écran d'accueil (sinon l'icône ouvre la version http, sans dictée).
- Sources consultées le 15 septembre 2026 : web.dev « install criteria »,
  developer.chrome.com « Revisiting Chrome's installability criteria » (Chrome 108),
  support Apple « Turn a website into an app » et MacRumors (iOS 26), WebKit bug
  181849. **Rien de ce tableau n'a été essayé sur un vrai téléphone.**

## Pavé tactile

Par défaut ; « Boutons » (bascule au-dessus, ou ⋯) rend la croix directionnelle.

| Geste | Commande |
|---|---|
| glisser (≥ 26 px, ~7 mm) | une flèche, **pendant** le mouvement, sans attendre le relâcher |
| continuer le trait (tous les 80 px, ou 25 % du pavé) | une flèche de plus |
| rester posé 380 ms après un glissement | la flèche se répète toutes les 130 ms |
| toucher (< 10 px, < 480 ms) | OK |
| appui long (480 ms, immobile) | Retour |
| deux doigts | Accueil |

Pointer events, `touch-action: none` sur le pavé (ni défilement, ni zoom, ni délai de
300 ms), `pointercancel` n'envoie rien. **Main** (⋯ → Main : droitier/gaucher) : le
volume et « Retour » passent du côté du pouce. **Haptique** : `navigator.vibrate` sur
Android ; sur iPhone, qui n'a pas cette API, le « tic » que Safari (iOS 18+) donne
quand un `<input type="checkbox" switch>` change d'état, déclenché par son label.

## Dictée depuis le téléphone

« Maintenir pour parler » : on dit une commande de la voix du salon (« télé »,
« à droite », « thème sombre »… sans « HUB » devant), on relâche.

**Le chemin.** getUserMedia → Web Audio (`ScriptProcessorNode`) → rééchantillonnage
à 16 kHz dans la page → WAV PCM → `POST /api/dictee` en HTTPS → travailleur Vosk →
`hub_voix_logique.analyser` → même routage qu'un appui. Menu ouvert, il reçoit
`voix:entendu:<texte>`, la commande, `voix:repos` (ou `voix:incompris`).

**Pourquoi pas la reconnaissance du navigateur (Web Speech API).** Elle aussi exige
le contexte sécurisé, donc ne dispense pas du certificat ; elle envoie la voix chez
Google (Chrome) ou Apple (Safari), contrairement au reste du HUB ; sur iPhone elle
est capricieuse dans une app d'écran d'accueil ; et elle transcrit du français libre
qu'il faudrait ensuite ramener aux commandes. Vosk sur le HUB : même comportement
sur les deux téléphones, hors ligne, mêmes phrases et même analyse que le salon.

**Pourquoi pas MediaRecorder.** Chrome enregistre en WebM/Opus, Safari en MP4/AAC :
il faudrait ffmpeg sur le HUB et un décodeur de conteneurs exposé au réseau. La page
rend directement le format du reconnaisseur.

**Le travailleur.** `hub_telecommande.py --travailleur-dictee hub-voix.py`, lancé
par le Python du venv de la voix à la première dictée (le service, lui, reste en
Python système sans dépendance), importe la classe `Reconnaisseur` de `hub-voix.py`
et lui passe le son par blocs de 0,2 s comme le fait `--fichier`. Arrêté après 5 min
sans dictée (le modèle occupe ~150 Mo). Langue : celle du profil actif.

**Sans le certificat (ou s'il échoue sur un iPhone).** Le bouton micro ouvre la marche
à suivre au lieu d'échouer. Pour du **texte libre** (recherche Kodi), le micro du
**clavier** du téléphone (Gboard, clavier iOS) dicte dans le champ texte et marche
en http : aucune dépendance au certificat. Écarté : `<input type="file" capture>`
(iOS n'enregistre pas de son seul, il faudrait une vidéo et ffmpeg).

## Ce qui est prouvé, et comment

Le 13 septembre 2026, sur la machine de développement (Python 3.12.3, Node 18/24) :

- `python3 -m unittest installer/telecommande/test_telecommande.py` : 42 tests, dont
  les requêtes HTTP réelles sur 127.0.0.1 (appairage, code faux, limite d'essais,
  jeton requis, révocation, commandes hors liste, Host étranger, CSP, routage vers un
  faux socket de menu et un faux JSON-RPC Kodi, photo).
- QR code : décodé par un décodeur écrit dans le test (format, masque, lecture en
  zigzag, **correction Reed-Solomon recalculée**) pour deux URL typiques, et par
  **zxing-cpp** (venv de test, pas installé sur l'hôte ; ni zbarimg). Le test tiers
  est sauté si aucun décodeur n'est présent.
- Page : Chromium en vue mobile (Playwright) contre le service réel — appairage avec
  code faux puis bon, commandes reçues par un faux socket de menu, texte, feuille
  d'options, photo recadrée et écrite, **aucune violation CSP**, jeton conservé au
  rechargement.

Le 15 septembre 2026, même machine (Python 3.12.3, OpenSSL 3.0.13, Chrome stable,
Node 22) :

- `python3 -m unittest installer/telecommande/test_telecommande.py` : 67 tests.
  Manifeste et icônes relus octet par octet ; autorité : modes 0600/0700, extensions,
  durée, chaîne vérifiée par `openssl verify` et par le client TLS de Python (IP et
  `hub.local`), contraintes de nom appliquées, réémission sur changement d'adresse ou
  d'échéance sans changer la racine, clés absentes de toutes les réponses des deux
  ports, poignée de main ratée sans effet sur le service, ticket à usage unique ;
  dictée avec un faux reconnaisseur (formats refusés, langue, 503, « éteindre » hors
  menu refusé). Avec `HUB_VOIX_PYTHON`, `HUB_VOIX_MODELES` et `HUB_TEST_DICTEE_WAV`
  (« Télé. » synthétisé par Piper), le vrai Vosk de bout en bout (sinon sauté).
- `node --test installer/telecommande/test_navigateur.mjs` (playwright-core de
  `tests/menu`, Chrome du système, vues Pixel et iPhone émulées) : 11 tests.
  Encart Android/iPhone ; **gestes du pavé en vrais touchers** (protocole DevTools :
  toucher, 4 glissements, appui long, deux doigts, répétition, long trait, flèche
  reçue par le menu doigt encore posé) ; gaucher/droitier et boutons ;
  **HTTPS : racine installée dans un magasin NSS jetable, Chrome accepte
  `https://hub.local` avec son propre vérificateur** (aucun contournement) et le
  refuse sans elle ; passage http → https par ticket ; **dictée : micro de Chrome
  remplacé par le fichier « Télé. », page en https vérifié, vrai Vosk → datagrammes
  `voix:entendu:télé`, `tv`, `voix:repos` au menu** (sans Vosk, un faux reconnaisseur
  vérifie la capture et la durée envoyée).

**Pas prouvé :** un vrai téléphone sur le vrai réseau du HUB — ni l'installation de
la racine sur Android ou iPhone (écrans de réglages décrits d'après la documentation),
ni l'acceptation des contraintes de nom par iOS (prévues par la norme et appliquées
par Chrome et OpenSSL ici), ni l'ouverture plein écran depuis l'écran d'accueil, ni
le « tic » haptique de l'iPhone, ni Web Audio de Safari (le moteur WebKit n'a pas été
lancé : seul Chrome l'a été, avec un agent iPhone). Kodi réel (TCP 9090 et
`Input.SendText`), `wpctl` sur la sortie audio du HUB, la vibration Android réelle.
