#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_TERRAFORM_VALIDATE=0

if [[ "${1:-}" == "--with-terraform" ]]; then
  RUN_TERRAFORM_VALIDATE=1
  shift
fi

if [[ $# -ne 0 ]]; then
  echo "Usage: $0 [--with-terraform]"
  exit 1
fi

if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

echo "==> Bytecode compile check"
"${PYTHON_BIN}" -m compileall "${ROOT_DIR}/app" "${ROOT_DIR}/scripts" "${ROOT_DIR}/server.py"

echo "==> Unit test suite"
"${PYTHON_BIN}" -m unittest discover -s "${ROOT_DIR}/testing" -p "test_*.py"

if [[ "${RUN_TERRAFORM_VALIDATE}" -eq 1 ]]; then
  if ! command -v terraform >/dev/null 2>&1; then
    echo "Terraform is not installed."
    exit 1
  fi

  if [[ ! -d "${ROOT_DIR}/infra/.terraform" ]]; then
    echo "Terraform is not initialized in infra/. Run 'terraform -chdir=infra init' first."
    exit 1
  fi

  echo "==> Terraform validate"
  terraform -chdir="${ROOT_DIR}/infra" validate
fi
