#!/usr/bin/env python3
"""
Cliente TCP Educacional para Homelab
Conecta-se a um servidor TCP em um endereço e porta especificados,
envia uma mensagem de texto e aguarda a confirmação de recebimento.
"""

import argparse
import socket
import sys

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9000
TIMEOUT_SECONDS = 5.0
BUFFER_SIZE = 1024


def send_message(host: str, port: int, message: str) -> bool:
    """Cria um socket TCP, conecta-se ao servidor e transmite a mensagem."""
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.settimeout(TIMEOUT_SECONDS)

    try:
        print(f"[*] Conectando a {host}:{port}...")
        client_socket.connect((host, port))
        print(f"[+] Conectado com sucesso ao servidor!")

        # Envio da mensagem codificada em UTF-8
        payload = message.encode("utf-8")
        print(f"[>] Enviando ({len(payload)} bytes): {message}")
        client_socket.sendall(payload)

        # Aguardar resposta (ACK) do servidor
        response = client_socket.recv(BUFFER_SIZE)
        if response:
            print(f"[<] Resposta do servidor: {response.decode('utf-8', errors='replace').strip()}")

        return True

    except ConnectionRefusedError:
        print(
            f"[!] Erro: Conexão recusada em {host}:{port}. "
            "Certifique-se de que o servidor está rodando e a porta está correta.",
            file=sys.stderr,
        )
        return False
    except socket.timeout:
        print(
            f"[!] Erro: Tempo de espera esgotado ({TIMEOUT_SECONDS}s) aguardando {host}:{port}.",
            file=sys.stderr,
        )
        return False
    except OSError as e:
        print(f"[!] Erro de rede: {e}", file=sys.stderr)
        return False
    finally:
        client_socket.close()
        print("[*] Conexão com o servidor finalizada.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cliente TCP Educacional para envio de mensagens."
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
        help="Mensagem de texto a ser enviada. Se omitido, solicita via prompt interativo.",
    )

    args = parser.parse_args()

    message = args.message
    if not message:
        try:
            message = input("Digite a mensagem para enviar ao servidor: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[*] Operação cancelada pelo usuário.")
            sys.exit(0)

    if not message:
        print("[!] Mensagem vazia. Nada a enviar.", file=sys.stderr)
        sys.exit(1)

    success = send_message(host=args.host, port=args.port, message=message)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
