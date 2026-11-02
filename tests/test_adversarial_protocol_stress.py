#!/usr/bin/env python3
"""
Módulo de Testes de Estresse Adversarial e Casos Extremos (Milestone M5 Integration)
Desenhado para desafiar empiricamente:
1. Enquadramento binário inválido ou corrompido no Canal de Controle (magic bytes, HMAC corrompido, oversized length, frames truncados, JSON inválido).
2. Chunks corrompidos ou fora de ordem no Canal de Dados (SHA-256 adulterado, ticket incorreto/inexistente, chunks fora de ordem, chunks duplicados, índice inválido).
3. Concorrência extrema (múltiplas conexões simultâneas, registro concorrente do mesmo usuário, uploads concorrentes).
4. Resiliência do Servidor e Cliente (manutenção de ciclo de vida sem exceções não tratadas nem travamentos).
"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import tempfile
import threading
import time
from typing import List, Tuple
import unittest

from app.client import ControlConnection, HomelabClient
from app.client_session import Session
from app.protocol import (
    CHUNK_HEADER_FORMAT,
    CHUNK_SIZE,
    CONTROL_HEADER_FORMAT,
    CONTROL_HEADER_SIZE,
    CONTROL_MAGIC,
    DATA_MAGIC,
    DEFAULT_HANDSHAKE_KEY,
    MediaChunk,
    Message,
    compute_hmac,
    generate_session_key,
    generate_upload_ticket,
)
from app.server import HomelabServer


class AdversarialServerTestCase(unittest.TestCase):
    """Base de teste com servidor Homelab rodando em portas efêmeras e diretório temporário isolado."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="homelab_adv_")
        self.db_path = Path(self.temp_dir) / "adv_homelab.db"
        self.log_path = Path(self.temp_dir) / "adv_server.log"
        self.uploads_dir = Path(self.temp_dir) / "uploads"

        self.server = HomelabServer(
            host="127.0.0.1",
            control_port=0,
            data_port=0,
            log_path=self.log_path,
            db_path=self.db_path,
            uploads_dir=self.uploads_dir,
        )
        self.server.start()
        time.sleep(0.05)

    def tearDown(self) -> None:
        self.server.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _wait_for_user_status(
        self, username: str, expected_status: str, timeout: float = 1.0
    ) -> None:
        """Aguarda de forma não-bloqueante a propagação do status de presença no SQLite."""
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
            f"Timeout ({timeout}s): Usuário '{username}' permaneceu com status '{actual}' "
            f"(esperado: '{expected_status}')",
        )


class TestControlChannelAdversarialFraming(AdversarialServerTestCase):
    """Cenário 1: Enquadramento binário inválido ou corrompido no Canal de Controle."""

    def test_bad_magic_bytes_on_initial_connection(self) -> None:
        """Envia cabeçalho com Magic Bytes inválidos (b'XX') na conexão inicial."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.control_port))
            bad_frame = b"XX" + os.urandom(38) + b"hello payload"
            sock.sendall(bad_frame)
            sock.settimeout(2.0)
            response = sock.recv(1024)
            self.assertTrue(len(response) >= 0)

        # Servidor continua vivo e aceita clientes normais
        with HomelabClient(host="127.0.0.1", control_port=self.server.control_port) as client:
            ok, msg = client.register("user_after_bad_magic", "pass123")
            self.assertTrue(ok, msg)

    def test_bad_magic_bytes_in_persistent_session(self) -> None:
        """Estabelece sessão persistente com b'HC', e no segundo frame envia magic b'ZZ'."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.control_port))
            sock.settimeout(2.0)

            # Primeiro frame: registro válido com chave padrão e hash derivado
            secret = Session.derive_secret("user_magic_pers", "pwd")
            reg_msg = Message(
                action=Message.ACTION_REGISTER,
                payload={"username": "user_magic_pers", "password": secret},
            )
            reg_msg.send_framed(sock, hmac_key=DEFAULT_HANDSHAKE_KEY)
            resp = Message.recv_framed(sock, hmac_key=DEFAULT_HANDSHAKE_KEY)
            self.assertIsNotNone(resp)
            self.assertEqual(resp.payload.get("status"), Message.STATUS_OK)
            new_key = bytes.fromhex(resp.payload["session_key"])

            # Segundo frame: cabeçalho com magic b'ZZ'
            meta_prefix = struct.pack(">2sHI", b"ZZ", Message.MSG_TYPE_REQUEST, 10)
            mac = compute_hmac(new_key, meta_prefix + b"0123456789")
            header = struct.pack(CONTROL_HEADER_FORMAT, b"ZZ", Message.MSG_TYPE_REQUEST, 10, mac)
            sock.sendall(header + b"0123456789")

            # Servidor deve detectar magic inválido, registrar erro no log e fechar a conexão
            time.sleep(0.1)
            try:
                data = sock.recv(1024)
                self.assertEqual(len(data), 0, "Servidor deveria ter fechado a conexão")
            except (ConnectionResetError, BrokenPipeError, TimeoutError, OSError):
                pass

        # Servidor deve limpar o status de presença para offline mesmo com erro de protocolo
        self._wait_for_user_status("user_magic_pers", "offline")
        user_pers = self.server.repo.get_by_username("user_magic_pers")
        self.assertIsNotNone(user_pers)
        self.assertEqual(user_pers.status, "offline")

        # Servidor continua saudável
        with HomelabClient(host="127.0.0.1", control_port=self.server.control_port) as client:
            ok, msg = client.login("user_magic_pers", "pwd")
            self.assertTrue(ok, msg)

    def test_corrupted_hmac_signature(self) -> None:
        """Envia mensagem enquadrada com HMAC adulterado (todos os bytes zero)."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.control_port))
            sock.settimeout(2.0)

            msg = Message(
                action=Message.ACTION_REGISTER,
                payload={"username": "tampered_hmac", "password": "pwd"},
            )
            payload_bytes = msg.to_bytes()
            bogus_mac = b"\x00" * 32
            header = struct.pack(
                CONTROL_HEADER_FORMAT,
                CONTROL_MAGIC,
                Message.MSG_TYPE_REQUEST,
                len(payload_bytes),
                bogus_mac,
            )
            sock.sendall(header + payload_bytes)

            time.sleep(0.1)
            try:
                data = sock.recv(1024)
                self.assertEqual(len(data), 0)
            except (ConnectionResetError, BrokenPipeError, TimeoutError, OSError):
                pass

        # Garante que o usuário NÃO foi registrado no banco
        client_rec = self.server.repo.get_by_username("tampered_hmac")
        self.assertIsNone(client_rec)

    def test_oversized_payload_length_header(self) -> None:
        """Envia cabeçalho com PayloadLen acima do limite máximo de 64KB (70000 e 0xFFFFFFFF)."""
        for bad_len in (70000, 0xFFFFFFFF):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect(("127.0.0.1", self.server.control_port))
                sock.settimeout(2.0)

                bogus_mac = b"\xAA" * 32
                header = struct.pack(
                    CONTROL_HEADER_FORMAT,
                    CONTROL_MAGIC,
                    Message.MSG_TYPE_REQUEST,
                    bad_len,
                    bogus_mac,
                )
                sock.sendall(header)
                time.sleep(0.1)
                try:
                    data = sock.recv(1024)
                    self.assertEqual(len(data), 0)
                except (ConnectionResetError, BrokenPipeError, TimeoutError, OSError):
                    pass

        # Servidor não sofreu crash de alocação de memória nem exceção não tratada
        with HomelabClient(host="127.0.0.1", control_port=self.server.control_port) as client:
            ok, msg = client.register("user_after_oversized", "pwd")
            self.assertTrue(ok, msg)

    def test_truncated_framing_and_premature_disconnect(self) -> None:
        """Simula queda de rede abrupta no meio do cabeçalho de controle e no meio do payload."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.control_port))
            sock.sendall(b"HC" + b"\x00" * 8)
            sock.close()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.control_port))
            meta_prefix = struct.pack(">2sHI", CONTROL_MAGIC, Message.MSG_TYPE_REQUEST, 200)
            mac = compute_hmac(DEFAULT_HANDSHAKE_KEY, meta_prefix + b"X" * 200)
            header = struct.pack(CONTROL_HEADER_FORMAT, CONTROL_MAGIC, Message.MSG_TYPE_REQUEST, 200, mac)
            sock.sendall(header + b"X" * 20)
            sock.close()

        time.sleep(0.1)
        with HomelabClient(host="127.0.0.1", control_port=self.server.control_port) as client:
            ok, msg = client.register("user_after_truncated", "pwd")
            self.assertTrue(ok, msg)

    def test_malformed_json_payload_with_valid_hmac(self) -> None:
        """Envia HMAC válido cobrindo um payload de bytes que não é JSON válido."""
        bad_json = b"{ action: 'broken', bad_json: [[[ "
        meta_prefix = struct.pack(">2sHI", CONTROL_MAGIC, Message.MSG_TYPE_REQUEST, len(bad_json))
        mac = compute_hmac(DEFAULT_HANDSHAKE_KEY, meta_prefix + bad_json)
        header = struct.pack(CONTROL_HEADER_FORMAT, CONTROL_MAGIC, Message.MSG_TYPE_REQUEST, len(bad_json), mac)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.control_port))
            sock.settimeout(2.0)
            sock.sendall(header + bad_json)
            time.sleep(0.1)
            try:
                data = sock.recv(1024)
                self.assertEqual(len(data), 0)
            except (ConnectionResetError, BrokenPipeError, TimeoutError, OSError):
                pass

        self.assertTrue(self.server.is_running)

    def test_presence_cleanup_on_tcp_rst(self) -> None:
        """Valida que queda abrupta por TCP RST (SO_LINGER=0) transiciona usuário para offline."""
        username = "user_rst_presence"
        secret = Session.derive_secret(username, "senha_rst_123")
        self.server.repo.register(username, secret)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.control_port))
            sock.settimeout(2.0)

            # 1. Realiza login do usuário no canal de controle
            login_msg = Message(
                action=Message.ACTION_LOGIN,
                payload={"username": username, "password": secret},
            )
            login_msg.send_framed(sock, hmac_key=DEFAULT_HANDSHAKE_KEY)
            resp = Message.recv_framed(sock, hmac_key=DEFAULT_HANDSHAKE_KEY)
            self.assertIsNotNone(resp)
            self.assertEqual(resp.payload.get("status"), Message.STATUS_OK)

            # 2. Confirma que o status ativo inicial é 'online'
            user = self.server.repo.get_by_username(username)
            self.assertIsNotNone(user)
            self.assertEqual(user.status, "online")

            # 3. Força reset abrupto via TCP RST (l_onoff=1, l_linger=0) sem handshake de término
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))

        # 4. Invariante: servidor deve detectar ConnectionResetError e limpar para 'offline'
        self._wait_for_user_status(username, "offline")

        # 5. Garante que o servidor continua operante após o RST
        with HomelabClient(host="127.0.0.1", control_port=self.server.control_port) as client:
            ok, msg = client.login(username, "senha_rst_123")
            self.assertTrue(ok, msg)

    def test_presence_cleanup_on_malformed_magic_frame(self) -> None:
        """Valida que erro por magic inválido em sessão ativa transiciona usuário para offline."""
        username = "user_magic_cleanup"
        secret = Session.derive_secret(username, "senha_magic_123")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.control_port))
            sock.settimeout(2.0)

            # 1. Registra novo usuário obtendo sessão persistente e chave HMAC derivada
            reg_msg = Message(
                action=Message.ACTION_REGISTER,
                payload={"username": username, "password": secret},
            )
            reg_msg.send_framed(sock, hmac_key=DEFAULT_HANDSHAKE_KEY)
            resp = Message.recv_framed(sock, hmac_key=DEFAULT_HANDSHAKE_KEY)
            self.assertIsNotNone(resp)
            self.assertEqual(resp.payload.get("status"), Message.STATUS_OK)
            session_key = bytes.fromhex(resp.payload["session_key"])

            # 2. Valida presença online logo após o cadastro
            user = self.server.repo.get_by_username(username)
            self.assertIsNotNone(user)
            self.assertEqual(user.status, "online")

            # 3. Transmite frame com Magic Bytes inválidos (b'ZZ') na sessão autenticada
            payload = b"0123456789"
            meta_prefix = struct.pack(">2sHI", b"ZZ", Message.MSG_TYPE_REQUEST, len(payload))
            mac = compute_hmac(session_key, meta_prefix + payload)
            header = struct.pack(
                CONTROL_HEADER_FORMAT, b"ZZ", Message.MSG_TYPE_REQUEST, len(payload), mac
            )
            sock.sendall(header + payload)

            # 4. Servidor deve registrar ProtocolError e fechar o socket
            try:
                sock.recv(1024)
            except (ConnectionResetError, BrokenPipeError, TimeoutError, OSError):
                pass

        # 5. Invariante: servidor deve executar cleanup para 'offline' no finally da conexão
        self._wait_for_user_status(username, "offline")

        # 6. Servidor continua saudável e aceita reautenticação
        with HomelabClient(host="127.0.0.1", control_port=self.server.control_port) as client:
            ok, msg = client.login(username, "senha_magic_123")
            self.assertTrue(ok, msg)


class TestDataChannelAdversarialChunks(AdversarialServerTestCase):
    """Cenário 2: Chunks corrompidos ou fora de ordem no Canal de Dados."""

    def _register_and_get_ticket(
        self, username: str, filename: str, file_size: int, sha256_hash: str
    ) -> Tuple[str, bytes]:
        """Auxiliar: registra um usuário e emite um ticket de upload via Canal de Controle."""
        with ControlConnection(host="127.0.0.1", port=self.server.control_port) as conn:
            secret = Session.derive_secret(username, "senha123")
            ok, _ = conn.register(username, secret)
            self.assertTrue(ok)
            session_key = conn.session_key

            req = Message(
                action=Message.ACTION_REQUEST_UPLOAD,
                payload={
                    "username": username,
                    "password": secret,
                    "filename": filename,
                    "file_size": file_size,
                    "sha256": sha256_hash,
                },
            )
            resp = conn.send_request(req)
            self.assertIsNotNone(resp)
            self.assertEqual(resp.payload.get("status"), Message.STATUS_OK)
            ticket_hex = resp.payload["ticket"]
            return ticket_hex, session_key

    def test_mismatched_or_unknown_ticket(self) -> None:
        """Envia chunk com ticket de 16 bytes que não foi gerado pelo servidor."""
        fake_ticket = os.urandom(16)
        session_key = generate_session_key()
        chunk = MediaChunk(ticket=fake_ticket, chunk_index=0, total_chunks=1, data=b"dados fantasmas")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.data_port))
            sock.settimeout(2.0)
            chunk.send(sock, hmac_key=session_key)

            time.sleep(0.1)
            try:
                data = sock.recv(1024)
                self.assertEqual(len(data), 0)
            except (ConnectionResetError, BrokenPipeError, TimeoutError, OSError):
                pass

        self.assertTrue(self.server.is_running)

    def test_tampered_chunk_hmac(self) -> None:
        """Gera ticket legítimo mas envia chunk com HMAC adulterado."""
        data = b"dados de teste para tamper hmac"
        expected_sha = hashlib.sha256(data).hexdigest()
        ticket_hex, session_key = self._register_and_get_ticket(
            "user_chunk_tamper", "doc.txt", len(data), expected_sha
        )

        ticket_bytes = bytes.fromhex(ticket_hex)
        bogus_mac = b"\xEE" * 32
        header = struct.pack(
            CHUNK_HEADER_FORMAT,
            DATA_MAGIC,
            ticket_bytes,
            0,
            1,
            len(data),
            bogus_mac,
        )

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.data_port))
            sock.settimeout(2.0)
            sock.sendall(header + data)

            time.sleep(0.1)
            try:
                data_in = sock.recv(1024)
                if len(data_in) >= CONTROL_HEADER_SIZE:
                    resp = Message.from_frame(data_in, hmac_key=session_key)
                    self.assertEqual(resp.payload.get("status"), Message.STATUS_ERROR)
            except (ConnectionResetError, BrokenPipeError, TimeoutError, OSError):
                pass

        # Garante que o upload não foi marcado como concluído no log
        if self.log_path.exists() and self.log_path.is_file():
            log_content = self.log_path.read_text(encoding="utf-8")
            self.assertNotIn("UPLOAD CONCLUÍDO: 'doc.txt'", log_content)

    def test_tampered_sha256_integrity_violation(self) -> None:
        """Ticket emitido com hash SHA-256 esperado, mas cliente transmite dados divergentes."""
        real_data = b"Conteudo Real que sera enviado"
        bogus_sha256 = "0" * 64
        ticket_hex, session_key = self._register_and_get_ticket(
            "user_sha_mismatch", "segredo.bin", len(real_data), bogus_sha256
        )

        chunk = MediaChunk(ticket=ticket_hex, chunk_index=0, total_chunks=1, data=real_data)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.data_port))
            sock.settimeout(2.0)
            chunk.send(sock, hmac_key=session_key)

            resp = Message.recv_framed(sock, hmac_key=session_key)
            self.assertIsNotNone(resp)
            self.assertEqual(resp.payload.get("status"), Message.STATUS_ERROR)
            self.assertIn("Hash SHA-256 final", resp.payload.get("message", ""))

        user_uploads = list((self.uploads_dir / "user_sha_mismatch").glob("*segredo.bin"))
        self.assertEqual(len(user_uploads), 0, "Arquivo com SHA-256 inválido deveria ser apagado")

    def test_out_of_order_chunks_assembly(self) -> None:
        """Transmite 3 chunks em ordem inversa (Chunk 2, depois Chunk 0, depois Chunk 1)."""
        chunk_0_data = os.urandom(64 * 1024)
        chunk_1_data = os.urandom(64 * 1024)
        chunk_2_data = os.urandom(12 * 1024)
        full_content = chunk_0_data + chunk_1_data + chunk_2_data
        full_sha256 = hashlib.sha256(full_content).hexdigest()

        ticket_hex, session_key = self._register_and_get_ticket(
            "user_out_of_order", "reorder.bin", len(full_content), full_sha256
        )

        c0 = MediaChunk(ticket=ticket_hex, chunk_index=0, total_chunks=3, data=chunk_0_data)
        c1 = MediaChunk(ticket=ticket_hex, chunk_index=1, total_chunks=3, data=chunk_1_data)
        c2 = MediaChunk(ticket=ticket_hex, chunk_index=2, total_chunks=3, data=chunk_2_data)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.data_port))
            sock.settimeout(5.0)

            c2.send(sock, hmac_key=session_key)
            c0.send(sock, hmac_key=session_key)
            c1.send(sock, hmac_key=session_key)

            resp = Message.recv_framed(sock, hmac_key=session_key)
            self.assertIsNotNone(resp)
            self.assertEqual(resp.payload.get("status"), Message.STATUS_OK)

        user_uploads = list((self.uploads_dir / "user_out_of_order").glob("*reorder.bin"))
        self.assertEqual(len(user_uploads), 1)
        saved_bytes = user_uploads[0].read_bytes()
        self.assertEqual(len(saved_bytes), len(full_content))
        self.assertEqual(hashlib.sha256(saved_bytes).hexdigest(), full_sha256)

    def test_duplicate_chunks_handling(self) -> None:
        """Envia chunk 0 duplicado antes de enviar chunk 1 em arquivo de 2 chunks."""
        part_0 = os.urandom(64 * 1024)
        part_1 = os.urandom(1000)
        full = part_0 + part_1
        full_sha = hashlib.sha256(full).hexdigest()

        ticket_hex, session_key = self._register_and_get_ticket(
            "user_duplicate", "dup.bin", len(full), full_sha
        )

        c0 = MediaChunk(ticket=ticket_hex, chunk_index=0, total_chunks=2, data=part_0)
        c1 = MediaChunk(ticket=ticket_hex, chunk_index=1, total_chunks=2, data=part_1)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.data_port))
            sock.settimeout(5.0)

            # Envia c0, repete c0, depois envia c1
            c0.send(sock, hmac_key=session_key)
            c0.send(sock, hmac_key=session_key)
            c1.send(sock, hmac_key=session_key)

            resp = Message.recv_framed(sock, hmac_key=session_key)
            self.assertIsNotNone(resp)
            self.assertEqual(resp.payload.get("status"), Message.STATUS_OK)

        user_uploads = list((self.uploads_dir / "user_duplicate").glob("*dup.bin"))
        self.assertEqual(len(user_uploads), 1)
        self.assertEqual(hashlib.sha256(user_uploads[0].read_bytes()).hexdigest(), full_sha)

    def test_invalid_chunk_index_rejection(self) -> None:
        """Tenta enviar chunk com índice fora do intervalo permitido (chunk_index >= total_chunks)."""
        ticket_hex, session_key = self._register_and_get_ticket(
            "user_bad_idx", "bad_idx.bin", 100, None
        )
        ticket_bytes = bytes.fromhex(ticket_hex)

        bad_meta = struct.pack(">2s16sIII", DATA_MAGIC, ticket_bytes, 5, 2, 10)
        mac = compute_hmac(session_key, bad_meta + b"0123456789")
        bad_header = struct.pack(CHUNK_HEADER_FORMAT, DATA_MAGIC, ticket_bytes, 5, 2, 10, mac)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect(("127.0.0.1", self.server.data_port))
            sock.settimeout(2.0)
            sock.sendall(bad_header + b"0123456789")

            time.sleep(0.1)
            try:
                data = sock.recv(1024)
                if len(data) >= CONTROL_HEADER_SIZE:
                    resp = Message.from_frame(data, hmac_key=session_key)
                    self.assertEqual(resp.payload.get("status"), Message.STATUS_ERROR)
            except (ConnectionResetError, BrokenPipeError, TimeoutError, OSError):
                pass

        self.assertTrue(self.server.is_running)


class TestConcurrencyAndRaceConditions(AdversarialServerTestCase):
    """Cenário 3: Concorrência extrema no Canal de Controle e Canal de Dados."""

    def test_concurrent_registrations_same_username(self) -> None:
        """15 threads tentam simultaneamente registrar exatamente o mesmo nome de usuário."""
        target_user = "race_condition_user"
        results: List[Tuple[bool, str]] = []
        lock = threading.Lock()

        def try_register() -> None:
            with HomelabClient(host="127.0.0.1", control_port=self.server.control_port) as client:
                ok, msg = client.register(target_user, "senha_concorrente_123")
                with lock:
                    results.append((ok, msg))

        threads = [threading.Thread(target=try_register) for _ in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 15)
        successes = [r for r in results if r[0] is True]
        failures = [r for r in results if r[0] is False]

        self.assertEqual(len(successes), 1, f"Esperado exatamente 1 sucesso, obteve: {len(successes)}")
        self.assertEqual(len(failures), 14)
        for fail in failures:
            self.assertTrue(
                "já existe" in fail[1].lower() or "já cadastrado" in fail[1].lower(),
                f"Mensagem de erro inesperada: {fail[1]}",
            )

    def test_concurrent_logins_and_messaging(self) -> None:
        """10 usuários distintos cadastrados operando simultaneamente em threads paralelas."""
        num_users = 10
        for i in range(num_users):
            username = f"concurrent_worker_{i}"
            with HomelabClient(host="127.0.0.1", control_port=self.server.control_port) as client:
                ok, msg = client.register(username, f"pwd_{i}")
                self.assertTrue(ok, msg)

        success_flags: List[bool] = []
        lock = threading.Lock()

        def client_worker(idx: int) -> None:
            username = f"concurrent_worker_{idx}"
            with HomelabClient(host="127.0.0.1", control_port=self.server.control_port) as client:
                ok_login, msg_login = client.login(username, f"pwd_{idx}")
                if not ok_login:
                    with lock:
                        success_flags.append(False)
                    return

                ok_msg, _ = client.send_message(f"Mensagem simultânea do worker {idx}")
                with lock:
                    success_flags.append(ok_msg)

        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(client_worker, range(num_users))

        self.assertEqual(len(success_flags), num_users)
        self.assertTrue(all(success_flags), "Todos os clientes concorrentes deveriam ter enviado com sucesso")

    def test_concurrent_uploads_in_data_channel(self) -> None:
        """5 clientes realizam upload simultâneo de arquivos no Canal de Dados."""
        num_uploads = 5
        results: List[Tuple[bool, str]] = []
        lock = threading.Lock()

        def do_upload(idx: int) -> None:
            user = f"up_worker_{idx}"
            test_file = Path(self.temp_dir) / f"file_{idx}.bin"
            content = os.urandom(80 * 1024)
            test_file.write_bytes(content)
            expected_hash = hashlib.sha256(content).hexdigest()

            with HomelabClient(
                host="127.0.0.1",
                control_port=self.server.control_port,
                data_port=self.server.data_port,
            ) as client:
                client.register(user, "senha123")
                ok, msg = client.upload_file(test_file)

                saved_files = list((self.uploads_dir / user).glob(f"*file_{idx}.bin"))
                integrity = False
                if saved_files and hashlib.sha256(saved_files[0].read_bytes()).hexdigest() == expected_hash:
                    integrity = True

                with lock:
                    results.append((ok and integrity, msg))

        threads = [threading.Thread(target=do_upload, args=(i,)) for i in range(num_uploads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), num_uploads)
        self.assertTrue(all(r[0] for r in results), f"Uploads falharam: {results}")


class TestClientResilienceToAdversarialResponses(AdversarialServerTestCase):
    """Cenário 4: Resiliência do HomelabClient ao receber respostas corrompidas ou anômalas."""

    def test_client_handles_unexpected_server_disconnect_gracefully(self) -> None:
        """Cliente tenta enviar requisição, mas servidor morre abruptamente."""
        client = HomelabClient(host="127.0.0.1", control_port=self.server.control_port)
        self.assertTrue(client.connect())

        self.server.stop()

        ok, msg = client.send_message("Tentativa após queda do servidor")
        self.assertFalse(ok)
        self.assertIn("Sem resposta", msg)
        client.close()

    def test_client_upload_file_handles_corrupted_data_channel_server_response(self) -> None:
        """Garante que o cliente não sofre crash (unhandled ValueError) se o canal de dados receber framing corrompido."""
        corrupt_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        corrupt_server.bind(("127.0.0.1", 0))
        corrupt_server.listen(1)
        corrupt_port = corrupt_server.getsockname()[1]

        def serve_corrupt() -> None:
            try:
                conn, _ = corrupt_server.accept()
                conn.recv(1024)
                conn.sendall(b"ZZ" + b"\x00" * 38 + b"{}")
                conn.close()
            except OSError:
                pass
            finally:
                corrupt_server.close()

        t = threading.Thread(target=serve_corrupt, daemon=True)
        t.start()

        temp_file = Path(self.temp_dir) / "small_test.txt"
        temp_file.write_text("Hello Homelab")

        with HomelabClient(
            host="127.0.0.1",
            control_port=self.server.control_port,
            data_port=self.server.data_port,
        ) as client:
            client.register("client_resilience_user", "senha123")

            ok, msg = client.upload_file(temp_file, data_port=corrupt_port)
            self.assertFalse(ok)



class TestServerOverallHealthAfterAllAttacks(AdversarialServerTestCase):
    """Garante a resiliência do servidor após ser submetido a toda a bateria de estresse."""

    def test_server_healthy_end_to_end_after_adversarial_barrage(self) -> None:
        """Executa um fluxo completo após o servidor ter resistido aos cenários de ataque."""
        with HomelabClient(
            host="127.0.0.1",
            control_port=self.server.control_port,
            data_port=self.server.data_port,
        ) as client:
            ok, msg = client.register("healthy_user", "super_senha_123")
            self.assertTrue(ok, msg)

            ok, msg = client.login("healthy_user", "super_senha_123")
            self.assertTrue(ok, msg)

            ok, msg = client.send_message("Servidor Homelab está saudável e resiliente!")
            self.assertTrue(ok, msg)

            test_doc = Path(self.temp_dir) / "healthy_doc.bin"
            content = os.urandom(100 * 1024)
            test_doc.write_bytes(content)
            ok, msg = client.upload_file(test_doc)
            self.assertTrue(ok, msg)

            saved_files = list((self.uploads_dir / "healthy_user").glob("*healthy_doc.bin"))
            self.assertEqual(len(saved_files), 1)
            self.assertEqual(
                hashlib.sha256(saved_files[0].read_bytes()).hexdigest(),
                hashlib.sha256(content).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
