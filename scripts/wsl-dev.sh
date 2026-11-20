#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
ARTIFACT_DIR="${LAMBDA_ARTIFACT_DIR:-$ROOT_DIR/.artifacts}"

if [[ "$ARTIFACT_DIR" != /* ]]; then
  ARTIFACT_DIR="$ROOT_DIR/$ARTIFACT_DIR"
fi

check_tools() {
  if ! command -v zip >/dev/null 2>&1; then
    printf 'zip is required to build Lambda artifacts.\n' >&2
    exit 1
  fi
}

check_destination() {
  local artifact="$1"
  if [[ -e "$artifact" || -L "$artifact" ]]; then
    printf 'Artifact already exists: %s\nChoose a different LAMBDA_ARTIFACT_DIR or move the existing artifact.\n' "$artifact" >&2
    exit 1
  fi
}

package_source() (
  local source_dir="$ROOT_DIR/src/servicenow_mcp_server"
  local artifact="$ARTIFACT_DIR/lambda-src.zip"
  if [[ ! -d "$source_dir" ]]; then
    printf 'Source package not found: %s\n' "$source_dir" >&2
    exit 1
  fi
  check_destination "$artifact"
  local build_dir
  build_dir="$(mktemp -d "${TMPDIR:-/tmp}/snow-mcp-lambda-src.XXXXXX")"
  trap 'rm -rf "$build_dir"' EXIT
  cp -a "$source_dir" "$build_dir/servicenow_mcp_server"
  find "$build_dir" -type d -name '__pycache__' -prune -exec rm -rf {} +
  find "$build_dir" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
  (cd "$build_dir" && zip -qr "$build_dir/artifact.zip" servicenow_mcp_server)
  mkdir -p "$ARTIFACT_DIR"
  mv "$build_dir/artifact.zip" "$artifact"
  printf 'Lambda source ZIP: %s\n' "$artifact"
  printf 'Handler: servicenow_mcp_server.lambda.handler\n'
)

package_layer() (
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    printf 'WSL virtual environment missing: %s\n' "$VENV_DIR" >&2
    exit 1
  fi
  local artifact="$ARTIFACT_DIR/lambda-layer.zip"
  check_destination "$artifact"
  local python_version site_packages
  python_version="$("$VENV_DIR/bin/python" -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')"
  site_packages="$("$VENV_DIR/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
  if [[ ! -d "$site_packages" ]]; then
    printf 'site-packages not found: %s\n' "$site_packages" >&2
    exit 1
  fi
  local build_dir layer_site_packages
  build_dir="$(mktemp -d "${TMPDIR:-/tmp}/snow-mcp-lambda-layer.XXXXXX")"
  trap 'rm -rf "$build_dir"' EXIT
  layer_site_packages="$build_dir/python/lib/$python_version/site-packages"
  mkdir -p "$layer_site_packages"
  cp -a "$site_packages/." "$layer_site_packages/"
  find "$layer_site_packages" -maxdepth 1 \( -name '__editable__.snow_mcp-*.pth' -o -name '__editable___snow_mcp_*_finder.py' -o -name 'snow_mcp-*.dist-info' \) -exec rm -rf {} +
  find "$build_dir" -type d -name '__pycache__' -prune -exec rm -rf {} +
  find "$build_dir" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
  (cd "$build_dir" && zip -qr "$build_dir/artifact.zip" python)
  mkdir -p "$ARTIFACT_DIR"
  mv "$build_dir/artifact.zip" "$artifact"
  printf 'Lambda layer ZIP: %s\n' "$artifact"
  printf 'Layer layout: python/lib/%s/site-packages\n' "$python_version"
  printf 'Use a Lambda runtime and CPU architecture compatible with this virtual environment.\n'
)

check_tools
case "${1:-lambda-package}" in
  lambda-src)
    package_source
    ;;
  lambda-layer)
    package_layer
    ;;
  lambda-package)
    check_destination "$ARTIFACT_DIR/lambda-src.zip"
    check_destination "$ARTIFACT_DIR/lambda-layer.zip"
    package_source
    package_layer
    ;;
  *)
    printf 'Usage: %s [lambda-src|lambda-layer|lambda-package]\n' "$0" >&2
    exit 2
    ;;
esac