"""
Datialog — Natural AI Data Explorer
Analyze datasets in plain language, locally and privately.

Usage:
    datialog              # Launch from terminal (system tray + browser)
    datialog --port 8080  # Custom port
    datialog --no-tray    # Without system tray

Or from Python:
    import datialog
    datialog.launch()

Author: Ivan Pastor Sanz · https://datialog.app
License: CC BY-NC 4.0
DOI: 10.5281/zenodo.20075103
"""

__version__ = "1.3.0"
__author__ = "Ivan Pastor Sanz"
__email__ = "licencias@datialog.app"
__url__ = "https://datialog.app"

from datialog.launcher import launch

__all__ = ["launch"]
