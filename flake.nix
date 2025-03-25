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
        services = {
          services.dev-postgres = {
            enable = true;
            databases = ["renku_test"];
            init-script = ./.devcontainer/generate_ulid_func.sql;
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
          system = flake-utils.lib.system.x86_64-linux;
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

      devSettings = {
        CORS_ALLOW_ALL_ORIGINS = "true";
        DB_USER = "dev";
        DB_NAME = "renku";
        DB_PASSWORD = "dev";
        PGPASSWORD = "dev";
        AUTHZ_DB_KEY = "dev";
        AUTHZ_DB_NO_TLS_CONNECTION = "true";
        AUTHZ_DB_GRPC_PORT = "50051";

        LD_LIBRARY_PATH = "${pkgs.stdenv.cc.cc.lib}/lib";
        POETRY_VIRTUALENVS_PREFER_ACTIVE_PYTHON = "true";
        POETRY_VIRTUALENVS_OPTIONS_SYSTEM_SITE_PACKAGES = "true";
        POETRY_INSTALLER_NO_BINARY = "ruff";

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
        devcontainer
        redis
        postgresql
        jq
        devshellToolsPkgs.openapi-docs
        devshellToolsPkgs.solr
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
        (writeShellScriptBin "pyfix" ''
          poetry run ruff check --fix
          poetry run ruff format
        '')
      ];
    in {
      formatter = pkgs.alejandra;

      devShells = rec {
        default = vm;
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
