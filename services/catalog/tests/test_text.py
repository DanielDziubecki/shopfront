from catalog.text import normalize


def test_no_normalization_keeps_text() -> None:
    assert normalize("three–season", "none") == "three–season"


def test_ascii_normalization_replaces_typography() -> None:
    assert normalize("It’s a three–season tent", "ascii") == "It's a three-season tent"
