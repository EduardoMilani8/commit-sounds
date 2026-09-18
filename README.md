# commit-sounds

Você dá `git push` → o PC do seu amigo **toca o seu som**. Ele dá push →
o seu PC toca o som dele. Funciona na **LAN** (mesma rede Wi-Fi), sem
servidor central, usando só Python, `curl` e git — que todo Linux já tem.

---

## Índice

- [Como funciona](#como-funciona)
- [Pré-requisitos (nos dois PCs)](#pré-requisitos-nos-dois-pcs)
- [Passo a passo: primeiro contato entre 2 amigos](#passo-a-passo-primeiro-contato-entre-2-amigos)
- [Adicionando mais amigos](#adicionando-mais-amigos)
- [Escolhendo o som](#escolhendo-o-som)
- [Testando e diagnosticando](#testando-e-diagnosticando)
- [Referência rápida](#referência-rápida)
- [FAQ](#faq)
- [Depois de desligar ou religar](#depois-de-desligar-ou-religar)
- [Limitações (conscientes)](#limitações-conscientes)

---

## Como funciona

| Papel | Script | O que faz |
|-------|--------|-----------|
| **Ouvinte** | `install-listener.sh` | Vira um mini-servidor na porta 8080: recebe avisos de push e **toca o som** de quem avisou |
| **Avisador** | `install-hook.sh` | Instala um hook global de git que, **a cada push**, manda um aviso pro PC de quem ouve |

Na prática todo mundo é **os dois ao mesmo tempo**: você ouve os amigos
**e** avisa os amigos.

### O que você troca com cada amigo

Quando alguém vira ouvinte, o `install-listener.sh` imprime **2 valores**
— a "identidade" daquela pessoa na rede:

1. **URL** — ex: `http://192.168.0.15:8080`
2. **SECRETO** — uma senha da brincadeira, gerada na instalação

Você usa os valores **dele** no seu hook, e ele usa os **seus** no dele.

---

## Pré-requisitos (nos dois PCs)

- Linux com **Python 3**, **curl**, **git** e um player de áudio
  (`pw-play`/`paplay`/`aplay` — já vêm com PipeWire/PulseAudio/ALSA).
- Os dois PCs na **mesma rede** (LAN/Wi-Fi, IP do tipo `192.168.x.x`).

---

## Passo a passo: primeiro contato entre 2 amigos

Façam os 4 passos **nos dois PCs**. A ordem não importa; no fim os dois
estarão ouvindo o outro.

### Passo 1 · Instalar o ouvinte (nos dois PCs)

```bash
cd ~/commit-sounds
bash install-listener.sh
```

No final o script mostra algo assim:

```
Compartilhe com seus amigos:
  1) URL:   http://192.168.0.15:8080
  2) SECRETO: a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4
```

**Anote a URL e o SECRETO do SEU PC** e mande pro amigo — e peça a URL e
o SECRETO do PC dele.

Libere a porta no firewall (quem ouve precisa; no Ubuntu):

```bash
sudo ufw allow 8080/tcp
```

### Passo 2 · Apontar seu hook pro PC do amigo (nos dois PCs)

Cada um roda no próprio PC, informando **a URL e o SECRETO do outro**:

```bash
bash install-hook.sh
```

O script pergunta:

| Pergunta | O que responder |
|----------|-----------------|
| *Seu apelido* | como você fica registrado no PC do amigo (ex: `vini`) |
| *IP/URL do PC que toca o som* | a URL que **o amigo** te mandou |
| *Secreto* | o secreto que **o amigo** te mandou |
| *Adicionar outro PC?* | `N` — no primeiro contato |

Observações:

- O hook é **global**: vale pra qualquer repositório do seu PC, não só
  esse.
- Mudou alguma informação depois? Rode de novo o script, ou edite
  `~/.git-hooks/hook-config.sh` (ver [Referência](#referência-rápida)).

### Passo 3 · Enviar seu som (nos dois PCs)

```bash
bash upload-som.sh ~/Downloads/meu-som.wav
```

Registra **o seu apelido + o seu som** no PC do amigo. **O som precisa
existir lá antes do primeiro push** — senão o push chega, mas não toca
nada (resposta `404`).

Quer trocar o som? Rode o mesmo comando de novo.

### Passo 4 · Testar

```bash
cd ~/commit-sounds
./testar-som.sh
```

Se aparecer `OK recebeu (200)`, o PC do amigo tocou o seu som **agora**.
Qualquer outro resultado vem com a dica do que fazer (resumo na tabela em
[Testando e diagnosticando](#testando-e-diagnosticando)).

### Pronto

De agora em diante todo push seu toca o som no PC do amigo, e vice-versa.
Tudo fica salvo no disco: **pode reiniciar o PC**, o serviço `commit-sound`
sobe sozinho no login e o hook nunca "desconfigura".

---

## Adicionando mais amigos

1. O novo amigo faz o **Passo 1** e te manda URL + SECRETO.
2. No SEU PC, rode de novo `bash install-hook.sh` e, em *"Adicionar outro
   PC?"*, responda `s` com a URL + SECRETO dele. (Ou edite o array
   `CS_TARGETS` em `~/.git-hooks/hook-config.sh` — ver
   [Referência](#referência-rápida).)
3. `bash upload-som.sh ~/Downloads/meu-som.wav` — agora o script envia seu
   som pra **todos** os PCs configurados.
4. O novo amigo faz os passos 2 e 3 apontando pro SEU PC.

Cada amigo tem o próprio arquivo de som no seu ouvinte (guardado pelo
apelido) — dá pra receber avisos de **várias pessoas ao mesmo tempo**, cada
uma com seu som.

---

## Escolhendo o som

- **Prefira `.wav`**: toca em qualquer player (`pw-play`, `paplay`,
  `aplay`). É o formato mais seguro.
- **`.mp3` só toca se o PC que OUVE tiver `ffmpeg`** (vem o `ffplay`).
  Muitos `pw-play`/`paplay` não decodificam mp3 por padrão e falham **em
  silêncio** — a causa nº 1 de "não tocou nada".
- Formatos aceitos: `mp3, wav, ogg, opus, flac, m4a, aac`.
- O som é cortado em **4 segundos** automaticamente (mais curto toca
  inteiro).

Se o amigo só tiver mp3 e o PC dele não reproduzir:

```bash
sudo apt install -y ffmpeg
systemctl --user restart commit-sound
```

---

## Testando e diagnosticando

### Do seu PC — o aviso CHEGA no amigo e toca?

```bash
./testar-som.sh
```

| Resultado | Significado / o que fazer |
|-----------|---------------------------|
| `OK recebeu (200)` | Chegou e o amigo tentou tocar. Não ouviu? O áudio do PC dele é o problema → veja `--local` |
| `X NAO CONECTOU` | IP errado, PC desligado, fora da LAN ou firewall → quem ouve precisa de `sudo ufw allow 8080/tcp` |
| `HTTP 403` | SECRETO errado → confira `hook-config.sh` e o `config.json` do ouvinte |
| `HTTP 404` | Você ainda não enviou seu som pra lá → `bash upload-som.sh seu-som.wav` |
| `HTTP 500` | Chegou, mas o PC dele não conseguiu reproduzir → instale `ffmpeg` lá ou reenvie como `.wav` |

### Do seu PC — o ÁUDIO deste PC funciona?

```bash
./testar-som.sh --local
```

Tenta tocar o som salvo aqui com cada player até um funcionar. Serve pra
separar "não chegou" (rede) de "não toca" (áudio).

### Logs

- **Hook**: `~/.git-hooks/pre-push.log` — pra qual URL mandou e qual
  resposta o listener deu.
- **Ouvinte**: `journalctl --user -u commit-sound -n 30`.

---

## Referência rápida

### Comandos

| Comando | Para quê |
|---------|----------|
| `bash install-listener.sh` | Instala o ouvinte e mostra URL + SECRETO |
| `bash install-hook.sh` | Instala o hook que avisa a cada push |
| `bash upload-som.sh /caminho/som` | Manda seu som pra **todos** os PCs configurados |
| `./testar-som.sh` | Testa se o aviso chega e toca |
| `./testar-som.sh --local` | Testa só o áudio deste PC |

### Onde fica cada coisa

| Arquivo | O que é |
|---------|---------|
| `~/.commit-sounds/listener.py` | o servidor de som |
| `~/.commit-sounds/config.json` | porta + secreto do SEU ouvinte |
| `~/.commit-sounds/sounds/<apelido>.<ext>` | sons que os amigos te enviaram |
| `~/.git-hooks/hook-config.sh` | seu apelido + lista de PCs pra avisar |
| `~/.git-hooks/pre-push` | hook que dispara o aviso |
| `~/.git-hooks/pre-push.log` | histórico dos avisos |

### Configuração do hook (`~/.git-hooks/hook-config.sh`)

```bash
CS_AMIGO="vini"
CS_TARGETS=(
  "http://192.168.0.15:8080|secreto-do-amigo-1"
  "http://192.168.0.20:8080|secreto-do-amigo-2"
)
```

Uma linha por PC, no formato `URL|secreto`. A cada push, seu aviso vai pra
todos.

### Personalização

- **Duração do som**: `DURACAO_MAX` no topo do `listener.py` (depois de
  editar, reinicie: `systemctl --user restart commit-sound`).
- **Porta**: `"porta"` em `~/.commit-sounds/config.json`, reinicie como
  acima e avise os amigos da nova URL.
- **Pasta de sons**: `~/.commit-sounds/sounds` pode ser um link simbólico
  pro seu drive/OneDrive.

---

## FAQ

### "Rodei tudo e não ouço nada quando dou push"
1. Você já mandou seu som? (`bash upload-som.sh som.wav`)
2. `./testar-som.sh` — se der 200 e mesmo assim não tocar, o áudio do PC
   do amigo é o problema.
3. Confira `~/.git-hooks/pre-push.log` pra ver se o push disparou o aviso.

### "O teste diz 200 mas não ouviu nada"
A conexão chegou, mas o player falhou em silêncio. Causa mais comum:
**mp3 sem `ffplay`/ffmpeg no PC de quem ouve**. Resolva lá:

```bash
sudo apt install -y ffmpeg
systemctl --user restart commit-sound
```

Ou reenvie como `.wav`.

### "`install-hook.sh: command not found`"
Faltou o `bash` na frente. Rode sempre `bash install-hook.sh` (os scripts
não estão no `PATH`).

### "Só funciona aqui, não de outro PC na rede"
Firewall ou rede diferente. Quem ouve: `sudo ufw allow 8080/tcp`. Os dois
na **mesma** LAN (sem VPN ou roteador separado).

### "Como troco o som?"
`bash upload-som.sh novo-som.wav` de novo. Sobrescreve o anterior; não
precisa mexer em mais nada.

### "Dois amigos usam o mesmo apelido no meu PC"
O segundo upload sobrescreve o primeiro. Peça pra um deles trocar o
apelido (reedite `hook-config.sh` e reenvie o som).

### "Quero ouvir MEU próprio push no meu PC"
Aponte seu hook pro seu próprio PC (seu IP + seu secreto) e rode
`bash upload-som.sh som.wav` pra você mesmo.

### "O som é cortado no meio!"
De propósito: máximo de **4 segundos** por toque. Mude `DURACAO_MAX` no
`listener.py` se quiser outro valor.

### "Push up to date (não envia nada) não toca"
Correto, por design: o hook só dispara quando há branch/tag nova sendo
enviada. (E toca mesmo se o push for **recusado** — o aviso sai antes; é
uma escolha de simplicidade.)

### "Porta 8080 em uso"
Troque `"porta"` em `~/.commit-sounds/config.json`,
`systemctl --user restart commit-sound` e avise os amigos da nova porta.

### "`Failed to connect to bus` no systemctl"
Sessão de usuário incompleta (comum via SSH). Suba na mão:
`nohup python3 ~/.commit-sounds/listener.py &` (adicione no login).

### "Como removo o som de alguém?"
`rm ~/.commit-sounds/sounds/<apelido>.*`. A partir daí, o `/play` daquele
apelido responde `404`.

### "Qualquer um da rede pode fazer tocar?"
Não. Todo pedido precisa do **secreto** do ouvinte (fica no `config.json`
dele e no `hook-config.sh` de quem avisa; sem ele, `403`). Vazou ou mudou
de amigo? Apague `~/.commit-sounds/config.json`, rode
`bash install-listener.sh` de novo e reenvie o novo secreto.

---

## Depois de desligar ou religar

Nada precisa ser refeito: sons, `config.json` e `hook-config.sh` ficam no
disco, o serviço `commit-sound` é `enabled` e sobe **sozinho no login**.
Só 2 pontos de atenção:

1. O serviço sobe no **login** — se o PC fica parado na tela bloqueada, o
   serviço ainda não rodou. Opcional: `sudo loginctl enable-linger SEU_USUARIO`
   (só adianta pro servidor; o áudio ainda depende da sessão gráfica).
2. O **IP da LAN pode mudar** (DHCP). Duas saídas:
   - reserve um **IP fixo** pro PC no roteador (lease estático por MAC), ou
   - use o **hostname** no lugar do IP: `http://pc-do-vini.local:8080` —
     o mDNS/avahi resolve o nome mesmo com IP novo, e o listener já escuta
     em `0.0.0.0:8080` (todas as interfaces). É o jeito mais "à prova de
     futuro".

---

## Limitações (conscientes)

- Só **LAN** — pra internet precisaria de encaminhamento de porta no
  roteador.
- O aviso sai **antes** do push ser aceito (é um hook `pre-push`), então
  um push rejeitado ainda toca o som.
- Secreto em texto puro no arquivo local — ok pra brincadeira entre amigos,
  não use em rede aberta com estranhos.