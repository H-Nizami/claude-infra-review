#!/usr/bin/env python3
"""Validate the structured contract without ever logging model-produced data."""
import argparse
import json
from pathlib import Path, PurePosixPath
import sys

from jsonschema.validators import validator_for

SCHEMA = Path(__file__).resolve().parents[1] / "schema/findings.schema.json"


def validate(data, schema_path=None):
    schema = json.loads(Path(schema_path or SCHEMA).read_text())
    validator = validator_for(schema)
    validator.check_schema(schema)
    if not validator(schema).is_valid(data):
        raise ValueError("findings do not match the schema")
    for item in data["findings"] + data["dropped_scanner_findings"]:
        path = item["file"]
        if (not path or PurePosixPath(path).is_absolute() or ".." in path.split("/")
                or "\\" in path or any(ord(c) < 32 for c in path)):
            raise ValueError("finding path must be repository-relative")
        if "line_start" in item and item["line_end"] < item["line_start"]:
            raise ValueError("finding line range is reversed")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        if args.file.stat().st_size > 200_000:
            raise ValueError("output too large")
        validate(json.loads(args.file.read_text()))
    except (ValueError, OSError):
        print("Invalid findings: structured contract validation failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
