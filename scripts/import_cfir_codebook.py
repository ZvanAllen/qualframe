from __future__ import annotations

"""Starter script for importing a CFIR codebook workbook into a framework YAML spec.

This is intentionally a stub. The immediate value is to define where the import logic should live.
"""

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a CFIR codebook workbook into YAML.")
    parser.add_argument("codebook_workbook", type=Path)
    parser.add_argument("output_yaml", type=Path)
    args = parser.parse_args()

    raise SystemExit(
        "TODO: implement codebook parsing once the team confirms the canonical codebook workbook format."
    )


if __name__ == "__main__":
    main()
