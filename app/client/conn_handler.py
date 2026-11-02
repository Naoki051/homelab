#!/usr/bin/env python3
"""
Gerenciamento de Conexões de Rede TCP para o Cliente Homelab.
Contém ControlConnection (Canal de Controle :9000 persistente com HMAC dinâmico)
e ClientConnectionHandler (Canal de Dados :9001 efêmero para streaming de chunks).
"""

import contextlib
import hashlib
import json
from pathlib import Path
import socket
import sys
from types import TracebackType
from typing import List, Optional, Tuple, Type, Union

from app.config import ClientConfig, load_client_config
from app.exceptions import HMACVerificationError, ProtocolError, mask_secret
from app.logger import get_logger
from app.protocol import (
    CHUNK_SIZE,
    CONTROL_MAGIC,
    DEFAULT_HANDSHAKE_KEY,
    MediaChunk,
    Message,
)

logger = get_logger(__name__)

# Configurações dinâmicas padrão carregadas via client config
_cfg: ClientConfig = load_client_config()
DEFAULT_HOST: str = _cfg.host
DEFAULT_PORT: int = _cfg.control_port
DEFAULT_DATA_PORT: int = _cfg.data_port
DEFAULT_HANDSHAKE_KEY: bytes = _cfg.handshake_key
TIMEOUT_SECONDS: float = _cfg.timeout
BUFFER_SIZE: int = _cfg.buffer_size

__all__: List[str] = [
    "ControlConnection",
    "ClientConnectionHandler",
    "send_network_message",
    "_compute_file_sha256",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_DATA_PORT",
    "DEFAULT_HANDSHAKE_KEY",
    "TIMEOUT_SECONDS",
    "BUFFER_SIZE",
]


def _compute_file_sha256(file_path: Path) -> str:
    """Calcula o SHA-256 do arquivo em blocos de CHUNK_SIZE para integridade."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


class ClientConnectionHandler:
    """Gerenciador utilitário para sockets TCP efêmeros no canal de dados."""

    def __init__(self, host: str, timeout: float = 10.0) -> None:
        self.host = host
        self.timeout = timeout

    def open_data_socket(self, port: int) -> socket.socket:
        """Abre e conecta um socket TCP no canal de dados."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect((self.host, port))
        return sock


class ControlConnection:
    """
    Mantém uma conexão TCP persistente no Canal de Controle (Porta 9000)
    com Framing Binário e rotação automática para session_key dinâmica.
    """

    host: str
    port: int
    timeout: float
    sock: Optional[socket.socket]
    session_key: bytes
    username: Optional[str]

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.session_key = DEFAULT_HANDSHAKE_KEY
        self.username = None

    def connect(self) -> bool:
        """Abre a conexão TCP persistente com o servidor, se ainda não estiver aberta."""
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
        """Envia mensagem enquadrada na conexão persistente e lê a resposta."""
        if not self.connect() or self.sock is None:
            return None

        try:
            current_key = self.session_key
            message.send_framed(self.sock, hmac_key=current_key)
            resp = Message.recv_framed(self.sock, hmac_key=current_key)
            if resp is None:
                self.close()
                return None

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
        """Executa a requisição de login e registra o usuário na conexão."""
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
        """Executa o cadastro de usuário e registra o usuário na conexão."""
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
        """Envia mensagem de texto autenticada através da conexão de controle."""
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
        file_path: Union[Path, str],
        data_port: Optional[int] = None,
        secret_hash: str = "",
    ) -> Tuple[bool, str]:
        """Solicita ticket no Canal de Controle e transmite chunks de 64KB no Canal de Dados."""
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
            "Iniciando upload de '%s' (%d bytes em %d chunks, ticket=%s) via Canal de Dados %s:%s.",
            path.name,
            file_size,
            total_chunks,
            mask_secret(ticket_hex),
            self.host,
            target_data_port,
        )
        print(
            f"[*] Iniciando upload de '{path.name}' ({file_size} bytes em {total_chunks} chunks de "
            f"até 64KB) via Canal de Dados {self.host}:{target_data_port}..."
        )

        handler = ClientConnectionHandler(self.host, timeout=self.timeout)
        with contextlib.closing(handler.open_data_socket(target_data_port)) as data_sock:
            try:
                for chunk in MediaChunk.slice_file(path, ticket=ticket_hex, chunk_size=CHUNK_SIZE):
                    chunk.send(data_sock, hmac_key=self.session_key)

                try:
                    final_resp = Message.recv_framed(data_sock, hmac_key=self.session_key)
                except (ValueError, json.JSONDecodeError) as e:
                    logger.error("Falha no protocolo de resposta no Canal de Dados: %s", e)
                    return False, f"Falha no protocolo de resposta: {e}"

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
                ValueError,
                json.JSONDecodeError,
            ) as e:
                logger.error("Erro no Canal de Dados ao enviar '%s': %s", path.name, e)
                return False, f"Falha no protocolo de resposta: {e}"

    def close(self) -> None:
        """Envia logout e fecha determinísticamente o socket TCP de controle."""
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
    """Envia uma mensagem pontual efêmera (legado ou framed)."""
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
            except (
                ProtocolError,
                HMACVerificationError,
                ValueError,
                json.JSONDecodeError,
                UnicodeDecodeError,
            ):
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
                f"\n[!] Erro: Tempo de espera esgotado ({TIMEOUT_SECONDS}s) "
                f"aguardando {host}:{port}.",
                file=sys.stderr,
            )
            return None
        except OSError as e:
            print(f"\n[!] Erro de rede: {e}", file=sys.stderr)
            return None
