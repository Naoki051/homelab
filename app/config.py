#!/usr/bin/env python3
"""
Módulo Central de Gerenciamento de Configurações para Homelab
Suporta leitura de arquivos .env específicos (server.env, client.env, .env) via python-dotenv,
com fallback automático para variáveis de ambiente do sistema operacional (os.environ),
valores padrão seguros e arquitetura preparada para fail fast.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Any, Optional, Union

# Tenta carregar python-dotenv conforme declarado no requirements.txt
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False
    load_dotenv = None

# Raiz do repositório
REPO_ROOT = Path(__file__).resolve().parent.parent


class ConfigValidationError(ValueError):
    """Exceção levantada quando uma constante obrigatória está ausente sob fail_fast=True."""
    pass


def _resolve_env_file(
    explicit_path: Optional[Union[Path, str]],
    default_candidates: list[str],
) -> Optional[Path]:
    """
    Determina o arquivo de ambiente a ser carregado.
    Se explicit_path for fornecido, resolve e valida sua existência.
    Caso contrário, busca na raiz do projeto na ordem da lista de candidatos.
    """
    if explicit_path:
        p = Path(explicit_path)
        if not p.is_absolute():
            p = (REPO_ROOT / p).resolve()
        return p if p.is_file() else None

    for candidate in default_candidates:
        candidate_path = REPO_ROOT / candidate
        if candidate_path.is_file():
            return candidate_path

    return None


def _load_env_if_present(env_path: Optional[Path], override: bool = False) -> None:
    """Carrega o arquivo env usando python-dotenv se disponível e o arquivo existir."""
    if env_path and env_path.is_file():
        if HAS_DOTENV and load_dotenv:
            load_dotenv(dotenv_path=env_path, override=override)
        else:
            # Fallback nativo simples se python-dotenv não estiver instalado
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if override or key not in os.environ:
                            os.environ[key] = val
            except Exception:
                pass


def _get_str(key: str, default: str, fail_fast: bool = False, required: bool = False) -> str:
    val = os.environ.get(key)
    if val is None or val.strip() == "":
        if fail_fast and required:
            raise ConfigValidationError(f"Configuração obrigatória ausente ou vazia: '{key}'")
        return default
    return val.strip()


def _get_int(key: str, default: int, fail_fast: bool = False, required: bool = False) -> int:
    val = os.environ.get(key)
    if val is None or val.strip() == "":
        if fail_fast and required:
            raise ConfigValidationError(f"Configuração obrigatória ausente ou vazia: '{key}'")
        return default
    try:
        return int(val.strip())
    except ValueError as e:
        if fail_fast:
            raise ConfigValidationError(f"Configuração '{key}' deve ser um inteiro válido. Valor recebido: '{val}'") from e
        return default


def _get_float(key: str, default: float, fail_fast: bool = False, required: bool = False) -> float:
    val = os.environ.get(key)
    if val is None or val.strip() == "":
        if fail_fast and required:
            raise ConfigValidationError(f"Configuração obrigatória ausente ou vazia: '{key}'")
        return default
    try:
        return float(val.strip())
    except ValueError as e:
        if fail_fast:
            raise ConfigValidationError(f"Configuração '{key}' deve ser um número decimal válido. Valor recebido: '{val}'") from e
        return default


def _get_path(
    key: str,
    default: Path,
    fail_fast: bool = False,
    required: bool = False,
    base_dir: Path = REPO_ROOT,
) -> Path:
    val = os.environ.get(key)
    if val is None or val.strip() == "":
        if fail_fast and required:
            raise ConfigValidationError(f"Configuração de caminho obrigatória ausente: '{key}'")
        return default
    p = Path(val.strip())
    if not p.is_absolute():
        p = (base_dir / p).resolve()
    return p


def _get_bytes(key: str, default: bytes, fail_fast: bool = False, required: bool = False) -> bytes:
    val = os.environ.get(key)
    if val is None or val.strip() == "":
        if fail_fast and required:
            raise ConfigValidationError(f"Configuração de chave/bytes obrigatória ausente: '{key}'")
        return default
    return val.strip().encode("utf-8")


@dataclass
class ServerConfig:
    """Configurações operacionais do Servidor TCP Dual-Channel."""
    host: str
    control_port: int
    data_port: int
    handshake_key: bytes
    chunk_size: int
    buffer_size: int
    db_path: Path
    log_path: Path
    uploads_dir: Path
    source_file: Optional[Path] = None

    def validate(self, fail_fast: bool = False) -> None:
        """Hook extensível para validação ou aplicação de fail fast."""
        if fail_fast:
            if not self.host:
                raise ConfigValidationError("ServerConfig: host não pode ser vazio.")
            if not (1 <= self.control_port <= 65535):
                raise ConfigValidationError(f"ServerConfig: control_port inválida ({self.control_port}).")
            if not (1 <= self.data_port <= 65535):
                raise ConfigValidationError(f"ServerConfig: data_port inválida ({self.data_port}).")
            if not self.handshake_key:
                raise ConfigValidationError("ServerConfig: handshake_key não pode ser vazia.")


@dataclass
class ClientConfig:
    """Configurações operacionais do Cliente TCP Dual-Protocol."""
    host: str
    control_port: int
    data_port: int
    handshake_key: bytes
    chunk_size: int
    timeout: float
    buffer_size: int
    session_path: Path
    source_file: Optional[Path] = None

    def validate(self, fail_fast: bool = False) -> None:
        """Hook extensível para validação ou aplicação de fail fast."""
        if fail_fast:
            if not self.host:
                raise ConfigValidationError("ClientConfig: host não pode ser vazio.")
            if not (1 <= self.control_port <= 65535):
                raise ConfigValidationError(f"ClientConfig: control_port inválida ({self.control_port}).")
            if not (1 <= self.data_port <= 65535):
                raise ConfigValidationError(f"ClientConfig: data_port inválida ({self.data_port}).")
            if not self.handshake_key:
                raise ConfigValidationError("ClientConfig: handshake_key não pode ser vazia.")


def load_server_config(
    env_file: Optional[Union[Path, str]] = None,
    fail_fast: bool = False,
    override: bool = False,
) -> ServerConfig:
    """
    Carrega as configurações do Servidor.
    Busca na seguinte ordem de precedência:
      1. Arquivo explícito (env_file)
      2. envs/server.env (ou server.env)
      3. envs/.env (ou .env)
      4. Variáveis de ambiente do SO (os.environ)
      5. Valores padrão seguros em código
    """
    resolved_env = _resolve_env_file(env_file, ["envs/server.env", "envs/.env", "server.env", ".env"])
    _load_env_if_present(resolved_env, override=override)

    # Defaults padrão da aplicação
    default_db_path = REPO_ROOT / "app" / "data" / "homelab.db"
    default_log_path = REPO_ROOT / "app" / "logs" / "server_messages.log"
    default_uploads_dir = REPO_ROOT / "app" / "data" / "uploads"
    default_handshake_key = b"homelab-initial-handshake-key-32"

    config = ServerConfig(
        host=_get_str("HOMELAB_SERVER_HOST", "0.0.0.0", fail_fast=fail_fast),
        control_port=_get_int("HOMELAB_CONTROL_PORT", 9000, fail_fast=fail_fast),
        data_port=_get_int("HOMELAB_DATA_PORT", 9001, fail_fast=fail_fast),
        handshake_key=_get_bytes("HOMELAB_HANDSHAKE_KEY", default_handshake_key, fail_fast=fail_fast),
        chunk_size=_get_int("HOMELAB_CHUNK_SIZE", 65536, fail_fast=fail_fast),
        buffer_size=_get_int("HOMELAB_BUFFER_SIZE", 4096, fail_fast=fail_fast),
        db_path=_get_path("HOMELAB_DB_PATH", default_db_path, fail_fast=fail_fast),
        log_path=_get_path("HOMELAB_LOG_PATH", default_log_path, fail_fast=fail_fast),
        uploads_dir=_get_path("HOMELAB_UPLOADS_DIR", default_uploads_dir, fail_fast=fail_fast),
        source_file=resolved_env,
    )
    config.validate(fail_fast=fail_fast)
    return config


def load_client_config(
    env_file: Optional[Union[Path, str]] = None,
    fail_fast: bool = False,
    override: bool = False,
) -> ClientConfig:
    """
    Carrega as configurações do Cliente.
    Busca na seguinte ordem de precedência:
      1. Arquivo explícito (env_file)
      2. envs/client.env (ou client.env)
      3. envs/.env (ou .env)
      4. Variáveis de ambiente do SO (os.environ)
      5. Valores padrão seguros em código
    """
    resolved_env = _resolve_env_file(env_file, ["envs/client.env", "envs/.env", "client.env", ".env"])
    _load_env_if_present(resolved_env, override=override)

    # Fallback de host: se HOMELAB_CLIENT_TARGET_HOST não estiver definido, verifica HOMELAB_SERVER_HOST
    target_host_default = os.environ.get("HOMELAB_SERVER_HOST", "192.168.0.246")

    default_session_path = REPO_ROOT / "app" / "data" / "client_session.json"
    default_handshake_key = b"homelab-initial-handshake-key-32"

    config = ClientConfig(
        host=_get_str("HOMELAB_CLIENT_TARGET_HOST", target_host_default, fail_fast=fail_fast),
        control_port=_get_int("HOMELAB_CONTROL_PORT", 9000, fail_fast=fail_fast),
        data_port=_get_int("HOMELAB_DATA_PORT", 9001, fail_fast=fail_fast),
        handshake_key=_get_bytes("HOMELAB_HANDSHAKE_KEY", default_handshake_key, fail_fast=fail_fast),
        chunk_size=_get_int("HOMELAB_CHUNK_SIZE", 65536, fail_fast=fail_fast),
        timeout=_get_float("HOMELAB_CLIENT_TIMEOUT", 10.0, fail_fast=fail_fast),
        buffer_size=_get_int("HOMELAB_CLIENT_BUFFER_SIZE", 4096, fail_fast=fail_fast),
        session_path=_get_path("HOMELAB_SESSION_PATH", default_session_path, fail_fast=fail_fast),
        source_file=resolved_env,
    )
    config.validate(fail_fast=fail_fast)
    return config
