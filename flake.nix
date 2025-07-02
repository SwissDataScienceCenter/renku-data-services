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

      rclone = pkgs.rclone.overrideAttrs (old: {
        version = "1.70.0";
        vendorHash = "sha256-Wu9d98SIENCkJYoGT/f9KN8vnYYGMN7HxhzqtkOYQ/8=";
        src = pkgs.fetchFromGitHub {
          owner = "SwissDataScienceCenter";
          repo = "rclone";
          rev = "v1.70.0+renku-1";
          sha256 = "sha256-aorgWwYBVVOYhMXXBDWBMXkaZi0WjnGaMoRlwXCa5w4=";
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
          PSQLRC = (pkgs.writeText "rsdrc.sql" ''
            SET SEARCH_PATH TO authz,common,connected_services,events,platform,projects,public,resource_pools,secrets,sessions,storage,users
          '');
          AUTHZ_DB_KEY = "dev";
          AUTHZ_DB_NO_TLS_CONNECTION = "true";
          AUTHZ_DB_GRPC_PORT = "50051";

          DUMMY_STORES = "true";

          ZED_ENDPOINT = "localhost:50051";
          ZED_TOKEN = "dev";

          SOLR_BIN_PATH = "${devshellToolsPkgs.solr}/bin/solr";

          shellHook = ''
            export FLAKE_ROOT="$(git rev-parse --show-toplevel)"
            export PATH="$FLAKE_ROOT/.venv/bin:$PATH"
            export ALEMBIC_CONFIG="$FLAKE_ROOT/components/renku_data_services/migrations/alembic.ini"
            export NB_SERVER_OPTIONS__DEFAULTS_PATH="$FLAKE_ROOT/server_defaults.json"
            export NB_SERVER_OPTIONS__UI_CHOICES_PATH="$FLAKE_ROOT/server_options.json"
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
        ruff-lsp
        poetry
        python313
        basedpyright
        rclone
        (writeShellScriptBin "pg" ''
          psql -h $DB_HOST -p $DB_PORT -U dev $DB_NAME
        ''
        )
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
        (writeShellScriptBin "zedl" ''
          ${spicedb-zed}/bin/zed --no-verify-ca --insecure --endpoint ''$ZED_ENDPOINT --token ''$ZED_TOKEN $@
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
              export FLAKE_ROOT="$(git rev-parse --show-toplevel)"
              export PATH="$FLAKE_ROOT/.venv/bin:$PATH"
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
            AUTHZ_DB_HOST = "localhost";
            SOLR_URL = "http://localhost:18983";
            SOLR_CORE = "renku-search-dev";
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
              AUTHZ_DB_HOST = "localhost";
              SOLR_URL = "http://rsdevcnt:8983";
              SOLR_CORE = "renku-search-dev";
            }
          );
      };
    });
}
