"""lerobot's "Relative goal position magnitude had to be clamped to be safe" warning, counted.

The follower limits every command to --max-step degrees from where the arm really is (a safety).
When a program commands faster than the arm can follow, lerobot prints that warning with a table
for every single command: hundreds of lines. install() drops them from the log and counts them, so
a program can say once at the end how often its commands were limited.
"""

import logging


class ClampFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.count = 0

    def filter(self, record: logging.LogRecord) -> bool:
        if "had to be clamped" in record.getMessage():
            self.count += 1
            return False
        return True


def install() -> ClampFilter:
    """Filter on the root logger (lerobot logs with logging.warning)."""
    clamp = ClampFilter()
    logging.getLogger().addFilter(clamp)
    return clamp
