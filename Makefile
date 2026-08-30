install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check src tests

format:
	ruff format src tests

validate:
	qualframe validate-config examples/project_template/project.yaml

list-prompts:
	qualframe list-prompts config/prompt_sets/cfir_final_prompts_v1.yaml

run-dry:
	qualframe run examples/project_template/project.yaml --dry-run
