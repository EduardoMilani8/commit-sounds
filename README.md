# commit-sounds 🎵

Toque um som no PC dos seus amigos quando você der `git push` — e ouça
os deles no seu. Funciona só na **LAN** (mesma rede Wi-Fi).

Acabou de fazer um push? Todo mundo que te configurou ouve o **seu** som.
Sem pip/apt-get pra instalar: Python stdlib + `curl` + git.

---

## Por que são 2 coisas?

O sistema tem dois papéis, e cada pessoa pode ter um ou os dois:

| Quem roda | Preciso de | Servidor | Instala com |
|-----------|-----------|----------|-------------|
| **Quem OUVE** os pushes dos outros | `listener.py` na porta 8080 | Este PC (seu) | `install-listener.sh` |
| **Quem AVISA** os outros (dá push) | hook `pre-push` + curl | PC do outro | `install-hook.sh` |

Igual WhatsApp: você **ouve** só quem você configurou, e quem **assina**
seu som é quem configura o seu PC. Pra **ouvirem um ao outro**, os dois
rodam os dois scripts.

---

## 🚀 Fluxo 1 — PARA VOCÊ (primeira vez)

Objetivo: **seu PC toca o som do seu amigo quando ele der push**, e
**você avisa o PC dele quando der push**. Os dois ficam funcionando.

> Faça no seu PC, com um terminal aberto em `~/commit-sounds`.

1. **Instale o "ouvidor" (seu PC toca sons):**
   ```bash
   cd ~/commit-sounds
   bash install-listener.sh
   ```
   Ele instala o `listener.py` em `~/.commit-sounds`, sobe como serviço
   systemd (volta no login) e imprime 3 coisas:
   - seu **IP** (ex: `http://192.168.0.15:8080`)
   - seu **SECRETO** (ex: `4f1a...`)
   - o caminho dos seus sons (`~/.commit-sounds/sounds/`)

2. **Libere a porta 8080 no firewall** (rodar no seu PC):
   ```bash
   sudo ufw allow 8080/tcp            # se usa ufw
   # ou firewalld:
   sudo firewall-cmd --add-port=8080/tcp --permanent && sudo firewall-cmd --reload
   ```

3. **Mande pro seu amigo** estes 4 dados (pode ser por WhatsApp):
   - o seu IP/URL (`http://SEU_IP:8080`)
   - o seu SECRETO
   - o **seu** apelido (ex: `Veplex`) — é o som que vai ficar te representando
   - esta mensagem: *"roda `bash install-hook.sh`, cola meu IP e secreto, e depois `bash upload-som.sh <arquivo.mp3>`"*

4. **Você avisa o PC do amigo** (quando ele der os dados dele pra você):
   ```bash
   bash install-hook.sh
   ```
   Responde as perguntas:
   - *Seu apelido:* o SEU nome (ex: `Veplex`)
   - *IP/URL:* o IP que o seu **amigo** te mandou
   - *Secreto:* o secreto que o **seu amigo** te mandou
   - *Adicionar outro PC?* `s` se quiser tocar em mais pessoas, `N` pra fechar

5. **Envie seu som** (fica salvo no PC do amigo, uma vez só):
   ```bash
   bash upload-som.sh /caminho/para/som.mp3
   ```

6. **Teste junto com o amigo:** você faz um push de qualquer repo →
   o PC dele toca o seu som. Ele faz um push → o seu PC toca o som dele.

---

## 📲 Fluxo 2 — PARA O SEU AMIGO (primeira vez)

Mande isso pra ele assim que ele perguntar "como configuro?". Ele faz
no **PC dele**, com o projeto `commit-sounds` na máquina dele.

1. **Instale o "ouvidor" (você também quer ouvir os pushes dele):**
   ```bash
   cd ~/commit-sounds
   bash install-listener.sh
   ```
   Anota o **IP** e o **SECRETO** que aparecerem — você vai mandar pro seu amigo.

2. **Libere a porta 8080:**
   ```bash
   sudo ufw allow 8080/tcp
   ```

3. **Configure pra ouvir o seu amigo** (o script `install-hook.sh` já
   vem no pacote que seu amigo te mandou, ou baixando o `commit-sounds`):
   ```bash
   bash install-hook.sh
   ```
   Responde:
   - *Seu apelido:* seu NOME
   - *IP/URL:* o IP que **seu amigo** te passou
   - *Secreto:* o secreto que **seu amigo** te passou

4. **Envie seu som pro PC dele:**
   ```bash
   bash upload-som.sh /caminho/para/som.mp3
   ```

5. **Mande pro seu amigo** o SEU IP + SEU SECRETO, pra ele fazer o
   passo 4 do Fluxo 1 (instalar o hook apontando pra você e enviar o som dele).

6. **Teste:** um push qualquer seu → o PC do seu amigo toca. Push dele → o seu toca.

> Agora os dois se ouvem: cada um tem o listener do seu jeito e o hook
> apontando pro outro. Próximos amigos é só repetir o Fluxo 1, passo 4.

---

## Como funciona por baixo

```
SEU AMIGO (dá o push)                   VOCÊ (ouve)
─────────────────────                    ─────────────────
git push
   │
   ▼
~/.git-hooks/pre-push  ──curl──►  listener.py:8080
(global, roda em todo                 │
 repo dele)                           ▼
                                ~/.commit-sounds/sounds/SEU_AMIGO.mp3
                                      │
                                      ▼
                          pw-play / paplay / aplay / ffplay  → 🔊 fone
```

- **`/upload`** — o amigo manda o arquivo de som; vira
  `~/.commit-sounds/sounds/<apelido>.<ext>`. Reenviar troca o som.
- **`/play`** — o hook avisa "tocou push do <apelido>"; o listener procura
  o som dele e reproduz em processo separado (não trava nada).
- **Segredo** — todo request precisa do **SECRETO**. Qualquer PC da sua
  rede sem o segredo recebe `403`. O segredo fica em
  `~/.commit-sounds/config.json` (seu) e `~/.git-hooks/hook-config.sh` (amigo).
- **Player** — usa o primeiro que existir: `pw-play` → `paplay` → `aplay` → `ffplay`.
  Se so tiver `aplay`, prefere arquivos **.wav** (ele não lê mp3).

---

## Configurações úteis

**Vários ouvintes de uma vez** (você quer que 3 PCs toquem seus pushes):
edite `~/.git-hooks/hook-config.sh` e adicione linhas em `CS_TARGETS`,
cada uma `URL|secreto`:
```bash
CS_TARGETS=(
  "http://192.168.0.15:8080|abc123..."
  "http://192.168.0.20:8080|def456..."
)
```
depois rode o `upload-som.sh` de novo (ele envia pro primeiro da lista;
se quiser mandar pra outro, use a variável):
```bash
CONF=~/.git-hooks/hook-config.sh bash upload-som.sh som.mp3
```

**Apelido único por ouvinte:** se dois amigos usarem o mesmo apelido no
seu PC, o segundo upload **sobrescreve** o primeiro.

**Som no seu próprio push:** se o seu hook apontar pro SEU IP+secret
(você tem listener e hook), você ouve o próprio push também.

**Mudar o som:** é só rodar `upload-som.sh` de novo. Não precisa mexer no hook.

---

## Testes rápidos

Sobe o listener na mão (sem systemd) pra testar:
```bash
python3 ~/.commit-sounds/listener.py
```

Dispara um som de amigo manualmente (substituir SECRETO e APELIDO):
```bash
curl -s -X POST http://127.0.0.1:8080/play \
  -H 'Content-Type: application/json' \
  -d '{"secreto":"SEU_SECRETO","amigo":"APELIDO_DO_AMIGO"}'
```
Aceita o secreto também no header `X-Secreto`.

---

## Problemas comuns

| Sintoma | Causa e solução |
|---------|-----------------|
| Nada toca no push | Amigo ainda não enviou o som → ele roda `upload-som.sh`. Ou o segredo/IP no `hook-config.sh` está errado. |
| Nada todo na LAN, mas funciona em `127.0.0.1` | Firewall bloqueando → libera a porta 8080 (passo 2 do Fluxo 1). |
| Toque trava o push | `curl` tem `--max-time 2` e `|| true`: no máximo espera 2s e nunca falha o push. |
| Sem sound (mas API responde 200) | Player de áudio? `which pw-play paplay aplay ffplay`. Se só tem `aplay`, usa `.wav`. |
| `curl` falha no amigo | Ele precisa do `curl` instalado (`apt install curl`), ou fora da sua LAN. |

---

## Limitações (de propósito)

- Só **LAN**: o amigo precisa alcançar o seu IP na mesma rede. Pra internet
  precisaria de encaminhamento de porta + IP do roteador.
- Hook toca mesmo se o push for **recusado** (pre-push roda antes de saber
  se o push vai dar certo). De propósito, pra manter simples.
- Segredo em texto plano no arquivo do link. Ok pra brincadeira entre amigos;
  se quiser mais segurança, dá pra gerar outro secreto (apaga o `config.json`
  e o listener gera um novo) e reenviar pra galera.