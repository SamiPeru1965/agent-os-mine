#!/bin/bash
# Auto-commit del vault Obsidian
# Uso: vault-committer.sh [contexto-opcional]
# Idempotente: si no hay cambios, sale silencioso con exit 0
set -u
VAULT="$HOME/obsidian-agentos"
cd "$VAULT" || { echo "$(date -Iseconds) vault-committer: vault no encontrado en $VAULT"; exit 1; }

# Si no hay cambios ni untracked files, salir OK sin commit
if git diff --quiet && git diff --staged --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
  exit 0
fi

git add -A

# Generar mensaje: contexto (si viene) + carpetas cambiadas
FOLDERS=$(git diff --staged --name-only | awk -F/ '{print $1}' | sort -u | tr '\n' ',' | sed 's/,$//')
if [ -n "${1:-}" ]; then
  MSG="$1 · $FOLDERS · $(date +%Y-%m-%d\ %H:%M)"
else
  MSG="auto-commit · $FOLDERS · $(date +%Y-%m-%d\ %H:%M)"
fi

if git commit -m "$MSG" > /dev/null 2>&1; then
  echo "$(date -Iseconds) vault-committer OK: $MSG"
else
  echo "$(date -Iseconds) vault-committer FAIL"
  exit 1
fi
