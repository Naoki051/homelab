# Guia Rápido: Como Rodar e Usar o Servidor e o Cliente (Pós-Refatoração OO)

> **Propósito:** Guia prático passo a passo para subir o servidor TCP Dual-Channel (`app/server/`) e operar o cliente CLI (`app/client/`) no dia a dia, tanto em ambiente local (Mac/Linux) quanto conectado ao smartphone (**Xiaomi Redmi Note 9S**).

---

## 1. Pré-Voo Rápido (Configuração `.env`)

Na primeira vez que clonar o repositório, gere os arquivos de ambiente a partir dos templates em [`envs/`](../../envs/):

```bash
cp envs/server.env.sample envs/server.env
cp envs/client.env.sample envs/client.env

# Validar se variáveis e portas (9000 e 9001) estão prontas
./scripts/check-infra.sh --mode server --env-only
./scripts/check-infra.sh --mode client --env-only
```

---

## 2. Passo 1: Como Rodar o Servidor (`app/server/`)

Abra um terminal para o servidor. Ele escutará simultaneamente no **Canal de Controle (`:9000`)** e no **Canal de Dados/Mídia (`:9001`)**:

### A. Execução Padrão (Lendo `envs/server.env`)
```bash
python3 -m app.server
# Alternativa equivalente:
python3 app/server
```

### B. Execução Local para Testes Rápidos (`127.0.0.1`)
```bash
python3 -m app.server --host 127.0.0.1 --port 9000 --data-port 9001
```

### C. Execução Contínua em Segundo Plano (PM2 no Smartphone)
```bash
pm2 start app/server --name "homelab-server" --interpreter python3
pm2 status
pm2 logs homelab-server
```

---

## 3. Passo 2: Como Rodar e Usar o Cliente (`app/client/`)

Com o servidor rodando, abra outro terminal para o cliente:

### A. Modo Interativo (Menu Completo no Terminal)
```bash
# Conectando ao host definido em envs/client.env
python3 -m app.client
# Alternativa equivalente:
python3 app/client

# Ou apontando diretamente para o IP do celular na rede Wi-Fi / Tailscale
python3 -m app.client --host 192.168.0.246
```

#### Como navegar no Menu Interativo:
```text
=======================================================
          HOMELAB TCP CLIENT - ACESSO
=======================================================
  1. Login
  2. Register (Criar nova conta)
  3. Sair
=======================================================
Escolha uma opção [1-3]:
```

1. **Primeiro Acesso (`2. Register`):**
   - Digite um `Username` (mínimo 3 caracteres) e defina uma `Senha`.
   - O servidor cadastra sua conta com hash PBKDF2, emite uma chave de sessão dinâmica HMAC de 32 bytes e o cliente salva automaticamente o **Quick Login** em `app/data/client_session.json` (válido por 7 dias).
2. **Próximos Acessos (`1. Login` $\rightarrow$ Quick Login):**
   - Ao escolher `1`, o cliente detecta sua sessão salva e pergunta:
     ```text
     [?] Quick login disponível para 'naoki' (6d 23h restantes). Deseja aceitar? [S/n]:
     ```
   - Pressione **Enter** (ou `S`) para entrar instantaneamente sem digitar senha.
3. **Dentro da Sessão Conectada (`[usuario] >`):**
   - **Enviar mensagem de texto:** Digite a mensagem e pressione **Enter**:
     ```text
     [naoki] > Olá Homelab!
     [<] Resposta do servidor: Mensagem processada com sucesso para 'naoki'
     ```
   - **Enviar arquivo ou imagem (Upload em Chunks de 64KB):** Use o comando `/upload <caminho>`:
     ```text
     [naoki] > /upload app/data/foto.jpg
     [*] Iniciando upload de 'foto.jpg' (...) via Canal de Dados ...:9001...
     [✓] Arquivo 'foto.jpg' recebido com sucesso (X chunks).
     ```
   - **Sair com Logout Limpo:** Digite `sair` (ou `exit`, `quit` ou pressione `Ctrl+C`). O servidor atualiza seu status no banco para `offline`.

---

### B. Modo Direto por Linha de Comando (One-Shot CLI)

Se quiser enviar uma mensagem ou fazer upload de um arquivo e encerrar automaticamente logo após autenticar:

```bash
# Enviar apenas uma mensagem de texto
python3 -m app.client --host 127.0.0.1 -m "Mensagem rápida via terminal!"

# Fazer upload direto de um arquivo em chunks de 64KB
python3 -m app.client --host 127.0.0.1 -u app/data/foto.jpg

# Enviar mensagem e fazer upload no mesmo comando
python3 -m app.client --host 127.0.0.1 -m "Segue foto anexa" -u app/data/foto.jpg
```

---

## 4. Tabela de Argumentos de Linha de Comando (CLI)

### Servidor (`python3 -m app.server --help`)
| Flag | Descrição | Padrão (`envs/server.env`) |
| :--- | :--- | :--- |
| `--env-file <path>` | Caminho para arquivo `.env` customizado | `envs/server.env` |
| `--host <ip>` | Endereço IP de escuta (bind) | `0.0.0.0` |
| `--port <int>` | Porta TCP do Canal de Controle | `9000` |
| `--data-port <int>` | Porta TCP do Canal de Dados/Mídia | `9001` |
| `--db <path>` | Caminho do arquivo SQLite | `app/data/homelab.db` |
| `--log <path>` | Caminho do arquivo de log de mensagens | `app/logs/server_messages.log` |
| `--uploads-dir <dir>` | Pasta onde os uploads recebidos são salvos | `app/data/uploads` |

### Cliente (`python3 -m app.client --help`)
| Flag | Descrição | Padrão (`envs/client.env`) |
| :--- | :--- | :--- |
| `--env-file <path>` | Caminho para arquivo `.env` customizado | `envs/client.env` |
| `--host <ip>` | IP de destino do servidor Homelab | `127.0.0.1` |
| `--port <int>` | Porta TCP do Canal de Controle | `9000` |
| `--data-port <int>` | Porta TCP do Canal de Dados/Mídia | `9001` |
| `-m`, `--message <txt>` | Envia mensagem de texto após autenticar e encerra | — |
| `-u`, `--upload <path>` | Envia arquivo em chunks de 64KB após autenticar e encerra | — |

---

## 5. Onde Conferir os Dados Gerados

```bash
# 1. Ver mensagens de texto e registros de upload em tempo real
tail -f app/logs/server_messages.log

# 2. Listar os arquivos enviados pelo comando /upload
ls -lh app/data/uploads/<seu_username>/

# 3. Consultar usuários e status (online/offline) no banco SQLite
sqlite3 app/data/homelab.db "SELECT id, username, status, last_seen FROM clients;"

# 4. Ver dados da sessão local do Quick Login no cliente
cat app/data/client_session.json
```

---

## 6. Como Rodar os Testes e o Linter

```bash
# Rodar todas as 112 suítes de testes (unitários, integração, estresse adversarial e E2E)
python3 -m unittest discover -s tests -v

# Auditar estilo PEP 8 e complexidade ciclomática (<= 12) com Flake8
./scripts/run-lint.sh app/ tests/
```
