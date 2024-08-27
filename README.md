# Renku Data Services

[![Coverage Status](https://coveralls.io/repos/github/SwissDataScienceCenter/renku-data-services/badge.svg?branch=main)](https://coveralls.io/github/SwissDataScienceCenter/renku-data-services?branch=main)

A set of services that handle reading and writing data from Postgres about
compute resources.


## Initial Setup

1. `poetry install`
2. `pre-commit install` to install pre commit hooks
3. `DUMMY_STORES=true poetry run python bases/renku_data_services/data_api/main.py --debug --dev --fast`

## Developing

See the [Development documentation for more details](/DEVELOPING.md)
