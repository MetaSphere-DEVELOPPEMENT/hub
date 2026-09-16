# Mise à jour du HUB

Le menu (Réglages → À propos) vérifie s'il existe une version plus récente du dépôt et
l'installe en un geste. Tout le détail du fonctionnement est en tête de
`hub-mise-a-jour`.

## Ce que l'installateur doit poser

| Fichier du dépôt | Destination | Droits |
|---|---|---|
| `hub-mise-a-jour` | `/usr/local/bin/hub-mise-a-jour` | 0755 |
| `hub-mise-a-jour.service` | `/etc/systemd/system/hub-mise-a-jour.service` | 0644 |
| `50-hub-mise-a-jour.rules` | `/etc/polkit-1/rules.d/50-hub-mise-a-jour.rules` | 0644 |
| `signataires-autorises` | `/etc/hub/signataires-autorises` (voir plus bas) | 0644, root |

Puis :

```sh
groupadd -f hub && usermod -aG hub "$UTILISATEUR"
install -d -m 0755 /etc/hub /var/lib/hub/versions
printf 'HUB_UTILISATEUR=%s\n' "$UTILISATEUR" > /etc/hub/mise-a-jour.env
# seulement si absent : l'utilisateur peut choisir une autre source
[ -f /etc/hub/mise-a-jour.json ] ||
  echo '{"source": "https://github.com/MetaSphere-DEVELOPPEMENT/hub.git", "branche": "master"}' > /etc/hub/mise-a-jour.json
systemctl daemon-reload
```

`hub-installer.sh` le fait (étape « Mise à jour depuis le menu »), et installe `git`,
absent d'une Ubuntu Desktop neuve.

Le service n'est **pas** activé au démarrage : il ne tourne que quand le menu le lance.

## Seuls les commits signés sont installés

Le dépôt est public et l'installateur tourne en root. Le HUB n'installe donc que le
commit **signé** (signature SSH de git) par une clé listée dans
`/etc/hub/signataires-autorises`. Un compte GitHub volé ou une PR fusionnée par
erreur ne suffisent plus à prendre la main sur le HUB.

- Fichier absent, ou sans aucune clé : **rien n'est installé** (menu : « aucun
  signataire autorisé »).
- Commit non signé, ou signé par une autre clé : **rien n'est installé**, le clone est
  effacé (menu : signature refusée).
- Seul le **dernier commit** de la branche compte : c'est lui qui est cloné et vérifié.
  L'historique peut contenir des commits non signés.
- **Tout commit de tête créé sans la clé est refusé** : fusion par le bouton de
  GitHub (signée par la clé de GitHub, pas la tienne), modification dans l'interface
  web, commit fait sur une autre machine ou par un outil qui n'a pas la clé.
  Fusionner en local, signer, pousser.

### Une fois, sur la machine de développement

```sh
# Une clé existante convient ; sinon :
ssh-keygen -t ed25519 -C "moi@exemple"
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
```

Ajouter sa clé **publique** au fichier du dépôt, la committer (signée) et pousser :

```sh
echo "moi@exemple namespaces=\"git\" $(cut -d' ' -f1,2 ~/.ssh/id_ed25519.pub)" \
  >> installer/mise-a-jour/signataires-autorises
git add installer/mise-a-jour/signataires-autorises
git commit -m "…" && git push
```

L'adresse n'est qu'un nom affiché ; ce qui compte est la clé. Vérifier en local que
la signature passe :

```sh
git -c gpg.ssh.allowedSignersFile=installer/mise-a-jour/signataires-autorises verify-commit HEAD
# Good "git" signature for moi@exemple with ED25519 key SHA256:…
```

### Une fois, sur un HUB déjà installé

L'installateur pose le fichier seulement s'il est **absent de `/etc/hub` ou sans
clé** (première installation, depuis un support qu'on contrôle), ou quand il tourne
depuis un commit dont la signature vient d'être vérifiée (c'est ainsi qu'on ajoute
ou remplace une clé plus tard : un commit signé par l'ancienne clé). Lancé à la main
depuis un clone quelconque, il ne remplace jamais un fichier qui contient déjà une clé.

Le plus sûr, sur le HUB (mode Bureau, ou en SSH), avec le fichier rempli ci-dessus :

```sh
sudo install -m 0644 -o root -g root signataires-autorises /etc/hub/signataires-autorises
```

Sans ce geste, la première mise à jour vers cette version s'installe encore sans
vérification (c'est l'ancien `hub-mise-a-jour` qui la mène) et pose le fichier du
dépôt ; les suivantes sont vérifiées.

Clé perdue ou changée sans commit signé par l'ancienne : refaire le `sudo install`
ci-dessus avec la nouvelle ligne.

### Diagnostic, un soir de panne

```sh
cat /run/hub-mise-a-jour/etat.json          # "raison": "signataires" | "signature" | "tests" | …
journalctl -u hub-mise-a-jour -n 50
hub-mise-a-jour verifier                    # "verifiable": false = aucun signataire utilisable
ls -l /etc/hub/signataires-autorises        # root, -rw-r--r-- ; sinon refusé
# Vérifier à la main le commit que le HUB téléchargerait :
git clone --depth 1 --branch master https://github.com/MetaSphere-DEVELOPPEMENT/hub.git /tmp/hub-verif
git -C /tmp/hub-verif -c gpg.ssh.allowedSignersFile=/etc/hub/signataires-autorises verify-commit HEAD
```

« No principal matched » : la clé qui a signé n'est pas dans le fichier. Aucune
sortie et code 1 : le commit de tête n'est pas signé (voir la liste des cas plus haut).
(Messages relevés avec git 2.54 le 17/09/2026.)

## Les tests ne tournent pas en root

Les tests du dépôt sont du code arbitraire lancé avant l'installation. Ils tournent
**après** la vérification de signature, sous l'utilisateur **`nobody`** (`runuser`),
dans une copie jetable du clone (sans `.git`) posée dans un dossier temporaire à
nobody, avec un `HOME` et un `TMPDIR` pris dans ce dossier. Pas sous l'utilisateur du
HUB : ils auraient accès à ses codes, ses photos, son `~/.bashrc`. Et jamais dans le
clone lui-même, que root installe ensuite.

Conséquence : un test qui a besoin de root, du vrai `HOME` de l'utilisateur ou
d'écrire hors de son dossier échoue sur le HUB, et la mise à jour est refusée.

## Choisir la source

`/etc/hub/mise-a-jour.json`, par défaut :

```json
{"source": "https://github.com/MetaSphere-DEVELOPPEMENT/hub.git", "branche": "master"}
```

La branche du dépôt est **`master`**, pas `main`. Le dépôt est public : HTTPS suffit,
sans compte ni clé d'accès. La confiance vient de la signature, pas de la source.

- **Le Mac sur le réseau local** : `"source": "ssh://samuel@mac.local/Volumes/Projets/projets/hub"`.
- **Un dépôt local** (essai) : `"source": "/srv/hub.git"`. S'il n'appartient pas à
  root, git refuse de le lire en root (« dubious ownership ») :
  `git config --system --add safe.directory /srv/hub.git`. Éprouvé en VM le 15/09/2026
  (avant la vérification de signature).

Quelle que soit la source, les commits doivent être signés.

## Ce qui est garanti

- Rien n'est installé ni exécuté (pas même les tests) si le commit n'est pas signé par
  une clé de `/etc/hub/signataires-autorises`.
- Rien n'est installé si les tests de la nouvelle version échouent.
- Si l'installateur échoue, celui de la version précédente est relancé.
- Les réglages, profils, codes et photos (`~/.config/hub`, `~/Images/HUB`) ne sont jamais touchés.
- Les trois dernières versions restent dans `/var/lib/hub/versions/`.

Tests : `python3 -m unittest tests/test_hub_mise_a_jour.py` (vrai git ≥ 2.34, vraies
clés SSH jetables, installateur et `runuser` simulés).
