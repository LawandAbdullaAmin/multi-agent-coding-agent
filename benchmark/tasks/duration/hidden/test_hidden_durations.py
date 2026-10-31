import pytest

from durations import parse_duration


@pytest.mark.parametrize("text, expected", [
    ("2h", 7200), ("1h30m", 5400), ("1h30m15s", 5415), ("45m10s", 2710), ("1h5s", 3605), ("30s", 30),
])
def test_combined(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["", "1x", "h", "10"])
def test_invalid(text):
    with pytest.raises(ValueError):
        parse_duration(text)
