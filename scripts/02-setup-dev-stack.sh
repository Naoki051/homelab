#!/data/data/com.termux/files/usr/bin/env bash
# ==============================================================================
# Script: 02-setup-dev-stack.sh
# Objetivo: Instalar Stack de Desenvolvimento, Bancos de Dados e Proxy Reverso
# (Python, Node.js LTS, PostgreSQL, SQLite, Caddy, PM2)
# ==============================================================================

set -euo pipefail

# Cores
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[AVISO]${NC} $1"; }

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"

log_info "Instalando compiladores e ferramentas de compilação..."
pkg install -y build-essential clang make pkg-config

# 1. Python 3
log_info "Instalando Python 3 e pip..."
pkg install -y python python-pip
python -m pip install --upgrade pip

# 2. Node.js LTS e PM2
log_info "Instalando Node.js LTS e gerenciadores..."
pkg install -y nodejs-lts
npm install -g pnpm pm2

# 3. Bancos de Dados (PostgreSQL & SQLite)
log_info "Instalando PostgreSQL e SQLite..."
pkg install -y postgresql sqlite

PG_DATA_DIR="$PREFIX/var/lib/postgresql"
if [ ! -d "$PG_DATA_DIR" ]; then
    log_info "Inicializando cluster do PostgreSQL em $PG_DATA_DIR..."
    mkdir -p "$PG_DATA_DIR"
    initdb -D "$PG_DATA_DIR"
    log_success "PostgreSQL cluster inicializado com sucesso."
else
    log_info "Cluster do PostgreSQL já existe em $PG_DATA_DIR."
fi

# 4. Proxy Reverso Caddy
log_info "Instalando servidor web Caddy..."
pkg install -y caddy

CADDY_DIR="$PREFIX/etc/caddy"
CADDYFILE="$CADDY_DIR/Caddyfile"
mkdir -p "$CADDY_DIR"
mkdir -p "$HOME/www"

if [ ! -f "$CADDYFILE" ]; then
    log_info "Criando Caddyfile padrão na porta 8080..."
    cat << 'EOF' > "$CADDYFILE"
:8080 {
    root * /data/data/com.termux/files/home/www
    file_server

    # Exemplo: Proxy para API Node.js na porta 3000
    # handle_path /api/* {
    #     reverse_proxy localhost:3000
    # }

    # Exemplo: Proxy para API Python na porta 8000
    # handle_path /py/* {
    #     reverse_proxy localhost:8000
    # }
}
EOF
    cat << 'EOF' > "$HOME/www/index.html"
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Homelab Redmi Note 9S</title>
    <style>
        body { font-family: sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding-top: 50px; }
        .card { background: #1e293b; max-width: 500px; margin: 0 auto; padding: 25px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        h1 { color: #38bdf8; }
        .badge { background: #0284c7; padding: 4px 12px; border-radius: 9999px; font-weight: bold; }
    </style>
</head>
<body>
    <div class="card">
        <h1>Miniservidor Homelab</h1>
        <p><span class="badge">Redmi Note 9S Online</span></p>
        <p>Servidor web Caddy operando na porta 8080 via Termux.</p>
    </div>
</body>
</html>
EOF
    log_success "Página web de boas-vindas criada em ~/www/index.html."
fi

# 5. Configurar termux-services se disponível
if command -v sv-enable > /dev/null 2>&1; then
    log_info "Habilitando PostgreSQL no termux-services..."
    sv-enable postgresql || true
fi

echo ""
echo -e "${GREEN}================================================================${NC}"
echo -e "${GREEN}       STACK DEV E BANCOS INSTALADOS COM SUCESSO!               ${NC}"
echo -e "${GREEN}================================================================${NC}"
echo -e "Node.js    : $(node -v)"
echo -e "Python     : $(python --version)"
echo -e "PostgreSQL : Porta 5432 (iniciar: pg_ctl -D $PG_DATA_DIR start)"
echo -e "Caddy Web  : Porta 8080 (iniciar: caddy start --config $CADDYFILE)"
echo -e "PM2        : Ativo para monitorar processos Node/Python"
echo -e "${GREEN}================================================================${NC}"
