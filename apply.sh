#!/bin/bash
# Wrapper that sets macOS library path for WeasyPrint then runs the apply pipeline.
# Usage: ./apply.sh [--dry-run] [--sources greenhouse] [--limit 10]
export DYLD_LIBRARY_PATH=/opt/homebrew/lib:${DYLD_LIBRARY_PATH}
exec python scripts/run_apply.py "$@"
