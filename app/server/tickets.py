#!/usr/bin/env python3
"""Gerenciamento de tickets de upload, hashing em streaming e logs de auditoria.

Módulo: app/server/tickets.py
"""

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import math
from pathlib import Path
import threading
import time
from typing import Dict, List, Optional, Set, Tuple, Union

from app.config import load_server_config
from app.protocol import CHUNK_SIZE, generate_upload_ticket

_initial_cfg = load_server_config()
DEFAULT_UPLOADS_DIR: Path = _initial_cfg.uploads_dir

__all__: List[str] = [
    "UploadTicket",
    "UploadTicketManager",
    "compute_file_sha256",
    "log_message",
]


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
    created_at: float = field(default_factory=time.time)

    def is_expired(self, ttl_seconds: float = 300.0) -> bool:
        """Verifica se o ticket ultrapassou o tempo de vida útil (TTL)."""
        return (time.time() - self.created_at) > ttl_seconds

    def is_complete(self) -> bool:
        """Verifica se todos os chunks esperados já foram recebidos."""
        return len(self.received_chunks) >= self.total_chunks

    def progress_percentage(self) -> float:
        """Calcula o percentual de progresso da transferência."""
        if self.total_chunks <= 0:
            return 0.0
        return (len(self.received_chunks) / self.total_chunks) * 100.0


class UploadTicketManager:
    """Gerenciador thread-safe de tickets de upload com suporte a expiração e pré-alocação."""

    def __init__(self, uploads_dir: Path = DEFAULT_UPLOADS_DIR) -> None:
        self.uploads_dir: Path = Path(uploads_dir)
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

    def get_ticket(
        self, ticket_hex: str, ttl_seconds: Optional[float] = None
    ) -> Optional[UploadTicket]:
        """Consulta um ticket de forma thread-safe com validação opcional de TTL."""
        with self._lock:
            ticket = self._tickets.get(ticket_hex)
            if ticket is not None and ttl_seconds is not None:
                if ticket.is_expired(ttl_seconds):
                    self._tickets.pop(ticket_hex, None)
                    return None
            return ticket

    def get_session_key(self, ticket_hex: str) -> Optional[bytes]:
        """Resolve a chave de sessão HMAC associada ao ticket de forma thread-safe."""
        with self._lock:
            ticket = self._tickets.get(ticket_hex)
            return ticket.session_key if ticket else None

    def remove_ticket(self, ticket_hex: str) -> None:
        """Revoga e remove o ticket de forma thread-safe."""
        with self._lock:
            self._tickets.pop(ticket_hex, None)

    def cleanup_expired_tickets(self, ttl_seconds: float = 300.0) -> int:
        """Remove todos os tickets que excederam o TTL especificado."""
        with self._lock:
            expired_keys = [
                k for k, t in self._tickets.items() if t.is_expired(ttl_seconds)
            ]
            for key in expired_keys:
                self._tickets.pop(key, None)
            return len(expired_keys)


def compute_file_sha256(file_path: Path) -> str:
    """Calcula o SHA-256 de um arquivo em disco lendo em streaming de blocos de 64 KB."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            block = f.read(CHUNK_SIZE)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def log_message(
    arg1: Union[Path, str],
    arg2: Union[Tuple[str, int], str] = ("127.0.0.1", 0),
    arg3: Union[str, Path] = "",
    username: Optional[str] = None,
    client_address: Optional[Tuple[str, int]] = None,
) -> None:
    """Registra uma mensagem no log com compatibilidade para múltiplas convenções de chamada."""
    if isinstance(arg1, (Path, str)) and isinstance(arg2, tuple):
        log_file = Path(arg1)
        addr = arg2
        msg = str(arg3)
        user = username
    else:
        user = str(arg1)
        msg = str(arg2)
        dir_or_file = Path(arg3) if arg3 else Path("app/logs")
        log_file = dir_or_file if dir_or_file.suffix else dir_or_file / "server.log"
        addr = client_address or ("127.0.0.1", 0)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client_ip, client_port = addr
    sender = f"{user}@" if user else ""
    log_entry = f"[{timestamp}] [{sender}{client_ip}:{client_port}] {msg.strip()}\n"

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(log_entry)
