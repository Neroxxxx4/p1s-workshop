"""Calculs et parsing purs (sans Flask), testables isolément."""
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Paris")
FMT = "%Y-%m-%d %H:%M:%S"        # dates des impressions
FMT_VENTE = "%d/%m/%Y %H:%M"      # dates des ventes : format historique, différent !
PUISSANCE_KW = 0.2                # consommation moyenne supposée de la P1S (200 W)
STATUTS = {"EN_COURS": "En cours", "SUCCES": "Réussie", "ECHEC": "Échec"}
MARGES_SCENARIOS = (25, 50, 75, 100, 150, 200, 300)


def now():
    """Heure locale Paris, naïve (c'est ce qui est stocké en DB)."""
    return datetime.now(TZ).replace(tzinfo=None)


def cout_impression(prix_kg, poids_total, duree_h, prix_kwh, usure, puissance_kw=PUISSANCE_KW):
    return round((prix_kg / 1000) * poids_total + duree_h * (usure + puissance_kw * prix_kwh), 2)


def prix_vente(cout, marge_pct):
    """Retourne (prix, benefice), arrondis au centime."""
    prix = round(cout * (1 + marge_pct / 100), 2)
    return prix, round(prix - cout, 2)


def parse_statut(texte):
    t = (texte or "").lower()
    if "cours" in t:
        return "EN_COURS"
    if "chec" in t or "fail" in t:
        return "ECHEC"
    return "SUCCES"


_FORMATS_FR = ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d/%m/%y %H:%M", "%d/%m/%y", "%d-%m-%Y")


def parse_date(texte):
    """Date CSV (ISO ou FR) → format DB des impressions ; repli sur maintenant."""
    t = (texte or "").strip()
    try:
        return datetime.fromisoformat(t).strftime(FMT)
    except ValueError:
        pass
    for f in _FORMATS_FR:
        try:
            return datetime.strptime(t, f).strftime(FMT)
        except ValueError:
            pass
    return now().strftime(FMT)


def parse_float(texte):
    """Accepte « 1,5 », « 1.5 », « 2,30 € ». Lève ValueError sinon."""
    return float(str(texte).replace("€", "").replace(",", ".").replace(" ", "").replace(" ", ""))
