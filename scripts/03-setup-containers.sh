#!/data/data/com.termux/files/usr/bin/env bash
# ==============================================================================
# Script: 03-setup-containers.sh
# Objetivo: Provisionar Containers Sem Root no Redmi Note 9S
# Permite escolher entre udocker (via proot-distro Debian) ou QEMU ARM64 (Docker real)
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[AVISO]${NC} $1"; }

install_udocker() {
    log_info "Instalando Debian no proot-distro para suportar o udocker..."
    pkg install -y proot-distro
    if ! proot-distro list | grep -q "debian (installed)"; then
        proot-distro install debian
    fi

    log_info "Configurando udocker dentro do ambiente Debian..."
    proot-distro login debian -- bash -c '
        apt update && apt install -y python3 curl tar git
        if [ ! -f /usr/local/bin/udocker ]; then
            curl -sSL https://raw.githubusercontent.com/indigo-dc/udocker/master/udocker.py -o /usr/local/bin/udocker
            chmod +x /usr/local/bin/udocker
            udocker install
        fi
    '
    
    # Criar atalho no Termux para invocar o udocker diretamente
    cat << 'EOF' > "$PREFIX/bin/udocker-run"
#!/data/data/com.termux/files/usr/bin/sh
proot-distro login debian -- udocker "$@"
EOF
    chmod +x "$PREFIX/bin/udocker-run"

    log_success "udocker instalado com sucesso! Use o comando 'udocker-run' diretamente no Termux."
}

install_qemu_docker() {
    log_info "Instalando QEMU e ferramentas de virtualização..."
    pkg install -y qemu-system-aarch64 qemu-utils wget

    VM_DIR="$HOME/alpine-vm"
    mkdir -p "$VM_DIR"
    cd "$VM_DIR"

    DISK_FILE="$VM_DIR/alpine-disk.qcow2"
    if [ ! -f "$DISK_FILE" ]; then
        log_info "Criando disco virtual de 15GB em formato qcow2..."
        qemu-img create -f qcow2 "$DISK_FILE" 15G
    fi

    ISO_FILE="$VM_DIR/alpine-virt-3.20.0-aarch64.iso"
    if [ ! -f "$ISO_FILE" ]; then
        log_info "Baixando ISO Virt do Alpine Linux ARM64..."
        wget -c https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/alpine-virt-3.20.0-aarch64.iso -O "$ISO_FILE"
    fi

    # Criar script de inicialização padrão da VM (com redirecionamento de portas)
    cat << 'EOF' > "$VM_DIR/start-vm.sh"
#!/data/data/com.termux/files/usr/bin/sh
cd ~/alpine-vm
echo "Iniciando Alpine Linux ARM64 VM (Docker Host)..."
echo "Portas mapeadas:"
echo "  - SSH VM   : localhost:2222 -> :22"
echo "  - Web App 1: localhost:8088 -> :80"
echo "  - Web App 2: localhost:9000 -> :9000"
echo "Para sair do console do QEMU: pressione Ctrl+A e depois X"

qemu-system-aarch64 \
  -M virt -cpu cortex-a57 -smp 4 -m 2048M \
  -drive file=alpine-disk.qcow2,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::8088-:80,hostfwd=tcp::9000-:9000 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
EOF
    chmod +x "$VM_DIR/start-vm.sh"

    # Criar script de instalação inicial com ISO anexada
    cat << 'EOF' > "$VM_DIR/install-vm.sh"
#!/data/data/com.termux/files/usr/bin/sh
cd ~/alpine-vm
echo "Iniciando instalador do Alpine Linux a partir da ISO..."
echo "Ao carregar o prompt 'localhost login:', digite 'root' e execute: setup-alpine"
qemu-system-aarch64 \
  -M virt -cpu cortex-a57 -smp 4 -m 2048M \
  -drive file=alpine-disk.qcow2,if=virtio,format=qcow2 \
  -cdrom alpine-virt-3.20.0-aarch64.iso -boot d \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
EOF
    chmod +x "$VM_DIR/install-vm.sh"

    log_success "Ambiente QEMU Alpine preparado em ~/alpine-vm!"
    log_info "Para realizar a instalação inicial: execute ~/alpine-vm/install-vm.sh"
    log_info "Após instalado, para iniciar a VM no dia a dia: execute ~/alpine-vm/start-vm.sh"
}

# Verificação de argumentos ou menu
CHOICE="${1:-}"

if [ -z "$CHOICE" ]; then
    echo -e "${BLUE}Escolha o ambiente de containers a configurar:${NC}"
    echo "1) udocker (Leve, sem VM, executa imagens OCI via PRoot)"
    echo "2) QEMU + Alpine Linux (VM com Docker Daemon e Docker Compose nativos)"
    echo "3) Instalar ambos"
    echo "q) Cancelar"
    read -rp "Opção [1-3]: " CHOICE
fi

case "$CHOICE" in
    1)
        install_udocker
        ;;
    2)
        install_qemu_docker
        ;;
    3)
        install_udocker
        install_qemu_docker
        ;;
    *)
        log_warn "Operação cancelada ou inválida."
        exit 0
        ;;
esac
