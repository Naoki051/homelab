#!/usr/bin/env python3
"""
Testes automatizados para o módulo de gerenciamento de configurações (app/config.py).
Valida valores padrão, leitura de arquivos server.env e client.env,
sobreposição via os.environ e hooks de validação (fail fast).
"""

import os
from pathlib import Path
import tempfile
import unittest

from app.config import (
    REPO_ROOT,
    ClientConfig,
    ConfigValidationError,
    ServerConfig,
    _get_float,
    _get_int,
    _get_path,
    _get_str,
    load_client_config,
    load_server_config,
)


class TestConfigManagement(unittest.TestCase):
    """Suite de testes para carregamento, precedência e validação de configurações."""

    def setUp(self):
        # Salva o estado original do os.environ para restauração
        self._orig_env = os.environ.copy()

    def tearDown(self):
        # Restaura os.environ original
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_sample_files_exist_in_envs_dir(self):
        """Garante que os arquivos .sample existam e estejam na pasta envs/."""
        self.assertTrue((REPO_ROOT / "envs" / "server.env.sample").is_file(), "server.env.sample deve existir em envs/.")
        self.assertTrue((REPO_ROOT / "envs" / "client.env.sample").is_file(), "client.env.sample deve existir em envs/.")
        self.assertTrue((REPO_ROOT / "envs" / ".env.sample").is_file(), ".env.sample deve existir em envs/.")

    def test_default_loader_discovers_envs_directory(self):
        """Verifica se os loaders encontram automaticamente os arquivos em envs/."""
        s_cfg = load_server_config()
        c_cfg = load_client_config()
        self.assertIsNotNone(s_cfg.source_file)
        self.assertTrue(str(s_cfg.source_file).endswith("envs/server.env"))
        self.assertIsNotNone(c_cfg.source_file)
        self.assertTrue(str(c_cfg.source_file).endswith("envs/client.env"))

    def test_server_config_defaults(self):
        """Verifica se os valores padrão do servidor são seguros e válidos."""
        # Limpa variáveis HOMELAB_ do ambiente para testar defaults puros
        for k in list(os.environ.keys()):
            if k.startswith("HOMELAB_"):
                del os.environ[k]

        with tempfile.NamedTemporaryFile("w", delete=False) as empty_env:
            empty_env.write("# Arquivo vazio\n")
            empty_path = Path(empty_env.name)

        try:
            cfg = load_server_config(env_file=empty_path, override=True)
            self.assertEqual(cfg.host, "0.0.0.0")
            self.assertEqual(cfg.control_port, 9000)
            self.assertEqual(cfg.data_port, 9001)
            self.assertEqual(cfg.chunk_size, 65536)
            self.assertEqual(cfg.buffer_size, 4096)
            self.assertEqual(cfg.handshake_key, b"homelab-initial-handshake-key-32")
            self.assertTrue(cfg.db_path.name.endswith(".db"))
            self.assertTrue(cfg.log_path.name.endswith(".log"))
            self.assertTrue(cfg.uploads_dir.name == "uploads")
        finally:
            if empty_path.exists():
                empty_path.unlink()

    def test_client_config_defaults(self):
        """Verifica se os valores padrão do cliente são seguros e válidos."""
        for k in list(os.environ.keys()):
            if k.startswith("HOMELAB_"):
                del os.environ[k]

        with tempfile.NamedTemporaryFile("w", delete=False) as empty_env:
            empty_env.write("# Arquivo vazio\n")
            empty_path = Path(empty_env.name)

        try:
            cfg = load_client_config(env_file=empty_path, override=True)
            self.assertIn(cfg.host, ("192.168.0.246", "127.0.0.1"))
            self.assertEqual(cfg.control_port, 9000)
            self.assertEqual(cfg.data_port, 9001)
            self.assertEqual(cfg.chunk_size, 65536)
            self.assertEqual(cfg.timeout, 10.0)
            self.assertEqual(cfg.buffer_size, 4096)
            self.assertTrue(cfg.session_path.name.endswith(".json"))
        finally:
            if empty_path.exists():
                empty_path.unlink()

    def test_server_env_file_custom_values(self):
        """Valida que o arquivo customizado de server.env substitui corretamente as configurações."""
        content = """
HOMELAB_SERVER_HOST=10.0.0.50
HOMELAB_CONTROL_PORT=9500
HOMELAB_DATA_PORT=9501
HOMELAB_CHUNK_SIZE=32768
HOMELAB_HANDSHAKE_KEY=chave-secreta-personalizada-servidor
"""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(content)
            temp_path = Path(f.name)

        try:
            cfg = load_server_config(env_file=temp_path, override=True)
            self.assertEqual(cfg.host, "10.0.0.50")
            self.assertEqual(cfg.control_port, 9500)
            self.assertEqual(cfg.data_port, 9501)
            self.assertEqual(cfg.chunk_size, 32768)
            self.assertEqual(cfg.handshake_key, b"chave-secreta-personalizada-servidor")
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_client_env_file_custom_values(self):
        """Valida que o arquivo customizado de client.env substitui corretamente as configurações."""
        content = """
HOMELAB_CLIENT_TARGET_HOST=172.16.0.10
HOMELAB_CONTROL_PORT=9600
HOMELAB_DATA_PORT=9601
HOMELAB_CLIENT_TIMEOUT=45.5
HOMELAB_HANDSHAKE_KEY=chave-secreta-personalizada-cliente
"""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(content)
            temp_path = Path(f.name)

        try:
            cfg = load_client_config(env_file=temp_path, override=True)
            self.assertEqual(cfg.host, "172.16.0.10")
            self.assertEqual(cfg.control_port, 9600)
            self.assertEqual(cfg.data_port, 9601)
            self.assertEqual(cfg.timeout, 45.5)
            self.assertEqual(cfg.handshake_key, b"chave-secreta-personalizada-cliente")
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_os_environ_precedence_when_no_override(self):
        """Valida que variáveis de ambiente já exportadas no SO são respeitadas."""
        os.environ["HOMELAB_CONTROL_PORT"] = "9999"
        os.environ["HOMELAB_SERVER_HOST"] = "192.168.1.200"

        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("HOMELAB_CONTROL_PORT=8888\nHOMELAB_SERVER_HOST=10.0.0.1\n")
            temp_path = Path(f.name)

        try:
            # Com override=False (padrão de variáveis de ambiente do SO), o os.environ prevalece
            cfg = load_server_config(env_file=temp_path, override=False)
            self.assertEqual(cfg.control_port, 9999)
            self.assertEqual(cfg.host, "192.168.1.200")
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_fail_fast_hook_validation(self):
        """Testa o comportamento do hook de validação e fail fast."""
        # Instância válida com fail_fast=True não deve levantar erro
        valid_server = ServerConfig(
            host="127.0.0.1",
            control_port=9000,
            data_port=9001,
            handshake_key=b"chave",
            chunk_size=65536,
            buffer_size=4096,
            db_path=Path("test.db"),
            log_path=Path("test.log"),
            uploads_dir=Path("uploads"),
        )
        valid_server.validate(fail_fast=True)

        # Instância com porta inválida sob fail_fast=True deve levantar ConfigValidationError
        invalid_server = ServerConfig(
            host="127.0.0.1",
            control_port=70000,  # Porta inválida (> 65535)
            data_port=9001,
            handshake_key=b"chave",
            chunk_size=65536,
            buffer_size=4096,
            db_path=Path("test.db"),
            log_path=Path("test.log"),
            uploads_dir=Path("uploads"),
        )
        with self.assertRaises(ConfigValidationError):
            invalid_server.validate(fail_fast=True)

        # Teste de helper _get_str com required=True e fail_fast=True
        with self.assertRaises(ConfigValidationError):
            _get_str("NON_EXISTENT_VAR", "", fail_fast=True, required=True)

        # Teste de helper _get_int com valor inválido
        os.environ["HOMELAB_BAD_INT"] = "nao_e_numero"
        with self.assertRaises(ConfigValidationError):
            _get_int("HOMELAB_BAD_INT", 9000, fail_fast=True)


if __name__ == "__main__":
    unittest.main()
