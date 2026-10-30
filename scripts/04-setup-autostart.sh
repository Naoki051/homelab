#!/data/data/com.termux/files/usr/bin/env bash
# ==============================================================================
# Script: 04-setup-autostart.sh
# Objetivo: Configurar Inicialização Automática no Boot (Termux:Boot)
# Garante que Wake-lock, SSH, Cron, Bancos e PM2 subam sozinhos após reinicialização.
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[AVISO]${NC} $1"; }

BOOT_DIR="$HOME/.termux/boot"
BOOT_SCRIPT="$BOOT_DIR/start-homelab.sh"

log_info "Criando diretório do Termux:Boot em $BOOT_DIR..."
mkdir -p "$BOOT_DIR"

log_info "Gerando script de autostart em $BOOT_SCRIPT..."
cat << 'EOF' > "$BOOT_SCRIPT"
#!/data/data/com.termux/files/usr/bin/sh
# Script disparado automaticamente pelo app Termux:Boot na inicialização do celular

# 1. Manter CPU ativa mesmo com tela desligada
termux-wake-lock

# 2. Iniciar servidor OpenSSH
if ! pgrep -x "sshd" > /dev/null 2>&1; then
    sshd
fi

# 3. Iniciar agendador de tarefas Cron
if ! pgrep -x "crond" > /dev/null 2>&1; then
    crond
fi

# 4. Iniciar PostgreSQL se instalado
if command -v pg_ctl > /dev/null 2>&1 && [ -d "$PREFIX/var/lib/postgresql" ]; then
    pg_ctl -D "$PREFIX/var/lib/postgresql" -l "$PREFIX/var/log/postgresql.log" start > /dev/null 2>&1 || true
fi

# 5. Iniciar Caddy se configurado
if command -v caddy > /dev/null 2>&1 && [ -f "$PREFIX/etc/caddy/Caddyfile" ]; then
    caddy start --config "$PREFIX/etc/caddy/Caddyfile" > /dev/null 2>&1 || true
fi

# 6. Restaurar processos salvos no PM2
if command -v pm2 > /dev/null 2>&1; then
    pm2 resurrect > /dev/null 2>&1 || true
fi

# 7. (Opcional) Descomente abaixo se desejar iniciar a VM Alpine Docker no boot
# if [ -f "$HOME/alpine-vm/start-vm.sh" ]; then
#     nohup "$HOME/alpine-vm/start-vm.sh" > "$HOME/alpine-vm/vm.log" 2>&1 &
# fi
EOF

chmod +x "$BOOT_SCRIPT"
log_success "Script de boot configurado com permissão de execução."

echo ""
echo -e "${GREEN}================================================================${NC}"
echo -e "${GREEN}          AUTOSTART CONFIGURADO COM SUCESSO!                    ${NC}"
echo -e "${GREEN}================================================================${NC}"
echo -e "Script gerado em: ${YELLOW}$BOOT_SCRIPT${NC}"
echo ""
echo -e "Lembre-se:"
echo -e "1. Abra o app ${BLUE}Termux:Boot${NC} pelo menos uma vez no celular."
echo -e "2. Confirme que a opção ${YELLOW}Início Automático${NC} está ativada na MIUI."
echo -e "${GREEN}================================================================${NC}"
