"""Worker process entry point.

The API and worker intentionally share this package, settings, persistence,
services, and rules. Queue claiming will be implemented after the persistence
models and first migration are finalized.
"""

import logging

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    logging.getLogger(__name__).info(
        "Kabtak worker scaffold is configured; queue processing is not implemented yet."
    )


if __name__ == "__main__":
    main()
