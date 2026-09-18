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

falhou=0
for alvo in "${CS_TARGETS[@]}"; do
    url="${alvo%%|*}"
    token="${alvo#*|}"
    echo "Enviando som de \"$CS_AMIGO\" para $url ..."
    if curl -sf --max-time 30 -X POST "$url/upload" \
        -H "X-Secreto: $token" \
        -F "amigo=$CS_AMIGO" \
        -F "som=@$ARC"; then
        echo "  ok ($url)"
    else
        echo "  falha em $url. Confere IP/porta/firewall e o secreto." >&2
        falhou=1
    fi
done

if [[ "$falhou" -eq 0 ]]; then
    echo "Som atualizado em todos os PCs."
else
    exit 1
fi
