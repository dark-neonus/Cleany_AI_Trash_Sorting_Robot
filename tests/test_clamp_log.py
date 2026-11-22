"""The clamp warning filter (scripts/common/clamp_log.py)."""

import logging

import clamp_log


def test_clamp_warnings_are_dropped_and_counted_and_others_pass(caplog):
    root = logging.getLogger()
    clamp = clamp_log.install()
    try:
        with caplog.at_level(logging.WARNING):
            logging.warning("Relative goal position magnitude had to be clamped to be safe.\n{'elbow': 1}")
            logging.warning("Relative goal position magnitude had to be clamped to be safe.")
            logging.warning("something else")
        assert clamp.count == 2
    finally:
        root.removeFilter(clamp)
