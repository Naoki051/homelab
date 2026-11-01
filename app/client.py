#!/usr/bin/env python3
"""
Cliente TCP Dual-Protocol para Homelab com Autenticação, Conexão Persistente, HMAC Dinâmico e Upload em Chunks
Oferece suporte a:
1. Canal de Controle Persistente (Porta 9000): Framing binário (40B) + HMAC-SHA256 com chave de sessão dinâmica.
2. Canal de Dados/Mídia (Porta 9001): Upload de imagens/arquivos em Chunks indexados de 64KB (62B header) + HMAC.
3. Quick Login automático (NoSQL / JSON local válido por até 7 dias).
"""

import argparse
import contextlib
import getpass
import hashlib
import json
from pathlib import Path
import socket
import sys
from types import TracebackType
from typing import Any, Dict, List, Optional, Tuple, Type, Union

# Garante que a raiz do projeto esteja no sys.path para suportar execução a partir de qualquer diretório
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from app.client_session import Session
    from app.config import ClientConfig, load_client_config
    from app.exceptions import (
        AuthenticationError,
        HMACVerificationError,
        HomelabError,
        NetworkTimeoutError,
        ProtocolError,
        SessionExpiredError,
        StorageError,
        mask_password,
        mask_secret,
    )
    from app.logging import get_logger
    from app.protocol import (
        CHUNK_SIZE,
        CONTROL_MAGIC,
        DEFAULT_HANDSHAKE_KEY,
        MediaChunk,
        Message,
    )
except ImportError:
    from client_session import Session  # type: ignore
    from config import ClientConfig, load_client_config  # type: ignore
    from exceptions import (  # type: ignore
        AuthenticationError,
        HMACVerificationError,
        HomelabError,
        NetworkTimeoutError,
        ProtocolError,
        SessionExpiredError,
        StorageError,
        mask_password,
        mask_secret,
    )
    from logging_compat import get_logger  # type: ignore
    from protocol import (  # type: ignore
        CHUNK_SIZE,
        CONTROL_MAGIC,
        DEFAULT_HANDSHAKE_KEY,
        MediaChunk,
        Message,
    )

logger = get_logger(__name__)


_initial_client_config = load_client_config()
DEFAULT_HOST = _initial_client_config.host
DEFAULT_PORT = _initial_client_config.control_port
DEFAULT_DATA_PORT = _initial_client_config.data_port
DEFAULT_HANDSHAKE_KEY = _initial_client_config.handshake_key
TIMEOUT_SECONDS = _initial_client_config.timeout
BUFFER_SIZE = _initial_client_config.buffer_size
CHUNK_SIZE = _initial_client_config.chunk_size
DEFAULT_SESSION_FILE = _initial_client_config.session_path
Session.DEFAULT_SESSION_FILE = DEFAULT_SESSION_FILE


def _compute_file_sha256(file_path: Path) -> str:
    """Calcula o hash SHA-256 de um arquivo lendo em blocos de 64 KB."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            block = f.read(CHUNK_SIZE)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


class ControlConnection:
    """
    Mantém uma conexão TCP persistente no Canal de Controle (Porta 9000)
    com Framing Binário e rotação automática para a `session_key` dinâmica após autenticação.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = TIMEOUT_SECONDS,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.session_key: bytes = DEFAULT_HANDSHAKE_KEY
        self.username: Optional[str] = None

    def connect(self) -> bool:
        """Abre a conexão TCP persistente com o servidor, caso ainda não esteja aberta."""
        if self.sock is not None:
            return True
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            s.connect((self.host, self.port))
            self.sock = s
            self.session_key = DEFAULT_HANDSHAKE_KEY
            return True
        except ConnectionRefusedError:
            print(
                f"\n[!] Erro: Conexão recusada em {self.host}:{self.port}. "
                "Certifique-se de que o servidor está rodando.",
                file=sys.stderr,
            )
            s.close()
            return False
        except OSError as e:
            print(f"\n[!] Erro ao conectar em {self.host}:{self.port}: {e}", file=sys.stderr)
            s.close()
            return False

    def send_request(self, message: Message) -> Optional[Message]:
        """Envia uma mensagem enquadrada (40B header + HMAC) na conexão persistente e lê a resposta."""
        if not self.connect() or self.sock is None:
            return None

        try:
            current_key = self.session_key
            message.send_framed(self.sock, hmac_key=current_key)
            resp = Message.recv_framed(self.sock, hmac_key=current_key)
            if resp is None:
                self.close()
                return None

            # Se o servidor emitiu uma nova chave de sessão dinâmica (após login ou registro), atualiza-a
            new_key_hex = resp.payload.get("session_key")
            if new_key_hex and resp.payload.get("status") == Message.STATUS_OK:
                self.session_key = bytes.fromhex(new_key_hex)

            return resp
        except (
            ConnectionResetError,
            BrokenPipeError,
            TimeoutError,
            socket.timeout,
            OSError,
            ProtocolError,
            HMACVerificationError,
            json.JSONDecodeError,
            ValueError,
        ) as e:
            logger.error("Erro na conexão persistente de controle: %s", e)
            print(f"\n[!] Erro na conexão persistente de controle: {e}", file=sys.stderr)
            self.close()
            return None

    def login(self, username: str, secret_hash: str) -> Tuple[bool, str]:
        req = Message(
            action=Message.ACTION_LOGIN,
            payload={"username": username, "password": secret_hash},
        )
        resp = self.send_request(req)
        if not resp:
            return False, "Sem resposta do servidor."
        ok = resp.payload.get("status") == Message.STATUS_OK
        if ok:
            self.username = username
        return ok, resp.payload.get("message", "")

    def register(self, username: str, secret_hash: str) -> Tuple[bool, str]:
        req = Message(
            action=Message.ACTION_REGISTER,
            payload={"username": username, "password": secret_hash},
        )
        resp = self.send_request(req)
        if not resp:
            return False, "Sem resposta do servidor."
        ok = resp.payload.get("status") == Message.STATUS_OK
        if ok:
            self.username = username
        return ok, resp.payload.get("message", "")

    def send_text(self, username: str, text: str, secret_hash: str = "") -> bool:
        req = Message(
            action=Message.ACTION_SEND,
            payload={"username": username, "password": secret_hash, "text": text},
        )
        resp = self.send_request(req)
        if not resp:
            return False
        status = resp.payload.get("status")
        msg = resp.payload.get("message", "")
        if status == Message.STATUS_OK:
            print(f"[<] Resposta do servidor: {msg}")
            return True
        print(f"[!] Erro retornado pelo servidor: {msg}", file=sys.stderr)
        return False

    def upload_file(
        self,
        file_path: Path,
        data_port: Optional[int] = None,
        secret_hash: str = "",
    ) -> Tuple[bool, str]:
        """
        Solicita um ticket no Canal de Controle (Porta 9000) e transmite o arquivo
        fatiado em Chunks de 64 KB autenticados com HMAC no Canal de Dados (Porta 9001).
        """
        path = Path(file_path)
        if not path.is_file():
            return False, f"Arquivo não encontrado: {path}"

        file_size = path.stat().st_size
        file_sha256 = _compute_file_sha256(path)

        req = Message(
            action=Message.ACTION_REQUEST_UPLOAD,
            payload={
                "username": self.username or "",
                "password": secret_hash,
                "filename": path.name,
                "file_size": file_size,
                "sha256": file_sha256,
            },
        )
        resp = self.send_request(req)
        if not resp:
            return False, "Sem resposta ao solicitar permissão de upload."

        if resp.payload.get("status") != Message.STATUS_OK:
            return False, resp.payload.get("message", "Upload negado pelo servidor.")

        ticket_hex = resp.payload["ticket"]
        target_data_port = data_port or int(resp.payload.get("data_port", DEFAULT_DATA_PORT))
        total_chunks = int(resp.payload.get("total_chunks", 1))

        logger.info(
            "Iniciando upload de '%s' (%d bytes em %d chunks de até 64KB, ticket=%s) via Canal de Dados %s:%s...",
            path.name,
            file_size,
            total_chunks,
            mask_secret(ticket_hex),
            self.host,
            target_data_port,
        )
        print(
            f"[*] Iniciando upload de '{path.name}' ({file_size} bytes em {total_chunks} chunks de até 64KB) "
            f"via Canal de Dados {self.host}:{target_data_port}..."
        )

        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as data_sock:
            data_sock.settimeout(self.timeout)
            try:
                data_sock.connect((self.host, target_data_port))
                for chunk in MediaChunk.slice_file(path, ticket=ticket_hex, chunk_size=CHUNK_SIZE):
                    chunk.send(data_sock, hmac_key=self.session_key)

                final_resp = Message.recv_framed(data_sock, hmac_key=self.session_key)
                if not final_resp:
                    return False, "Canal de dados fechou sem enviar confirmação final."

                ok = final_resp.payload.get("status") == Message.STATUS_OK
                msg = final_resp.payload.get("message", "")
                if ok:
                    print(f"[✓] {msg}")
                else:
                    logger.error("Erro retornado pelo servidor no upload: %s", msg)
                    print(f"[!] Erro no upload: {msg}", file=sys.stderr)
                return ok, msg
            except (
                ConnectionResetError,
                BrokenPipeError,
                TimeoutError,
                socket.timeout,
                OSError,
                ProtocolError,
                HMACVerificationError,
            ) as e:
                logger.error("Erro de rede no Canal de Dados ao enviar '%s': %s", path.name, e)
                return False, f"Erro de rede no Canal de Dados: {e}"

    def close(self) -> None:
        if self.sock is not None:
            try:
                logout_msg = Message(action=Message.ACTION_LOGOUT, payload={})
                logout_msg.send_framed(self.sock, hmac_key=self.session_key)
                Message.recv_framed(self.sock, hmac_key=self.session_key)
            except (
                ConnectionResetError,
                BrokenPipeError,
                TimeoutError,
                socket.timeout,
                OSError,
                ProtocolError,
                HMACVerificationError,
                ValueError,
            ):
                pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
            self.session_key = DEFAULT_HANDSHAKE_KEY

    def __enter__(self) -> "ControlConnection":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


class HomelabClient:
    """Cliente TCP Dual-Protocol para o Homelab com arquitetura orientada a objetos (DEBT-01).

    Encapsula as configurações operacionais (`ClientConfig`), o estado da sessão
    local (`Session`) e o gerenciamento da conexão persistente no Canal de Controle
    (`ControlConnection`), oferecendo suporte a Context Manager determinístico.
    """

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
    ) -> None:
        if config is not None:
            self.config = config
        else:
            self.config = load_client_config(env_file=env_file)

        if host is not None:
            self.config.host = host
        if control_port is not None:
            self.config.control_port = control_port
        elif port is not None:
            self.config.control_port = port
        if data_port is not None:
            self.config.data_port = data_port
        if timeout is not None:
            self.config.timeout = timeout
        if session_path is not None:
            self.config.session_path = Path(session_path)

        self.session = session
        if self.session is None and self.config.session_path.is_file():
            self.session = Session.load(path=self.config.session_path)

        self.control_conn = control_conn
        self.username = self.session.last_username if (self.session and self.session.is_valid()) else None
        self.secret_hash = self.session.last_password if (self.session and self.session.is_valid()) else None

    @property
    def host(self) -> str:
        return self.config.host

    @property
    def control_port(self) -> int:
        return self.config.control_port

    @property
    def data_port(self) -> int:
        return self.config.data_port

    @property
    def is_connected(self) -> bool:
        """Indica se a conexão de controle está estabelecida com o servidor."""
        return self.control_conn is not None and self.control_conn.sock is not None

    @property
    def session_key(self) -> bytes:
        """Retorna a chave HMAC ativa da conexão de controle."""
        if self.control_conn is not None:
            return self.control_conn.session_key
        return self.config.handshake_key

    def connect(self) -> bool:
        """Abre a conexão TCP persistente no Canal de Controle se ainda não estiver aberta."""
        if self.control_conn is None:
            self.control_conn = ControlConnection(
                host=self.config.host,
                port=self.config.control_port,
                timeout=self.config.timeout,
            )
        ok = self.control_conn.connect()
        if ok and self.username:
            self.control_conn.username = self.username
        return ok

    def login(
        self,
        username: str,
        password: Optional[str] = None,
        is_already_derived: bool = False,
    ) -> Tuple[bool, str]:
        """Autentica o cliente junto ao servidor via Canal de Controle.

        Suporta senha em texto puro, segredo já derivado ou Quick Login com sessão em cache.
        """
        if password is not None:
            secret_hash = password if is_already_derived else Session.derive_secret(username, password)
        elif self.session and self.session.is_valid() and self.session.last_username == username:
            secret_hash = self.session.last_password
        else:
            return False, "Senha não informada e nenhuma sessão válida disponível."

        if not self.connect() or self.control_conn is None:
            return False, "Falha na conexão com o servidor."

        ok, reason = self.control_conn.login(username, secret_hash)
        if ok:
            self.username = username
            self.secret_hash = secret_hash
            self.session = Session.create(
                username,
                secret_hash,
                is_already_derived=True,
                days=Session.DEFAULT_TTL_DAYS,
            )
            self.session.save(path=self.config.session_path)
            logger.info("Login realizado com sucesso para '%s'", username)
        else:
            logger.warning("Falha no login para '%s': %s", username, reason)

        return ok, reason

    def register(
        self,
        username: str,
        password: Optional[str] = None,
        is_already_derived: bool = False,
    ) -> Tuple[bool, str]:
        """Cadastra nova conta de cliente e persiste a sessão local com auto-login."""
        secret_hash = password or "" if is_already_derived else Session.derive_secret(username, password or "")

        if not self.connect() or self.control_conn is None:
            return False, "Falha na conexão com o servidor."

        ok, reason = self.control_conn.register(username, secret_hash)
        if ok:
            self.username = username
            self.secret_hash = secret_hash
            self.session = Session.create(
                username,
                secret_hash,
                is_already_derived=True,
                days=Session.DEFAULT_TTL_DAYS,
            )
            self.session.save(path=self.config.session_path)
            logger.info("Conta '%s' cadastrada com sucesso", username)
        else:
            logger.warning("Falha no cadastro para '%s': %s", username, reason)

        return ok, reason

    def send_message(self, text: str) -> Tuple[bool, str]:
        """Envia mensagem de texto autenticada ao servidor via conexão persistente."""
        if not self.username:
            return False, "Cliente não autenticado. Faça login antes de enviar mensagens."

        if not self.connect() or self.control_conn is None:
            return False, "Falha na conexão com o servidor."

        req = Message(
            action=Message.ACTION_SEND,
            payload={
                "username": self.username,
                "password": self.secret_hash or "",
                "text": text,
            },
        )
        resp = self.control_conn.send_request(req)
        if not resp:
            return False, "Sem resposta do servidor."

        status = resp.payload.get("status")
        msg = resp.payload.get("message", "")
        ok = status == Message.STATUS_OK
        return ok, msg

    def upload_file(
        self,
        file_path: Union[str, Path],
        data_port: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """Realiza upload de arquivo fatiado em chunks de 64KB no Canal de Dados."""
        if not self.username:
            return False, "Cliente não autenticado. Faça login antes de enviar arquivos."

        if not self.connect() or self.control_conn is None:
            return False, "Falha na conexão com o servidor."

        path = Path(file_path)
        target_port = data_port or self.config.data_port
        return self.control_conn.upload_file(
            path,
            data_port=target_port,
            secret_hash=self.secret_hash or "",
        )

    def close(self) -> None:
        """Fecha determinísticamente a conexão TCP de controle."""
        if self.control_conn is not None:
            self.control_conn.close()
            self.control_conn = None

    def __enter__(self) -> "HomelabClient":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self.close()



def send_network_message(
    host: str,
    port: int,
    message: Message,
    use_framing: bool = False,
    hmac_key: bytes = DEFAULT_HANDSHAKE_KEY,
) -> Optional[Message]:
    """Envia uma mensagem pontual (compatível com servidores legados ou modo framed)."""
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as client_socket:
        client_socket.settimeout(TIMEOUT_SECONDS)
        try:
            client_socket.connect((host, port))
            if use_framing:
                message.send_framed(client_socket, hmac_key=hmac_key)
                return Message.recv_framed(client_socket, hmac_key=hmac_key)

            payload_bytes = message.to_bytes()
            client_socket.sendall(payload_bytes)

            raw_response = client_socket.recv(BUFFER_SIZE)
            if not raw_response:
                return None

            try:
                if len(raw_response) >= 40 and raw_response[:2] == CONTROL_MAGIC:
                    return Message.from_frame(raw_response, hmac_key=hmac_key)
                return Message.from_bytes(raw_response)
            except (ProtocolError, HMACVerificationError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
                return Message.response(
                    Message.STATUS_OK,
                    raw_response.decode("utf-8", errors="replace").strip(),
                )

        except ConnectionRefusedError:
            print(
                f"\n[!] Erro: Conexão recusada em {host}:{port}. "
                "Certifique-se de que o servidor está rodando.",
                file=sys.stderr,
            )
            return None
        except (socket.timeout, TimeoutError):
            print(
                f"\n[!] Erro: Tempo de espera esgotado ({TIMEOUT_SECONDS}s) aguardando {host}:{port}.",
                file=sys.stderr,
            )
            return None
        except OSError as e:
            print(f"\n[!] Erro de rede: {e}", file=sys.stderr)
            return None


def do_login_request(
    host: str,
    port: int,
    username: str,
    secret_hash: str,
    conn: Optional[Union[ControlConnection, HomelabClient]] = None,
) -> Tuple[bool, str]:
    """Envia requisição de autenticação para o servidor (via conexão persistente ou pontual)."""
    if isinstance(conn, HomelabClient):
        return conn.login(username, secret_hash, is_already_derived=True)
    if conn is not None:
        return conn.login(username, secret_hash)

    req = Message(
        action=Message.ACTION_LOGIN,
        payload={"username": username, "password": secret_hash},
    )
    resp = send_network_message(host, port, req)
    if not resp:
        return False, "Sem resposta do servidor."

    status = resp.payload.get("status")
    msg = resp.payload.get("message", "")
    return status == Message.STATUS_OK, msg


def do_register_request(
    host: str,
    port: int,
    username: str,
    secret_hash: str,
    conn: Optional[Union[ControlConnection, HomelabClient]] = None,
) -> Tuple[bool, str]:
    """Envia requisição de cadastro explícito para o servidor (via conexão persistente ou pontual)."""
    if isinstance(conn, HomelabClient):
        return conn.register(username, secret_hash, is_already_derived=True)
    if conn is not None:
        return conn.register(username, secret_hash)

    req = Message(
        action=Message.ACTION_REGISTER,
        payload={"username": username, "password": secret_hash},
    )
    resp = send_network_message(host, port, req)
    if not resp:
        return False, "Sem resposta do servidor."

    status = resp.payload.get("status")
    msg = resp.payload.get("message", "")
    return status == Message.STATUS_OK, msg


def send_user_message(
    host: str,
    port: int,
    username: str,
    secret_hash: str,
    text: str,
    conn: Optional[Union[ControlConnection, HomelabClient]] = None,
) -> bool:
    """Envia uma mensagem de texto autenticada ao servidor (via conexão persistente ou pontual)."""
    if isinstance(conn, HomelabClient):
        ok, msg = conn.send_message(text)
        if ok:
            print(f"[<] Resposta do servidor: {msg}")
            return True
        print(f"[!] Erro retornado pelo servidor: {msg}", file=sys.stderr)
        return False
    if conn is not None:
        return conn.send_text(username, text, secret_hash=secret_hash)

    req = Message(
        action=Message.ACTION_SEND,
        payload={"username": username, "password": secret_hash, "text": text},
    )
    print(f"[*] Enviando mensagem como '{username}' para {host}:{port}...")
    resp = send_network_message(host, port, req)
    if not resp:
        return False

    status = resp.payload.get("status")
    message = resp.payload.get("message", "")
    if status == Message.STATUS_OK:
        print(f"[<] Resposta do servidor: {message}")
        return True
    else:
        print(f"[!] Erro retornado pelo servidor: {message}", file=sys.stderr)
        return False


def run_auth_flow(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    conn: Optional[ControlConnection] = None,
    client: Optional[HomelabClient] = None,
) -> Optional[Tuple[str, str]]:
    """
    Executa a interface de terminal para Login ou Cadastro:
    1. Login (com Quick Login se houver sessão < 7 dias)
    2. Register (com Auto-login imediato)
    3. Sair
    Retorna tupla (username, secret_hash) em caso de sucesso ou None.
    """
    if client is None:
        client = HomelabClient(host=host, control_port=port, control_conn=conn)

    while True:
        print("\n" + "=" * 55)
        print("          HOMELAB TCP CLIENT - ACESSO")
        print("=" * 55)
        print("  1. Login")
        print("  2. Register (Criar nova conta)")
        print("  3. Sair")
        print("=" * 55)

        try:
            choice = input("Escolha uma opção [1-3]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[*] Operação cancelada.")
            return None

        if choice == "1":
            session = client.session or Session.load(path=client.config.session_path)
            if session and session.is_valid():
                prompt_text = (
                    f"\n[?] Quick login disponível para '{session.last_username}' "
                    f"({session.time_remaining()}). Deseja aceitar? [S/n]: "
                )
                try:
                    accept = input(prompt_text).strip().lower()
                except (KeyboardInterrupt, EOFError):
                    return None

                if accept in ("", "s", "sim", "y", "yes"):
                    print(f"[*] Autenticando com Quick Login como '{session.last_username}'...")
                    ok, reason = client.login(session.last_username)
                    if ok:
                        print(f"[✓] Quick login aceito com sucesso! Bem-vindo, {session.last_username}.")
                        return session.last_username, session.last_password
                    else:
                        print(f"[!] Falha no Quick Login: {reason}")
                        print("[*] Limpando sessão local inválida...")
                        Session.clear(path=client.config.session_path)
                        client.session = None

            print("\n--- 1.2.2 Identificação de Usuário ---")
            try:
                username = input("Username: ").strip()
                if not username:
                    print("[!] Username obrigatório.")
                    continue
                password = getpass.getpass("Password: ")
            except (KeyboardInterrupt, EOFError):
                return None

            ok, reason = client.login(username, password)
            if ok:
                print(f"[✓] Login realizado com sucesso! Bem-vindo, {username}.")
                return username, client.secret_hash or ""
            else:
                print(f"[!] Falha no login: {reason}")

        elif choice == "2":
            print("\n--- 2.1 Cadastro de Nova Conta ---")
            try:
                username = input("Escolha um Username (mínimo 3 caracteres): ").strip()
                if len(username) < 3:
                    print("[!] O username deve conter pelo menos 3 caracteres.")
                    continue
                password = getpass.getpass("Escolha uma Senha: ")
                if not password:
                    print("[!] Senha não pode ser vazia.")
                    continue
                confirm_password = getpass.getpass("Confirme a Senha: ")
                if password != confirm_password:
                    print("[!] As senhas não conferem.")
                    continue
            except (KeyboardInterrupt, EOFError):
                return None

            ok, reason = client.register(username, password)
            if ok:
                print(f"[✓] Conta '{username}' criada com sucesso!")
                print(
                    f"[✓] Auto-login ativado: Sessão local gravada com validade de {Session.DEFAULT_TTL_DAYS} dias."
                )
                return username, client.secret_hash or ""
            else:
                print(f"[!] Erro no cadastro: {reason}")

        elif choice == "3":
            print("[*] Encerrando o cliente. Até logo!")
            return None
        else:
            print("[!] Opção inválida. Digite 1, 2 ou 3.")


def interactive_menu(client: HomelabClient) -> None:
    """Interface interativa de terminal (CLI) desacoplada da camada de rede."""
    username = client.username or "cliente"
    print(f"\n[*] Conexão TCP Persistente ativa para '{username}' (HMAC-SHA256 dinâmico).")
    print("[*] Digite sua mensagem ou use '/upload <caminho_do_arquivo>' para enviar mídia em chunks.")
    print("[*] Digite 'sair' ou Ctrl+C para encerrar.\n")

    while True:
        try:
            user_input = input(f"[{username}] > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[*] Sessão interativa finalizada.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("sair", "exit", "quit"):
            print("[*] Sessão encerrada pelo usuário.")
            break

        if user_input.startswith("/upload "):
            raw_path = user_input[len("/upload ") :].strip()
            if not raw_path:
                print("[!] Informe o caminho do arquivo. Exemplo: /upload foto.png")
                continue
            ok, msg = client.upload_file(raw_path)
            if ok:
                print(f"[✓] {msg}")
            else:
                print(f"[!] Erro no upload: {msg}", file=sys.stderr)
            continue

        ok, msg = client.send_message(user_input)
        if ok:
            print(f"[<] Resposta do servidor: {msg}")
        else:
            print(f"[!] Erro retornado pelo servidor: {msg}", file=sys.stderr)


def main() -> None:
    # Pré-processamento de argumentos para verificar se --env-file foi informado
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env-file", type=str, default=None)
    pre_args, remaining_argv = pre_parser.parse_known_args()

    cfg = load_client_config(env_file=pre_args.env_file, override=True if pre_args.env_file else False)
    Session.DEFAULT_SESSION_FILE = cfg.session_path

    parser = argparse.ArgumentParser(
        description="Cliente TCP Dual-Protocol Homelab (Controle Persistente + Upload em Chunks de 64KB)."
    )
    parser.add_argument(
        "--env-file",
        type=str,
        default=pre_args.env_file,
        help="Caminho para arquivo de variáveis de ambiente customizado (ex: envs/client.env, envs/.env.prod)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=cfg.host,
        help=f"Endereço IP do servidor TCP (padrão: {cfg.host})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=cfg.control_port,
        help=f"Porta do Canal de Controle (padrão: {cfg.control_port})",
    )
    parser.add_argument(
        "--data-port",
        type=int,
        default=cfg.data_port,
        help=f"Porta do Canal de Dados/Mídia (padrão: {cfg.data_port})",
    )
    parser.add_argument(
        "-m",
        "--message",
        type=str,
        help="Mensagem opcional a ser enviada após autenticação.",
    )
    parser.add_argument(
        "-u",
        "--upload",
        type=Path,
        help="Caminho de arquivo/imagem opcional para upload em chunks de 64KB após autenticação.",
    )

    args = parser.parse_args(remaining_argv)

    cfg.host = args.host
    cfg.control_port = args.port
    cfg.data_port = args.data_port

    with HomelabClient(config=cfg) as client:
        auth_credentials = run_auth_flow(client=client)
        if not auth_credentials:
            sys.exit(0)

        username, secret_hash = auth_credentials

        if args.message:
            ok, msg = client.send_message(args.message)
            if ok:
                print(f"[<] Resposta do servidor: {msg}")
            else:
                print(f"[!] Erro retornado pelo servidor: {msg}", file=sys.stderr)
            if not args.upload:
                sys.exit(0 if ok else 1)

        if args.upload:
            ok, msg = client.upload_file(args.upload)
            if ok:
                print(f"[✓] {msg}")
            else:
                print(f"[!] Erro no upload: {msg}", file=sys.stderr)
            sys.exit(0 if ok else 1)

        interactive_menu(client)

    sys.exit(0)



if __name__ == "__main__":
    main()
