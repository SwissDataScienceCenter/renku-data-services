export DATA_SERVICE_ROOT=$(cd "$(dirname ${0})"; pwd)

export KUBECONFIG="${DATA_SERVICE_ROOT}/.k3d-config.yaml"

export NB_SERVER_OPTIONS__DEFAULTS_PATH="${DATA_SERVICE_ROOT}/server_defaults.json"
export NB_SERVER_OPTIONS__UI_CHOICES_PATH="${DATA_SERVICE_ROOT}/server_options.json"
export CORS_ALLOW_ALL_ORIGINS=true

export ALEMBIC_CONFIG="${DATA_SERVICE_ROOT}/components/renku_data_services/migrations/alembic.ini"

export AUTHZ_DB_GRPC_PORT=50051
export AUTHZ_DB_HOST=127.0.0.1
export AUTHZ_DB_KEY=renku
export AUTHZ_DB_NO_TLS_CONNECTION=true

export DB_HOST=127.0.0.1
export DB_NAME=renku
export DB_PASSWORD=renku
export DB_USER=renku

export ZED_TOKEN=renku
export ZED_ENDPOINT=127.0.0.1:50051
export ZED_INSECURE=true

export SOLR_URL="http://127.0.0.1:8983"
export SOLR_CORE="renku-search-dev"
