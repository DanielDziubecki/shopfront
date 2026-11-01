"""Text normalization for clients that only render plain ASCII."""

# Typographic characters our copywriters use, mapped to ASCII equivalents.
_TYPOGRAPHY = {
    "–": "-",  # en dash
    "—": "-",  # em dash
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "°": " deg",
    " ": " ",
}


def to_ascii(text: str) -> str:
    return "".join(_TYPOGRAPHY[c] if ord(c) > 127 else c for c in text)


def normalize(text: str, mode: str) -> str:
    if mode == "ascii":
        return to_ascii(text)
    return text
