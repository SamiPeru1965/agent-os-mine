#!/bin/bash
# Ejecuta el procesamiento de ideas nuevas de Notion
# Corre cada 30 min. Silencio si no hay ideas nuevas.
set -u
export PATH="$HOME/.local/bin:$PATH"
[ -f "$HOME/.config/agent-os/env" ] && source "$HOME/.config/agent-os/env"

LOG_DIR="$HOME/agent-os/logs"
STATE_DIR="$HOME/agent-os/state"
mkdir -p "$LOG_DIR" "$STATE_DIR"
LOG="$LOG_DIR/procesar-ideas-$(date +%Y-%m-%d).log"
cd "$HOME"

START_ISO=$(date -Iseconds)
echo "=== $START_ISO INICIO procesar-ideas ===" >> "$LOG"

timeout 300 python3 ~/agent-os/bin/procesar-ideas.py >> "$LOG" 2>&1
EXIT=$?
END_ISO=$(date -Iseconds)

if [ $EXIT -eq 0 ]; then
  echo "$END_ISO OK" > "$STATE_DIR/procesar-ideas.last"
  echo "=== $END_ISO OK ===" >> "$LOG"
elif [ $EXIT -eq 2 ] || [ $EXIT -eq 3 ]; then
  # Solo notifica por Telegram si es fallo grave (auth/red), no si es una idea rota
  echo "$END_ISO FAIL exit=$EXIT" > "$STATE_DIR/procesar-ideas.last"
  echo "=== $END_ISO FAIL exit=$EXIT ===" >> "$LOG"
  echo "🚨 procesar-ideas FALLÓ (exit=$EXIT). Ver: $LOG" | hermes send -t telegram >> "$LOG" 2>&1 || true
else
  echo "$END_ISO FAIL exit=$EXIT" > "$STATE_DIR/procesar-ideas.last"
  echo "=== $END_ISO FAIL exit=$EXIT ===" >> "$LOG"
fi

exit $EXIT
