AMALTHEA_JS_VERSION ?= 0.13.0
AMALTHEA_SESSIONS_VERSION ?= 0.13.0
CODEGEN_PARAMS := \
    --input-file-type openapi \
    --output-model-type pydantic_v2.BaseModel \
    --use-double-quotes \
    --target-python-version 3.12 \
    --collapse-root-models \
    --field-constraints \
    --strict-nullable \
    --set-default-enum-member \
    --openapi-scopes schemas paths parameters \
    --set-default-enum-member \
    --use-one-literal-as-default \
    --use-default

.PHONY: all
all: help

##@ Apispec

# If you add a new api spec, add the `apispec.py` file here and as a
# target/dependency below
API_SPECS := \
    components/renku_data_services/crc/apispec.py \
    components/renku_data_services/storage/apispec.py \
    components/renku_data_services/users/apispec.py \
    components/renku_data_services/project/apispec.py \
    components/renku_data_services/session/apispec.py \
    components/renku_data_services/namespace/apispec.py \
    components/renku_data_services/secrets/apispec.py \
    components/renku_data_services/connected_services/apispec.py \
    components/renku_data_services/repositories/apispec.py \
    components/renku_data_services/notebooks/apispec.py \
    components/renku_data_services/platform/apispec.py \
    components/renku_data_services/message_queue/apispec.py \
    components/renku_data_services/data_connectors/apispec.py \
    components/renku_data_services/search/apispec.py

components/renku_data_services/crc/apispec.py: components/renku_data_services/crc/api.spec.yaml
components/renku_data_services/storage/apispec.py: components/renku_data_services/storage/api.spec.yaml
components/renku_data_services/users/apispec.py: components/renku_data_services/users/api.spec.yaml
components/renku_data_services/project/apispec.py: components/renku_data_services/project/api.spec.yaml
components/renku_data_services/session/apispec.py: components/renku_data_services/session/api.spec.yaml
components/renku_data_services/namespace/apispec.py: components/renku_data_services/namespace/api.spec.yaml
components/renku_data_services/secrets/apispec.py: components/renku_data_services/secrets/api.spec.yaml
components/renku_data_services/connected_services/apispec.py: components/renku_data_services/connected_services/api.spec.yaml
components/renku_data_services/repositories/apispec.py: components/renku_data_services/repositories/api.spec.yaml
components/renku_data_services/notebooks/apispec.py: components/renku_data_services/notebooks/api.spec.yaml
components/renku_data_services/platform/apispec.py: components/renku_data_services/platform/api.spec.yaml
components/renku_data_services/message_queue/apispec.py: components/renku_data_services/message_queue/api.spec.yaml
components/renku_data_services/data_connectors/apispec.py: components/renku_data_services/data_connectors/api.spec.yaml
components/renku_data_services/search/apispec.py: components/renku_data_services/search/api.spec.yaml

schemas: ${API_SPECS}  ## Generate pydantic classes from apispec yaml files
	@echo "generated classes based on ApiSpec"

##@ Avro schemas

.PHONY: download_avro
download_avro:  ## Download the latest avro schema files
	@echo "Downloading avro schema files"
	curl -L -o schemas.tar.gz https://github.com/SwissDataScienceCenter/renku-schema/tarball/main
	tar xf schemas.tar.gz --directory=components/renku_data_services/message_queue/schemas/ --strip-components=1
	rm schemas.tar.gz

.PHONY: check_avro
check_avro: download_avro avro_models  ## Download avro schemas, generate models and check if the avro schemas are up to date
	@echo "checking if avro schemas are up to date"
	git diff --exit-code || (git diff && exit 1)

.PHONY: avro_models
avro_models:  ## Generate message queue classes and code from the avro schemas
	@echo "generating message queues classes from avro schemas"
	poetry run python components/renku_data_services/message_queue/generate_models.py

.PHONY: update_avro
update_avro: download_avro avro_models  ## Download avro schemas and generate models

##@ Test and linting

.PHONY: style_checks
style_checks: ${API_SPECS} ## Run linting and style checks
	poetry check
	poetry run mypy
	poetry run ruff format --check
	poetry run ruff check .
	poetry run bandit -c pyproject.toml -r .
	poetry poly check
	poetry poly libs

.PHONY: test_setup
test_setup:  ## Prep for the tests - removes old coverage reports if one is present
	@rm -f coverage.lcov .coverage

.PHONY: main_tests
main_tests:  ## Run the main (i.e. non-schemathesis tests)
	DUMMY_STORES=true poetry run alembic --name common upgrade heads
	poetry run alembic --name common check
	poetry run pytest -m "not schemathesis" -n auto -v

.PHONY: schemathesis_tests
schemathesis_tests:  ## Run schemathesis checks
	poetry run pytest -m "schemathesis" --cov-append

.PHONY: collect_coverage
collect_coverage:  ## Collect test coverage reports
	poetry run coverage report --show-missing
	poetry run coverage lcov -o coverage.lcov

.PHONY: tests
tests: test_setup main_tests schemathesis_tests collect_coverage  ## Run all tests

.PHONY: pre_commit_checks
pre_commit_checks:  ## Run pre-commit checks
	poetry run pre-commit run --all-files

##@ General

.PHONY: run
run:  ## Run the sanic server
	DUMMY_STORES=true poetry run python bases/renku_data_services/data_api/main.py --dev --debug

.PHONY: debug
debug:  ## Debug the sanic server
	DUMMY_STORES=true poetry run python -Xfrozen_modules=off -m debugpy --listen 0.0.0.0:5678 --wait-for-client -m sanic renku_data_services.data_api.main:create_app --debug --single-process --port 8000 --host 0.0.0.0

# From the operator sdk Makefile
# The help target prints out all targets with their descriptions organized
# beneath their categories. The categories are represented by '##@' and the
# target descriptions by '##'. The awk command is responsible for reading the
# entire set of makefiles included in this invocation, looking for lines of the
# file as xyz: ## something, and then pretty-format the target and help. Then,
# if there's a line with ##@ something, that gets pretty-printed as a category.
# More info on the usage of ANSI control characters for terminal formatting:
# https://en.wikipedia.org/wiki/ANSI_escape_code#SGR_parameters
# More info on the awk command:
# http://linuxcommand.org/lc3_adv_awk.php
.PHONY: help
help:  ## Display this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Helm/k8s

.PHONY: k3d_cluster
k3d_cluster:  ## Creates a k3d cluster for testing
	k3d cluster delete
	# k3d registry delete myregistry.localhost || true
	# k3d registry create myregistry.localhost
	k3d cluster create --registry-create k3d-myregistry.localhost:5000 --agents 1 --k3s-arg --disable=metrics-server@server:0 

.PHONY: install_amaltheas
install_amaltheas:  ## Installs both version of amalthea in the. NOTE: It uses the currently active k8s context.
	helm repo add renku https://swissdatasciencecenter.github.io/helm-charts
	helm repo update
	helm upgrade --install amalthea-js renku/amalthea --version $(AMALTHEA_JS_VERSION)
	helm upgrade --install amalthea-se renku/amalthea-sessions --version ${AMALTHEA_SESSIONS_VERSION}
install_kpack:
	curl -L https://github.com/buildpacks-community/kpack/releases/download/v0.15.0/release-0.15.0.yaml | kubectl apply -f -
	kubectl apply -f .devcontainer/kpack/clusterstore.yaml
	kubectl apply -f .devcontainer/kpack/clusterstack.yaml
	sleep 10
	kubectl apply -f .devcontainer/kpack/python-builder.yaml

# TODO: Add the version variables from the top of the file here when the charts are fully published
.PHONY: amalthea_schema
amalthea_schema:  ## Updates generates pydantic classes from CRDs
	curl https://raw.githubusercontent.com/SwissDataScienceCenter/amalthea/main/config/crd/bases/amalthea.dev_amaltheasessions.yaml | yq '.spec.versions[0].schema.openAPIV3Schema' | poetry run datamodel-codegen --input-file-type jsonschema --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/notebooks/cr_amalthea_session.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.notebooks.cr_base.BaseCRD --allow-extra-fields --use-default-kwarg
	curl https://raw.githubusercontent.com/SwissDataScienceCenter/amalthea/main/controller/crds/jupyter_server.yaml | yq '.spec.versions[0].schema.openAPIV3Schema' | poetry run datamodel-codegen --input-file-type jsonschema --output-model-type pydantic_v2.BaseModel --output components/renku_data_services/notebooks/cr_jupyter_server.py --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --base-class renku_data_services.notebooks.cr_base.BaseCRD --allow-extra-fields --use-default-kwarg

# Pattern rules

%/apispec.py: %/api.spec.yaml
	poetry run datamodel-codegen --input $< --output $@ --base-class $(subst /,.,$(subst .py,_base.BaseAPISpec,$(subst components/,,$@))) ${CODEGEN_PARAMS}
# If the only difference is the timestamp comment line, ignore it by
# reverting to the checked in version. As the file timestamps is now
# newer than the requirements these steps won't be re-triggered.
# Ignore the return value when there are more differences.
	( git diff --exit-code -I "^#   timestamp\: " $@ >/dev/null && git checkout $@ ) || true
