#!/usr/bin/env python3
"""
Servidor TCP Educacional para Homelab com Autenticação e Persistência SQLite
Escuta conexões TCP, processa envelopes do protocolo Message (registro, login e envio),
valida credenciais no banco SQLite e persiste registros em log.
"""

import argparse
from datetime import datetime
import os
from pathlib import Path
import socket
import sys
from typing import Optional, Tuple

from app.database import ClientRepository
from app.protocol import Message

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9000
DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "logs" / "server_messages.log"
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "homelab.db"
BUFFER_SIZE = 4096


def log_message(
    log_file_path: Path,
    client_address: Tuple[str, int],
    message: str,
    username: Optional[str] = None,
) -> None:
    """Registra a mensagem recebida no arquivo de log com timestamp, identificação de usuário e endereço do cliente."""
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client_ip, client_port = client_address
    sender = f"{username}@" if username else ""
    log_entry = f"[{timestamp}] [{sender}{client_ip}:{client_port}] {message.strip()}\n"

    with open(log_file_path, "a", encoding="utf-8") as f:
        f.write(log_entry)


def handle_client_payload(
    raw_data: bytes,
    client_address: Tuple[str, int],
    repo: ClientRepository,
    log_path: Path,
) -> Tuple[bytes, Optional[str]]:
    """
    Processa o payload recebido (via protocolo Message ou raw text)
    e retorna a resposta em bytes e o nome do usuário associado (se houver).
    """
    client_ip, client_port = client_address
    try:
        msg = Message.from_bytes(raw_data)
    except Exception:
        # Fallback de compatibilidade para mensagens em texto puro
        raw_text = raw_data.decode("utf-8", errors="replace").strip()
        print(f"[>] Mensagem em texto puro recebida de {client_ip}:{client_port}: {raw_text}")
        log_message(log_path, client_address, raw_text)
        ack = f"ACK: Mensagem recebida pelo servidor ({datetime.now().strftime('%H:%M:%S')})\n"
        return ack.encode("utf-8"), None

    action = msg.action
    payload = msg.payload
    username = payload.get("username", "").strip()
    password = payload.get("password", "")

    if action == Message.ACTION_REGISTER:
        print(f"[*] Requisição de registro para o usuário '{username}' de {client_ip}:{client_port}")
        ok, reason, client = repo.register(username, password)
        if ok:
            print(f"[+] Usuário '{username}' registrado com sucesso!")
            resp = Message.response(Message.STATUS_OK, reason, {"username": username})
            return resp.to_bytes(), username
        else:
            print(f"[!] Falha no registro do usuário '{username}': {reason}")
            resp = Message.response(Message.STATUS_ERROR, reason)
            return resp.to_bytes(), None

    elif action == Message.ACTION_LOGIN:
        print(f"[*] Tentativa de login do usuário '{username}' de {client_ip}:{client_port}")
        ok, reason, client = repo.authenticate(username, password)
        if ok:
            repo.update_status(username, "online")
            print(f"[+] Usuário '{username}' autenticado com sucesso! Status: online")
            resp = Message.response(
                Message.STATUS_OK,
                reason,
                {"username": username, "status": "online"},
            )
            return resp.to_bytes(), username
        else:
            print(f"[!] Login rejeitado para '{username}': {reason}")
            resp = Message.response(Message.STATUS_ERROR, reason)
            return resp.to_bytes(), None

    elif action == Message.ACTION_SEND:
        text = payload.get("text", "").strip()
        print(f"[*] Envio de mensagem autenticada por '{username}' de {client_ip}:{client_port}")
        ok, reason, client = repo.authenticate(username, password)
        if not ok:
            print(f"[!] Mensagem de '{username}' rejeitada: {reason}")
            resp = Message.response(Message.STATUS_ERROR, f"Autenticação requerida: {reason}")
            return resp.to_bytes(), None

        repo.update_status(username, "online")
        log_message(log_path, client_address, text, username=username)
        print(f"[✓] Mensagem de '{username}' salva no log: {text}")

        resp = Message.response(
            Message.STATUS_OK,
            f"Mensagem processada com sucesso para '{username}'",
            {"timestamp": datetime.now().strftime("%H:%M:%S")},
        )
        return resp.to_bytes(), username

    else:
        resp = Message.response(Message.STATUS_ERROR, f"Ação desconhecida: '{action}'")
        return resp.to_bytes(), None


def start_server(host: str, port: int, log_path: Path, db_path: Path) -> None:
    """Inicia o ciclo de vida do servidor TCP com banco SQLite e protocolo Message."""
    repo = ClientRepository(db_path=db_path)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((host, port))
        server_socket.listen(5)
        print("=" * 60)
        print(f"[*] Servidor TCP Homelab iniciado com sucesso!")
        print(f"[*] Escutando em: {host}:{port}")
        print(f"[*] Banco de dados SQLite: {db_path}")
        print(f"[*] Arquivo de log: {log_path}")
        print(f"[*] Pressione Ctrl+C para encerrar.")
        print("=" * 60)

        while True:
            client_socket, client_address = server_socket.accept()
            client_ip, client_port = client_address
            print(f"[+] Conexão aceita de {client_ip}:{client_port}")
            active_username: Optional[str] = None

            try:
                data = client_socket.recv(BUFFER_SIZE)
                if data:
                    response_bytes, active_username = handle_client_payload(
                        data, client_address, repo, log_path
                    )
                    client_socket.sendall(response_bytes)
            except Exception as e:
                print(f"[!] Erro ao processar socket de {client_ip}:{client_port} -> {e}")
            finally:
                if active_username:
                    repo.update_status(active_username, "offline")
                client_socket.close()
                print(f"[-] Conexão encerrada com {client_ip}:{client_port}\n")

    except KeyboardInterrupt:
        print("\n[*] Servidor interrompido pelo usuário (SIGINT). Encerrando...")
    except OSError as e:
        print(f"[!] Erro de socket no servidor: {e}", file=sys.stderr)
    finally:
        server_socket.close()
        print("[*] Socket do servidor finalizado com sucesso.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Servidor TCP Homelab com autenticação de clientes e persistência SQLite."
    )
    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help=f"Endereço de escuta (padrão: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Porta de escuta (padrão: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"Caminho do arquivo de log (padrão: {DEFAULT_LOG_PATH})",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Caminho do banco SQLite (padrão: {DEFAULT_DB_PATH})",
    )

    args = parser.parse_args()
    start_server(host=args.host, port=args.port, log_path=args.log, db_path=args.db)


if __name__ == "__main__":
    main()
