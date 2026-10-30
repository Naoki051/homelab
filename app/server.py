#!/usr/bin/env python3
"""
Servidor TCP Educacional para Homelab
Escuta conexões TCP em uma porta designada, recebe mensagens de texto
e persiste os registros em um arquivo de log local com timestamp e IP de origem.
"""

import argparse
import os
from datetime import datetime
from pathlib import Path
import socket
import sys

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9000
DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "logs" / "server_messages.log"
BUFFER_SIZE = 4096


def log_message(log_file_path: Path, client_address: tuple, message: str) -> None:
    """Registra a mensagem recebida no arquivo de log com timestamp e endereço do cliente."""
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client_ip, client_port = client_address
    log_entry = f"[{timestamp}] [{client_ip}:{client_port}] {message.strip()}\n"

    with open(log_file_path, "a", encoding="utf-8") as f:
        f.write(log_entry)


def start_server(host: str, port: int, log_path: Path) -> None:
    """Inicia o ciclo de vida do servidor TCP: bind, listen e accept."""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((host, port))
        server_socket.listen(5)
        print("=" * 60)
        print(f"[*] Servidor TCP iniciado com sucesso!")
        print(f"[*] Escutando em: {host}:{port}")
        print(f"[*] Arquivo de log: {log_path}")
        print(f"[*] Pressione Ctrl+C para encerrar.")
        print("=" * 60)

        while True:
            client_socket, client_address = server_socket.accept()
            client_ip, client_port = client_address
            print(f"[+] Conexão estabelecida com {client_ip}:{client_port}")

            try:
                data = client_socket.recv(BUFFER_SIZE)
                if data:
                    message = data.decode("utf-8", errors="replace")
                    print(f"[>] Mensagem recebida: {message.strip()}")

                    # Persistência em arquivo de log
                    log_message(log_path, client_address, message)
                    print(f"[✓] Mensagem salva em {log_path.name}")

                    # Confirmação de recebimento ao cliente
                    ack_response = f"ACK: Mensagem recebida pelo servidor ({datetime.now().strftime('%H:%M:%S')})\n"
                    client_socket.sendall(ack_response.encode("utf-8"))
            except Exception as e:
                print(f"[!] Erro ao processar dados do cliente {client_ip}:{client_port} -> {e}")
            finally:
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
        description="Servidor TCP Educacional para registro de mensagens em log."
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

    args = parser.parse_args()
    start_server(host=args.host, port=args.port, log_path=args.log)


if __name__ == "__main__":
    main()
