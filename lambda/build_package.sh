#!/usr/bin/env bash
# Build a clean AWS Lambda deployment zip for this function (ARM64 / Graviton).
# Output: lambda/lambda-deploy.zip (never pollutes the repo root)
#
# Usage:
#   ./lambda/build_package.sh
#   PYTHON_VERSION=3.12 ./lambda/build_package.sh
#
# IMPORTANT:
# - Lambda Architectures must be ["arm64"] to match this wheel.
# - Place Cockroach Cloud CA at repo root as cockroach-ca.crt before building.
# - In Lambda, set PGSSLROOTCERT=/var/task/root.crt (official Cockroach pattern).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
PLATFORM="manylinux2014_aarch64"
BUILD_DIR="${SCRIPT_DIR}/package"
ZIP_PATH="${SCRIPT_DIR}/lambda-deploy.zip"
CA_SRC="${REPO_ROOT}/cockroach-ca.crt"
CA_DST_NAME="root.crt"

echo "==> Cleaning previous build artifacts (avoid mixing x86_64 with arm64)"
rm -rf "${BUILD_DIR}"
rm -f "${ZIP_PATH}"
mkdir -p "${BUILD_DIR}"

if [[ ! -f "${CA_SRC}" ]]; then
  echo "ERROR: Missing ${CA_SRC}" >&2
  echo "Download the Cockroach Cloud CA first, e.g.:" >&2
  echo "  ccloud cluster cert 02ed67d5-8378-492c-8d93-5a3d8992d3ec --cert-dir ." >&2
  echo "  # then: mv root.crt cockroach-ca.crt   (or copy from Connect dialog)" >&2
  echo "  # or: curl -fsSL -o cockroach-ca.crt \\" >&2
  echo "  #   https://cockroachlabs.cloud/clusters/02ed67d5-8378-492c-8d93-5a3d8992d3ec/cert" >&2
  exit 1
fi

echo "==> Installing psycopg2-binary for Lambda ARM64 (${PLATFORM} / Python ${PYTHON_VERSION})"
pip install \
  --quiet \
  --upgrade \
  --platform "${PLATFORM}" \
  --target="${BUILD_DIR}" \
  --implementation cp \
  --python-version "${PYTHON_VERSION}" \
  --only-binary=:all: \
  psycopg2-binary

echo "==> Copying lambda_function.py"
cp "${SCRIPT_DIR}/lambda_function.py" "${BUILD_DIR}/lambda_function.py"

echo "==> Copying Cockroach CA as ${CA_DST_NAME} (Lambda path: /var/task/${CA_DST_NAME})"
cp "${CA_SRC}" "${BUILD_DIR}/${CA_DST_NAME}"

echo "==> Creating ${ZIP_PATH} (modules + root.crt at zip root, not nested under package/)"
BUILD_DIR="${BUILD_DIR}" ZIP_PATH="${ZIP_PATH}" python3 - <<'PY'
import os
import zipfile
from pathlib import Path

build_dir = Path(os.environ["BUILD_DIR"])
zip_path = Path(os.environ["ZIP_PATH"])

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in build_dir.rglob("*"):
        if path.is_file():
            # Write relative to package/ so zip root contains:
            #   lambda_function.py
            #   root.crt
            #   psycopg2/
            #   ...
            zf.write(path, path.relative_to(build_dir).as_posix())

names = zipfile.ZipFile(zip_path).namelist()
assert "root.crt" in names, "root.crt missing from zip root"
assert "lambda_function.py" in names, "lambda_function.py missing from zip root"
print(f"Wrote {zip_path} ({zip_path.stat().st_size / 1024:.1f} KB)")
print(f"Confirmed zip contains root.crt at package root")
PY

echo "==> Cleaning temporary package/ folder"
rm -rf "${BUILD_DIR}"

echo "==> Done. Upload lambda/lambda-deploy.zip to AWS Lambda."
echo "    Handler: lambda_function.lambda_handler"
echo "    Runtime: Python ${PYTHON_VERSION}"
echo "    Architecture: arm64 (Graviton)"
echo "    Confirmed pip platform used: ${PLATFORM}"
echo "    CA inside zip: root.crt  ->  Lambda path /var/task/root.crt"
echo "    Set Lambda env: PGSSLROOTCERT=/var/task/root.crt"
