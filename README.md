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

---

## ⚡ Quickstart (Executando os Scripts)

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
│   │   └── 005-gerenciamento-de-configuracoes-e-env.md
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
│   └── test_dual_protocol_and_chunks.py
└── scripts/
    ├── 01-bootstrap-termux.sh
    ├── 02-setup-dev-stack.sh
    ├── 03-setup-containers.sh
    ├── 04-setup-autostart.sh
    ├── check-infra.sh         # Utilitário estrito de verificação de pré-voo e saúde
    ├── battery-guard.sh
    └── wifi-watchdog.sh
```
