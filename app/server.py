#!/usr/bin/env python3
"""
Servidor TCP Dual-Channel para Homelab com Autenticação, Framing Binário, Chunks e Persistência SQLite
- Canal de Controle (Porta 9000): Conexão TCP persistente por cliente (Thread-per-Client) com Framing (40B) e HMAC-SHA256 dinâmico.
- Canal de Dados/Mídia (Porta 9001): Recepção de arquivos pesados em Chunks indexados de 64KB (62B header) com streaming direto para disco.
"""

import argparse
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import math
from pathlib import Path
import socket
import sys
import threading
from typing import Dict, Optional, Set, Tuple

# Garante que a raiz do projeto esteja no sys.path para suportar execução a partir de qualquer diretório
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from app.database import ClientRepository
    from app.protocol import (
        CHUNK_SIZE,
        CONTROL_MAGIC,
        DEFAULT_HANDSHAKE_KEY,
        MediaChunk,
        Message,
        generate_session_key,
        generate_upload_ticket,
    )
except ImportError:
    from database import ClientRepository
    from protocol import (
        CHUNK_SIZE,
        CONTROL_MAGIC,
        DEFAULT_HANDSHAKE_KEY,
        MediaChunk,
        Message,
        generate_session_key,
        generate_upload_ticket,
    )

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9000
DEFAULT_DATA_PORT = 9001
DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "logs" / "server_messages.log"
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "homelab.db"
DEFAULT_UPLOADS_DIR = Path(__file__).resolve().parent / "data" / "uploads"
BUFFER_SIZE = 4096


@dataclass
class UploadTicket:
    """Representa uma autorização ativa para envio de arquivo em chunks no Canal de Dados."""

    ticket_hex: str
    username: str
    filename: str
    file_size: int
    total_chunks: int
    session_key: bytes
    dest_path: Path
    expected_sha256: Optional[str] = None
    received_chunks: Set[int] = field(default_factory=set)


class UploadTicketManager:
    """Gerenciador thread-safe de tickets de upload emitidos pelo Canal de Controle."""

    def __init__(self, uploads_dir: Path = DEFAULT_UPLOADS_DIR):
        self.uploads_dir = uploads_dir
        self._tickets: Dict[str, UploadTicket] = {}
        self._lock = threading.Lock()

    def create_ticket(
        self,
        username: str,
        filename: str,
        file_size: int,
        session_key: bytes,
        expected_sha256: Optional[str] = None,
    ) -> UploadTicket:
        """Cria e registra um novo ticket de upload preparando o arquivo de destino em disco."""
        safe_name = Path(filename).name or "upload.bin"
        timestamp_prefix = datetime.now().strftime("%Y%m%d_%H%M%S")
        ticket_bytes = generate_upload_ticket()
        ticket_hex = ticket_bytes.hex()

        user_dir = self.uploads_dir / username
        user_dir.mkdir(parents=True, exist_ok=True)
        dest_path = user_dir / f"{timestamp_prefix}_{ticket_hex[:8]}_{safe_name}"

        total_chunks = max(1, math.ceil(file_size / CHUNK_SIZE)) if file_size > 0 else 1

        # Pré-cria o arquivo vazio no disco para escrita posicional dos chunks
        with open(dest_path, "wb") as f:
            if file_size > 0:
                f.truncate(file_size)

        ticket = UploadTicket(
            ticket_hex=ticket_hex,
            username=username,
            filename=safe_name,
            file_size=file_size,
            total_chunks=total_chunks,
            session_key=session_key,
            dest_path=dest_path,
            expected_sha256=expected_sha256,
        )

        with self._lock:
            self._tickets[ticket_hex] = ticket
        return ticket

    def get_ticket(self, ticket_hex: str) -> Optional[UploadTicket]:
        with self._lock:
            return self._tickets.get(ticket_hex)

    def get_session_key(self, ticket_hex: str) -> Optional[bytes]:
        with self._lock:
            ticket = self._tickets.get(ticket_hex)
            return ticket.session_key if ticket else None

    def remove_ticket(self, ticket_hex: str) -> None:
        with self._lock:
            self._tickets.pop(ticket_hex, None)


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


def process_control_message(
    msg: Message,
    client_address: Tuple[str, int],
    repo: ClientRepository,
    log_path: Path,
    authenticated_user: Optional[str] = None,
    session_key: bytes = DEFAULT_HANDSHAKE_KEY,
    ticket_manager: Optional[UploadTicketManager] = None,
    data_port: int = DEFAULT_DATA_PORT,
) -> Tuple[Message, Optional[str], bytes]:
    """
    Processa um objeto Message do Canal de Controle e retorna:
    (mensagem_de_resposta, usuario_autenticado_atual, chave_hmac_proxima_mensagem)
    """
    client_ip, client_port = client_address
    action = msg.action
    payload = msg.payload
    username = payload.get("username", "").strip() or (authenticated_user or "")
    password = payload.get("password", "")

    if action == Message.ACTION_REGISTER:
        print(f"[*] Requisição de registro para o usuário '{username}' de {client_ip}:{client_port}")
        ok, reason, _ = repo.register(username, password)
        if ok:
            repo.update_status(username, "online")
            new_session_key = generate_session_key()
            print(f"[+] Usuário '{username}' registrado com sucesso! Chave de sessão HMAC emitida.")
            resp = Message.response(
                Message.STATUS_OK,
                reason,
                {
                    "username": username,
                    "presence": "online",
                    "session_key": new_session_key.hex(),
                },
            )
            return resp, username, new_session_key
        else:
            print(f"[!] Falha no registro do usuário '{username}': {reason}")
            resp = Message.response(Message.STATUS_ERROR, reason)
            return resp, authenticated_user, session_key

    elif action == Message.ACTION_LOGIN:
        print(f"[*] Tentativa de login do usuário '{username}' de {client_ip}:{client_port}")
        ok, reason, _ = repo.authenticate(username, password)
        if ok:
            repo.update_status(username, "online")
            new_session_key = generate_session_key()
            print(f"[+] Usuário '{username}' autenticado com sucesso! Status: online")
            resp = Message.response(
                Message.STATUS_OK,
                reason,
                {
                    "username": username,
                    "presence": "online",
                    "session_key": new_session_key.hex(),
                },
            )
            return resp, username, new_session_key
        else:
            print(f"[!] Login rejeitado para '{username}': {reason}")
            resp = Message.response(Message.STATUS_ERROR, reason)
            return resp, authenticated_user, session_key

    elif action == Message.ACTION_SEND:
        text = payload.get("text", "").strip()
        print(f"[*] Envio de mensagem autenticada por '{username}' de {client_ip}:{client_port}")

        # Se a conexão já está autenticada via sessão persistente + HMAC válido, evita re-hash PBKDF2
        if authenticated_user and username == authenticated_user:
            auth_ok, reason = True, "Sessão persistente autenticada via HMAC"
        else:
            auth_ok, reason, _ = repo.authenticate(username, password)

        if not auth_ok:
            print(f"[!] Mensagem de '{username}' rejeitada: {reason}")
            resp = Message.response(Message.STATUS_ERROR, f"Autenticação requerida: {reason}")
            return resp, authenticated_user, session_key

        repo.update_status(username, "online")
        log_message(log_path, client_address, text, username=username)
        print(f"[✓] Mensagem de '{username}' salva no log: {text}")

        resp = Message.response(
            Message.STATUS_OK,
            f"Mensagem processada com sucesso para '{username}'",
            {"timestamp": datetime.now().strftime("%H:%M:%S")},
        )
        return resp, username, session_key

    elif action == Message.ACTION_REQUEST_UPLOAD:
        if authenticated_user and username == authenticated_user:
            auth_ok, reason = True, "Sessão persistente autenticada"
        else:
            auth_ok, reason, _ = repo.authenticate(username, password)

        if not auth_ok:
            resp = Message.response(Message.STATUS_ERROR, f"Autenticação requerida para upload: {reason}")
            return resp, authenticated_user, session_key

        if ticket_manager is None:
            resp = Message.response(Message.STATUS_ERROR, "Serviço de upload de mídia indisponível.")
            return resp, authenticated_user, session_key

        filename = str(payload.get("filename", "arquivo.bin"))
        file_size = int(payload.get("file_size", 0))
        expected_sha256 = payload.get("sha256")

        if file_size < 0:
            resp = Message.response(Message.STATUS_ERROR, "Tamanho de arquivo inválido.")
            return resp, authenticated_user, session_key

        ticket = ticket_manager.create_ticket(
            username=username,
            filename=filename,
            file_size=file_size,
            session_key=session_key,
            expected_sha256=expected_sha256,
        )
        print(
            f"[*] Ticket de upload '{ticket.ticket_hex[:8]}...' emitido para '{username}' "
            f"({ticket.filename}, {file_size} bytes, {ticket.total_chunks} chunks)"
        )
        resp = Message.response(
            Message.STATUS_OK,
            f"Upload autorizado para '{ticket.filename}'",
            {
                "ticket": ticket.ticket_hex,
                "chunk_size": CHUNK_SIZE,
                "total_chunks": ticket.total_chunks,
                "data_port": data_port,
            },
        )
        return resp, username, session_key

    elif action == Message.ACTION_LOGOUT:
        if authenticated_user:
            repo.update_status(authenticated_user, "offline")
        resp = Message.response(Message.STATUS_OK, "Sessão encerrada com sucesso.")
        return resp, None, DEFAULT_HANDSHAKE_KEY

    else:
        resp = Message.response(Message.STATUS_ERROR, f"Ação desconhecida: '{action}'")
        return resp, authenticated_user, session_key


def handle_client_payload(
    raw_data: bytes,
    client_address: Tuple[str, int],
    repo: ClientRepository,
    log_path: Path,
) -> Tuple[bytes, Optional[str]]:
    """
    Processa um payload unitário (compatível com clientes legados e testes unitários)
    e retorna a resposta em bytes e o nome do usuário associado (se houver).
    """
    client_ip, client_port = client_address
    is_framed = len(raw_data) >= 40 and raw_data[:2] == CONTROL_MAGIC

    try:
        msg = Message.from_bytes(raw_data)
    except Exception:
        raw_text = raw_data.decode("utf-8", errors="replace").strip()
        print(f"[>] Mensagem em texto puro recebida de {client_ip}:{client_port}: {raw_text}")
        log_message(log_path, client_address, raw_text)
        ack = f"ACK: Mensagem recebida pelo servidor ({datetime.now().strftime('%H:%M:%S')})\n"
        return ack.encode("utf-8"), None

    resp, active_user, _ = process_control_message(
        msg=msg,
        client_address=client_address,
        repo=repo,
        log_path=log_path,
    )
    if is_framed:
        return resp.to_frame(hmac_key=DEFAULT_HANDSHAKE_KEY), active_user
    return resp.to_bytes(), active_user


def compute_file_sha256(file_path: Path) -> str:
    """Calcula o SHA-256 de um arquivo em disco lendo em blocos de 64 KB."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            block = f.read(CHUNK_SIZE)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def handle_control_client_connection(
    client_socket: socket.socket,
    client_address: Tuple[str, int],
    repo: ClientRepository,
    log_path: Path,
    ticket_manager: UploadTicketManager,
    data_port: int,
) -> None:
    """
    Atende um cliente no Canal de Controle (Porta 9000) em thread dedicada.
    Suporta conexões TCP persistentes com Framing Binário + HMAC dinâmico
    e mantém fallback automático para pacotes pontuais JSON/texto.
    """
    client_ip, client_port = client_address
    active_username: Optional[str] = None
    current_hmac_key: bytes = DEFAULT_HANDSHAKE_KEY

    try:
        prefix = client_socket.recv(2)
        if not prefix:
            return

        # Modo 1: Conexão Persistente com Enquadramento Binário (Magic == b"HC")
        if prefix == CONTROL_MAGIC:
            first_iteration = True
            while True:
                pre_read = prefix if first_iteration else b""
                first_iteration = False

                msg = Message.recv_framed(
                    client_socket,
                    hmac_key=current_hmac_key,
                    pre_read_prefix=pre_read,
                )
                if msg is None:
                    break

                resp, active_username, next_hmac_key = process_control_message(
                    msg=msg,
                    client_address=client_address,
                    repo=repo,
                    log_path=log_path,
                    authenticated_user=active_username,
                    session_key=current_hmac_key,
                    ticket_manager=ticket_manager,
                    data_port=data_port,
                )

                # A resposta é assinada com a chave vigente no momento da requisição
                resp.send_framed(client_socket, hmac_key=current_hmac_key)
                # Atualiza para a nova session_key dinâmica (caso login/register tenha ocorrido)
                current_hmac_key = next_hmac_key

                if msg.action == Message.ACTION_LOGOUT:
                    break
        else:
            # Modo 2: Fallback para conexão pontual legada (JSON puro ou texto)
            rest = client_socket.recv(BUFFER_SIZE)
            raw_data = prefix + rest
            response_bytes, active_username = handle_client_payload(
                raw_data, client_address, repo, log_path
            )
            client_socket.sendall(response_bytes)

    except Exception as e:
        print(f"[!] Erro no Canal de Controle ({client_ip}:{client_port}) -> {e}")
    finally:
        if active_username:
            repo.update_status(active_username, "offline")
        try:
            client_socket.close()
        except Exception:
            pass
        print(f"[-] Conexão de controle encerrada com {client_ip}:{client_port}")


def handle_data_client_connection(
    client_socket: socket.socket,
    client_address: Tuple[str, int],
    ticket_manager: UploadTicketManager,
    log_path: Path,
) -> None:
    """
    Atende uma transferência de arquivo em Chunks de 64 KB no Canal de Dados (Porta 9001).
    Cada chunk é validado via HMAC-SHA256 e gravado diretamente no disco (streaming).
    """
    client_ip, client_port = client_address
    current_ticket: Optional[UploadTicket] = None

    try:
        while True:
            chunk = MediaChunk.recv_from_socket(
                client_socket,
                key_resolver=ticket_manager.get_session_key,
            )
            if chunk is None:
                break

            ticket = ticket_manager.get_ticket(chunk.ticket_hex)
            if ticket is None:
                raise ValueError(f"Ticket não encontrado: {chunk.ticket_hex}")
            current_ticket = ticket

            if chunk.total_chunks != ticket.total_chunks:
                raise ValueError(
                    f"Total de chunks divergente ({chunk.total_chunks} != {ticket.total_chunks})."
                )

            # Grava os bytes do bloco diretamente na posição correspondente do arquivo em disco
            offset = chunk.chunk_index * CHUNK_SIZE
            with open(ticket.dest_path, "r+b") as f:
                f.seek(offset)
                f.write(chunk.data)

            ticket.received_chunks.add(chunk.chunk_index)

            # Verifica se todos os chunks esperados já foram recebidos
            if len(ticket.received_chunks) >= ticket.total_chunks:
                actual_sha256 = compute_file_sha256(ticket.dest_path)
                if ticket.expected_sha256 and actual_sha256 != ticket.expected_sha256:
                    ticket.dest_path.unlink(missing_ok=True)
                    ticket_manager.remove_ticket(ticket.ticket_hex)
                    err_resp = Message.response(
                        Message.STATUS_ERROR,
                        "Hash SHA-256 final do arquivo diverge do esperado.",
                    )
                    err_resp.send_framed(client_socket, hmac_key=ticket.session_key)
                    return

                log_message(
                    log_path,
                    client_address,
                    f"UPLOAD CONCLUÍDO: '{ticket.filename}' ({ticket.file_size} bytes, "
                    f"{ticket.total_chunks} chunks, sha256={actual_sha256[:12]}...)",
                    username=ticket.username,
                )
                print(
                    f"[✓] Upload concluído para '{ticket.username}': {ticket.dest_path.name} "
                    f"({ticket.total_chunks} chunks)"
                )
                ok_resp = Message.response(
                    Message.STATUS_OK,
                    f"Arquivo '{ticket.filename}' recebido com sucesso ({ticket.total_chunks} chunks).",
                    {
                        "filename": ticket.filename,
                        "file_size": ticket.file_size,
                        "total_chunks": ticket.total_chunks,
                        "sha256": actual_sha256,
                        "saved_path": str(ticket.dest_path),
                    },
                )
                ok_resp.send_framed(client_socket, hmac_key=ticket.session_key)
                ticket_manager.remove_ticket(ticket.ticket_hex)
                break

    except Exception as e:
        print(f"[!] Erro no Canal de Dados ({client_ip}:{client_port}) -> {e}")
        if current_ticket:
            try:
                err_resp = Message.response(Message.STATUS_ERROR, f"Falha no upload: {e}")
                err_resp.send_framed(client_socket, hmac_key=current_ticket.session_key)
            except Exception:
                pass
    finally:
        try:
            client_socket.close()
        except Exception:
            pass


class DualChannelServer:
    """Gerencia o ciclo de vida dos sockets de Controle (Porta 9000) e de Dados (Porta 9001)."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        control_port: int = DEFAULT_PORT,
        data_port: int = DEFAULT_DATA_PORT,
        log_path: Path = DEFAULT_LOG_PATH,
        db_path: Path = DEFAULT_DB_PATH,
        uploads_dir: Path = DEFAULT_UPLOADS_DIR,
    ):
        self.host = host
        self.control_port = control_port
        self.data_port = data_port
        self.log_path = log_path
        self.db_path = db_path
        self.uploads_dir = uploads_dir

        self.repo = ClientRepository(db_path=self.db_path)
        self.ticket_manager = UploadTicketManager(uploads_dir=self.uploads_dir)

        self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.control_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.running = False

    def bind_and_listen(self, backlog: int = 16) -> None:
        self.control_socket.bind((self.host, self.control_port))
        self.control_socket.listen(backlog)
        self.control_port = self.control_socket.getsockname()[1]

        self.data_socket.bind((self.host, self.data_port))
        self.data_socket.listen(backlog)
        self.data_port = self.data_socket.getsockname()[1]
        self.running = True

    def _accept_data_loop(self) -> None:
        while self.running:
            try:
                client_sock, client_addr = self.data_socket.accept()
                if not self.running:
                    client_sock.close()
                    break
                t = threading.Thread(
                    target=handle_data_client_connection,
                    args=(client_sock, client_addr, self.ticket_manager, self.log_path),
                    daemon=True,
                )
                t.start()
            except OSError:
                break

    def _accept_control_loop(self) -> None:
        while self.running:
            try:
                client_sock, client_addr = self.control_socket.accept()
                if not self.running:
                    client_sock.close()
                    break
                client_ip, client_port = client_addr
                print(f"[+] Conexão de controle aceita de {client_ip}:{client_port}")
                t = threading.Thread(
                    target=handle_control_client_connection,
                    args=(
                        client_sock,
                        client_addr,
                        self.repo,
                        self.log_path,
                        self.ticket_manager,
                        self.data_port,
                    ),
                    daemon=True,
                )
                t.start()
            except OSError:
                break

    def start_in_background(self) -> None:
        """Inicia os loops de aceitação de Controle e Dados em threads de segundo plano."""
        self.bind_and_listen()
        threading.Thread(target=self._accept_data_loop, daemon=True).start()
        threading.Thread(target=self._accept_control_loop, daemon=True).start()

    def serve_forever(self) -> None:
        """Inicia o servidor bloqueando a thread principal no loop de Controle."""
        self.bind_and_listen()
        print("=" * 65)
        print("[*] Servidor TCP Dual-Protocol Homelab iniciado com sucesso!")
        print(f"[*] Canal 1 (Controle Persistente + Framing): {self.host}:{self.control_port}")
        print(f"[*] Canal 2 (Dados/Mídia em Chunks 64KB):     {self.host}:{self.data_port}")
        print(f"[*] Banco de dados SQLite: {self.db_path}")
        print(f"[*] Diretório de uploads:  {self.uploads_dir}")
        print(f"[*] Arquivo de log:        {self.log_path}")
        print("[*] Pressione Ctrl+C para encerrar.")
        print("=" * 65)

        data_thread = threading.Thread(target=self._accept_data_loop, daemon=True)
        data_thread.start()

        try:
            self._accept_control_loop()
        except KeyboardInterrupt:
            print("\n[*] Servidor interrompido pelo usuário (SIGINT). Encerrando...")
        finally:
            self.stop()
            print("[*] Sockets do servidor finalizados com sucesso.")

    def stop(self) -> None:
        self.running = False
        for sock in (self.control_socket, self.data_socket):
            try:
                sock.close()
            except Exception:
                pass


def start_server(
    host: str,
    port: int,
    log_path: Path,
    db_path: Path,
    data_port: int = DEFAULT_DATA_PORT,
    uploads_dir: Path = DEFAULT_UPLOADS_DIR,
) -> None:
    """Inicia o ciclo de vida do servidor TCP Dual-Channel."""
    server = DualChannelServer(
        host=host,
        control_port=port,
        data_port=data_port,
        log_path=log_path,
        db_path=db_path,
        uploads_dir=uploads_dir,
    )
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Servidor TCP Dual-Protocol Homelab (Controle Persistente + Mídia em Chunks)."
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
        help=f"Porta do Canal de Controle (padrão: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--data-port",
        type=int,
        default=DEFAULT_DATA_PORT,
        help=f"Porta do Canal de Dados/Mídia em Chunks (padrão: {DEFAULT_DATA_PORT})",
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
    parser.add_argument(
        "--uploads-dir",
        type=Path,
        default=DEFAULT_UPLOADS_DIR,
        help=f"Diretório para salvar uploads de mídia (padrão: {DEFAULT_UPLOADS_DIR})",
    )

    args = parser.parse_args()
    start_server(
        host=args.host,
        port=args.port,
        log_path=args.log,
        db_path=args.db,
        data_port=args.data_port,
        uploads_dir=args.uploads_dir,
    )


if __name__ == "__main__":
    main()
