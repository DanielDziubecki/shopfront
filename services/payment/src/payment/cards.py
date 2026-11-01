"""Card checks that don't need the card network."""

import datetime as dt


def luhn_valid(number: str) -> bool:
    if not number.isdigit() or not 12 <= len(number) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(number)):
        digit = int(ch)
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def expired(month: int, year: int, today: dt.date) -> bool:
    return (year, month) < (today.year, today.month)
