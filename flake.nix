{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/release-24.05";
    flake-utils.url = "github:numtide/flake-utils";
    devshell-tools.url = "github:eikek/devshell-tools";
    poetry2nix.url = "github:nix-community/poetry2nix";
  };

  outputs = inputs @ {
    self,
    nixpkgs,
    flake-utils,
    devshell-tools,
    poetry2nix,
  }:
    {
      nixosConfigurations = let
        services = {
          services.dev-postgres = {
            enable = true;
            databases = ["renku"];
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

      poetryLib = poetry2nix.lib.mkPoetry2Nix {inherit pkgs;};
      p2n-args = {
        projectDir = ./.;
        python = pkgs.python312;
        editablePackageSources = {
          bases = ./bases;
          components = ./components;
        };
        extraPackages = p: [
          p.ruff-lsp
        ];
        overrides = let
          add-setuptools = name: final: prev:
            prev.${name}.overridePythonAttrs (old: {buildInputs = (old.buildInputs or []) ++ [prev.setuptools];});
          add-poetry = name: final: prev:
            prev.${name}.overridePythonAttrs (old: {buildInputs = (old.buildInputs or []) ++ [prev.poetry];});
        in
          poetryLib.defaultPoetryOverrides.extend
          (final: prev: {
            appier = add-setuptools "appier" final prev;
            inflector = add-setuptools "inflector" final prev;
            google-api = add-setuptools "google-api" final prev;
            sanic-ext = add-setuptools "sanic-ext" final prev;
            undictify = add-setuptools "undictify" final prev;
            types-cffi = add-setuptools "types-cffi" final prev;
            avro-preprocessor = add-setuptools "avro-preprocessor" final prev;
            authzed = add-poetry "authzed" final prev;
            dataclasses-avroschema = add-poetry "dataclasses-avroschema" final prev;
            datamodel-code-generator = add-poetry "datamodel-code-generator" final prev;
            kubernetes-asyncio = add-setuptools "kubernetes-asyncio" final prev;
            prometheus-sanic =
              prev.prometheus-sanic.overridePythonAttrs
              (
                old: {
                  buildInputs = (old.buildInputs or []) ++ [prev.poetry prev.poetry-core];
                  # fix the wrong dependency
                  # see https://github.com/nix-community/poetry2nix/issues/1694
                  postPatch = ''
                    substituteInPlace pyproject.toml --replace "poetry.masonry" "poetry.core.masonry"
                  '';
                }
              );
          });
      };

      projectEnv = poetryLib.mkPoetryEnv p2n-args;

      devSettings = {
        CORS_ALLOW_ALL_ORIGINS = "true";
        DB_USER = "dev";
        DB_NAME = "renku";
        DB_PASSWORD = "dev";
        AUTHZ_DB_KEY = "dev";
        AUTHZ_DB_NO_TLS_CONNECTION = "true";
        AUTHZ_DB_GRPC_PORT = "50051";
        ALEMBIC_CONFIG = "./components/renku_data_services/migrations/alembic.ini";

        # necessary for poetry run … as it might need to compile stuff
        # ONLY WHEN NOT using python from nix dev environment
        #LD_LIBRARY_PATH = "${pkgs.stdenv.cc.cc.lib}/lib";
        POETRY_VIRTUALENVS_PREFER_ACTIVE_PYTHON = "true";
        POETRY_VIRTUALENVS_OPTIONS_SYSTEM_SITE_PACKAGES = "true";
      };

      fix-poetry-cfg = pkgs.writeShellScriptBin "poetry-fix-cfg" ''
        python_exec="$(which python)"
        python_bin="$(dirname "$python_exec")"
        python_env="$(dirname "$python_bin")"

        env_path="$(poetry env info -p)"
        if [ -z "$env_path" ]; then
          poetry env use "$python_exec"
          env_path="$(poetry env info -p)"
        fi
        env_cfg="$env_path/pyvenv.cfg"

        if [ ! -r "$env_path/pyvenv.cfg.bak" ]; then
          cp "$env_path/pyvenv.cfg" "$env_path/pyvenv.cfg.bak"
        fi

        echo "Fix paths in: $env_cfg"
        ${pkgs.gnused}/bin/sed -i -E "s,home = (.*)$,home = $python_bin,g" "$env_cfg"
        ${pkgs.gnused}/bin/sed -i -E "s,base-prefix = (.*)$,base-prefix = $python_env,g" "$env_cfg"
        ${pkgs.gnused}/bin/sed -i -E "s,base-exec-prefix = (.*)$,base-exec-prefix = $python_env,g" "$env_cfg"
        ${pkgs.gnused}/bin/sed -i -E "s,base-executable = (.*)$,base-executable = $python_exec,g" "$env_cfg"
      '';
      commonPackages = with pkgs; [
        redis
        postgresql
        jq
        devshellToolsPkgs.openapi-docs
        spicedb
        spicedb-zed
        ruff
        ruff-lsp
        poetry
        pyright
        mypy
        rclone
        fix-poetry-cfg
      ];
    in {
      formatter = pkgs.alejandra;

      devShells = rec {
        default = vm;
        vm = projectEnv.env.overrideAttrs (oldAttrs:
          devSettings
          // {
            buildInputs =
              commonPackages
              ++ (builtins.attrValues devshell-tools.legacyPackages.${system}.vm-scripts);

            DEV_VM = "rdsdev-vm";
            VM_SSH_PORT = "10022";

            DB_HOST = "localhost";
            DB_PORT = "15432";
            AUTHZ_DB_HOST = "localhost";
          });

        cnt = let
          # authzed-py doesn't allow to connect via non-localhost, so this must
          # be run (in the background) to forward localhost:50051 to the container
          forward-auth = pkgs.writeShellScriptBin "authzed-forward-localhost" ''
            ${pkgs.socat}/bin/socat TCP-LISTEN:50051,fork TCP:rsdevcnt:50051
          '';
        in
          projectEnv.env.overrideAttrs (oldAttrs:
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
            });
      };
    });
}
