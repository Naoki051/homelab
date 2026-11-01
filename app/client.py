#!/usr/bin/env python3
"""
Cliente TCP Dual-Protocol para Homelab com Autenticação, Conexão Persistente, HMAC Dinâmico e Upload em Chunks
Oferece suporte a:
1. Canal de Controle Persistente (Porta 9000): Framing binário (40B) + HMAC-SHA256 com chave de sessão dinâmica.
2. Canal de Dados/Mídia (Porta 9001): Upload de imagens/arquivos em Chunks indexados de 64KB (62B header) + HMAC.
3. Quick Login automático (NoSQL / JSON local válido por até 7 dias).
"""

import argparse
import getpass
import hashlib
from pathlib import Path
import socket
import sys
from typing import Optional, Tuple

# Garante que a raiz do projeto esteja no sys.path para suportar execução a partir de qualquer diretório
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from app.client_session import Session
    from app.config import ClientConfig, load_client_config
    from app.protocol import (
        CHUNK_SIZE,
        CONTROL_MAGIC,
        DEFAULT_HANDSHAKE_KEY,
        MediaChunk,
        Message,
    )
except ImportError:
    from client_session import Session
    from config import ClientConfig, load_client_config
    from protocol import (
        CHUNK_SIZE,
        CONTROL_MAGIC,
        DEFAULT_HANDSHAKE_KEY,
        MediaChunk,
        Message,
    )

_initial_client_config = load_client_config()
DEFAULT_HOST = _initial_client_config.host
DEFAULT_PORT = _initial_client_config.control_port
DEFAULT_DATA_PORT = _initial_client_config.data_port
DEFAULT_HANDSHAKE_KEY = _initial_client_config.handshake_key
TIMEOUT_SECONDS = _initial_client_config.timeout
BUFFER_SIZE = _initial_client_config.buffer_size
CHUNK_SIZE = _initial_client_config.chunk_size
DEFAULT_SESSION_FILE = _initial_client_config.session_path
Session.DEFAULT_SESSION_FILE = DEFAULT_SESSION_FILE


def _compute_file_sha256(file_path: Path) -> str:
    """Calcula o hash SHA-256 de um arquivo lendo em blocos de 64 KB."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            block = f.read(CHUNK_SIZE)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


class ControlConnection:
    """
    Mantém uma conexão TCP persistente no Canal de Controle (Porta 9000)
    com Framing Binário e rotação automática para a `session_key` dinâmica após autenticação.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = TIMEOUT_SECONDS,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.session_key: bytes = DEFAULT_HANDSHAKE_KEY
        self.username: Optional[str] = None

    def connect(self) -> bool:
        """Abre a conexão TCP persistente com o servidor, caso ainda não esteja aberta."""
        if self.sock is not None:
            return True
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            s.connect((self.host, self.port))
            self.sock = s
            self.session_key = DEFAULT_HANDSHAKE_KEY
            return True
        except ConnectionRefusedError:
            print(
                f"\n[!] Erro: Conexão recusada em {self.host}:{self.port}. "
                "Certifique-se de que o servidor está rodando.",
                file=sys.stderr,
            )
            s.close()
            return False
        except OSError as e:
            print(f"\n[!] Erro ao conectar em {self.host}:{self.port}: {e}", file=sys.stderr)
            s.close()
            return False

    def send_request(self, message: Message) -> Optional[Message]:
        """Envia uma mensagem enquadrada (40B header + HMAC) na conexão persistente e lê a resposta."""
        if not self.connect() or self.sock is None:
            return None

        try:
            current_key = self.session_key
            message.send_framed(self.sock, hmac_key=current_key)
            resp = Message.recv_framed(self.sock, hmac_key=current_key)
            if resp is None:
                self.close()
                return None

            # Se o servidor emitiu uma nova chave de sessão dinâmica (após login ou registro), atualiza-a
            new_key_hex = resp.payload.get("session_key")
            if new_key_hex and resp.payload.get("status") == Message.STATUS_OK:
                self.session_key = bytes.fromhex(new_key_hex)

            return resp
        except Exception as e:
            print(f"\n[!] Erro na conexão persistente de controle: {e}", file=sys.stderr)
            self.close()
            return None

    def login(self, username: str, secret_hash: str) -> Tuple[bool, str]:
        req = Message(
            action=Message.ACTION_LOGIN,
            payload={"username": username, "password": secret_hash},
        )
        resp = self.send_request(req)
        if not resp:
            return False, "Sem resposta do servidor."
        ok = resp.payload.get("status") == Message.STATUS_OK
        if ok:
            self.username = username
        return ok, resp.payload.get("message", "")

    def register(self, username: str, secret_hash: str) -> Tuple[bool, str]:
        req = Message(
            action=Message.ACTION_REGISTER,
            payload={"username": username, "password": secret_hash},
        )
        resp = self.send_request(req)
        if not resp:
            return False, "Sem resposta do servidor."
        ok = resp.payload.get("status") == Message.STATUS_OK
        if ok:
            self.username = username
        return ok, resp.payload.get("message", "")

    def send_text(self, username: str, text: str, secret_hash: str = "") -> bool:
        req = Message(
            action=Message.ACTION_SEND,
            payload={"username": username, "password": secret_hash, "text": text},
        )
        resp = self.send_request(req)
        if not resp:
            return False
        status = resp.payload.get("status")
        msg = resp.payload.get("message", "")
        if status == Message.STATUS_OK:
            print(f"[<] Resposta do servidor: {msg}")
            return True
        print(f"[!] Erro retornado pelo servidor: {msg}", file=sys.stderr)
        return False

    def upload_file(
        self,
        file_path: Path,
        data_port: Optional[int] = None,
        secret_hash: str = "",
    ) -> Tuple[bool, str]:
        """
        Solicita um ticket no Canal de Controle (Porta 9000) e transmite o arquivo
        fatiado em Chunks de 64 KB autenticados com HMAC no Canal de Dados (Porta 9001).
        """
        path = Path(file_path)
        if not path.is_file():
            return False, f"Arquivo não encontrado: {path}"

        file_size = path.stat().st_size
        file_sha256 = _compute_file_sha256(path)

        req = Message(
            action=Message.ACTION_REQUEST_UPLOAD,
            payload={
                "username": self.username or "",
                "password": secret_hash,
                "filename": path.name,
                "file_size": file_size,
                "sha256": file_sha256,
            },
        )
        resp = self.send_request(req)
        if not resp:
            return False, "Sem resposta ao solicitar permissão de upload."

        if resp.payload.get("status") != Message.STATUS_OK:
            return False, resp.payload.get("message", "Upload negado pelo servidor.")

        ticket_hex = resp.payload["ticket"]
        target_data_port = data_port or int(resp.payload.get("data_port", DEFAULT_DATA_PORT))
        total_chunks = int(resp.payload.get("total_chunks", 1))

        print(
            f"[*] Iniciando upload de '{path.name}' ({file_size} bytes em {total_chunks} chunks de até 64KB) "
            f"via Canal de Dados {self.host}:{target_data_port}..."
        )

        data_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        data_sock.settimeout(self.timeout)
        try:
            data_sock.connect((self.host, target_data_port))
            for chunk in MediaChunk.slice_file(path, ticket=ticket_hex, chunk_size=CHUNK_SIZE):
                chunk.send(data_sock, hmac_key=self.session_key)

            final_resp = Message.recv_framed(data_sock, hmac_key=self.session_key)
            if not final_resp:
                return False, "Canal de dados fechou sem enviar confirmação final."

            ok = final_resp.payload.get("status") == Message.STATUS_OK
            msg = final_resp.payload.get("message", "")
            if ok:
                print(f"[✓] {msg}")
            else:
                print(f"[!] Erro no upload: {msg}", file=sys.stderr)
            return ok, msg
        except OSError as e:
            return False, f"Erro de rede no Canal de Dados: {e}"
        finally:
            data_sock.close()

    def close(self) -> None:
        if self.sock is not None:
            try:
                logout_msg = Message(action=Message.ACTION_LOGOUT, payload={})
                logout_msg.send_framed(self.sock, hmac_key=self.session_key)
                Message.recv_framed(self.sock, hmac_key=self.session_key)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
            self.session_key = DEFAULT_HANDSHAKE_KEY

    def __enter__(self) -> "ControlConnection":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def send_network_message(
    host: str,
    port: int,
    message: Message,
    use_framing: bool = False,
    hmac_key: bytes = DEFAULT_HANDSHAKE_KEY,
) -> Optional[Message]:
    """Envia uma mensagem pontual (compatível com servidores legados ou modo framed)."""
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.settimeout(TIMEOUT_SECONDS)

    try:
        client_socket.connect((host, port))
        if use_framing:
            message.send_framed(client_socket, hmac_key=hmac_key)
            return Message.recv_framed(client_socket, hmac_key=hmac_key)

        payload_bytes = message.to_bytes()
        client_socket.sendall(payload_bytes)

        raw_response = client_socket.recv(BUFFER_SIZE)
        if not raw_response:
            return None

        try:
            if len(raw_response) >= 40 and raw_response[:2] == CONTROL_MAGIC:
                return Message.from_frame(raw_response, hmac_key=hmac_key)
            return Message.from_bytes(raw_response)
        except Exception:
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
    conn: Optional[ControlConnection] = None,
) -> Tuple[bool, str]:
    """Envia requisição de autenticação para o servidor (via conexão persistente ou pontual)."""
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
    conn: Optional[ControlConnection] = None,
) -> Tuple[bool, str]:
    """Envia requisição de cadastro explícito para o servidor (via conexão persistente ou pontual)."""
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
    conn: Optional[ControlConnection] = None,
) -> bool:
    """Envia uma mensagem de texto autenticada ao servidor (via conexão persistente ou pontual)."""
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
    else:
        print(f"[!] Erro retornado pelo servidor: {message}", file=sys.stderr)
        return False


def run_auth_flow(
    host: str,
    port: int,
    conn: Optional[ControlConnection] = None,
) -> Optional[Tuple[str, str]]:
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
                    print(f"[*] Autenticando com Quick Login como '{session.last_username}'...")
                    ok, reason = do_login_request(
                        host, port, session.last_username, session.last_password, conn=conn
                    )
                    if ok:
                        print(f"[✓] Quick login aceito com sucesso! Bem-vindo, {session.last_username}.")
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
            ok, reason = do_login_request(host, port, username, secret_hash, conn=conn)
            if ok:
                print(f"[✓] Login realizado com sucesso! Bem-vindo, {username}.")
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
            ok, reason = do_register_request(host, port, username, secret_hash, conn=conn)
            if ok:
                print(f"[✓] Conta '{username}' criada com sucesso!")
                print(
                    f"[✓] Auto-login ativado: Sessão local gravada com validade de {Session.DEFAULT_TTL_DAYS} dias."
                )
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
    # Pré-processamento de argumentos para verificar se --env-file foi informado
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env-file", type=str, default=None)
    pre_args, remaining_argv = pre_parser.parse_known_args()

    cfg = load_client_config(env_file=pre_args.env_file, override=True if pre_args.env_file else False)
    Session.DEFAULT_SESSION_FILE = cfg.session_path

    parser = argparse.ArgumentParser(
        description="Cliente TCP Dual-Protocol Homelab (Controle Persistente + Upload em Chunks de 64KB)."
    )
    parser.add_argument(
        "--env-file",
        type=str,
        default=pre_args.env_file,
        help="Caminho para arquivo de variáveis de ambiente customizado (ex: client.env, .env.prod)",
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
        help="Caminho de arquivo/imagem opcional para upload em chunks de 64KB após autenticação.",
    )

    args = parser.parse_args(remaining_argv)

    with ControlConnection(host=args.host, port=args.port, timeout=cfg.timeout) as conn:
        auth_credentials = run_auth_flow(host=args.host, port=args.port, conn=conn)
        if not auth_credentials:
            sys.exit(0)

        username, secret_hash = auth_credentials

        if args.message:
            success = send_user_message(
                host=args.host,
                port=args.port,
                username=username,
                secret_hash=secret_hash,
                text=args.message,
                conn=conn,
            )
            if not args.upload:
                sys.exit(0 if success else 1)

        if args.upload:
            ok, _ = conn.upload_file(args.upload, data_port=args.data_port, secret_hash=secret_hash)
            sys.exit(0 if ok else 1)

        print(f"\n[*] Conexão TCP Persistente ativa para '{username}' (HMAC-SHA256 dinâmico).")
        print("[*] Digite sua mensagem ou use '/upload <caminho_do_arquivo>' para enviar mídia em chunks.")
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
                conn.upload_file(Path(raw_path), data_port=args.data_port, secret_hash=secret_hash)
                continue

            send_user_message(
                host=args.host,
                port=args.port,
                username=username,
                secret_hash=secret_hash,
                text=user_input,
                conn=conn,
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
