#!/usr/bin/env python3
"""
Módulo de Sessão Local do Cliente (NoSQL / JSON) para Homelab
Define a classe Session para gerenciar o estado local e o recurso de Quick Login
com expiração configurável (padrão de 7 dias) e permissões de arquivo restritas.
"""

from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
from typing import Optional


class Session:
    """Gerencia a persistência de credenciais locais para o recurso de Quick Login."""

    DEFAULT_TTL_DAYS = 7
    DEFAULT_SESSION_FILE = Path(__file__).resolve().parent / "data" / "client_session.json"

    def __init__(
        self,
        last_username: str,
        last_password: str,
        expire_date_time: str,
    ):
        self.last_username = last_username
        self.last_password = last_password
        self.expire_date_time = expire_date_time

    @staticmethod
    def derive_secret(username: str, raw_password: str) -> str:
        """Gera um hash SHA-256 local da senha para nunca salvar texto puro em disco."""
        salted = f"{username.strip().lower()}:{raw_password}"
        return hashlib.sha256(salted.encode("utf-8")).hexdigest()

    def is_valid(self) -> bool:
        """Verifica se a sessão ainda não expirou em relação ao horário atual."""
        try:
            expires_at = datetime.fromisoformat(self.expire_date_time)
            return datetime.now() < expires_at
        except (ValueError, TypeError):
            return False

    def time_remaining(self) -> str:
        """Retorna uma string legível com o tempo restante de validade da sessão."""
        try:
            expires_at = datetime.fromisoformat(self.expire_date_time)
            remaining = expires_at - datetime.now()
            if remaining.total_seconds() <= 0:
                return "expirada"
            days = remaining.days
            hours = remaining.seconds // 3600
            if days > 0:
                return f"{days}d {hours}h restantes"
            minutes = (remaining.seconds % 3600) // 60
            return f"{hours}h {minutes}m restantes"
        except Exception:
            return "desconhecido"

    def to_dict(self) -> dict:
        """Serializa os dados da sessão no dicionário exigido."""
        return {
            "last_username": self.last_username,
            "last_password": self.last_password,
            "expire_date_time": self.expire_date_time,
        }

    @classmethod
    def create(
        cls,
        username: str,
        password_value: str,
        is_already_derived: bool = False,
        days: int = DEFAULT_TTL_DAYS,
    ) -> "Session":
        """Cria uma nova instância de sessão calculando expiração para N dias."""
        secret = (
            password_value
            if is_already_derived
            else cls.derive_secret(username, password_value)
        )
        expire_time = (datetime.now() + timedelta(days=days)).isoformat()
        return cls(
            last_username=username.strip(),
            last_password=secret,
            expire_date_time=expire_time,
        )

    def save(self, path: Optional[Path] = None) -> None:
        """Salva a sessão em arquivo JSON aplicando permissão restrita (chmod 600)."""
        target_path = path or self.DEFAULT_SESSION_FILE
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

        try:
            os.chmod(target_path, 0o600)
        except OSError:
            pass  # Ignorar se o sistema de arquivos não suportar chmod POSIX

    @classmethod
    def load(cls, path: Optional[Path] = None) -> Optional["Session"]:
        """Carrega a sessão do arquivo NoSQL JSON se existir e for válida."""
        target_path = path or cls.DEFAULT_SESSION_FILE
        if not target_path.exists():
            return None

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            session = cls(
                last_username=data.get("last_username", ""),
                last_password=data.get("last_password", ""),
                expire_date_time=data.get("expire_date_time", ""),
            )
            return session
        except Exception:
            return None

    @classmethod
    def clear(cls, path: Optional[Path] = None) -> None:
        """Remove o arquivo de sessão local."""
        target_path = path or cls.DEFAULT_SESSION_FILE
        if target_path.exists():
            try:
                target_path.unlink()
            except OSError:
                pass
