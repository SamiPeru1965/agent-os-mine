#!/bin/bash
# Ejecuta la retro semanal desde cron, viernes 18:00 America/Lima
# Notifica por Telegram vía hermes send al terminar (OK o FAIL)
set -u
export PATH="$HOME/.local/bin:$PATH"
[ -f "$HOME/.config/agent-os/env" ] && source "$HOME/.config/agent-os/env"

WEEK=$(date +%Y-W%V)
LOG_DIR="$HOME/agent-os/logs"
STATE_DIR="$HOME/agent-os/state"
mkdir -p "$LOG_DIR" "$STATE_DIR"
LOG="$LOG_DIR/retro-semanal-$WEEK.log"
cd "$HOME"

START_TS=$(date +%s)
START_ISO=$(date -Iseconds)
echo "=== $START_ISO INICIO retro semanal $WEEK ===" >> "$LOG"

timeout 900 claude -p --dangerously-skip-permissions < /dev/null \
  "Invoca el skill retro-semanal. Sobrescribe el retro de la semana en curso si ya existe. Al terminar imprime SOLO la ruta absoluta del archivo generado." \
  >> "$LOG" 2>&1
EXIT=$?
END_TS=$(date +%s)
END_ISO=$(date -Iseconds)
DURATION=$((END_TS - START_TS))
DUR_STR="$((DURATION/60))m $((DURATION%60))s"

# Escribir state file
if [ $EXIT -eq 0 ]; then
  echo "$END_ISO OK" > "$STATE_DIR/retro-semanal.last"
  echo "=== $END_ISO OK ===" >> "$LOG"
else
  echo "$END_ISO FAIL exit=$EXIT" > "$STATE_DIR/retro-semanal.last"
  echo "=== $END_ISO FAIL exit=$EXIT ===" >> "$LOG"
fi

# Auto-commit del vault (solo si retro salió OK)
if [ $EXIT -eq 0 ]; then
  ~/agent-os/bin/vault-committer.sh "retro semanal $WEEK" >> "$LOG" 2>&1 || echo "$(date -Iseconds) WARN vault-committer falló" >> "$LOG"
fi

# Notificar por Telegram (fail-soft: no rompe si hermes está caído)
if [ $EXIT -eq 0 ]; then
  MSG="✅ Retro $WEEK OK · $(date +"%Y-%m-%d %H:%M") · $DUR_STR
→ http://hp-z4:3100/actividad"
else
  LAST_LINES=$(tail -5 "$LOG" | sed "s/^/  /")
  MSG="🚨 Retro Agent OS FALLÓ
Semana: $WEEK
Hora: $(date +"%Y-%m-%d %H:%M")
Exit: $EXIT

Últimas 5 líneas del log:
$LAST_LINES

Log completo: $LOG
Pulso: http://hp-z4:3100/pulso"
fi

echo "$MSG" | hermes send -t telegram >> "$LOG" 2>&1 || echo "$(date -Iseconds) WARN hermes send falló, notificación no enviada" >> "$LOG"

exit $EXIT
