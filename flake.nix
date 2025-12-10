{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    devshell-tools.url = "github:eikek/devshell-tools";
    devshell-tools.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = inputs @ {
    self,
    nixpkgs,
    flake-utils,
    devshell-tools,
  }:
    {
      nixosConfigurations = let
        system = flake-utils.lib.system.x86_64-linux;
        services = {
          services.dev-postgres = {
            enable = true;
            databases = ["renku_test"];
            init-script = ./.devcontainer/generate_ulid_func.sql;
            pkg = nixpkgs.legacyPackages.${system}.postgresql_16;
            pgweb = {
              enable = true;
              database = "renku";
            };
          };
          services.dev-spicedb = {
            enable = true;
          };
          services.openapi-docs = {
            enable = true;
            openapi-spec = "http://localhost:8000/api/data/spec.json";
          };
          services.dev-solr = {
            enable = true;
            cores = ["renku-search-dev"];
            heap = 1024;
          };
        };
      in {
        rdsdev-vm = devshell-tools.lib.mkVm {
          inherit system;
          modules = [
            {
              virtualisation.memorySize = 2048;
              networking.hostName = "rdsdev";
              port-forward.openapi-docs = 8099;
            }
            services
          ];
        };
        rsdevcnt = devshell-tools.lib.mkContainer {
          system = flake-utils.lib.system.x86_64-linux;
          modules = [
            services
          ];
        };
      };
    }
    // flake-utils.lib.eachDefaultSystem (system: let
      pkgs = nixpkgs.legacyPackages.${system};
      devshellToolsPkgs = devshell-tools.packages.${system};

      rclone-sdsc = pkgs.rclone.overrideAttrs (old: {
        version = "1.71.2";
        vendorHash = "sha256-0RK2gc3InPZZnAEgv01fgG19cWeKCsBP6JN2OCVY8O4=";
        nativeInstallCheckInputs = [];
        src = pkgs.fetchFromGitHub {
          owner = "SwissDataScienceCenter";
          repo = "rclone";
          rev = "v1.71.2+renku-1";
          sha256 = "sha256-NhPYEGPgpwe56zExrV3SiYsbKLb3/OuX+UOuezgJQ8w=";
        };
      });

      ruff = pkgs.ruff.overrideAttrs (old: rec {
        pname = "ruff";
        version = "0.8.6";
        src = pkgs.fetchFromGitHub {
          owner = "astral-sh";
          repo = "ruff";
          tag = "0.8.6";
          hash = "sha256-9YvHmNiKdf5hKqy9tToFSQZM2DNLoIiChcfjQay8wbU=";
        };
        cargoDeps = pkgs.rustPlatform.fetchCargoVendor {
          inherit src;
          name = "${pname}-${version}";
          hash = "sha256-aTzTCDCMhG4cKD9wFNHv6A3VBUifnKgI8a6kelc3bAM=";
        };
      });

      poetrySettings = {
        LD_LIBRARY_PATH = "${pkgs.stdenv.cc.cc.lib}/lib";
        POETRY_VIRTUALENVS_PREFER_ACTIVE_PYTHON = "true";
        POETRY_VIRTUALENVS_OPTIONS_SYSTEM_SITE_PACKAGES = "true";
        POETRY_INSTALLER_NO_BINARY = "ruff";
      };
      devSettings =
        poetrySettings
        // {
          CORS_ALLOW_ALL_ORIGINS = "true";
          DB_USER = "dev";
          DB_NAME = "renku";
          DB_PASSWORD = "dev";
          PGPASSWORD = "dev";
          PGUSER = "dev";
          PGDATABASE = "renku";
          PSQLRC = pkgs.writeText "rsdrc.sql" ''
            SET SEARCH_PATH TO authz,common,connected_services,events,platform,projects,public,resource_pools,secrets,sessions,storage,users
          '';
          AUTHZ_DB_KEY = "dev";
          AUTHZ_DB_NO_TLS_CONNECTION = "true";
          AUTHZ_DB_GRPC_PORT = "50051";

          DUMMY_STORES = "true";

          ZED_ENDPOINT = "localhost:50051";
          ZED_TOKEN = "dev";

          SOLR_BIN_PATH = "${devshellToolsPkgs.solr}/bin/solr";
          TEST_RUN_SOLR_LOCALLY = "true";

          shellHook = ''
            PYENV_PATH=$(poetry env info --path)
            export FLAKE_ROOT="$(git rev-parse --show-toplevel)"
            export PATH="$PYENV_PATH/bin:$PATH"
            export ALEMBIC_CONFIG="$FLAKE_ROOT/components/renku_data_services/migrations/alembic.ini"
            export NB_SERVER_OPTIONS__DEFAULTS_PATH="$FLAKE_ROOT/server_defaults.json"
            export NB_SERVER_OPTIONS__UI_CHOICES_PATH="$FLAKE_ROOT/server_options.json"
            export ENCRYPTION_KEY_PATH="$FLAKE_ROOT/.encryption_key"

            if [ ! -e "$FLAKE_ROOT/.encryption_key" ]; then
              head -c30 /dev/random > "$FLAKE_ROOT/.encryption_key"
            fi
          '';
        };

      commonPackages = with pkgs; [
        redis
        postgresql_16
        jq
        devshellToolsPkgs.openapi-docs
        devshellToolsPkgs.solr
        devshellToolsPkgs.postgres-fg
        spicedb
        cargo
        rustc
        spicedb-zed
        ruff
        poetry
        python313
        basedpyright
        rclone-sdsc
        azure-cli
        kind
        redocly
        yq-go
        (writeShellScriptBin "pyfix" ''
          poetry run ruff check --fix
          poetry run ruff format
        '')
        (
          writeShellScriptBin "poetry-setup" ''
            venv_path="$(poetry env info -p)"
            if [ "$1" == "-c" ]; then
               echo "Removing virtual env at $venv_path"
               rm -rf "$venv_path"/*
            fi
            poetry install
            if ! poetry self show --addons | grep poetry-multiproject-plugin > /dev/null; then
                poetry self add poetry-multiproject-plugin
            fi
            if ! poetry self show --addons | grep poetry-polylith-plugin > /dev/null; then
                poetry self add poetry-polylith-plugin
            fi
          ''
        )
        (
          writeShellScriptBin "zedl" ''
            ${spicedb-zed}/bin/zed --no-verify-ca --insecure --endpoint ''$ZED_ENDPOINT --token ''$ZED_TOKEN $@
          ''
        )
        (
          writeShellScriptBin "ptest" ''
            pytest --disable-warnings --no-cov -s -p no:warnings $@
          ''
        )
      ];
    in {
      formatter = pkgs.alejandra;

      devShells = rec {
        default = vm;
        devcontainer = pkgs.mkShell (poetrySettings
          // {
            buildInputs =
              commonPackages
              ++ [
                pkgs.devcontainer
                (pkgs.writeShellScriptBin "devc" ''
                  devcontainer exec --workspace-folder $FLAKE_ROOT \
                    --remote-env POETRY_VIRTUALENVS_IN_PROJECT=false \
                    -- bash -c "$@"
                '')
                (pkgs.writeShellScriptBin "devcontainer-up" ''
                  devcontainer up --workspace-folder $FLAKE_ROOT \
                    --remote-env POETRY_VIRTUALENVS_IN_PROJECT=false
                '')
                (pkgs.writeShellScriptBin "devcontainer-build" ''
                  devcontainer build --workspace-folder $FLAKE_ROOT \
                    --remote-env POETRY_VIRTUALENVS_IN_PROJECT=false
                '')
                (pkgs.writeShellScriptBin "devcontainer-destroy" ''
                  set -e
                  docker stop $(docker ps -a -q)
                  docker container ls -f "name=renku-data-services_*" -a -q | xargs docker rm -f
                  docker volume ls -f "name=renku-data-services_*" -q | xargs docker volume rm -f
                '')
                (pkgs.writeShellScriptBin "devcontainer-main-tests" ''
                  devcontainer exec --workspace-folder $FLAKE_ROOT \
                    --remote-env POETRY_VIRTUALENVS_IN_PROJECT=false \
                    -- bash -c "make main_tests"
                '')
                (pkgs.writeShellScriptBin "devcontainer-schemathesis" ''
                  devcontainer exec --workspace-folder $FLAKE_ROOT \
                    --remote-env POETRY_VIRTUALENVS_IN_PROJECT=false \
                    --remote-env HYPOTHESIS_PROFILE=ci \
                    -- bash -c "make schemathesis_tests"
                '')
                (pkgs.writeShellScriptBin "devcontainer-pytest" ''
                  devcontainer exec --workspace-folder $FLAKE_ROOT \
                     --remote-env POETRY_VIRTUALENVS_IN_PROJECT=false \
                     --remote-env HYPOTHESIS_PROFILE=ci \
                     --remote-env DUMMY_STORES=true \
                     -- bash -c "poetry run pytest --no-cov -p no:warnings -s \"$@\""
                '')
              ];

            shellHook = ''
              PYENV_PATH=$(poetry env info --path)
              export FLAKE_ROOT="$(git rev-parse --show-toplevel)"
              export PATH="$PYENV_PATH/bin:$PATH"
            '';
          });
        vm = pkgs.mkShell (devSettings
          // {
            buildInputs =
              commonPackages
              ++ (builtins.attrValues devshell-tools.legacyPackages.${system}.vm-scripts);

            DEV_VM = "rdsdev-vm";
            VM_SSH_PORT = "10022";

            DB_HOST = "localhost";
            DB_PORT = "15432";
            PGHOST = "localhost";
            PGPORT = "15432";
            AUTHZ_DB_HOST = "localhost";
            SOLR_URL = "http://localhost:18983";
            SOLR_CORE = "renku-search-dev";
          });

        vm-eikek = pkgs.mkShell (devSettings
          // {
            buildInputs =
              commonPackages
              ++ (builtins.attrValues devshell-tools.legacyPackages.${system}.vm-scripts);

            DEV_VM = "rdsdev-vm";
            VM_SSH_PORT = "10022";

            DB_HOST = "localhost";
            DB_PORT = "15432";
            PGHOST = "localhost";
            PGPORT = "15432";
            AUTHZ_DB_HOST = "localhost";
            SOLR_URL = "http://localhost:18983";
            SOLR_CORE = "renku-search-dev";

            AMALTHEA_SESSIONS_VERSION = "refs/heads/eikek/feat-prove-active-session";
            AMALTHEA_JS_VERSION = "refs/heads/eikek/feat-prove-active-session";
          });

        cnt = let
          # authzed-py doesn't allow to connect via non-localhost, so this must
          # be run (in the background) to forward localhost:50051 to the container
          forward-auth = pkgs.writeShellScriptBin "authzed-forward-localhost" ''
            ${pkgs.socat}/bin/socat TCP-LISTEN:50051,fork TCP:rsdevcnt:50051
          '';
        in
          pkgs.mkShell (
            devSettings
            // {
              buildInputs =
                commonPackages
                ++ [forward-auth]
                ++ (builtins.attrValues devshell-tools.legacyPackages.${system}.cnt-scripts);

              DEV_CONTAINER = "rsdevcnt";

              DB_HOST = "rsdevcnt";
              DB_PORT = "5432";
              PGHOST = "rsdevcnt";
              PGPORT = "5432";
              AUTHZ_DB_HOST = "localhost";
              SOLR_URL = "http://rsdevcnt:8983";
              SOLR_CORE = "renku-search-dev";
            }
          );
      };
    });
}
