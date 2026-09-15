# Allumage programmé, extinction programmée, allumage à distance

Réglages → **Allumage** dans le menu. Détail du fonctionnement en tête de `hub-allumage`.

## Ce que l'installateur pose (étape « Allumage programmé et Wake-on-LAN »)

| Fichier du dépôt | Destination | Droits |
|---|---|---|
| `hub-allumage` | `/usr/local/bin/hub-allumage` | 0755 |
| `hub-allumage.service` | `/etc/systemd/system/` | 0644 |
| `hub-allumage-demarrage.service` | `/etc/systemd/system/` (activé) | 0644 |
| `50-hub-allumage.rules` | `/etc/polkit-1/rules.d/` | 0644 |

Plus `/etc/hub/allumage.env` (`HUB_UTILISATEUR=…`) et le groupe `hub` (partagé avec la
mise à jour). Rejouable : chaque fichier est comparé avant d'être posé.

## Le chemin d'un réglage

1. Le menu enregistre `systeme.allumage` dans `~/.config/hub/reglages.json`
   (`reveils` et `extinctions` : sept cases, lundi d'abord, `"HH:MM"` ou `null`) ;
2. puis `systemctl start --no-block hub-allumage.service` (autorisé par polkit) ;
3. le service arme `rtcwake -m no -t <epoch>` et un minuteur transitoire
   `hub-extinction.timer`, et écrit le résultat dans `/var/lib/hub/allumage.json`,
   lisible par le menu.

Au démarrage suivant, si la machine s'est allumée dans les dix minutes après le
réveil armé, `/run/hub-allumage/reveil` existe : le menu ouvre directement le mode
ambiant (horloge, météo et cadre photo s'il est activé).

## Ce qui n'est prouvé qu'avec le vrai matériel

- **Le réveil depuis l'arrêt complet (S5) dépend du firmware.** Les tests prouvent
  les horaires calculés et les commandes produites, jamais qu'un M720q s'allume. Dans
  le BIOS Lenovo (F1 au démarrage), vérifier *Power → Automatic Power On* : l'alarme
  logicielle doit y être permise. Contrôle : `sudo rtcwake -m off -s 120` doit
  rallumer la machine deux minutes après l'avoir éteinte.
- **La TV ne s'allume pas avec le HUB** : pas de HDMI-CEC sur cette machine
  (ARCHITECTURE.md). Le mode ambiant attend donc qu'on allume la TV.
- L'extinction programmée éteint même en plein film, comme le minuteur de veille.

## Allumer le HUB à distance : Wake-on-LAN

L'installateur active le réveil par « paquet magique » sur la carte Ethernet
(Intel I219-V) de deux façons, parce qu'aucune des deux ne suffit seule :
`ethtool -s <carte> wol g` pour tout de suite, et
`nmcli connection modify <connexion> 802-3-ethernet.wake-on-lan magic` pour que
NetworkManager le remette à chaque démarrage. Il affiche l'adresse MAC, que le menu
montre aussi (Réglages → Allumage).

À vérifier dans le BIOS (non mesuré, pas de matériel sous la main) : *Wake on LAN*
activé, et *Enhanced Power Saving Mode* désactivé — ce mode coupe la carte réseau à
l'arrêt. Seul le câble compte : **pas de Wake-on-LAN par le wifi** (clé USB).

### Et depuis le téléphone ?

**La télécommande web ne peut pas allumer le HUB**, et aucun bouton ne le fera :

1. sa page est servie par le HUB lui-même ; HUB éteint, il n'y a plus de page à ouvrir ;
2. même une page gardée en cache ne peut pas envoyer de paquet magique : un navigateur
   n'a pas le droit d'émettre de l'UDP brut vers une adresse de diffusion.

Les vraies options, par ordre de simplicité :

- **Une application Wake-on-LAN sur le téléphone** (il en existe pour Android et iOS) :
  on y enregistre l'adresse MAC du HUB, le téléphone doit être sur le wifi de la maison.
- **La box** : plusieurs box françaises proposent le réveil d'un appareil du réseau
  local depuis leur interface ou leur application ; à vérifier sur la vôtre.
- **Un autre appareil toujours allumé** (NAS, Raspberry Pi…) :
  `wakeonlan <MAC>` ou `etherwake -i <carte> <MAC>`, éventuellement déclenché à distance.
- Depuis l'extérieur de la maison : seulement via un VPN vers le réseau local ; ne
  jamais ouvrir un port de la box vers la diffusion.

La télécommande explique cela à la place d'un faux bouton (section « Allumer le HUB »).

Tests : `python3 -m unittest tests/test_hub_allumage.py` (aucune commande exécutée).
