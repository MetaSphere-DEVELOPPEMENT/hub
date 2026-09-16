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
# seulement si absent : l'utilisateur peut choisir une autre source
[ -f /etc/hub/mise-a-jour.json ] ||
  echo '{"source": "https://github.com/MetaSphere-DEVELOPPEMENT/hub.git", "branche": "master"}' > /etc/hub/mise-a-jour.json
systemctl daemon-reload
```

`hub-installer.sh` le fait (étape « Mise à jour depuis le menu »), et installe `git`,
absent d'une Ubuntu Desktop neuve.

Le service n'est **pas** activé au démarrage : il ne tourne que quand le menu le lance.

## Choisir la source

`/etc/hub/mise-a-jour.json`, par défaut :

```json
{"source": "https://github.com/MetaSphere-DEVELOPPEMENT/hub.git", "branche": "master"}
```

La branche du dépôt est **`master`**, pas `main`.

- **Le dépôt GitHub est privé** : sans accès, « Rechercher » répond « source
  injoignable ». `root` (le service, qui clone) et l'utilisateur (la vérification
  depuis le menu, `git ls-remote`) doivent pouvoir le lire. Le plus simple : une
  **deploy key en lecture seule** — `ssh-keygen -t ed25519 -N ''`, clé publique ajoutée
  au dépôt (Settings → Deploy keys, sans « Allow write access »), la même clé privée
  dans `/root/.ssh/` et `~/.ssh/` de l'utilisateur, `github.com` dans leurs
  `known_hosts` — puis
  `"source": "git@github.com:MetaSphere-DEVELOPPEMENT/hub.git"`. Une URL HTTPS demanderait
  un jeton stocké en clair : à éviter.
- **Le Mac sur le réseau local** : `"source": "ssh://utilisateur@mon-mac.local/chemin/vers/hub"`.
- **Un dépôt local** (essai) : `"source": "/srv/hub.git"`. S'il n'appartient pas à
  root, git refuse de le lire en root (« dubious ownership ») :
  `git config --system --add safe.directory /srv/hub.git`. Éprouvé en VM le 15/09/2026.

## Ce qui est garanti

- Rien n'est installé si les tests de la nouvelle version échouent.
- Si l'installateur échoue, celui de la version précédente est relancé.
- Les réglages, profils, codes et photos (`~/.config/hub`, `~/Images/HUB`) ne sont jamais touchés.
- Les trois dernières versions restent dans `/var/lib/hub/versions/`.

Tests : `python3 -m unittest tests/test_hub_mise_a_jour.py` (vrai git, installateur simulé).
