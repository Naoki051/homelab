# Registro Canônico de Débitos Técnicos e Roadmap de Refatoração

> **Status:** Ativo  
> **Propósito:** Mapear, quantificar e orientar a resolução progressiva dos débitos técnicos acumulados na camada de código do Homelab, preservando o funcionamento atual e guiando as próximas fases de evolução.

---

## 1. Visão Geral dos Débitos Mapeados

A tabela abaixo sumariza as divergências técnicas identificadas no repositório, categorizadas por prioridade de mitigação e impacto arquitetural:

| ID | Área / Domínio | Gravidade | Descrição do Débito | Alvo da Refatoração | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **DEBT-01** | **Arquitetura OO da Rede** | Média | Camada de sockets e threads procedural em `server.py` e `client.py` refatorada para pacotes modulares OO | Classes `HomelabServer`, `ControlServer`, `DataServer`, `HomelabClient` e `Package(ABC)` | **Resolvido** (2026-11-02) |
| **DEBT-02** | **Exceções Genéricas** | Alta | 22 ocorrências de `except Exception:` e capturas sem tipagem | Adoção estrita da hierarquia em `app/exceptions.py` | Ativo |
| **DEBT-03** | **Gerenciamento de Recursos** | Alta | `ResourceWarning: unclosed database` e sockets sem `with` | Uso mandatório de Context Managers e fechamento garantido | Ativo |
| **DEBT-04** | **Logging vs `print`** | Média | Uso de `print()` solto em código de servidor e ausência de mascarador | Padronização em `logging` nativo com `mask_secret()` | Ativo |
| **DEBT-05** | **Tipagem Estática (PEP 484)**| Baixa | Funções com tipagem parcial ou retorno implícito | 100% de type hints nas assinaturas públicas | Ativo |

---

## 2. Detalhamento e Plano de Mitigação por Débito

### DEBT-01: Arquitetura Cliente-Servidor Orientada a Objetos (OO)

> **Status:** **RESOLVIDO**  
> **Data de Resolução:** 2026-11-02  
> **Branch de Resolução:** `refactor/client-server-oo-architecture`  
> **Commits:** `0ffc014` (setup gitignore), `de9a324` (especificações canônicas), `b5e892c` (protocolo Package ABC), `0e083a1` (pacote modular client), `273f25c` (pacote modular server), `3644f94` (cleanup determinístico de presença)  
> **Validação de Testes:** 84/84 testes unitários e de integração (100% OK) | 20/20 testes adversariais de concorrência e estresse (100% OK)  
> **Documentos Canônicos:** [`docs/app/SPEC-client-architecture.md`](app/SPEC-client-architecture.md) e [`docs/app/SPEC-server-architecture.md`](app/SPEC-server-architecture.md)

#### Diagnóstico Histórico (Legado):
- No monólito original `app/server.py`, o ciclo de vida dos listeners era iniciado por funções procedurais (`start_control_server`, `start_data_server`), orquestradas por threads manuais em `main()`.
- No monólito original `app/client.py`, o envio de mensagens e uploads era gerenciado por uma cascata de funções procedurais misturadas com o menu de terminal (`interactive_menu`).
- Embora existissem classes de dados (`UploadTicket`, `UploadTicketManager`, `ClientRepository`), a camada de rede e despacho de comandos carecia de encapsulamento OO e abstração polimórfica.

#### Resolução Implementada e Entregue:
1. **Classe Base Abstrata de Protocolo (`Package(ABC)` em `app/protocol.py`):**
   - Contratos polimórficos de serialização (`to_frame_bytes`), transmissão (`send`) e leitura (`read_frame`).
   - Herança implementada por `Message` (`ControlPackage`, porta 9000, 40B header + JSON) e `MediaChunk` (`DataPackage`, porta 9001, 62B header + binário).
2. **Pacote Modular do Cliente (`app/client/`):**
   - Decomposição em módulos de responsabilidade única:
     - `session.py`: Armazenamento de sessão local NoSQL (JSON) com Quick Login e permissões POSIX 0600.
     - `conn_handler.py`: Gerenciamento de conexões TCP (`ControlConnection` e `ClientConnectionHandler`).
     - `commands.py`: Padrão Command (`RegisterCommand`, `LoginCommand`, `SendMessageCommand`, `UploadFileCommand`, `LogoutCommand`).
     - `client.py`: Fachada de alto nível `HomelabClient` (alias `Client`).
     - `menus.py`: Interface interativa de linha de comando (`ClientTerminalUI`) com complexidade ciclomática <= 12.
     - `__init__.py` e `__main__.py`: Re-exportações públicas garantindo retrocompatibilidade total e entrypoint CLI (`python3 -m app.client`).
   - Re-exportação mantida em `app/client_session.py` para compatibilidade retroativa com código legado.
3. **Pacote Modular do Servidor (`app/server/`):**
   - Decomposição em módulos desacoplados:
     - `tickets.py`: `UploadTicketManager` thread-safe com lock de concorrência, expiração e integridade SHA-256.
     - `commands.py`: Contexto `ServerCommandContext`, estrutura `ServerCommandResult`, `ServerCommandDispatcher` e handlers dedicados (`RegisterCommandHandler`, `LoginCommandHandler`, `SendMessageCommandHandler`, `RequestUploadCommandHandler`, `LogoutCommandHandler`).
     - `conn_handler.py`: Serviços de rede `BaseNetworkService`, `ControlServer` (:9000) e `DataServer` (:9001).
     - `server.py`: Fachada `HomelabServer` (alias `Server`, `DualChannelServer`).
     - `__init__.py` e `__main__.py`: Re-exportações públicas e entrypoint executável via `python3 -m app.server`.
4. **Remoção Segura de Monólitos:**
   - Remoção completa de `app/client.py` e `app/server.py` sem breaking changes em imports ou APIs públicas.
5. **Invariantes de Segurança e Presença:**
   - Autenticação PBKDF2 com salt aleatório de 16B e 100.000 iterações.
   - Chave de sessão HMAC emitida dinamicamente no login e vinculada a tickets de upload.
   - Ciclo de vida determinístico de presença (online no login, offline no logout ou em disconnect abrupto/broken pipe).

#### Estrutura Arquitetural Entregue:
```mermaid
classDiagram
    class BaseNetworkService {
        <<abstract>>
        +str host
        +int port
        +socket socket
        +bool is_running
        +start() void
        +stop() void
    }

    class ControlServer {
        +ClientRepository repo
        +UploadTicketManager ticket_mgr
        +handle_connection(sock, addr) void
    }

    class DataServer {
        +UploadTicketManager ticket_mgr
        +handle_chunk_stream(sock, addr) void
    }

    class HomelabServer {
        +ServerConfig config
        +ControlServer control
        +DataServer data
        +start() void
        +stop() void
    }

    class HomelabClient {
        +ClientConfig config
        +SessionStore session
        +send_message(msg) bool
        +upload_file(path) bool
        +close() void
    }

    BaseNetworkService <|-- ControlServer
    BaseNetworkService <|-- DataServer
    HomelabServer *-- ControlServer
    HomelabServer *-- DataServer
```

---

### DEBT-02: Eliminação de Exceções Genéricas (`except Exception:`)

#### Diagnóstico Atual:
Foram catalogadas **22 ocorrências** onde blocos `except Exception:` ou capturas indiscriminadas mascaram possíveis falhas ou dificultam o rastreamento da causa raiz:
1. `app/client_session.py`: Linhas 59 e 121 (ao ler e persistir sessão JSON).
2. `app/config.py`: Linha 73 (ao converter valores tipados do arquivo .env).
3. `app/server.py`: Linhas 315, 409, 416, 500, 506, 511, 631 (desconexões e streams de chunks).
4. `app/client.py`: Linhas 131, 250, 254, 295 (tratamento de sockets de controle e dados).

#### Estratégia de Mitigação:
- Substituir cada ocorrência pela classe especializada de [`app/exceptions.py`](../app/exceptions.py):
  - Erros de framing ou payload $\rightarrow$ `ProtocolError` / `HMACVerificationError`.
  - Credenciais ou usuários inválidos $\rightarrow$ `AuthenticationError` / `SessionExpiredError`.
  - Falha em arquivos e SQLite $\rightarrow$ `StorageError`.
  - Timeouts de conexão $\rightarrow$ `NetworkTimeoutError`.
- Registrar sempre o log com contexto (`logger.error("Falha no cliente %s: %s", client_ip, exc, exc_info=True)`).

---

### DEBT-03: Gerenciamento Determinístico de Recursos (Context Managers)

#### Diagnóstico Atual:
A execução da suíte de testes unitários acusa avisos do coletor de lixo do Python:
```text
ResourceWarning: unclosed database in <sqlite3.Connection object at 0x1012235b0>
```
Conexões de banco SQLite e instâncias de socket em determinadas rotinas de exceção não são fechadas imediatamente, aguardando o garbage collector. No ambiente Android (Snapdragon 720G / Debian UserLAnd), o limite de descritores de arquivo (`ulimit -n`) é finito e precisa ser preservado.

#### Estratégia de Mitigação:
- Adotar o padrão `with` (Context Manager) ou blocos `try...finally: conn.close()` determinísticos em todas as consultas a [`app/database.py`](../app/database.py).
- Garantir o fechamento de sockets em métodos `close()` e em tratadores de erro com `contextlib.closing`.

---

### DEBT-04: Substituição de `print()` Solto por Logging e Mascaramento

#### Diagnóstico Atual:
- O servidor e o cliente realizam impressões no terminal usando `print("[*] Tentativa de login...")` ou `print("[+] Sucesso")`.
- Falta um filtro padronizado para garantir que dados confidenciais (senhas, hashes PBKDF2 ou chaves de sessão HMAC dinâmicas) nunca vazem em logs ou na saída de depuração.

#### Estratégia de Mitigação:
- Configurar o módulo nativo `logging` em `app/server.py` com formatação padronizada:
  ```text
  [%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s
  ```
- Introduzir a função utilitária `mask_secret(val: str) -> str` para mascarar credenciais e tokens em qualquer saída:
  - Senhas: `***`
  - Hashes/Chaves: `a1b2...9f8e` (apenas primeiros e últimos caracteres)
- Restringir `print()` estritamente à interface interativa de CLI em `app/client.py`.

---

### DEBT-05: Cobertura Completa de Tipagem Estática (Type Hints)

#### Diagnóstico Atual:
Determinadas funções utilitárias em módulos legados não possuem tipagem explícita de retorno (`-> None` ou `-> bool`) e utilizam tipos ambíguos para tuplas e dicionários.

#### Estratégia de Mitigação:
- Anotar 100% das funções e métodos públicos conforme a PEP 484 e PEP 526.
- Habilitar checagem gradual com linters estáticos.

---

## 3. Matriz de Priorização para Próximas Branches

| Ciclo | Ação Planejada | Branches Relacionadas |
| :--- | :--- | :--- |
| **Sprint 1** | Resolução do DEBT-03 (Context Managers & SQLite) e DEBT-02 (Exceções de Domínio) | `refactor/exceptions-and-resources` |
| **Sprint 2** | Resolução do DEBT-04 (Logging Nativo & Mascaramento de Segredos) | `refactor/logging-and-masking` |
| **Sprint 3** | Resolução do DEBT-01 (Arquitetura OO de Rede) e DEBT-05 (Type Hints) | `refactor/client-server-oo-architecture` (DEBT-01 Concluído) |
