import pytest

from durations import parse_duration


def test_seconds():
    assert parse_duration("90s") == 90


def test_minutes():
    assert parse_duration("15m") == 900


def test_invalid():
    with pytest.raises(ValueError):
        parse_duration("abc")
