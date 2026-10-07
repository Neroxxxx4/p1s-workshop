import sqlite3
from contextlib import closing

from flask import current_app, g

# Schéma identique à l'ancienne version (FK déclarée mais jamais activée : ne pas activer).
SCHEMA = """
CREATE TABLE IF NOT EXISTS stock (
    id TEXT PRIMARY KEY,
    marque TEXT NOT NULL,
    matiere TEXT NOT NULL,
    couleur TEXT NOT NULL,
    prix REAL NOT NULL,
    reste REAL NOT NULL,
    capacite REAL DEFAULT 1000
);
CREATE TABLE IF NOT EXISTS impressions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_lancement TEXT NOT NULL,
    nom TEXT NOT NULL,
    bobine_id TEXT NOT NULL,
    poids REAL NOT NULL,
    cout REAL NOT NULL,
    duree_minutes INTEGER NOT NULL,
    statut TEXT NOT NULL,
    fin_prevue TEXT NOT NULL,
    FOREIGN KEY (bobine_id) REFERENCES stock(id)
);
CREATE TABLE IF NOT EXISTS ventes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    nom TEXT NOT NULL,
    nb_pieces INTEGER NOT NULL,
    cout_total REAL NOT NULL,
    marge_pct REAL NOT NULL,
    prix_vente REAL NOT NULL,
    benefice REAL NOT NULL,
    pieces_json TEXT NOT NULL
);
"""

# Migrations additives uniquement : (table, colonne, définition avec défaut). Idempotentes.
# capacite manquait dans les toutes premières bases : on la rajoute si besoin.
AJOUTS_COLONNES = [
    ("stock", "capacite", "REAL DEFAULT 1000"),
]


def connect(path):
    # ponytail: journal "delete" par défaut (pas de WAL) : workshop.db reste copiable seul,
    # le timeout suffit pour 2 workers. Passer en WAL si des "database is locked" apparaissent.
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init(conn):
    conn.executescript(SCHEMA)
    for table, col, ddl in AJOUTS_COLONNES:
        if col not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    conn.commit()


def get():
    """Une connexion par requête."""
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def _close(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app):
    with closing(connect(app.config["DB_PATH"])) as conn:
        init(conn)
    app.teardown_appcontext(_close)
