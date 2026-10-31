#!/usr/bin/env python3
"""
Cliente TCP Educacional para Homelab com Autenticação e Quick Login (NoSQL / JSON)
Oferece interface interativa no terminal com suporte a:
1. Login (com Quick Login automático para sessões salvas válidas por até 7 dias)
2. Register (cadastro de novo usuário com auto-login)
3. Envio de mensagens autenticadas para o servidor TCP.
"""

import argparse
import getpass
from pathlib import Path
import socket
import sys
from typing import Optional, Tuple

from app.client_session import Session
from app.protocol import Message

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9000
TIMEOUT_SECONDS = 5.0
BUFFER_SIZE = 4096


def send_network_message(
    host: str,
    port: int,
    message: Message,
) -> Optional[Message]:
    """Cria um socket TCP pontual, envia a mensagem serializada e aguarda resposta do servidor."""
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.settimeout(TIMEOUT_SECONDS)

    try:
        client_socket.connect((host, port))
        payload_bytes = message.to_bytes()
        client_socket.sendall(payload_bytes)

        raw_response = client_socket.recv(BUFFER_SIZE)
        if not raw_response:
            return None

        try:
            return Message.from_bytes(raw_response)
        except Exception:
            # Fallback para resposta textual simples
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
    except socket.timeout:
        print(
            f"\n[!] Erro: Tempo de espera esgotado ({TIMEOUT_SECONDS}s) aguardando {host}:{port}.",
            file=sys.stderr,
        )
        return None
    except OSError as e:
        print(f"\n[!] Erro de rede: {e}", file=sys.stderr)
        return None
    finally:
        client_socket.close()


def do_login_request(
    host: str,
    port: int,
    username: str,
    secret_hash: str,
) -> Tuple[bool, str]:
    """Envia requisição de autenticação para o servidor."""
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
) -> Tuple[bool, str]:
    """Envia requisição de cadastro explícito para o servidor."""
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
) -> bool:
    """Envia uma mensagem de texto autenticada ao servidor."""
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


def run_auth_flow(host: str, port: int) -> Optional[Tuple[str, str]]:
    """
    Executa a interface de terminal para Login ou Cadastro:
    1. Login (com Quick Login se houver sessão < 7 dias)
    2. Register (com Auto-login imediato)
    3. Sair
    Retorna tupla (username, secret_hash) em caso de sucesso ou None.
    """
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
            session = Session.load()
            # 1.1 / 1.2: Verifica se existe Quick Login válido
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
                    # 1.2.1: Entrou via Quick Login
                    print(f"[*] Autenticando com Quick Login como '{session.last_username}'...")
                    ok, reason = do_login_request(
                        host, port, session.last_username, session.last_password
                    )
                    if ok:
                        print(f"[✓] Quick login aceito com sucesso! Bem-vindo, {session.last_username}.")
                        # Renova a sessão por mais 7 dias
                        Session.create(
                            session.last_username,
                            session.last_password,
                            is_already_derived=True,
                            days=Session.DEFAULT_TTL_DAYS,
                        ).save()
                        return session.last_username, session.last_password
                    else:
                        print(f"[!] Falha no Quick Login: {reason}")
                        print("[*] Limpando sessão local inválida...")
                        Session.clear()

            # 1.2.2: Login manual (usuário e senha)
            print("\n--- 1.2.2 Identificação de Usuário ---")
            try:
                username = input("Username: ").strip()
                if not username:
                    print("[!] Username obrigatório.")
                    continue
                password = getpass.getpass("Password: ")
            except (KeyboardInterrupt, EOFError):
                return None

            secret_hash = Session.derive_secret(username, password)
            ok, reason = do_login_request(host, port, username, secret_hash)
            if ok:
                print(f"[✓] Login realizado com sucesso! Bem-vindo, {username}.")
                # Salva a sessão local para Quick Login futuro (7 dias)
                Session.create(
                    username,
                    secret_hash,
                    is_already_derived=True,
                    days=Session.DEFAULT_TTL_DAYS,
                ).save()
                return username, secret_hash
            else:
                print(f"[!] Falha no login: {reason}")

        elif choice == "2":
            # 2.1: Cadastro explícito de usuário
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

            secret_hash = Session.derive_secret(username, password)
            ok, reason = do_register_request(host, port, username, secret_hash)
            if ok:
                # 2.2: Auto-login
                print(f"[✓] Conta '{username}' criada com sucesso!")
                print(f"[✓] Auto-login ativado: Sessão local gravada com validade de {Session.DEFAULT_TTL_DAYS} dias.")
                Session.create(
                    username,
                    secret_hash,
                    is_already_derived=True,
                    days=Session.DEFAULT_TTL_DAYS,
                ).save()
                return username, secret_hash
            else:
                print(f"[!] Erro no cadastro: {reason}")

        elif choice == "3":
            print("[*] Encerrando o cliente. Até logo!")
            return None
        else:
            print("[!] Opção inválida. Digite 1, 2 ou 3.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cliente TCP Homelab com autenticação, classes OO e Quick Login."
    )
    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help=f"Endereço IP do servidor TCP (padrão: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Porta do servidor TCP (padrão: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "-m",
        "--message",
        type=str,
        help="Mensagem opcional a ser enviada após autenticação.",
    )

    args = parser.parse_args()

    # Executa fluxo interativo de autenticação (Login / Quick Login / Register)
    auth_credentials = run_auth_flow(host=args.host, port=args.port)
    if not auth_credentials:
        sys.exit(0)

    username, secret_hash = auth_credentials

    # Se a mensagem foi passada via argumento de linha de comando:
    if args.message:
        success = send_user_message(
            host=args.host,
            port=args.port,
            username=username,
            secret_hash=secret_hash,
            text=args.message,
        )
        sys.exit(0 if success else 1)

    # Caso contrário, abre loop interativo de mensagens
    print(f"\n[*] Modo de transmissão interativo para '{username}'.")
    print("[*] Digite sua mensagem e pressione Enter. Digite 'sair' ou Ctrl+C para encerrar.\n")

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

        send_user_message(
            host=args.host,
            port=args.port,
            username=username,
            secret_hash=secret_hash,
            text=user_input,
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
