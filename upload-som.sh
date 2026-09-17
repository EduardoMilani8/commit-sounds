#!/usr/bin/env bash
set -euo pipefail

ARC="${1:-}"
if [[ -z "$ARC" ]]; then
    echo "uso: $0 /caminho/para/som.{mp3,wav,ogg,opus,flac,m4a,aac}" >&2
    exit 1
fi
if [[ ! -f "$ARC" ]]; then
    echo "arquivo nao encontrado: $ARC" >&2
    exit 1
fi

CONF="${CONF:-$HOME/.git-hooks/hook-config.sh}"
if [[ ! -f "$CONF" ]]; then
    echo "nao achei $CONF. Rode antes: bash install-hook.sh" >&2
    exit 1
fi
# shellcheck disable=SC1090
source "$CONF"

if [[ -z "${CS_AMIGO:-}" ]]; then
    echo "faltou CS_AMIGO em $CONF" >&2
    exit 1
fi
if [[ ! -v CS_TARGETS ]] || [[ ${#CS_TARGETS[@]} -eq 0 ]]; then
    echo "faltou CS_TARGETS em $CONF" >&2
    exit 1
fi

ALVO="${CS_TARGETS[0]}"
URL="${ALVO%%|*}"
TOKEN="${ALVO#*|}"

echo "Enviando som de \"$CS_AMIGO\" para $URL ..."
if curl -sf --max-time 30 -X POST "$URL/upload" \
    -H "X-Secreto: $TOKEN" \
    -F "amigo=$CS_AMIGO" \
    -F "som=@$ARC"; then
    echo "Ok! Som atualizado."
else
    echo "Falha no upload. Confere IP/porta/firewall e o secreto." >&2
    exit 1
fi