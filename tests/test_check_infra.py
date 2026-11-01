#!/usr/bin/env python3
"""
Testes automatizados para o script scripts/check-infra.sh.
Valida o comportamento estrito de Fail-Fast:
- Falha na ausência de arquivo de ambiente especificado.
- Falha na ausência de variáveis obrigatórias de servidor ou cliente.
- Falha ao configurar portas privilegiadas (< 1024).
- Falha em caso de colisão entre porta de controle e de dados.
- Sucesso na validação dos arquivos .sample oficiais (server, client, unificado).
"""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check-infra.sh"
ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


class TestCheckInfraScript(unittest.TestCase):
    """Suíte de testes para validação estrita de infraestrutura e variáveis de ambiente."""

    @classmethod
    def setUpClass(cls):
        # Garante que o script tenha permissão de execução
        cls.assertTrue(SCRIPT_PATH.is_file(), f"Script não encontrado em {SCRIPT_PATH}")

    def _run_script(self, args: list[str]) -> subprocess.CompletedProcess:
        """Helper para invocar o scripts/check-infra.sh a partir da raiz do repositório."""
        cmd = [str(SCRIPT_PATH)] + args
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        proc.clean_stdout = ANSI_ESCAPE.sub("", proc.stdout)
        proc.clean_stderr = ANSI_ESCAPE.sub("", proc.stderr)
        return proc

    def test_fail_missing_env_file(self):
        """Valida que o script falha com exit code 1 se o arquivo .env apontado não existir."""
        proc = self._run_script(["--env-file", "envs/nao_existe_arquivo_12345.env", "--env-only"])
        self.assertEqual(proc.returncode, 1, f"Script deveria falhar com 1, obteve {proc.returncode}. Output:\n{proc.stdout}")
        self.assertIn("[FAIL]", proc.stdout)
        self.assertIn("Arquivo de configuração não encontrado", proc.stdout)

    def test_fail_missing_required_variable_server(self):
        """Valida fail-fast quando variáveis obrigatórias do servidor estiverem faltando."""
        content = (
            "HOMELAB_SERVER_HOST=0.0.0.0\n"
            "HOMELAB_CONTROL_PORT=9000\n"
            # Omitindo HOMELAB_DATA_PORT, HOMELAB_HANDSHAKE_KEY, etc.
        )
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            proc = self._run_script(["--mode", "server", "--env-file", temp_path, "--env-only"])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("[FAIL]", proc.stdout)
            self.assertIn("HOMELAB_DATA_PORT", proc.stdout)
            self.assertIn("HOMELAB_HANDSHAKE_KEY", proc.stdout)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_fail_missing_required_variable_client(self):
        """Valida fail-fast quando variáveis obrigatórias do cliente estiverem faltando."""
        content = (
            "HOMELAB_CLIENT_TARGET_HOST=127.0.0.1\n"
            "HOMELAB_CONTROL_PORT=9000\n"
            # Omitindo HOMELAB_CLIENT_TIMEOUT, HOMELAB_SESSION_PATH, etc.
        )
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            proc = self._run_script(["--mode", "client", "--env-file", temp_path, "--env-only"])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("[FAIL]", proc.stdout)
            self.assertIn("HOMELAB_CLIENT_TIMEOUT", proc.stdout)
            self.assertIn("HOMELAB_SESSION_PATH", proc.stdout)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_fail_privileged_port(self):
        """Valida que portas privilegiadas (< 1024) são rejeitadas estritamente."""
        content = (
            "HOMELAB_SERVER_HOST=0.0.0.0\n"
            "HOMELAB_CONTROL_PORT=80\n"  # Porta HTTP privilegiada (< 1024)
            "HOMELAB_DATA_PORT=9001\n"
            "HOMELAB_HANDSHAKE_KEY=chave-teste\n"
            "HOMELAB_CHUNK_SIZE=65536\n"
            "HOMELAB_BUFFER_SIZE=4096\n"
            "HOMELAB_DB_PATH=app/data/homelab.db\n"
            "HOMELAB_LOG_PATH=app/logs/server.log\n"
            "HOMELAB_UPLOADS_DIR=app/data/uploads\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            proc = self._run_script(["--mode", "server", "--env-file", temp_path, "--env-only"])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("[FAIL]", proc.stdout)
            self.assertIn("não privilegiada", proc.stdout)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_fail_port_collision(self):
        """Valida que a colisão entre a porta de controle e dados causa fail-fast imediato."""
        content = (
            "HOMELAB_SERVER_HOST=0.0.0.0\n"
            "HOMELAB_CONTROL_PORT=9000\n"
            "HOMELAB_DATA_PORT=9000\n"  # Mesma porta do controle
            "HOMELAB_HANDSHAKE_KEY=chave-teste\n"
            "HOMELAB_CHUNK_SIZE=65536\n"
            "HOMELAB_BUFFER_SIZE=4096\n"
            "HOMELAB_DB_PATH=app/data/homelab.db\n"
            "HOMELAB_LOG_PATH=app/logs/server.log\n"
            "HOMELAB_UPLOADS_DIR=app/data/uploads\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            proc = self._run_script(["--mode", "server", "--env-file", temp_path, "--env-only"])
            self.assertEqual(proc.returncode, 1)
            self.assertIn("[FAIL]", proc.stdout)
            self.assertIn("Conflito de portas", proc.stdout)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_success_server_env_sample(self):
        """Valida sucesso na verificação do arquivo oficial envs/server.env.sample."""
        proc = self._run_script(["--mode", "server", "--env-file", "envs/server.env.sample", "--env-only"])
        self.assertEqual(proc.returncode, 0, f"Deveria ter retornado 0. Saída:\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("[OK] Verificação estrita de ambiente concluída com sucesso (--env-only).", proc.stdout)

    def test_success_client_env_sample(self):
        """Valida sucesso na verificação do arquivo oficial envs/client.env.sample."""
        proc = self._run_script(["--mode", "client", "--env-file", "envs/client.env.sample", "--env-only"])
        self.assertEqual(proc.returncode, 0, f"Deveria ter retornado 0. Saída:\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("[OK] Verificação estrita de ambiente concluída com sucesso (--env-only).", proc.stdout)

    def test_success_unified_env_sample(self):
        """Valida sucesso do arquivo unificado envs/.env.sample tanto para server quanto para client."""
        # Modo Server
        proc_s = self._run_script(["--mode", "server", "--env-file", "envs/.env.sample", "--env-only"])
        self.assertEqual(proc_s.returncode, 0, f"Server mode falhou com envs/.env.sample:\n{proc_s.stdout}")
        self.assertIn("[OK] Verificação estrita de ambiente concluída com sucesso", proc_s.stdout)

        # Modo Client
        proc_c = self._run_script(["--mode", "client", "--env-file", "envs/.env.sample", "--env-only"])
        self.assertEqual(proc_c.returncode, 0, f"Client mode falhou com envs/.env.sample:\n{proc_c.stdout}")
        self.assertIn("[OK] Verificação estrita de ambiente concluída com sucesso", proc_c.stdout)


if __name__ == "__main__":
    unittest.main()
