import csv
import hmac
import io
import json
import math
import os
import secrets
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timedelta

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, send_file, session, url_for)
from markupsafe import Markup

from . import db
from . import services as s

# ponytail: un seul blueprint pour les 6 onglets (~300 lignes), à découper si ça grossit.
bp = Blueprint("main", __name__)

# Colonnes minimales attendues dans une base importée (capacite est ajoutée par migration).
COLONNES_REQUISES = {
    "stock": {"id", "marque", "matiere", "couleur", "prix", "reste"},
    "impressions": {"id", "date_lancement", "nom", "bobine_id", "poids", "cout", "duree_minutes", "statut",
                    "fin_prevue"},
    "ventes": {"id", "date", "nom", "nb_pieces", "cout_total", "marge_pct", "prix_vente", "benefice",
               "pieces_json"},
}
MATIERES = ("PLA", "PETG", "TPU", "ASA", "ABS", "Autre")
ONGLETS = [("main.lancement", "🚀 Lancement"), ("main.stock", "🧵 Stock"),
           ("main.historique", "📜 Historique"), ("main.prix", "🏷️ Prix"),
           ("main.ventes", "💶 Ventes"), ("main.reglages", "💾 DB")]


# --- Garde : mot de passe optionnel + CSRF -------------------------------------------

@bp.before_app_request
def garde():
    if request.endpoint == "static":
        return None
    if current_app.config["APP_PASSWORD"] and not session.get("auth") and request.endpoint != "main.login":
        return redirect(url_for("main.login"))
    if request.method == "POST":
        jeton = session.get("csrf")
        if not jeton or not hmac.compare_digest(request.form.get("csrf", ""), jeton):
            # Session perdue (ex. app iPhone rouverte après longtemps) : on recharge la page proprement.
            flash("Session expirée : la page a été rechargée, refais l'action.", "error")
            retour = request.referrer or ""
            return redirect(retour if retour.startswith(request.host_url) else url_for("main.index"))
    return None


@bp.app_context_processor
def contexte():
    session.permanent = True   # sinon iOS jette le cookie à la fermeture de l'app écran d'accueil
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    metrics = db.get().execute("""SELECT
        (SELECT COALESCE(SUM(reste), 0) FROM stock) AS filament,
        (SELECT COUNT(*) FROM impressions) AS nb,
        (SELECT COALESCE(SUM(cout), 0) FROM impressions) AS cout,
        (SELECT COUNT(*) FROM impressions WHERE statut = 'EN_COURS') AS en_cours""").fetchone()
    return {"csrf_field": Markup(f'<input type="hidden" name="csrf" value="{session["csrf"]}">'),
            "metrics": metrics, "ONGLETS": ONGLETS, "STATUTS": s.STATUTS}


@bp.app_template_filter("eur")
def eur(v):
    return f"{(v or 0):.2f} €"


@bp.app_template_filter("duree")
def duree(minutes):
    minutes = int(minutes or 0)
    return f"{minutes // 60}h{minutes % 60:02d}" if minutes else "—"


@bp.app_template_filter("date_courte")
def date_courte(texte):
    try:
        return datetime.strptime(texte, s.FMT).strftime("%d/%m/%y")
    except (TypeError, ValueError):
        return (texte or "")[:10]


@bp.app_template_filter("fin_courte")
def fin_courte(texte):
    """« 14:30 » si c'est aujourd'hui, sinon « 08/10 14:30 »."""
    try:
        d = datetime.strptime(texte, s.FMT)
    except (TypeError, ValueError):
        return texte or ""
    return d.strftime("%H:%M" if d.date() == s.now().date() else "%d/%m %H:%M")


@bp.app_template_filter("pieces")
def pieces(texte):
    try:
        return [p for p in json.loads(texte) if isinstance(p, dict)]
    except (TypeError, ValueError):
        return []


@bp.app_template_filter("pct")
def pct(b):
    cap = b["capacite"] or 1000
    return max(0, min(100, round(b["reste"] / cap * 100)))


def nombre(form, cle, defaut, libelle, erreurs):
    """Lit un nombre du formulaire ; ajoute une erreur lisible au lieu de planter."""
    brut = (form.get(cle) or "").strip()
    if not brut:
        return defaut
    try:
        v = s.parse_float(brut)
    except ValueError:
        v = math.nan
    if not math.isfinite(v):   # "nan"/"inf" passent float() et videraient une bobine
        erreurs.append(f"« {libelle} » n'est pas un nombre valide.")
        return defaut
    if v < 0:
        erreurs.append(f"« {libelle} » ne peut pas être négatif.")
    return v


def coche(cle="confirme"):
    if request.form.get(cle):
        return True
    flash("Action annulée : coche la case de confirmation.", "error")
    return False


@bp.route("/")
def index():
    return redirect(url_for(".lancement"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        attendu = current_app.config["APP_PASSWORD"].encode()
        if hmac.compare_digest(request.form.get("password", "").encode(), attendu):
            session["auth"] = True
            session.permanent = True
            return redirect(url_for(".lancement"))
        flash("Mot de passe incorrect.", "error")
    return render_template("login.html", public=True)


# --- 1. Lancement ------------------------------------------------------------------

@bp.route("/lancement", methods=["GET", "POST"])
def lancement():
    conn = db.get()
    bobines = conn.execute("SELECT * FROM stock ORDER BY id").fetchall()
    if request.method == "GET":
        return render_template("lancement.html", bobines=bobines, form={}, puissance=s.PUISSANCE_KW)

    f, erreurs = request.form, []
    nom = f.get("nom", "").strip() or "Sans nom"
    bobine = next((b for b in bobines if b["id"] == f.get("bobine")), None)
    poids = nombre(f, "poids", 0, "Poids de l'objet", erreurs)
    perte = nombre(f, "perte", 5, "Perte", erreurs)
    heures = nombre(f, "heures", 0, "Heures", erreurs)
    minutes = nombre(f, "minutes", 0, "Minutes", erreurs)
    kwh = nombre(f, "kwh", 0.25, "Prix du kWh", erreurs)
    usure = nombre(f, "usure", 0.10, "Usure machine", erreurs)
    duree_min = round(heures * 60 + minutes)
    if bobine is None:
        erreurs.append("Choisis une bobine.")
    if not erreurs and poids <= 0:
        erreurs.append("Le poids de l'objet doit être supérieur à 0 g.")
    if not erreurs and duree_min <= 0:
        erreurs.append("La durée doit être supérieure à 0.")
    if not erreurs and duree_min > 30 * 24 * 60:
        erreurs.append("La durée dépasse 30 jours : vérifie les heures et minutes.")
    if erreurs:
        for e in erreurs:
            flash(e, "error")
        return render_template("lancement.html", bobines=bobines, form=f, puissance=s.PUISSANCE_KW), 400

    total = poids + perte
    cout = s.cout_impression(bobine["prix"], total, duree_min / 60, kwh, usure)
    debut = s.now()
    fin = debut + timedelta(minutes=duree_min)
    conn.execute("""INSERT INTO impressions (date_lancement, nom, bobine_id, poids, cout, duree_minutes,
                    statut, fin_prevue) VALUES (?, ?, ?, ?, ?, ?, 'EN_COURS', ?)""",
                 (debut.strftime(s.FMT), nom, bobine["id"], total, cout, duree_min, fin.strftime(s.FMT)))
    conn.execute("UPDATE stock SET reste = MAX(0, reste - ?) WHERE id = ?", (total, bobine["id"]))
    conn.commit()
    flash(f"« {nom} » lancé : {cout:.2f} €, fin prévue à {fin:%H:%M}.", "success")
    if total > bobine["reste"]:
        flash(f"Attention : il ne restait que {bobine['reste']:g} g sur « {bobine['id']} », la bobine est à 0.", "error")
    return redirect(url_for(".historique"))


# --- 2. Stock ----------------------------------------------------------------------

@bp.route("/stock")
def stock():
    bobines = db.get().execute("SELECT * FROM stock ORDER BY id").fetchall()
    return render_template("stock.html", bobines=bobines, matieres=MATIERES)


@bp.post("/stock/ajouter")
def stock_ajouter():
    f, erreurs = request.form, []
    marque, couleur, matiere = f.get("marque", "").strip(), f.get("couleur", "").strip(), f.get("matiere")
    prix = nombre(f, "prix", 20, "Prix", erreurs)
    capacite = nombre(f, "capacite", 1000, "Capacité", erreurs)
    if not marque or not couleur:
        erreurs.append("Marque et couleur sont obligatoires.")
    if matiere not in MATIERES:
        erreurs.append("Matière inconnue.")
    if not erreurs and capacite <= 0:
        erreurs.append("La capacité doit être supérieure à 0 g.")
    for e in erreurs:
        flash(e, "error")
    if erreurs:
        return redirect(url_for(".stock"))

    bid = f"{marque} {matiere} {couleur}"
    conn = db.get()
    existe = conn.execute("SELECT 1 FROM stock WHERE id = ?", (bid,)).fetchone()
    if existe and not f.get("remplacer"):
        flash(f"La bobine « {bid} » existe déjà : confirme pour la recharger.", "error")
        return redirect(url_for(".stock"))
    conn.execute("INSERT OR REPLACE INTO stock (id, marque, matiere, couleur, prix, reste, capacite) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?)", (bid, marque, matiere, couleur, prix, capacite, capacite))
    conn.commit()
    flash(f"Bobine « {bid} » {'rechargée' if existe else 'ajoutée'}.", "success")
    return redirect(url_for(".stock"))


@bp.post("/stock/modifier")
def stock_modifier():
    erreurs = []
    prix = nombre(request.form, "prix", None, "Prix", erreurs)
    reste = nombre(request.form, "reste", None, "Reste", erreurs)
    if prix is None or reste is None:
        erreurs.append("Prix et reste sont obligatoires.")
    for e in erreurs:
        flash(e, "error")
    if not erreurs:
        conn = db.get()
        if conn.execute("UPDATE stock SET prix = ?, reste = ? WHERE id = ?",
                        (prix, reste, request.form.get("id"))).rowcount:
            conn.commit()
            flash("Bobine mise à jour.", "success")
        else:
            flash("Bobine introuvable (déjà supprimée ?).", "error")
    return redirect(url_for(".stock"))


@bp.post("/stock/supprimer")
def stock_supprimer():
    conn = db.get()
    if conn.execute("DELETE FROM stock WHERE id = ?", (request.form.get("id"),)).rowcount:
        conn.commit()
        flash("Bobine supprimée.", "success")
    else:
        flash("Bobine introuvable (déjà supprimée ?).", "error")
    return redirect(url_for(".stock"))


# --- 3. Historique -----------------------------------------------------------------

@bp.route("/historique")
def historique():
    conn = db.get()
    impressions = conn.execute("""SELECT i.*, s.id IS NOT NULL AS bobine_ok FROM impressions i
        LEFT JOIN stock s ON s.id = i.bobine_id ORDER BY i.date_lancement DESC, i.id DESC""").fetchall()
    maintenant = s.now().strftime(s.FMT)
    alertes = [i for i in impressions if i["statut"] == "EN_COURS" and i["fin_prevue"] <= maintenant]
    ok = sum(i["statut"] == "SUCCES" for i in impressions)
    ko = sum(i["statut"] == "ECHEC" for i in impressions)
    taux = round(ok / (ok + ko) * 100) if ok + ko else None
    return render_template("historique.html", impressions=impressions, alertes=alertes,
                           ok=ok, ko=ko, taux=taux)


@bp.post("/historique/statut")
def historique_statut():
    statut = request.form.get("statut")
    if statut not in s.STATUTS:
        abort(400)
    conn = db.get()
    if conn.execute("UPDATE impressions SET statut = ? WHERE id = ?", (statut, request.form.get("id"))).rowcount:
        conn.commit()
        flash(f"Statut passé à « {s.STATUTS[statut]} ».", "success")
    else:
        flash("Impression introuvable (déjà supprimée ?).", "error")
    return redirect(url_for(".historique"))


@bp.post("/historique/supprimer")
def historique_supprimer():
    conn = db.get()
    imp = conn.execute("SELECT * FROM impressions WHERE id = ?", (request.form.get("id"),)).fetchone()
    if imp is None:
        flash("Impression introuvable.", "error")
        return redirect(url_for(".historique"))
    conn.execute("DELETE FROM impressions WHERE id = ?", (imp["id"],))
    msg = f"« {imp['nom']} » supprimée."
    if request.form.get("rendre"):
        cur = conn.execute("UPDATE stock SET reste = MIN(COALESCE(capacite, 1000), reste + ?) WHERE id = ?",
                           (imp["poids"], imp["bobine_id"]))
        msg += (f" {imp['poids']:g} g rendus à « {imp['bobine_id']} »." if cur.rowcount
                else " La bobine n'existe plus : filament non rendu.")
    conn.commit()
    flash(msg, "success")
    return redirect(url_for(".historique"))


@bp.post("/historique/import")
def historique_import():
    fichier = request.files.get("csv")
    if not fichier or not fichier.filename:
        flash("Choisis un fichier CSV.", "error")
        return redirect(url_for(".historique"))
    brut = fichier.read()
    # utf-8-sig lit aussi l'UTF-8 sans BOM ; cp1252 avant latin-1 (qui accepte tout) pour garder le « € ».
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texte = brut.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialecte = csv.Sniffer().sniff(texte[:4096], delimiters=",;\t")
    except csv.Error:
        dialecte = csv.excel
    lignes = csv.DictReader(io.StringIO(texte), dialect=dialecte)
    lignes.fieldnames = [(c or "").strip().lower() for c in (lignes.fieldnames or [])]
    manquantes = {"date", "nom", "bobine", "poids", "cout", "statut"} - set(lignes.fieldnames)
    if manquantes:
        flash(f"Colonnes manquantes : {', '.join(sorted(manquantes))}.", "error")
        return redirect(url_for(".historique"))

    conn, ok, ignorees = db.get(), 0, 0
    for ligne in lignes:
        nom = (ligne.get("nom") or "").strip()
        try:
            poids, cout = s.parse_float(ligne.get("poids")), round(s.parse_float(ligne.get("cout")), 2)
        except ValueError:
            poids = cout = math.nan
        if not nom or not (0 <= poids < math.inf and 0 <= cout < math.inf):   # nan échoue aussi
            ignorees += 1
            continue
        date = s.parse_date(ligne.get("date"))
        conn.execute("""INSERT INTO impressions (date_lancement, nom, bobine_id, poids, cout, duree_minutes,
                        statut, fin_prevue) VALUES (?, ?, ?, ?, ?, 0, ?, ?)""",
                     (date, nom, (ligne.get("bobine") or "").strip(), poids, cout,
                      s.parse_statut(ligne.get("statut")), date))
        ok += 1
    conn.commit()
    flash(f"Import CSV : {ok} ligne(s) importée(s), {ignorees} ignorée(s).", "success" if ok else "error")
    return redirect(url_for(".historique"))


@bp.post("/historique/vider")
def historique_vider():
    if coche():
        conn = db.get()
        n = conn.execute("DELETE FROM impressions").rowcount
        conn.commit()
        flash(f"Historique vidé ({n} impressions).", "success")
    return redirect(url_for(".historique"))


# --- 4. Prix de vente --------------------------------------------------------------

@bp.route("/prix")
def prix():
    conn = db.get()
    pieces_ok = conn.execute("SELECT id, nom, cout, date_lancement FROM impressions "
                             "WHERE statut = 'SUCCES' ORDER BY date_lancement DESC, id DESC").fetchall()
    vendues = {p.get("id") for (pj,) in conn.execute("SELECT pieces_json FROM ventes") for p in pieces(pj)}
    return render_template("prix.html", pieces=pieces_ok, vendues=vendues, scenarios=s.MARGES_SCENARIOS)


@bp.post("/prix/vendre")
def prix_vendre():
    erreurs = []
    marge = nombre(request.form, "marge", 100, "Marge", erreurs)
    try:
        ids = [int(i) for i in request.form.getlist("ids")]
    except ValueError:
        ids = []
    if not ids:
        erreurs.append("Le panier est vide.")
    if erreurs:
        for e in erreurs:
            flash(e, "error")
        return redirect(url_for(".prix"))

    conn = db.get()
    # Le coût vient de la DB, jamais du navigateur.
    lignes = conn.execute(f"SELECT id, nom, cout FROM impressions WHERE id IN ({','.join('?' * len(ids))})",
                          ids).fetchall()
    par_id = {r["id"]: r for r in lignes}
    pieces_db = [{"id": r["id"], "nom": r["nom"], "cout": r["cout"]} for i in ids if (r := par_id.get(i))]
    if not pieces_db:
        flash("Aucune des pièces du panier n'existe encore.", "error")
        return redirect(url_for(".prix"))
    cout = round(sum(p["cout"] for p in pieces_db), 2)
    prix_v, benef = s.prix_vente(cout, marge)
    nom = request.form.get("nom", "").strip() or "Vente sans nom"
    conn.execute("""INSERT INTO ventes (date, nom, nb_pieces, cout_total, marge_pct, prix_vente, benefice,
                    pieces_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                 (s.now().strftime(s.FMT_VENTE), nom, len(pieces_db), cout, marge, prix_v, benef,
                  json.dumps(pieces_db)))
    conn.commit()
    flash(f"Vente « {nom} » enregistrée : {prix_v:.2f} € (bénéfice {benef:.2f} €).", "success")
    return redirect(url_for(".ventes"))


# --- 5. Ventes ---------------------------------------------------------------------

@bp.route("/ventes")
def ventes():
    conn = db.get()
    liste = conn.execute("SELECT * FROM ventes ORDER BY id DESC").fetchall()
    totaux = conn.execute("SELECT COUNT(*) AS nb, COALESCE(SUM(prix_vente), 0) AS revenus, "
                          "COALESCE(SUM(benefice), 0) AS benefices FROM ventes").fetchone()
    return render_template("ventes.html", ventes=liste, totaux=totaux)


@bp.post("/ventes/supprimer")
def ventes_supprimer():
    conn = db.get()
    if conn.execute("DELETE FROM ventes WHERE id = ?", (request.form.get("id"),)).rowcount:
        conn.commit()
        flash("Vente supprimée.", "success")
    else:
        flash("Vente introuvable (déjà supprimée ?).", "error")
    return redirect(url_for(".ventes"))


@bp.post("/ventes/vider")
def ventes_vider():
    if coche():
        conn = db.get()
        n = conn.execute("DELETE FROM ventes").rowcount
        conn.commit()
        flash(f"{n} vente(s) effacée(s).", "success")
    return redirect(url_for(".ventes"))


# --- 6. DB -------------------------------------------------------------------------

@bp.route("/db")
def reglages():
    return render_template("db.html", db_path=os.path.abspath(current_app.config["DB_PATH"]))


@bp.route("/db/export")
def db_export():
    with closing(sqlite3.connect(":memory:")) as mem:
        db.get().backup(mem)  # copie cohérente même pendant une écriture
        data = mem.serialize()
    return send_file(io.BytesIO(data), mimetype="application/vnd.sqlite3", as_attachment=True,
                     download_name=f"workshop-{s.now():%Y%m%d-%H%M%S}.db")


@bp.post("/db/import")
def db_import():
    fichier = request.files.get("db")
    if not fichier or not fichier.filename.lower().endswith((".db", ".sqlite", ".sqlite3")):
        flash("Choisis un fichier .db, .sqlite ou .sqlite3.", "error")
        return redirect(url_for(".reglages"))
    if not coche():
        return redirect(url_for(".reglages"))

    fd, chemin = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        fichier.save(chemin)
        with closing(sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)) as src:
            if src.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("base corrompue")
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            manquantes = {"stock", "impressions"} - tables
            if manquantes:
                flash(f"Base refusée : table(s) manquante(s) {', '.join(sorted(manquantes))}.", "error")
                return redirect(url_for(".reglages"))
            for table, requises in COLONNES_REQUISES.items():
                if table in tables:
                    cols = {r[1] for r in src.execute(f"PRAGMA table_info({table})")}
                    if requises - cols:
                        flash(f"Base refusée : colonnes manquantes dans « {table} » : "
                              f"{', '.join(sorted(requises - cols))}.", "error")
                        return redirect(url_for(".reglages"))
            live = db.get()
            sauvegarde = f"{current_app.config['DB_PATH']}.bak-{s.now():%Y%m%d-%H%M%S}"
            with closing(sqlite3.connect(sauvegarde)) as bak:
                live.backup(bak)
            src.backup(live)  # remplace le contenu de la base en place
            db.init(live)     # crée ventes si absente + migrations
    except sqlite3.DatabaseError:
        flash("Ce fichier n'est pas une base SQLite valide.", "error")
        return redirect(url_for(".reglages"))
    finally:
        os.unlink(chemin)
    flash(f"Base importée. Ancienne base sauvegardée sous {os.path.basename(sauvegarde)}.", "success")
    return redirect(url_for(".reglages"))
