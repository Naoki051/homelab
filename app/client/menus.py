#!/usr/bin/env python3
"""
Interface de Terminal e Linha de Comando (CLI) para o Cliente Homelab.
Garante complexidade ciclomática <= 12 através da decomposição de ClientTerminalUI.
"""

import argparse
import getpass
from pathlib import Path
import sys
from typing import List, Optional, Tuple, Union

from app.client.client import HomelabClient
from app.client.conn_handler import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    ControlConnection,
    send_network_message,
)
from app.client.session import Session
from app.config import load_client_config
from app.protocol import Message

__all__: List[str] = [
    "ClientTerminalUI",
    "run_auth_flow",
    "interactive_menu",
    "do_login_request",
    "do_register_request",
    "send_user_message",
    "main",
]


class ClientTerminalUI:
    """Interface de terminal para autenticação e interação com o Homelab."""

    def __init__(self, client: HomelabClient) -> None:
        self.client = client

    def _print_auth_menu(self) -> None:
        """Exibe o cabeçalho e opções de acesso."""
        print("\n" + "=" * 55)
        print("          HOMELAB TCP CLIENT - ACESSO")
        print("=" * 55)
        print("  1. Login")
        print("  2. Register (Criar nova conta)")
        print("  3. Sair")
        print("=" * 55)

    def _handle_quick_login(self) -> Optional[Tuple[str, str]]:
        """Processa a oferta e execução de Quick Login local."""
        session = self.client.session or Session.load(path=self.client.config.session_path)
        if not session or not session.is_valid():
            return None

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
            ok, reason = self.client.login(session.last_username)
            if ok:
                print(f"[✓] Quick login aceito com sucesso! Bem-vindo, {session.last_username}.")
                return session.last_username, session.last_password

            print(f"[!] Falha no Quick Login: {reason}")
            print("[*] Limpando sessão local inválida...")
            Session.clear(path=self.client.config.session_path)
            self.client.session = None

        return None

    def _handle_credentials_login(self) -> Optional[Tuple[str, str]]:
        """Processa a captura de credenciais e login explícito."""
        print("\n--- 1.2.2 Identificação de Usuário ---")
        try:
            username = input("Username: ").strip()
            if not username:
                print("[!] Username obrigatório.")
                return None
            password = getpass.getpass("Password: ")
        except (KeyboardInterrupt, EOFError):
            return None

        ok, reason = self.client.login(username, password)
        if ok:
            print(f"[✓] Login realizado com sucesso! Bem-vindo, {username}.")
            return username, self.client.secret_hash or ""

        print(f"[!] Falha no login: {reason}")
        return None

    def _handle_registration(self) -> Optional[Tuple[str, str]]:
        """Processa a criação de conta e auto-login."""
        print("\n--- 2.1 Cadastro de Nova Conta ---")
        try:
            username = input("Escolha um Username (mínimo 3 caracteres): ").strip()
            if len(username) < 3:
                print("[!] O username deve conter pelo menos 3 caracteres.")
                return None
            password = getpass.getpass("Escolha uma Senha: ")
            if not password:
                print("[!] Senha não pode ser vazia.")
                return None
            confirm_password = getpass.getpass("Confirme a Senha: ")
            if password != confirm_password:
                print("[!] As senhas não conferem.")
                return None
        except (KeyboardInterrupt, EOFError):
            return None

        ok, reason = self.client.register(username, password)
        if ok:
            print(f"[✓] Conta '{username}' criada com sucesso!")
            print(
                f"[✓] Auto-login ativado: Sessão local gravada com validade de "
                f"{Session.DEFAULT_TTL_DAYS} dias."
            )
            return username, self.client.secret_hash or ""

        print(f"[!] Erro no cadastro: {reason}")
        return None

    def run_auth_flow(self) -> Optional[Tuple[str, str]]:
        """Orquestra o menu principal de autenticação."""
        while True:
            self._print_auth_menu()
            try:
                choice = input("Escolha uma opção [1-3]: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n[*] Operação cancelada.")
                return None

            if choice == "1":
                auth = self._handle_quick_login()
                if auth is not None:
                    return auth
                auth = self._handle_credentials_login()
                if auth is not None:
                    return auth
            elif choice == "2":
                auth = self._handle_registration()
                if auth is not None:
                    return auth
            elif choice == "3":
                print("[*] Encerrando o cliente. Até logo!")
                return None
            else:
                print("[!] Opção inválida. Digite 1, 2 ou 3.")

    def interactive_menu(self) -> None:
        """Sessão interativa de envio de mensagens e uploads."""
        username = self.client.username or "cliente"
        print(f"\n[*] Conexão TCP Persistente ativa para '{username}' (HMAC-SHA256 dinâmico).")
        print("[*] Digite sua mensagem ou use '/upload <caminho>' para enviar mídia.")
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
                ok, msg = self.client.upload_file(raw_path)
                if ok:
                    print(f"[✓] {msg}")
                else:
                    print(f"[!] Erro no upload: {msg}", file=sys.stderr)
                continue

            ok, msg = self.client.send_message(user_input)
            if ok:
                print(f"[<] Resposta do servidor: {msg}")
            else:
                print(f"[!] Erro retornado pelo servidor: {msg}", file=sys.stderr)


# ==============================================================================
# Funções Globais de Compatibilidade Retroativa
# ==============================================================================

def run_auth_flow(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    conn: Optional[ControlConnection] = None,
    client: Optional[HomelabClient] = None,
) -> Optional[Tuple[str, str]]:
    """Invoca o fluxo de autenticação com compatibilidade para chamadas funcionais."""
    if client is None:
        client = HomelabClient(host=host, control_port=port, control_conn=conn)
    return ClientTerminalUI(client).run_auth_flow()


def interactive_menu(client: HomelabClient) -> None:
    """Wrapper funcional para a sessão interativa."""
    ClientTerminalUI(client).interactive_menu()


def do_login_request(
    host: str,
    port: int,
    username: str,
    secret_hash: str,
    conn: Optional[Union[ControlConnection, HomelabClient]] = None,
) -> Tuple[bool, str]:
    """Envia requisição de login (via HomelabClient, ControlConnection ou efêmera)."""
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
    """Envia requisição de cadastro (via HomelabClient, ControlConnection ou efêmera)."""
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
    """Envia mensagem de texto autenticada (via HomelabClient, ControlConnection ou efêmera)."""
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
    print(f"[!] Erro retornado pelo servidor: {message}", file=sys.stderr)
    return False


def main() -> None:
    """Entrypoint principal da CLI do cliente Homelab."""
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env-file", type=str, default=None)
    pre_args, remaining_argv = pre_parser.parse_known_args()

    cfg = load_client_config(
        env_file=pre_args.env_file,
        override=True if pre_args.env_file else False,
    )
    Session.DEFAULT_SESSION_FILE = cfg.session_path

    parser = argparse.ArgumentParser(
        description="Cliente TCP Dual-Protocol Homelab (Controle + Mídia em Chunks 64KB)."
    )
    parser.add_argument(
        "--env-file",
        type=str,
        default=pre_args.env_file,
        help="Caminho para arquivo .env customizado.",
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
        help="Caminho de arquivo/imagem opcional para upload em chunks de 64KB.",
    )

    args = parser.parse_args(remaining_argv)
    cfg.host = args.host
    cfg.control_port = args.port
    cfg.data_port = args.data_port

    with HomelabClient(config=cfg) as client:
        auth_credentials = run_auth_flow(client=client)
        if not auth_credentials:
            sys.exit(0)

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
