#!/usr/bin/env bash
# ==============================================================================
# Homelab TCP Dual-Protocol - Verificação de Infraestrutura e Pré-Voo
# Script: scripts/check-infra.sh
# Objetivo: Validação estrita (Fail-Fast) de arquivos .env, limites de rede
#           e saúde do host (Debian 11 / UserLAnd / Termux / macOS).
# ==============================================================================

set -eo pipefail

# Cores ANSI (habilitadas somente se terminal interativo e NO_COLOR não estiver definida)
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    BLUE='\033[0;34m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    BLUE=''
    YELLOW=''
    CYAN=''
    NC=''
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[AVISO]${NC} $1"
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
}

show_help() {
    cat << EOF
Uso: $(basename "$0") [OPÇÕES]

Opções:
  --mode <server|client>   Define o perfil de validação (padrão: server)
  --local                  Atalho para --mode server
  --remote                 Atalho para --mode client
  --env-only               Valida apenas as variáveis e limites do arquivo .env (sem probes de rede/host)
  --env-file <caminho>     Especifica o caminho de um arquivo .env customizado
  --ssh                    (Modo client) Realiza probe de conectividade SSH no host alvo
  --ssh-port <porta>       Porta para probe SSH (padrão: 2022 para UserLAnd Debian ou 8022 para Termux)
  -h, --help               Exibe esta mensagem de ajuda

Exemplos:
  $(basename "$0") --mode server --env-only
  $(basename "$0") --mode client --env-file envs/client.env.sample --env-only
  $(basename "$0") --local
  $(basename "$0") --remote --ssh
EOF
}

# ------------------------------------------------------------------------------
# 1. Parsing de Argumentos da Linha de Comando
# ------------------------------------------------------------------------------
MODE="server"
ENV_ONLY=false
ENV_FILE=""
SSH_CHECK=false
SSH_PORT="2022"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            if [ -z "${2:-}" ]; then
                log_fail "A flag --mode requer um valor ('server' ou 'client')."
                exit 1
            fi
            if [ "$2" != "server" ] && [ "$2" != "client" ]; then
                log_fail "Modo inválido: '$2'. Use 'server' ou 'client'."
                exit 1
            fi
            MODE="$2"
            shift 2
            ;;
        --local)
            MODE="server"
            shift
            ;;
        --remote)
            MODE="client"
            shift
            ;;
        --env-only)
            ENV_ONLY=true
            shift
            ;;
        --env-file)
            if [ -z "${2:-}" ]; then
                log_fail "A flag --env-file requer o caminho para um arquivo."
                exit 1
            fi
            ENV_FILE="$2"
            shift 2
            ;;
        --ssh)
            SSH_CHECK=true
            shift
            ;;
        --ssh-port)
            if [ -z "${2:-}" ]; then
                log_fail "A flag --ssh-port requer um número de porta válido."
                exit 1
            fi
            SSH_PORT="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            log_fail "Opção desconhecida: $1"
            show_help
            exit 1
            ;;
    esac
done

MODE_UPPER=$(echo "$MODE" | tr '[:lower:]' '[:upper:]')
echo -e "${CYAN}=== Homelab Infra Check & Pre-Flight (Modo: ${MODE_UPPER}) ===${NC}"

# ------------------------------------------------------------------------------
# 2. Resolução do Arquivo de Ambiente (.env)
# ------------------------------------------------------------------------------
TARGET_ENV_FILE=""

if [ -n "$ENV_FILE" ]; then
    if [ -f "$ENV_FILE" ]; then
        TARGET_ENV_FILE="$ENV_FILE"
    elif [ -f "$REPO_ROOT/$ENV_FILE" ]; then
        TARGET_ENV_FILE="$REPO_ROOT/$ENV_FILE"
    else
        log_fail "Arquivo de configuração não encontrado: $ENV_FILE"
        exit 1
    fi
else
    if [ "$MODE" = "server" ]; then
        candidates=("envs/server.env" "envs/.env" "server.env" ".env")
    else
        candidates=("envs/client.env" "envs/.env" "client.env" ".env")
    fi

    for c in "${candidates[@]}"; do
        if [ -f "$c" ]; then
            TARGET_ENV_FILE="$c"
            break
        elif [ -f "$REPO_ROOT/$c" ]; then
            TARGET_ENV_FILE="$REPO_ROOT/$c"
            break
        fi
    done

    if [ -z "$TARGET_ENV_FILE" ]; then
        log_fail "Nenhum arquivo de ambiente encontrado para o modo '$MODE'."
        echo -e "${RED}       Caminhos pesquisados: ${candidates[*]}${NC}"
        exit 1
    fi
fi

log_info "Arquivo de configuração selecionado: $TARGET_ENV_FILE"

# ------------------------------------------------------------------------------
# 3. Helper de Parsing de Variáveis
# ------------------------------------------------------------------------------
get_env_val() {
    local key="$1"
    local file="$2"
    local line
    line=$(grep -E "^[[:space:]]*${key}=" "$file" 2>/dev/null | tail -n 1 || true)
    if [ -z "$line" ]; then
        echo ""
        return 1
    fi
    local val
    val="${line#*=}"
    # Remove espaços no início e fim
    val=$(echo "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
    # Remove aspas se houver
    if [[ "$val" =~ ^\".*\"$ ]]; then
        val="${val#\"}"
        val="${val%\"}"
    elif [[ "$val" =~ ^\'.*\'$ ]]; then
        val="${val#\'}"
        val="${val%\'}"
    fi
    # Remove \r de quebra de linha Windows
    val=$(echo "$val" | tr -d '\r')
    echo "$val"
    if [ -z "$val" ]; then
        return 1
    fi
    return 0
}

# ------------------------------------------------------------------------------
# 4. Fail-Fast Estrito: Variáveis Obrigatórias
# ------------------------------------------------------------------------------
MISSING_VARS=()

if [ "$MODE" = "server" ]; then
    REQUIRED_VARS=(
        "HOMELAB_SERVER_HOST"
        "HOMELAB_CONTROL_PORT"
        "HOMELAB_DATA_PORT"
        "HOMELAB_HANDSHAKE_KEY"
        "HOMELAB_CHUNK_SIZE"
        "HOMELAB_BUFFER_SIZE"
        "HOMELAB_DB_PATH"
        "HOMELAB_LOG_PATH"
        "HOMELAB_UPLOADS_DIR"
    )
else
    REQUIRED_VARS=(
        "HOMELAB_CLIENT_TARGET_HOST"
        "HOMELAB_CONTROL_PORT"
        "HOMELAB_DATA_PORT"
        "HOMELAB_HANDSHAKE_KEY"
        "HOMELAB_CHUNK_SIZE"
        "HOMELAB_CLIENT_BUFFER_SIZE"
        "HOMELAB_CLIENT_TIMEOUT"
        "HOMELAB_SESSION_PATH"
    )
fi

for var in "${REQUIRED_VARS[@]}"; do
    val=$(get_env_val "$var" "$TARGET_ENV_FILE" || true)
    if [ -z "$val" ]; then
        MISSING_VARS+=("$var")
    fi
done

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    log_fail "Variáveis obrigatórias ausentes ou vazias em '$TARGET_ENV_FILE':"
    for mv in "${MISSING_VARS[@]}"; do
        echo -e "${RED}       - $mv${NC}"
    done
    exit 1
fi

log_success "Todas as variáveis obrigatórias estão presentes e preenchidas."

# ------------------------------------------------------------------------------
# 5. Validações de Limites e Portas
# ------------------------------------------------------------------------------
CONTROL_PORT=$(get_env_val "HOMELAB_CONTROL_PORT" "$TARGET_ENV_FILE")
DATA_PORT=$(get_env_val "HOMELAB_DATA_PORT" "$TARGET_ENV_FILE")

if ! [[ "$CONTROL_PORT" =~ ^[0-9]+$ ]]; then
    log_fail "HOMELAB_CONTROL_PORT deve ser um número inteiro (recebido: '$CONTROL_PORT')."
    exit 1
fi

if ! [[ "$DATA_PORT" =~ ^[0-9]+$ ]]; then
    log_fail "HOMELAB_DATA_PORT deve ser um número inteiro (recebido: '$DATA_PORT')."
    exit 1
fi

if [ "$CONTROL_PORT" -lt 1024 ] || [ "$CONTROL_PORT" -gt 65535 ]; then
    log_fail "HOMELAB_CONTROL_PORT ($CONTROL_PORT) inválida: deve ser porta não privilegiada entre 1024 e 65535."
    exit 1
fi

if [ "$DATA_PORT" -lt 1024 ] || [ "$DATA_PORT" -gt 65535 ]; then
    log_fail "HOMELAB_DATA_PORT ($DATA_PORT) inválida: deve ser porta não privilegiada entre 1024 e 65535."
    exit 1
fi

if [ "$CONTROL_PORT" -eq "$DATA_PORT" ]; then
    log_fail "Conflito de portas: HOMELAB_CONTROL_PORT e HOMELAB_DATA_PORT não podem ser iguais ($CONTROL_PORT)."
    exit 1
fi

log_success "Validação de portas OK (Controle: $CONTROL_PORT, Dados: $DATA_PORT - Faixa não-privilegiada sem conflito)."

# Se --env-only foi solicitado, encerra com sucesso aqui
if [ "$ENV_ONLY" = true ]; then
    log_success "Verificação estrita de ambiente concluída com sucesso (--env-only)."
    exit 0
fi

# ------------------------------------------------------------------------------
# 6. Checagens Locais de Host (--mode server)
# ------------------------------------------------------------------------------
if [ "$MODE" = "server" ]; then
    echo -e "\n${CYAN}--- Checagens Locais do Host Servidor ---${NC}"

    # 6.1 Detecção do Sistema Operacional
    OS_NAME="Desconhecido"
    if [ -f /data/data/com.termux/files/usr/bin/bash ] || [ -n "${PREFIX:-}" ]; then
        OS_NAME="Android (Termux)"
    elif [ -f /etc/debian_version ]; then
        DEB_VER=$(cat /etc/debian_version 2>/dev/null || echo "11")
        if [ -d "/support" ] || grep -q -i "userland" /proc/version 2>/dev/null; then
            OS_NAME="Debian $DEB_VER (UserLAnd no Xiaomi Redmi Note 9S)"
        else
            OS_NAME="Debian $DEB_VER / Linux"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        DARWIN_VER=$(sw_vers -productVersion 2>/dev/null || uname -r)
        OS_NAME="macOS ($DARWIN_VER)"
    elif [ -f /etc/os-release ]; then
        OS_NAME=$(grep -E "^PRETTY_NAME=" /etc/os-release | cut -d= -f2 | tr -d '"')
    else
        OS_NAME="$(uname -s) $(uname -r)"
    fi
    log_info "Sistema Operacional detectado: $OS_NAME"

    # 6.2 Python e Ambiente Virtual
    VENV_PY=""
    if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python3" ]; then
        VENV_PY="${VIRTUAL_ENV}/bin/python3"
    elif [ -x "$REPO_ROOT/.venv/bin/python3" ]; then
        VENV_PY="$REPO_ROOT/.venv/bin/python3"
    elif [ -x ".venv/bin/python3" ]; then
        VENV_PY=".venv/bin/python3"
    elif command -v python3 >/dev/null 2>&1; then
        VENV_PY="$(command -v python3)"
    fi

    if [ -n "$VENV_PY" ]; then
        PY_VER=$("$VENV_PY" --version 2>&1)
        log_success "Ambiente Python: $VENV_PY ($PY_VER)"
    else
        log_warn "Interpretador Python 3 não detectado em .venv ou no PATH."
    fi

    # 6.3 Memória RAM Livre
    FREE_RAM=""
    if command -v free >/dev/null 2>&1; then
        FREE_RAM=$(free -m | awk '/^Mem:/{print $7}')
        if [ -z "$FREE_RAM" ] || [ "$FREE_RAM" = "0" ]; then
            FREE_RAM=$(free -m | awk '/^Mem:/{print $4}')
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        FREE_RAM=$(python3 -c "
import subprocess
try:
    out = subprocess.check_output(['sysctl', '-n', 'hw.memsize']).decode().strip()
    print(int(int(out) / (1024 * 1024) / 4))
except Exception:
    print('1024')
" 2>/dev/null || echo "1024")
    fi

    if [ -n "$FREE_RAM" ] && [[ "$FREE_RAM" =~ ^[0-9]+$ ]]; then
        if [ "$FREE_RAM" -lt 300 ]; then
            log_warn "Memória RAM disponível baixa: ${FREE_RAM}MB (< 300MB recomendados para Debian UserLAnd)."
        else
            log_success "Memória RAM livre estimada: ${FREE_RAM}MB (>= 300MB)."
        fi
    fi

    # 6.4 Espaço em Disco
    DISK_FREE=$(df -h "$REPO_ROOT" 2>/dev/null | awk 'NR==2 {print $4 " livres de " $2 " (uso: " $5 ")"}')
    if [ -n "$DISK_FREE" ]; then
        log_info "Espaço em disco no projeto: $DISK_FREE"
    fi

    # 6.5 Limite de Arquivos Abertos (ulimit -n)
    CURRENT_ULIMIT=$(ulimit -n 2>/dev/null || echo "0")
    if [[ "$CURRENT_ULIMIT" =~ ^[0-9]+$ ]]; then
        if [ "$CURRENT_ULIMIT" -lt 1024 ]; then
            log_warn "ulimit -n atual ($CURRENT_ULIMIT) é inferior a 1024 (recomendado aumentar para conexões simultâneas)."
        else
            log_success "Limite de descritores de arquivo (ulimit -n): $CURRENT_ULIMIT (>= 1024)."
        fi
    fi

    # 6.6 Processo app/server.py e Escuta de Portas
    SERVER_PIDS=$(pgrep -f "app/server.py" 2>/dev/null || true)
    if [ -n "$SERVER_PIDS" ]; then
        log_success "Processo do servidor em execução (PID: $(echo "$SERVER_PIDS" | tr '\n' ' '))"
    else
        log_info "Processo app/server.py não está ativo no momento."
    fi

    check_port_listening() {
        local port="$1"
        python3 -c "
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1.0)
try:
    res = s.connect_ex(('127.0.0.1', int('$port')))
    s.close()
    sys.exit(0 if res == 0 else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null
    }

    if check_port_listening "$CONTROL_PORT"; then
        log_success "Porta de Controle local ($CONTROL_PORT): EM ESCUTA"
    else
        log_info "Porta de Controle local ($CONTROL_PORT): Livre / Não em escuta"
    fi

    if check_port_listening "$DATA_PORT"; then
        log_success "Porta de Dados local ($DATA_PORT): EM ESCUTA"
    else
        log_info "Porta de Dados local ($DATA_PORT): Livre / Não em escuta"
    fi

    echo -e "\n${GREEN}=== Diagnóstico do Servidor Concluído com Sucesso ===${NC}"
    exit 0
fi

# ------------------------------------------------------------------------------
# 7. Checagens Remotas (--mode client)
# ------------------------------------------------------------------------------
if [ "$MODE" = "client" ]; then
    TARGET_HOST=$(get_env_val "HOMELAB_CLIENT_TARGET_HOST" "$TARGET_ENV_FILE")
    TIMEOUT_SEC=$(get_env_val "HOMELAB_CLIENT_TIMEOUT" "$TARGET_ENV_FILE")
    TIMEOUT_SEC="${TIMEOUT_SEC:-5}"

    echo -e "\n${CYAN}--- Checagens Remotas de Conectividade do Cliente ---${NC}"
    log_info "Host Alvo configurado: $TARGET_HOST (Timeout: ${TIMEOUT_SEC}s)"

    # 7.1 Ping ICMP
    if ping -c 1 -W 2 "$TARGET_HOST" >/dev/null 2>&1 || ping -c 1 "$TARGET_HOST" >/dev/null 2>&1; then
        log_success "Host alvo responde ao ping ICMP ($TARGET_HOST)."
    else
        log_warn "Host alvo ($TARGET_HOST) não respondeu ao ping ICMP (ICMP pode estar bloqueado por firewall)."
    fi

    # 7.2 Probes TCP Ativos
    probe_tcp() {
        local host="$1"
        local port="$2"
        local timeout="$3"
        python3 -c "
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(float('$timeout'))
try:
    res = s.connect_ex(('$host', int('$port')))
    s.close()
    sys.exit(0 if res == 0 else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null
    }

    if probe_tcp "$TARGET_HOST" "$CONTROL_PORT" "$TIMEOUT_SEC"; then
        log_success "Canal de Controle ($TARGET_HOST:$CONTROL_PORT): ACESSÍVEL / CONEXÃO ESTABELECIDA"
    else
        log_warn "Canal de Controle ($TARGET_HOST:$CONTROL_PORT): INACESSÍVEL / CONEXÃO RECUSADA"
    fi

    if probe_tcp "$TARGET_HOST" "$DATA_PORT" "$TIMEOUT_SEC"; then
        log_success "Canal de Dados ($TARGET_HOST:$DATA_PORT): ACESSÍVEL / CONEXÃO ESTABELECIDA"
    else
        log_warn "Canal de Dados ($TARGET_HOST:$DATA_PORT): INACESSÍVEL / CONEXÃO RECUSADA"
    fi

    # 7.3 Checagem opcional de SSH
    if [ "$SSH_CHECK" = true ]; then
        log_info "Verificando serviço SSH no host alvo (porta $SSH_PORT)..."
        if probe_tcp "$TARGET_HOST" "$SSH_PORT" "$TIMEOUT_SEC"; then
            log_success "Serviço SSH ($TARGET_HOST:$SSH_PORT): ACESSÍVEL"
        else
            log_warn "Serviço SSH ($TARGET_HOST:$SSH_PORT): INACESSÍVEL (verifique se sshd está ativo no Debian/UserLAnd)"
        fi
    fi

    echo -e "\n${GREEN}=== Diagnóstico do Cliente Concluído com Sucesso ===${NC}"
    exit 0
fi
