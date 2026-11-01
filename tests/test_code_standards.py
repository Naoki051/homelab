"""Testes Unitários para a Fundação de Padrões de Código e Exceções do Homelab.

Valida a hierarquia de exceções de domínio, formatação de contexto e os utilitários
de mascaramento e sanitização de dados sensíveis.
"""

from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.exceptions import (  # noqa: E402
    AuthenticationError,
    HMACVerificationError,
    HomelabError,
    NetworkTimeoutError,
    ProtocolError,
    SessionExpiredError,
    StorageError,
    mask_password,
    mask_secret,
)


class TestHomelabExceptionsHierarchy(unittest.TestCase):
    """Garante a integridade da árvore de herança e enriquecimento contextual."""

    def test_base_homelab_error_without_context(self) -> None:
        err = HomelabError("Erro genérico de teste")
        self.assertIsInstance(err, Exception)
        self.assertEqual(str(err), "Erro genérico de teste")
        self.assertEqual(err.context, {})

    def test_base_homelab_error_with_context(self) -> None:
        err = HomelabError(
            "Conexão falhou",
            context={"ip": "192.168.0.246", "port": 9000, "status": "timeout"},
        )
        msg = str(err)
        self.assertIn("Conexão falhou", msg)
        self.assertIn("ip=192.168.0.246", msg)
        self.assertIn("port=9000", msg)
        self.assertIn("status=timeout", msg)

    def test_protocol_and_hmac_errors(self) -> None:
        proto_err = ProtocolError("Magic byte inválido")
        self.assertIsInstance(proto_err, HomelabError)

        hmac_err = HMACVerificationError("Assinatura HMAC violada")
        self.assertIsInstance(hmac_err, ProtocolError)
        self.assertIsInstance(hmac_err, HomelabError)

    def test_authentication_and_session_errors(self) -> None:
        auth_err = AuthenticationError("Credenciais inválidas")
        self.assertIsInstance(auth_err, HomelabError)

        session_err = SessionExpiredError("Sessão expirada")
        self.assertIsInstance(session_err, AuthenticationError)
        self.assertIsInstance(session_err, HomelabError)

    def test_storage_and_network_errors(self) -> None:
        storage_err = StorageError("Disco cheio ou banco travado")
        self.assertIsInstance(storage_err, HomelabError)

        net_err = NetworkTimeoutError("Socket timeout após 10s")
        self.assertIsInstance(net_err, HomelabError)


class TestSecretMaskingSanitization(unittest.TestCase):
    """Valida que nenhum dado confidencial vaze em texto plano."""

    def test_mask_secret_empty_and_none(self) -> None:
        self.assertEqual(mask_secret(None), "[VAZIO]")
        self.assertEqual(mask_secret(""), "[VAZIO]")

    def test_mask_secret_short_values(self) -> None:
        self.assertEqual(mask_secret("123"), "***")
        self.assertEqual(mask_secret("segredo"), "***")

    def test_mask_secret_long_hmac_and_tokens(self) -> None:
        token = "1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p"
        masked = mask_secret(token, show_prefix=4, show_suffix=4)
        self.assertEqual(masked, "1a2b...5o6p")
        self.assertNotIn("3c4d5e6f", masked)

    def test_mask_password(self) -> None:
        self.assertEqual(mask_password(None), "[VAZIO]")
        self.assertEqual(mask_password(""), "[VAZIO]")
        self.assertEqual(mask_password("MinhaSenhaUltraSecreta123!"), "***")


if __name__ == "__main__":
    unittest.main()
