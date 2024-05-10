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
`docker build -f projects/renku_data_services/Dockerfile . --build-arg DEV_BUILD=true -t renku-data-service`

It can then be run as daemon: `docker run -d -e DUMMY_STORES=true --name renku-crc renku-data-service`

## Migrations

We use Alembic for migrations and we have a single version table for all schemas. This version table
is used by Alembic to determine what migrations have been applied or not and it resides in the `common`
schema. That is why all the Alembic commands include the `--name common` argument.

Our Alembic setup is such that we have multiple schemas. Most use cases will probably simply use
the `common` schema. However, if you add a new schema, you have to make sure to add the
metadata for it in the `components/renku_data_services/migrations/env.py` file.

**To create a new migration:**

`DUMMY_STORES=true alembic -c components/renku_data_services/migrations/alembic.ini --name common revision -m "<message>" --autogenerate --version-path components/renku_data_services/migrations/versions`

You can specify a different version path if you wish to, just make sure it is listed in `alembic.ini` under
`version_locations`.

**To run all migrations:**
`DUMMY_STORES=true alembic -c components/renku_data_services/migrations/alembic.ini --name=common upgrade heads`
