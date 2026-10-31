#!/usr/bin/env python3
"""
Módulo de Protocolo de Rede para Homelab
Define a classe Message para estruturar a comunicação serializada em JSON entre cliente e servidor TCP.
"""

from datetime import datetime
import json
from typing import Any, Dict, Optional


class Message:
    """Representa uma mensagem no protocolo de aplicação."""

    ACTION_REGISTER = "register"
    ACTION_LOGIN = "login"
    ACTION_SEND = "send"
    ACTION_RESPONSE = "response"

    STATUS_OK = "ok"
    STATUS_ERROR = "error"

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
        """Desserializa bytes de socket em um objeto Message."""
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
