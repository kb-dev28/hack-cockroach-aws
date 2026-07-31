#!/usr/bin/env bash
# Build a clean AWS Lambda deployment zip for this function.
# Output: lambda/lambda-deploy.zip (never pollutes the repo root)
#
# Usage:
#   ./lambda/build_package.sh
#   PYTHON_VERSION=3.12 ./lambda/build_package.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
BUILD_DIR="${SCRIPT_DIR}/package"
ZIP_PATH="${SCRIPT_DIR}/lambda-deploy.zip"

echo "==> Cleaning previous build artifacts"
rm -rf "${BUILD_DIR}"
rm -f "${ZIP_PATH}"
mkdir -p "${BUILD_DIR}"

echo "==> Installing psycopg2-binary (manylinux / Python ${PYTHON_VERSION})"
pip install \
  --quiet \
  --upgrade \
  --target "${BUILD_DIR}" \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version "${PYTHON_VERSION}" \
  --only-binary=:all: \
  psycopg2-binary

echo "==> Copying lambda_function.py"
cp "${SCRIPT_DIR}/lambda_function.py" "${BUILD_DIR}/lambda_function.py"

echo "==> Creating ${ZIP_PATH}"
BUILD_DIR="${BUILD_DIR}" ZIP_PATH="${ZIP_PATH}" python3 - <<'PY'
import os
import zipfile
from pathlib import Path

build_dir = Path(os.environ["BUILD_DIR"])
zip_path = Path(os.environ["ZIP_PATH"])

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in build_dir.rglob("*"):
        if path.is_file():
            zf.write(path, path.relative_to(build_dir).as_posix())

print(f"Wrote {zip_path} ({zip_path.stat().st_size / 1024:.1f} KB)")
PY

echo "==> Cleaning temporary package/ folder"
rm -rf "${BUILD_DIR}"

echo "==> Done. Upload lambda/lambda-deploy.zip to AWS Lambda."
echo "    Handler: lambda_function.lambda_handler"
echo "    Runtime tip: match PYTHON_VERSION (default 3.12)"
