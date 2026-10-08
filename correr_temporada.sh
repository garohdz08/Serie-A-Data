#!/usr/bin/env bash
# Descarga + compara + commit, una jornada a la vez. Reanudable (descargar_jornada.py omite lo ya hecho).
# Uso: ./correr_temporada.sh [desde] [hasta]
cd "$(dirname "$0")" || exit 1
for n in $(seq "${1:-1}" "${2:-38}"); do
  j=$(printf '%02d' "$n")
  python3 descargar_jornada.py --jornada "$n"; rc=$?
  python3 comparar.py --jornada "$n"
  estado="completa"; [ "$rc" -ne 0 ] && estado="CON FALLOS de descarga (ver datos/fallos.csv)"
  git add datos
  git commit -q -m "Jornada $n Serie A 2025-26: ESPN + Sofascore ($estado)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MoyBzk7RLtqcSegXc1YKUz" && echo "commit J$j: $estado"
done
