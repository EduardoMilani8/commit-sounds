# 🔊 commit-sounds

**Você dá `git push` → o PC dos seus amigos toca o seu som.**
Eles dão push → o seu PC toca o deles.

![Linux](https://img.shields.io/badge/Linux-only-informational)
![Python](https://img.shields.io/badge/Python-stdlib%20only-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Sem servidor, sem conta, sem IP pra trocar. Funciona na mesma rede (Wi-Fi/LAN).

```
  você: git push ──▶ 🔊 PC da Ana toca seu som
                 ──▶ 🔊 PC do Beto toca seu som
```

## Instalar (1 minuto)

```bash
git clone https://github.com/EduardoMilani8/commit-sounds ~/commit-sounds
cd ~/commit-sounds
bash instalar.sh
```

O instalador faz 3 perguntas:

| Pergunta | Resposta |
|----------|----------|
| Apelido | como os amigos te veem (`vini`) |
| Código da sala | o código que um amigo mandou, ou **Enter** pra criar uma sala nova |
| Seu som | ex: `~/Downloads/risada.mp3` |

Pronto. Dê um `git push` em qualquer repositório e ouça.

## Chamar um amigo

1. Rode `commit-sounds sala` e mande o código (ex: `sapo-azul-7k2mpq`).
2. Ele instala e cola o código. Ele aparece pra todo mundo sozinho.

## Comandos

| Comando | Para quê |
|---------|----------|
| `commit-sounds` | mostra quem da sala está online |
| `commit-sounds testar` | toca seu som nos amigos agora |
| `commit-sounds testar --aqui` | toca seu som neste PC |
| `commit-sounds som ~/novo.mp3` | troca seu som |
| `commit-sounds mudo [min]` | silencia (padrão 60 min); `mudo off` volta |
| `commit-sounds sala` | mostra o código da sala |
| `commit-sounds adicionar <ip>` | adiciona amigo pelo IP se a descoberta falhar |
| `commit-sounds remover <apelido>` | esquece um amigo |
| `commit-sounds configurar` | refaz apelido, sala e som |

## Como funciona

- Cada PC roda um serviço leve (systemd de usuário) que se anuncia na rede
  por UDP a cada 30 s.
- Um hook global de `pre-push` avisa os amigos **em segundo plano**: o push
  nunca fica lento nem é bloqueado.
- Se o amigo não tem seu som, ele baixa direto do seu PC na hora.
- Tudo é assinado com uma chave derivada do código da sala: quem não tem o
  código não toca nada.

## Sobre o som

- `mp3, wav, ogg, opus, flac, m4a, aac`, até 5 MB.
- Toca no máximo **5 segundos**.
- `.mp3` precisa de `ffmpeg` no PC de quem ouve (o instalador instala).

## Deu problema?

Rode `commit-sounds` e `commit-sounds testar`: cada erro vem com a dica.

| Sintoma | O que fazer |
|---------|-------------|
| Nenhum amigo na sala | Confira se o código é o mesmo. Se o roteador bloqueia broadcast, use `commit-sounds adicionar <ip>` |
| `nao conectou` | PC do amigo desligado, outra rede ou firewall (`sudo ufw allow 8008`) |
| `relogio fora de sincronia` | Hora errada em um dos PCs (mais de 10 min de diferença) |
| `tocou`, mas ninguém ouviu | Volume do amigo; ele pode testar com `commit-sounds testar --aqui` |
| `Servico: PARADO` | `systemctl --user restart commit-sounds` e `journalctl --user -u commit-sounds -n 30` |
| `command not found` | Abra um terminal novo (o comando fica em `~/.local/bin`) |

## Limitações

- Só Linux, só na mesma rede.
- O aviso sai antes do remoto aceitar o push, então um push recusado também toca.
- O hook global (`core.hooksPath`) faz o git ignorar `.git/hooks` de cada repo.
- Quem tem o código da sala toca som em todo mundo dela. Não compartilhe fora da turma.

## Arquivos

Tudo fica em `~/.commit-sounds/` (config, seu som, amigos, cache) e o hook em
`~/.git-hooks/pre-push`. Porta padrão **8008** (TCP e UDP); a sala inteira
precisa usar a mesma.

## Contribuir

Issues e PRs são bem-vindos. O projeto é um único arquivo Python (só stdlib)
e não tem build nem dependências.

## Licença

[MIT](LICENSE)
