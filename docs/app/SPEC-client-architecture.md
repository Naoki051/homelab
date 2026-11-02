# Especificação Técnica Canônica: Arquitetura Orientada a Objetos do Cliente e Protocolo Homelab

> **Status:** Aprovado  
> **Documento Canônico:** `docs/app/SPEC-client-architecture.md`  
> **Referência de Requisitos:** `ORIGINAL_REQUEST.md` (R1, R2, R3, R4)  
> **Débitos Técnicos Associados:** DEBT-01 (Arquitetura OO), DEBT-02 (Exceções de Domínio), DEBT-03 (Context Managers), DEBT-04 (Mascaramento de Segredos), DEBT-05 (Type Hints)  
> **Documentos Relacionados:** [`docs/INDEX.md`](../INDEX.md), [`docs/app/002-stack-definicao-e-arquitetura.md`](002-stack-definicao-e-arquitetura.md), [`docs/app/004-protocolos-controle-e-dados.md`](004-protocolos-controle-e-dados.md)

---

## 1. Visão Geral e Objetivos Arquiteturais

Este documento estabelece a especificação canônica da refatoração da camada cliente e do protocolo de rede do ecossistema Homelab.

### 1.1. Objetivos Principais
1. **Unificação do Contrato de Protocolo (`Package(ABC)`):** Introduzir a classe base abstrata `Package` em `app/protocol.py`, definindo contratos polimórficos de serialização (`to_frame_bytes`), transmissão (`send`) e desserialização (`read_frame`) herdados por `Message` (`ControlPackage`) e `MediaChunk` (`DataPackage`).
2. **Decomposição Modular do Pacote Cliente (`app/client/`):** Desacoplar o arquivo monolítico `app/client.py` em módulos de responsabilidade única:
   - `session.py`: Armazenamento de sessão local NoSQL (JSON) com Quick Login e permissões POSIX 0600.
   - `conn_handler.py`: Gerenciamento de conexões TCP (`ControlConnection` e `ClientConnectionHandler`).
   - `commands.py`: Padrão Command encapsulando operações de registro, login, envio de texto e upload de mídia.
   - `client.py`: Fachada de alto nível `HomelabClient` (com alias `Client`).
   - `menus.py`: Interface de linha de comando (`ClientTerminalUI`) com complexidade ciclomática <= 12.
   - `__init__.py` & `__main__.py`: Re-exportações públicas garantindo retrocompatibilidade total e entrypoint CLI.
3. **Compatibilidade Retroativa Imutável:** Manter preservada a sintaxe de importação `from app.client import Client, HomelabClient, ControlConnection` e `from app.client_session import Session` sem qualquer regressão nas suítes de teste existentes.
4. **Governança de Qualidade e Segurança:**
   - 100% de anotações de tipo estático (PEP 484).
   - Zero ocorrências de exceções genéricas (`except Exception:`), adotando a hierarquia oficial em `app.exceptions`.
   - Gerenciamento determinístico de sockets via Context Managers (`with`, `contextlib.closing`).
   - Mascaramento estrito de senhas, chaves HMAC e tickets em logs (`mask_secret`, `mask_password`).
   - Linhas com comprimento máximo de 100 caracteres e complexidade ciclomática por método <= 12.

---

## 2. Especificação do Protocolo Base (`Package(ABC)`)

O protocolo de rede do Homelab opera sob a arquitetura dual-channel (Canal de Controle :9000 e Canal de Dados :9001). A classe base abstrata `Package` padroniza o ciclo de vida dos quadros binários trafegados em ambas as portas.

### 2.1. Hierarquia de Classes

```text
               +--------------------------------------+
               |         Package(ABC)                 |
               +--------------------------------------+
               | + to_frame_bytes(hmac_key, **kw)     |
               | + send(sock, hmac_key, **kw)         |
               | + read_frame(sock, hmac_key, **kw)   |
               +--------------------------------------+
                                   ^
                                   |
         +-------------------------+-------------------------+
         |                                                   |
+-----------------------------------+   +------------------------------------+
|     Message (ControlPackage)      |   |      MediaChunk (DataPackage)      |
+-----------------------------------+   +------------------------------------+
| - Canal: Porta 9000 (Persistente) |   | - Canal: Porta 9001 (Streaming)    |
| - Header: 40 bytes (>2sHI32s)     |   | - Header: 62 bytes (>2s16sIII32s)  |
| - Payload: JSON UTF-8 (máx 64KB)  |   | - Payload: Binário bruto (máx 64KB)|
+-----------------------------------+   +------------------------------------+
```

### 2.2. Contrato da Classe Base `Package(ABC)` em `app/protocol.py`

```python
from abc import ABC, abstractmethod
import socket
from typing import Optional, Union

class Package(ABC):
    """Classe base abstrata para todos os pacotes enquadrados do protocolo Homelab."""

    @abstractmethod
    def to_frame_bytes(
        self,
        hmac_key: Optional[Union[bytes, str]] = None,
        **kwargs
    ) -> bytes:
        """Serializa o pacote em bytes binários enquadrados com assinatura HMAC-SHA256."""
        pass

    @abstractmethod
    def send(
        self,
        sock: socket.socket,
        hmac_key: Optional[Union[bytes, str]] = None,
        **kwargs
    ) -> None:
        """Transmite o pacote binário enquadrado através do socket conectado."""
        pass

    @classmethod
    @abstractmethod
    def read_frame(
        cls,
        sock: socket.socket,
        hmac_key: Optional[Union[bytes, str]] = None,
        **kwargs
    ) -> Optional["Package"]:
        """Lê, desenquadra e valida a assinatura HMAC de um pacote completo do socket."""
        pass
```

### 2.3. Especificação do Canal de Controle (`Message` / `ControlPackage`)
- **Porta:** 9000 (TCP persistente).
- **Cabeçalho:** Fixo de 40 bytes em formato Big-Endian (`CONTROL_HEADER_FORMAT = ">2sHI32s"`):
  - `Magic`: `b"HC"` (2 bytes).
  - `MsgType`: `uint16` (2 bytes, 1 = Requisição, 2 = Resposta).
  - `PayloadLength`: `uint32` (4 bytes, limite máximo de 65536 bytes).
  - `HMAC-SHA256`: 32 bytes calculados sobre `Magic || MsgType || PayloadLength || PayloadJSON`.
- **Payload:** String codificada em JSON UTF-8 contendo campos `action`, `payload` e `timestamp`.
- **Implementação dos Métodos Polimórficos:**
  - `to_frame_bytes(hmac_key=None, msg_type=None, **kwargs) -> bytes`: Invoca `self.to_frame(hmac_key=hmac_key, msg_type=msg_type)`.
  - `send(sock, hmac_key=None, msg_type=None, **kwargs) -> None`: Invoca `self.send_framed(sock, hmac_key=hmac_key, msg_type=msg_type)`.
  - `read_frame(sock, hmac_key=None, **kwargs) -> Optional[Message]`: Invoca `cls.recv_framed(sock, hmac_key=hmac_key)`.
- **Métodos Preservados para Retrocompatibilidade:** `to_dict()`, `to_json()`, `to_bytes()`, `to_frame()`, `from_dict()`, `from_json()`, `from_bytes()`, `from_frame()`, `send_framed()`, `recv_framed()`, `response()`.

### 2.4. Especificação do Canal de Dados (`MediaChunk` / `DataPackage`)
- **Porta:** 9001 (TCP streaming sob demanda).
- **Cabeçalho:** Fixo de 62 bytes em formato Big-Endian (`CHUNK_HEADER_FORMAT = ">2s16sIII32s"`):
  - `Magic`: `b"HD"` (2 bytes).
  - `Ticket`: 16 bytes brutos do token de upload emitido pelo servidor.
  - `ChunkIndex`: `uint32` (4 bytes, 0 <= chunk_index < total_chunks).
  - `TotalChunks`: `uint32` (4 bytes, > 0).
  - `DataLength`: `uint32` (4 bytes, limite máximo de 65536 bytes).
  - `HMAC-SHA256`: 32 bytes calculados sobre `Magic || Ticket || ChunkIndex || TotalChunks || DataLength || DataBytes`.
- **Payload:** Bytes brutos do fragmento de arquivo (fatiado em até 64 KB).
- **Implementação dos Métodos Polimórficos:**
  - `to_frame_bytes(hmac_key=None, **kwargs) -> bytes`: Invoca `self.to_bytes(hmac_key=hmac_key)`.
  - `send(sock, hmac_key=None, **kwargs) -> None`: Transmite `self.to_bytes(hmac_key)` via `sock.sendall()`.
  - `read_frame(sock, hmac_key=None, **kwargs) -> Optional[MediaChunk]`: Invoca `cls.recv_from_socket(sock, key_resolver=hmac_key)`.
- **Métodos Preservados para Retrocompatibilidade:** `to_bytes()`, `from_bytes()`, `send()`, `recv_from_socket()`, `slice_file()`, `compute_mac()`.

### 2.5. Regras de Gerenciamento da Chave Criptográfica HMAC
1. **Handshake Pré-Autenticação:** Mensagens de `register` e `login` são assinadas e validadas com `DEFAULT_HANDSHAKE_KEY = b"homelab-initial-handshake-key-32"`.
2. **Rotação para Chave de Sessão Dinâmica:** No sucesso da autenticação ou cadastro, o servidor gera 32 bytes criptograficamente aleatórios (`os.urandom(32)`) e os retorna em hexadecimal na resposta. O cliente rotaciona imediatamente a chave ativa de sua `ControlConnection`.
3. **Prevenção de Timing Attacks:** Toda validação de HMAC deve utilizar `hmac.compare_digest`.
4. **Normalização de Chaves (`normalize_hmac_key`):** Suporta `bytes`, `str` em hexadecimal (64 caracteres) ou `None` (retornando a chave padrão).

---

## 3. Arquitetura Modular do Pacote Cliente (`app/client/`)

A decomposição substitui o monolito `app/client.py` por uma estrutura em pacote de 7 arquivos:

```text
app/client/
├── __init__.py        # Re-exportações públicas e aliases
├── __main__.py        # Ponto de entrada CLI (python -m app.client)
├── session.py         # Gestão de sessão local NoSQL (Session)
├── conn_handler.py    # Conexões de rede TCP (ControlConnection, ClientConnectionHandler)
├── commands.py        # Padrão Command (Register, Login, SendMessage, UploadFile, Logout)
├── client.py          # Fachada principal (HomelabClient, Client)
└── menus.py           # Interface de terminal CLI (ClientTerminalUI)
```

### 3.1. Módulo `app/client/session.py`
- **Responsabilidade:** Persistência de credenciais locais em arquivo JSON (`client_session.json`) para Quick Login.
- **Assinatura da Classe:**
  ```python
  class Session:
      DEFAULT_TTL_DAYS: int = 7
      DEFAULT_SESSION_FILE: Path

      def __init__(self, last_username: str, last_password: str, expire_date_time: str) -> None: ...
      @staticmethod
      def derive_secret(username: str, raw_password: str) -> str: ...
      def is_valid(self) -> bool: ...
      def time_remaining(self) -> str: ...
      def to_dict(self) -> Dict[str, Any]: ...
      @classmethod
      def create(cls, username: str, password_value: str, is_already_derived: bool = False, days: int = DEFAULT_TTL_DAYS) -> "Session": ...
      def save(self, path: Optional[Path] = None) -> None: ...
      @classmethod
      def load(cls, path: Optional[Path] = None) -> Optional["Session"]: ...
      @classmethod
      def clear(cls, path: Optional[Path] = None) -> None: ...
  ```
- **Invariantes de Segurança:**
  - Aplicação estrita de `os.chmod(target_path, 0o600)` ao salvar.
  - Derivação salted SHA-256 (`username.strip().lower() + ":" + password`) impedindo armazenamento de senhas em texto puro.
  - Tratamento determinístico de `StorageError` e JSON corrompido retornando `None`.

### 3.2. Módulo `app/client/conn_handler.py`
- **Responsabilidade:** Gerenciamento dos sockets TCP no Canal de Controle (:9000) e no Canal de Dados (:9001).
- **Assinatura da Classe `ControlConnection`:**
  ```python
  class ControlConnection:
      host: str
      port: int
      timeout: float
      sock: Optional[socket.socket]
      session_key: bytes
      username: Optional[str]

      def __init__(self, host: str = ..., port: int = ..., timeout: float = ...) -> None: ...
      def connect(self) -> bool: ...
      def send_request(self, message: Message) -> Optional[Message]: ...
      def login(self, username: str, secret_hash: str) -> Tuple[bool, str]: ...
      def register(self, username: str, secret_hash: str) -> Tuple[bool, str]: ...
      def send_text(self, username: str, text: str, secret_hash: str = "") -> bool: ...
      def upload_file(self, file_path: Union[Path, str], data_port: Optional[int] = None, secret_hash: str = "") -> Tuple[bool, str]: ...
      def close(self) -> None: ...
      def __enter__(self) -> "ControlConnection": ...
      def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...
  ```
- **Assinatura da Classe `ClientConnectionHandler`:**
  ```python
  class ClientConnectionHandler:
      """Gerenciador utilitário para sockets TCP efêmeros no canal de dados."""
      def __init__(self, host: str, timeout: float = 10.0) -> None: ...
      def open_data_socket(self, port: int) -> socket.socket: ...
  ```
- **Utilitários do Módulo:**
  - `_compute_file_sha256(file_path: Path) -> str`: Streaming em blocos de 64 KB.
  - `send_network_message(host, port, message, use_framing=False, hmac_key=...) -> Optional[Message]`: Wrapper de conexão efêmera para compatibilidade legada.

### 3.3. Módulo `app/client/commands.py`
- **Responsabilidade:** Encapsulamento das ações do cliente via Padrão Command.
- **Estrutura:**
  ```python
  class ClientCommand(ABC):
      @abstractmethod
      def execute(self, conn: ControlConnection) -> Tuple[bool, Any]: ...

  class RegisterCommand(ClientCommand):
      def __init__(self, username: str, password_or_hash: str, is_already_derived: bool = False) -> None: ...
      def execute(self, conn: ControlConnection) -> Tuple[bool, str]: ...

  class LoginCommand(ClientCommand):
      def __init__(self, username: str, password_or_hash: str, is_already_derived: bool = False) -> None: ...
      def execute(self, conn: ControlConnection) -> Tuple[bool, str]: ...

  class SendMessageCommand(ClientCommand):
      def __init__(self, text: str) -> None: ...
      def execute(self, conn: ControlConnection) -> Tuple[bool, str]: ...

  class UploadFileCommand(ClientCommand):
      def __init__(self, file_path: Union[str, Path], data_port: Optional[int] = None) -> None: ...
      def execute(self, conn: ControlConnection) -> Tuple[bool, str]: ...

  class LogoutCommand(ClientCommand):
      def execute(self, conn: ControlConnection) -> Tuple[bool, str]: ...
  ```

### 3.4. Módulo `app/client/client.py`
- **Responsabilidade:** Fachada pública orientada a objetos `HomelabClient` (com alias `Client = HomelabClient`).
- **Assinatura Pública Completa:**
  ```python
  class HomelabClient:
      config: ClientConfig
      session: Optional[Session]
      control_conn: Optional[ControlConnection]
      username: Optional[str]
      secret_hash: Optional[str]

      def __init__(
          self,
          config: Optional[ClientConfig] = None,
          host: Optional[str] = None,
          port: Optional[int] = None,
          control_port: Optional[int] = None,
          data_port: Optional[int] = None,
          timeout: Optional[float] = None,
          session: Optional[Session] = None,
          session_path: Optional[Union[Path, str]] = None,
          control_conn: Optional[ControlConnection] = None,
          env_file: Optional[Union[Path, str]] = None,
      ) -> None: ...

      @property
      def host(self) -> str: ...
      @property
      def control_port(self) -> int: ...
      @property
      def data_port(self) -> int: ...
      @property
      def is_connected(self) -> bool: ...
      @property
      def session_key(self) -> bytes: ...

      def connect(self) -> bool: ...
      def login(self, username: str, password: Optional[str] = None, is_already_derived: bool = False) -> Tuple[bool, str]: ...
      def register(self, username: str, password: Optional[str] = None, is_already_derived: bool = False) -> Tuple[bool, str]: ...
      def send_message(self, text: str) -> Tuple[bool, str]: ...
      def upload_file(self, file_path: Union[str, Path], data_port: Optional[int] = None) -> Tuple[bool, str]: ...
      def close(self) -> None: ...
      def __enter__(self) -> "HomelabClient": ...
      def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...

  # Alias retrocompatível
  Client = HomelabClient
  ```

### 3.5. Módulo `app/client/menus.py`
- **Responsabilidade:** Interface interativa de linha de comando com prompts, menu de opções e envio de comandos.
- **Classe `ClientTerminalUI` e Decomposição de Complexidade:**
  Para atender à regra mandatória do `.flake8` (`max-complexity = 12`), o fluxo de autenticação é dividido em métodos especializados com complexidade ciclomática <= 5:
  ```python
  class ClientTerminalUI:
      def __init__(self, client: HomelabClient) -> None: ...
      def run_auth_flow(self) -> Optional[Tuple[str, str]]: ...
      def _handle_quick_login(self) -> Optional[Tuple[str, str]]: ...
      def _handle_credentials_login(self) -> Optional[Tuple[str, str]]: ...
      def _handle_registration(self) -> Optional[Tuple[str, str]]: ...
      def interactive_menu(self) -> None: ...
  ```
- **Wrappers Funcionais Globais (Retrocompatibilidade):**
  - `run_auth_flow(host=..., port=..., conn=..., client=...) -> Optional[Tuple[str, str]]`
  - `interactive_menu(client: HomelabClient) -> None`
  - `do_login_request(host, port, username, secret_hash, conn=None) -> Tuple[bool, str]`
  - `do_register_request(host, port, username, secret_hash, conn=None) -> Tuple[bool, str]`
  - `send_user_message(host, port, username, secret_hash, text, conn=None) -> bool`
  - `main() -> None`: Parse de argumentos CLI (`--env-file`, `--host`, `--port`, `--data-port`, `-m/--message`, `-u/--upload`) e execução do ciclo de vida.

### 3.6. Módulos `__init__.py` e `__main__.py`
- **`app/client/__init__.py`:**
  ```python
  from app.client.client import Client, HomelabClient
  from app.client.conn_handler import ControlConnection, send_network_message
  from app.client.menus import (
      do_login_request,
      do_register_request,
      interactive_menu,
      main,
      run_auth_flow,
      send_user_message,
  )
  from app.client.session import Session

  __all__ = [
      "HomelabClient",
      "Client",
      "ControlConnection",
      "Session",
      "send_network_message",
      "do_login_request",
      "do_register_request",
      "send_user_message",
      "run_auth_flow",
      "interactive_menu",
      "main",
  ]
  ```
- **`app/client/__main__.py`:**
  ```python
  from app.client.menus import main

  if __name__ == "__main__":
      main()
  ```

---

## 4. Diretrizes de Retrocompatibilidade

1. **Remoção Segura de `app/client.py`:**
   O arquivo monolítico `app/client.py` é removido e substituído pelo diretório de pacote `app/client/`. Como `__init__.py` re-exporta todas as classes e funções históricas, nenhuma instrução `import app.client` ou `from app.client import ...` sofrerá quebra.
2. **Preservação de `app/client_session.py`:**
   Para garantir que nenhum script de automação ou teste que importe diretamente `app.client_session` falhe, o arquivo `app/client_session.py` permanece como um wrapper de re-exportação:
   ```python
   """Wrapper de compatibilidade retroativa para app.client_session."""
   from app.client.session import Session

   __all__ = ["Session"]
   ```
3. **Assinaturas de Métodos Públicos:**
   Todos os parâmetros de `HomelabClient.__init__` (`config`, `host`, `port`, `control_port`, `data_port`, `timeout`, `session`, `session_path`, `control_conn`, `env_file`) são mantidos rigorosamente.

---

## 5. Diretrizes de Tratamento de Exceções e Segurança

1. **Hierarquia Canônica de Exceções (`app/exceptions.py`):**
   - Violações de formato, magic bytes ou truncamento de frame: levantar `ProtocolError`.
   - Divergência ou adulteração na assinatura HMAC: levantar `HMACVerificationError`.
   - Falhas de autenticação ou login inválido: levantar `AuthenticationError`.
   - Sessão NoSQL expirada ou revogada: levantar `SessionExpiredError`.
   - Falhas de gravação em disco ou corrupção de JSON: levantar `StorageError`.
   - Timeouts de socket TCP: levantar `NetworkTimeoutError`.
2. **Proibição de `except Exception:`:**
   - Em camadas internas de rede, capturar explicitamente tuplas de I/O de socket: `(ConnectionResetError, BrokenPipeError, TimeoutError, socket.timeout, OSError)`.
   - Em métodos da fachada (`login`, `register`, `send_message`, `upload_file`), registrar o erro contextualizado via `logger.error` e retornar tupla `(False, mensagem_amigável)` sem propagar unhandled exceptions.
3. **Mascaramento Obrigatório de Dados Sensíveis:**
   - Toda emissão de logs ou mensagens contendo senhas deve usar `mask_password(pwd)`.
   - Toda emissão de logs contendo chaves de sessão HMAC, tickets de upload ou hashes deve usar `mask_secret(token)`.

---

## 6. Governança de Código e Critérios de Aceitação

1. **Linhas e Complexidade:**
   - Nenhum arquivo em `app/client/` ou `app/protocol.py` pode ultrapassar 100 caracteres por linha.
   - Nenhuma função ou método pode possuir complexidade ciclomática superior a 12.
2. **Execução de Testes Automatizados:**
   - `python3 -m unittest discover -s tests -v` deve passar com 100% de taxa de sucesso.
   - `python3 -m unittest tests/test_adversarial_protocol_stress.py -v` deve passar com 100% de sucesso.
