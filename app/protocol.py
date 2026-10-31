#!/usr/bin/env python3
"""
Módulo de Protocolo de Rede para Homelab (Arquitetura Dual-Protocol)
1. Canal de Controle (Porta 9000): Classe Message com Length-Prefixed Framing (40B header) e HMAC-SHA256.
2. Canal de Dados/Mídia (Porta 9001): Classe MediaChunk com Chunks Indexados de 64KB (62B header) e HMAC-SHA256.
"""

from datetime import datetime
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import socket
import struct
from typing import Any, Callable, Dict, Iterator, Optional, Union

# Constantes de Enquadramento Binário e Criptografia HMAC
CONTROL_MAGIC = b"HC"
DATA_MAGIC = b"HD"

# Chave inicial usada apenas no handshake pré-autenticação (login / register)
DEFAULT_HANDSHAKE_KEY = b"homelab-initial-handshake-key-32"

# Limite de 64 KB por chunk de mídia ou quadro de controle
CHUNK_SIZE = 65536
MAX_CONTROL_PAYLOAD = 65536

# Cabeçalho de Controle: Magic(2s) + MsgType(H:2B) + PayloadLen(I:4B) + HMAC(32s) = 40 bytes
CONTROL_HEADER_FORMAT = ">2sHI32s"
CONTROL_HEADER_SIZE = struct.calcsize(CONTROL_HEADER_FORMAT)

# Cabeçalho de Chunk: Magic(2s) + Ticket(16s) + ChunkIdx(I:4B) + TotalChunks(I:4B) + DataLen(I:4B) + HMAC(32s) = 62 bytes
CHUNK_HEADER_FORMAT = ">2s16sIII32s"
CHUNK_HEADER_SIZE = struct.calcsize(CHUNK_HEADER_FORMAT)


def generate_session_key() -> bytes:
    """Gera uma chave de sessão dinâmica criptograficamente segura de 32 bytes (256 bits)."""
    return os.urandom(32)


def generate_upload_ticket() -> bytes:
    """Gera um identificador único de ticket de upload de 16 bytes (128 bits)."""
    return os.urandom(16)


def normalize_hmac_key(key: Optional[Union[bytes, str]]) -> bytes:
    """Converte chaves de sessão (bytes, hex string ou None) para bytes."""
    if key is None:
        return DEFAULT_HANDSHAKE_KEY
    if isinstance(key, bytes):
        return key
    if isinstance(key, str):
        if len(key) == 64:
            try:
                return bytes.fromhex(key)
            except ValueError:
                pass
        return key.encode("utf-8")
    raise TypeError("Formato de chave HMAC inválido.")


def compute_hmac(key: Optional[Union[bytes, str]], data: bytes) -> bytes:
    """Calcula o HMAC-SHA256 (32 bytes) sobre os dados informados."""
    key_bytes = normalize_hmac_key(key)
    return hmac.new(key_bytes, data, hashlib.sha256).digest()


def verify_hmac(key: Optional[Union[bytes, str]], data: bytes, expected_mac: bytes) -> bool:
    """Verifica o HMAC-SHA256 em tempo constante para prevenir ataques de timing."""
    calculated = compute_hmac(key, data)
    return hmac.compare_digest(calculated, expected_mac)


def recv_exact(sock: socket.socket, num_bytes: int) -> Optional[bytes]:
    """
    Lê exatamente `num_bytes` de um socket TCP.
    Retorna None caso o socket seja fechado limpo antes do primeiro byte (EOF).
    Levanta ConnectionError se a conexão cair no meio da leitura de um bloco.
    """
    if num_bytes == 0:
        return b""
    chunks = bytearray()
    while len(chunks) < num_bytes:
        packet = sock.recv(num_bytes - len(chunks))
        if not packet:
            if len(chunks) == 0:
                return None
            raise ConnectionError(
                f"Conexão TCP encerrada prematuramente ({len(chunks)}/{num_bytes} bytes lidos)."
            )
        chunks.extend(packet)
    return bytes(chunks)


class Message:
    """Representa uma mensagem no protocolo de controle da aplicação."""

    ACTION_REGISTER = "register"
    ACTION_LOGIN = "login"
    ACTION_SEND = "send"
    ACTION_REQUEST_UPLOAD = "request_upload"
    ACTION_LOGOUT = "logout"
    ACTION_RESPONSE = "response"

    STATUS_OK = "ok"
    STATUS_ERROR = "error"

    MSG_TYPE_REQUEST = 1
    MSG_TYPE_RESPONSE = 2

    def __init__(
        self,
        action: str,
        payload: Dict[str, Any],
        timestamp: Optional[str] = None,
    ):
        self.action = action
        self.payload = payload
        self.timestamp = timestamp or datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Converte a mensagem em um dicionário serializável."""
        return {
            "action": self.action,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        """Serializa a mensagem em uma string JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def to_bytes(self, encoding: str = "utf-8") -> bytes:
        """Serializa a mensagem em bytes codificados para transmissão via socket."""
        return self.to_json().encode(encoding)

    def to_frame(
        self,
        hmac_key: Optional[Union[bytes, str]] = None,
        msg_type: Optional[int] = None,
    ) -> bytes:
        """
        Empacota a mensagem em um quadro binário com Length-Prefixed Framing (40B header) e HMAC-SHA256.
        Layout: Magic(2B) | MsgType(2B) | PayloadLen(4B) | HMAC-SHA256(32B) | Payload JSON
        """
        payload_bytes = self.to_bytes()
        payload_len = len(payload_bytes)
        if payload_len > MAX_CONTROL_PAYLOAD:
            raise ValueError(
                f"Payload de controle excede o limite de {MAX_CONTROL_PAYLOAD} bytes: {payload_len}"
            )

        if msg_type is None:
            msg_type = (
                self.MSG_TYPE_RESPONSE
                if self.action == self.ACTION_RESPONSE
                else self.MSG_TYPE_REQUEST
            )

        meta_prefix = struct.pack(">2sHI", CONTROL_MAGIC, msg_type, payload_len)
        mac = compute_hmac(hmac_key, meta_prefix + payload_bytes)
        header = struct.pack(CONTROL_HEADER_FORMAT, CONTROL_MAGIC, msg_type, payload_len, mac)
        return header + payload_bytes

    @classmethod
    def from_frame(
        cls,
        frame_bytes: bytes,
        hmac_key: Optional[Union[bytes, str]] = None,
    ) -> "Message":
        """Desempacota e valida o HMAC de um quadro binário completo em memória."""
        if len(frame_bytes) < CONTROL_HEADER_SIZE:
            raise ValueError("Frame de controle menor que o cabeçalho mínimo de 40 bytes.")

        header = frame_bytes[:CONTROL_HEADER_SIZE]
        payload_bytes = frame_bytes[CONTROL_HEADER_SIZE:]
        magic, msg_type, payload_len, expected_mac = struct.unpack(CONTROL_HEADER_FORMAT, header)

        if magic != CONTROL_MAGIC:
            raise ValueError(f"Magic de controle inválido: {magic!r}")
        if len(payload_bytes) != payload_len:
            raise ValueError(
                f"Tamanho do payload ({len(payload_bytes)}) diverge do cabeçalho ({payload_len})."
            )

        meta_prefix = struct.pack(">2sHI", magic, msg_type, payload_len)
        if not verify_hmac(hmac_key, meta_prefix + payload_bytes, expected_mac):
            raise ValueError("Falha de integridade/autenticidade: assinatura HMAC inválida.")

        return cls.from_bytes(payload_bytes)

    def send_framed(
        self,
        sock: socket.socket,
        hmac_key: Optional[Union[bytes, str]] = None,
        msg_type: Optional[int] = None,
    ) -> None:
        """Envia a mensagem enquadrada com cabeçalho binário e HMAC através do socket."""
        frame = self.to_frame(hmac_key=hmac_key, msg_type=msg_type)
        sock.sendall(frame)

    @classmethod
    def recv_framed(
        cls,
        sock: socket.socket,
        hmac_key: Optional[Union[bytes, str]] = None,
        pre_read_prefix: bytes = b"",
    ) -> Optional["Message"]:
        """
        Lê um quadro de controle completo de um socket TCP, validando cabeçalho e HMAC.
        Retorna None caso o cliente encerre a conexão limpa (EOF).
        """
        needed_header = CONTROL_HEADER_SIZE - len(pre_read_prefix)
        rest_header = recv_exact(sock, needed_header)
        if rest_header is None:
            if not pre_read_prefix:
                return None
            raise ConnectionError("Conexão encerrada no meio do cabeçalho de controle.")

        header = pre_read_prefix + rest_header
        magic, msg_type, payload_len, expected_mac = struct.unpack(CONTROL_HEADER_FORMAT, header)

        if magic != CONTROL_MAGIC:
            raise ValueError(f"Magic de controle inválido recebido: {magic!r}")
        if payload_len > MAX_CONTROL_PAYLOAD:
            raise ValueError(f"PayloadLength excede o limite permitido: {payload_len}")

        payload_bytes = recv_exact(sock, payload_len)
        if payload_bytes is None:
            raise ConnectionError("Conexão encerrada antes de receber o payload de controle.")

        meta_prefix = struct.pack(">2sHI", magic, msg_type, payload_len)
        if not verify_hmac(hmac_key, meta_prefix + payload_bytes, expected_mac):
            raise ValueError("Falha de integridade/autenticidade: assinatura HMAC inválida.")

        return cls.from_bytes(payload_bytes)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Instancia um objeto Message a partir de um dicionário."""
        action = data.get("action", "")
        payload = data.get("payload", {})
        timestamp = data.get("timestamp")
        return cls(action=action, payload=payload, timestamp=timestamp)

    @classmethod
    def from_json(cls, data_str: str) -> "Message":
        """Desserializa uma string JSON em um objeto Message."""
        data = json.loads(data_str)
        return cls.from_dict(data)

    @classmethod
    def from_bytes(cls, data: bytes, encoding: str = "utf-8") -> "Message":
        """Desserializa bytes de socket em um objeto Message (suporta frame binário ou JSON puro)."""
        if len(data) >= CONTROL_HEADER_SIZE and data[:2] == CONTROL_MAGIC:
            return cls.from_frame(data)
        return cls.from_json(data.decode(encoding))

    @classmethod
    def response(
        cls,
        status: str,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> "Message":
        """Cria uma mensagem padronizada de resposta (ACK ou ERRO)."""
        payload: Dict[str, Any] = {"status": status, "message": message}
        if extra:
            for k, v in extra.items():
                if k not in ("status", "message"):
                    payload[k] = v
                else:
                    payload[f"client_{k}"] = v
        return cls(action=cls.ACTION_RESPONSE, payload=payload)


class MediaChunk:
    """
    Representa um bloco binário indexado (até 64 KB) do Protocolo de Dados/Mídia (Porta 9001).
    Cabeçalho fixo de 62 bytes:
    Magic(2B: b'HD') | Ticket(16B) | ChunkIndex(4B) | TotalChunks(4B) | DataLength(4B) | HMAC-SHA256(32B)
    """

    def __init__(
        self,
        ticket: Union[bytes, str],
        chunk_index: int,
        total_chunks: int,
        data: bytes,
    ):
        if isinstance(ticket, str):
            ticket_bytes = bytes.fromhex(ticket)
        else:
            ticket_bytes = bytes(ticket)

        if len(ticket_bytes) != 16:
            raise ValueError("O ticket de upload deve possuir exatamente 16 bytes (32 hex chars).")
        if len(data) > CHUNK_SIZE:
            raise ValueError(f"O tamanho do chunk ({len(data)}B) excede o limite de {CHUNK_SIZE}B.")
        if total_chunks < 1 or chunk_index < 0 or chunk_index >= total_chunks:
            raise ValueError(
                f"Índice de chunk inválido: chunk_index={chunk_index}, total_chunks={total_chunks}."
            )

        self.ticket: bytes = ticket_bytes
        self.chunk_index: int = chunk_index
        self.total_chunks: int = total_chunks
        self.data: bytes = data

    @property
    def ticket_hex(self) -> str:
        """Retorna o identificador do ticket em formato hexadecimal (32 caracteres)."""
        return self.ticket.hex()

    @property
    def data_length(self) -> int:
        """Retorna o tamanho em bytes do conteúdo deste chunk."""
        return len(self.data)

    def _metadata_prefix(self) -> bytes:
        return struct.pack(
            ">2s16sIII",
            DATA_MAGIC,
            self.ticket,
            self.chunk_index,
            self.total_chunks,
            len(self.data),
        )

    def compute_mac(self, hmac_key: Union[bytes, str, None]) -> bytes:
        """Calcula o HMAC-SHA256 cobrindo os metadados do cabeçalho e os bytes brutos do chunk."""
        return compute_hmac(hmac_key, self._metadata_prefix() + self.data)

    def to_bytes(self, hmac_key: Union[bytes, str, None]) -> bytes:
        """Empacota o cabeçalho de 62 bytes com HMAC-SHA256 seguido dos dados brutos do chunk."""
        mac = self.compute_mac(hmac_key)
        header = struct.pack(
            CHUNK_HEADER_FORMAT,
            DATA_MAGIC,
            self.ticket,
            self.chunk_index,
            self.total_chunks,
            len(self.data),
            mac,
        )
        return header + self.data

    def send(self, sock: socket.socket, hmac_key: Union[bytes, str, None]) -> None:
        """Transmite o chunk assinado pelo socket TCP."""
        sock.sendall(self.to_bytes(hmac_key))

    @classmethod
    def from_bytes(cls, raw_bytes: bytes, hmac_key: Union[bytes, str, None]) -> "MediaChunk":
        """Desempacota e valida um chunk completo em memória."""
        if len(raw_bytes) < CHUNK_HEADER_SIZE:
            raise ValueError("Pacote menor que o cabeçalho de chunk de 62 bytes.")

        header = raw_bytes[:CHUNK_HEADER_SIZE]
        data = raw_bytes[CHUNK_HEADER_SIZE:]
        magic, ticket, chunk_idx, total_chunks, data_len, expected_mac = struct.unpack(
            CHUNK_HEADER_FORMAT, header
        )

        if magic != DATA_MAGIC:
            raise ValueError(f"Magic de dados inválido: {magic!r}")
        if len(data) != data_len:
            raise ValueError(f"Tamanho dos dados ({len(data)}) diverge do cabeçalho ({data_len}).")

        meta_prefix = struct.pack(">2s16sIII", magic, ticket, chunk_idx, total_chunks, data_len)
        if not verify_hmac(hmac_key, meta_prefix + data, expected_mac):
            raise ValueError(f"Assinatura HMAC inválida para o chunk {chunk_idx}.")

        return cls(ticket=ticket, chunk_index=chunk_idx, total_chunks=total_chunks, data=data)

    @classmethod
    def recv_from_socket(
        cls,
        sock: socket.socket,
        key_resolver: Union[bytes, str, None, Callable[[str], Optional[bytes]]],
    ) -> Optional["MediaChunk"]:
        """
        Lê um único MediaChunk do socket TCP (62B de cabeçalho + DataLength bytes) e valida o HMAC.
        `key_resolver` pode ser a chave diretamente ou uma função `fn(ticket_hex) -> session_key`.
        """
        header = recv_exact(sock, CHUNK_HEADER_SIZE)
        if header is None:
            return None

        magic, ticket, chunk_idx, total_chunks, data_len, expected_mac = struct.unpack(
            CHUNK_HEADER_FORMAT, header
        )

        if magic != DATA_MAGIC:
            raise ValueError(f"Magic de dados inválido no canal de mídia: {magic!r}")
        if data_len > CHUNK_SIZE:
            raise ValueError(f"Chunk excede o tamanho máximo de {CHUNK_SIZE} bytes: {data_len}")

        data = recv_exact(sock, data_len)
        if data is None:
            raise ConnectionError(f"Conexão encerrada durante leitura dos dados do chunk {chunk_idx}.")

        ticket_hex = ticket.hex()
        if callable(key_resolver):
            hmac_key = key_resolver(ticket_hex)
            if hmac_key is None:
                raise ValueError(f"Ticket de upload desconhecido ou expirado: {ticket_hex}")
        else:
            hmac_key = key_resolver

        meta_prefix = struct.pack(">2s16sIII", magic, ticket, chunk_idx, total_chunks, data_len)
        if not verify_hmac(hmac_key, meta_prefix + data, expected_mac):
            raise ValueError(f"Falha de integridade: HMAC inválido no chunk {chunk_idx}.")

        return cls(ticket=ticket, chunk_index=chunk_idx, total_chunks=total_chunks, data=data)

    @classmethod
    def slice_file(
        cls,
        file_path: Path,
        ticket: Union[bytes, str],
        chunk_size: int = CHUNK_SIZE,
    ) -> Iterator["MediaChunk"]:
        """
        Gerador que lê um arquivo do disco em blocos de até 64 KB sob demanda,
        sem carregar o arquivo inteiro na memória RAM.
        """
        file_size = file_path.stat().st_size
        if file_size == 0:
            yield cls(ticket=ticket, chunk_index=0, total_chunks=1, data=b"")
            return

        total_chunks = math.ceil(file_size / chunk_size)
        with open(file_path, "rb") as f:
            for idx in range(total_chunks):
                block = f.read(chunk_size)
                yield cls(
                    ticket=ticket,
                    chunk_index=idx,
                    total_chunks=total_chunks,
                    data=block,
                )
