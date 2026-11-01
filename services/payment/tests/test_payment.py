import datetime as dt

import pytest

from payment.cards import expired, luhn_valid
from payment.tokens import InvalidTokenError, TokenCache, verify


@pytest.mark.parametrize("number", ["4111111111111111", "5555555555554444", "378282246310005"])
def test_valid_card_numbers(number: str) -> None:
    assert luhn_valid(number)


@pytest.mark.parametrize("number", ["4111111111111112", "1234", "41111111abc11111"])
def test_invalid_card_numbers(number: str) -> None:
    assert not luhn_valid(number)


def test_expiry() -> None:
    today = dt.date(2026, 11, 1)
    assert expired(10, 2026, today)
    assert not expired(11, 2026, today)


def test_tokens_are_reused_per_card() -> None:
    cache = TokenCache()
    first = cache.token_for("4111111111111111", now=0)

    assert cache.token_for("4111111111111111", now=10) == first
    assert cache.token_for("4111111111111111", now=10_000) != first
    verify(first, "4111111111111111")


def test_token_for_another_card_is_rejected() -> None:
    token = TokenCache().token_for("4111111111111111", now=0)

    with pytest.raises(InvalidTokenError):
        verify(token, "4012888888881881")
