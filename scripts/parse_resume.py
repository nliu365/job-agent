#!/usr/bin/env python3
"""One-time script: parse a Word/PDF resume into structured JSON."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tailoring.resume_parser import parse_resume


def main():
    parser = argparse.ArgumentParser(description="Parse a resume into structured JSON")
    parser.add_argument("resume_file", help="Path to resume file (.pdf, .docx, or .txt)")
    parser.add_argument(
        "--output", "-o",
        default="data/resume.json",
        help="Output path for JSON (default: data/resume.json)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CLAUDE_API_KEY", ""),
        help="Claude API key (or set CLAUDE_API_KEY env var)",
    )
    args = parser.parse_args()

    if not args.api_key:
        print("Error: CLAUDE_API_KEY is required. Set it as env var or use --api-key.")
        sys.exit(1)

    if not Path(args.resume_file).exists():
        print(f"Error: File not found: {args.resume_file}")
        sys.exit(1)

    print(f"Parsing resume: {args.resume_file}")
    resume = parse_resume(args.resume_file, args.api_key)

    # Ensure output directory exists
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    with open(args.output, "w") as f:
        json.dump(resume.model_dump(), f, indent=2)

    print(f"Resume parsed and saved to: {args.output}")
    print(f"  Name: {resume.name}")
    print(f"  Email: {resume.email}")
    print(f"  Experience entries: {len(resume.experience)}")
    print(f"  Skills: {len(resume.skills)}")


if __name__ == "__main__":
    main()
