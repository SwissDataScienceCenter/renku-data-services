.PHONY: schemas tests style_checks pre_commit_checks

schemas:
	poetry run datamodel-codegen --input src/api.spec.yaml --input-file-type openapi --output src/schemas/apispec.py --use-double-quotes --target-python-version 3.11

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
