"""CLI entry: python -m whisper_app"""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="whisper", description="Offline speech-to-text overlay")
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="Path to config.toml (default: next to ./whisper)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Download model into models/ and exit",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from pathlib import Path

    from .config import load_config
    from .paths import app_root

    cfg_path = Path(args.config) if args.config else None
    cfg = load_config(cfg_path)
    logging.getLogger(__name__).info("App root: %s", app_root())
    if cfg.config_path:
        logging.getLogger(__name__).info("Config: %s", cfg.config_path)

    if args.download_only:
        from .asr import ensure_model

        path = ensure_model(cfg.model)
        print(f"Model ready at {path}")
        return 0

    # Qt application
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    # High-DPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)
    qt_app.setApplicationName("Whisper")
    qt_app.setOrganizationName("whisper")

    from .app import WhisperApp

    app = WhisperApp(qt_app, cfg)
    app.start()
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
