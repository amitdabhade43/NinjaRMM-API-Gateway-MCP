from email.utils import formatdate

from ninja_mcp.client import MAX_RETRY_DELAY_S, _retry_delay


def test_retry_after_seconds_is_honored():
    assert _retry_delay({"Retry-After": "7"}, attempt=0, now=1_700_000_000) == 7


def test_retry_after_http_date_is_honored():
    now = 1_700_000_000
    header = formatdate(now + 9, usegmt=True)
    assert _retry_delay({"Retry-After": header}, attempt=0, now=now) == 9


def test_ratelimit_reset_relative_delay_is_honored():
    assert _retry_delay({"RateLimit-Reset": "12"}, attempt=1, now=1_700_000_000) == 12


def test_x_ratelimit_reset_epoch_is_honored():
    now = 1_700_000_000
    assert _retry_delay({"X-RateLimit-Reset": str(now + 11)}, attempt=0, now=now) == 11


def test_retry_delay_is_bounded():
    assert _retry_delay({"Retry-After": "999"}, attempt=0, now=1_700_000_000) == MAX_RETRY_DELAY_S


def test_invalid_retry_header_uses_exponential_fallback():
    assert _retry_delay({"Retry-After": "not-a-date"}, attempt=2, now=1_700_000_000) == 4
