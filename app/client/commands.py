#!/usr/bin/env python3
"""
Padrão Command para operações do cliente Homelab.
Encapsula as ações de registro, login, envio de mensagens e upload em chunks.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

from app.client.conn_handler import ControlConnection
from app.client.session import Session
from app.exceptions import HMACVerificationError, ProtocolError
from app.logger import get_logger
from app.protocol import Message

logger = get_logger(__name__)

__all__: List[str] = [
    "ClientCommand",
    "RegisterCommand",
    "LoginCommand",
    "SendMessageCommand",
    "UploadFileCommand",
    "LogoutCommand",
]


class ClientCommand(ABC):
    """Classe base abstrata para comandos executados pelo cliente no canal de controle."""

    @abstractmethod
    def execute(self, conn: ControlConnection) -> Tuple[bool, Any]:
        """Executa o comando através de uma conexão de controle ativa."""
        pass


class RegisterCommand(ClientCommand):
    """Encapsula o cadastro de uma nova conta de usuário."""

    def __init__(
        self,
        username: str,
        password_or_hash: str,
        is_already_derived: bool = False,
    ) -> None:
        self.username = username
        if is_already_derived:
            self.secret_hash = password_or_hash
        else:
            self.secret_hash = Session.derive_secret(username, password_or_hash)

    def execute(self, conn: ControlConnection) -> Tuple[bool, str]:
        if not conn.connect() or conn.sock is None:
            return False, "Falha na conexão com o servidor."
        return conn.register(self.username, self.secret_hash)


class LoginCommand(ClientCommand):
    """Encapsula a autenticação de usuário no servidor."""

    def __init__(
        self,
        username: str,
        password_or_hash: str,
        is_already_derived: bool = False,
    ) -> None:
        self.username = username
        if is_already_derived:
            self.secret_hash = password_or_hash
        else:
            self.secret_hash = Session.derive_secret(username, password_or_hash)

    def execute(self, conn: ControlConnection) -> Tuple[bool, str]:
        if not conn.connect() or conn.sock is None:
            return False, "Falha na conexão com o servidor."
        return conn.login(self.username, self.secret_hash)


class SendMessageCommand(ClientCommand):
    """Encapsula o envio de mensagem de texto autenticada."""

    def __init__(self, text: str, secret_hash: str = "") -> None:
        self.text = text
        self.secret_hash = secret_hash

    def execute(self, conn: ControlConnection) -> Tuple[bool, str]:
        if not conn.connect() or conn.sock is None:
            return False, "Falha na conexão com o servidor."
        if not conn.username:
            return False, "Cliente não autenticado. Faça login antes de enviar mensagens."

        req = Message(
            action=Message.ACTION_SEND,
            payload={
                "username": conn.username,
                "password": self.secret_hash,
                "text": self.text,
            },
        )
        resp = conn.send_request(req)
        if not resp:
            return False, "Sem resposta do servidor."

        status = resp.payload.get("status")
        msg = resp.payload.get("message", "")
        return status == Message.STATUS_OK, msg


class UploadFileCommand(ClientCommand):
    """Encapsula o upload de arquivos via canal de controle (ticket) e dados (chunks)."""

    def __init__(
        self,
        file_path: Union[str, Path],
        data_port: Optional[int] = None,
        secret_hash: str = "",
    ) -> None:
        self.file_path = Path(file_path)
        self.data_port = data_port
        self.secret_hash = secret_hash

    def execute(self, conn: ControlConnection) -> Tuple[bool, str]:
        if not conn.connect() or conn.sock is None:
            return False, "Falha na conexão com o servidor."
        if not conn.username:
            return False, "Cliente não autenticado. Faça login antes de enviar arquivos."
        if not self.file_path.is_file():
            return False, f"Arquivo não encontrado: {self.file_path}"

        return conn.upload_file(
            self.file_path,
            data_port=self.data_port,
            secret_hash=self.secret_hash,
        )


class LogoutCommand(ClientCommand):
    """Encapsula o encerramento gracioso da sessão no servidor."""

    def execute(self, conn: ControlConnection) -> Tuple[bool, str]:
        if conn.sock is None:
            return True, "Conexão já encerrada."

        try:
            logout_msg = Message(action=Message.ACTION_LOGOUT, payload={})
            resp = conn.send_request(logout_msg)
            msg = (
                resp.payload.get("message", "Logout realizado com sucesso.")
                if resp
                else "Logout realizado."
            )
            return True, msg
        except (
            ConnectionResetError,
            BrokenPipeError,
            TimeoutError,
            OSError,
            ProtocolError,
            HMACVerificationError,
            ValueError,
        ) as e:
            logger.debug("Erro não-crítico ao enviar logout: %s", e)
            return False, f"Erro no logout: {e}"
