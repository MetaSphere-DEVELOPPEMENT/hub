# Télécommande téléphone

Le téléphone devient la télécommande du HUB : on scanne le QR code affiché sur la TV,
on tape le code à 6 chiffres, et la page offre croix directionnelle, OK, Retour,
Accueil, les trois modes, le volume, l'envoi de texte (recherche dans Kodi) et l'envoi
d'une photo de profil.

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
- Aucune dépendance à installer : `python3`, `wpctl` (paquet `wireplumber`) et
  `gnome-session-quit` sont déjà sur Ubuntu Desktop.

Essai sans installer : `python3 installer/telecommande/hub_telecommande.py -v`.

## Port et adresse

**Port 8790, fixe** : l'URL finit en favori sur les téléphones, et le jeton est lié à
l'origine `http://ip:8790`.

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
- **Rien d'autre n'est servi** que `/` (la page, lue une fois au démarrage) et l'API.
  Aucun chemin reçu du réseau ne touche le disque : le nom des photos est fabriqué
  par le serveur.
- **En-têtes.** CSP `default-src 'none'`, script et style autorisés **par empreinte**
  (pas de `unsafe-inline`), `connect-src 'self'`, `frame-ancestors 'none'` ;
  `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Cache-Control: no-store`. **Aucun en-tête CORS.**
- **Rebinding DNS.** L'en-tête `Host` doit être `ip:8790`, `nom-machine:8790` ou
  `nom-machine.local:8790`, sinon 421. Les POST exigent `application/json` (ou
  `image/jpeg` pour la photo) : une page étrangère ne peut les envoyer sans prévol
  CORS, auquel on ne répond jamais favorablement. `Sec-Fetch-Site: cross-site` : 403.
- **Éteindre** ne part qu'au menu, qui demande confirmation sur la TV. Menu fermé,
  c'est refusé.
- Corps limités à 2 Kio (JSON) et 2 Mio (photo) ; délai de 10 s par connexion.

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
{"url": "http://192.168.1.50:8790/", "code": "123456", "expire": 1789308639458,
 "telephones": 1, "appairageLe": 1789308300000}
```

`expire` et `appairageLe` en millisecondes epoch ; `telephones` = nombre de
téléphones appairés ; `appairageLe` change quand un téléphone vient d'être relié
(pour afficher « Téléphone relié » sur la TV). Le menu doit relire le fichier quand il
change (Gio.FileMonitor, ou toutes les 2 s tant que l'écran est affiché) et masquer
QR code et code si le fichier est absent.

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

**Pas prouvé :** un vrai téléphone sur le vrai réseau du HUB, Kodi réel (TCP 9090 et
`Input.SendText`), `wpctl` sur la sortie audio du HUB, la vibration (Android ; iOS n'a
pas l'API).
