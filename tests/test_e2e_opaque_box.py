#!/usr/bin/env python3
"""Suíte de Testes Ponta a Ponta (E2E) Opaque-Box em 4 Tiers para o Ecossistema Homelab.

Esta suíte valida o comportamento do cliente e servidor Homelab exclusivamente
através de interfaces públicas, sockets TCP reais em loopback, chamadas CLI via
subprocesso e persistência em disco isolada, sem mocks ou inspeção de estado privado:

- Tier 1: Feature Coverage (Caminho Feliz Isolado)
- Tier 2: Boundary & Corner Cases (Limites, Ataques e Falhas de Rede)
- Tier 3: Cross-Feature Combinations (Fluxos Sequenciais e Transições de Estado)
- Tier 4: Real-World Application Scenarios (Concorrência, Ciclo Completo e CLI)
"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from typing import List, Optional, Tuple
import unittest

from app.client import Client, ControlConnection, HomelabClient, Session
from app.client.commands import (
    LoginCommand,
    LogoutCommand,
    RegisterCommand,
    SendMessageCommand,
    UploadFileCommand,
)
from app.client_session import Session as LegacySession
from app.protocol import (
    CHUNK_HEADER_SIZE,
    CHUNK_SIZE,
    CONTROL_HEADER_SIZE,
    CONTROL_MAGIC,
    DATA_MAGIC,
    DEFAULT_HANDSHAKE_KEY,
    ControlPackage,
    DataPackage,
    MediaChunk,
    Message,
    Package,
    compute_hmac,
    generate_session_key,
    generate_upload_ticket,
)
from app.server import (
    BaseNetworkService,
    ControlServer,
    DataServer,
    DualChannelServer,
    HomelabServer,
    Server,
)


class OpaqueBoxTestCase(unittest.TestCase):
    """Fixture base com servidor efêmero isolado e utilitários de ciclo de vida."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="homelab_e2e_")
        self.db_path = Path(self.temp_dir) / "e2e.db"
        self.log_path = Path(self.temp_dir) / "e2e.log"
        self.uploads_dir = Path(self.temp_dir) / "uploads"
        self.session_path = Path(self.temp_dir) / "client_session.json"

        self.server = HomelabServer(
            host="127.0.0.1",
            control_port=0,
            data_port=0,
            db_path=self.db_path,
            log_path=self.log_path,
            uploads_dir=self.uploads_dir,
        )
        self.server.start()
        time.sleep(0.05)

    def tearDown(self) -> None:
        self.server.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_client(
        self, session_path: Optional[Path] = None, timeout: float = 5.0
    ) -> HomelabClient:
        """Instancia um HomelabClient apontado para as portas efêmeras do servidor de teste."""
        return HomelabClient(
            host="127.0.0.1",
            control_port=self.server.control_port,
            data_port=self.server.data_port,
            session_path=session_path or self.session_path,
            timeout=timeout,
        )

    def wait_for_user_status(
        self, username: str, expected_status: str, timeout: float = 2.0
    ) -> None:
        """Aguarda a atualização determinística de status de presença no SQLite."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            user = self.server.repo.get_by_username(username)
            if user and user.status == expected_status:
                return
            time.sleep(0.02)
        user = self.server.repo.get_by_username(username)
        actual = user.status if user else None
        self.assertEqual(
            actual,
            expected_status,
            f"Timeout ({timeout}s): Usuário '{username}' com status '{actual}' "
            f"(esperado: '{expected_status}')",
        )


class TestTier1FeatureCoverage(OpaqueBoxTestCase):
    """Tier 1: Feature Coverage — Validação isolada de caminhos felizes em componentes públicos."""

    def test_tier1_server_facades_and_cli_help(self) -> None:
        """Valida fachadas retrocompatíveis do servidor e sinalizadores CLI (--help)."""
        self.assertIs(DualChannelServer, HomelabServer)
        self.assertIs(Server, HomelabServer)
        self.assertIs(Client, HomelabClient)

        self.assertTrue(self.server.is_running)
        self.assertGreater(self.server.control_port, 0)
        self.assertGreater(self.server.data_port, 0)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd())

        res_srv = subprocess.run(
            [sys.executable, "-m", "app.server", "--help"],
            capture_output=True,
            text=True,
            env=env,
            timeout=5.0,
        )
        self.assertEqual(res_srv.returncode, 0)
        self.assertIn("--port", res_srv.stdout)
        self.assertIn("--data-port", res_srv.stdout)

        res_cli = subprocess.run(
            [sys.executable, "-m", "app.client", "--help"],
            capture_output=True,
            text=True,
            env=env,
            timeout=5.0,
        )
        self.assertEqual(res_cli.returncode, 0)
        self.assertIn("--port", res_cli.stdout)
        self.assertIn("--message", res_cli.stdout)
        self.assertIn("--upload", res_cli.stdout)

    def test_tier1_client_registration_happy_path(self) -> None:
        """Valida cadastro de nova conta via HomelabClient e emissão de chave HMAC dinâmica."""
        with self.create_client() as client:
            ok, msg = client.register("user_t1_reg", "SecretPass123!")
            self.assertTrue(ok, msg)
            self.assertEqual(client.username, "user_t1_reg")
            self.assertNotEqual(client.session_key, DEFAULT_HANDSHAKE_KEY)
            self.assertEqual(len(client.session_key), 32)

        user = self.server.repo.get_by_username("user_t1_reg")
        self.assertIsNotNone(user)
        self.assertEqual(user.status, "offline")

    def test_tier1_client_login_and_hmac_session_rotation(self) -> None:
        """Valida autenticação de usuário existente e rotação de chave HMAC."""
        with self.create_client() as c_reg:
            ok_reg, msg_reg = c_reg.register("user_t1_login", "LoginPass456!")
            self.assertTrue(ok_reg, msg_reg)

        with self.create_client() as client:
            self.assertEqual(client.session_key, DEFAULT_HANDSHAKE_KEY)
            ok, msg = client.login("user_t1_login", "LoginPass456!")
            self.assertTrue(ok, msg)
            self.assertEqual(client.username, "user_t1_login")
            self.assertNotEqual(client.session_key, DEFAULT_HANDSHAKE_KEY)
            self.assertEqual(len(client.session_key), 32)

    def test_tier1_client_send_message_happy_path(self) -> None:
        """Valida envio de mensagem no canal de controle persistente e auditoria em log."""
        with self.create_client() as client:
            client.register("user_t1_msg", "Pass12345!")
            ok, msg = client.send_message("Mensagem de teste Tier 1 Opaque-Box")
            self.assertTrue(ok, msg)
            self.assertIn("sucesso", msg.lower())

        self.assertTrue(self.log_path.is_file())
        log_content = self.log_path.read_text(encoding="utf-8")
        self.assertIn("user_t1_msg@", log_content)
        self.assertIn("Mensagem de teste Tier 1 Opaque-Box", log_content)

    def test_tier1_client_upload_small_file_happy_path(self) -> None:
        """Valida upload de arquivo com chunk único (< 64 KB) e integridade de disco."""
        src_file = Path(self.temp_dir) / "small_doc.txt"
        test_data = b"Homelab Tier 1 Opaque-Box Single-Chunk Upload Payload."
        src_file.write_bytes(test_data)

        with self.create_client() as client:
            client.register("user_t1_up_small", "UploadPass123!")
            ok, msg = client.upload_file(src_file)
            self.assertTrue(ok, msg)
            self.assertIn("sucesso", msg.lower())

        user_dir = self.uploads_dir / "user_t1_up_small"
        self.assertTrue(user_dir.is_dir())
        saved_files = list(user_dir.glob("*small_doc.txt"))
        self.assertEqual(len(saved_files), 1)
        self.assertEqual(saved_files[0].read_bytes(), test_data)

    def test_tier1_client_upload_multi_chunk_file_happy_path(self) -> None:
        """Valida upload de arquivo com múltiplos chunks (> 64 KB) e cálculo SHA-256."""
        src_file = Path(self.temp_dir) / "multi_chunk.bin"
        payload_size = 150 * 1024  # 150 KB -> 3 chunks (64KB + 64KB + 22KB)
        test_data = os.urandom(payload_size)
        src_file.write_bytes(test_data)
        expected_sha = hashlib.sha256(test_data).hexdigest()

        with self.create_client() as client:
            client.register("user_t1_up_multi", "MultiPass123!")
            ok, msg = client.upload_file(src_file)
            self.assertTrue(ok, msg)
            self.assertIn("sucesso", msg.lower())

        saved_files = list((self.uploads_dir / "user_t1_up_multi").glob("*multi_chunk.bin"))
        self.assertEqual(len(saved_files), 1)
        actual_bytes = saved_files[0].read_bytes()
        self.assertEqual(len(actual_bytes), payload_size)
        self.assertEqual(actual_bytes, test_data)
        self.assertEqual(hashlib.sha256(actual_bytes).hexdigest(), expected_sha)

    def test_tier1_session_persistence_posix_permissions_and_load(self) -> None:
        """Valida persistência de sessão NoSQL, permissões POSIX 0600 e compatibilidade legada."""
        self.assertIs(LegacySession, Session)
        session = Session.create("user_t1_sess", "Pass12345!")
        session.save(self.session_path)

        self.assertTrue(self.session_path.is_file())
        file_mode = self.session_path.stat().st_mode & 0o777
        self.assertEqual(file_mode, 0o600)

        loaded = Session.load(self.session_path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.last_username, "user_t1_sess")
        self.assertTrue(loaded.is_valid())

    def test_tier1_client_logout_and_presence_offline(self) -> None:
        """Valida encerramento voluntário via LogoutCommand e reversão de chave de sessão."""
        with self.create_client() as client:
            client.register("user_t1_logout", "LogoutPass123!")
            self.assertNotEqual(client.session_key, DEFAULT_HANDSHAKE_KEY)
            self.wait_for_user_status("user_t1_logout", "online")

            ok, msg = LogoutCommand().execute(client.control_conn)
            self.assertTrue(ok, msg)
            self.wait_for_user_status("user_t1_logout", "offline")
            client.close()
            self.assertEqual(client.session_key, DEFAULT_HANDSHAKE_KEY)

    def test_tier1_protocol_package_hierarchy_and_polymorphism(self) -> None:
        """Valida a hierarquia Package(ABC), Message e MediaChunk sob despacho polimórfico."""
        self.assertTrue(issubclass(Package, unittest.TestCase.__class__.__bases__[0]))
        self.assertTrue(issubclass(Message, Package))
        self.assertTrue(issubclass(MediaChunk, Package))
        self.assertIs(ControlPackage, Message)
        self.assertIs(DataPackage, MediaChunk)

        key = generate_session_key()
        msg = Message(action=Message.ACTION_SEND, payload={"text": "teste_poly"})
        frame_bytes = msg.to_frame_bytes(hmac_key=key)
        self.assertTrue(frame_bytes.startswith(CONTROL_MAGIC))

        cli_sock, srv_sock = socket.socketpair()
        try:
            msg.send(cli_sock, hmac_key=key)
            received = Message.read_frame(srv_sock, hmac_key=key)
            self.assertIsNotNone(received)
            self.assertIsInstance(received, Package)
            self.assertEqual(received.payload.get("text"), "teste_poly")
        finally:
            cli_sock.close()
            srv_sock.close()


class TestTier2BoundaryAndCornerCases(OpaqueBoxTestCase):
    """Tier 2: Boundary & Corner Cases — Limites de tamanho, credenciais inválidas e ataques."""

    def test_tier2_empty_and_whitespace_credentials(self) -> None:
        """Rejeita cadastros e logins com strings vazias ou compostas por espaços."""
        with self.create_client() as client:
            ok, msg = client.register("", "ValidPass123!")
            self.assertFalse(ok)
            self.assertTrue(len(msg) > 0)

            ok, msg = client.register("   ", "ValidPass123!")
            self.assertFalse(ok)
            self.assertTrue(len(msg) > 0)

            ok, msg = client.register("valid_user_empty_pwd", "", is_already_derived=True)
            self.assertFalse(ok)
            self.assertTrue(len(msg) > 0)

            ok, msg = client.login("valid_user_empty_pwd", "", is_already_derived=True)
            self.assertFalse(ok)
            self.assertTrue(len(msg) > 0)

    def test_tier2_duplicate_user_registration(self) -> None:
        """Rejeita tentativa de cadastrar usuário com nome já existente no SQLite."""
        with self.create_client() as client:
            ok, msg = client.register("user_t2_dup", "PassOriginal123!")
            self.assertTrue(ok)

        with self.create_client() as client2:
            ok2, msg2 = client2.register("user_t2_dup", "OutraSenha123!")
            self.assertFalse(ok2)
            self.assertIn("já existe", msg2.lower())

    def test_tier2_invalid_login_credentials(self) -> None:
        """Rejeita tentativa de login com usuário inexistente ou senha incorreta."""
        with self.create_client() as client:
            ok, msg = client.login("fantasma_inexistente", "senha123")
            self.assertFalse(ok)
            self.assertIn("não encontrado", msg.lower())

            client.register("user_t2_badpwd", "SenhaCorreta123!")

        with self.create_client() as client2:
            ok_err, msg_err = client2.login("user_t2_badpwd", "SenhaTotalmenteErrada")
            self.assertFalse(ok_err)
            self.assertIn("senha incorreta", msg_err.lower())

    def test_tier2_unauthenticated_actions_rejected(self) -> None:
        """Rejeita envio de mensagens ou solicitação de upload por clientes não autenticados."""
        dummy_file = Path(self.temp_dir) / "dummy.txt"
        dummy_file.write_bytes(b"dados")

        with self.create_client() as client:
            ok_msg, res_msg = client.send_message("Texto sem autenticação")
            self.assertFalse(ok_msg)
            self.assertIn("não autenticado", res_msg.lower())

            ok_up, res_up = client.upload_file(dummy_file)
            self.assertFalse(ok_up)
            self.assertIn("não autenticado", res_up.lower())

    def test_tier2_zero_byte_empty_file_upload(self) -> None:
        """Manipula upload de arquivo vazio (0 bytes) com integridade SHA-256."""
        empty_file = Path(self.temp_dir) / "empty.bin"
        empty_file.write_bytes(b"")
        empty_sha = hashlib.sha256(b"").hexdigest()

        with self.create_client() as client:
            client.register("user_t2_empty", "EmptyPass123!")
            ok, msg = client.upload_file(empty_file)
            self.assertTrue(ok, msg)
            self.assertIn("sucesso", msg.lower())

        saved = list((self.uploads_dir / "user_t2_empty").glob("*empty.bin"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].stat().st_size, 0)
        self.assertEqual(hashlib.sha256(saved[0].read_bytes()).hexdigest(), empty_sha)

    def test_tier2_exact_chunk_boundary_payload_65536_bytes(self) -> None:
        """Valida arquivo com tamanho exatamente igual ao limite de chunk de 64 KB."""
        exact_file = Path(self.temp_dir) / "exact_64k.bin"
        exact_payload = os.urandom(CHUNK_SIZE)  # 65536 bytes
        exact_file.write_bytes(exact_payload)
        expected_sha = hashlib.sha256(exact_payload).hexdigest()

        with self.create_client() as client:
            client.register("user_t2_exact", "ExactPass123!")
            ok, msg = client.upload_file(exact_file)
            self.assertTrue(ok, msg)

        saved = list((self.uploads_dir / "user_t2_exact").glob("*exact_64k.bin"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].stat().st_size, CHUNK_SIZE)
        self.assertEqual(hashlib.sha256(saved[0].read_bytes()).hexdigest(), expected_sha)

    def test_tier2_control_channel_bad_magic_bytes(self) -> None:
        """Servidor rejeita com segurança bytes mágicos desconhecidos sem travar o daemon."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.control_port))
            bad_frame = b"ZZ" + os.urandom(38) + b"malicious_payload"
            sock.sendall(bad_frame)
            sock.settimeout(2.0)
            try:
                sock.recv(1024)
            except (ConnectionResetError, socket.timeout):
                pass

        # Verifica se o servidor permanece perfeitamente operacional para clientes subsequentes
        with self.create_client() as client:
            ok, msg = client.register("user_after_bad_magic", "Pass12345!")
            self.assertTrue(ok, msg)

    def test_tier2_control_channel_corrupted_hmac(self) -> None:
        """Servidor descarta pacote com assinatura HMAC violada e encerra a conexão."""
        key = generate_session_key()
        msg = Message(action=Message.ACTION_SEND, payload={"text": "adulterado"})
        tampered_frame = bytearray(msg.to_frame(hmac_key=key))
        # Adultera o HMAC (bytes 8 a 39 do cabeçalho)
        tampered_frame[10] ^= 0xFF

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.control_port))
            sock.sendall(tampered_frame)
            sock.settimeout(2.0)
            try:
                resp = sock.recv(1024)
                self.assertEqual(len(resp), 0)
            except (ConnectionResetError, socket.timeout):
                pass

    def test_tier2_data_channel_tampered_payload_sha_mismatch(self) -> None:
        """Servidor descarta arquivo corrompido em disco se o SHA-256 divergir do esperado."""
        with self.create_client() as client:
            client.register("user_t2_tamper", "TamperPass123!")
            conn = client.control_conn
            self.assertIsNotNone(conn)

            # Solicita ticket de upload com SHA esperado informado na chave 'sha256'
            raw_data = b"Dados_originais_intactos_123"
            expected_sha = hashlib.sha256(raw_data).hexdigest()
            req = Message(
                action=Message.ACTION_REQUEST_UPLOAD,
                payload={
                    "username": "user_t2_tamper",
                    "filename": "tampered.bin",
                    "file_size": len(raw_data),
                    "sha256": expected_sha,
                },
            )
            resp = conn.send_request(req)
            self.assertIsNotNone(resp)
            self.assertEqual(resp.payload.get("status"), Message.STATUS_OK)
            ticket_hex = resp.payload.get("ticket")
            ticket_bytes = bytes.fromhex(ticket_hex)

            # Envia chunk com dados propositalmente alterados
            tampered_data = b"Dados_adulterados_com_erro!!"
            chunk = MediaChunk(
                ticket=ticket_bytes,
                chunk_index=0,
                total_chunks=1,
                data=tampered_data,
            )
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as data_sock:
                data_sock.settimeout(5.0)
                data_sock.connect(("127.0.0.1", self.server.data_port))
                chunk.send(data_sock, hmac_key=conn.session_key)
                resp_chunk = Message.recv_framed(data_sock, hmac_key=conn.session_key)
                self.assertIsNotNone(resp_chunk)
                self.assertEqual(resp_chunk.payload.get("status"), Message.STATUS_ERROR)
                self.assertIn("sha-256", resp_chunk.payload.get("message", "").lower())

        # Garante que nenhum arquivo corrompido sobreviveu no diretório de uploads
        saved = list((self.uploads_dir / "user_t2_tamper").glob("*tampered.bin"))
        self.assertEqual(len(saved), 0)

    def test_tier2_abrupt_tcp_rst_presence_cleanup(self) -> None:
        """Garante que queda abrupta de conexão (SO_LINGER=0) transiciona usuário para offline."""
        client = self.create_client()
        client.register("user_t2_rst", "RstPass123!")
        self.wait_for_user_status("user_t2_rst", "online")

        # Configura SO_LINGER=0 e fecha o socket sem FIN (emite TCP RST)
        sock = client.control_conn.sock
        if sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            sock.close()

        self.wait_for_user_status("user_t2_rst", "offline", timeout=3.0)


class TestTier3CrossFeatureCombinations(OpaqueBoxTestCase):
    """Tier 3: Cross-Feature Combinations — Transições de estado entre múltiplos subsistemas."""

    def test_tier3_registration_session_save_and_quick_login_flow(self) -> None:
        """Fluxo sequencial: Registro -> Gravação de Sessão -> Quick-Login com hash derivado."""
        with self.create_client() as client1:
            ok, msg = client1.register("tier3_flow_user", "ComplexPass999!")
            self.assertTrue(ok, msg)
            sess = Session.create(
                "tier3_flow_user", client1.secret_hash or "", is_already_derived=True
            )
            sess.save(self.session_path)

        # Nova instância do cliente carrega a sessão e realiza login sem senha em texto puro
        with self.create_client() as client2:
            self.assertIsNotNone(client2.session)
            ok_login, msg_login = client2.login(
                username="tier3_flow_user",
                password=client2.session.last_password,
                is_already_derived=True,
            )
            self.assertTrue(ok_login, msg_login)
            ok_msg, res_msg = client2.send_message("Mensagem pós Quick-Login!")
            self.assertTrue(ok_msg, res_msg)

    def test_tier3_auth_upload_and_message_in_single_persistent_session(self) -> None:
        """Upload de 80 KB e mensagem mantendo a mesma chave dinâmica de sessão persistente."""
        test_file = Path(self.temp_dir) / "persistent_flow.bin"
        test_data = os.urandom(80 * 1024)
        test_file.write_bytes(test_data)

        with self.create_client() as client:
            client.register("tier3_persist", "PersistPass123!")
            initial_session_key = client.session_key

            ok_up, msg_up = client.upload_file(test_file)
            self.assertTrue(ok_up, msg_up)
            self.assertEqual(client.session_key, initial_session_key)

            ok_send, msg_send = client.send_message("Arquivo de 80KB transmitido com sucesso!")
            self.assertTrue(ok_send, msg_send)
            self.assertEqual(client.session_key, initial_session_key)

        log_data = self.log_path.read_text(encoding="utf-8")
        self.assertIn("Arquivo de 80KB transmitido", log_data)

    def test_tier3_interrupted_upload_and_reauth_recovery(self) -> None:
        """Cliente sofre interrupção do socket de dados e recupera com novo ticket sem travar."""
        file_to_send = Path(self.temp_dir) / "resilient.bin"
        file_data = b"B" * 70000  # 2 chunks
        file_to_send.write_bytes(file_data)

        with self.create_client() as client:
            client.register("tier3_resilient", "ResilientPass123!")
            conn = client.control_conn

            # 1. Solicita ticket inicial e derruba o socket de dados prematuramente
            req = Message(
                action=Message.ACTION_REQUEST_UPLOAD,
                payload={
                    "username": "tier3_resilient",
                    "filename": "resilient.bin",
                    "file_size": len(file_data),
                    "sha256": hashlib.sha256(file_data).hexdigest(),
                },
            )
            resp = conn.send_request(req)
            ticket_bytes = bytes.fromhex(resp.payload.get("ticket"))

            # Abre socket de dados e encerra antes de terminar
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bad_data_sock:
                bad_data_sock.connect(("127.0.0.1", self.server.data_port))
                first_chunk = MediaChunk(
                    ticket=ticket_bytes,
                    chunk_index=0,
                    total_chunks=2,
                    data=file_data[:CHUNK_SIZE],
                )
                first_chunk.send(bad_data_sock, hmac_key=conn.session_key)

            # 2. Conexão de controle permanece sã: reemite upload completo com sucesso
            ok_up, msg_up = client.upload_file(file_to_send)
            self.assertTrue(ok_up, msg_up)

        saved = list((self.uploads_dir / "tier3_resilient").glob("*resilient.bin"))
        self.assertGreaterEqual(len(saved), 1)
        self.assertTrue(any(f.read_bytes() == file_data for f in saved))

    def test_tier3_sequential_uploads_varying_payload_sizes(self) -> None:
        """Executa 4 uploads consecutivos com tamanhos heterogêneos na mesma sessão."""
        sizes = [256, 65536, 100000, 196608]  # <1 chunk, 1 chunk, 2 chunks, 3 chunks
        with self.create_client() as client:
            client.register("tier3_multi_sizes", "SizesPass123!")

            for i, sz in enumerate(sizes):
                fpath = Path(self.temp_dir) / f"file_{i}_{sz}.bin"
                data = os.urandom(sz)
                fpath.write_bytes(data)
                ok, msg = client.upload_file(fpath)
                self.assertTrue(ok, f"Falha no upload do arquivo {i} de tamanho {sz}: {msg}")

        user_files = list((self.uploads_dir / "tier3_multi_sizes").glob("*.bin"))
        self.assertEqual(len(user_files), 4)

    def test_tier3_interleaved_messages_and_uploads(self) -> None:
        """Intercala repetidamente o envio de texto e arquivos na mesma conexão keep-alive."""
        with self.create_client() as client:
            client.register("tier3_interleave", "InterPass123!")

            for i in range(3):
                ok_msg, res_msg = client.send_message(f"Mensagem intercalada {i}")
                self.assertTrue(ok_msg, res_msg)

                fpath = Path(self.temp_dir) / f"interleaved_{i}.txt"
                fpath.write_bytes(f"Conteúdo de upload {i}".encode())
                ok_up, res_up = client.upload_file(fpath)
                self.assertTrue(ok_up, res_up)

        log_content = self.log_path.read_text(encoding="utf-8")
        for i in range(3):
            self.assertIn(f"Mensagem intercalada {i}", log_content)


class TestTier4RealWorldScenarios(OpaqueBoxTestCase):
    """Tier 4: Real-World Scenarios — Concorrência, ciclo de vida completo e CLI em subprocesso."""

    def test_tier4_multi_client_concurrent_chat_simulation(self) -> None:
        """Simulação de 3 clientes operando em paralelo com envio concorrente de mensagens."""
        usernames = ["alice_t4", "bob_t4", "charlie_t4"]

        def run_client_worker(uname: str) -> None:
            with self.create_client() as client:
                ok_reg, _ = client.register(uname, f"Pass_{uname}!")
                self.assertTrue(ok_reg)
                for m_idx in range(3):
                    ok_m, _ = client.send_message(f"Mensagem concorrente {m_idx} de {uname}")
                    self.assertTrue(ok_m)
                    time.sleep(0.01)

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(run_client_worker, u) for u in usernames]
            for f in futures:
                f.result()

        log_text = self.log_path.read_text(encoding="utf-8")
        for uname in usernames:
            for m_idx in range(3):
                self.assertIn(f"Mensagem concorrente {m_idx} de {uname}", log_text)
            self.wait_for_user_status(uname, "offline")

    def test_tier4_concurrent_media_uploads(self) -> None:
        """Uploads concorrentes de arquivos pesados por múltiplos usuários em paralelo."""
        users_and_sizes = [
            ("user_up_1", 20 * 1024),
            ("user_up_2", 50 * 1024),
            ("user_up_3", 120 * 1024),
        ]

        def upload_worker(uname: str, size: int) -> str:
            src = Path(self.temp_dir) / f"{uname}_data.bin"
            payload = os.urandom(size)
            src.write_bytes(payload)
            sha = hashlib.sha256(payload).hexdigest()

            with self.create_client() as client:
                client.register(uname, f"Pass_{uname}!")
                ok, msg = client.upload_file(src)
                self.assertTrue(ok, msg)

            return sha

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                u: executor.submit(upload_worker, u, sz) for u, sz in users_and_sizes
            }
            results = {u: f.result() for u, f in futures.items()}

        for uname, expected_sha in results.items():
            saved = list((self.uploads_dir / uname).glob(f"*{uname}_data.bin"))
            self.assertEqual(len(saved), 1)
            actual_sha = hashlib.sha256(saved[0].read_bytes()).hexdigest()
            self.assertEqual(actual_sha, expected_sha)

    def test_tier4_complete_user_lifecycle(self) -> None:
        """Ciclo completo: recusa sem login -> cadastro -> mensagem -> upload -> retorno."""
        file_path = Path(self.temp_dir) / "lifecycle.dat"
        file_path.write_bytes(b"Dados do ciclo completo")

        with self.create_client() as client:
            # 1. Tentativa sem login é recusada
            ok_pre, _ = client.send_message("Não autorizado")
            self.assertFalse(ok_pre)

            # 2. Cadastro de conta
            ok_reg, _ = client.register("lifecycle_user", "LifecyclePass123!")
            self.assertTrue(ok_reg)
            self.wait_for_user_status("lifecycle_user", "online")

            # 3. Envio de mensagem
            ok_msg, _ = client.send_message("Primeiro sinal no ciclo de vida")
            self.assertTrue(ok_msg)

            # 4. Upload de mídia
            ok_up, _ = client.upload_file(file_path)
            self.assertTrue(ok_up)

            # 5. Logout voluntário
            ok_out, _ = LogoutCommand().execute(client.control_conn)
            self.assertTrue(ok_out)
            self.wait_for_user_status("lifecycle_user", "offline")
            client.close()

            # 6. Re-login
            ok_in, _ = client.login("lifecycle_user", "LifecyclePass123!")
            self.assertTrue(ok_in)
            self.wait_for_user_status("lifecycle_user", "online")

        # 7. Queda com fechamento do socket
        self.wait_for_user_status("lifecycle_user", "offline")

        # 8. Reconexão e mensagem final
        with self.create_client() as client_reconnected:
            ok_relogin, _ = client_reconnected.login("lifecycle_user", "LifecyclePass123!")
            self.assertTrue(ok_relogin)
            ok_final, _ = client_reconnected.send_message("Sessão finalizada com sucesso!")
            self.assertTrue(ok_final)

        log_content = self.log_path.read_text(encoding="utf-8")
        self.assertIn("Primeiro sinal no ciclo de vida", log_content)
        self.assertIn("Sessão finalizada com sucesso!", log_content)

    def test_tier4_cli_subprocess_execution(self) -> None:
        """Execução real do cliente como subprocesso do SO (python3 -m app.client)."""
        # 1. Registra usuário via interface pública e gera arquivo de sessão válido
        with self.create_client() as c_init:
            ok_init, _ = c_init.register("cli_subp_user", "CliPassword123!")
            self.assertTrue(ok_init)
            sess = Session.create(
                "cli_subp_user", c_init.secret_hash or "", is_already_derived=True
            )
            sess.save(self.session_path)

        # 2. Cria arquivo .env customizado com os parâmetros das portas efêmeras
        custom_env = Path(self.temp_dir) / "client.env"
        env_content = (
            f"HOMELAB_CLIENT_TARGET_HOST=127.0.0.1\n"
            f"HOMELAB_CONTROL_PORT={self.server.control_port}\n"
            f"HOMELAB_DATA_PORT={self.server.data_port}\n"
            f"HOMELAB_SESSION_PATH={self.session_path}\n"
        )
        custom_env.write_text(env_content, encoding="utf-8")

        # 3. Executa o cliente via subprocesso interagindo com o menu via stdin ("1\ns\n")
        proc_env = os.environ.copy()
        proc_env["PYTHONPATH"] = str(Path.cwd())

        cmd = [
            sys.executable,
            "-m",
            "app.client",
            "--env-file",
            str(custom_env),
            "-m",
            "Mensagem enviada via CLI Subprocess E2E!",
        ]

        result = subprocess.run(
            cmd,
            input="1\ns\n",
            capture_output=True,
            text=True,
            env=proc_env,
            timeout=8.0,
        )

        self.assertEqual(
            result.returncode,
            0,
            f"CLI Subprocess falhou (code {result.returncode}). Stderr: {result.stderr}",
        )
        self.assertIn("Resposta do servidor", result.stdout)

        # 4. Confirma gravação da mensagem no log do servidor
        log_content = self.log_path.read_text(encoding="utf-8")
        self.assertIn("cli_subp_user@", log_content)
        self.assertIn("Mensagem enviada via CLI Subprocess E2E!", log_content)


if __name__ == "__main__":
    unittest.main()
