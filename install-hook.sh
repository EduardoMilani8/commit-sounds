#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HOOKS="$HOME/.git-hooks"

mkdir -p "$HOOKS"
install -m 755 "$SCRIPTS_DIR/hook/pre-push" "$HOOKS/pre-push"
git config --global core.hooksPath "$HOOKS" || true

echo "== commit-sounds: instalacao do hook (no PC de quem da push) =="
read -r -p "Seu apelido na brincadeira (ex: Fabio): " AMIGO

TARGETS=()
while :; do
    read -r -p "IP/URL do PC que toca o som (ex: http://192.168.0.10:8080): " URL
    read -r -p "Secreto que essa pessoa te passou: " TOKEN
    TARGETS+=("${URL}|${TOKEN}")
    read -r -p "Adicionar outro PC que tambem deve tocar? [s/N] " MAIS
    [[ "$MAIS" =~ ^[sSyY] ]] || break
done

CONF="$HOOKS/hook-config.sh"
{
    printf 'CS_AMIGO="%s"\n' "$AMIGO"
    printf '\n'
    printf 'CS_TARGETS=(\n'
    for alvo in "${TARGETS[@]}"; do
        printf '  "%s"\n' "$alvo"
    done
    printf ')\n'
} > "$CONF"
chmod 600 "$CONF"

echo ""
echo "Pronto! Hooks globais instalados em $HOOKS."
echo "Todo push seu (branch ou tag) vai tocar o som nos PCs configurados."
echo ""
echo "Falta mandar seu som:  bash $SCRIPTS_DIR/upload-som.sh /caminho/som.mp3"