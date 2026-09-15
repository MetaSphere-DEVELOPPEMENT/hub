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

Puis :

```sh
groupadd -f hub && usermod -aG hub "$UTILISATEUR"
install -d -m 0755 /etc/hub /var/lib/hub/versions
printf 'HUB_UTILISATEUR=%s\n' "$UTILISATEUR" > /etc/hub/mise-a-jour.env
# seulement si absent : c'est l'utilisateur qui choisit la source
[ -f /etc/hub/mise-a-jour.json ] || echo '{"source": "", "branche": "main"}' > /etc/hub/mise-a-jour.json
systemctl daemon-reload
```

Le service n'est **pas** activé au démarrage : il ne tourne que quand le menu le lance.

## Choisir la source

`/etc/hub/mise-a-jour.json` :

```json
{"source": "https://github.com/samuel-boudine-pro/hub.git", "branche": "main"}
```

- **Dépôt GitHub privé** : `root` (le service) et l'utilisateur (la vérification
  depuis le menu) doivent pouvoir le lire. Le plus simple : une *deploy key* en lecture
  seule, ajoutée au dépôt, et `"source": "git@github.com:samuel-boudine-pro/hub.git"`
  avec la clé dans `/root/.ssh/` et `~/.ssh/` de l'utilisateur.
- **Le Mac sur le réseau local** : `"source": "ssh://samuel@mac.local/Volumes/Projets/projets/hub"`.

## Ce qui est garanti

- Rien n'est installé si les tests de la nouvelle version échouent.
- Si l'installateur échoue, celui de la version précédente est relancé.
- Les réglages, profils, codes et photos (`~/.config/hub`, `~/Images/HUB`) ne sont jamais touchés.
- Les trois dernières versions restent dans `/var/lib/hub/versions/`.

Tests : `python3 -m unittest tests/test_hub_mise_a_jour.py` (vrai git, installateur simulé).
