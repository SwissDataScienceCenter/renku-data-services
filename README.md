# Renku Data Services

A set of services that handle reading and writing data from Postgres about compute resources.

## Initial Setup

1. `poetry install`
2. `pre-commit install` to install pre commit hooks
4. `make migrations` to execute any outstanding database migrations
3. `poetry run python src/renku_crac/main.py --debug --dev --fast`

## Developing

1. Write code
2. Run tests: `make tests`
3. Style checks: `make style_checks`
4. Run schemathesis by first running the server and then executing `make schemathesis`
