from slugify import slugify


def test_uppercase_umlauts_and_numbers():
    assert slugify("Über 100 Äpfel") == "ueber-100-aepfel"


def test_underscores_collapse():
    assert slugify("a__b") == "a-b"


def test_only_symbols_gives_empty_slug():
    assert slugify("!!!") == ""
