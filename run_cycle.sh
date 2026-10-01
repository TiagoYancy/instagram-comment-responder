#!/usr/bin/env bash
# ============================================================================
#  Executa um ciclo completo: busca comentários novos, gera respostas,
#  aplica a política e (no modo auto) publica sozinho.
#
#  Use no cron:
#     */15 * * * * /home/hermes/instagram-responder/run_cycle.sh >> logs/cron.log 2>&1
# ============================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

mkdir -p logs

# Carrega credenciais (Hermes API server key para o LLM)
if [ -f /home/hermes/.hermes/.env ]; then
    set -a
    # shellcheck disable=SC1091
    . /home/hermes/.hermes/.env >/dev/null 2>&1 || true
    set +a
fi
export IG_LLM_API_KEY="${IG_LLM_API_KEY:-${API_SERVER_KEY:-}}"

STAMP="$(date '+%Y-%m-%d %H:%M:%S')"
echo "───────── $STAMP ─────────"

python3 -m ig_responder scan --posts "${IG_SCAN_POSTS:-10}" --comments "${IG_SCAN_COMMENTS:-50}"

echo "fila pendente:"
python3 -m ig_responder queue --limit 5 || true
echo
