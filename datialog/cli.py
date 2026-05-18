"""
Datialog CLI entry point
Author: Ivan Pastor Sanz · CC BY-NC 4.0
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="datialog",
        description="Datialog — Natural AI Data Explorer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  datialog                    Launch with system tray and browser
  datialog --port 9090        Use custom port
  datialog --no-tray          Terminal mode (no system tray)
  datialog --no-browser       Don't open browser automatically
  datialog --version          Show version

Web: https://datialog.app
DOI: 10.5281/zenodo.20075103
        """
    )
    
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8080,
        help="Port number (default: 8080)"
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Disable system tray icon (terminal mode)"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open browser automatically"
    )
    parser.add_argument(
        "--version", "-v",
        action="store_true",
        help="Show version and exit"
    )
    parser.add_argument(
        "--skip-license",
        action="store_true",
        help="Skip license check (development mode)"
    )
    
    args = parser.parse_args()
    
    if args.version:
        from datialog import __version__
        print(f"Datialog {__version__}")
        print("https://datialog.app")
        print("DOI: 10.5281/zenodo.20075103")
        sys.exit(0)
    
    if args.skip_license:
        import os
        os.environ["DATIALOG_SKIP_LICENSE"] = "1"
    
    # Print banner
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║   Datialog — Natural AI Data Explorer    ║")
    print("  ║   datialog.app · CC BY-NC 4.0            ║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    
    from datialog.launcher import launch
    launch(
        port=args.port,
        no_tray=args.no_tray,
        no_browser=args.no_browser
    )


if __name__ == "__main__":
    main()
