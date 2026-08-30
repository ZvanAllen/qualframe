from __future__ import annotations

from pathlib import Path

# src/qualframe_eval/ → src/ → repo root
PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent

EVAL_PROMPTS_DIR = PROJECT_ROOT / "prompts" / "evaluation"
EVAL_SCHEMAS_DIR = PROJECT_ROOT / "schemas"
EVAL_CONFIG_DIR = PROJECT_ROOT / "config" / "eval"
