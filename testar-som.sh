#!/usr/bin/env bash
# Testa se o seu aviso de push chega no PC do amigo e toca o som.
#
# uso:
#   ./testar-som.sh                          usa a config do hook (~/.git-hooks/hook-config.sh)
#   ./testar-som.sh URL SECRETO APELIDO      testa um PC específico na mão
set -u

CONF="${CS_CONF:-$HOME/.git-hooks/hook-config.sh}"
URL="${1:-}"
TOKEN="${2:-}"
AMIGO="${3:-}"

if [[ -n "$URL" && -n "$TOKEN" && -n "$AMIGO" ]]; then
    TARGETS=("${URL}|${TOKEN}")
else
    if [[ ! -f "$CONF" ]]; then
        echo "nao achei $CONF e nao passei URL/SECRETO/APELIDO." >&2
        echo "uso: $0 [URL SECRETO APELIDO]" >&2
        exit 1
    fi
    # shellcheck disable=SC1090
    source "$CONF"
    AMIGO="${CS_AMIGO:-}"
    if [[ -z "$AMIGO" ]]; then
        echo "faltou CS_AMIGO em $CONF" >&2
        exit 1
    fi
    TARGETS=("${CS_TARGETS[@]:-}")
    if [[ ${#TARGETS[@]} -eq 0 ]]; then
        echo "faltou CS_TARGETS em $CONF" >&2
        exit 1
    fi
fi

echo "== teste de som do push (APELIDO: $AMIGO) =="
falhou=0

for alvo in "${TARGETS[@]}"; do
    url="${alvo%%|*}"
    token="${alvo#*|}"
    echo ""
    echo "-- $url"
    if ! ping -c 1 -W 2 "$(echo "$url" | sed -E 's|^https?://||; s|:[0-9]+/?$||')" >/dev/null 2>&1; then
        echo "   ! PC do amigo nao responde ping (mesma rede LAN?)."
    fi

    dados="{\"secreto\":\"$token\",\"amigo\":\"$AMIGO\"}"
    saida="$(curl -s --max-time 5 -w $'\n%{http_code}' -X POST "$url/play" \
        -H 'Content-Type: application/json' -d "$dados" 2>&1)"
    codigo="$(printf '%s' "$saida" | tail -n1)"
    corpo="$(printf '%s' "$saida" | sed '$d')"

    if [[ -z "$codigo" || "$codigo" == "000" ]]; then
        echo "   X NAO CONECTOU: $url"
        echo "     causas: PC do amigo desligado? fora da LAN? firewall?"
        echo "     confira: ping; nc -vz IP 8080; ele precisa abrir a porta 8080."
        falhou=1
    elif [[ "$codigo" == "200" ]]; then
        echo "   OK recebeu ($corpo)"
        echo "     o som DEVE estar tocando agora (confere volume/fone)."
        echo "     se nao tocou, no PC dele os players sao: pw-play/paplay/aplay/ffplay"
    else
        echo "   X resposta HTTP $codigo: $corpo"
        case "$codigo" in
            403) echo "     secreto errado -> confere o token no hook-config.sh e no config.json dele." ;;
            404) echo "     voce ainda NAO enviou seu som pra ele -> rode: bash upload-som.sh SEU_SOM.mp3" ;;
            400) echo "     apelido invalido (use letras, numeros, _ . -)." ;;
            500) echo "     chegou, mas o PC dele nao tem player de audio." ;;
        esac
        falhou=1
    fi
done

echo ""
if [[ "$falhou" -eq 0 ]]; then
    echo "Tudo certo! Seu push chegou no amigo." 
else
    echo "Algum problema acima. Pra testar o caminho inverso"
    echo "(o SOUND chegar em voce), rode o MESMO script no PC do seu amigo."
fi
exit "$falhou"