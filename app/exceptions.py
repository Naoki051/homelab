"""Módulo de Exceções de Domínio e Sanitização Segura do Homelab.

Este módulo centraliza a hierarquia oficial de exceções do projeto Homelab,
eliminando a necessidade de capturas e lançamentos genéricos de `Exception`,
além de fornecer utilitários para mascaramento de credenciais e dados sensíveis.
"""

from typing import Any, Dict, Optional


class HomelabError(Exception):
    """Exceção base para todas as falhas de domínio do ecossistema Homelab."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def __str__(self) -> str:
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in sorted(self.context.items()))
            return f"{self.message} [{context_str}]"
        return self.message


class ProtocolError(HomelabError):
    """Violação de protocolo, framing binário corrompido ou magic byte inválido."""

    pass


class HMACVerificationError(ProtocolError):
    """Falha de integridade criptográfica ou adulteração de assinatura HMAC-SHA256."""

    pass


class AuthenticationError(HomelabError):
    """Falha em credenciais de usuário, cadastro ou validação de senha."""

    pass


class SessionExpiredError(AuthenticationError):
    """Sessão de cliente expirada ou chave de autenticação revogada."""

    pass


class StorageError(HomelabError):
    """Erro em operações de persistência SQLite ou escrita de arquivos no disco."""

    pass


class NetworkTimeoutError(HomelabError):
    """Timeout em handshakes ou operações de I/O em sockets TCP."""

    pass


def mask_secret(
    secret: Optional[str],
    show_prefix: int = 4,
    show_suffix: int = 4,
) -> str:
    """Mascara chaves, tokens e hashes longos preservando apenas prefixo e sufixo.

    Exemplos:
        mask_secret("1a2b3c4d5e6f7g8h9i0j") -> "1a2b...9i0j"
        mask_secret("curto") -> "***"
        mask_secret(None) -> "[VAZIO]"
    """
    if secret is None or len(secret) == 0:
        return "[VAZIO]"

    total_len = len(secret)
    if total_len <= (show_prefix + show_suffix + 2):
        return "***"

    return f"{secret[:show_prefix]}...{secret[-show_suffix:]}"


def mask_password(password: Optional[str]) -> str:
    """Mascara terminantemente qualquer senha para impedir vazamento em logs."""
    if not password:
        return "[VAZIO]"
    return "***"
