# Renku Data Services

[![Coverage Status](https://coveralls.io/repos/github/SwissDataScienceCenter/renku-data-services/badge.svg?branch=main)](https://coveralls.io/github/SwissDataScienceCenter/renku-data-services?branch=main)

A set of services that handle reading and writing data from Postgres about compute resources.

## Initial Setup

1. `poetry install`
2. `pre-commit install` to install pre commit hooks
3. `DUMMY_STORES=true poetry run python src/renku_crc/main.py --debug --dev --fast`

## Developing

1. Write code
2. Run tests: `make tests`
3. Style checks: `make style_checks`

### Developing with the container image

The container image can be built to be used as a local development service:
`docker build . --build-arg DEV_BUILD=true`
