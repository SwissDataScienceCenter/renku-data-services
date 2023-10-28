# Renku Data Services

[![Coverage Status](https://coveralls.io/repos/github/SwissDataScienceCenter/renku-data-services/badge.svg?branch=main)](https://coveralls.io/github/SwissDataScienceCenter/renku-data-services?branch=main)

A set of services that handle reading and writing data from Postgres about
compute resources.

## Polylith
This project follows the [Polylith Architecture]() using the [Polylith Poetry
Plugin](https://davidvujic.github.io/python-polylith-docs/installation/).



[Installation
instructions](https://davidvujic.github.io/python-polylith-docs/installation/)
for the plugin.

Use `poetry poly info` to get an overview of the contained
components/bases/projects. Refer to the documentation of the plugin for further
details.

## Initial Setup

1. `poetry install`
2. `pre-commit install` to install pre commit hooks
3. `DUMMY_STORES=true poetry run python bases/renku_data_services/data_api/main.py --debug --dev --fast`

## Developing

1. Write code
2. Run tests: `make tests`
3. Style checks: `make style_checks`

### Developing with the container image

The container image can be built to be used as a local development service (for renku_crc):
`docker build -f projects/renku_crc/Dockerfile . --build-arg DEV_BUILD=true -t renku-data-service`

It can then be run as daemon: `docker run -d -e DUMMY_STORES=true --name renku-crc renku-data-service`

## Migrations
to create migrations locally, run alembic like
`DUMMY_STORES=true alembic -c components/renku_data_services/migrations/alembic.ini --name=<app> revision --message="<message>" --head=head --autogenerate`
where `app` is the name of the app from the `alembic.ini` file (e.g. `storage` or `resource_pools`)

To run migrations locally, run
`DUMMY_STORES=true alembic -c components/renku_data_services/migrations/alembic.ini --name=<app> upgrade head`
