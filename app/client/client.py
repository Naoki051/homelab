#!/usr/bin/env python3
"""
Fachada de alto nível HomelabClient (com alias Client) orientada a objetos.
Encapsula o ciclo de vida da conexão, comandos, autenticação e sessão local.
"""

from pathlib import Path
from types import TracebackType
from typing import Any, List, Optional, Tuple, Type, Union

from app.client.commands import (
    ClientCommand,
    LoginCommand,
    RegisterCommand,
    SendMessageCommand,
    UploadFileCommand,
)
from app.client.conn_handler import ControlConnection
from app.client.session import Session
from app.config import ClientConfig, load_client_config
from app.logger import get_logger

logger = get_logger(__name__)

__all__: List[str] = [
    "HomelabClient",
    "Client",
]


class HomelabClient:
    """Cliente TCP Dual-Protocol para o Homelab com arquitetura orientada a objetos."""

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
        self.config = config if config is not None else load_client_config(env_file=env_file)
        self._apply_config_overrides(host, port, control_port, data_port, timeout, session_path)
        self.control_conn = control_conn
        self.session, self.username, self.secret_hash = self._resolve_initial_session(session)

    def _apply_config_overrides(
        self,
        host: Optional[str],
        port: Optional[int],
        control_port: Optional[int],
        data_port: Optional[int],
        timeout: Optional[float],
        session_path: Optional[Union[Path, str]],
    ) -> None:
        """Aplica overrides pontuais nas configurações do cliente."""
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

    def _resolve_initial_session(
        self,
        session: Optional[Session],
    ) -> Tuple[Optional[Session], Optional[str], Optional[str]]:
        """Carrega e valida a sessão inicial persistida."""
        active_session = session
        if active_session is None and self.config.session_path.is_file():
            active_session = Session.load(path=self.config.session_path)

        if active_session and active_session.is_valid():
            return active_session, active_session.last_username, active_session.last_password
        return active_session, None, None

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

    def execute_command(self, command: ClientCommand) -> Tuple[bool, Any]:
        """Executa um comando garantindo conexão ativa com o servidor."""
        if not self.connect() or self.control_conn is None:
            return False, "Falha na conexão com o servidor."
        return command.execute(self.control_conn)

    def login(
        self,
        username: str,
        password: Optional[str] = None,
        is_already_derived: bool = False,
    ) -> Tuple[bool, str]:
        """Autentica o cliente junto ao servidor via Canal de Controle."""
        if password is not None:
            secret_hash = (
                password if is_already_derived else Session.derive_secret(username, password)
            )
        elif (
            self.session
            and self.session.is_valid()
            and self.session.last_username == username
        ):
            secret_hash = self.session.last_password
        else:
            return False, "Senha não informada e nenhuma sessão válida disponível."

        cmd = LoginCommand(username, secret_hash, is_already_derived=True)
        ok, reason = self.execute_command(cmd)
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
        cmd = RegisterCommand(
            username,
            password or "",
            is_already_derived=is_already_derived,
        )
        ok, reason = self.execute_command(cmd)
        if ok:
            self.username = username
            self.secret_hash = cmd.secret_hash
            self.session = Session.create(
                username,
                cmd.secret_hash,
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

        cmd = SendMessageCommand(text, secret_hash=self.secret_hash or "")
        return self.execute_command(cmd)

    def upload_file(
        self,
        file_path: Union[str, Path],
        data_port: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """Realiza upload de arquivo fatiado em chunks de 64KB no Canal de Dados."""
        if not self.username:
            return False, "Cliente não autenticado. Faça login antes de enviar arquivos."

        target_port = data_port or self.config.data_port
        cmd = UploadFileCommand(
            file_path,
            data_port=target_port,
            secret_hash=self.secret_hash or "",
        )
        return self.execute_command(cmd)

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


# Alias retrocompatível
Client = HomelabClient
