.PHONY: schemas tests style_checks pre_commit_checks schemathesis

schemas:
	poetry run datamodel-codegen --input src/api.spec.yaml --input-file-type openapi --output src/schemas/apispec.py --use-double-quotes --target-python-version 3.11 --collapse-root-models --field-constraints --base-class schemas.base.BaseAPISpec

style_checks:
	poetry check
	poetry run mypy
	poetry run flake8 -v
	poetry run bandit -c pyproject.toml -r .
	poetry run isort --check-only --diff --verbose .
	poetry run pydocstyle -v

tests:
	poetry run pytest

pre_commit_checks:
	poetry run pre-commit run --all-files

schemathesis:
	poetry run st run http://localhost:8000/api/data/spec.json --validate-schema True --checks all --hypothesis-max-examples 20 --data-generation-method all --show-errors-tracebacks --hypothesis-suppress-health-check data_too_large --max-response-time 100 -v
