# Télécommande téléphone

Le téléphone devient la télécommande du HUB : on affiche Réglages → Télécommande sur
la TV, on scanne le QR code, on tape le code à 6 chiffres, et la page offre un pavé tactile (ou la croix
directionnelle), OK, Retour, Accueil, les modes, le volume, la dictée d'une commande,
l'envoi de texte (recherche dans Kodi) et l'envoi d'une photo de profil. Elle
s'ajoute à l'écran d'accueil et s'ouvre alors comme une app.

Hors du menu et de Kodi — devant un service web (Netflix, YouTube, jeu en nuage) ou sur
le bureau — plus rien n'écoute des flèches : le pavé devient alors **une vraie souris**
et le champ texte **un vrai clavier** (voir « Souris et clavier »). C'est éteint par
défaut, et c'est le plus gros pouvoir que cette page puisse recevoir : lire la section
Sécurité avant de l'allumer.

**Pourquoi.** Le M720q n'a ni Bluetooth ni HDMI-CEC (ARCHITECTURE.md, contraintes 2
et 3) : la télécommande de la TV ne pilote rien. Un téléphone sur le wifi de la
maison n'a rien à installer.

## Fichiers

| Fichier | Rôle |
|---|---|
| `hub_telecommande.py` | le service (bibliothèque standard seule) et la ligne de commande de révocation |
| `page.html` | la page du téléphone, CSS et JS inclus, aucune ressource externe |
| `hub_pointeur.py` | le clavier-souris virtuel (`/dev/uinput`), les tables de clavier, le WebSocket — bibliothèque standard seule |
| `71-hub-uinput.rules` · `hub-uinput.conf` | règle udev (groupe `hub-uinput` sur `/dev/uinput`) et chargement du module au démarrage |
| `hub-telecommande.service` | unité systemd **utilisateur** |
| `qrcode.js` | générateur de QR code pour le menu (MIT, vendorisé, voir l'en-tête) |
| `test_telecommande.py` | tests : `python3 -m unittest installer/telecommande/test_telecommande.py` |
| `test_navigateur.mjs` | tests dans Chrome en vue téléphone (voir « Ce qui est prouvé ») |
| `test_pointeur.py` | le périphérique virtuel octet par octet (faux `/dev/uinput`), les tables de clavier **vérifiées contre xkb**, logind, trames WebSocket |
| `test_pointeur_service.py` | chaque garde-fou de la souris, route par route, en http et https réels |
| `banc_essai.py` | le service sur 127.0.0.1 avec un faux menu, un faux `/dev/uinput` et un faux logind, pour `test_navigateur.mjs` — **pas installé** |
| `mesure_transport.py` | latence et débit : une requête https par événement contre le WebSocket — **pas installé** |

## Installation — ce que `hub-installer.sh` doit faire

```bash
install -D -m 0755 telecommande/hub_telecommande.py  /usr/local/lib/hub/telecommande/hub_telecommande.py
install -D -m 0644 telecommande/page.html            /usr/local/lib/hub/telecommande/page.html
install -D -m 0644 telecommande/hub_pointeur.py      /usr/local/lib/hub/telecommande/hub_pointeur.py
install -D -m 0644 telecommande/71-hub-uinput.rules  /etc/udev/rules.d/71-hub-uinput.rules
install -D -m 0644 telecommande/hub-uinput.conf      /etc/modules-load.d/hub-uinput.conf
groupadd --system hub-uinput && usermod -aG hub-uinput <utilisateur du HUB>   # jamais le groupe « input »
modprobe uinput && udevadm control --reload-rules && udevadm trigger --action=change --sysname-match=uinput
install -D -m 0644 telecommande/README.md            /usr/local/lib/hub/telecommande/README.md
install -D -m 0644 telecommande/hub-telecommande.service /usr/local/lib/systemd/user/hub-telecommande.service
install -D -m 0644 telecommande/qrcode.js            /usr/local/share/hub/menu/qrcode.js
ln -sfn /usr/local/lib/hub/telecommande/hub_telecommande.py /usr/local/bin/hub-telecommande
systemctl --global enable hub-telecommande.service
```

- `page.html` et `hub_pointeur.py` doivent rester **à côté** de `hub_telecommande.py` :
  c'est là qu'il les lit (le lien de `/usr/local/bin` est résolu).
- **Souris et clavier.** Le groupe `hub-uinput` ne vaut qu'**après un redémarrage** du
  HUB (le gestionnaire de session de l'utilisateur garde ses anciens groupes) : d'ici
  là, la page affiche « redémarrez le HUB une fois ». La mise à jour depuis le menu
  **rejoue** ces étapes root (elle relance `hub-installer.sh` en entier) : rien à faire
  par SSH sur un HUB déjà installé. Rien de ceci n'allume la fonction.
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
- **Le menu doit ouvrir la fenêtre d'appairage** (fichier `telecommande-appairage`, voir
  « Intégration dans le menu ») tant que l'écran Télécommande est affiché : sans elle,
  tout code est refusé. Recours sans menu : `hub-telecommande --appairage`.
- **Le menu doit afficher l'empreinte** `empreinteRacineCourte` du fichier d'état à côté
  du code (voir plus bas) : c'est ce que le téléphone compare, dans ses propres réglages,
  avant de faire confiance au certificat. Tant qu'il ne le fait pas :
  `hub-telecommande --empreinte`.
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
  à la fermeture de l'écran d'appairage et après 20 codes faux toutes adresses confondues.
- **Fenêtre d'appairage.** Un code n'est comparé que si l'écran Télécommande est
  affiché sur la TV : le menu touche `$XDG_RUNTIME_DIR/hub/telecommande-appairage`, qui
  ouvre l'appairage 5 minutes après sa date de modification. Sinon 403
  `appairage-ferme`, sans rien compter. Avant le 17/09/2026, l'appairage était ouvert en
  permanence.
- **Limite d'essais.** 5 essais par minute par adresse IP (réussites comprises), et
  surtout une limite **globale** : après 3 codes faux toutes adresses confondues, chaque
  essai attend 2, 4, 8, 16, 32 puis 60 s (la série s'oublie après 15 min calmes ou une
  réussite). Réponse 429 avec `Retry-After` au-delà. Pourquoi : l'audit du 17/09/2026
  montrait qu'un appareil prenant ~250 adresses sur le réseau avait ~50 % de chances de
  deviner le code en ~9 h avec la seule limite par adresse. Désormais : au plus ~12
  essais par fenêtre de 5 min (test `test_delai_global_croissant_toutes_adresses_confondues`),
  ~1 chance sur 80 000, et seulement pendant qu'on appaire. Le prix : quelqu'un du
  réseau qui envoie des codes faux en continu retarde l'appairage légitime (au plus
  60 s par essai) ; le journal le montre (`appairage : code faux depuis …`).
- **Jeton.** `secrets.token_urlsafe(32)` (256 bits), gardé par le téléphone dans
  `localStorage`. Le HUB n'en garde que l'**empreinte SHA-256**, dans
  `~/.config/hub/telecommande-jetons.json` (0600). Envoyé en `Authorization: Bearer`,
  jamais en cookie : pas de CSRF possible.
- **Identifiant d'appareil.** 128 bits tirés par le HUB au premier appairage et rendus
  au téléphone (`appareil`), qui les range à côté de son jeton. **Il n'ouvre rien :**
  un appairage ne réussit toujours que par le code de la TV (fenêtre ouverte) ou par un
  ticket de transfert. Il ne sert qu'après coup, à savoir *quelle* entrée renouveler —
  voir « Un téléphone, une entrée ».
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
  lecture, poignée de main TLS comprise.
- **Connexions bornées** : 32 à la fois par port, 8 par adresse IP ; au-delà, la
  connexion est fermée sans ouvrir de fil. Avant, chaque connexion muette coûtait un fil.
- **Photos bornées** : au plus 50 photos `telephone-*.jpg` et 50 Mio en tout dans le
  dossier des profils, jamais s'il resterait moins de 512 Mio libres (507 `quota` ou
  `espace`). Les photos déposées à la main ne comptent pas.
- **Ticket de transfert** http → https : 256 bits, usage unique, 2 minutes, accepté
  sur l'origine https seulement ; il voyage dans le fragment de l'URL (jamais envoyé
  au serveur par le navigateur) et la page l'efface de l'adresse avant tout.

### Souris et clavier : ce que ça ouvre, et à qui

**Ce qu'un téléphone autorisé peut faire, une fois la fonction allumée : tout ce que
ferait quelqu'un assis devant le HUB avec un clavier et une souris.** Déplacer le
pointeur, cliquer, faire défiler, taper du texte — donc, sur le bureau, ouvrir un
terminal et y taper des commandes avec les droits de l'utilisateur du HUB ; devant un
service web, agir dans le compte connecté. Il n'existe pas de version « inoffensive »
d'une souris : la sécurité tient à **qui** l'obtient, pas à ce qu'on lui filtre.

Elle n'est donc donnée qu'à **toutes** ces conditions, vérifiées à chaque ouverture puis
**chaque seconde** tant que le périphérique existe (`Pointeur`, `hub_telecommande.py`) :

1. **L'interrupteur est allumé sur la TV** — Réglages → Télécommande → « Souris et
   clavier depuis le téléphone ». Éteint par défaut ; tout ce qui n'est pas exactement
   `true` dans `reglages.json` vaut éteint ; l'éteindre coupe les sessions en cours dans
   la seconde. Un profil restreint ne voit pas l'interrupteur.
2. **La connexion est en https** (port 8791). En http, le jeton se lit sur le wifi :
   tenable pour des flèches, pas pour un clavier.
3. **Le jeton est « sûr »** : obtenu en tapant le code de la TV **sur la page https**.
   Un jeton obtenu en http ne l'est pas, ni celui d'un transfert http → https (le
   ticket de transfert est rendu en http à qui présente le jeton http : qui a lu l'un a
   pu demander l'autre). La page le dit et propose « Retaper le code » ; le jeton http du
   même téléphone reste valable pour la télécommande d'avant. `hub-telecommande
   --lister` marque les téléphones qui tiennent un tel jeton.
4. **Le contexte est un service web ou le bureau.** Dans le menu et dans Kodi, les
   flèches gardent leur chemin (socket, JSON-RPC), et le clavier virtuel n'est même pas
   créé.
5. **La session est au premier plan et déverrouillée** (logind : `Active=yes`,
   `LockedHint=no`, classe `user`, type graphique, locale). Un périphérique noyau parle à
   ce qui est devant, quoi que ce soit : sans cette garde, une frappe irait dans le champ
   du mot de passe de GDM (passage du HUB au bureau) ou de l'écran verrouillé. logind
   muet ou illisible : c'est non.
6. `/dev/uinput` est accessible (groupe `hub-uinput`, voir Installation).

Et autour :

- **Aucune route nouvelle sans appairage.** `POST /api/pointeur/session` exige le jeton ;
  le WebSocket `/api/pointeur` exige un **ticket** à usage unique (30 s, 256 bits) délivré
  par cette route, présenté comme sous-protocole (jamais dans l'adresse, donc ni dans un
  journal ni dans un historique). Un ticket de souris n'appaire pas, un ticket de
  transfert n'ouvre pas la souris. `Origin` doit être exactement celle du HUB (un
  WebSocket échappe à CORS), en plus du `Host` et de `Sec-Fetch-Site` déjà vérifiés.
- **La route des boutons n'est pas une porte de derrière** : `POST /api/commande` ne
  transforme flèches, OK, Retour et texte en touches qu'aux mêmes six conditions, et
  partage la même limite de débit.
- **Le périphérique n'existe que pendant l'usage.** Créé à l'ouverture d'une session,
  **détruit** à la fermeture de la dernière (page fermée ou cachée, téléphone en veille,
  30 s sans battement, verrouillage, retour au menu, interrupteur éteint, téléphone
  retiré). Entre-temps, rien ne peut injecter quoi que ce soit par ce service.
- **Limites de débit**, par téléphone : 120 déplacements/s (réserve 240, le surplus est
  jeté, jamais mis en file), 30 frappes-clics-caractères/s (réserve 400), déplacement
  borné à 400 points par message, trames de 2 Kio au plus, 5 messages mal formés puis
  fermeture, 4 sessions à la fois.
- **Témoins.** Sur le téléphone : bandeau ambre « Souris et clavier actifs sur la TV »
  et « Souris » écrit sur le pavé, tant que la session est ouverte. Sur le bureau : une
  notification « Un téléphone pilote la souris et le clavier » (au plus une par minute ;
  la session kiosque n'affiche pas de notifications — là, c'est le pointeur qui bouge).
- **Journal** : ouverture et fermeture de chaque session (téléphone, raison, nombre de
  messages). **Jamais ce qui est tapé** : ce peut être un mot de passe.
- **Révocation** : « Retirer » sur la TV, `--revoquer`, « Oublier ce téléphone » — la
  session ouverte tombe dans la seconde (elle ne repasse plus par la vérification du
  jeton, le gardien s'en charge).
- **Aucune exécution de commande, aucun raccourci.** La page ne peut demander que :
  un déplacement, un défilement, un clic gauche ou droit, une touche **nommée** d'une
  liste fermée (haut, bas, gauche, droite, OK=Entrée, Retour=Échap, effacer, tab,
  lecture/pause, recul, avance) ou du **texte**. Le texte est tapé caractère par
  caractère ; Maj et AltGr ne servent qu'à produire ces caractères. Le périphérique ne
  **déclare** au noyau ni Ctrl, ni Alt, ni Super, ni F1–F12, ni Suppr, ni Impr écran :
  le noyau jette tout événement d'une touche non déclarée, donc Ctrl+Alt+F3 ou SysRq ne
  peuvent pas sortir d'ici, même par un défaut du programme. **Ce n'est pas une barrière
  contre un téléphone malveillant** (la souris ouvre un terminal, le texte y tape ce
  qu'il veut) : c'est une garde contre les accidents. La barrière, ce sont les points 1
  à 3.

**Ce qui reste vrai, et qu'il faut savoir avant d'allumer :**

- Un téléphone appairé pilote déjà le menu : il peut donc **aller lui-même allumer
  l'interrupteur** (Réglages → Télécommande). Ce qui l'arrête ensuite est le point 3 :
  il lui faut le code affiché sur la TV, tapé en https — être dans la pièce, certificat
  installé. Un jeton http volé sur le wifi ne va pas plus loin que la télécommande
  d'avant. Un invité ou un enfant **dans la pièce**, téléphone appairé, peut en revanche
  tout faire : l'interrupteur n'est pas un contrôle parental (le profil restreint, lui,
  ne le voit pas). Pistes non faites : un droit accordé téléphone par téléphone sur la TV.
- `reglages.json`, `/dev/uinput` (groupe `hub-uinput`) et la clé du certificat sont à la
  portée de **tout programme de la session** (Kodi et ses extensions, Chrome) : ils
  tournent déjà avec les droits de l'utilisateur, la souris ne leur donne rien de plus.
- Le délai de garde est d'**une seconde** : un verrouillage d'écran coupe la souris au
  plus une seconde après (un texte en cours s'arrête au caractère suivant).

**Écarté, et pourquoi.** `xdotool`/XTEST : n'atteignent pas Wayland. Le portail
RemoteDesktop (libei) : consentement à l'écran à chaque session, impossible sans clavier.
Le groupe `input` : il donne la lecture de tous les claviers (enregistreur de frappe).
`TAG+="uaccess"` : droits immédiats, mais aussi pour l'écran de connexion quand il est
devant. Un service root intermédiaire : tout programme de la session pourrait lui parler
comme le fait la télécommande, pour une couche de plus à réparer. Le presse-papiers
(coller le texte) : `wl-clipboard` n'est pas installé, et il faudrait envoyer Ctrl+V.
Des raccourcis « utiles » (Alt+Tab, Super, Alt+F4) : aucun n'est indispensable avec une
souris, chacun est une combinaison de plus à justifier — la liste est vide. Le glisser-
déposer (bouton tenu) : pas fait, un bouton resté enfoncé après une coupure de wifi est
un défaut pire que son absence. Durcir l'unité systemd (`PrivateDevices`, filtres
d'appels) : rien qu'on n'ait pu éprouver sur la TV n'entre dans l'unité du seul moyen de
piloter le HUB.

### Autorité locale (HTTPS)

Créée au premier démarrage dans `~/.config/hub/telecommande-tls/` (dossier 0700) :

| Fichier | |
|---|---|
| `racine.key` (0600) · `racine.crt` | ECDSA P-256, 10 ans, `CA:TRUE, pathlen:0` |
| `hub.key` (0600) · `hub.crt` | 397 jours, `serverAuth`, SAN : IP du HUB, `hub.local`, `nom-machine.local` |
| `hub.json` | adresse, noms, échéance, empreinte de la racine qui l'a signé |

- **Contraintes de nom critiques** sur la racine, réduites au strict nécessaire :
  l'adresse actuelle du HUB **en /32**, `hub.local` et `nom-machine.local`. Pourquoi :
  `racine.key` est lisible par tout programme de la session (Kodi, UxPlay, Chrome…) ;
  volée, l'ancienne racine (10/8, 172.16/12, 192.168/16, 169.254/16, 127/8, `.local`)
  permettait d'intercepter le HTTPS du téléphone vers **toute adresse privée de
  n'importe quel réseau** (box, NAS, wifi d'hôtel). Volée aujourd'hui, elle ne permet
  d'usurper que le HUB — ce que `hub.key`, lisible pareil, permet déjà. Tests : un
  certificat signé par la racine pour `banque.example`, `192.168.1.1`, `10.0.0.5` ou
  `nas.local` est refusé (« permitted subtree violation »).
- Écarté : supprimer `racine.key` après signature. Le certificat du HUB (397 jours)
  ne pourrait plus être renouvelé sans réinstaller la racine, et `hub.key` reste de
  toute façon exposée.
- **Le prix : une autre adresse ou un autre nom de machine = une nouvelle racine**, à
  réinstaller sur chaque téléphone (et retirer l'ancienne). **Réserver l'adresse du
  HUB en DHCP sur la box** (bail fixe) évite de le refaire.
- **Migration** : au démarrage, le service relit les contraintes de la racine existante
  (`openssl x509 -text`) ; si elles diffèrent de celles attendues (racine d'avant le
  17/09/2026, adresse ou nom changés, racine sans contraintes), il **détruit l'ancienne
  clé, crée une nouvelle racine** et réémet le certificat. Journal : « autorité locale
  remplacée ». **Après cette mise à jour, il faut donc réinstaller le certificat sur
  chaque téléphone une fois** et supprimer l'ancien « HUB autorité locale » de ses
  réglages.
- Le certificat du HUB est **réémis tout seul** 30 jours avant l'échéance (vérifié
  toutes les heures) ; la racine, seule chose installée sur les téléphones, ne change
  pas alors. Adresse non privée, horloge avant 2026 ou openssl absent : pas de HTTPS, la
  télécommande http continue.
- 397 jours : sous la limite d'Apple (825 j) et sous celle des autorités publiques
  (398 j), si un navigateur l'étendait un jour aux racines installées à la main.
- Réinitialiser : arrêter le service, supprimer le dossier, relancer — puis
  réinstaller la nouvelle racine sur chaque téléphone (et retirer l'ancienne).
- Le téléchargement de la racine passe en **http** : quelqu'un sur le wifi pourrait
  la remplacer. D'où l'empreinte SHA-256 affichée **sur la TV** (fichier d'état), à
  comparer avec celle que montrent **les réglages du téléphone** (détails du certificat
  téléchargé) avant d'activer la confiance. La page du téléphone ne l'affiche plus, et
  `/api/certificat` ne la donne plus : venue par le même canal http que le certificat,
  elle aurait été remplacée avec lui (vérification circulaire, audit du 17/09/2026).

## Un téléphone, une entrée

Avant le 18/09/2026, chaque appairage **ajoutait** une ligne : un téléphone relié trois
fois comptait trois fois, et la liste du HUB se remplissait de doublons du même
appareil. Désormais l'entrée est **renouvelée sur place** — même identifiant, même date
d'appairage, secret neuf — dès que le HUB sait que c'est le même téléphone. Il ne le
sait que de trois façons, toutes prouvées :

| Preuve | Ce qui se passe |
|---|---|
| le **jeton précédent** est présenté avec le nouvel appairage (`Authorization: Bearer`) | son entrée est renouvelée |
| un **ticket de transfert** http → https (délivré à un jeton valide) | son entrée garde ses jetons et reçoit celui de la nouvelle origine |
| le **code de la TV** est juste **et** le téléphone renvoie son `appareil` | son entrée est renouvelée, l'ancien secret cesse de valoir |

Ce qui ne prouve rien, et ne remplace donc jamais rien : le nom du téléphone, son
adresse IP, son agent utilisateur. Et l'identifiant d'appareil **seul** ne suffit pas :
sans code juste (donc sans être dans la pièce, écran d'appairage affiché), la requête
est refusée en 403 avant même qu'on le regarde — un appareil non appairé ne peut pas
prendre la place d'un autre. Si deux preuves se contredisent (un téléphone appairé
présente son jeton *et* l'identifiant d'un autre), **le jeton gagne** : on ne renouvelle
que sa propre entrée.

**Ménage.** Un téléphone jamais revu depuis **180 jours** est oublié — au démarrage du
service et à chaque appairage. Et la liste est plafonnée à **20** : au-delà, le moins
récemment vu part, jamais celui qu'on vient d'appairer.

## Retirer un téléphone

Sur la TV : **Réglages → Télécommande** liste les téléphones reliés (nom, dernier
usage) avec un bouton **Retirer** par ligne — deux appuis, le second confirme. Le menu
appelle `hub-telecommande --revoquer <id>`.

```bash
hub-telecommande --appairage         # sans le menu (SSH) : ouvre l'appairage 5 min, affiche le code
hub-telecommande --lister            # id, nom, date d'appairage, dernier usage
hub-telecommande --revoquer 2ab063   # un téléphone
hub-telecommande --revoquer-tout     # tous
```

Effet immédiat, sans redémarrer le service : il relit le fichier dès qu'il change. Le
téléphone révoqué revient tout seul à l'écran d'appairage (au deuxième refus, voir
« Rester relié pendant un mode » : au plus six secondes). Depuis le téléphone,
« ⋯ → Oublier ce téléphone » révoque aussi son propre jeton côté HUB.

## Rester relié pendant un mode

Un mode n'est pas une fenêtre de plus. **Bureau** ferme la session kiosque
(`hub-vers-bureau`) et GDM rouvre aussitôt la session Ubuntu ; le service, s'il suivait
la session, s'arrêtait à ce moment-là et le téléphone perdait la main en entrant dans le
mode. Trois choses l'en empêchent :

- l'unité **ne porte plus `PartOf=graphical-session.target`** : elle traverse le
  changement de session, même adresse, même port, même jeton ;
- `Restart=always` : un service tombé pendant un film revient seul (2 s) ;
- la page **se reconnecte toute seule**, sans rien redemander : pastille « Reconnexion… »
  et relances espacées (1, 2, 4, 8 puis 15 s), plus un essai immédiat au retour sur la
  page, au réveil de l'écran et quand le wifi revient. Elle ne se croit déliée qu'après
  **deux 401 d'affilée** — un seul refus, c'est un service qui redémarre, et effacer le
  jeton pour si peu était justement ce qui faisait retaper un code et compter un
  téléphone de plus.

Pendant un service **Web**, « Accueil » ferme le service (`hub-web --fermer`, comme la
voix et la télécommande CEC) et le volume marche ; le reste passe par la souris et le
clavier s'ils sont allumés. Pendant le mode **Jeux** sans client lancé, rien ne se
pilote : la page l'affiche (« En veille », « Rien à piloter ») mais reste reliée.

## Où vont les commandes

| Situation | Destination |
|---|---|
| socket du menu présent et joignable | datagramme au menu (`accueil` y devient `retour`) ; `texte` refusé (le menu n'a pas ce message) |
| menu fermé, Kodi lancé | JSON-RPC : `Input.Left/Right/Up/Down/Select/Back`, `Input.SendText` (avec `done: true`), `accueil` = `Application.Quit` puis SIGTERM en dernier recours |
| menu fermé, service web (`hub-web` vivant, lu dans `web.pid`) | `accueil` = `hub-web --fermer` ; flèches, OK, Retour, texte = **touches** (voir « Souris et clavier ») si les six conditions sont réunies, sinon sans effet et la réponse dit laquelle manque (`pointeur-…`) |
| menu fermé, bureau GNOME | `accueil` = `gnome-session-quit --logout --no-prompt` ; flèches, OK, Retour, texte = **touches**, aux mêmes conditions ; le reste est sans effet |
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
| `POST /api/appairer` `{"code":"123456","nom":"Pixel 8","appareil":"…32 hex…"}` | facultatif | 200 `{"jeton","id","nom","appareil"}` · 403 `{"erreur":"code"}` code faux · 403 `{"erreur":"appairage-ferme"}` écran d'appairage fermé · 429 `{"attente"}` trop d'essais. `appareil` est facultatif, et ignoré s'il est mal formé ; le jeton présenté en `Authorization`, s'il est encore valide, prime sur lui (voir « Un téléphone, une entrée ») |
| `POST /api/commande` `{"nom":"gauche"}` ou `{"nom":"texte","texte":"Dune"}` | oui | 200 `{"ok","cible","raison"?,"volume"?}` · 400 hors liste · 401 |
| `GET /api/etat` | oui | `{"ok":true,"contexte":"menu"\|"web"\|"kodi"\|"bureau"\|null,"pointeur":{"permis":bool,"raison":null\|"desactive"\|"connexion-non-securisee"\|"jeton-non-sur"\|"contexte"\|"uinput-absent"\|"uinput-refuse"\|"session-verrouillee"\|"session-en-arriere-plan"\|"session-inconnue"\|"module-absent"}}` |
| `POST /api/pointeur/session` `{}` (https) | oui, **sûr** | 200 `{"ticket"}` (usage unique, 30 s) · 401 · 403 `{"erreur":"pointeur","raison":…}` |
| `GET /api/pointeur` (WebSocket, https, `Sec-WebSocket-Protocol: hub-pointeur, ticket.<ticket>`) | ticket | 101 puis messages JSON · 401 ticket absent, faux, usé, expiré · 400 poignée de main · 403 http, origine étrangère ou condition manquante |
| `POST /api/oublier` `{}` | oui | révoque le jeton présenté |
| `POST /photo-profil` (corps JPEG brut, `Content-Type: image/jpeg`) | oui | 200 `{"ok":true,"fichier":"telephone-AAAAMMJJ-HHMMSS.jpg"}` · 400 pas un JPEG · 413 > 2 Mio · 415 · 507 `{"erreur":"quota"\|"espace"}` |
| `GET /manifest.webmanifest`, `/icone-32.png`, `/icone-192.png`, `/icone-512.png`, `/apple-touch-icon.png` | non | manifeste, icônes |
| `GET /hub-racine.crt` | non | la racine en DER (`application/x-x509-ca-cert`) · 404 si HTTPS désactivé |
| `GET /api/certificat` | non | `{"disponible","securise","https":"https://nom:8791/"}` (pas d'empreinte : elle ne fait foi que sur la TV) |
| `GET /sonde` (https) | non | 204 vide, lisible en `no-cors` : prouve que le téléphone fait confiance |
| `POST /api/transfert` `{}` | oui | `{"url":"https://nom:8791/#transfert=…"}` |
| `POST /api/appairer` `{"transfert":"…","nom":…}` (https) | non | comme avec le code, mais le téléphone **garde** son jeton http : une seule entrée pour les deux origines · 403 ticket faux, usé, expiré ou reçu en http |
| `POST /api/dictee` (WAV 16 kHz mono 16 bits, `Content-Type: audio/wav`) | oui | 200 `{"ok","cible","commande","texte","raison"?}` · 400 format ou < 0,25 s · 413 > 10 s · 415 · 503 `voix-indisponible` |

## Photo de profil

Le téléphone recadre au centre en carré de 512 px et réencode en JPEG qualité 0,88
(aperçu rond avant l'envoi). Le serveur n'accepte que des octets commençant par
`FF D8 FF`, dans la limite des quotas (50 photos du téléphone, 50 Mio, 512 Mio libres au
moins, 507 sinon), écrit de façon atomique dans `~/Images/HUB/profils/telephone-AAAAMMJJ-HHMMSS.jpg`
(suffixe `-2`, `-3`… si deux photos arrivent dans la même seconde, jamais
d'écrasement), puis envoie le datagramme `avatars` au socket du menu s'il existe.

## Intégration dans le menu

### Fichier d'état

`$XDG_RUNTIME_DIR/hub/telecommande.json` (0600), réécrit à chaque changement de code,
d'adresse ou de fenêtre d'appairage, **supprimé** quand le service s'arrête ou n'a pas
d'adresse :

```json
{"url": "http://192.168.1.50:8790/", "code": "123456", "expire": 1789308639458,
 "telephones": 1,
 "listeTelephones": [{"id": "2ab063", "nom": "Pixel 8",
                      "cree": 1789200000000, "vu": 1789308200000}],
 "appairageLe": 1789308300000,
 "appairageOuvert": true, "appairageJusque": 1789308600000,
 "https": "https://192.168.1.50:8791/",
 "empreinteRacine": "3A:9F:…:C2",
 "empreinteRacineCourte": "3A9F 12C0 4481 7BE2"}
```

`expire`, `appairageLe` et `appairageJusque` en millisecondes epoch ; `telephones` =
nombre de téléphones appairés ; `listeTelephones` = les mêmes, le plus récemment vu
d'abord, pour la liste de Réglages → Télécommande (**rien de secret n'y passe** : ni
jeton, ni empreinte, ni identifiant d'appareil) ; `appairageLe` change quand un téléphone vient d'être
relié (pour afficher « Téléphone relié » sur la TV). `appairageOuvert` : le code est-il
accepté en ce moment (publié au plus 5 s après l'ouverture ou la fermeture) ;
`appairageJusque` : fin de la fenêtre, `null` si fermée. Le menu doit relire le fichier
quand il change (Gio.FileMonitor, ou toutes les 2 s tant que l'écran est affiché) et
masquer QR code et code si le fichier est absent. `https`, `empreinteRacine` et
`empreinteRacineCourte` valent `null` quand le HTTPS n'est pas disponible ; sinon
**afficher `empreinteRacineCourte`** sous le code, telle quelle (les 8 premières paires
de l'empreinte SHA-256, 4 groupes de 4 caractères hexadécimaux majuscules), avec
« Empreinte du certificat (début) » : le téléphone la compare à celle de ses réglages
avant de faire confiance au certificat. 64 bits suffisent contre quelqu'un du wifi et se
lisent d'un canapé ; `empreinteRacine` (32 paires séparées par `:`) reste disponible.

### Fenêtre d'appairage

`$XDG_RUNTIME_DIR/hub/telecommande-appairage` : fichier vide, régulier, de l'utilisateur
de la session. **L'appairage est ouvert tant que sa date de modification a moins de
5 minutes** (et pas plus d'une minute dans le futur) ; son contenu est ignoré ; un lien
symbolique n'ouvre rien.

- Le menu le **crée ou le touche** (`os.utime`, ou réécriture) quand il affiche l'écran
  Télécommande, puis **au moins toutes les 60 s** tant que l'écran reste affiché ;
- il le **supprime** quand l'écran se ferme (le code est alors renouvelé : celui vu à
  l'écran ne servira pas à la prochaine ouverture) ;
- s'il tombe sans le supprimer, la fenêtre se ferme seule 5 minutes après le dernier
  toucher.
- `hub-telecommande --appairage` fait la même chose une fois (5 min), pour un appairage
  par SSH sans menu.

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

C'est le mode **Navigation** (menu et Kodi), inchangé ; devant un service web ou sur le
bureau, voir « Souris et clavier ».

Pointer events, `touch-action: none` sur le pavé (ni défilement, ni zoom, ni délai de
300 ms), `pointercancel` n'envoie rien. **Main** (⋯ → Main : droitier/gaucher) : le
volume et « Retour » passent du côté du pouce. **Haptique** : `navigator.vibrate` sur
Android ; sur iPhone, qui n'a pas cette API, le « tic » que Safari (iOS 18+) donne
quand un `<input type="checkbox" switch>` change d'état, déclenché par son label.

## Souris et clavier

La page lit `contexte` et `pointeur` dans `/api/etat` (toutes les 6 s, et tout de suite
après une commande qui change de contexte) et **bascule seule** : « Navigation » est
écrit sur le pavé dans le menu et dans Kodi, « Souris » devant un service web ou sur le
bureau. Si la souris manque là où elle servirait, une ligne dit pourquoi et quoi faire.
Le mode d'un geste est décidé au poser du doigt.

| Geste (mode Souris) | Effet |
|---|---|
| glisser | déplacement relatif du pointeur, accéléré en douceur : ×1,2 lentement, jusqu'à ×4 pour un geste vif (`gain = 1,2 + 1,6 × points/ms`) |
| toucher | clic gauche (deux touchers = double clic) |
| appui long (480 ms, immobile) | clic droit |
| deux doigts | défilement vertical et horizontal, sens des doigts, en haute résolution (`REL_WHEEL_HI_RES`, un cran tous les 30 points) |
| OK · Retour · flèches (boutons) | Entrée · Échap · flèches |
| ⌫ « ⏯ » | effacer, recul, lecture/pause, avance (touches multimédia) |
| champ texte | tapé caractère par caractère sur la TV, avec compte rendu |

**Retour = Échap**, et pas Alt+Gauche : c'est la touche que `hub-web` donne déjà au
bouton B de la manette, celle que YouTube TV, Netflix et les lecteurs prennent pour
« revenir » ou quitter le plein écran, celle qui ferme un menu du bureau — et ce n'est pas
une combinaison. Échap **maintenue** deux secondes ramène au HUB dans `hub-web` : la
télécommande envoie appui et relâcher d'un coup, donc jamais par accident. **Accueil**
garde son sens partout (fermer le service web, quitter Kodi, fermer le bureau).

**Transport.** Un WebSocket sur le port https, écrit avec la bibliothèque standard
(`hub_pointeur.py`), et un envoi **par image** (`requestAnimationFrame`) : la page
additionne les `pointermove` et envoie la somme ; si le wifi cale (`bufferedAmount`), la
somme attend l'image suivante au lieu de s'empiler. Pourquoi pas une requête par
déplacement : le service répond en HTTP/1.0 et ferme, donc **une poignée de main TLS par
événement**. Mesuré le 21 septembre 2026 sur la machine de développement (boucle locale,
Python 3.12.14, OpenSSL 3.6.4, `python3 installer/telecommande/mesure_transport.py`,
deux passes) : POST https médiane 2,6–3,1 ms (p95 4–6 ms), au plus ~300–350 événements/s ;
WebSocket à 60 messages/s, de l'envoi à l'écriture dans le périphérique : médiane
0,24 ms, p95 1,0–1,3 ms ; aller-retour d'un battement 0,06–0,09 ms ; sans retenue,
35 000–52 000 événements/s. **Ce sont des planchers du protocole, pas la latence du
salon** : ni wifi, ni téléphone, ni compositeur. Sur un vrai wifi, l'écart se creuse
(une poignée de main TLS coûte un à deux allers-retours réseau de plus par événement,
le WebSocket aucun) ; ce chiffre-là reste à relever sur place.

### Clavier : ce qui est couvert

uinput envoie des **touches**, pas des caractères : `KEY_A` écrit « q » sur un HUB en
AZERTY. La disposition **de la session** est lue à chaque création du périphérique
(`gsettings org.gnome.desktop.input-sources` : première de `mru-sources` présente dans
`sources`, sinon première de `sources` ; liste vide → `/etc/default/keyboard`), et le
texte passe par sa table. Les tables sont recopiées de xkeyboard-config et **vérifiées
contre ses fichiers** par `test_pointeur.py` (781 positions de touches relues, sept tables ; sur le HUB :
`python3 -m unittest installer/telecommande/test_pointeur.py`, qui lit
`/usr/share/X11/xkb/symbols`).

| | Couvert | Pas couvert |
|---|---|---|
| **fr** (de base), **fr+oss** (« Français (variante) »), **fr+latin9**, et leurs variantes `nodeadkeys` | minuscules, majuscules, chiffres (Maj), tout l'ASCII imprimable (`@ # { [ \ ] } ~ ^` et la barre verticale par AltGr), `é è ç à ù € £ § ° µ « »`, `â ê î ô û ä ë ï ö ü ÿ` et leurs majuscules par **touche morte** (^ puis lettre), `É È Ç À Ù` en oss et latin9, `œ Œ` en oss et latin9, `æ Æ` en fr et oss | `É È Ç À Ù` en fr de base → tapés `E E C A U` **et signalés** ; l'accent grave seul en latin9 ; en `nodeadkeys`, les lettres à circonflexe ou tréma → sans accent, signalé |
| **us** | tout l'ASCII imprimable | toute lettre accentuée → sans accent, signalé |
| toute autre disposition (bépo, AFNOR, be, ch, de…) ou une source `ibus` | flèches, OK, Retour, souris | **le texte est refusé** (« Clavier de la TV non reconnu ») : rien n'est deviné |

La typographie du téléphone est ramenée au clavier (`’` → `'`, `“ ”` → `"`, `– —` → `-`,
`…` → `...`, espaces insécables → espace). Émojis et autres écritures : laissés de côté,
et la page dit lesquels. **Jamais un caractère faux tapé en silence.** À vérifier sur la
TV : que Chrome et GTK composent bien la touche morte venue d'un clavier virtuel.

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

Le 18 septembre 2026 (Mac de développement, Python 3.9, Chromium de Playwright) :

- `python3 installer/telecommande/test_telecommande.py` : 103 tests. Nouveaux : fichier
  de jetons d'avant les appareils encore valable, ré-appairage par l'appareil et par le
  jeton précédent sans doublon, transfert http → https en une seule entrée, appareil
  inconnu ou mal formé qui n'emprunte l'entrée de personne, ménage des entrées jamais
  revues (seul et à l'appairage), plafond de la liste, liste publiée sans rien de secret,
  et — côté HTTP réel — **aucun appareil ne remplace l'entrée d'un autre sans code juste**
  (code faux et écran d'appairage fermé), un téléphone appairé ne renouvelant que la
  sienne. Les 6 tests `ServiceHTTPS` échouent **sur ce Mac seulement** : la LibreSSL
  d'Apple refuse les contraintes de nom du certificat
  (`unsupported name constraint type`). Ils passent sur le HUB (OpenSSL).
- `node --test installer/telecommande/test_navigateur.mjs` : 3 tests de plus, tous
  passés — coupure réseau (pastille « Reconnexion… », retour tout seul, aucun code
  redemandé), un 401 isolé qui ne délie pas mais deux d'affilée qui délient, et
  ré-appairage du même téléphone sans seconde entrée (même `id`, même date d'appairage).
  Les 4 tests HTTPS et dictée échouent **sur ce Mac seulement** : ni Google Chrome
  (`channel: "chrome"`) ni `certutil` (outils NSS) n'y sont installés.
- `cd tests/menu && npm test` : 156 tests, 155 passés, 1 sauté — dont la liste des
  téléphones dans Réglages → Télécommande (dernier usage en toutes lettres, un appui
  qui arme « Confirmer », le second qui envoie `telecommande-retirer`).
- **Rien n'a été essayé sur un vrai téléphone ni sur le HUB.**

Le 17 septembre 2026, sur un Mac (Python 3.9.6 lié à LibreSSL 2.8.3, OpenSSL 3.6.4 de
Homebrew en ligne de commande) — correctifs de l'audit de sécurité du même jour :

- `python3 -m unittest installer/telecommande/test_telecommande.py` : 88 tests, dont
  fenêtre d'appairage, délai global croissant (au plus 15 essais simulés par fenêtre de
  5 min en changeant d'adresse à chaque essai), quotas de photos (envois simultanés
  compris), plafond de connexions, racine /32 (certificats pour d'autres adresses
  privées et d'autres noms `.local` refusés par `openssl verify`), migration d'une
  racine d'avant le 17/09 et d'une racine sans contraintes. **6 tests `ServiceHTTPS`
  échouent sur ce Mac, avant comme après** : le module `ssl` de Python y est lié à
  LibreSSL 2.8.3, qui refuse les contraintes de nom IP (« unsupported name constraint
  type »). Sur le HUB (OpenSSL 3), ils sont à relancer.
- Contre-épreuve à la main avec OpenSSL 3.6.4 (`openssl s_client -verify_return_error`)
  contre `banc_essai.py --https` : chaîne acceptée pour `hub.local` et `127.0.0.1`,
  refusée pour `autre.local` et `127.0.0.2`.
- `test_navigateur.mjs` mis à jour (l'empreinte absente de la page) mais **pas relancé**
  (ni Chrome ni playwright sur cette machine).

Le 21 septembre 2026 (Mac de développement, Python 3.12.14 lié à OpenSSL 3.6.4, Chromium
de Playwright, Node 26) — souris et clavier hors du menu et de Kodi :

- `python3 -m unittest installer/telecommande/test_pointeur.py` : 55 tests. Le
  périphérique reçoit de fausses fonctions `open`/`ioctl`/`write` : ordre des ioctl
  (bits, puis `UI_DEV_SETUP`, puis `UI_DEV_CREATE`), numéros d'ioctl **recalculés** depuis
  `_IOW`, structures `input_event` relues **octet par octet**, un `EV_SYN` et un seul à la
  fin de chaque lot, aucune touche tenue après un texte, défilement fin et crans entiers,
  pannes nommées (`ENOENT` → module absent, `EACCES` → droits), aucune touche hors de la
  liste. Tables de clavier : AZERTY (`a` = `KEY_Q`), chiffres, AltGr, touches mortes,
  majuscules accentuées selon la variante, typographie du téléphone, et **les sept tables
  relues contre les fichiers de xkeyboard-config** (781 positions ; fichiers pris sur
  gitlab.freedesktop.org le jour même, `HUB_XKB_SYMBOLES=dossier` ; contre-épreuve : une
  table faussée fait échouer le test). logind : verrouillé, écran de connexion, console,
  session distante, réponse illisible → non. Trames WebSocket : exemple de la RFC 6455,
  trame non masquée, fragmentée ou trop grosse refusée.
- `python3 -m unittest installer/telecommande/test_pointeur_service.py` : 47 tests, par
  de vraies requêtes http et https et un vrai client WebSocket écrit dans le banc.
  **Route par route** (`/api/commande`, `/api/pointeur/session`, `/api/pointeur`) : sans
  jeton, avec un faux, en http avec un jeton sûr, avec un jeton obtenu en http ou par
  transfert, interrupteur absent, éteint ou abîmé, menu ouvert, écran verrouillé, écran
  de connexion, uinput absent ou refusé, module absent — chaque fois **rien n'est écrit**
  et le périphérique n'est pas créé. Ticket à usage unique, expiré, présenté au mauvais
  guichet, origine étrangère, poignée de main incomplète, téléphone révoqué entre-temps.
  En session : verrouillage, écran de connexion, interrupteur éteint, retour au menu,
  téléphone retiré, silence → la session tombe et le périphérique est **détruit**.
  Débit borné (mouvements, frappes, et la route HTTP partage le seau), déplacement borné,
  messages hors liste (« ctrl+alt+t », code de touche brut, « exec »…) sans effet, journal
  sans le texte tapé.
- `tests/test_telecommande_souris.py` : 20 tests, **dans `tests/`** — donc rejoués par le
  HUB avant toute mise à jour : les six conditions, les jetons sûrs, les touches
  interdites, la règle udev (groupe dédié, jamais `input`), l'étape de l'installateur en
  simulation sous `set -u`, l'interrupteur éteint par défaut dans le menu.
- `node --test installer/telecommande/test_navigateur.mjs` : 3 tests de plus, en **https
  réel** (certificat accepté par `ignoreHTTPSErrors`, WebSocket compris) : la page
  affiche « Navigation » dans le menu (flèches au socket, périphérique jamais créé), passe
  seule à « Souris » quand le bureau s'ouvre (témoin visible), vrais touchers → `REL_X`,
  clic gauche, clic droit à l'appui long, défilement à deux doigts, « aé » → `KEY_Q` puis
  `KEY_2`, Retour → Échap, puis revient seule à « Navigation » ; geste vif > geste lent,
  borné à ×4 ; souris indisponible → la raison et le remède à l'écran (interrupteur,
  écran verrouillé, http) ; aucune violation CSP. Les 4 tests HTTPS et dictée échouent
  **sur ce Mac seulement**, avant comme après (ni Chrome ni `certutil`).
- `cd tests/menu && HUB_NAVIGATEUR=chromium npm test` : 4 tests de plus
  (`telecommande-souris.test.js`) — interrupteur éteint par défaut, phrase affichée,
  booléen strict enregistré, anglais, invisible pour un profil restreint.
- **Rien de tout cela n'a touché un vrai `/dev/uinput`, un vrai logind, un vrai
  compositeur ni un vrai téléphone.** À vérifier sur le HUB, dans cet ordre : que
  `/dev/uinput` appartient bien à `root:hub-uinput` en 0660 après un redémarrage
  (`stat -c '%U:%G %a' /dev/uinput`) ; que Mutter (session kiosque et bureau) adopte le
  périphérique — il déclare des touches sans Ctrl, donc udev le marque `ID_INPUT_KEY` et
  non `ID_INPUT_KEYBOARD`, ce que libinput accepte d'après son code mais que rien ici n'a
  éprouvé ; que `LockedHint` passe bien à `yes` au verrouillage
  (`loginctl show-session $(loginctl show-user $USER -p Display --value) -p LockedHint`) ;
  que `gsettings` rend la bonne disposition depuis le service (sinon : « Clavier de la TV
  non reconnu ») ; que Chrome compose la touche morte (« ê ») ; la sensation de la souris
  (gain, défilement) ; la latence sur le vrai wifi.

**Pas prouvé :** un vrai téléphone sur le vrai réseau du HUB — ni l'installation de
la racine sur Android ou iPhone (écrans de réglages décrits d'après la documentation),
ni l'acceptation des contraintes de nom par iOS (prévues par la norme et appliquées
par Chrome et OpenSSL ici), ni l'ouverture plein écran depuis l'écran d'accueil, ni
le « tic » haptique de l'iPhone, ni Web Audio de Safari (le moteur WebKit n'a pas été
lancé : seul Chrome l'a été, avec un agent iPhone). Kodi réel (TCP 9090 et
`Input.SendText`), `wpctl` sur la sortie audio du HUB, la vibration Android réelle.
