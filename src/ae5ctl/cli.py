"""Hardware-independent command-line entry point."""

import argparse
from collections.abc import Sequence

from ae5ctl import __version__


def main(argv: Sequence[str] | None = None) -> int:
    """Show the baseline interface without accessing audio hardware."""
    parser = argparse.ArgumentParser(
        prog="ae5ctl",
        description="AE-5 control tools (in development; audio commands coming soon).",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.parse_args(argv)
    parser.print_help()
    return 0
