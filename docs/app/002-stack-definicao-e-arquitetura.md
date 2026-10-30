# Documento de Arquitetura: Definição das Stacks de Infraestrutura e Software

> **Status:** Aprovado  
> **Linguagem Oficial da Aplicação:** Python 3  
> **Host da Infraestrutura:** Xiaomi Redmi Note 9S (`curtana` / `miatoll` — Snapdragon 720G / ARM64) sem Root

---

## 1. Visão Geral e Propósito

Este documento consolida a arquitetura tecnológica do projeto **Homelab**, estabelecendo as diretrizes técnicas para as duas camadas do ecossistema:
1. **Camada de Infraestrutura (Host da Máquina):** O ambiente operacional, restrições e ferramentas que transformam o smartphone em um miniservidor autônomo e contínuo (24/7).
2. **Camada de Software (Aplicações em `app/`):** A stack de desenvolvimento, linguagem padrão, convenções de código e ciclo de vida dos serviços construídos para rodar no homelab.

---

## 2. Camada 1: Stack de Infraestrutura da Máquina

### 2.1. Especificações de Hardware e Capacidades
* **SoC / Processador:** Qualcomm Snapdragon 720G (8 núcleos Kryo 465, até 2.3 GHz).
* **Arquitetura de CPU:** ARM64 (`aarch64`).
* **Memória RAM:** 4GB ou 6GB LPDDR4X.
* **Armazenamento:** 64GB / 128GB UFS 2.1 (expansível via microSD classe A1/A2).
* **Bateria:** 5020 mAh atuando como **No-Break (UPS) embutido**.
* **Consumo Energético Médio:** 1.5W a 4W em operação contínua.

### 2.2. Sistema Operacional e Restrições do Android sem Root
Por estarmos em ambiente Android nativo com Termux e sem permissão de superusuário (Root):
* **Espaço de Usuário:** Toda a árvore do sistema de pacotes reside em `$PREFIX` (`/data/data/com.termux/files/usr`).
* **Portas de Rede:** Apenas portas não privilegiadas (`> 1024`) são permitidas. Portas baixas (80, 443, 22) não são utilizáveis diretamente.
* **Mitigação do OOM e Phantom Process Killer:**
  * Desativação do Phantom Process Killer (Android 12+) via ADB:
    ```bash
    adb shell "/system/bin/device_config put activity_manager max_phantom_processes 2147483647"
    ```
  * Wake-lock permanente ativado via `termux-wake-lock` para evitar que a CPU entre em suspensão profunda (*deep sleep*).
  * Otimização de bateria configurada como "Sem restrições" nas configurações da MIUI.

### 2.3. Matriz de Serviços de Infraestrutura

| Serviço / Papel | Tecnologia Adotada | Porta Padrão | Descrição e Justificativa |
| :--- | :--- | :--- | :--- |
| **Terminal & Acesso Seguro** | **OpenSSH** | `8022` | Autenticação exclusiva por chave pública Ed25519; acesso direto via LAN. |
| **Acesso Externo Seguro** | **Tailscale / Mesh VPN** | Dinâmica | Túnel criptografado P2P sem necessidade de abrir portas no roteador de borda. |
| **Proxy Reverso HTTP/HTTPS** | **Caddy Server** | `8080` / `8443` | Proxy moderno e leve com recarregamento a quente e baixo uso de memória. |
| **Gerenciador de Processos** | **PM2** / `termux-services` | — | Monitoramento, auto-restart em caso de falha e gestão de logs em segundo plano. |
| **Banco de Dados Relacional** | **PostgreSQL** | `5432` | Banco relacional robusto e nativo compilado para ARM64 no Termux. |
| **Banco de Dados Embutido** | **SQLite 3** | Arquivo local | Persistência serverless direta e sem overhead de rede para aplicações locais. |
| **Containers sem Root** | **udocker** | Dinâmica | Execução de containers OCI via user namespaces e PRoot sem necessidade de Docker daemon. |
| **Containers Completos** | **QEMU + Alpine VM** | `2222` (SSH VM) | VM de contingência para workloads que exigem Docker Engine e Docker Compose padrão. |

---

## 3. Camada 2: Stack de Software da Aplicação (`app/`)

### 3.1. Linguagem Oficial: Python 3
A linguagem padrão homologada para o desenvolvimento dos serviços e aplicações do repositório é o **Python 3 (versão 3.11+)**.

#### Justificativa da Escolha:
1. **Foco Pedagógico e Clareza:** Facilita o estudo e visualização explícita dos conceitos de redes (Camada 4 TCP vs Camada 7 HTTP) sem abstrações opacas.
2. **Biblioteca Padrão Completa (Zero Dependências Obrigatórias):** Módulos como `socket`, `threading`, `asyncio`, `pathlib`, `logging` e `sqlite3` vêm pré-instalados com o runtime, viabilizando execução imediata sem necessidade de compilar extensões em C.
3. **Eficiência no Snapdragon 720G:** Baixo consumo de memória em idle (~15MB a 25MB de RAM para daemons de sockets) e baixo impacto térmico no smartphone.
4. **Facilidade de Evolução:** Permite transição fluida para frameworks web modernos assíncronos (como FastAPI e Uvicorn) no futuro.

---

### 3.2. Estrutura Padrão de Diretórios da Aplicação

```text
app/
├── server.py              # Ponto de entrada do servidor de aplicação (TCP socket)
├── client.py              # Cliente utilitário de teste e envio de mensagens
├── logs/                  # Diretório de persistência de logs locais
│   └── .gitkeep           # Preserva o diretório no repositório
└── requirements.txt       # Dependências externas opcionais (quando houver)
```

---

### 3.3. Padrões de Projeto e Diretrizes de Implementação

#### A. Comunicação de Baixo Nível (Camada de Transporte - TCP)
* **Interface de Bind:** O servidor deve fazer bind em `0.0.0.0` para aceitar requisições vindas da interface Wi-Fi local e de interfaces de VPN (Tailscale), e não apenas `127.0.0.1`.
* **Porta de Aplicação:** A porta base do servidor de sockets TCP é a porta **`9000`** (alta e não conflitante com serviços de sistema).
* **Tratamento de Socket:**
  * Uso de `SO_REUSEADDR` para evitar travamento da porta após encerramento do processo (`TIME_WAIT`).
  * Timeout configurável para evitar que sockets zumbis consumam descritores de arquivo indefinidamente.
* **Codificação:** Transmissão estritamente codificada em **UTF-8**.

#### B. Persistência de Dados e Logs
* **Formato do Log:** Cada registro de mensagem recebida deve conter timestamp legível, tupla de origem (IP e porta do cliente) e conteúdo textual limpo:
  ```text
  [AAAA-MM-DD HH:MM:SS] [IP_CLIENTE:PORTA_CLIENTE] MENSAGEM
  ```
* **Escrita Segura:** Abertura de arquivos em modo append (`"a"`), com flushing apropriado e garantia de existência prévia do diretório `logs/`.

#### C. Gerenciamento de Ciclo de Vida em Produção
Para manter o servidor Python rodando em background 24/7 no Termux com recuperação automática de falhas, recomenda-se o uso do **PM2**:

```bash
# Inicializar o servidor gerenciado pelo PM2
pm2 start app/server.py --name "tcp-server" --interpreter python3

# Verificar status e monitorar consumo
pm2 status
pm2 logs tcp-server

# Salvar lista de processos para autostart
pm2 save
```

---

## 4. Roteiro de Evolução da Stack

```text
[Fase 1: Conexão TCP Pura] (Atual)
└── Python nativo (socket), persistência em arquivo de log, porta 9000.

[Fase 2: Protocolo Estruturado]
└── Serialização de mensagens em JSON, autenticação por token leve, tratamento multi-cliente concorrente.

[Fase 3: Camada Web e Proxy Reverso]
└── API HTTP com FastAPI + Uvicorn na porta 8000, roteada pelo Caddy na porta 8080 com terminação TLS.

[Fase 4: Persistência Relacional]
└── Migração de logs e dados para PostgreSQL nativo (porta 5432) com pooling de conexões.
```
