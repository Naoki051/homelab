#!/usr/bin/env python3
"""Serviços de rede TCP e trabalhadores de conexão para o Servidor Homelab.

Módulo: app/server/conn_handler.py
"""

from abc import ABC, abstractmethod
import contextlib
from pathlib import Path
import socket
import sqlite3
import threading
from typing import Dict, List, Optional, Tuple

from app.config import load_server_config
from app.database import ClientRepository
from app.exceptions import (
    HomelabError,
    ProtocolError,
    StorageError,
    mask_secret,
)
from app.logger import get_logger
from app.protocol import (
    CHUNK_SIZE,
    CONTROL_MAGIC,
    DEFAULT_HANDSHAKE_KEY,
    MediaChunk,
    Message,
)
from app.server.commands import (
    ServerCommandDispatcher,
    handle_client_payload,
    process_control_message,
)
from app.server.tickets import (
    UploadTicket,
    UploadTicketManager,
    compute_file_sha256,
    log_message,
)

logger = get_logger(__name__)

_cfg = load_server_config()
DEFAULT_HOST: str = _cfg.host
DEFAULT_PORT: int = _cfg.control_port
DEFAULT_DATA_PORT: int = _cfg.data_port
DEFAULT_LOG_PATH: Path = _cfg.log_path
DEFAULT_DB_PATH: Path = _cfg.db_path
DEFAULT_UPLOADS_DIR: Path = _cfg.uploads_dir
DEFAULT_HANDSHAKE_KEY: bytes = _cfg.handshake_key
BUFFER_SIZE: int = _cfg.buffer_size

__all__: List[str] = [
    "BaseNetworkService",
    "ControlServer",
    "DataServer",
    "handle_control_client_connection",
    "handle_data_client_connection",
]


class BaseNetworkService(ABC):
    """Classe base abstrata para serviços de rede TCP no Homelab."""

    def __init__(self, host: str, port: int) -> None:
        self.host: str = host
        self.port: int = port
        self.socket: Optional[socket.socket] = None
        self.is_running: bool = False
        self._thread: Optional[threading.Thread] = None

    def bind_and_listen(self, backlog: int = 16) -> None:
        """Vincula o socket TCP com SO_REUSEADDR e coloca em modo de escuta."""
        if self.socket is not None:
            return
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen(backlog)
        self.port = self.socket.getsockname()[1]
        self.socket.settimeout(1.0)
        self.is_running = True

    @abstractmethod
    def start(self) -> None:
        """Inicia o serviço de rede e seu loop de escuta."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Encerra o serviço de rede e libera recursos alocados."""
        pass

    def _stop_service(self) -> None:
        """Rotina comum de encerramento de sockets e join de thread."""
        self.is_running = False
        if self.socket is not None:
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None


class ControlServer(BaseNetworkService):
    """Servidor TCP para o Canal de Controle (Porta 9000)."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        repo: Optional[ClientRepository] = None,
        log_path: Path = DEFAULT_LOG_PATH,
        ticket_manager: Optional[UploadTicketManager] = None,
        data_port: int = DEFAULT_DATA_PORT,
        db_path: Path = DEFAULT_DB_PATH,
        uploads_dir: Path = DEFAULT_UPLOADS_DIR,
        dispatcher: Optional[ServerCommandDispatcher] = None,
    ) -> None:
        super().__init__(host=host, port=port)
        self.db_path = db_path
        self.uploads_dir = uploads_dir
        self.repo = repo if repo is not None else ClientRepository(db_path=self.db_path)
        self.ticket_manager = (
            ticket_manager
            if ticket_manager is not None
            else UploadTicketManager(uploads_dir=self.uploads_dir)
        )
        self.log_path = log_path
        self.data_port = data_port
        self.dispatcher = (
            dispatcher if dispatcher is not None else ServerCommandDispatcher()
        )

    def start(self) -> None:
        """Inicia o listener TCP do canal de controle em thread daemon."""
        if self.is_running and self._thread is not None and self._thread.is_alive():
            return
        if self.socket is None:
            self.bind_and_listen()
        self.is_running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        if self.socket is not None:
            self.socket.settimeout(1.0)
        while self.is_running:
            try:
                if self.socket is None:
                    break
                client_sock, client_addr = self.socket.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break

            if not self.is_running:
                client_sock.close()
                break
            client_ip, client_port = client_addr
            logger.info("Conexão de controle aceita de %s:%s", client_ip, client_port)
            t = threading.Thread(
                target=self._handle_client_thread,
                args=(client_sock, client_addr),
                daemon=True,
            )
            t.start()

    def _handle_client_thread(
        self, client_sock: socket.socket, client_addr: Tuple[str, int]
    ) -> None:
        with contextlib.closing(client_sock):
            self.handle_connection(client_sock, client_addr)

    def handle_connection(
        self, client_sock: socket.socket, client_addr: Tuple[str, int]
    ) -> None:
        """Delega atendimento de cliente de controle para o worker."""
        handle_control_client_connection(
            client_socket=client_sock,
            client_address=client_addr,
            repo=self.repo,
            log_path=self.log_path,
            ticket_manager=self.ticket_manager,
            data_port=self.data_port,
            dispatcher=self.dispatcher,
        )

    def stop(self) -> None:
        """Encerra o listener de controle."""
        self._stop_service()


class DataServer(BaseNetworkService):
    """Servidor TCP para o Canal de Dados/Mídia (Porta 9001)."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_DATA_PORT,
        ticket_manager: Optional[UploadTicketManager] = None,
        log_path: Path = DEFAULT_LOG_PATH,
        uploads_dir: Path = DEFAULT_UPLOADS_DIR,
    ) -> None:
        super().__init__(host=host, port=port)
        self.uploads_dir = uploads_dir
        self.ticket_manager = (
            ticket_manager
            if ticket_manager is not None
            else UploadTicketManager(uploads_dir=self.uploads_dir)
        )
        self.log_path = log_path

    def start(self) -> None:
        """Inicia o listener TCP do canal de dados em thread daemon."""
        if self.is_running and self._thread is not None and self._thread.is_alive():
            return
        if self.socket is None:
            self.bind_and_listen()
        self.is_running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        if self.socket is not None:
            self.socket.settimeout(1.0)
        while self.is_running:
            try:
                if self.socket is None:
                    break
                client_sock, client_addr = self.socket.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break

            if not self.is_running:
                client_sock.close()
                break
            t = threading.Thread(
                target=self._handle_client_thread,
                args=(client_sock, client_addr),
                daemon=True,
            )
            t.start()

    def _handle_client_thread(
        self, client_sock: socket.socket, client_addr: Tuple[str, int]
    ) -> None:
        with contextlib.closing(client_sock):
            self.handle_chunk_stream(client_sock, client_addr)

    def handle_chunk_stream(
        self, client_sock: socket.socket, client_addr: Tuple[str, int]
    ) -> None:
        """Delega recepção de chunks para o worker."""
        handle_data_client_connection(
            client_socket=client_sock,
            client_address=client_addr,
            ticket_manager=self.ticket_manager,
            log_path=self.log_path,
        )

    def stop(self) -> None:
        """Encerra o listener de dados."""
        self._stop_service()


def _run_control_framed_loop(
    client_socket: socket.socket,
    client_address: Tuple[str, int],
    repo: ClientRepository,
    log_path: Path,
    ticket_manager: UploadTicketManager,
    data_port: int,
    dispatcher: Optional[ServerCommandDispatcher],
    prefix: bytes,
    session_state: Optional[Dict[str, Optional[str]]] = None,
) -> Optional[str]:
    client_ip, client_port = client_address
    active_username: Optional[str] = (
        session_state.get("active_username") if session_state else None
    )
    current_hmac_key: bytes = DEFAULT_HANDSHAKE_KEY
    first_iteration = True

    while True:
        pre_read = prefix if first_iteration else b""
        first_iteration = False

        msg = Message.recv_framed(
            client_socket,
            hmac_key=current_hmac_key,
            pre_read_prefix=pre_read,
        )
        if msg is None:
            break

        try:
            resp, active_username, next_hmac_key = process_control_message(
                msg=msg,
                client_address=client_address,
                repo=repo,
                log_path=log_path,
                authenticated_user=active_username,
                session_key=current_hmac_key,
                ticket_manager=ticket_manager,
                data_port=data_port,
                dispatcher=dispatcher,
            )
            if session_state is not None:
                session_state["active_username"] = active_username
        except (StorageError, sqlite3.DatabaseError) as db_err:
            logger.error(
                "Erro de banco de dados no Canal de Controle (%s:%s): %s",
                client_ip,
                client_port,
                db_err,
            )
            resp = Message.response(
                Message.STATUS_ERROR,
                f"Erro interno de armazenamento: {db_err}",
            )
            next_hmac_key = current_hmac_key

        resp.send_framed(client_socket, hmac_key=current_hmac_key)
        current_hmac_key = next_hmac_key

        if msg.action == Message.ACTION_LOGOUT:
            break

    return active_username


def _handle_control_unframed(
    client_socket: socket.socket,
    client_address: Tuple[str, int],
    repo: ClientRepository,
    log_path: Path,
    ticket_manager: UploadTicketManager,
    data_port: int,
    prefix: bytes,
    session_state: Optional[Dict[str, Optional[str]]] = None,
) -> Optional[str]:
    rest = client_socket.recv(BUFFER_SIZE)
    raw_data = prefix + rest
    response_bytes, active_username = handle_client_payload(
        raw_data,
        client_address,
        repo,
        log_path,
        ticket_manager=ticket_manager,
        data_port=data_port,
    )
    if session_state is not None:
        session_state["active_username"] = active_username
    client_socket.sendall(response_bytes)
    return active_username


def _cleanup_control_connection(
    client_socket: socket.socket,
    client_address: Tuple[str, int],
    repo: ClientRepository,
    active_username: Optional[str],
) -> None:
    client_ip, client_port = client_address
    try:
        if active_username:
            try:
                repo.update_status(active_username, "offline")
            except (HomelabError, sqlite3.DatabaseError, OSError, ValueError) as err:
                logger.warning(
                    "Falha ao atualizar presença para offline de '%s' (%s:%s): %s",
                    active_username,
                    client_ip,
                    client_port,
                    err,
                )
    finally:
        try:
            client_socket.close()
        except OSError:
            pass
        logger.info("Conexão de controle encerrada com %s:%s", client_ip, client_port)


def handle_control_client_connection(
    client_socket: socket.socket,
    client_address: Tuple[str, int],
    repo: ClientRepository,
    log_path: Path,
    ticket_manager: UploadTicketManager,
    data_port: int,
    dispatcher: Optional[ServerCommandDispatcher] = None,
) -> None:
    """Atende conexão persistente ou legada no Canal de Controle."""
    client_ip, client_port = client_address
    session_state: Dict[str, Optional[str]] = {"active_username": None}
    try:
        prefix = client_socket.recv(2)
        if not prefix:
            return

        if prefix == CONTROL_MAGIC:
            _run_control_framed_loop(
                client_socket,
                client_address,
                repo,
                log_path,
                ticket_manager,
                data_port,
                dispatcher,
                prefix,
                session_state=session_state,
            )
        else:
            _handle_control_unframed(
                client_socket,
                client_address,
                repo,
                log_path,
                ticket_manager,
                data_port,
                prefix,
                session_state=session_state,
            )

    except (
        HomelabError,
        sqlite3.DatabaseError,
        OSError,
        ValueError,
    ) as e:
        logger.error("Erro no Canal de Controle (%s:%s) -> %s", client_ip, client_port, e)
        if isinstance(e, (StorageError, sqlite3.DatabaseError)):
            try:
                err_resp = Message.response(
                    Message.STATUS_ERROR,
                    f"Erro de armazenamento: {e}",
                )
                err_resp.send_framed(client_socket, hmac_key=DEFAULT_HANDSHAKE_KEY)
            except OSError:
                pass
    finally:
        _cleanup_control_connection(
            client_socket,
            client_address,
            repo,
            session_state.get("active_username"),
        )


def _write_chunk_to_disk(ticket: UploadTicket, chunk: MediaChunk) -> None:
    offset = chunk.chunk_index * CHUNK_SIZE
    with open(ticket.dest_path, "r+b") as f:
        f.seek(offset)
        f.write(chunk.data)
    ticket.received_chunks.add(chunk.chunk_index)


def _finalize_upload(
    client_socket: socket.socket,
    client_address: Tuple[str, int],
    ticket: UploadTicket,
    ticket_manager: UploadTicketManager,
    log_path: Path,
) -> None:
    actual_sha256 = compute_file_sha256(ticket.dest_path)
    if ticket.expected_sha256 and actual_sha256 != ticket.expected_sha256:
        ticket.dest_path.unlink(missing_ok=True)
        ticket_manager.remove_ticket(ticket.ticket_hex)
        err_resp = Message.response(
            Message.STATUS_ERROR,
            "Hash SHA-256 final do arquivo diverge do esperado.",
        )
        err_resp.send_framed(client_socket, hmac_key=ticket.session_key)
        return

    log_message(
        log_path,
        client_address,
        f"UPLOAD CONCLUÍDO: '{ticket.filename}' ({ticket.file_size} bytes, "
        f"{ticket.total_chunks} chunks, sha256={actual_sha256[:12]}...)",
        username=ticket.username,
    )
    logger.info(
        "Upload concluído para '%s': %s (%d chunks, sha256=%s)",
        ticket.username,
        ticket.dest_path.name,
        ticket.total_chunks,
        mask_secret(actual_sha256),
    )
    ok_resp = Message.response(
        Message.STATUS_OK,
        f"Arquivo '{ticket.filename}' recebido com sucesso "
        f"({ticket.total_chunks} chunks).",
        {
            "filename": ticket.filename,
            "file_size": ticket.file_size,
            "total_chunks": ticket.total_chunks,
            "sha256": actual_sha256,
            "saved_path": str(ticket.dest_path),
        },
    )
    try:
        ok_resp.send_framed(client_socket, hmac_key=ticket.session_key)
    finally:
        ticket_manager.remove_ticket(ticket.ticket_hex)


def _cleanup_data_connection(
    client_socket: socket.socket,
    client_address: Tuple[str, int],
) -> None:
    """Encerra o socket do canal de dados com tolerância a falhas."""
    client_ip, client_port = client_address
    try:
        client_socket.close()
    except OSError:
        pass
    logger.info("Conexão de dados encerrada com %s:%s", client_ip, client_port)


def handle_data_client_connection(
    client_socket: socket.socket,
    client_address: Tuple[str, int],
    ticket_manager: UploadTicketManager,
    log_path: Path,
) -> None:
    """Atende recepção de chunks indexados de 64 KB no Canal de Dados."""
    client_ip, client_port = client_address
    current_ticket: Optional[UploadTicket] = None

    try:
        while True:
            chunk = MediaChunk.recv_from_socket(
                client_socket,
                key_resolver=ticket_manager.get_session_key,
            )
            if chunk is None:
                break

            ticket = ticket_manager.get_ticket(chunk.ticket_hex)
            if ticket is None:
                raise ValueError(f"Ticket não encontrado: {chunk.ticket_hex}")
            current_ticket = ticket

            if chunk.total_chunks != ticket.total_chunks:
                raise ValueError(
                    f"Total de chunks divergente ({chunk.total_chunks} != {ticket.total_chunks})."
                )

            _write_chunk_to_disk(ticket, chunk)

            if len(ticket.received_chunks) >= ticket.total_chunks:
                _finalize_upload(
                    client_socket, client_address, ticket, ticket_manager, log_path
                )
                break

    except (
        HomelabError,
        sqlite3.DatabaseError,
        OSError,
        ValueError,
    ) as e:
        logger.error("Erro no Canal de Dados (%s:%s) -> %s", client_ip, client_port, e)
        if current_ticket:
            try:
                err_resp = Message.response(Message.STATUS_ERROR, f"Falha no upload: {e}")
                err_resp.send_framed(client_socket, hmac_key=current_ticket.session_key)
            except (OSError, ProtocolError, ValueError):
                pass
    finally:
        _cleanup_data_connection(client_socket, client_address)
