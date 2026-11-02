# Homelab no Xiaomi Redmi Note 9S (Sem Root)

Guia completo e scripts de automação para transformar um smartphone **Xiaomi Redmi Note 9S (`curtana` / `miatoll` — Snapdragon 720G / ARM64)** em um miniservidor local eficiente, estável e de baixo consumo de energia (1.5W a 4W), operando 24/7 **sem necessidade de Root ou desbloqueio de bootloader**.

---

## 📱 Hardware & Características do Aparelho

| Especificação | Detalhe | Impacto no Homelab |
| :--- | :--- | :--- |
| **SoC / CPU** | Qualcomm Snapdragon 720G (8 núcleos Kryo 465, até 2.3 GHz) | Excelente desempenho para web, APIs, bancos e VMs ARM64 |
| **Arquitetura** | ARM64 (`aarch64`) | Compatível com a maioria das imagens Linux e containers modernos |
| **Memória RAM** | 4GB ou 6GB LPDDR4X | Suficiente para Termux nativo, PostgreSQL, Node/Python e containers leves |
| **Armazenamento**| 64GB ou 128GB UFS 2.1 (+ slot microSD) | IOPS e leitura rápida; expansível com cartão de memória classe A1/A2 |
| **Bateria** | 5020 mAh | Funciona como um **No-Break (UPS) embutido** em quedas de energia |
| **Rede** | Wi-Fi 802.11 a/b/g/n/ac (2.4GHz e 5GHz) + Suporte OTG Ethernet | Conexão rápida; possibilidade de adaptador USB-C Ethernet com carregamento |

---

## 🗺️ Mapa de Portas Padrão

Por estarmos operando no Android **sem root**, todos os serviços rodam em **portas altas (> 1024)**:

| Serviço | Porta Padrão | Protocolo / Descrição |
| :--- | :--- | :--- |
| **Canal de Controle TCP** | `9000` | Canal persistente de controle com framing binário de 40B e HMAC-SHA256 |
| **Canal de Dados/Mídia TCP** | `9001` | Recepção de arquivos e mídia em chunks indexados de 64KB |
| **OpenSSH (Debian UserLAnd)**| `2022` | Acesso SSH ao ambiente Debian 11 em espaço de usuário (sem root) |
| **OpenSSH (Termux)** | `8022` | Acesso terminal remoto no Termux com chave pública Ed25519 |
| **Caddy / Nginx (HTTP)** | `8080` | Proxy reverso principal HTTP |
| **Caddy / Nginx (HTTPS)** | `8443` | Proxy reverso seguro HTTPS |
| **PostgreSQL** | `5432` | Banco de dados relacional nativo |
| **Alpine Docker VM (QEMU SSH)** | `2222` | Acesso SSH à máquina virtual Docker de contingência |
| **Udocker / Apps Web** | `3000` / `8000` | APIs Node.js, FastAPI, Flask, etc. |

---

## 📚 Documentação do Projeto

A documentação está organizada entre **Infraestrutura do Homelab** e **Aplicações / Software**:

### 🛠️ Infraestrutura e Setup do Aparelho (`docs/infra/`)
1. [**01. Preparação da MIUI e Android**](docs/infra/01-preparacao-miui-android.md)
   - Limpeza de bloatware, desativação de suspensão e morte de processos na MIUI.
   - Desativação do *Phantom Process Killer* (Android 12+) via ADB.
   - Instalação limpa dos apps Termux via F-Droid.
   - Cuidados físicos e elétricos com a bateria 24/7.
2. [**02. Rede, SSH e Acesso Remoto**](docs/infra/02-rede-ssh-e-acesso-remoto.md)
   - Configuração de IP estático e wake-lock permanente.
   - OpenSSH seguro com chaves Ed25519 e atalhos no Mac (`~/.ssh/config`).
   - Conexão segura externa sem abrir portas via Tailscale / ZeroTier.
3. [**03. Serviços Web, Dev e Bancos de Dados**](docs/infra/03-servicos-web-dev-e-bancos.md)
   - Stack nativa: Python (venv/uv), Node.js LTS, Git e compiladores.
   - PostgreSQL e SQLite configurados e integrados.
   - Proxy reverso com Caddy ou Nginx para múltiplos projetos.
   - Gerenciamento de daemons em segundo plano com `termux-services` e `pm2`.
4. [**04. Containers e Docker Sem Root**](docs/infra/04-containers-docker-sem-root.md)
   - **Opção A (`udocker`)**: Execução de imagens OCI com desempenho nativo.
   - **Opção B (QEMU ARM64 + Alpine Linux)**: Docker Engine e Docker Compose completos.
   - **Decisão Arquitetural (ADR)**: Adoção do Debian 11 (UserLAnd) + Python venv nativo.
5. [**05. Automação de Boot e Manutenção**](docs/infra/05-automacao-boot-e-manutencao.md)
   - Auto-inicialização após reinicialização com `Termux:Boot`.
   - Monitoramento de temperatura e hardware.
   - Automação inteligente de ciclo de bateria (30% - 80%) com tomadas Wi-Fi.
6. [**06. Spike de Capacidade, Concorrência e Limites Físicos do Host**](docs/infra/06-capacidade-e-limites-fisicos-do-host.md)
   - Desmistificação do mito de limitação de portas TCP (kernel 4-tuple).
   - Raio-X do Snapdragon 720G: dissipação térmica passiva, LMK, ulimit e I/O flash.
   - Análise comparativa: Thread-per-Client vs Event Loop assíncrono (`asyncio`).
7. [**07. Verificação, Pré-Voo e Saúde da Infraestrutura do Host**](docs/infra/07-verificacao-e-saude-da-infraestrutura.md)
   - Arquitetura real em produção: Debian 11 (UserLAnd PRoot) + Python venv nativo.
   - Validações estritas Fail-Fast de arquivos `.env` e limites de portas não privilegiadas.
   - Guia completo do utilitário `scripts/check-infra.sh` e matriz de diagnóstico.

### 💻 Aplicações e Arquitetura de Software (`docs/app/`)
* [**SPEC - Arquitetura e Protocolo do Cliente OO**](docs/app/SPEC-client-architecture.md): Decomposição modular de `app/client/`, hierarquia `Package`, comandos OO e gestão de sessão.
* [**SPEC - Arquitetura e Invariantes do Servidor OO**](docs/app/SPEC-server-architecture.md): Decomposição modular de `app/server/`, dispatcher de comandos, gestão de tickets e segurança PBKDF2/HMAC.
* [**001. Conexão TCP via Sockets e Persistência de Logs**](docs/app/001-connection-tcp.md): Especificação do socket TCP puro na porta 9000 e gravação em arquivo.
* [**002. Definição das Stacks de Infraestrutura e Software**](docs/app/002-stack-definicao-e-arquitetura.md): Diretrizes oficiais de arquitetura, hardware e stack oficial em Python 3.
* [**003. Autenticação de Clientes, Classes OO e Quick Login**](docs/app/003-client-auth-and-storage.md): Especificação da tabela `clients` em SQLite, classes `Client`, `Session` e `Message`, e documento NoSQL para Quick Login.
* [**004. Protocolos de Controle e Dados (Framing Persistente e Chunks)**](docs/app/004-protocolos-controle-e-dados.md): Framing binário de 40B, chave de sessão dinâmica HMAC-SHA256 e upload de arquivos em chunks indexados de 64KB.
* [**005. Gerenciamento de Configurações e Variáveis de Ambiente**](docs/app/005-gerenciamento-de-configuracoes-e-env.md): Suporte a `server.env`, `client.env`, fallback para `os.environ`, precedência em camadas e suporte a fail fast.
* [**006. Guia Rápido: Como Rodar e Usar o Servidor e o Cliente**](docs/app/006-guia-rapido-como-rodar.md): Guia direto de execução passo a passo (`python3 -m app.server` e `python3 -m app.client`), flags CLI, Quick Login, `/upload` e inspeção de logs/SQLite.

---

## 🚀 Como Usar e Executar (Servidor e Cliente)

Após a refatoração orientada a objetos, o **Servidor** ([`app/server/`](app/server/)) e o **Cliente** ([`app/client/`](app/client/)) são pacotes Python modulares equipados com `__main__.py`, permitindo execução direta tanto via módulo (`python3 -m app.server` / `python3 -m app.client`) quanto via caminho do diretório (`python3 app/server` / `python3 app/client`).

### 1. Preparação dos Arquivos de Ambiente (`.env`)
Antes de iniciar, crie os arquivos locais de configuração a partir dos templates oficiais em [`envs/`](envs/):

```bash
cp envs/server.env.sample envs/server.env
cp envs/client.env.sample envs/client.env

# Validar configurações (Fail-Fast)
./scripts/check-infra.sh --mode server --env-only
./scripts/check-infra.sh --mode client --env-only
```

---

### 2. Como Rodar o Servidor (`app/server/`)

O servidor inicia simultaneamente dois canais TCP:
- **Canal de Controle (Porta `9000`):** Conexão persistente com framing binário de 40B, autenticação PBKDF2 e emissão de chave de sessão dinâmica HMAC-SHA256.
- **Canal de Dados/Mídia (Porta `9001`):** Recepção de arquivos fatiados em chunks indexados de 64KB (cabeçalho de 62B) com gravação direta em disco e validação SHA-256.

```bash
# Iniciar com as configurações padrão de envs/server.env (escutando em 0.0.0.0:9000 e :9001)
python3 -m app.server
# Ou: python3 app/server

# Iniciar apenas em loopback (para desenvolvimento/testes locais)
python3 -m app.server --host 127.0.0.1

# Sobrescrever portas, banco SQLite, log ou diretório de uploads via CLI
python3 -m app.server --host 0.0.0.0 --port 9000 --data-port 9001 \
  --db app/data/homelab.db \
  --log app/logs/server_messages.log \
  --uploads-dir app/data/uploads

# Iniciar com um arquivo .env específico
python3 -m app.server --env-file envs/server.env
```

#### Executando em Produção 24/7 com PM2 (Termux / Debian UserLAnd):
```bash
pm2 start app/server --name "homelab-server" --interpreter python3
pm2 status
pm2 logs homelab-server
pm2 save
```

---

### 3. Como Rodar e Usar o Cliente (`app/client/`)

#### A. Modo Interativo (Menu de Acesso, Quick Login e Chat/Upload)
Execute o cliente sem argumentos de ação para abrir a interface interativa de terminal (`ClientTerminalUI`):

```bash
# Conectar usando o destino configurado em envs/client.env
python3 -m app.client
# Ou: python3 app/client

# Apontar para o IP do smartphone na rede local (LAN ou Tailscale)
python3 -m app.client --host 192.168.0.246 --port 9000 --data-port 9001
```

**Fluxo no Terminal Interativo:**
1. **Menu de Acesso:**
   - Escolha `2. Register` no primeiro acesso para criar sua conta (mínimo 3 caracteres). O cliente ativa o **Auto-Login** e salva a sessão local em `app/data/client_session.json` (`chmod 600`, válida por 7 dias).
   - Escolha `1. Login` nos próximos acessos: se houver sessão válida, o cliente oferece **Quick Login** (`[S/n]`) sem precisar redigitar a senha.
2. **Prompt Conectado (`[usuario] >`):**
   - **Enviar mensagem de texto:** Digite qualquer texto e pressione `Enter`.
   - **Enviar arquivo/mídia em chunks de 64KB:** Digite `/upload <caminho_do_arquivo>` (ex: `/upload app/data/foto.jpg`).
   - **Encerrar sessão:** Digite `sair` (ou `exit` / `quit` / `Ctrl+C`), realizando o logout limpo e marcando presença como `offline` no servidor.

#### B. Modo Direto via Linha de Comando (CLI One-Shot)
Você também pode enviar uma mensagem ou fazer upload de um arquivo diretamente por flags após a autenticação:

```bash
# Enviar uma mensagem de texto e encerrar
python3 -m app.client --host 127.0.0.1 -m "Olá Homelab via CLI!"

# Fazer upload de um arquivo em chunks de 64KB e encerrar
python3 -m app.client --host 127.0.0.1 -u caminho/para/arquivo.png

# Enviar mensagem + fazer upload na mesma sessão
python3 -m app.client --host 127.0.0.1 -m "Enviando relatório" -u relatorio.pdf
```

---

### 4. Uso Programático (API Orientada a Objetos em Python)

Como os pacotes [`app.client`](app/client/__init__.py) e [`app.server`](app/server/__init__.py) expõem as classes `HomelabClient` (`Client`) e `HomelabServer` (`Server`) com suporte a *Context Manager* (`with`), você pode integrá-los diretamente em scripts ou testes:

```python
from app.client import HomelabClient
from app.server import HomelabServer

# Iniciar servidor em background e conectar cliente via Context Manager determinístico
with HomelabServer(host="127.0.0.1", control_port=9000, data_port=9001) as server:
    with HomelabClient(host="127.0.0.1", control_port=9000, data_port=9001) as client:
        # 1. Cadastrar ou fazer login
        ok, msg = client.register("naoki", "MinhaSenhaSegura123")
        # Ou: ok, msg = client.login("naoki", "MinhaSenhaSegura123")

        # 2. Enviar mensagem de texto no Canal de Controle (:9000)
        ok, resp = client.send_message("Mensagem via API OO!")

        # 3. Enviar arquivo fatiado em Chunks de 64KB no Canal de Dados (:9001)
        ok, up_resp = client.upload_file("app/data/foto.jpg")
```

---

## ⚡ Quickstart de Infraestrutura (Scripts do Aparelho)

Se você já instalou o Termux pelo F-Droid e tem acesso ao terminal no celular, você pode clonar este repositório ou copiar a pasta de scripts para o aparelho:

```bash
# 1. No Termux, instale o git e clone o repositório
pkg update && pkg install -y git
git clone <URL_DO_SEU_REPOSITORIO> homelab
cd homelab/scripts

# 2. Torne os scripts executáveis
chmod +x *.sh

# 3. Execute o bootstrap do sistema básico + SSH
./01-bootstrap-termux.sh

# 4. (Opcional) Instale a stack de desenvolvimento e bancos
./02-setup-dev-stack.sh

# 5. (Opcional) Configure containers (udocker ou Docker QEMU)
./03-setup-containers.sh

# 6. Configure a inicialização automática no boot do celular
./04-setup-autostart.sh
```

---

## 📁 Estrutura do Repositório

```text
homelab/
├── README.md
├── GEMINI.md
├── requirements.txt
├── app/
│   ├── client/                # Pacote modular do Cliente CLI (OO, commands, session)
│   ├── server/                # Pacote modular do Servidor TCP (OO, dispatcher, tickets)
│   ├── config.py              # Gestor de configurações e arquivos .env com Fail-Fast
│   ├── protocol.py            # Hierarquia Package, framing binário de 40B/62B e HMAC
│   ├── database.py            # Persistência SQLite (homelab.db), auth PBKDF2 e chaves HMAC
│   ├── client_session.py      # Wrapper de compatibilidade retroativa para app.client.session
│   ├── data/
│   │   ├── homelab.db         # Banco relacional de contas, presenças e mensagens
│   │   └── uploads/           # Armazenamento de arquivos e mídias recebidos
│   └── logs/
│       └── server_messages.log
├── envs/
│   ├── .env.sample            # Modelo consolidado para desenvolvimento local
│   ├── server.env.sample      # Modelo exclusivo para o host do Servidor
│   └── client.env.sample      # Modelo exclusivo para o Cliente
├── docs/
│   ├── app/
│   │   ├── SPEC-client-architecture.md
│   │   ├── SPEC-server-architecture.md
│   │   ├── 001-connection-tcp.md
│   │   ├── 002-stack-definicao-e-arquitetura.md
│   │   ├── 003-client-auth-and-storage.md
│   │   ├── 004-protocolos-controle-e-dados.md
│   │   ├── 005-gerenciamento-de-configuracoes-e-env.md
│   │   └── 006-guia-rapido-como-rodar.md
│   └── infra/
│       ├── 01-preparacao-miui-android.md
│       ├── 02-rede-ssh-e-acesso-remoto.md
│       ├── 03-servicos-web-dev-e-bancos.md
│       ├── 04-containers-docker-sem-root.md
│       ├── 05-automacao-boot-e-manutencao.md
│       ├── 06-capacidade-e-limites-fisicos-do-host.md
│       └── 07-verificacao-e-saude-da-infraestrutura.md
├── tests/
│   ├── test_adversarial_protocol_stress.py
│   ├── test_auth_and_session.py
│   ├── test_check_infra.py
│   ├── test_code_standards.py
│   ├── test_config.py
│   ├── test_dual_protocol_and_chunks.py
│   └── test_e2e_opaque_box.py
└── scripts/
    ├── 01-bootstrap-termux.sh
    ├── 02-setup-dev-stack.sh
    ├── 03-setup-containers.sh
    ├── 04-setup-autostart.sh
    ├── check-infra.sh         # Utilitário estrito de verificação de pré-voo e saúde
    ├── battery-guard.sh
    └── wifi-watchdog.sh
```
