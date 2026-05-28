#!/usr/bin/env python3
"""CLI entrypoint: run the apply phase only."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config
from src.pipeline import Pipeline
from src.utils.logging_config import setup_logging


async def main():
    parser = argparse.ArgumentParser(description="Apply to matched jobs")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Tailor resumes and fill forms but don't submit",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of jobs to process (overrides config)",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        default=None,
        metavar="SOURCE",
        help="Only process jobs from these sources (e.g. greenhouse lever)",
    )
    args = parser.parse_args()

    setup_logging()

    config = load_config()
    if args.dry_run:
        config.pipeline.dry_run = True
    if args.limit is not None:
        config.pipeline.max_applications_per_run = args.limit

    pipeline = Pipeline(config)
    results = await pipeline.run_apply(sources=args.sources)
    print(f"\nApply complete: {results}")


if __name__ == "__main__":
    asyncio.run(main())
