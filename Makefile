.PHONY: schemas tests test_setup main_tests schemathesis_tests collect_coverage style_checks pre_commit_checks run download_avro check_avro avro_models update_avro kind_cluster install_amaltheas all

AMALTHEA_JS_VERSION ?= 0.11.0
AMALTHEA_SESSIONS_VERSION ?= 0.0.1-new-operator-chart
codegen_params = --input-file-type openapi --output-model-type pydantic_v2.BaseModel --use-double-quotes --target-python-version 3.12 --collapse-root-models --field-constraints --strict-nullable --openapi-scopes schemas paths parameters --set-default-enum-member --use-one-literal-as-default --use-default

define test_apispec_up_to_date
	$(eval $@_NAME=$(1))
	cp "components/renku_data_services/${$@_NAME}/apispec.py" "/tmp/apispec_orig.py"
	poetry run datamodel-codegen --input components/renku_data_services/${$@_NAME}/api.spec.yaml --output components/renku_data_services/${$@_NAME}/apispec.py --base-class renku_data_services.${$@_NAME}.apispec_base.BaseAPISpec $(codegen_params)
	diff -I "^#   timestamp\: " "/tmp/apispec_orig.py" "components/renku_data_services/${$@_NAME}/apispec.py"
	@RESULT=$?
	cp "/tmp/apispec_orig.py" "components/renku_data_services/${$@_NAME}/apispec.py"
	exit ${RESULT}
endef

all: help

components/renku_data_services/crc/apispec.py: components/renku_data_services/crc/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/crc/api.spec.yaml --output components/renku_data_services/crc/apispec.py --base-class renku_data_services.crc.apispec_base.BaseAPISpec $(codegen_params)
components/renku_data_services/storage/apispec.py: components/renku_data_services/storage/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/storage/api.spec.yaml --output components/renku_data_services/storage/apispec.py --base-class renku_data_services.storage.apispec_base.BaseAPISpec $(codegen_params)
components/renku_data_services/users/apispec.py: components/renku_data_services/users/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/users/api.spec.yaml --output components/renku_data_services/users/apispec.py --base-class renku_data_services.users.apispec_base.BaseAPISpec $(codegen_params)
components/renku_data_services/project/apispec.py: components/renku_data_services/project/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/project/api.spec.yaml --output components/renku_data_services/project/apispec.py --base-class renku_data_services.project.apispec_base.BaseAPISpec $(codegen_params)
components/renku_data_services/session/apispec.py: components/renku_data_services/session/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/session/api.spec.yaml --output components/renku_data_services/session/apispec.py --base-class renku_data_services.session.apispec_base.BaseAPISpec $(codegen_params)
components/renku_data_services/namespace/apispec.py: components/renku_data_services/namespace/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/namespace/api.spec.yaml --output components/renku_data_services/namespace/apispec.py --base-class renku_data_services.namespace.apispec_base.BaseAPISpec $(codegen_params)
components/renku_data_services/secrets/apispec.py: components/renku_data_services/secrets/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/secrets/api.spec.yaml --output components/renku_data_services/secrets/apispec.py --base-class renku_data_services.secrets.apispec_base.BaseAPISpec $(codegen_params)
components/renku_data_services/connected_services/apispec.py: components/renku_data_services/connected_services/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/connected_services/api.spec.yaml --output components/renku_data_services/connected_services/apispec.py --base-class renku_data_services.connected_services.apispec_base.BaseAPISpec $(codegen_params)
components/renku_data_services/repositories/apispec.py: components/renku_data_services/repositories/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/repositories/api.spec.yaml --output components/renku_data_services/repositories/apispec.py --base-class renku_data_services.repositories.apispec_base.BaseAPISpec $(codegen_params)
components/renku_data_services/notebooks/apispec.py: components/renku_data_services/notebooks/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/notebooks/api.spec.yaml --output components/renku_data_services/notebooks/apispec.py --base-class renku_data_services.notebooks.apispec_base.BaseAPISpec $(codegen_params)
components/renku_data_services/platform/apispec.py: components/renku_data_services/platform/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/platform/api.spec.yaml --output components/renku_data_services/platform/apispec.py --base-class renku_data_services.platform.apispec_base.BaseAPISpec $(codegen_params)
components/renku_data_services/message_queue/apispec.py: components/renku_data_services/message_queue/api.spec.yaml
	poetry run datamodel-codegen --input components/renku_data_services/message_queue/api.spec.yaml --output components/renku_data_services/message_queue/apispec.py --base-class renku_data_services.message_queue.apispec_base.BaseAPISpec $(codegen_params)

##@ Apispec

schemas: components/renku_data_services/crc/apispec.py \
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
components/renku_data_services/message_queue/apispec.py  ## Generate pydantic classes from apispec yaml files
	@echo "generated classes based on ApiSpec"

##@ Avro schemas

download_avro:  ## Download the latest avro schema files
	@echo "Downloading avro schema files"
	curl -L -o schemas.tar.gz https://github.com/SwissDataScienceCenter/renku-schema/tarball/main
	tar xf schemas.tar.gz --directory=components/renku_data_services/message_queue/schemas/ --strip-components=1
	rm schemas.tar.gz

check_avro: download_avro avro_models  ## Download avro schemas, generate models and check if the avro schemas are up to date
	@echo "checking if avro schemas are up to date"
	git diff --exit-code || (git diff && exit 1)

avro_models:  ## Generate message queue classes and code from the avro schemas
	@echo "generating message queues classes from avro schemas"
	poetry run python components/renku_data_services/message_queue/generate_models.py

update_avro: download_avro avro_models  ## Download avro schemas and generate models

##@ Test and linting

style_checks:  ## Run linting and style checks
	poetry check
	@echo "checking crc apispec is up to date"
	@$(call test_apispec_up_to_date,"crc")
	@echo "checking storage apispec is up to date"
	@$(call test_apispec_up_to_date,"storage")
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
	@echo "checking notebooks apispec is up to date"
	@$(call test_apispec_up_to_date,"notebooks")
	@echo "checking platform apispec is up to date"
	@$(call test_apispec_up_to_date,"platform")
	@echo "checking message_queue apispec is up to date"
	@$(call test_apispec_up_to_date,"message_queue")
	@echo "checking session apispec is up to date"
	@$(call test_apispec_up_to_date,"session")
	poetry run mypy
	poetry run ruff format --check
	poetry run ruff check .
	poetry run bandit -c pyproject.toml -r .
	poetry poly check
	poetry poly libs
test_setup:  ## Prep for the tests - removes old coverage reports if one is present
	@rm -f coverage.lcov .coverage
main_tests:  ## Run the main (i.e. non-schemathesis tests)
	DUMMY_STORES=true poetry run alembic --name common upgrade heads
	poetry run alembic --name common check
	poetry run pytest -m "not schemathesis" -n auto
schemathesis_tests:  ## Run schemathesis checks
	poetry run pytest -m "schemathesis" --cov-append
collect_coverage:  ## Collect test coverage reports
	poetry run coverage report --show-missing
	poetry run coverage lcov -o coverage.lcov
tests: test_setup main_tests schemathesis_tests collect_coverage  ## Run all tests

pre_commit_checks:  ## Run pre-commit checks
	poetry run pre-commit run --all-files

##@ General

run:  ## Run the sanic server
	DUMMY_STORES=true poetry run python bases/renku_data_services/data_api/main.py --dev --debug

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

kind_cluster:  ## Creates a kind cluster for testing
	kind delete cluster
	docker network rm -f kind
	docker network create -d=bridge -o com.docker.network.bridge.enable_ip_masquerade=true -o com.docker.network.driver.mtu=1500 --ipv6=false kind
	kind create cluster --config kind_config.yaml
	kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
	echo "Waiting for ingress controller to initialize"
	sleep 15
	kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=90s

install_amaltheas:  ## Installs both version of amalthea in the currently active k8s context.
	helm repo add renku https://swissdatasciencecenter.github.io/helm-charts
	helm install amalthea-js renku/amalthea --version $(AMALTHEA_JS_VERSION)
	helm install amalthea-sessions renku/amalthea-sessions --version $(AMALTHEA_SESSIONS_VERSION)
