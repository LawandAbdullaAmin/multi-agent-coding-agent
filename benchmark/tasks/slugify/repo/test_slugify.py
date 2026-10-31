from slugify import slugify


def test_simple():
    assert slugify("Hallo Welt") == "hallo-welt"


def test_umlauts_and_symbols():
    assert slugify("Größe & Gewicht") == "groesse-gewicht"


def test_strips_dashes_at_edges():
    assert slugify("  -Hallo!- ") == "hallo"
