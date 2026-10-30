#!/data/data/com.termux/files/usr/bin/env bash
# ==============================================================================
# Script: 01-bootstrap-termux.sh
# Objetivo: Bootstrap inicial do Termux no Redmi Note 9S (Sem Root)
# Instala OpenSSH, utilitários essenciais, ativa wake-lock e inicia o SSH.
# ==============================================================================

set -euo pipefail

# Cores para saída no terminal
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[AVISO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERRO]${NC} $1"
}

log_info "Iniciando bootstrap do ambiente Termux para Homelab..."

# 1. Verificar se está rodando no Termux
if [ -z "${PREFIX:-}" ]; then
    log_warn "A variável \$PREFIX não está definida. Verifique se este script está sendo executado no Termux."
fi

# 2. Solicitar permissões de armazenamento do Android se necessário
if [ ! -d "$HOME/storage" ]; then
    log_info "Configurando acesso ao armazenamento compartilhado..."
    termux-setup-storage || true
    log_success "Permissão de armazenamento solicitada."
fi

# 3. Ativar wake-lock para impedir o Android de suspender a CPU
log_info "Ativando wake-lock (impede suspensão da CPU)..."
if command -v termux-wake-lock > /dev/null 2>&1; then
    termux-wake-lock
    log_success "Wake-lock ativado com sucesso."
else
    log_warn "termux-wake-lock não encontrado. Instale o pacote termux-tools."
fi

# 4. Atualizar repositórios e pacotes base
log_info "Atualizando pacotes do sistema (pkg update)..."
pkg update -y
pkg upgrade -y

# 5. Instalar pacotes essenciais
ESSENTIAL_PKGS=(
    openssh
    termux-api
    termux-services
    git
    curl
    wget
    jq
    htop
    tmux
    cronie
    proot-distro
    tar
    unzip
)

log_info "Instalando pacotes essenciais: ${ESSENTIAL_PKGS[*]}..."
pkg install -y "${ESSENTIAL_PKGS[@]}"
log_success "Pacotes essenciais instalados com sucesso."

# 6. Configurar e Iniciar OpenSSH na porta 8022
log_info "Configurando OpenSSH Server..."
if [ ! -d "$HOME/.ssh" ]; then
    mkdir -p "$HOME/.ssh"
    chmod 700 "$HOME/.ssh"
fi

if [ ! -f "$HOME/.ssh/authorized_keys" ]; then
    touch "$HOME/.ssh/authorized_keys"
    chmod 600 "$HOME/.ssh/authorized_keys"
fi

# Iniciar o daemon SSH se não estiver em execução
if ! pgrep -x "sshd" > /dev/null 2>&1; then
    log_info "Iniciando sshd na porta 8022..."
    sshd
    log_success "Serviço SSH iniciado."
else
    log_info "O serviço sshd já está em execução."
fi

# 7. Exibir informações de rede para conexão
IP_LOCAL=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $7}' || echo "Não detectado")

echo ""
echo -e "${GREEN}================================================================${NC}"
echo -e "${GREEN}       BOOTSTRAP CONCLUÍDO COM SUCESSO NO REDMI NOTE 9S!        ${NC}"
echo -e "${GREEN}================================================================${NC}"
echo -e "Endereço IP Local : ${YELLOW}${IP_LOCAL}${NC}"
echo -e "Porta SSH         : ${YELLOW}8022${NC}"
echo -e "Comando para SSH  : ${BLUE}ssh -p 8022 $(whoami)@${IP_LOCAL}${NC}"
echo ""
echo -e "Lembre-se de definir uma senha segura executando: ${YELLOW}passwd${NC}"
echo -e "Ou cadastre sua chave pública SSH em: ${YELLOW}~/.ssh/authorized_keys${NC}"
echo -e "${GREEN}================================================================${NC}"
