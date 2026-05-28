#!/usr/bin/env python3
"""CLI entrypoint: run the scan phase only."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline import Pipeline
from src.utils.logging_config import setup_logging


async def main():
    setup_logging()
    pipeline = Pipeline()
    new_jobs = await pipeline.run_scan()
    print(f"\nScan complete: {len(new_jobs)} new matching jobs found.")
    for job in new_jobs:
        print(f"  [{job.relevance_score:.2f}] {job.company} - {job.title} ({job.source.value})")


if __name__ == "__main__":
    asyncio.run(main())
