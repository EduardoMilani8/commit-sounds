# commit-sounds

Você dá `git push` → o PC dos seus amigos **toca o seu som**. Eles dão
push → o seu PC toca o deles. Funciona na **mesma rede** (Wi-Fi/LAN), sem
servidor central.

A turma entra numa **sala**: um código tipo `sapo-azul-7k2mpq`. Quem tem o
código se encontra sozinho na rede — ninguém precisa trocar IP nem senha.

---

## Instalar

```bash
git clone <este repositório> ~/commit-sounds
cd ~/commit-sounds
bash instalar.sh
```

O instalador pergunta três coisas:

| Pergunta | O que responder |
|----------|-----------------|
| Seu apelido | como os amigos vão te ver (ex: `vini`) |
| Código da sala | o código que um amigo te mandou — ou **Enter** para criar uma sala nova |
| Caminho do seu som | ex: `~/Downloads/risada.mp3` |

E cuida do resto: instala `ffmpeg`/player de áudio se faltar, libera a
porta no firewall (`ufw`), deixa o serviço rodando (sobe sozinho no login)
e instala o hook global de push.

No fim, ele já mostra quem da sala está online.

## Chamar um amigo novo

1. Rode `commit-sounds sala` e mande o código pra ele.
2. Ele roda `bash instalar.sh` e cola o código.

Pronto. Ninguém mais da sala precisa fazer nada — ele aparece pra todo
mundo e o som dele chega sozinho no primeiro push.

---

## Comandos

| Comando | Para quê |
|---------|----------|
| `commit-sounds` | mostra sua config e quem da sala está online |
| `commit-sounds testar` | toca o seu som nos amigos **agora** |
| `commit-sounds testar --aqui` | toca o seu som neste PC (testa o áudio daqui) |
| `commit-sounds som ~/novo.mp3` | troca o seu som |
| `commit-sounds sala` | mostra o código da sala |
| `commit-sounds mudo [minutos]` | silencia os sons (padrão 60 min); `mudo off` desliga |
| `commit-sounds adicionar 192.168.0.15` | adiciona um amigo pelo IP, se a descoberta automática falhar |
| `commit-sounds remover vini` | esquece um amigo |
| `commit-sounds configurar` | refaz as perguntas (apelido, sala, som) |

## Como funciona

- Cada PC roda um serviço (`commit-sounds.service`, do systemd de usuário)
  que se anuncia na rede a cada 30 s e escuta avisos de push.
- A cada `git push` de branch ou tag, o hook avisa todos os amigos da sala
  **em segundo plano** — o push não fica mais lento e nunca é bloqueado.
- O aviso leva a "impressão digital" do seu som. Se o amigo ainda não tem
  essa versão, o PC dele baixa do seu na hora. Por isso, trocar o som é só
  `commit-sounds som`: os amigos recebem o novo no próximo push.
- Tudo é assinado com uma chave derivada do código da sala: quem não tem o
  código não consegue tocar nada.

## Escolhendo o som

- Formatos: `mp3, wav, ogg, opus, flac, m4a, aac`, até 5 MB.
- Toca no máximo **5 segundos** (mais curto toca inteiro).
- `.wav` toca em qualquer PC. `.mp3` precisa de `ffmpeg` no PC de quem
  ouve — o instalador já instala.

---

## Deu problema?

Comece por `commit-sounds` (status) e `commit-sounds testar`: cada falha
vem com a dica do que fazer.

| Sintoma | O que fazer |
|---------|-------------|
| "Nenhum amigo na sala ainda" | Confiram se o código da sala é o mesmo (`commit-sounds sala`). Alguns roteadores bloqueiam a descoberta: use `commit-sounds adicionar IP_DO_AMIGO` (o IP dele aparece no `ip -4 addr` do PC dele) |
| `nao conectou` | PC do amigo desligado, em outra rede, ou firewall fechado lá (`sudo ufw allow 8080`) |
| `codigo da sala diferente` | Um dos dois digitou outro código → `commit-sounds configurar` |
| `relogio fora de sincronia` | Data/hora de um dos PCs está errada (mais de 10 min de diferença) |
| `nao conseguiu baixar seu som` | O problema é no **seu** PC: serviço parado ou porta 8080 fechada aqui |
| `o PC dele nao conseguiu tocar` | Falta `ffmpeg` no PC dele, ou mande um `.wav` |
| `tocou`, mas ninguém ouviu | Volume/saída de áudio do amigo. Ele pode rodar `commit-sounds testar --aqui` |
| `Servico: PARADO` | `systemctl --user restart commit-sounds` e veja `journalctl --user -u commit-sounds -n 30` |
| `commit-sounds: command not found` | Abra um terminal novo (o comando fica em `~/.local/bin`) |

### Logs

- Avisos que você mandou: `~/.commit-sounds/avisos.log`
- Serviço (o que chegou e tocou): `journalctl --user -u commit-sounds -n 30`

## Onde fica cada coisa

| Arquivo | O que é |
|---------|---------|
| `~/.commit-sounds/config.json` | apelido, sala, portas |
| `~/.commit-sounds/meu-som.*` | uma cópia do seu som |
| `~/.commit-sounds/amigos.json` | amigos encontrados na sala |
| `~/.commit-sounds/cache/` | sons dos amigos |
| `~/.git-hooks/pre-push` | hook global que avisa a cada push |

Porta padrão: **8080** (TCP para avisos, UDP para a descoberta). Para mudar,
edite `porta`/`porta_sala` no `config.json` e reinicie o serviço — mas a
sala inteira precisa usar a mesma `porta_sala`.

## Limitações

- Só Linux e só na mesma rede.
- O aviso sai **antes** do remoto aceitar o push (é um hook `pre-push`),
  então um push recusado também toca.
- O hook global (`core.hooksPath`) faz o git ignorar os hooks em
  `.git/hooks` de cada repositório.
- Quem tem o código da sala consegue tocar som em todo mundo da sala.
  Não compartilhe fora da turma.
