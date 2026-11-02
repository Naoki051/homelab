"""Pacote Servidor Homelab Modular e Orientado a Objetos.

Re-exporta a infraestrutura do Canal de Controle, Canal de Dados, gerenciamento
de tickets de upload, roteador Command e fachadas de servidor.
"""

from typing import List

from app.server.commands import (
    LoginCommandHandler,
    LogoutCommandHandler,
    RegisterCommandHandler,
    RequestUploadCommandHandler,
    SendMessageCommandHandler,
    ServerCommandContext,
    ServerCommandDispatcher,
    ServerCommandHandler,
    ServerCommandResult,
    handle_client_payload,
    process_control_message,
)
from app.server.conn_handler import (
    BaseNetworkService,
    ControlServer,
    DataServer,
    handle_control_client_connection,
    handle_data_client_connection,
)
from app.server.server import (
    DualChannelServer,
    HomelabServer,
    Server,
    main,
    start_server,
)
from app.server.tickets import (
    UploadTicket,
    UploadTicketManager,
    compute_file_sha256,
    log_message,
)

__all__: List[str] = [
    "UploadTicket",
    "UploadTicketManager",
    "compute_file_sha256",
    "log_message",
    "ServerCommandContext",
    "ServerCommandResult",
    "ServerCommandHandler",
    "RegisterCommandHandler",
    "LoginCommandHandler",
    "SendMessageCommandHandler",
    "RequestUploadCommandHandler",
    "LogoutCommandHandler",
    "ServerCommandDispatcher",
    "process_control_message",
    "handle_client_payload",
    "BaseNetworkService",
    "ControlServer",
    "DataServer",
    "handle_control_client_connection",
    "handle_data_client_connection",
    "HomelabServer",
    "DualChannelServer",
    "Server",
    "start_server",
    "main",
]
