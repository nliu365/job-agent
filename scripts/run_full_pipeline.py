#!/usr/bin/env python3
"""CLI entrypoint: run the full pipeline (scan + apply)."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config
from src.pipeline import Pipeline
from src.utils.logging_config import setup_logging


async def main():
    parser = argparse.ArgumentParser(description="Run full job alert pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Tailor resumes and fill forms but don't submit",
    )
    args = parser.parse_args()

    setup_logging()

    config = load_config()
    if args.dry_run:
        config.pipeline.dry_run = True

    pipeline = Pipeline(config)
    results = await pipeline.run_full()
    print(f"\nPipeline complete: {results}")


if __name__ == "__main__":
    asyncio.run(main())
