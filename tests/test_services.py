import pytest

from app import services as s


def test_cout_identique_ancienne_version():
    # Impression réelle n°14 : PETG 13 €/kg, 10 g, 31 min, kWh 0.25, usure 0.10 → 0.21 €
    assert s.cout_impression(13, 10, 31 / 60, 0.25, 0.10) == 0.21
    # n°12 : 111 g, 238 min → 2.04 €
    assert s.cout_impression(13, 111, 238 / 60, 0.25, 0.10) == 2.04
    assert s.cout_impression(20, 100, 1, 0.25, 0.10, puissance_kw=0) == 2.10


def test_prix_vente():
    assert s.prix_vente(2.98, 70) == (5.07, 2.09)   # vente réelle n°4
    assert s.prix_vente(7.06, 100) == (14.12, 7.06)
    assert s.prix_vente(0, 300) == (0, 0)


@pytest.mark.parametrize("texte, attendu", [
    ("En cours", "EN_COURS"), ("EN_COURS", "EN_COURS"), ("Échec", "ECHEC"), ("ECHEC", "ECHEC"),
    ("failed", "ECHEC"), ("Succès", "SUCCES"), ("", "SUCCES"), (None, "SUCCES"),
])
def test_parse_statut(texte, attendu):
    assert s.parse_statut(texte) == attendu


@pytest.mark.parametrize("texte, attendu", [
    ("2026-04-29 22:18:00", "2026-04-29 22:18:00"),
    ("2026-04-29T22:18", "2026-04-29 22:18:00"),
    ("2026-04-29", "2026-04-29 00:00:00"),
    ("29/04/2026 22:18", "2026-04-29 22:18:00"),
    ("29/04/2026", "2026-04-29 00:00:00"),
    ("29/04/26", "2026-04-29 00:00:00"),
])
def test_parse_date(texte, attendu):
    assert s.parse_date(texte) == attendu


def test_parse_date_repli_maintenant():
    assert s.parse_date("n'importe quoi")[:10] == s.now().strftime("%Y-%m-%d")


def test_parse_float():
    assert s.parse_float("1,5") == 1.5
    assert s.parse_float(" 2,30 € ") == 2.3
    with pytest.raises(ValueError):
        s.parse_float("abc")
