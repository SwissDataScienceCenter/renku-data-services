AMALTHEA_JS_VERSION ?= 0.20.0
AMALTHEA_SESSIONS_VERSION ?= build/support-remote-sessions-hpc
COMMON_CODEGEN_PARAMS := \
	--output-model-type pydantic_v2.BaseModel \
	--use-double-quotes \
	--target-python-version 3.13 \
	--field-constraints \
	--strict-nullable
API_CODEGEN_PARAMS := \
	--input-file-type openapi \
	${COMMON_CODEGEN_PARAMS} \
	--collapse-root-models \
	--set-default-enum-member \
	--openapi-scopes schemas paths parameters \
	--use-one-literal-as-default \
	--use-default
CR_CODEGEN_PARAMS := \
	--input-file-type jsonschema \
	${COMMON_CODEGEN_PARAMS} \
	--collapse-root-models \
	--allow-extra-fields \
	--use-default-kwarg \
	--use-generic-container-types

# A separate set of params without the --collaps-root-models option as
# this causes a bug in the code generator related to list of unions.
# https://github.com/koxudaxi/datamodel-code-generator/issues/1937
SEARCH_CODEGEN_PARAMS := \
	--input-file-type openapi \
	${COMMON_CODEGEN_PARAMS} \
	--set-default-enum-member \
	--openapi-scopes schemas paths parameters \
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
components/renku_data_services/data_connectors/apispec.py: components/renku_data_services/data_connectors/api.spec.yaml
components/renku_data_services/search/apispec.py: components/renku_data_services/search/api.spec.yaml

schemas: ${API_SPECS}  ## Generate pydantic classes from apispec yaml files
	@echo "generated classes based on ApiSpec"

##@ Test and linting

.PHONY: style_checks
style_checks: ${API_SPECS} ## Run linting and style checks
	poetry check
	poetry run mypy
	poetry run ruff format --check
	poetry run ruff check
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

##@ Helm/k8s

.PHONY: k3d_cluster
k3d_cluster:  ## Creates a k3d cluster for testing
	./setup-k3d-cluster.sh --reset --deploy-shipwright

.PHONY: install_amaltheas
install_amaltheas:  ## Installs both version of amalthea in the. NOTE: It uses the currently active k8s context.
	helm repo add renku https://swissdatasciencecenter.github.io/helm-charts
	helm repo update
	helm upgrade --install amalthea-js renku/amalthea --version $(AMALTHEA_JS_VERSION)
	helm upgrade --install amalthea-se renku/amalthea-sessions --version ${AMALTHEA_SESSIONS_VERSION}

# TODO: Add the version variables from the top of the file here when the charts are fully published
.PHONY: amalthea_schema
amalthea_schema:  ## Updates generates pydantic classes from CRDs
	curl https://raw.githubusercontent.com/SwissDataScienceCenter/amalthea/${AMALTHEA_SESSIONS_VERSION}/config/crd/bases/amalthea.dev_hpcamaltheasessions.yaml | yq '.spec.versions[0].schema.openAPIV3Schema' | poetry run datamodel-codegen --output components/renku_data_services/notebooks/cr_amalthea_session.py --base-class renku_data_services.notebooks.cr_base.BaseCRD ${CR_CODEGEN_PARAMS}
	curl https://raw.githubusercontent.com/SwissDataScienceCenter/amalthea/${AMALTHEA_JS_VERSION}/controller/crds/jupyter_server.yaml | yq '.spec.versions[0].schema.openAPIV3Schema' | poetry run datamodel-codegen --output components/renku_data_services/notebooks/cr_jupyter_server.py --base-class renku_data_services.notebooks.cr_base.BaseCRD ${CR_CODEGEN_PARAMS}

.PHONY: shipwright_schema
shipwright_schema:  ## Updates the Shipwright pydantic classes
	curl https://raw.githubusercontent.com/shipwright-io/build/refs/tags/v0.15.2/deploy/crds/shipwright.io_buildruns.yaml | yq '.spec.versions[] | select(.name == "v1beta1") | .schema.openAPIV3Schema' | poetry run datamodel-codegen --output components/renku_data_services/session/cr_shipwright_buildrun.py --base-class renku_data_services.session.cr_base.BaseCRD ${CR_CODEGEN_PARAMS}

##@ Devcontainer

.PHONY: devcontainer_up
devcontainer_up:  ## Start dev containers
	devcontainer up --workspace-folder .

.PHONY: devcontainer_rebuild
devcontainer_rebuild:  ## Rebuild dev containers images
	devcontainer up --remove-existing-container --workspace-folder .

.PHONY: devcontainer_exec
devcontainer_exec: devcontainer_up ## Start a shell in the development container
	devcontainer exec --container-id renku-data-services_devcontainer-data_service-1 -- bash

##@ General

.PHONY: run
run:  ## Run the sanic server
	DUMMY_STORES=true poetry run python bases/renku_data_services/data_api/main.py --dev --debug

.PHONY: debug
debug:  ## Debug the sanic server
	DUMMY_STORES=true poetry run python -Xfrozen_modules=off -m debugpy --listen 0.0.0.0:5678 --wait-for-client -m sanic renku_data_services.data_api.main:create_app --debug --single-process --port 8000 --host 0.0.0.0

.PHONY: run-tasks
run-tasks:  ## Run the data tasks
	DUMMY_STORES=true poetry run python bases/renku_data_services/data_tasks/main.py

.PHONY: lock
lock:  ## Update the lock files for all projects from their repsective poetry.toml
	poetry lock $(ARGS)
	poetry -C projects/renku_data_service lock $(ARGS)
	poetry -C projects/secrets_storage lock $(ARGS)
	poetry -C projects/k8s_watcher lock $(ARGS)
	poetry -C projects/renku_data_tasks lock $(ARGS)

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

# Pattern rules

API_SPEC_CODEGEN_PARAMS := ${API_CODEGEN_PARAMS}
%/apispec.py: %/api.spec.yaml
	$(if $(findstring /search/, $(<)), $(eval API_SPEC_CODEGEN_PARAMS=${SEARCH_CODEGEN_PARAMS}))
	poetry run datamodel-codegen --input $< --output $@ --base-class $(subst /,.,$(subst .py,_base.BaseAPISpec,$(subst components/,,$@))) ${API_SPEC_CODEGEN_PARAMS}
# If the only difference is the timestamp comment line, ignore it by
# reverting to the checked in version. As the file timestamps is now
# newer than the requirements these steps won't be re-triggered.
# Ignore the return value when there are more differences.
	( git diff --exit-code -I "^#   timestamp\: " $@ >/dev/null && git checkout $@ ) || true
