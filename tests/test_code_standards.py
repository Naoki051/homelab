"""Testes Unitários para a Fundação de Padrões de Código e Exceções do Homelab.

Valida a hierarquia de exceções de domínio, formatação de contexto e os utilitários
de mascaramento e sanitização de dados sensíveis.
"""

import io
import logging
from pathlib import Path
import re
import sys
import tempfile
from typing import List
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
from app.logger import (  # noqa: E402
    HOMELAB_DATE_FORMAT,
    HOMELAB_LOG_FORMAT,
    get_logger,
    setup_logging,
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

    def test_protocol_error_inherits_value_error(self) -> None:
        """Valida que ProtocolError e subclasses herdam de ValueError para retrocompatibilidade."""
        self.assertTrue(issubclass(ProtocolError, ValueError))
        self.assertTrue(issubclass(ProtocolError, HomelabError))
        self.assertTrue(issubclass(HMACVerificationError, ValueError))

        proto_err = ProtocolError("Payload truncado")
        self.assertIsInstance(proto_err, ValueError)
        self.assertIsInstance(proto_err, HomelabError)

        with self.assertRaises(ValueError):
            raise ProtocolError("Falha de framing capturada como ValueError")

        with self.assertRaises(ValueError):
            raise HMACVerificationError("HMAC inválido capturado como ValueError")

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

    def test_mask_secret_bytes_input(self) -> None:
        secret_bytes = b"abcdef1234567890abcdef"
        masked = mask_secret(secret_bytes, show_prefix=4, show_suffix=4)
        self.assertTrue(masked.startswith("6162"))
        self.assertTrue(masked.endswith("6566"))
        self.assertIn("...", masked)
        self.assertNotIn("1234567890", masked)

    def test_mask_secret_exact_boundary(self) -> None:
        # Com prefixo 4 e sufixo 4: limite = 4 + 4 + 2 = 10
        self.assertEqual(mask_secret("1234567890", show_prefix=4, show_suffix=4), "***")
        self.assertEqual(mask_secret("12345678901", show_prefix=4, show_suffix=4), "1234...8901")

    def test_mask_password(self) -> None:
        self.assertEqual(mask_password(None), "[VAZIO]")
        self.assertEqual(mask_password(""), "[VAZIO]")
        self.assertEqual(mask_password("MinhaSenhaUltraSecreta123!"), "***")


class TestHomelabStructuredLogging(unittest.TestCase):
    """Valida a inicialização, formatação canônica e handlers do logging estruturado."""

    def setUp(self) -> None:
        self.root_logger = logging.getLogger()
        self._original_handlers: List[logging.Handler] = list(self.root_logger.handlers)
        self._original_level: int = self.root_logger.level

    def tearDown(self) -> None:
        for handler in list(self.root_logger.handlers):
            self.root_logger.removeHandler(handler)
            handler.close()
        for handler in self._original_handlers:
            self.root_logger.addHandler(handler)
        self.root_logger.setLevel(self._original_level)

    def test_canonical_format_constant(self) -> None:
        expected_format = "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"
        self.assertEqual(HOMELAB_LOG_FORMAT, expected_format)
        self.assertEqual(HOMELAB_DATE_FORMAT, "%Y-%m-%d %H:%M:%S")

    def test_get_logger_instance(self) -> None:
        logger = get_logger("homelab.test.standards")
        self.assertIsInstance(logger, logging.Logger)
        self.assertEqual(logger.name, "homelab.test.standards")

    def test_logging_canonical_formatting_output(self) -> None:
        stream = io.StringIO()
        setup_logging(level=logging.INFO)

        for handler in self.root_logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.stream = stream

        logger = get_logger("homelab.service")
        logger.info("Serviço de teste inicializado com sucesso")

        output = stream.getvalue()
        pattern = (
            r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] "
            r"\[INFO\] \[homelab\.service\]: Serviço de teste inicializado com sucesso\n$"
        )
        self.assertRegex(output, pattern)

    def test_logging_with_masked_sensitive_data(self) -> None:
        stream = io.StringIO()
        setup_logging(level=logging.WARNING)

        for handler in self.root_logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.stream = stream

        logger = get_logger("homelab.auth")
        raw_secret = "1a2b3c4d5e6f7g8h9i0j"
        raw_password = "SuperSecretPassword123"

        logger.warning(
            "Tentativa de login: token=%s senha=%s",
            mask_secret(raw_secret),
            mask_password(raw_password),
        )

        output = stream.getvalue()
        self.assertIn("token=1a2b...9i0j", output)
        self.assertIn("senha=***", output)
        self.assertNotIn("3c4d5e6f", output)
        self.assertNotIn(raw_password, output)

    def test_setup_logging_file_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_file = Path(tmp_dir) / "sub" / "homelab_test.log"
            setup_logging(level=logging.DEBUG, log_file=log_file)

            for handler in self.root_logger.handlers:
                if isinstance(handler, logging.StreamHandler) and not isinstance(
                    handler, logging.FileHandler
                ):
                    handler.stream = io.StringIO()

            logger = get_logger("homelab.file")
            logger.debug("Mensagem de depuração gravada em arquivo")

            self.assertTrue(log_file.exists())
            content = log_file.read_text(encoding="utf-8")
            pattern = (
                r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] "
                r"\[DEBUG\] \[homelab\.file\]: Mensagem de depuração gravada em arquivo\n$"
            )
            self.assertRegex(content, pattern)

    def test_setup_logging_idempotent(self) -> None:
        setup_logging(level=logging.INFO)
        count_first = len(self.root_logger.handlers)
        setup_logging(level=logging.INFO)
        count_second = len(self.root_logger.handlers)
        self.assertEqual(count_first, count_second)


if __name__ == "__main__":
    unittest.main()

