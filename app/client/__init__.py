"""Pacote Cliente Homelab Modular e Orientado a Objetos.

Re-exporta a fachada de alto nível (HomelabClient / Client), o gerenciador de
conexões (ControlConnection, ClientConnectionHandler), classes do padrão Command,
gerenciamento de sessão local (Session), interface de terminal (ClientTerminalUI)
e funções utilitárias legadas.
"""

from typing import List

from app.client.client import Client, HomelabClient
from app.client.commands import (
    ClientCommand,
    LoginCommand,
    LogoutCommand,
    RegisterCommand,
    SendMessageCommand,
    UploadFileCommand,
)
from app.client.conn_handler import (
    ClientConnectionHandler,
    ControlConnection,
    send_network_message,
)
from app.client.menus import (
    ClientTerminalUI,
    do_login_request,
    do_register_request,
    interactive_menu,
    main,
    run_auth_flow,
    send_user_message,
)
from app.client.session import Session

__all__: List[str] = [
    "HomelabClient",
    "Client",
    "ControlConnection",
    "ClientConnectionHandler",
    "Session",
    "ClientCommand",
    "RegisterCommand",
    "LoginCommand",
    "SendMessageCommand",
    "UploadFileCommand",
    "LogoutCommand",
    "ClientTerminalUI",
    "send_network_message",
    "do_login_request",
    "do_register_request",
    "send_user_message",
    "run_auth_flow",
    "interactive_menu",
    "main",
]
