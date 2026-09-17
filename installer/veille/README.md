# Le mode ambiant du HUB sur le bureau Ubuntu

**Le défaut réglé.** En mode Bureau, rester sans rien toucher donnait l'écran noir de GNOME,
puis l'écran de verrouillage. Le mode ambiant du HUB (heure, date, météo, cadre photo, fond
animé) n'existe que dans la page du menu, et le menu est fermé tant que le bureau est ouvert.

État au 17 septembre 2026 : **prouvé par tests seulement** (Mac de développement, ni GNOME
ni Mutter). Rien n'a tourné sur le M720q ni en VM.

## Comment ça marche

1. À l'ouverture du bureau (session `ubuntu`), l'autostart `hub-veille-bureau.desktop`
   (`OnlyShowIn=ubuntu`) lance `hub-veille-bureau`. Une seule instance par session (verrou
   dans `$XDG_RUNTIME_DIR/hub/`).
2. Il lit le délai du mode ambiant dans `~/.config/hub/reglages.json`, comme la page :
   réglage du profil actif, sinon réglage commun, sinon 10 min.
3. Il demande à Mutter d'être prévenu après ce délai sans clavier ni souris
   (`org.gnome.Mutter.IdleMonitor.AddIdleWatch`).
4. Au signal, il vérifie que l'écran n'est pas déjà noir ou verrouillé
   (`org.gnome.ScreenSaver.GetActive`) et qu'aucune application n'empêche la veille
   (`org.gnome.SessionManager.IsInhibited(8)` : vidéo en plein écran, présentation). Mutter
   ne déclenche d'ailleurs pas la surveillance tant que la veille est inhibée.
5. Il lance `hub-menu --ambiant` : la page du menu en plein écran, directement en mode
   ambiant. L'accueil n'est jamais montré.
6. **Premier geste** : touche, clic, molette, toucher, vrai déplacement de souris (pas le
   frôlement, pas l'apparition de la fenêtre sous le pointeur) ou bouton de manette. La
   fenêtre se ferme et le bureau revient tel qu'il était. Clavier et souris sont arrêtés
   dans GTK avant la page : la touche de réveil n'arrive à personne. La fenêtre n'accepte
   de la page que la météo, le cadre photo et « ambiant-fin » : aucun choix de mode, aucun
   réglage enregistré, pas de voix, pas d'appairage.
7. Filets : si la fenêtre est encore là une seconde après le retour de l'utilisateur (vu
   par `AddUserActiveWatch`), elle est fermée ; quand l'écran noir de GNOME arrive
   (`ActiveChanged(true)`), elle est fermée aussi, pour retrouver le bureau au déverrouillage.

Sources lues le 17/09/2026 (gitlab.gnome.org, étiquettes `50.0`) : l'en-tête de
`hub-veille-bureau` les cite fichier par fichier.

## Avec la veille de GNOME

| Moment (réglages par défaut) | Qui | Quoi |
|---|---|---|
| délai du menu (10 min) | HUB | mode ambiant |
| `org.gnome.desktop.session idle-delay` | GNOME | écran noir, puis verrouillage (`lock-enabled`, `lock-delay`) |
| `org.gnome.settings-daemon.plugins.power sleep-inactive-ac-*` | GNOME | mise en veille : **0 (jamais) sur secteur** dans Ubuntu 26.04 (`ubuntu-settings`) |

`idle-delay` vaut 300 s par défaut : l'écran noir passerait avant l'ambiant. S'il laisse
moins de 5 min d'ambiant, `hub-veille-bureau` le **relève** à délai + 15 min (25 min pour 10)
et l'écrit dans le journal. Il ne le baisse jamais et laisse « Jamais » (0) tel quel. **Le
verrouillage n'est pas désactivé** : il arrive simplement après le mode ambiant, au même
moment qu'avant par rapport à l'écran noir. Une mise en veille automatique réglée avant
l'écran noir est signalée dans le journal, pas modifiée.

Ce réglage vit ici et pas dans `hub-theme` : `hub-theme` est l'habillage, qu'on désactive
et « restaure » depuis le menu ; le délai d'écran noir n'est pas de l'apparence et dépend
du délai du mode ambiant.

## Temps d'écran

`hub-temps-ecran bureau` compte la durée de la session, activité ou pas. Pendant que le
mode ambiant est affiché, `hub-veille-bureau` écrit le numéro du processus dans
`$XDG_RUNTIME_DIR/hub/ambiant-bureau` et le décompte se met en pause (seulement si ce
numéro est bien un `hub-menu --ambiant` vivant). Les minutes d'inactivité *avant* l'ambiant
restent comptées, comme avant.

Réglé au passage : `hub-temps-ecran-bureau.desktop` portait `X-GNOME-Autostart-Phase`,
que GNOME 50 ignore (ARCHITECTURE.md, pièges ; `systemd-xdg-autostart-generator` marque
ces entrées `NotShowIn=GNOME` et gnome-session 50 n'a plus de lanceur à lui). Le temps
passé sur le bureau n'était vraisemblablement pas compté du tout.

## Régler, désactiver, diagnostiquer

- **Délai** : Réglages → Mode ambiant dans le menu du HUB (5, 10, 30 min). Lu à
  l'ouverture du bureau : un changement vaut pour la prochaine session Bureau.
- **Désactiver** : Réglages → Mode ambiant → « Jamais » (GNOME garde alors sa veille, rien
  n'est écrit). Pour couper le programme lui-même, pour cet utilisateur :
  ```bash
  mkdir -p ~/.config/autostart
  printf '[Desktop Entry]\nHidden=true\n' > ~/.config/autostart/hub-veille-bureau.desktop
  ```
- **Rendre à GNOME son délai d'écran noir** : `gsettings reset org.gnome.desktop.session idle-delay`
  (ou Paramètres → Alimentation → Écran noir).
- **Ce qu'il ferait**, sans rien écrire : `hub-veille-bureau --etat`.
- **Journal** : `journalctl --user -b | grep hub-veille-bureau`.
- **Essayer l'ambiant sans attendre** : `hub-menu --ambiant` depuis un terminal du bureau.

## À éprouver sur le M720q / en VM

- [ ] `systemctl --user list-units 'app-*hub*'` sur le bureau : `hub-veille-bureau` et
      `hub-temps-ecran bureau` démarrés (le second n'avait plus de phase)
- [ ] `hub-veille-bureau --etat` : délai lu, `idle-delay` 300 → 1500 voulu
- [ ] 10 min sans rien toucher : l'ambiant apparaît en plein écran **au-dessus** de la barre
      du haut et du dock, avec le clavier (focus donné par Mutter à une fenêtre ouverte sans
      jeton d'activation : non vérifié)
- [ ] une touche (« 3 », Entrée) : le bureau revient, rien ne se lance, la touche n'arrive
      pas à la fenêtre du dessous
- [ ] souris posée sous la fenêtre qui apparaît : l'ambiant reste ; vrai mouvement : il se ferme
- [ ] bouton de manette : il se ferme (API Gamepad de WebKitGTK sans geste préalable ?)
- [ ] vidéo YouTube en plein écran dans Chrome, 15 min : pas d'ambiant
- [ ] écran noir de GNOME après `idle-delay` : ambiant fermé, écran verrouillé, déverrouillage
      → bureau sans horloge
- [ ] `hub-temps-ecran etat` avant et après 10 min d'ambiant : le temps du bureau n'a pas
      avancé pendant l'ambiant
- [ ] session HUB (kiosque) après ce changement d'`idle-delay` (dconf commun) : rien de changé
      pour le menu ni pour Kodi
- [ ] assombrissement de gnome-settings-daemon (`idle-dim`, à la moitié d'`idle-delay` :
      12 min 30 pour 10 min) : l'ambiant ne reste lumineux que 2 min 30 ; acceptable ou non
