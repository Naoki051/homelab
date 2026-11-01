"""Módulo de Exceções de Domínio e Sanitização Segura do Homelab.

Este módulo centraliza a hierarquia oficial de exceções do projeto Homelab,
eliminando a necessidade de capturas e lançamentos genéricos de `Exception`,
além de fornecer utilitários para mascaramento de credenciais e dados sensíveis.
"""

from typing import Any, Dict, List, Optional, Union

__all__: List[str] = [
    "HomelabError",
    "ProtocolError",
    "HMACVerificationError",
    "AuthenticationError",
    "SessionExpiredError",
    "StorageError",
    "NetworkTimeoutError",
    "mask_secret",
    "mask_password",
]


class HomelabError(Exception):
    """Exceção base para todas as falhas de domínio do ecossistema Homelab."""

    message: str
    context: Dict[str, Any]

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def __str__(self) -> str:
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in sorted(self.context.items()))
            return f"{self.message} [{context_str}]"
        return self.message


class ProtocolError(HomelabError, ValueError):
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
    secret: Optional[Union[str, bytes]] = None,
    show_prefix: int = 4,
    show_suffix: int = 4,
) -> str:
    """Mascara chaves, tokens e hashes longos preservando apenas prefixo e sufixo.

    Substitui o segmento intermediário de identificadores e chaves sensíveis por
    reticências, garantindo proteção estrita contra vazamento em logs ou saídas
    de terminal, ou por '***' caso o comprimento seja insuficiente.

    Args:
        secret: Chave, token ou hash confidencial (aceita str, bytes ou None).
        show_prefix: Quantidade de caracteres visíveis no início (padrão: 4).
        show_suffix: Quantidade de caracteres visíveis no final (padrão: 4).

    Returns:
        str: Valor sanitizado seguro contra vazamento em logs.
    """
    if secret is None or len(secret) == 0:
        return "[VAZIO]"

    raw_secret: str = secret.hex() if isinstance(secret, (bytes, bytearray)) else str(secret)
    total_len = len(raw_secret)
    if total_len <= (show_prefix + show_suffix + 2):
        return "***"

    return f"{raw_secret[:show_prefix]}...{raw_secret[-show_suffix:]}"


def mask_password(password: Optional[str]) -> str:
    """Mascara terminantemente qualquer senha para impedir vazamento em logs.

    Args:
        password: Senha em texto puro a ser mascarada (ou None).

    Returns:
        str: '[VAZIO]' se None ou vazia, ou '***' se preenchida.
    """
    if not password:
        return "[VAZIO]"
    return "***"
