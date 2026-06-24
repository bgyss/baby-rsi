{
  description = "baby-rsi — bounded self-improving research organization testbed";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        # Reproducible bootstrap shell.
        #
        # Layering:
        #   nix  — this shell: provides `mise` + native/system deps (no global installs).
        #   mise — single source of truth for language tool versions (python, uv) + task runner.
        #   uv   — Python dependency resolution, lockfile, and `.venv` management.
        #
        # nix deliberately does NOT provide python/uv itself; mise owns those so tool
        # versions are pinned in one place (mise.toml) and reproducible off-Nix too.
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            mise           # language tool versions + task runner
            llama-cpp      # local model server (llama-server) for the research loop;
                           # Tier 0 talks to an OpenAI-compatible llama.cpp endpoint.
                           # An external LlamaBarn server (127.0.0.1:2276) also works.
            stdenv.cc      # C toolchain for any native Python wheels
            git
            jujutsu        # repo is versioned with git + jj
          ];

          shellHook = ''
            export MISE_TRUSTED_CONFIG_PATHS="$PWD:''${MISE_TRUSTED_CONFIG_PATHS:-}"
            eval "$(mise activate bash)"
            mise install
          '';
        };
      });
}
