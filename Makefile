.PHONY: schemas tests style_checks yesqa

schemas:
	poetry run datamodel-codegen --input src/api.spec.yaml --input-file-type openapi --output src/schemas/apispec.py --use-double-quotes --target-python-version 3.11

style_checks:
	poetry run mypy
	poetry run flake8 -v
	poetry run bandit -c pyproject.toml -r .
	poetry run isort --check-only --diff --verbose .
	poetry run pydocstyle -v

tests:
	poetry run pytest

yesqa:
	poetry run yesqa $(wildcard *.py */*.py */*/*.py */*/*/*.py */*/*/*/*.py */*/*/*/*/*.py */*/*/*/*/*/*.py */*/*/*/*/*/*/*.py */*/*/*/*/*/*/*/*.py)
