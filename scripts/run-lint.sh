#!/usr/bin/env bash
# ==============================================================================
# Script Auxiliar de Linting e Verificação PEP 8 do Homelab
# ==============================================================================
# Utiliza a configuração canônica do .flake8 na raiz do projeto para auditar
# conformidade de estilo, limites de linha (100) e complexidade ciclomática.
#
# Uso:
#   ./scripts/run-lint.sh             # Audita os diretórios padrão (app/ e tests/)
#   ./scripts/run-lint.sh app/server/  # Audita arquivo ou pacote específico
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

FLAKE8_CMD=""

if command -v flake8 >/dev/null 2>&1; then
    FLAKE8_CMD="flake8"
elif [ -f "${REPO_ROOT}/.venv/bin/flake8" ]; then
    FLAKE8_CMD="${REPO_ROOT}/.venv/bin/flake8"
elif [ -f "${REPO_ROOT}/venv/bin/flake8" ]; then
    FLAKE8_CMD="${REPO_ROOT}/venv/bin/flake8"
elif python3 -m flake8 --version >/dev/null 2>&1; then
    FLAKE8_CMD="python3 -m flake8"
fi

if [ -z "${FLAKE8_CMD}" ]; then
    echo "=================================================================="
    echo " [AVISO] O utilitário 'flake8' não foi encontrado no ambiente."
    echo "=================================================================="
    echo " Para instalar e executar o linter oficial do Homelab:"
    echo "   1) No ambiente virtual ativo: pip install flake8"
    echo "   2) No Termux / Debian 11:     python3 -m pip install flake8"
    echo ""
    echo " A configuração canônica já está pronta em: .flake8"
    echo "=================================================================="
    exit 0
fi

TARGETS=("$@")
if [ ${#TARGETS[@]} -eq 0 ]; then
    TARGETS=("app" "tests")
fi

echo "=================================================================="
echo " [*] Executando Flake8 nos alvos: ${TARGETS[*]}"
echo " [*] Configuração canônica: ${REPO_ROOT}/.flake8"
echo "=================================================================="

${FLAKE8_CMD} --config="${REPO_ROOT}/.flake8" "${TARGETS[@]}"
EXIT_CODE=$?

if [ ${EXIT_CODE} -eq 0 ]; then
    echo " [✓] Sucesso! Todo o código analisado está 100% conforme a PEP 8."
else
    echo " [!] Foram encontradas não-conformidades de estilo listadas acima."
fi

exit ${EXIT_CODE}
