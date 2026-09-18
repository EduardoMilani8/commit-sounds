# commit-sounds

Você dá `git push` e o PC dos seus amigos **toca o seu som**. Quando eles
dão push, o seu PC toca o som deles. Funciona na **LAN** (mesma rede
Wi-Fi) e usa só ferramenta que todo Linux já tem: Python (stdlib) +
`curl` + git. **Nada de pip, nada de servidor central.**

---

## Como funciona (2 papéis)

| Papel | O que faz | Instala com | Roda onde |
|-------|-----------|-------------|-----------|
| **Quem OUVE** | Roda um servidor na porta 8080 que recebe o som dos outros e toca no fone | `install-listener.sh` | PC de quem quer ouvir |
| **Quem AVISA** | Hook de git que manda um aviso por `curl` quando dá push | `install-hook.sh` | PC de quem dá push |

Cada pessoa pode ser um, ou os dois. Pra **ouvirem um ao outro**, os dois
rodam os dois scripts (cada um na própria máquina).

---

## Rápido — os scripts que existem

| Script | Para quem | Efeito |
|--------|-----------|--------|
| `install-listener.sh` | Quem OUVE | instala o `listener.py`, gera seu **secreto**, sobe o serviço systemd no login e te mostra o IP |
| `install-hook.sh` | Quem AVISA | instala o hook global `~/.git-hooks/pre-push` e grava pra onde avisar |
| `upload-som.sh SEU_SOM` | Quem AVISA | envia o seu som pro PC de quem ouve (fica salvo lá) |
| `testar-som.sh` | Qualquer | testa se o seu aviso chega e toca (com `--local` testa só o áudio do PC) |

---

## Fluxo completo — os dois se ouvindo (primeira vez)

### Passo 1 — na SUA máquina (você quer ouvir os pushes dele)

```bash
cd ~/commit-sounds
bash install-listener.sh
```

O script imprime o seu **IP** (ex: `http://192.168.1.215:8080`) e o
**SECRETO** dele. Compartilhe os dois com seu amigo. Libere o firewall:

```bash
sudo ufw allow 8080/tcp
```

### Passo 2 — na máquina do SEU AMIGO (ele quer ouvir os seus)

Ele faz o mesmo Passo 1 no PC dele: roda `install-listener.sh`, libera o
firewall e te manda **o IP dele + o secreto dele**.

### Passo 3 — você configura o hook (pra ele receber o SEU push)

```bash
bash install-hook.sh
```

Responde:
- *Seu apelido*: seu nome (ex: `Edui`) — é como o SEU som fica registrado
  no PC dele.
- *IP/URL*: o IP que **ele** te mandou.
- *Secreto*: o secreto que **ele** te mandou.
- *Adicionar outro PC?*: `s` pra avisar mais gente, `N` pra terminar.

Depois, envia **o seu som** (uma vez só; pra trocar é só reenviar):

```bash
bash upload-som.sh ~/Downloads/som.mp3
```

### Passo 4 — ele faz o mesmo no PC dele

Ele roda `install-hook.sh` com **o SEU IP + SEU secreto**, e roda
`bash upload-som.sh <som dele>` apontando pro SEU PC.

### Pronto

Teste agora: você dá um push → **o PC dele toca o seu som**. Ele dá um
push → **o seu PC toca o dele**. (Funciona em qualquer repositório — o
hook é global.)

---

## Escolhendo o som (leia! importante)

- **Prefira `.wav`.** É o formato mais compatível: toca em qualquer player
  (`pw-play`, `paplay`, `aplay`).
- **`.mp3` só toca se o PC que OUVE tiver `ffmpeg`** (vem o `ffplay`).
  Muitos `pw-play`/`paplay` não decodificam mp3 por padrão e falham em
  silêncio — que é a causa número 1 de "não tocou nada".
- Formatos aceitos: `mp3, wav, ogg, opus, flac, m4a, aac`.
- **Duração**: o som é cortado em **4 segundos** automaticamente. Som
  mais curto toca inteiro.

Se não tiver como usar wav, quem ouve instala o decodificador:

```bash
sudo apt install -y ffmpeg
systemctl --user restart commit-sound
```

---

## Testando e diagnosticando

### Do seu PC, pra ver se SEU aviso chega no amigo

```bash
cd ~/commit-sounds
./testar-som.sh
```

Ele usa a mesma config do hook e mostra o resultado de cada PC:

| Resultado | Significado e o que fazer |
|-----------|--------------------------|
| `OK recebeu (200)` | Chegou e o listener tentou tocar. Se não ouviu, o problema é áudio no PC de quem ouve (veja `--local`) |
| `X NAO CONECTOU` | IP errado, PC do amigo desligado, fora da LAN, ou firewall bloqueando a porta 8080 dele |
| `HTTP 403` | Secreto errado (confere `hook-config.sh` e o `config.json` do ouvinte) |
| `HTTP 404` | Você ainda não enviou seu som pra esse PC → `bash upload-som.sh som.wav` |
| `HTTP 500` | Chegou, mas o PC dele **não conseguiu reproduzir** o arquivo → instalar `ffmpeg` lá, ou reenviar como `.wav` |

### Do seu PC, pra ver se o ÁUDIO deste PC funciona

```bash
./testar-som.sh --local
```

Tenta tocar o som que está salvo aqui com cada player até um funcionar.
Útil pra distinguir "não chegou" de "o PC não reproduz".

### Prod logs

- O hook guarda um log a cada push em `~/.git-hooks/pre-push.log` — mostra
  pra qual URL mandou e com qual resposta HTTP o listener respondeu.
- O listener loga tudo no serviço: `journalctl --user -u commit-sound -n 30`.

---

## Dúvidas e erros mais comuns (FAQ)

### "Rodei tudo e não ouço nada quando dou push"
1. Já enviou seu som pro PC do amigo? (`bash upload-som.sh meu-som.wav`)
2. `./testar-som.sh` — se der 200/OK e mesmo assim não ouve, o áudio do
   PC do amigo é o problema (veja a próxima pergunta).
3. Confira `~/.git-hooks/pre-push.log` pra ver se o push disparou aviso.

### "O teste diz 200 mas não ouviu nada"
A conexão foi ok, mas o player escolhido falhou em silêncio. Causa mais
comum: **sou em mp3 e o PC não tem `ffplay`/ffmpeg**. Solução: no PC de
quem ouve, `sudo apt install -y ffmpeg` + `systemctl --user restart
commit-sound`. Ou reenvie como `.wav`.

### "`install-hook.sh: command not found`"
Você pulou o `bash` na frente. Rode **sempre com `bash`**:
`bash install-hook.sh` (os scripts não estão no `PATH`).

### "Só funciona na máquina, mas não de outro PC na rede"
Firewall. Quem ouve precisa liberar a porta 8080:
`sudo ufw allow 8080/tcp`. E os dois precisam estar na **mesma rede**
(sem VPN/roteador separado, mesmo IP de LAN do tipo `192.168.x.x`).

### "`firewall-cmd: command not found`"
Esse comando é de sistemas com firewalld. Se você está no Ubuntu, o
firewall é `ufw` — use `sudo ufw allow 8080/tcp`.

### "Como troco o som?"
Só rodar de novo: `bash upload-som.sh novo-som.wav`. Sobrescreve o
antigo do seu apelido. Não precisa mexer em mais nada.

### "Posso ter mais de um PC ouvindo meus pushes?"
Sim. Edite `~/.git-hooks/hook-config.sh` e adicione linhas em `CS_TARGETS`
(uma por PC: `URL|secreto`). Depois reenvie seu som pra cada um.

### "Dois amigos usam o mesmo apelido no meu PC"
O segundo upload **sobrescreve** o primeiro. Peça pra um deles mudar o
apelido (editar `hook-config.sh` e reenviar o som).

### "Quero ouvir MEU próprio push no meu PC"
Apontar o hook pro seu próprio PC: em `hook-config.sh`, use seu IP e seu
secreto. Mas você precisa de um som com seu apelido salvo no seu listener
(rode `upload-som.sh` pra você mesmo).

### "O som é cortado no meio!"
Sim, de propósito: **máximo 4 segundos** por toque. Configure em
`DURACAO_MAX` no topo do `listener.py` se quiser outro valor.

### "`push` que não envia nada (up to date) não toca"
Correto, é por design: o hook só dispara quando há ref de branch/tag nova
sendo enviada. (E ele toca mesmo se o push for **recusado** — o aviso sai
antes; é uma escolha de simplicidade.)

### "Porta 8080 em uso"
Edite `~/.commit-sounds/config.json`, troque `"porta"`, reinicie:
`systemctl --user restart commit-sound`, e avise seus amigos do novo
número na URL.

### "`Failed to connect to bus` no systemctl"
O serviço de usuário não subiu porque a sessão não está completa
(comum via SSH). Alternativa: suba na mão
`nohup python3 ~/.commit-sounds/listener.py &` (e rode no login).

### "Como eu removo o som de alguém?"
Delete o arquivo: `rm ~/.commit-sounds/sounds/<apelido>.*`. Depois disso
o `/play` daquela pessoa responde 404.

### "Alguém da rede pode tocar som sem autorização?"
Não. Todo pedido precisa do **secreto** (fica no `config.json` do ouvinte
e no `hook-config.sh` de quem avisa). Sem o secreto é `403`. Se vazar,
regene o secreto (apague o `config.json`, rode `install-listener.sh` de
novo) e reenvie pros amigos.

---

## Depois de desligar / religar o PC

**Não precisa refazer conexão nenhuma.** Tudo é persistente:

- Seus sons, `config.json` e o `hook-config.sh` dos amigos ficam salvos no disco.
- O serviço `commit-sound` está **enabled** → sobe **sozinho no login**, na máquina de quem ouve. O hook é do git global e nunca "desconfigura".

Só 2 pontos de atenção:

1. **O serviço sobe no LOGIN.** Se o PC ligar e ficar na tela de login bloqueada, o serviço do usuário ainda não rodou (sobe quando você desbloqueia). Na prática não faz diferença — ninguém vai te dar um push com o PC desligado/bloqueado. Se quiser subir sem precisar logar: `sudo loginctl enable-linger SEU_USUARIO` (o áudio ainda depende da sessão gráfica, então o ganho é pequeno).
2. **O IP da LAN pode mudar** (DHCP). Se o roteador trocar o IP de quem ouve, os hooks que apontam pro IP antigo param de funcionar. Evite:
   - Reservando um **IP fixo** pro PC no roteador (lease estático por MAC), ou
   - Usando o **hostname** no lugar do IP: `http://pc.local:8080` — o `avahi` (mDNS) resolve o nome mesmo com IP novo, e o listener escuta em `0.0.0.0:8080` (todas as interfaces). É o jeito mais "à prova de futuro".

---

## Personalização rápida

- **Duração**: `DURACAO_MAX` em `listener.py`.
- **Porta**: `"porta"` em `~/.commit-sounds/config.json`.
- **Vários alvos**: `CS_TARGETS` (linhas `URL|secreto`) em
  `~/.git-hooks/hook-config.sh`.
- **Outro diretório de sons**: definido em `~/.commit-sounds/` (pode
  apontar um link simbólico pro seu drive/OneDrive).

## Onde cada coisa vive

| Arquivo | O que é |
|---------|---------|
| `~/.commit-sounds/listener.py` | o servidor de som |
| `~/.commit-sounds/config.json` | porta + secreto do listener |
| `~/.commit-sounds/sounds/<apelido>.<ext>` | os sons enviados |
| `~/.git-hooks/hook-config.sh` | pra onde avisar + seu apelido |
| `~/.git-hooks/pre-push` | hook que dispara o aviso |
| `~/.git-hooks/pre-push.log` | histórico dos avisos por push |

## Limitações (conscientes)

- Só **LAN** — os amigos precisam alcançar o seu IP na mesma rede.
  (Pra internet precisaria de encaminhamento de porta no roteador.)
- O aviso sai **antes** do push ser aceito (pre-push), então um push
  rejeitado ainda toca o som.
- Secreto em texto puro no arquivo local — ok pra brincadeira entre
  amigos, não use em rede aberta com estranhos.