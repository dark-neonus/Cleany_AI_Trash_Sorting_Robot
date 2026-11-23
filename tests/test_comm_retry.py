"""Retry of arm bus calls (scripts/common/comm_retry.py)."""

import pytest
from comm_retry import STATS, retry


def flaky(failures):
    calls = []

    def fn(x):
        calls.append(x)
        if len(calls) <= failures:
            raise ConnectionError("There is no status packet!")
        return x * 2
    fn.calls = calls
    return fn


def test_a_call_that_fails_once_or_twice_goes_through():
    before = STATS.count
    fn = flaky(2)
    assert retry(fn, 21, sleep=lambda s: None) == 42 and len(fn.calls) == 3
    assert STATS.count == before + 1 and "no status packet" in STATS.last
    assert retry(flaky(0), 1, sleep=lambda s: None) == 2 and STATS.count == before + 1  # no retry needed: not counted


def test_a_call_that_keeps_failing_raises_after_the_last_try():
    fn = flaky(99)
    with pytest.raises(ConnectionError):
        retry(fn, 1, tries=3, sleep=lambda s: None)
    assert len(fn.calls) == 3


def test_other_errors_are_not_retried():
    def broken():
        raise RuntimeError("Overload error!")
    with pytest.raises(RuntimeError):
        retry(broken)
