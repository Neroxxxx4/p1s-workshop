# P1S Workshop

Gestion d'atelier d'impression 3D (Bambu Lab P1S) : stock de filament, impressions, coûts, prix de vente et ventes.
Flask + SQLite, sans build front, pensé pour le téléphone.

## 1. Lancer en local (Mac)

Toujours sur une **copie** de la base :

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
mkdir -p data && cp ~/Downloads/workshop.db data/workshop.db
.venv/bin/flask --app app:create_app run --port 8501 --debug
```

Ouvrir http://localhost:8501. Tests : `.venv/bin/python -m pytest`.

Variables d'environnement :

| Variable | Défaut | Rôle |
|---|---|---|
| `DB_PATH` | `./data/workshop.db` | chemin de la base |
| `PORT` | `8501` | port (conteneur) |
| `APP_PASSWORD` | *(vide)* | si défini, un mot de passe est demandé |
| `SECRET_KEY` | générée dans `.secret_key` à côté de la DB | signature des sessions |

## 2. Déployer sur le NAS UGREEN (UGOS Pro)

### Préparer le dossier

L'image est construite par GitHub à chaque `git push` et publiée sur `ghcr.io/neroxxxx4/p1s-workshop:latest`.
Le NAS n'a besoin d'aucun fichier de code : seulement de la base.

1. Dans **Fichiers**, créer `docker/P1SWorkshop/data` (le dossier partagé `docker` est créé par l'app Docker).
2. Y déposer la base actuelle sous le nom `workshop.db`.

> Le chemin réel est en général `/volume1/docker/...`. Pour le vérifier : clic droit sur le dossier → **Propriétés**, ou `ls /volume1/docker` en SSH. Si ton volume est `volume2`, adapte la ligne `volumes:` du compose.

### Permissions (UID/GID)

Le conteneur ne tourne pas en root : il doit pouvoir écrire dans `data/`. En SSH (**Panneau de configuration → Terminal → activer SSH**) :

```bash
ssh ton_utilisateur@IP_DU_NAS
id
```

On obtient par exemple `uid=1000(maurice) gid=10(admin)`. Reporter ces valeurs dans `docker-compose.yml` :

```yaml
user: "1000:10"
```

En cas d'erreur `unable to open database file` ou `readonly database`, c'est cette ligne qui est fausse.

### Lancer

**Option A : interface UGOS.** App **Docker → Projet → Créer**, nom `p1s-workshop`, chemin `docker/P1SWorkshop`, puis coller le contenu de `docker-compose.yml` dans l'éditeur. Valider.

**Option B : SSH.** Copier `docker-compose.yml` dans `/volume1/docker/P1SWorkshop/`, puis :

```bash
cd /volume1/docker/P1SWorkshop && sudo docker compose up -d
```

L'app est ensuite sur `http://IP_DU_NAS:8501`. Sur iPhone : Safari → Partager → **Sur l'écran d'accueil**.

**Mettre à jour** : `git push` depuis le Mac, attendre la fin du build (onglet **Actions** sur GitHub, environ 3 min), puis sur le NAS **Docker → Projet → p1s-workshop → Arrêter / Démarrer** (`pull_policy: always` récupère la nouvelle image). En SSH : `sudo docker compose pull && sudo docker compose up -d`.

## 3. La base et ses sauvegardes

- Emplacement : `/volume1/docker/P1SWorkshop/data/workshop.db` sur le NAS (`/data/workshop.db` dans le conteneur).
- **Sauvegarde depuis l'app** : onglet **DB → Télécharger une sauvegarde**. La copie est cohérente même si l'app tourne.
- **Restauration** : onglet **DB → Importer**. La base actuelle est d'abord sauvegardée à côté (`workshop.db.bak-AAAAMMJJ-HHMMSS`).
- **Sauvegarde automatique** : inclure le dossier `docker/P1SWorkshop/data` dans une tâche de l'app **Sync & Backup** d'UGOS.
- Copier `workshop.db` directement est sûr quand le conteneur est arrêté. Il tourne sans WAL, le fichier seul suffit.

## 4. Dépôts Git

`git push` envoie le code à la fois sur GitHub (qui construit l'image) et sur le Gitea du NAS
(`http://192.168.1.26:3111/Maurice/P1S-Workshop`), qui sert de copie locale.
Pour retrouver cette configuration sur une autre machine :

```bash
git remote set-url --add --push origin https://github.com/Neroxxxx4/p1s-workshop.git
git remote set-url --add --push origin http://192.168.1.26:3111/Maurice/P1S-Workshop.git
```
