#!/usr/bin/env python3
"""Orquestrador e Fachada HomelabServer para a Arquitetura Dual-Channel TCP.

Módulo: app/server/server.py
"""

import argparse
from pathlib import Path
import socket
import threading
from types import TracebackType
from typing import List, Optional, Type

from app.config import ServerConfig, load_server_config
from app.database import ClientRepository
from app.logger import get_logger
from app.server.conn_handler import (
    ControlServer,
    DataServer,
)
from app.server.tickets import UploadTicketManager

logger = get_logger(__name__)

_cfg = load_server_config()
DEFAULT_HOST: str = _cfg.host
DEFAULT_PORT: int = _cfg.control_port
DEFAULT_DATA_PORT: int = _cfg.data_port
DEFAULT_LOG_PATH: Path = _cfg.log_path
DEFAULT_DB_PATH: Path = _cfg.db_path
DEFAULT_UPLOADS_DIR: Path = _cfg.uploads_dir

__all__: List[str] = [
    "HomelabServer",
    "DualChannelServer",
    "Server",
    "start_server",
    "main",
]


class HomelabServer:
    """Orquestrador da Arquitetura Dual-Channel do Homelab.

    Compõe e gerencia o ciclo de vida conjunto do Canal de Controle (ControlServer)
    e do Canal de Dados (DataServer), provendo suporte a Context Manager.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        control_port: int = DEFAULT_PORT,
        data_port: int = DEFAULT_DATA_PORT,
        log_path: Path = DEFAULT_LOG_PATH,
        db_path: Path = DEFAULT_DB_PATH,
        uploads_dir: Path = DEFAULT_UPLOADS_DIR,
        config: Optional[ServerConfig] = None,
    ) -> None:
        if config is not None:
            host = config.host
            control_port = config.control_port
            data_port = config.data_port
            log_path = config.log_path
            db_path = config.db_path
            uploads_dir = config.uploads_dir

        self.db_path = db_path
        self.uploads_dir = uploads_dir
        self.log_path = log_path
        self.repo = ClientRepository(db_path=self.db_path)
        self.ticket_manager = UploadTicketManager(uploads_dir=self.uploads_dir)

        self.control_server = ControlServer(
            host=host,
            port=control_port,
            repo=self.repo,
            log_path=self.log_path,
            ticket_manager=self.ticket_manager,
            data_port=data_port,
            db_path=self.db_path,
            uploads_dir=self.uploads_dir,
        )
        self.data_server = DataServer(
            host=host,
            port=data_port,
            ticket_manager=self.ticket_manager,
            log_path=self.log_path,
            uploads_dir=self.uploads_dir,
        )
        self.is_running = False

    @property
    def host(self) -> str:
        return self.control_server.host

    @property
    def control_port(self) -> int:
        return self.control_server.port

    @control_port.setter
    def control_port(self, val: int) -> None:
        self.control_server.port = val

    @property
    def data_port(self) -> int:
        return self.data_server.port

    @data_port.setter
    def data_port(self, val: int) -> None:
        self.data_server.port = val

    @property
    def control_socket(self) -> Optional[socket.socket]:
        return self.control_server.socket

    @property
    def data_socket(self) -> Optional[socket.socket]:
        return self.data_server.socket

    @property
    def running(self) -> bool:
        return self.is_running

    @running.setter
    def running(self, val: bool) -> None:
        self.is_running = val

    def bind_and_listen(self, backlog: int = 16) -> None:
        """Vincula os sockets de dados e controle preparando para aceitação."""
        self.data_server.bind_and_listen(backlog=backlog)
        self.control_server.data_port = self.data_server.port
        self.control_server.bind_and_listen(backlog=backlog)
        self.is_running = True

    def start(self) -> None:
        """Inicia os serviços de dados e controle em segundo plano."""
        if self.is_running:
            return
        self.data_server.start()
        self.control_server.data_port = self.data_server.port
        self.control_server.start()
        self.is_running = True

    def start_in_background(self) -> None:
        """Facade retrocompatível para inicialização em segundo plano."""
        self.start()

    def _accept_data_loop(self) -> None:
        self.data_server._accept_loop()

    def _accept_control_loop(self) -> None:
        self.control_server._accept_loop()

    def serve_forever(self) -> None:
        """Inicia o servidor e bloqueia a thread principal até encerramento."""
        self.start()
        logger.info("=" * 65)
        logger.info("Servidor TCP Dual-Protocol Homelab iniciado com sucesso!")
        logger.info(
            "Canal 1 (Controle Persistente + Framing): %s:%s",
            self.host,
            self.control_port,
        )
        logger.info(
            "Canal 2 (Dados/Mídia em Chunks 64KB):     %s:%s",
            self.host,
            self.data_port,
        )
        logger.info("Banco de dados SQLite: %s", self.db_path)
        logger.info("Diretório de uploads:  %s", self.uploads_dir)
        logger.info("Arquivo de log:        %s", self.log_path)
        logger.info("Pressione Ctrl+C para encerrar.")
        logger.info("=" * 65)

        try:
            while self.is_running:
                threading.Event().wait(0.5)
        except KeyboardInterrupt:
            logger.info("Servidor interrompido pelo usuário (SIGINT). Encerrando...")
        finally:
            self.stop()
            logger.info("Sockets do servidor finalizados com sucesso.")

    def stop(self) -> None:
        """Encerra ambos os serviços de controle e dados."""
        self.is_running = False
        self.control_server.stop()
        self.data_server.stop()

    def __enter__(self) -> "HomelabServer":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self.stop()


# Facades retrocompatíveis para clientes e testes legados
DualChannelServer = HomelabServer
Server = HomelabServer


def start_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    log_path: Path = DEFAULT_LOG_PATH,
    db_path: Path = DEFAULT_DB_PATH,
    data_port: int = DEFAULT_DATA_PORT,
    uploads_dir: Path = DEFAULT_UPLOADS_DIR,
    control_port: Optional[int] = None,
    env_file: Optional[str] = None,
) -> None:
    """Inicia o ciclo de vida do servidor TCP Dual-Channel."""
    effective_control_port = control_port if control_port is not None else port
    server = DualChannelServer(
        host=host,
        control_port=effective_control_port,
        data_port=data_port,
        log_path=log_path,
        db_path=db_path,
        uploads_dir=uploads_dir,
    )
    server.serve_forever()


def main() -> None:
    """Função principal para parsing de argumentos CLI e execução do servidor."""
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env-file", type=str, default=None)
    pre_args, remaining_argv = pre_parser.parse_known_args()

    cfg = load_server_config(
        env_file=pre_args.env_file,
        override=True if pre_args.env_file else False,
    )

    parser = argparse.ArgumentParser(
        description="Servidor TCP Dual-Protocol Homelab "
        "(Controle Persistente + Mídia em Chunks)."
    )
    parser.add_argument(
        "--env-file",
        type=str,
        default=pre_args.env_file,
        help="Caminho para arquivo de variáveis de ambiente customizado "
        "(ex: envs/server.env, envs/.env.prod)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=cfg.host,
        help=f"Endereço de escuta (padrão: {cfg.host})",
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
        help=f"Porta do Canal de Dados/Mídia em Chunks (padrão: {cfg.data_port})",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=cfg.log_path,
        help=f"Caminho do arquivo de log (padrão: {cfg.log_path})",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=cfg.db_path,
        help=f"Caminho do banco SQLite (padrão: {cfg.db_path})",
    )
    parser.add_argument(
        "--uploads-dir",
        type=Path,
        default=cfg.uploads_dir,
        help=f"Diretório para salvar uploads de mídia (padrão: {cfg.uploads_dir})",
    )

    args = parser.parse_args(remaining_argv)
    start_server(
        host=args.host,
        port=args.port,
        log_path=args.log,
        db_path=args.db,
        data_port=args.data_port,
        uploads_dir=args.uploads_dir,
    )
