# Télécommande de la TV (HDMI-CEC)

La télécommande de la Sony KD-55XG70 pilote le HUB : flèches, OK et Retour dans le
menu et dans Kodi ; **Retour tenu 1,2 s** ramène à l'accueil (quitte Kodi, ferme le
service web). Le HUB allume la TV et passe sur son entrée à son démarrage, et la met
en veille quand il s'éteint.

**Le M720q n'a pas de CEC** (pas de `/dev/cec*`, audit du 13 septembre 2026). Il faut
un adaptateur USB. Rien de ce dossier n'a encore touché de matériel : voir « Ce qui est
prouvé » plus bas.

## L'adaptateur à acheter

**Pulse-Eight USB - CEC Adapter**, référence **P8-USBCECv1** (USB 2548:1002).
Prix relevé sur pulse-eight.com le 15 septembre 2026 : **48,94 $** (hors port ; le
site vend aussi en euros et en livres). C'est l'adaptateur que libcec (et donc Kodi)
prend en charge nativement ; les « HDMI-CEC » USB génériques ne le sont pas.

Ce que dit le fabricant, et qui compte ici :
- adaptateur **passif** : au plus **2 m de câble HDMI au total** (des deux côtés) en
  UHD, 5 m en 1080p ;
- **pas au-delà de 4K60 4:2:0 8 bits**, et « en 4K, le modèle actuel peut ne pas
  marcher » en ligne. Or la TV est 4K et le HUB vise la 4K60 (ARCHITECTURE.md).

## Le brancher

Le bus CEC est **commun à toutes les entrées HDMI** de la TV : l'adaptateur n'a pas
besoin d'être sur le chemin de l'image. D'où deux montages.

**Montage conseillé — à côté de l'image** (celui que Pulse-Eight recommande en 4K) :

```
M720q ── DisplayPort → HDMI 2.0 actif ── câble HDMI ──────────── TV, entrée HDMI 1 (image)
M720q ── USB ── adaptateur Pulse-Eight ── côté « TV » : câble HDMI ── TV, entrée HDMI 2 (CEC seul)
                                          côté « PC » : rien
```

L'image ne traverse pas l'adaptateur : aucune limite de débit ni de longueur. Il faut
alors dire à libcec **sur quelle entrée est l'image**, sinon « passer sur l'entrée du
HUB » basculerait la TV sur l'entrée 2, noire : réglage `systeme.cec.portHdmi` = `1`
(le numéro de l'entrée où arrive l'image).

**Montage en ligne** (seulement si l'image reste stable) :

```
M720q ── DP → HDMI actif ── HDMI (court) ── [PC] adaptateur [TV] ── HDMI (court) ── TV, entrée 1
                                                  └── USB ── M720q
```

Sur la TV : **BRAVIA Sync** (le nom que Sony donne au CEC) activé, avec la commande
des appareils par la télécommande, dans les réglages des entrées externes — chemin
exact à relever sur la XG70. Sans lui, la TV ne relaie aucune touche.

## Fichiers

| Fichier | Rôle |
|---|---|
| `hub-cec.py` | le service : lance `cec-client`, lit ses trames, agit ; `--tv allumer\|veille\|entree` |
| `hub_cec_logique.py` | tout ce qui décide, sans dépendance : lecture des lignes, appuis longs, cible, partage avec Kodi, réglages |
| `test_hub_cec.py` | tests sans adaptateur : `python3 -m unittest test_hub_cec` (depuis `installer/cec`) |
| `simulateur_cec_client.py` | faux `cec-client` qui rejoue une trace et consigne les ordres reçus |
| `traces/sony-bravia-navigation.log` | trace au format exact de libcec 7.1.1 (reconstituée, voir son en-tête) |
| `hub-cec.service` | unité systemd **utilisateur** |
| `70-hub-cec.rules` | udev : l'adaptateur à l'utilisateur de la session (uaccess), ModemManager à l'écart |
| `kodi-cec-desactive.xml` | posé en `~/.kodi/userdata/peripheral_data/cec_2548_100x.xml` (mode relais) |

## Pourquoi `cec-client`

Ubuntu 26.04 (« resolute ») livre **libcec7 et cec-utils 7.1.1** (universe) mais **pas
de python3-cec** (API Launchpad, 15 septembre 2026). `cec-client` écrit chaque trame et
accepte des ordres sur son entrée : un processus séparé, relancé s'il meurt, rien à
compiler. Le service lit les lignes **TRAFFIC** (`>> 01:44:02` : la TV envoie « User
Control Pressed », touche Bas) plutôt que les lignes « key pressed » : la trame est
fixée par la norme, le texte ne l'est pas, et libcec réécrit les touches combinées.

`cec-client -t r -o HUB -d 13` : type « enregistreur » (le défaut de cec-client, et le
type auquel les Sony relaient le plus de touches — à confirmer sur la XG70), erreurs +
notices + trafic.

## Où vont les touches

Même ordre que la voix (`hub_voix_logique.cible`) :

| à l'écran | flèches, OK | Retour (court) | Retour tenu | lecture, pause, stop, avance, recul |
|---|---|---|---|---|
| menu (`menu.sock`) | `haut` `bas` `gauche` `droite` `ok` | `retour` | `retour` | — |
| service web (`hub-web`) | — (la page n'a pas d'interface pilotable) | — | `hub-web --fermer` | — |
| Kodi, mode relais | `Input.Up`… `Input.Select` | `Input.Back` | `Application.Quit` | `Input.ExecuteAction` |
| Kodi, mode céder | Kodi les reçoit lui-même par libcec | | | |
| bureau | — | — | — (fermer la session ferait perdre un travail) | — |

Retour court n'est envoyé qu'au relâcher : c'est là qu'on sait que ce n'était pas un
appui long. Une TV qui n'envoie pas « Released » : relâché implicite après 0,8 s sans
trame (la norme fait répéter une touche tenue toutes les 200 à 500 ms).

## Le partage avec Kodi

**libcec verrouille le port** (`flock(LOCK_EX | LOCK_NB)`, `serialport.cpp`) : un
second programme échoue avec « Couldn't lock the serial port ». Un seul propriétaire.

- **Relais (défaut).** hub-cec garde l'adaptateur en permanence et transmet à Kodi
  par JSON-RPC (TCP 9090, déjà ouvert en local par l'installateur). Le CEC intégré de
  Kodi est désactivé par `peripheral_data/cec_2548_100x.xml` (`enabled` = 0 ; nom et
  format lus dans `xbmc/peripherals/devices/Peripheral.cpp` de Kodi 21.3). Pourquoi
  c'est le défaut : un seul programme touche l'adaptateur, la télécommande marche
  même si Kodi plante, et Kodi n'envoie pas « Inactive Source » en quittant (réglage
  `send_inactive_source`, vrai par défaut dans son `peripherals.xml`), qui renverrait
  la TV sur son tuner au retour au menu.
- **Céder** (`systeme.cec.partage` = `"ceder"`). hub-cec ferme `cec-client` dès qu'il
  voit Kodi (sondage toutes les 0,25 s) et le rouvre quand Kodi quitte, en reprenant
  l'entrée HDMI. libcec réessaie d'ouvrir le port pendant **10 s**
  (`CEC_DEFAULT_CONNECT_TIMEOUT`, `CECProcessor.cpp`) : Kodi a le temps de le prendre.
  Il faut alors réactiver le CEC dans Kodi (Paramètres → Système → Entrées →
  Périphériques → CEC Adapter). Intérêt : les fonctions CEC propres à Kodi.

## Réglages (`~/.config/hub/reglages.json`, relus à chaud)

```json
"systeme": { "cec": { "partage": "relais", "portHdmi": 1, "allumerTv": true, "veilleTv": true } }
```

- `portHdmi` (1–15, absent = autodétection de libcec) : entrée de la TV où arrive
  l'**image** du HUB. Changer la valeur relance `cec-client`.
- `allumerTv` : au démarrage du HUB, allumer la TV et passer sur son entrée — **une
  fois par démarrage** (`$XDG_RUNTIME_DIR/hub/cec-tv-allumee`), pour qu'un changement
  de mode ne ramène pas la TV sur le HUB si on a choisi une autre entrée.
- `veilleTv` : mettre la TV en veille quand la machine s'éteint (seulement si
  `systemctl is-system-running` dit `stopping` : quitter une session ne l'éteint pas).

Ordres ponctuels, par le service en cours (socket `$XDG_RUNTIME_DIR/hub/cec.sock`,
0600) : `hub-cec.py --tv allumer`, `--tv veille`, `--tv entree` ; ou un datagramme
`tv:allumer` / `tv:veille` / `tv:entree` depuis le menu.

## Installation (`hub-installer.sh`, étape 15)

1. `apt-get install cec-utils` ;
2. `hub-cec.py`, `hub_cec_logique.py`, `README.md` dans `/usr/local/lib/hub/cec/`, et
   `hub_voix_logique.py` dans `/usr/local/lib/hub/voix/` (reconnaître Kodi, le bureau,
   hub-web) ;
3. `/etc/udev/rules/70-hub-cec.rules` ;
4. `peripheral_data/cec_2548_1001.xml` et `…1002.xml` pour Kodi, **s'ils n'existent pas** ;
5. `/usr/local/lib/systemd/user/hub-cec.service`, activé pour toutes les sessions.

Sans adaptateur, le service lit sysfs toutes les 5 s (identifiants USB 2548:1001 ou
2548:1002) et ne lance rien. Journal : `journalctl --user -u hub-cec -f`.

## Ce qui est prouvé sans matériel (15 septembre 2026)

`python3 -m unittest test_hub_cec` : 29 tests, dont le service complet contre le
simulateur (menu réel en socket datagramme, faux Kodi JSON-RPC sur TCP) :

- lecture de chaque forme de ligne de `cec-client` 7.1.1, formats vérifiés dans les
  sources (`CECTypeUtils.h`, `CECProcessor.cpp`, `cec-client.cpp`) ;
- trace Sony rejouée → menu reçoit `bas bas ok retour droite droite droite retour`
  (le dernier `retour` = appui long) ; Kodi reçoit `Input.Down ×2, Select, Back,
  Right ×3` puis `Application.Quit` ;
- à l'ouverture : `on 0` puis `as`, une seule fois par démarrage ;
- ordre extérieur `tv:veille` → `standby 0` ; arrêt → `q` ;
- mode céder : rien de lancé tant que Kodi tourne, reprise et `as` quand il quitte,
  adaptateur rendu quand il revient ;
- port verrouillé : pas de relance en boucle ; sans adaptateur : rien de lancé.

## Ce qui reste à éprouver avec l'adaptateur

- [ ] `cec-client -l` voit l'adaptateur ; `ls -l /dev/ttyACM*` montre l'ACL de
      l'utilisateur (règle uaccess) ; ModemManager ne l'ouvre pas.
- [ ] **Capturer une vraie trace** : `cec-client -t r -o HUB -d 13 | tee
      traces/sony-kd55xg70.log`, appuyer sur chaque touche, **tenir** Retour et une
      flèche. La rejouer dans les tests à la place de la trace reconstituée.
- [ ] Quelles touches la XG70 relaie-t-elle vraiment (Retour = 0x0D ? lecture ?), et
      répète-t-elle une touche tenue ? Si Retour n'arrive pas en type `r`, essayer
      `-t p` (lecteur).
- [ ] Adresse physique : autodétectée, ou `portHdmi` nécessaire (montage à côté : oui).
- [ ] Montage en ligne en 4K60 : image stable ou non.
- [ ] `on 0` / `as` allument la XG70 et basculent l'entrée ; `standby 0` l'éteint.
- [ ] Kodi ne signale pas d'erreur CEC au lancement avec `cec_2548_1002.xml` (mode
      relais) ; en mode céder, Kodi prend l'adaptateur dans ses 10 s.
- [ ] `hub-cec.service` démarre dans la session kiosque (même question que la voix :
      `graphical-session.target` atteint ?).
