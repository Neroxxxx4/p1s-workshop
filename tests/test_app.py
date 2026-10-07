import io
import json
import sqlite3

import pytest

from app import create_app

# Schéma exact de l'ancienne version, SANS la table ventes ni la colonne capacite
# (pour vérifier les migrations), et des lignes représentatives.
ANCIEN = """
CREATE TABLE stock (id TEXT PRIMARY KEY, marque TEXT NOT NULL, matiere TEXT NOT NULL,
    couleur TEXT NOT NULL, prix REAL NOT NULL, reste REAL NOT NULL);
CREATE TABLE impressions (id INTEGER PRIMARY KEY AUTOINCREMENT, date_lancement TEXT NOT NULL,
    nom TEXT NOT NULL, bobine_id TEXT NOT NULL, poids REAL NOT NULL, cout REAL NOT NULL,
    duree_minutes INTEGER NOT NULL, statut TEXT NOT NULL, fin_prevue TEXT NOT NULL,
    FOREIGN KEY (bobine_id) REFERENCES stock(id));
INSERT INTO stock VALUES ('Rosa3D PETG Vert', 'Rosa3D', 'PETG', 'Vert', 13, 153);
INSERT INTO impressions VALUES (1, '2026-04-29 22:18:00', 'Lève <b>meuble</b>', 'Rosa3D PETG Vert', 117, 2.07, 0, 'SUCCES', '2026-04-30 01:59:24');
INSERT INTO impressions VALUES (2, '2026-04-28 00:00:00', 'Orpheline', 'Bobine Supprimée PLA Rouge', 12, 0.27, 0, 'ECHEC', '2026-04-28 00:00:00');
INSERT INTO impressions VALUES (3, '2020-01-01 10:00:00', 'Finie hier', 'Rosa3D PETG Vert', 20, 0.5, 60, 'EN_COURS', '2020-01-01 11:00:00');
"""


def creer_ancienne_db(path, avec_ventes=True):
    with sqlite3.connect(path) as c:
        c.executescript(ANCIEN)
        if avec_ventes:
            c.executescript("""CREATE TABLE ventes (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
                nom TEXT NOT NULL, nb_pieces INTEGER NOT NULL, cout_total REAL NOT NULL, marge_pct REAL NOT NULL,
                prix_vente REAL NOT NULL, benefice REAL NOT NULL, pieces_json TEXT NOT NULL);""")
            c.execute("INSERT INTO ventes VALUES (2, '07/05/2026 13:23', 'Raph', 1, 0.45, 25, 0.56, 0.11, ?)",
                      ('[{"id": 1, "nom": "Lève meuble", "cout": 0.45, "poids": 26.0}]',))
    c.close()


@pytest.fixture
def env(tmp_path):
    path = tmp_path / "workshop.db"
    creer_ancienne_db(path)
    app = create_app({"DB_PATH": str(path), "TESTING": True})
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["csrf"] = "jeton"
    return app, client, path


def post(client, url, **data):
    return client.post(url, data={"csrf": "jeton", **data})


def lire(path, sql, *args):
    with sqlite3.connect(path) as c:
        return c.execute(sql, args).fetchall()


ONGLETS = ["/lancement", "/stock", "/historique", "/prix", "/ventes", "/db"]


def test_tous_les_onglets_sur_ancienne_db(env):
    _, client, path = env
    for url in ONGLETS:
        r = client.get(url)
        assert r.status_code == 200, url
    histo = client.get("/historique").get_data(as_text=True)
    assert "« Finie hier » est terminé" in histo
    assert "Bobine Supprimée PLA Rouge" in histo
    assert "&lt;b&gt;meuble" in histo and "<b>meuble" not in histo   # auto-échappement
    assert "07/05/2026 13:23" in client.get("/ventes").get_data(as_text=True)
    # migration additive : capacite ajoutée avec son défaut, données intactes
    assert lire(path, "SELECT reste, capacite FROM stock") == [(153.0, 1000.0)]


def test_csrf_obligatoire(env):
    _, client, path = env
    r = client.post("/stock/supprimer", data={"id": "Rosa3D PETG Vert"}, follow_redirects=True)
    assert "Session expirée" in r.get_data(as_text=True)
    assert lire(path, "SELECT COUNT(*) FROM stock")[0][0] == 1   # rien supprimé


def test_session_permanente_pour_iphone(env):
    _, client, _ = env
    assert "Expires=" in client.get("/stock").headers["Set-Cookie"]


@pytest.mark.parametrize("valeur", ["nan", "inf", "-inf", "1e400"])
def test_nombres_non_finis_refuses(env, valeur):
    _, client, path = env
    r = post(client, "/lancement", bobine="Rosa3D PETG Vert", poids=valeur, heures="1")
    assert r.status_code == 400 and "nombre valide" in r.get_data(as_text=True)
    assert lire(path, "SELECT reste FROM stock")[0][0] == 153            # bobine intacte
    assert post(client, "/prix/vendre", marge=valeur, ids=["1"]).status_code == 302
    assert lire(path, "SELECT COUNT(*) FROM ventes")[0][0] == 1


def test_virgule_decimale_iphone(env):
    _, client, path = env
    post(client, "/lancement", bobine="Rosa3D PETG Vert", poids="12,5", perte="0", kwh="0,25", heures="1")
    assert lire(path, "SELECT poids FROM impressions ORDER BY id DESC LIMIT 1")[0][0] == 12.5


def test_ids_inconnus_signales(env):
    _, client, _ = env
    for url, data in [("/historique/statut", {"id": "999", "statut": "SUCCES"}),
                      ("/stock/modifier", {"id": "?", "prix": "1", "reste": "1"}),
                      ("/stock/supprimer", {"id": "?"}), ("/ventes/supprimer", {"id": "999"})]:
        r = client.post(url, data={"csrf": "jeton", **data}, follow_redirects=True)
        assert "introuvable" in r.get_data(as_text=True), url


def test_stock_insuffisant_averti(env):
    _, client, path = env
    r = client.post("/lancement", data={"csrf": "jeton", "bobine": "Rosa3D PETG Vert", "poids": "500",
                                        "heures": "1"}, follow_redirects=True)
    assert "il ne restait que 153 g" in r.get_data(as_text=True)
    assert lire(path, "SELECT reste FROM stock")[0][0] == 0


def test_pieces_deja_vendues_marquees(env):
    _, client, _ = env
    html = client.get("/prix").get_data(as_text=True)
    assert html.count("déjà vendue") == 1   # l'impression 1 est dans la vente n°2


def test_lancement_et_validations(env):
    _, client, path = env
    r = post(client, "/lancement", nom="", bobine="Rosa3D PETG Vert", poids="0", heures="1")
    assert r.status_code == 400 and "supérieur à 0 g" in r.get_data(as_text=True)
    r = post(client, "/lancement", bobine="Rosa3D PETG Vert", poids="abc", heures="1")
    assert r.status_code == 400 and "nombre valide" in r.get_data(as_text=True)
    r = post(client, "/lancement", nom="", bobine="Rosa3D PETG Vert", poids="10", perte="5", heures="0", minutes="31")
    assert r.status_code == 302 and r.location.endswith("/historique")
    nom, poids, cout, statut, d, f = lire(path, "SELECT nom, poids, cout, statut, date_lancement, fin_prevue "
                                                "FROM impressions ORDER BY id DESC LIMIT 1")[0]
    assert (nom, poids, statut) == ("Sans nom", 15, "EN_COURS") and cout == 0.27
    assert len(d) == 19 and f > d
    assert lire(path, "SELECT reste FROM stock")[0][0] == 138


def test_stock_rechargement_et_modif(env):
    _, client, path = env
    data = dict(marque="Rosa3D", matiere="PETG", couleur="Vert", prix="15", capacite="1000")
    post(client, "/stock/ajouter", **data)
    assert lire(path, "SELECT reste FROM stock")[0][0] == 153   # refusé sans confirmation
    post(client, "/stock/ajouter", remplacer="1", **data)
    assert lire(path, "SELECT prix, reste FROM stock")[0] == (15, 1000)
    post(client, "/stock/modifier", id="Rosa3D PETG Vert", prix="14", reste="420,5")
    assert lire(path, "SELECT prix, reste FROM stock")[0] == (14, 420.5)


def test_historique_actions(env):
    _, client, path = env
    post(client, "/historique/statut", id="3", statut="ECHEC")
    assert lire(path, "SELECT statut FROM impressions WHERE id = 3")[0][0] == "ECHEC"
    post(client, "/historique/supprimer", id="3", rendre="1")
    assert lire(path, "SELECT reste FROM stock")[0][0] == 173
    r = post(client, "/historique/supprimer", id="2", rendre="1")   # bobine supprimée : pas de plantage
    assert r.status_code == 302 and lire(path, "SELECT COUNT(*) FROM impressions")[0][0] == 1
    post(client, "/historique/vider")                                  # sans case cochée : rien
    assert lire(path, "SELECT COUNT(*) FROM impressions")[0][0] == 1
    post(client, "/historique/vider", confirme="1")
    assert lire(path, "SELECT COUNT(*) FROM impressions")[0][0] == 0


def test_import_csv(env):
    _, client, path = env
    csv_txt = ("Date;Nom;Bobine;Poids;Cout;Statut\n29/04/2026 22:18;Vase;Rosa3D PETG Vert;12,5;0,30 €;Échec\n"
               ";Sans poids;X;;1;OK\n").encode("cp1252")
    r = client.post("/historique/import", data={"csrf": "jeton", "csv": (io.BytesIO(csv_txt), "h.csv")},
                    follow_redirects=True)
    assert "1 ligne(s) importée(s), 1 ignorée(s)" in r.get_data(as_text=True)
    assert lire(path, "SELECT date_lancement, poids, cout, statut, duree_minutes, fin_prevue FROM impressions "
                      "WHERE nom = 'Vase'")[0] == ("2026-04-29 22:18:00", 12.5, 0.3, "ECHEC", 0, "2026-04-29 22:18:00")


def test_vente_recalcule_cout_cote_serveur(env):
    _, client, path = env
    r = post(client, "/prix/vendre", nom="", marge="70", ids=["1", "999"], cout="0.01")
    assert r.status_code == 302
    date, nom, nb, cout, prix, benef, pj = lire(path, "SELECT date, nom, nb_pieces, cout_total, prix_vente, "
                                                      "benefice, pieces_json FROM ventes ORDER BY id DESC LIMIT 1")[0]
    assert (nom, nb, cout, prix, benef) == ("Vente sans nom", 1, 2.07, 3.52, 1.45)
    assert len(date) == 16 and date[2] == "/"
    assert json.loads(pj) == [{"id": 1, "nom": "Lève <b>meuble</b>", "cout": 2.07}]
    assert client.get("/ventes").status_code == 200


def test_export_import_db(env, tmp_path):
    app, client, path = env
    r = client.get("/db/export")
    assert r.status_code == 200 and r.data.startswith(b"SQLite format 3\x00")
    export = tmp_path / "export.db"
    export.write_bytes(r.data)
    assert lire(export, "SELECT COUNT(*) FROM impressions")[0][0] == 3

    # Import d'une base sans table ventes : sauvegarde .bak + création de ventes
    autre = tmp_path / "autre.db"
    creer_ancienne_db(autre, avec_ventes=False)
    with sqlite3.connect(autre) as c:
        c.execute("DELETE FROM impressions WHERE id = 1")
    c.close()
    r = client.post("/db/import", data={"csrf": "jeton", "confirme": "1",
                                        "db": (io.BytesIO(autre.read_bytes()), "autre.sqlite")})
    assert r.status_code == 302
    assert lire(path, "SELECT COUNT(*) FROM impressions")[0][0] == 2
    assert lire(path, "SELECT COUNT(*) FROM ventes")[0][0] == 0
    baks = list(tmp_path.glob("workshop.db.bak-*"))
    assert len(baks) == 1 and lire(baks[0], "SELECT COUNT(*) FROM ventes")[0][0] == 1
    for url in ONGLETS:
        assert client.get(url).status_code == 200


def test_import_db_refuse_fichier_invalide(env):
    _, client, path = env
    for contenu in (b"pas une base", None):
        if contenu is None:   # SQLite valide mais sans les bonnes tables
            p = path.parent / "vide.db"
            with sqlite3.connect(p) as c:
                c.execute("CREATE TABLE x (a)")
            c.close()
            contenu = p.read_bytes()
        r = client.post("/db/import", data={"csrf": "jeton", "confirme": "1", "db": (io.BytesIO(contenu), "x.db")},
                        follow_redirects=True)
        assert "Base importée" not in r.get_data(as_text=True)
    assert lire(path, "SELECT COUNT(*) FROM impressions")[0][0] == 3


def test_mot_de_passe(tmp_path, monkeypatch):
    path = tmp_path / "w.db"
    app = create_app({"DB_PATH": str(path), "APP_PASSWORD": "secret"})
    client = app.test_client()
    assert client.get("/stock").status_code == 302
    client.get("/login")
    with client.session_transaction() as sess:
        jeton = sess["csrf"]
    client.post("/login", data={"csrf": jeton, "password": "secret"})
    assert client.get("/stock").status_code == 200


def test_duree_absurde_refusee(env):
    _, client, _ = env
    r = post(client, "/lancement", bobine="Rosa3D PETG Vert", poids="10", heures="1000000")
    assert r.status_code == 400 and "30 jours" in r.get_data(as_text=True)


def test_import_csv_valeurs_invalides_ignorees(env):
    _, client, path = env
    csv_txt = "Date,Nom,Bobine,Poids,Cout,Statut\n,A,X,-5,1,OK\n,B,X,5,nan,OK\n,C,X,inf,1,OK\n,D,X,5,1,OK\n"
    r = client.post("/historique/import", data={"csrf": "jeton", "csv": (io.BytesIO(csv_txt.encode()), "h.csv")},
                    follow_redirects=True)
    assert "1 ligne(s) importée(s), 3 ignorée(s)" in r.get_data(as_text=True)


def test_import_db_colonnes_manquantes_refuse(env):
    _, client, path = env
    p = path.parent / "autre_app.db"
    with sqlite3.connect(p) as c:
        c.executescript("CREATE TABLE stock (id TEXT); CREATE TABLE impressions (id INTEGER);")
    c.close()
    r = client.post("/db/import", data={"csrf": "jeton", "confirme": "1", "db": (io.BytesIO(p.read_bytes()), "x.db")},
                    follow_redirects=True)
    assert "colonnes manquantes" in r.get_data(as_text=True)
    assert lire(path, "SELECT COUNT(*) FROM impressions")[0][0] == 3
