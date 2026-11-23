"""Retry of arm bus calls that fail once (docs/pick-dataset.md).

A servo bus reply can go missing now and then ("There is no status packet!"): a glitch on the USB
serial line, or a reply that came late while the computer was busy with the cameras and the panel.
lerobot tries once and raises ConnectionError, which ended a whole recording session at a harmless
spot (2026-11-23: the first Lock write of the leader at the start). Every call the recorder makes
to an arm goes through retry(): up to TRIES attempts, a few milliseconds apart; a call that keeps
failing is a real fault and raises. COUNT tells how many calls needed a retry, reported at the
end of a session.
"""

from __future__ import annotations

import time

TRIES = 4
PAUSE_S = 0.02


class Retries:
    def __init__(self):
        self.count = 0  # calls that failed at least once and then worked
        self.last = ""  # the last error text


STATS = Retries()


def retry(fn, *args, tries: int = TRIES, pause: float = PAUSE_S, sleep=time.sleep, **kwargs):
    """fn(*args, **kwargs); on ConnectionError again, up to `tries` attempts in all."""
    for attempt in range(1, tries + 1):
        try:
            result = fn(*args, **kwargs)
        except ConnectionError as error:
            STATS.last = str(error).strip()
            if attempt == tries:
                raise
            sleep(pause)
        else:
            if attempt > 1:
                STATS.count += 1
            return result
