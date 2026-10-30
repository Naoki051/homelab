#!/data/data/com.termux/files/usr/bin/env bash
# ==============================================================================
# Script: wifi-watchdog.sh
# Objetivo: Keepalive e monitoramento da interface Wi-Fi no Redmi Note 9S.
# Mantém tráfego leve periódico para evitar suspensão agressiva da placa de rede.
# ==============================================================================

set -euo pipefail

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Descobrir IP do Gateway local
GATEWAY_IP=$(ip route show default 2>/dev/null | awk '/default/ {print $3}' || echo "1.1.1.1")

# Executa 2 pings rápidos com timeout de 2 segundos
if ping -c 2 -W 2 "$GATEWAY_IP" > /dev/null 2>&1; then
    # Conexão saudável (não polui o log a menos que desejado)
    exit 0
else
    echo "[$TIMESTAMP] [AVISO] Falha ao responder ping para o Gateway ($GATEWAY_IP). Tentando ping externo (1.1.1.1)..."
    if ! ping -c 2 -W 3 "1.1.1.1" > /dev/null 2>&1; then
        echo "[$TIMESTAMP] [ALERTA] Conexão com a rede local e internet perdida!"
    else
        echo "[$TIMESTAMP] [OK] Conectividade com a internet preservada."
    fi
fi
