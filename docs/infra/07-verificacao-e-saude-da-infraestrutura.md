# Módulo 07: Verificação, Pré-Voo e Saúde da Infraestrutura do Host

> **Status:** Documentado  
> **Host Alvo:** Xiaomi Redmi Note 9S (`curtana` / `miatoll` — Snapdragon 720G / ARM64)  
> **Ambiente Operacional:** Debian 11 (Bullseye via UserLAnd PRoot) + Python 3.9/3.11 venv nativo  
> **Script Oficial:** [`scripts/check-infra.sh`](file:///Users/naokiteruya/Projects/homelab/scripts/check-infra.sh)  
> **Suíte de Testes:** [`tests/test_check_infra.py`](file:///Users/naokiteruya/Projects/homelab/tests/test_check_infra.py)

---

## 1. Visão Geral e Contexto de Execução Real

O servidor do projeto **Homelab** é executado em um smartphone Android convencional (**Xiaomi Redmi Note 9S**) sem privilégios de superusuário (*root*). Devido à ausência de módulos de *cgroups*, *network namespaces* e *overlayfs* no kernel de fábrica do Android da Xiaomi (MIUI), a execução do Docker daemon (`dockerd`) é inviável sem custom kernels ([Módulo 04](./04-containers-docker-sem-root.md)).

A arquitetura adotada em produção consiste em:
1. **Camada de Compatibilidade Linux:** Debian 11 (Bullseye) executado em espaço de usuário via **UserLAnd** (baseado em PRoot).
2. **Acesso Remoto Administrativo:** Servidor OpenSSH escutando em porta não privilegiada (`2022`).
3. **Isolamento de Aplicação:** Ambiente virtual Python (`.venv`) nativo, com pacotes instalados via `pip` e gerenciamento de dependências via `requirements.txt`.
4. **Serviço Dual-Protocol:** Processo Python executando os canais TCP de Controle (porta `9000`) e Dados (porta `9001`).

```
+-----------------------------------------------------------------------+
| Xiaomi Redmi Note 9S (Snapdragon 720G - Octa-Core - 4GB/6GB RAM)      |
| Android 10/11/12 (MIUI) - Sem Root                                    |
|                                                                       |
|   +---------------------------------------------------------------+   |
|   | UserLAnd (PRoot) / Debian 11 Bullseye                         |   |
|   | OpenSSH Server (:2022)                                        |   |
|   |                                                               |   |
|   |   +-------------------------------------------------------+   |   |
|   |   | Python Virtual Environment (.venv)                    |   |   |
|   |   | app/server.py                                         |   |   |
|   |   |   - Canal de Controle: TCP :9000 (Framing + HMAC)     |   |   |
|   |   |   - Canal de Dados:    TCP :9001 (Chunks de 64KB)     |   |   |
|   |   |   - Armazenamento:     SQLite (homelab.db) + uploads/ |   |   |
|   |   +-------------------------------------------------------+   |   |
|   +---------------------------------------------------------------+   |
+-----------------------------------------------------------------------+
```

Para garantir que o servidor e seus clientes operem de forma confiável e previsível neste ambiente restrito, o Homelab implementa um **utilitário estrito de verificação de pré-voo e saúde**: o script [`scripts/check-infra.sh`](file:///Users/naokiteruya/Projects/homelab/scripts/check-infra.sh).

---

## 2. Filosofia Fail-Fast Estrito

Falhas de configuração — como portas sobrepostas, variáveis ausentes, arquivos inexistentes ou portas restritas ao superusuário — não devem ser descobertas após a subida dos servidores ou durante a conexão de clientes em produção. O princípio adotado é o **Fail-Fast Estrito**: *qualquer inconsistência aborta imediatamente a execução com código de saída 1 e mensagens diagnósticas claras*.

### 2.1. Ordem de Descoberta dos Arquivos de Ambiente (.env)

O utilitário segue uma hierarquia de descoberta determinística baseada no modo de operação:

| Modo de Execução | Ordem de Busca Automática |
| :--- | :--- |
| **Servidor (`--mode server` ou `--local`)** | 1. `envs/server.env`<br>2. `envs/.env`<br>3. `server.env`<br>4. `.env` |
| **Cliente (`--mode client` ou `--remote`)** | 1. `envs/client.env`<br>2. `envs/.env`<br>3. `client.env`<br>4. `.env` |
| **Arquivo Explícito (`--env-file <caminho>`)** | Carrega exatamente o caminho especificado (relativo ou absoluto). |

> [!IMPORTANT]
> Se o arquivo apontado via `--env-file` não existir, ou se nenhum dos candidatos padrão for localizado, o script emite `[FAIL]` e aborta com `exit 1`.

### 2.2. Matriz de Variáveis Obrigatórias

O script realiza o parse direto do arquivo (ignorando comentários iniciados por `#` e linhas em branco) e exige que todas as chaves abaixo estejam presentes e não-vazias:

| Variável | Modo Exigido | Descrição | Exemplo |
| :--- | :--- | :--- | :--- |
| `HOMELAB_SERVER_HOST` | Servidor | Interface IP de escuta do servidor | `0.0.0.0` |
| `HOMELAB_CLIENT_TARGET_HOST` | Cliente | IP LAN ou loopback do servidor remoto | `192.168.0.246` ou `127.0.0.1` |
| `HOMELAB_CONTROL_PORT` | Ambos | Porta TCP do canal de controle persistente | `9000` |
| `HOMELAB_DATA_PORT` | Ambos | Porta TCP do canal de transferência de arquivos | `9001` |
| `HOMELAB_HANDSHAKE_KEY` | Ambos | Segredo compartilhado para handshake e assinatura | `homelab-initial-handshake-key-32` |
| `HOMELAB_CHUNK_SIZE` | Ambos | Tamanho máximo de chunks de mídia em bytes | `65536` (64KB) |
| `HOMELAB_BUFFER_SIZE` | Servidor | Buffer do socket de controle do servidor | `4096` |
| `HOMELAB_CLIENT_BUFFER_SIZE` | Cliente | Buffer do socket de controle do cliente | `4096` |
| `HOMELAB_CLIENT_TIMEOUT` | Cliente | Timeout em segundos das operações de rede | `10.0` |
| `HOMELAB_DB_PATH` | Servidor | Caminho relativo do SQLite | `app/data/homelab.db` |
| `HOMELAB_LOG_PATH` | Servidor | Caminho relativo do log de mensagens | `app/logs/server_messages.log` |
| `HOMELAB_UPLOADS_DIR` | Servidor | Diretório de armazenamento de mídia | `app/data/uploads` |
| `HOMELAB_SESSION_PATH` | Cliente | Caminho do arquivo de sessão NoSQL | `app/data/client_session.json` |

### 2.3. Validação de Limites de Portas (Sem Root)

Em sistemas Linux/Android sem privilégios de root, portas abaixo de `1024` são **privilegiadas** e seu bind resultará em `PermissionDenied`. Além disso, os canais de controle e dados devem ser estritamente independentes.
* **Validação Numérica:** `HOMELAB_CONTROL_PORT` e `HOMELAB_DATA_PORT` devem ser números inteiros.
* **Faixa Segura:** Ambas as portas devem estar contidas no intervalo $[1024, 65535]$.
* **Prevenção de Colisão:** `HOMELAB_CONTROL_PORT` não pode ser igual a `HOMELAB_DATA_PORT`.

---

## 3. O Script de Pré-Voo (`scripts/check-infra.sh`)

O script [`scripts/check-infra.sh`](file:///Users/naokiteruya/Projects/homelab/scripts/check-infra.sh) é o utilitário central de validação pré-voo. Suporta execução em ambientes Linux, Debian (UserLAnd), Android (Termux) e macOS (Darwin).

### 3.1. Flags e Argumentos

```bash
scripts/check-infra.sh [OPÇÕES]
```

* `--mode <server|client>`: Define o perfil de validação (padrão: `server`).
* `--local`: Atalho para `--mode server`.
* `--remote`: Atalho para `--mode client`.
* `--env-only`: Executa estritamente as validações de arquivo `.env` e limites de portas, sem efetuar probes de rede nem checagens de host.
* `--env-file <caminho>`: Aponta para um arquivo de configuração customizado.
* `--ssh`: No modo cliente, executa probe ativo na porta do servidor SSH do smartphone.
* `--ssh-port <porta>`: Define a porta SSH para probe (padrão: `2022` para Debian UserLAnd; `8022` para Termux).
* `-h`, `--help`: Exibe a documentação inline das opções.

### 3.2. Checagens Locais do Host (`--mode server`)

Quando executado no servidor (sem `--env-only`), o script inspeciona os recursos do host físico:
1. **Identificação do Sistema:** Detecta se está rodando em Debian (UserLAnd no Redmi Note 9S), Android (Termux), macOS ou Linux genérico.
2. **Ambiente Python:** Localiza o interpretador do ambiente virtual (`.venv/bin/python3`, `$VIRTUAL_ENV` ou `python3`) e exibe a versão ativa.
3. **Memória RAM Disponível:** Analisa a memória livre (via `free -m` ou `sysctl`). Alerta com `[AVISO]` caso a RAM livre seja inferior a **300 MB**, patamar mínimo seguro para prevenir o encerramento do processo pelo *Low Memory Killer* (LMK) da MIUI.
4. **Espaço em Disco:** Verifica o armazenamento disponível na partição do projeto via `df -h`.
5. **Descritores de Arquivos (`ulimit -n`):** Alerta se o limite de arquivos abertos for inferior a `1024`, recomendando a elevação para suportar conexões concorrentes.
6. **Status do Servidor e Portas:** Identifica se o processo `app/server.py` está rodando e se as portas de Controle e Dados estão abertas e em escuta.

### 3.3. Checagens Remotas de Rede (`--mode client`)

Quando executado a partir da máquina cliente:
1. **Ping ICMP:** Testa se o host alvo (`HOMELAB_CLIENT_TARGET_HOST`) responde a pacotes ICMP.
2. **Probe TCP de Controle e Dados:** Realiza tentativa ativa de conexão socket com timeout configurável em ambas as portas, confirmando se o daemon está aceitando conexões.
3. **Probe de SSH Opcional (`--ssh`):** Testa a porta `2022` (ou `--ssh-port`) para confirmar se a administração remota está funcional.

---

## 4. Guia Prático de Uso

### 4.1. Validação Rápida em Pipeline de Testes ou Pré-Commit
Garante que os arquivos de configuração de exemplo ou locais estão íntegros e sem erros de sintaxe:
```bash
# Validar arquivo de exemplo do servidor
./scripts/check-infra.sh --mode server --env-file envs/server.env.sample --env-only

# Validar arquivo de exemplo do cliente
./scripts/check-infra.sh --mode client --env-file envs/client.env.sample --env-only

# Validar arquivo unificado de desenvolvimento
./scripts/check-infra.sh --mode server --env-file envs/.env.sample --env-only
```

### 4.2. Diagnóstico Local no Smartphone (Debian UserLAnd / Termux)
Antes de iniciar o servidor Python ou para diagnosticar lentidão/paradas:
```bash
# Entrar no diretório do projeto e rodar a checagem local
cd ~/homelab
./scripts/check-infra.sh --local
```

Saída típica esperada no host:
```text
=== Homelab Infra Check & Pre-Flight (Modo: SERVER) ===
[INFO] Arquivo de configuração selecionado: envs/server.env
[OK] Todas as variáveis obrigatórias estão presentes e preenchidas.
[OK] Validação de portas OK (Controle: 9000, Dados: 9001 - Faixa não-privilegiada sem conflito).

--- Checagens Locais do Host Servidor ---
[INFO] Sistema Operacional detectado: Debian 11 (UserLAnd no Xiaomi Redmi Note 9S)
[OK] Ambiente Python: /home/debian/homelab/.venv/bin/python3 (Python 3.9.2)
[OK] Memória RAM livre estimada: 820MB (>= 300MB).
[INFO] Espaço em disco no projeto: 24G livres de 64G (uso: 62%)
[OK] Limite de descritores de arquivo (ulimit -n): 4096 (>= 1024).
[OK] Processo do servidor em execução (PID: 12345)
[OK] Porta de Controle local (9000): EM ESCUTA
[OK] Porta de Dados local (9001): EM ESCUTA

=== Diagnóstico do Servidor Concluído com Sucesso ===
```

### 4.3. Verificação Remota a partir da Estação de Trabalho do Desenvolvedor
Para diagnosticar problemas de conectividade Wi-Fi e portas antes de disparar o cliente:
```bash
# Probe completo com verificação de SSH no UserLAnd
./scripts/check-infra.sh --remote --ssh --ssh-port 2022
```

---

## 5. Matriz de Diagnóstico e Resolução de Problemas

| Sintoma / Mensagem | Causa Provável | Ação de Correção |
| :--- | :--- | :--- |
| `[FAIL] Arquivo de configuração não encontrado` | O caminho em `--env-file` está incorreto ou `envs/server.env` / `envs/client.env` ainda não foi criado. | Copie o arquivo `.sample` correspondente:<br>`cp envs/server.env.sample envs/server.env` |
| `[FAIL] Variáveis obrigatórias ausentes ou vazias` | O arquivo `.env` não contém todas as chaves exigidas pela especificação. | Verifique a lista de chaves impressa pelo script e copie os valores ausentes a partir do arquivo `.sample`. |
| `[FAIL] HOMELAB_CONTROL_PORT (...) inválida: deve ser porta não privilegiada` | Foi configurada uma porta `< 1024` (ex: 80, 443). Sem root, o SO rejeita o bind. | Altere a porta para uma faixa não privilegiada (ex: `9000` para controle, `9001` para dados). |
| `[FAIL] Conflito de portas: HOMELAB_CONTROL_PORT e HOMELAB_DATA_PORT não podem ser iguais` | Ambas as portas foram configuradas com o mesmo número. | Configure portas distintas (ex: `9000` e `9001`). |
| `[AVISO] Memória RAM disponível baixa: < 300MB` | A MIUI ou outros processos no Android estão consumindo a memória do aparelho. | Feche aplicativos recentes no Android; verifique processos em background com `htop` no Debian. |
| `[AVISO] ulimit -n atual é inferior a 1024` | O limite padrão de descritores de arquivo da sessão é baixo. | Execute `ulimit -n 4096` na sessão do shell ou configure no arquivo `~/.bashrc`. |
| `[AVISO] Host alvo (...) não respondeu ao ping ICMP` | Firewall do roteador ou isolamento AP de Wi-Fi bloqueando ICMP; ou host com IP alterado. | Verifique se o smartphone continua conectado ao Wi-Fi com o IP correto; verifique se o isolamento de clientes está ativo no roteador. |
| `[AVISO] Canal de Controle (...:9000): INACESSÍVEL / CONEXÃO RECUSADA` | O script `app/server.py` não está em execução no host ou travou. | Conecte via SSH (`ssh -p 2022 ...`) e inicie o servidor: `python3 app/server.py`. |
| `[AVISO] Serviço SSH (...:2022): INACESSÍVEL` | O serviço OpenSSH dentro do UserLAnd não foi iniciado ou o app UserLAnd foi suspenso. | Abra o UserLAnd no celular para retomar a sessão e inicie o serviço com `sudo service ssh start`. |

---

## 6. Documentos Relacionados

* [Módulo 02: Rede, SSH e Acesso Remoto](./02-rede-ssh-e-acesso-remoto.md)
* [Módulo 04: Containers Docker Sem Root e Adoção do Debian UserLAnd](./04-containers-docker-sem-root.md)
* [Módulo 06: Spike de Capacidade e Limites Físicos do Host](./06-capacidade-e-limites-fisicos-do-host.md)
* [Módulo 005 (App): Gerenciamento de Configurações e Arquivos Env](../app/005-gerenciamento-de-configuracoes-e-env.md)
