"""DEPRECATED: Superseded by realtime_archive_acceptance.py --mode live-uart/live-cdc.

The dual-output capture assumed simultaneous UART+CDC streaming which no longer
exists after the mutual-exclusion refactor (AT+LIVESTREAM selects one target).
Use realtime_archive_acceptance.py --mode live-uart or --mode live-cdc instead.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "ERROR: dual_output_acceptance.py is DEPRECATED.\n"
        "The firmware now uses mutually-exclusive live streaming (AT+LIVESTREAM).\n"
        "Use: python host/tools/realtime_archive_acceptance.py "
        "--mode live-uart|live-cdc ...",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
