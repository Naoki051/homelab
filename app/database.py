#!/usr/bin/env python3
"""
Módulo de Banco de Dados do Servidor Homelab
Define o modelo Client e a classe ClientRepository para persistência em SQLite,
estruturado com SQL padrão compatível com futura migração para PostgreSQL.
"""

from datetime import datetime
import hashlib
import hmac
from pathlib import Path
import secrets
import sqlite3
from typing import Optional, Tuple


def hash_password(secret: str) -> str:
    """Gera um hash PBKDF2-HMAC-SHA256 seguro com salt aleatório."""
    salt = secrets.token_hex(16)
    iterations = 100_000
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return f"{salt}${iterations}${derived}"


def verify_password(secret: str, stored_hash: str) -> bool:
    """Verifica se o secret fornecido confere com o hash armazenado."""
    try:
        salt, iterations_str, expected_derived = stored_hash.split("$")
        iterations = int(iterations_str)
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            secret.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        return hmac.compare_digest(derived, expected_derived)
    except (ValueError, AttributeError):
        return False


class Client:
    """Entidade que representa um cliente/usuário registrado no sistema."""

    def __init__(
        self,
        id: Optional[int],
        username: str,
        password_hash: str,
        status: str = "offline",
        last_seen: Optional[str] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
    ):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.status = status
        self.last_seen = last_seen
        self.created_at = created_at
        self.updated_at = updated_at

    def to_dict(self) -> dict:
        """Retorna os dados públicos do cliente (sem expor hash de senha)."""
        return {
            "id": self.id,
            "username": self.username,
            "status": self.status,
            "last_seen": self.last_seen,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ClientRepository:
    """Gerencia a persistência da tabela clients no banco de dados."""

    DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "homelab.db"

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or self.DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """Cria a tabela clients se não existir."""
        query = """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'offline',
            last_seen TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
        with self._get_connection() as conn:
            conn.execute(query)
            conn.commit()

    def get_by_username(self, username: str) -> Optional[Client]:
        """Recupera um cliente pelo username."""
        query = "SELECT * FROM clients WHERE username = ? LIMIT 1;"
        with self._get_connection() as conn:
            cursor = conn.execute(query, (username,))
            row = cursor.fetchone()
            if not row:
                return None
            return Client(
                id=row["id"],
                username=row["username"],
                password_hash=row["password"],
                status=row["status"],
                last_seen=row["last_seen"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def register(self, username: str, secret: str) -> Tuple[bool, str, Optional[Client]]:
        """
        Cadastra um novo usuário obrigatoriamente.
        Retorna (sucesso, mensagem, client).
        """
        username = username.strip()
        if not username or len(username) < 3:
            return False, "Nome de usuário deve ter pelo menos 3 caracteres.", None

        if not secret:
            return False, "Senha não pode ser vazia.", None

        if self.get_by_username(username):
            return False, f"Usuário '{username}' já existe no sistema.", None

        now = datetime.now().isoformat()
        pwd_hash = hash_password(secret)

        insert_query = """
        INSERT INTO clients (username, password, status, last_seen, created_at, updated_at)
        VALUES (?, ?, 'offline', NULL, ?, ?);
        """
        with self._get_connection() as conn:
            cursor = conn.execute(insert_query, (username, pwd_hash, now, now))
            conn.commit()
            client_id = cursor.lastrowid

        client = Client(
            id=client_id,
            username=username,
            password_hash=pwd_hash,
            status="offline",
            last_seen=None,
            created_at=now,
            updated_at=now,
        )
        return True, "Usuário cadastrado com sucesso.", client

    def authenticate(self, username: str, secret: str) -> Tuple[bool, str, Optional[Client]]:
        """
        Autentica o cliente.
        Falha se o usuário não existir (não cria conta automaticamente) ou senha incorreta.
        """
        username = username.strip()
        client = self.get_by_username(username)
        if not client:
            return False, f"Usuário '{username}' não encontrado. Crie uma conta antes de entrar.", None

        if not verify_password(secret, client.password_hash):
            return False, "Senha incorreta.", None

        return True, "Autenticação realizada com sucesso.", client

    def update_status(self, username: str, status: str) -> None:
        """Atualiza o status (online/offline) e last_seen do cliente."""
        now = datetime.now().isoformat()
        query = """
        UPDATE clients
        SET status = ?, last_seen = ?, updated_at = ?
        WHERE username = ?;
        """
        with self._get_connection() as conn:
            conn.execute(query, (status, now, now, username))
            conn.commit()
