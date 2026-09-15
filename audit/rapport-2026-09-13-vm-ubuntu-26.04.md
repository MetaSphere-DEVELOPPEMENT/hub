# Audit matériel — dimanche 13 septembre 2026, 09h30

_Mesuré sur `hub-essai`. Aucune installation, aucune modification._

## Système

  distribution               Ubuntu 26.04.1 LTS
  nom de code                resolute
  noyau                      7.0.0-31-generic (x86_64)
  systemd                    systemd 259 (259.5-0ubuntu3.4)
  session                    tty
  bureau                     aucun
  connexion                  /usr/sbin/gdm3
  démarrée depuis          up 1 minute

## Machine

  sys_vendor                 QEMU
  product_version            pc-q35-8.2
  product_name               Standard PC (Q35 + ICH9, 2009)
  processeur                 Intel(R) Core(TM) i3-8100T CPU @ 3.10GHz
  cœurs / fils              2
  mémoire                   3.3Gi dont 2.5Gi disponibles

## GPU et décodage vidéo

  00:02.0 VGA compatible controller [0300]: Red Hat, Inc. Virtio 1.0 GPU [1af4:1050] (rev 01)
  pilote noyau               virtio-pci
  NVIDIA                     aucun
  rendu OpenGL               glxinfo absent (paquet mesa-utils)
  VA-API                     vainfo absent (paquet vainfo) — décodage matériel non vérifié
  AV1 matériel              non vérifiable sans vainfo

## Sorties d'affichage

  Virtual-1                  connected  —  mode préféré 1280x800

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

## Réseau

  enp0s1           UP             10.0.2.15/24 fec0::5054:ff:fe12:3456/64 fe80::5054:ff:fe12:3456/64 

  enp0s1 (filaire)           branché


  _Le débit wifi annoncé est un débit négocié, pas un débit utile : comptez la_
  _moitié. Pour du streaming de jeu, seul un test réel a valeur de preuve._

## Bluetooth

  contrôleur                AUCUN détecté par le noyau

  _Sans Bluetooth : pas de manette, pas de télécommande, pas de casque sans fil._

## Stockage

  NAME  SIZE MODEL        ROTA
  sr0  1024M QEMU DVD-ROM    0
  vda    40G                 1

  NAME   TYPE FSTYPE MOUNTPOINT
  sr0    rom         
  vda    disk        
  ├─vda1 part vfat   /boot/efi
  └─vda2 part ext4   /

  Filesystem      Size  Used Avail Use% Mounted on
  /dev/vda2        39G   11G   26G  29% /
  /dev/vda2        39G   11G   26G  29% /
  /dev/vda1       1.1G  6.4M  1.1G   1% /boot/efi

  chiffrement                aucun volume déclaré dans /etc/crypttab
  racine chiffrée           non

## Logiciels du HUB

  kodi                       —
  steam                      —
  moonlight-qt               —
  sunshine                   —
  gamescope                  —
  retroarch                  —
  vlc                        —
  mpv                        —
  cec-client                 —
  vainfo                     —
  glxinfo                    —
  wmctrl                     —
  ethtool                    /usr/sbin/ethtool
  flatpak                    —
  snap                       présent, 13 paquets

## Sessions proposées à la connexion

  /usr/share/wayland-sessions :
    ubuntu.desktop

## Ce qui reste non mesuré

  Ces points ne se mesurent pas depuis un terminal, ou pas sans matériel branché.
  Les laisser en blanc vaut mieux que les supposer.

  [ ] résolution et fréquence réellement négociées avec la TV
  [ ] sortie audio HDMI (présence, canaux, passthrough)
  [ ] débit Ethernet réel, mesuré vers la box
  [ ] latence et stabilité en streaming de jeu
  [ ] consommation et bruit du ventilateur en lecture 4K prolongée

