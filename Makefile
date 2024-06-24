.PHONY: schemas tests test_setup main_tests schemathesis_tests collect_coverage style_checks pre_commit_checks run download_avro check_avro avro_models update_avro

define test_apispec_up_to_date
	$(eval $@_NAME=$(1))
	cp "components/renku_data_services/${$@_NAME}/apispec.py" "/tmp/apispec_orig.py"
	poetry run datamodel-codegen --input components/renku_data_services/${$@_NAME}/api.spec.yaml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/${$@_NAME}/apispec.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.${$@_NAME}.apispec_base.BaseAPISpec
	diff -I "^#   timestamp\: " "/tmp/apispec_orig.py" "components/renku_data_services/${$@_NAME}/apispec.py"
	@RESULT=$?
	cp "/tmp/apispec_orig.py" "components/renku_data_services/${$@_NAME}/apispec.py"
	exit ${RESULT}
endef

components/renku_data_services/crc/apispec.py: components/renku_data_services/crc/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/crc/api.spec.yaml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/crc/apispec.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.crc.apispec_base.BaseAPISpec
components/renku_data_services/storage/apispec.py: components/renku_data_services/storage/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/storage/api.spec.yaml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/storage/apispec.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.storage.apispec_base.BaseAPISpec
components/renku_data_services/users/apispec.py: components/renku_data_services/users/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/users/api.spec.yaml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/users/apispec.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.users.apispec_base.BaseAPISpec
components/renku_data_services/project/apispec.py: components/renku_data_services/project/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/project/api.spec.yaml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/project/apispec.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.project.apispec_base.BaseAPISpec
components/renku_data_services/session/apispec.py: components/renku_data_services/session/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/session/api.spec.yaml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/session/apispec.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.session.apispec_base.BaseAPISpec
components/renku_data_services/user_preferences/apispec.py: components/renku_data_services/user_preferences/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/user_preferences/api.spec.yaml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/user_preferences/apispec.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.user_preferences.apispec_base.BaseAPISpec
components/renku_data_services/namespace/apispec.py: components/renku_data_services/namespace/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/namespace/api.spec.yaml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/namespace/apispec.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.namespace.apispec_base.BaseAPISpec
components/renku_data_services/secrets/apispec.py: components/renku_data_services/secrets/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/secrets/api.spec.yaml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/secrets/apispec.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.secrets.apispec_base.BaseAPISpec
components/renku_data_services/connected_services/apispec.py: components/renku_data_services/connected_services/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/connected_services/api.spec.yaml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/connected_services/apispec.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.connected_services.apispec_base.BaseAPISpec
components/renku_data_services/repositories/apispec.py: components/renku_data_services/repositories/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/repositories/api.spec.yaml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/repositories/apispec.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.repositories.apispec_base.BaseAPISpec
components/renku_data_services/platform/apispec.py: components/renku_data_services/platform/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/platform/api.spec.yaml --input-file-type openapi --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/platform/apispec.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.platform.apispec_base.BaseAPISpec

schemas: components/renku_data_services/crc/apispec.py components/renku_data_services/storage/apispec.py components/renku_data_services/users/apispec.py components/renku_data_services/project/apispec.py components/renku_data_services/user_preferences/apispec.py components/renku_data_services/namespace/apispec.py components/renku_data_services/secrets/apispec.py components/renku_data_services/connected_services/apispec.py components/renku_data_services/repositories/apispec.py components/renku_data_services/platform/apispec.py
	@echo "generated classes based on ApiSpec"

download_avro:
	@echo "Downloading avro schema files"
	curl -L -o schemas.tar.gz https://github.com/SwissDataScienceCenter/renku-schema/tarball/main
	tar xf schemas.tar.gz --directory=components/renku_data_services/message_queue/schemas/ --strip-components=1
	rm schemas.tar.gz

check_avro: download_avro avro_models
	@echo "checking if avro schemas are up to date"
	git diff --exit-code || (git diff && exit 1)

avro_models:
	@echo "generating message queues classes from avro schemas"
	poetry run python components/renku_data_services/message_queue/generate_models.py

update_avro: download_avro avro_models

style_checks:
	poetry check
	@echo "checking crc apispec is up to date"
	@$(call test_apispec_up_to_date,"crc")
	@echo "checking storage apispec is up to date"
	@$(call test_apispec_up_to_date,"storage")
	@echo "checking user preferences apispec is up to date"
	@$(call test_apispec_up_to_date,"user_preferences")
	@echo "checking users apispec is up to date"
	@$(call test_apispec_up_to_date,"users")
	@echo "checking project apispec is up to date"
	@$(call test_apispec_up_to_date,"project")
	@echo "checking namespace apispec is up to date"
	@$(call test_apispec_up_to_date,"namespace")
	@echo "checking connected_services apispec is up to date"
	@$(call test_apispec_up_to_date,"connected_services")
	@echo "checking repositories apispec is up to date"
	@$(call test_apispec_up_to_date,"repositories")
	@echo "checking platform apispec is up to date"
	@$(call test_apispec_up_to_date,"platform")
	poetry run mypy
	poetry run ruff format --check
	poetry run ruff check .
	poetry run bandit -c pyproject.toml -r .
	poetry poly check
	poetry poly libs
test_setup:
	@rm -f coverage.lcov .coverage
main_tests:
	DUMMY_STORES=true poetry run alembic --name common upgrade heads
	poetry run alembic --name common check
	poetry run pytest -m "not schemathesis" -n auto
schemathesis_tests:
	poetry run pytest -m "schemathesis" --cov-append
collect_coverage:
	poetry run coverage report --show-missing
	poetry run coverage lcov -o coverage.lcov
tests: test_setup main_tests schemathesis_tests collect_coverage

pre_commit_checks:
	poetry run pre-commit run --all-files

run:
	DUMMY_STORES=true poetry run python bases/renku_data_services/data_api/main.py --dev --debug

debug:
	DUMMY_STORES=true poetry run python -Xfrozen_modules=off -m debugpy --listen 0.0.0.0:5678 --wait-for-client -m sanic renku_data_services.data_api.main:create_app --debug --single-process --port 8000 --host 0.0.0.0
