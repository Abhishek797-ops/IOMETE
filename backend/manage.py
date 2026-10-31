#!/usr/bin/env python
"""Django management entry point for IOMETE COMPASS."""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "compass.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Could not import Django. Is the virtualenv active and are requirements installed?\n"
            "  python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
