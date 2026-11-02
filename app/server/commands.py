#!/usr/bin/env python3
"""Padrão Command para roteamento e processamento de ações no Canal de Controle.

Módulo: app/server/commands.py
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from app.config import load_server_config
from app.database import ClientRepository
from app.exceptions import ProtocolError, mask_secret
from app.logger import get_logger
from app.protocol import (
    CHUNK_SIZE,
    CONTROL_MAGIC,
    DEFAULT_HANDSHAKE_KEY,
    Message,
    generate_session_key,
)
from app.server.tickets import UploadTicketManager, log_message

logger = get_logger(__name__)

_initial_cfg = load_server_config()
DEFAULT_DATA_PORT: int = _initial_cfg.data_port
DEFAULT_LOG_PATH: Path = _initial_cfg.log_path
DEFAULT_DB_PATH: Path = _initial_cfg.db_path
DEFAULT_HANDSHAKE_KEY: bytes = _initial_cfg.handshake_key

__all__: List[str] = [
    "ServerCommandContext",
    "ServerCommandResult",
    "ServerCommandHandler",
    "RegisterCommandHandler",
    "LoginCommandHandler",
    "SendMessageCommandHandler",
    "RequestUploadCommandHandler",
    "LogoutCommandHandler",
    "ServerCommandDispatcher",
    "create_default_dispatcher",
    "process_control_message",
    "handle_client_payload",
]


@dataclass
class ServerCommandContext:
    """Contexto de execução injetado em cada comando de controle."""

    client_address: Tuple[str, int]
    repo: ClientRepository
    log_path: Path
    authenticated_user: Optional[str] = None
    session_key: bytes = DEFAULT_HANDSHAKE_KEY
    ticket_manager: Optional[UploadTicketManager] = None
    data_port: int = DEFAULT_DATA_PORT
    message: Optional[Message] = None


@dataclass
class ServerCommandResult:
    """Resultado da execução de um comando de controle."""

    response: Message
    authenticated_user: Optional[str] = None
    session_key: bytes = DEFAULT_HANDSHAKE_KEY


class ServerCommandHandler(ABC):
    """Classe base abstrata para processadores de comandos do Canal de Controle."""

    @abstractmethod
    def handle(
        self,
        context: ServerCommandContext,
        msg: Optional[Message] = None,
    ) -> ServerCommandResult:
        """Processa a mensagem e retorna a resposta e o novo estado de sessão."""
        pass


def _extract_credentials(
    context: ServerCommandContext, msg: Optional[Message]
) -> Tuple[Optional[Message], str, str]:
    """Extrai mensagem e credenciais com fallback para o contexto de sessão."""
    message = msg or context.message
    if message is None:
        return None, "", ""
    payload = message.payload
    raw_user = payload.get("username", "").strip()
    username = raw_user if raw_user else (context.authenticated_user or "")
    password = payload.get("password", "")
    return message, username, password


def _authenticate_request(
    ctx: ServerCommandContext, username: str, password: str
) -> Tuple[bool, str]:
    """Valida credenciais com bypass otimizado para sessões ativas protegidas por HMAC."""
    if ctx.authenticated_user and username == ctx.authenticated_user:
        return True, "Sessão persistente autenticada via HMAC"
    ok, reason, _ = ctx.repo.authenticate(username, password)
    return ok, reason


class RegisterCommandHandler(ServerCommandHandler):
    """Handler para a ação 'register'."""

    def handle(
        self,
        context: ServerCommandContext,
        msg: Optional[Message] = None,
    ) -> ServerCommandResult:
        message, username, password = _extract_credentials(context, msg)
        if message is None:
            resp = Message.response(Message.STATUS_ERROR, "Mensagem ausente no contexto.")
            return ServerCommandResult(resp, context.authenticated_user, context.session_key)

        ok, reason, _ = context.repo.register(username, password)
        if not ok:
            logger.warning("Falha no registro do usuário '%s': %s", username, reason)
            resp = Message.response(Message.STATUS_ERROR, reason)
            return ServerCommandResult(resp, context.authenticated_user, context.session_key)

        return self._on_success(context, username, reason)

    def _on_success(
        self, context: ServerCommandContext, username: str, reason: str
    ) -> ServerCommandResult:
        context.repo.update_status(username, "online")
        new_session_key = generate_session_key()
        logger.info(
            "Usuário '%s' registrado com sucesso! Chave de sessão HMAC emitida (%s).",
            username,
            mask_secret(new_session_key),
        )
        resp = Message.response(
            Message.STATUS_OK,
            reason,
            {
                "username": username,
                "presence": "online",
                "session_key": new_session_key.hex(),
            },
        )
        return ServerCommandResult(
            resp, authenticated_user=username, session_key=new_session_key
        )


class LoginCommandHandler(ServerCommandHandler):
    """Handler para a ação 'login'."""

    def handle(
        self,
        context: ServerCommandContext,
        msg: Optional[Message] = None,
    ) -> ServerCommandResult:
        message, username, password = _extract_credentials(context, msg)
        if message is None:
            resp = Message.response(Message.STATUS_ERROR, "Mensagem ausente no contexto.")
            return ServerCommandResult(resp, context.authenticated_user, context.session_key)

        ok, reason, _ = context.repo.authenticate(username, password)
        if not ok:
            logger.warning("Login rejeitado para '%s': %s", username, reason)
            resp = Message.response(Message.STATUS_ERROR, reason)
            return ServerCommandResult(resp, context.authenticated_user, context.session_key)

        return self._on_success(context, username, reason)

    def _on_success(
        self, context: ServerCommandContext, username: str, reason: str
    ) -> ServerCommandResult:
        context.repo.update_status(username, "online")
        new_session_key = generate_session_key()
        logger.info("Usuário '%s' autenticado com sucesso! Status: online", username)
        resp = Message.response(
            Message.STATUS_OK,
            reason,
            {
                "username": username,
                "presence": "online",
                "session_key": new_session_key.hex(),
            },
        )
        return ServerCommandResult(
            resp, authenticated_user=username, session_key=new_session_key
        )


class SendMessageCommandHandler(ServerCommandHandler):
    """Handler para a ação 'send'."""

    def handle(
        self,
        context: ServerCommandContext,
        msg: Optional[Message] = None,
    ) -> ServerCommandResult:
        message, username, password = _extract_credentials(context, msg)
        if message is None:
            resp = Message.response(Message.STATUS_ERROR, "Mensagem ausente no contexto.")
            return ServerCommandResult(resp, context.authenticated_user, context.session_key)

        auth_ok, reason = _authenticate_request(context, username, password)
        if not auth_ok:
            logger.warning("Mensagem de '%s' rejeitada: %s", username, reason)
            resp = Message.response(Message.STATUS_ERROR, f"Autenticação requerida: {reason}")
            return ServerCommandResult(resp, context.authenticated_user, context.session_key)

        text = message.payload.get("text", "").strip()
        return self._send_message(context, username, text)

    def _send_message(
        self, context: ServerCommandContext, username: str, text: str
    ) -> ServerCommandResult:
        context.repo.update_status(username, "online")
        log_message(context.log_path, context.client_address, text, username=username)
        logger.info("Mensagem de '%s' salva no log: %s", username, text)
        resp = Message.response(
            Message.STATUS_OK,
            f"Mensagem processada com sucesso para '{username}'",
            {"timestamp": datetime.now().strftime("%H:%M:%S")},
        )
        return ServerCommandResult(
            resp, authenticated_user=username, session_key=context.session_key
        )


class RequestUploadCommandHandler(ServerCommandHandler):
    """Handler para a ação 'request_upload'."""

    def handle(
        self,
        context: ServerCommandContext,
        msg: Optional[Message] = None,
    ) -> ServerCommandResult:
        message, username, password = _extract_credentials(context, msg)
        if message is None:
            resp = Message.response(Message.STATUS_ERROR, "Mensagem ausente no contexto.")
            return ServerCommandResult(resp, context.authenticated_user, context.session_key)

        auth_ok, reason = _authenticate_request(context, username, password)
        if not auth_ok:
            resp = Message.response(
                Message.STATUS_ERROR, f"Autenticação requerida para upload: {reason}"
            )
            return ServerCommandResult(resp, context.authenticated_user, context.session_key)

        return self._create_ticket_response(context, username, message.payload)

    def _create_ticket_response(
        self, context: ServerCommandContext, username: str, payload: Dict
    ) -> ServerCommandResult:
        if context.ticket_manager is None:
            resp = Message.response(
                Message.STATUS_ERROR, "Serviço de upload de mídia indisponível."
            )
            return ServerCommandResult(resp, context.authenticated_user, context.session_key)

        filename = str(payload.get("filename", "arquivo.bin"))
        file_size = int(payload.get("file_size", 0))
        if file_size < 0:
            resp = Message.response(Message.STATUS_ERROR, "Tamanho de arquivo inválido.")
            return ServerCommandResult(resp, context.authenticated_user, context.session_key)

        return self._emit_ticket(
            context, username, filename, file_size, payload.get("sha256")
        )

    def _emit_ticket(
        self,
        context: ServerCommandContext,
        username: str,
        filename: str,
        file_size: int,
        expected_sha256: Optional[str],
    ) -> ServerCommandResult:
        ticket = context.ticket_manager.create_ticket(
            username=username,
            filename=filename,
            file_size=file_size,
            session_key=context.session_key,
            expected_sha256=expected_sha256,
        )
        logger.info(
            "Ticket de upload '%s' emitido para '%s' (%s, %d bytes, %d chunks)",
            mask_secret(ticket.ticket_hex),
            username,
            ticket.filename,
            file_size,
            ticket.total_chunks,
        )
        resp = Message.response(
            Message.STATUS_OK,
            f"Upload autorizado para '{ticket.filename}'",
            {
                "ticket": ticket.ticket_hex,
                "chunk_size": CHUNK_SIZE,
                "total_chunks": ticket.total_chunks,
                "data_port": context.data_port,
            },
        )
        return ServerCommandResult(
            resp, authenticated_user=username, session_key=context.session_key
        )


class LogoutCommandHandler(ServerCommandHandler):
    """Handler para a ação 'logout'."""

    def handle(
        self,
        context: ServerCommandContext,
        msg: Optional[Message] = None,
    ) -> ServerCommandResult:
        if context.authenticated_user:
            context.repo.update_status(context.authenticated_user, "offline")
        resp = Message.response(Message.STATUS_OK, "Sessão encerrada com sucesso.")
        return ServerCommandResult(
            resp, authenticated_user=None, session_key=DEFAULT_HANDSHAKE_KEY
        )


class ServerCommandDispatcher:
    """Despachante O(1) de comandos do Canal de Controle."""

    def __init__(self) -> None:
        self._handlers: Dict[str, ServerCommandHandler] = {}
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        self.register_handler(Message.ACTION_REGISTER, RegisterCommandHandler())
        self.register_handler(Message.ACTION_LOGIN, LoginCommandHandler())
        self.register_handler(Message.ACTION_SEND, SendMessageCommandHandler())
        self.register_handler(Message.ACTION_REQUEST_UPLOAD, RequestUploadCommandHandler())
        self.register_handler(Message.ACTION_LOGOUT, LogoutCommandHandler())

    def register_handler(self, action: str, handler: ServerCommandHandler) -> None:
        self._handlers[action] = handler

    def dispatch(
        self,
        msg_or_ctx: Union[Message, ServerCommandContext],
        ctx: Optional[ServerCommandContext] = None,
    ) -> ServerCommandResult:
        """Despacha uma mensagem para seu handler registrado."""
        if isinstance(msg_or_ctx, ServerCommandContext):
            context = msg_or_ctx
            message = context.message
        else:
            message = msg_or_ctx
            context = ctx
            if context and context.message is None:
                context.message = message

        if message is None:
            resp = Message.response(
                Message.STATUS_ERROR, "Mensagem inválida ou ausente no contexto."
            )
            auth_user = context.authenticated_user if context else None
            s_key = context.session_key if context else DEFAULT_HANDSHAKE_KEY
            return ServerCommandResult(resp, auth_user, s_key)

        handler = self._handlers.get(message.action)
        if not handler:
            resp = Message.response(
                Message.STATUS_ERROR, f"Ação desconhecida: '{message.action}'"
            )
            auth_user = context.authenticated_user if context else None
            s_key = context.session_key if context else DEFAULT_HANDSHAKE_KEY
            return ServerCommandResult(resp, auth_user, s_key)

        return handler.handle(context=context, msg=message)


def create_default_dispatcher() -> ServerCommandDispatcher:
    """Cria e retorna um novo ServerCommandDispatcher com handlers padrão registrados."""
    return ServerCommandDispatcher()


_default_dispatcher = create_default_dispatcher()


def _resolve_log_path(log_path: Optional[Path], log_dir: Optional[Path]) -> Path:
    if log_path is not None:
        return log_path
    if log_dir is not None:
        return Path(log_dir) / "server.log"
    return DEFAULT_LOG_PATH


def _resolve_repo(
    repo: Optional[ClientRepository], users_db_path: Optional[Path]
) -> ClientRepository:
    if repo is not None:
        return repo
    if users_db_path is not None:
        return ClientRepository(db_path=Path(users_db_path))
    return ClientRepository(db_path=DEFAULT_DB_PATH)


def _update_legacy_dicts(
    result: ServerCommandResult,
    actual_user: Optional[str],
    actual_client_addr: Tuple[str, int],
    active_sessions: Optional[Dict],
    active_users: Optional[Dict],
) -> None:
    if active_sessions is not None:
        if result.authenticated_user and result.session_key:
            active_sessions[result.authenticated_user] = result.session_key
        elif actual_user and result.authenticated_user is None:
            active_sessions.pop(actual_user, None)

    if active_users is not None:
        if result.authenticated_user:
            active_users[result.authenticated_user] = actual_client_addr
        elif actual_user and result.authenticated_user is None:
            active_users.pop(actual_user, None)


def process_control_message(
    msg: Optional[Message] = None,
    client_address: Optional[Tuple[str, int]] = None,
    repo: Optional[ClientRepository] = None,
    log_path: Optional[Path] = None,
    authenticated_user: Optional[str] = None,
    session_key: bytes = DEFAULT_HANDSHAKE_KEY,
    ticket_manager: Optional[UploadTicketManager] = None,
    data_port: int = DEFAULT_DATA_PORT,
    dispatcher: Optional[ServerCommandDispatcher] = None,
    *,
    message: Optional[Message] = None,
    active_users: Optional[Dict] = None,
    current_username: Optional[str] = None,
    users_db_path: Optional[Path] = None,
    upload_manager: Optional[UploadTicketManager] = None,
    active_sessions: Optional[Dict] = None,
    log_dir: Optional[Path] = None,
) -> Tuple[Optional[Message], Optional[str], Optional[bytes]]:
    """Camada de compatibilidade para processar mensagens de controle."""
    actual_msg = msg or message
    if actual_msg is None:
        return None, None, None

    actual_user = authenticated_user or current_username
    actual_log = _resolve_log_path(log_path, log_dir)
    actual_repo = _resolve_repo(repo, users_db_path)
    actual_addr = client_address or ("127.0.0.1", 0)

    current_key = session_key
    if active_sessions and actual_user and actual_user in active_sessions:
        current_key = active_sessions[actual_user]

    context = ServerCommandContext(
        client_address=actual_addr,
        repo=actual_repo,
        log_path=actual_log,
        authenticated_user=actual_user,
        session_key=current_key,
        ticket_manager=ticket_manager or upload_manager,
        data_port=data_port,
        message=actual_msg,
    )

    actual_dispatcher = dispatcher or _default_dispatcher
    result = actual_dispatcher.dispatch(actual_msg, context)
    _update_legacy_dicts(result, actual_user, actual_addr, active_sessions, active_users)
    return result.response, result.authenticated_user, result.session_key


def handle_client_payload(
    raw_data: bytes,
    client_address: Tuple[str, int],
    repo: ClientRepository,
    log_path: Path,
    ticket_manager: Optional[UploadTicketManager] = None,
    data_port: int = DEFAULT_DATA_PORT,
) -> Tuple[bytes, Optional[str]]:
    """Processa um payload unitário unframed ou texto plano (compatibilidade retroativa)."""
    client_ip, client_port = client_address
    is_framed = len(raw_data) >= 40 and raw_data[:2] == CONTROL_MAGIC

    try:
        msg = Message.from_bytes(raw_data)
    except (ProtocolError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        raw_text = raw_data.decode("utf-8", errors="replace").strip()
        logger.info(
            "Mensagem em texto puro recebida de %s:%s: %s", client_ip, client_port, raw_text
        )
        log_message(log_path, client_address, raw_text)
        ack = f"ACK: Mensagem recebida pelo servidor ({datetime.now().strftime('%H:%M:%S')})\n"
        return ack.encode("utf-8"), None

    resp, active_user, _ = process_control_message(
        msg=msg,
        client_address=client_address,
        repo=repo,
        log_path=log_path,
        ticket_manager=ticket_manager,
        data_port=data_port,
    )
    if resp is None:
        return b"", None

    if is_framed:
        return resp.to_frame(hmac_key=DEFAULT_HANDSHAKE_KEY), active_user
    return resp.to_bytes(), active_user
