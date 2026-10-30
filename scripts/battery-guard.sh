#!/data/data/com.termux/files/usr/bin/env bash
# ==============================================================================
# Script: battery-guard.sh
# Objetivo: Monitorar nível e temperatura da bateria do Redmi Note 9S.
# Cicla a carga entre 30% e 80% para preservar a química da bateria em operação 24/7.
# Dispara alertas ou webhooks para acionar tomadas inteligentes (Sonoff, Tuya, etc).
# ==============================================================================

set -euo pipefail

# ==================== CONFIGURAÇÃO DE LIMITES ====================
MAX_PERCENT=80       # Desligar carregamento ao atingir este nível
MIN_PERCENT=30       # Ligar carregamento ao cair abaixo deste nível
CRITICAL_TEMP=42.0   # Temperatura em Celsius para alerta crítico

# ==================== CONFIGURAÇÃO DE WEBHOOKS (OPCIONAL) ========
# Exemplo com Home Assistant, Tuya Webhook, ou ntfy.sh
# Deixe vazio caso queira apenas registro em log / notificação local.
WEBHOOK_TURN_OFF_URL="${WEBHOOK_TURN_OFF_URL:-}"
WEBHOOK_TURN_ON_URL="${WEBHOOK_TURN_ON_URL:-}"
ALERT_NTFY_TOPIC="${ALERT_NTFY_TOPIC:-}" # Ex: https://ntfy.sh/meu-homelab-note9s

# =================================================================

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Verificar se termux-battery-status está disponível
if ! command -v termux-battery-status > /dev/null 2>&1; then
    echo "[$TIMESTAMP] [ERRO] termux-battery-status não encontrado. Instale o pacote 'termux-api'."
    exit 1
fi

# Ler status em JSON
BATTERY_JSON=$(termux-battery-status 2>/dev/null || echo "{}")

PERCENT=$(echo "$BATTERY_JSON" | jq -r '.percentage // empty')
TEMP=$(echo "$BATTERY_JSON" | jq -r '.temperature // empty')
STATUS=$(echo "$BATTERY_JSON" | jq -r '.status // empty')
PLUGGED=$(echo "$BATTERY_JSON" | jq -r '.plugged // empty')

if [ -z "$PERCENT" ] || [ -z "$TEMP" ]; then
    echo "[$TIMESTAMP] [ERRO] Falha ao ler dados da bateria do Termux:API."
    exit 1
fi

echo "[$TIMESTAMP] [INFO] Bateria: ${PERCENT}% | Temperatura: ${TEMP}°C | Estado: ${STATUS} | Plugado: ${PLUGGED}"

# 1. Alerta crítico de sobreaquecimento
IS_OVERHEAT=$(awk -v t="$TEMP" -v c="$CRITICAL_TEMP" 'BEGIN {print (t > c) ? 1 : 0}')
if [ "$IS_OVERHEAT" -eq 1 ]; then
    MSG="ALERTA CRÍTICO: Temperatura da bateria do Redmi Note 9S atingiu ${TEMP}°C!"
    echo "[$TIMESTAMP] [CRÍTICO] $MSG"
    if [ -n "$ALERT_NTFY_TOPIC" ]; then
        curl -s -d "$MSG" "$ALERT_NTFY_TOPIC" > /dev/null 2>&1 || true
    fi
fi

# 2. Desligar carga se atingiu o teto de 80% e estiver carregando
if [ "$PERCENT" -ge "$MAX_PERCENT" ] && [ "$STATUS" = "CHARGING" ]; then
    echo "[$TIMESTAMP] [AÇÃO] Bateria atingiu ${PERCENT}% (>= ${MAX_PERCENT}%). Necessário DESLIGAR a tomada."
    if [ -n "$WEBHOOK_TURN_OFF_URL" ]; then
        curl -s -X POST "$WEBHOOK_TURN_OFF_URL" > /dev/null 2>&1 || true
        echo "[$TIMESTAMP] [WEBHOOK] Webhook de desligamento disparado."
    fi
    if [ -n "$ALERT_NTFY_TOPIC" ]; then
        curl -s -d "Redmi Note 9S atingiu ${PERCENT}%. Desconecte o carregador." "$ALERT_NTFY_TOPIC" > /dev/null 2>&1 || true
    fi
fi

# 3. Ligar carga se caiu para o piso de 30% e não estiver carregando
if [ "$PERCENT" -le "$MIN_PERCENT" ] && [ "$STATUS" != "CHARGING" ]; then
    echo "[$TIMESTAMP] [AÇÃO] Bateria caiu para ${PERCENT}% (<= ${MIN_PERCENT}%). Necessário LIGAR a tomada."
    if [ -n "$WEBHOOK_TURN_ON_URL" ]; then
        curl -s -X POST "$WEBHOOK_TURN_ON_URL" > /dev/null 2>&1 || true
        echo "[$TIMESTAMP] [WEBHOOK] Webhook de acionamento disparado."
    fi
    if [ -n "$ALERT_NTFY_TOPIC" ]; then
        curl -s -d "Redmi Note 9S caiu para ${PERCENT}%. Conecte o carregador." "$ALERT_NTFY_TOPIC" > /dev/null 2>&1 || true
    fi
fi
