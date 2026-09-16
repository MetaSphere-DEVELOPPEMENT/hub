# Audit matériel — samedi 12 septembre 2026, 00h52

_Mesuré sur `(nom d'hôte masqué)`. Aucune installation, aucune modification._

_Publié le 17 septembre 2026 avec les identifiants masqués à la main (nom du Wi-Fi,_
_adresses MAC, IPv6, UUID, chemins personnels) : ils localisent la maison sans rien_
_apprendre sur la machine. Les mesures sont inchangées._

## Système

  distribution               Ubuntu 24.04.4 LTS
  nom de code                noble
  noyau                      7.0.0-31-generic (x86_64)
  systemd                    systemd 255 (255.4-1ubuntu8.17)
  session                    wayland
  bureau                     ubuntu:GNOME
  connexion                  /usr/sbin/gdm3
  démarrée depuis          up 4 days, 22 minutes

## Machine

  sys_vendor                 LENOVO
  product_version            ThinkCentre M720q
  product_name               10T8S9LP00
  board_name                 312D
  processeur                 Intel(R) Core(TM) i3-8100T CPU @ 3.10GHz
  cœurs / fils              4
  mémoire                   15Gi dont 8.6Gi disponibles

## GPU et décodage vidéo

  00:02.0 VGA compatible controller [0300]: Intel Corporation CoffeeLake-S GT2 [UHD Graphics 630] [8086:3e91]
  pilote noyau               i915
  NVIDIA                     aucun
  rendu OpenGL               Mesa Intel(R) UHD Graphics 630 (CFL GT2)
  VA-API                     vainfo absent (paquet vainfo) — décodage matériel non vérifié
  AV1 matériel              non vérifiable sans vainfo

## Sorties d'affichage

  DP-1                       disconnected
  DP-2                       disconnected
  HDMI-A-1                   disconnected
  HDMI-A-2                   disconnected
  HDMI-A-3                   disconnected

  _Une sortie « disconnected » ne se mesure pas : résolution, fréquence et_
  _audio HDMI ne sont lisibles qu' écran branché._

## HDMI-CEC (télécommande de la TV)

  /dev/cec*                  aucun — pas de CEC matériel sur cette machine

  _Sans CEC, la télécommande de la TV ne pilote pas le HUB. Il faut soit un_
  _adaptateur USB-CEC, soit une manette ou un clavier sans fil._

## Audio

  pipewire                   active
  wireplumber                active
  pulseaudio                 inactive
—
  pactl                      absent (paquet pulseaudio-utils) — sorties non listées
  cartes ALSA :
    card 0: PCH [HDA Intel PCH], device 0: ALC233 Analog [ALC233 Analog]
    card 0: PCH [HDA Intel PCH], device 3: HDMI 0 [HDMI 0]
    card 0: PCH [HDA Intel PCH], device 7: HDMI 1 [HDMI 1]
    card 0: PCH [HDA Intel PCH], device 8: HDMI 2 [HDMI 2]

## Réseau

  eno1             DOWN           
  wlx(masqué)      UP             192.168.x.x/24 (masquée) 3 × IPv6 globale/64 (masquées) fe80::(masquée)/64 
  br-060ae02bc718  UP             172.18.0.1/16 fe80::(masquée)/64 
  docker0          DOWN           172.17.0.1/16 
  veth5307bdd@if2  UP             fe80::(masquée)/64 
  vetha70e2aa@if2  UP             fe80::(masquée)/64 

  eno1 (filaire)             DÉBRANCHÉ
  wlx(masqué)     (sans fil) branché

  wlx(masqué)      IEEE 802.11  ESSID:"(masqué)"  
            Mode:Managed  Frequency:2.462 GHz  Access Point: (masqué)   
            Bit Rate=26 Mb/s   Tx-Power=20 dBm   
            Link Quality=42/70  Signal level=-68 dBm  

  _Le débit wifi annoncé est un débit négocié, pas un débit utile : comptez la_
  _moitié. Pour du streaming de jeu, seul un test réel a valeur de preuve._

## Bluetooth

  contrôleur                AUCUN détecté par le noyau

  _Sans Bluetooth : pas de manette, pas de télécommande, pas de casque sans fil._

## Stockage

  NAME      SIZE MODEL                      ROTA
  sda     476.9G HIKSEMI PSSD                  1
  nvme0n1 238.5G SAMSUNG MZVLB256HAHQ-000L7    0

  NAME        TYPE  FSTYPE      MOUNTPOINT
  sda         disk              
  ├─sda1      part  exfat       /media/(masqué)
  └─sda2      part  crypto_LUKS 
    └─travail crypt ext4        /mnt/ssd
  nvme0n1     disk              
  ├─nvme0n1p1 part  vfat        /boot/efi
  └─nvme0n1p2 part  ext4        /

  Filesystem      Size  Used Avail Use% Mounted on
  /dev/nvme0n1p2  233G  171G   50G  78% /
  /dev/nvme0n1p2  233G  171G   50G  78% /
  /dev/nvme0n1p1  1.1G  6.2M  1.1G   1% /boot/efi

  volumes chiffrés déclarés :
    travail UUID=(masqué) none luks,nofail
    (« nofail » = le démarrage continue si le volume ne s'ouvre pas)
  racine chiffrée           non

## Logiciels du HUB

  kodi                       —
  steam                      —
  moonlight-qt               —
  sunshine                   —
  gamescope                  —
  retroarch                  —
  vlc                        /usr/bin/vlc
  mpv                        —
  cec-client                 —
  vainfo                     —
  glxinfo                    /usr/bin/glxinfo
  wmctrl                     —
  ethtool                    /usr/sbin/ethtool
  flatpak                    présent, 0 applications
  snap                       présent, 36 paquets

## Sessions proposées à la connexion

  /usr/share/wayland-sessions :
    ubuntu-wayland.desktop
    ubuntu.desktop
  /usr/share/xsessions :
    plasma.desktop
    ubuntu-xorg.desktop
    ubuntu.desktop

## Ce qui reste non mesuré

  Ces points ne se mesurent pas depuis un terminal, ou pas sans matériel branché.
  Les laisser en blanc vaut mieux que les supposer.

  [ ] résolution et fréquence réellement négociées avec la TV
  [ ] sortie audio HDMI (présence, canaux, passthrough)
  [ ] débit Ethernet réel, mesuré vers la box
  [ ] latence et stabilité en streaming de jeu
  [ ] consommation et bruit du ventilateur en lecture 4K prolongée

