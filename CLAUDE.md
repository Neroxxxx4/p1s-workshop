# P1S Workshop — CLAUDE.md

## Contexte

Petite app web perso pour gérer un atelier d'impression 3D (imprimante Bambu Lab P1S) : stock de filament, impressions, calcul des coûts, prix de vente et ventes.

L'ancienne version était un `app.py` Flask unique, encodé en base64 dans un `docker-compose.yml`. Elle était réinstallée avec pip à chaque démarrage et tournait sur un **NAS UGREEN (UGOS Pro, app Docker)**, port 8501.

Objectif : réécrire l'app proprement, avec les mêmes fonctionnalités, et surtout une compatibilité totale avec la base SQLite existante (`workshop.db`, déjà sauvegardée par l'utilisateur).

L'utilisateur parle français : l'interface, les messages et les commentaires sont en français.

## Contraintes non négociables

1. La base existante doit s'ouvrir telle quelle. On ne renomme ni ne supprime aucune table ou colonne. Les migrations sont uniquement additives (`ALTER TABLE ... ADD COLUMN` avec valeur par défaut), idempotentes et appliquées au démarrage.
2. Les valeurs stockées gardent le même format : statuts, formats de date, format de l'id de bobine, JSON des ventes (voir le schéma ci-dessous). On peut lire plusieurs formats, mais on n'écrit pas dans un format incompatible avec les anciennes lignes.
3. Le chemin de la DB vient de la variable d'environnement `DB_PATH`, avec `./data/workshop.db` par défaut.
4. Le port vient de `PORT`, avec 8501 par défaut. Le fuseau horaire est Europe/Paris.
5. Le déploiement cible est Docker sur un NAS UGREEN (UGOS Pro). Le volume monté est `/volume1/docker/P1SWorkshop/data:/data`.
6. Ne jamais toucher à la vraie DB pendant le dev : on travaille sur une copie (`./data/workshop.db`).

## Stack

- Python 3.12, Flask, templates Jinja2 (auto-échappement).
- SQLite via le module standard `sqlite3`, sans ORM.
- `zoneinfo` (+ paquet `tzdata` pour les images slim) à la place de `pytz`.
- Front : HTML, CSS et JS vanilla, sans build ni CDN. Mobile d'abord (utilisé depuis un téléphone à côté de l'imprimante).
- Prod : gunicorn dans le conteneur. Dépendances installées au build.

## Schéma de la base existante (à respecter exactement)

Vérifié sur la vraie DB (sept. 2026) : identique au schéma ci-dessous, avec en plus
`FOREIGN KEY (bobine_id) REFERENCES stock(id)` déclarée sur `impressions` (non appliquée :
`PRAGMA foreign_keys` reste désactivé, il ne faut pas l'activer).

```sql
CREATE TABLE IF NOT EXISTS stock (
    id TEXT PRIMARY KEY,          -- "{marque} {matiere} {couleur}", ex: "Bambu Lab PLA Noir"
    marque TEXT NOT NULL,
    matiere TEXT NOT NULL,        -- PLA, PETG, TPU, ASA, ABS, Autre
    couleur TEXT NOT NULL,
    prix REAL NOT NULL,           -- €/kg
    reste REAL NOT NULL,          -- grammes restants
    capacite REAL DEFAULT 1000    -- grammes (taille de la bobine)
);

CREATE TABLE IF NOT EXISTS impressions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_lancement TEXT NOT NULL, -- "%Y-%m-%d %H:%M:%S" heure locale Paris
    nom TEXT NOT NULL,
    bobine_id TEXT NOT NULL,      -- référence stock.id
    poids REAL NOT NULL,          -- grammes consommés (objet + perte)
    cout REAL NOT NULL,           -- €, arrondi à 2 décimales
    duree_minutes INTEGER NOT NULL,
    statut TEXT NOT NULL,         -- 'EN_COURS' | 'SUCCES' | 'ECHEC'
    fin_prevue TEXT NOT NULL      -- "%Y-%m-%d %H:%M:%S" heure locale Paris
);

CREATE TABLE IF NOT EXISTS ventes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,           -- ATTENTION : format "%d/%m/%Y %H:%M" (différent des impressions)
    nom TEXT NOT NULL,
    nb_pieces INTEGER NOT NULL,
    cout_total REAL NOT NULL,
    marge_pct REAL NOT NULL,      -- ex: 100 = +100 %
    prix_vente REAL NOT NULL,
    benefice REAL NOT NULL,
    pieces_json TEXT NOT NULL     -- JSON: [{"id": <impression_id>, "nom": "...", "cout": 1.23}, ...]
);
```

Remarques :

- `bobine_id` peut pointer vers une bobine supprimée : l'interface doit le gérer sans planter.
- Les lignes importées par CSV ont `duree_minutes = 0` et `fin_prevue = date_lancement`.
- Certaines anciennes ventes ont une clé `"poids"` en plus dans `pieces_json` : à tolérer en lecture.

## Fonctionnalités (6 onglets)

En-tête global : filament total restant (g), nombre d'impressions, coût cumulé (€), impressions en cours.

### 1. Lancement

Formulaire : nom (vide → « Sans nom »), bobine (stock vide → message vers Stock), poids objet (g, défaut 0), perte (g, défaut 5), durée h + min, prix kWh (défaut 0.25), usure machine (€/h, défaut 0.10).

```
poids_total = poids_objet + perte
duree_h     = heures + minutes / 60
cout        = (prix_kg / 1000) * poids_total + duree_h * (usure + PUISSANCE_KW * prix_kwh)
```

`PUISSANCE_KW = 0.2` (200 W moyens) dans `services.py`.

Effets : insertion `EN_COURS` avec `fin_prevue = maintenant + durée`, `reste = MAX(0, reste - poids_total)`, redirection vers Historique.
Validations : durée > 0, poids objet > 0, erreurs claires sur saisie invalide. Liste des bobines + aperçu du coût en direct.

### 2. Stock

Liste avec jauge (vert > 50 %, orange > 20 %, rouge sinon). Ajout (id = `"{marque} {matiere} {couleur}"`, `reste = capacite`, `INSERT OR REPLACE` avec confirmation si l'id existe). Suppression confirmée. Modification du prix et du reste.

### 3. Historique

Alertes pour les `EN_COURS` dont `fin_prevue` est passée (Réussite / Échec). Métriques et taux de réussite (vert ≥ 80 %, orange ≥ 50 %). Liste récente → ancienne. Actions : forcer la fin, supprimer, supprimer et rendre le filament (`MIN(capacite, reste + poids)`), changer le statut.
Import CSV `Date, Nom, Bobine, Poids, Cout, Statut` (encodages utf-8/utf-8-sig, cp1252, latin-1 ; statut « cours » → EN_COURS, « chec »/« fail » → ECHEC, sinon SUCCES ; date du CSV parsée, repli sur maintenant). Résumé importées/ignorées. Zone de danger « vider l'historique » avec double confirmation.

### 4. Prix de vente

Impressions SUCCES cliquables → panier. Marge 0–500 % pas de 5 (défaut 100), curseur + champ. `prix = cout * (1 + marge/100)`, `benefice = prix - cout`. Scénarios +25/50/75/100/150/200/300 %. Enregistrement (vide → « Vente sans nom ») : le serveur recalcule le coût depuis la DB.

### 5. Ventes

Métriques (nombre, revenus, bénéfices), accordéon avec détail et pièces, suppression, « Effacer toutes les ventes ».

### 6. DB

Export via `conn.backup()`. Import `.db/.sqlite/.sqlite3` validé (tables `stock` et `impressions`), sauvegarde auto `workshop.db.bak-YYYYMMDD-HHMMSS`, remplacement, init + migrations. Confirmation obligatoire.

## UX / sécurité

- Look sobre, cartes arrondies, accent `#5B5FEF`, onglets pilules, mode sombre. Mobile d'abord.
- Flash + PRG, une route par onglet. Montants `12.34 €`, chiffres tabulaires.
- SQL paramétré, auto-échappement Jinja, CSRF maison, `APP_PASSWORD` optionnel, pas de debug en prod, une connexion SQLite par requête.

## Déploiement (UGREEN)

- `Dockerfile` : `python:3.12-slim`, deps au build, gunicorn.
- `docker-compose.yml` : volume `/volume1/docker/P1SWorkshop/data:/data`, `user:` à régler sur l'UID/GID du propriétaire du dossier (`id` en SSH sur le NAS).
- Déploiement : app Docker d'UGOS → Projet, ou `docker compose up -d --build` en SSH.

## Tests

`pytest` : `services.py` (coût, prix, statuts, dates CSV), intégration sur une DB « ancien format » (vente datée `%d/%m/%Y %H:%M`, impression liée à une bobine supprimée), import/export DB.

## Manière de travailler

1. Inspecter la DB fournie sur une copie avant de toucher au code d'accès.
2. Avancer onglet par onglet, vérifier avec les tests.
3. Pas de dépendances lourdes sans raison.
