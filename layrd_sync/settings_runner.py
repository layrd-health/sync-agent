"""Standalone entry point for the setup wizard — invoked as a subprocess from the tray."""

import sys
from pathlib import Path

from .database import Database
from .setup_wizard import SetupWizard


def main():
    db = Database()
    wizard = SetupWizard(db)
    completed = wizard.run()
    db.close()
    sys.exit(0 if completed else 1)


if __name__ == "__main__":
    main()
