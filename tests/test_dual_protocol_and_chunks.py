#!/usr/bin/env python3
"""
Testes automatizados para os Dois Protocolos de Comunicação:
1. Protocolo de Controle (Framing Binário de 40B + HMAC-SHA256 com chave dinâmica e conexão TCP persistente)
2. Protocolo de Dados/Mídia (Chunks Indexados de 64KB + Cabeçalho de 62B + HMAC-SHA256 e streaming para disco)
"""

import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from app.client import ControlConnection
from app.client_session import Session
from app.protocol import (
    CHUNK_HEADER_SIZE,
    CHUNK_SIZE,
    CONTROL_HEADER_SIZE,
    DEFAULT_HANDSHAKE_KEY,
    MediaChunk,
    Message,
    generate_session_key,
    generate_upload_ticket,
)
from app.server import DualChannelServer


class TestControlFramingAndHMAC(unittest.TestCase):
    def test_frame_pack_and_unpack_with_session_key(self):
        session_key = generate_session_key()
        msg = Message(
            action=Message.ACTION_SEND,
            payload={"username": "naoki", "text": "Mensagem com framing binário e HMAC"},
        )

        frame_bytes = msg.to_frame(hmac_key=session_key)
        self.assertGreater(len(frame_bytes), CONTROL_HEADER_SIZE)
        self.assertEqual(frame_bytes[:2], b"HC")

        recovered = Message.from_frame(frame_bytes, hmac_key=session_key)
        self.assertEqual(recovered.action, Message.ACTION_SEND)
        self.assertEqual(recovered.payload["username"], "naoki")
        self.assertEqual(recovered.payload["text"], "Mensagem com framing binário e HMAC")

    def test_frame_rejects_tampered_payload_or_wrong_key(self):
        session_key = generate_session_key()
        wrong_key = generate_session_key()
        msg = Message(action=Message.ACTION_SEND, payload={"text": "Integridade garantida"})
        frame_bytes = msg.to_frame(hmac_key=session_key)

        # Chave incorreta deve falhar na verificação HMAC
        with self.assertRaises(ValueError):
            Message.from_frame(frame_bytes, hmac_key=wrong_key)

        # Adulteração de 1 byte no payload deve falhar no HMAC
        tampered = bytearray(frame_bytes)
        tampered[-1] ^= 0xFF
        with self.assertRaises(ValueError):
            Message.from_frame(bytes(tampered), hmac_key=session_key)


class TestMediaChunksAndHMAC(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_chunk_serialization_and_tamper_detection(self):
        session_key = generate_session_key()
        ticket = generate_upload_ticket()
        raw_payload = os.urandom(CHUNK_SIZE)  # Exatamente 64 KB (65536 bytes)

        chunk = MediaChunk(ticket=ticket, chunk_index=0, total_chunks=3, data=raw_payload)
        serialized = chunk.to_bytes(hmac_key=session_key)
        self.assertEqual(len(serialized), CHUNK_HEADER_SIZE + CHUNK_SIZE)

        recovered = MediaChunk.from_bytes(serialized, hmac_key=session_key)
        self.assertEqual(recovered.ticket, ticket)
        self.assertEqual(recovered.chunk_index, 0)
        self.assertEqual(recovered.total_chunks, 3)
        self.assertEqual(recovered.data, raw_payload)

        # Adulterar 1 byte nos dados brutos invalida o HMAC do chunk
        corrupted = bytearray(serialized)
        corrupted[CHUNK_HEADER_SIZE + 10] ^= 0x01
        with self.assertRaises(ValueError):
            MediaChunk.from_bytes(bytes(corrupted), hmac_key=session_key)

    def test_slice_file_into_64kb_chunks(self):
        # Cria um arquivo de 150 KB (2 chunks de 64 KB + 1 chunk de 22 KB = 3 chunks)
        file_path = Path(self.temp_dir) / "sample_image.bin"
        original_bytes = os.urandom(150 * 1024)
        file_path.write_bytes(original_bytes)

        ticket = generate_upload_ticket()
        chunks = list(MediaChunk.slice_file(file_path, ticket=ticket, chunk_size=CHUNK_SIZE))

        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].data_length, 65536)
        self.assertEqual(chunks[1].data_length, 65536)
        self.assertEqual(chunks[2].data_length, len(original_bytes) - (2 * 65536))

        reconstructed = b"".join(c.data for c in chunks)
        self.assertEqual(reconstructed, original_bytes)


class TestDualChannelEndToEnd(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "dual_homelab.db"
        self.log_path = Path(self.temp_dir) / "dual_server.log"
        self.uploads_dir = Path(self.temp_dir) / "uploads"

        self.server = DualChannelServer(
            host="127.0.0.1",
            control_port=0,
            data_port=0,
            log_path=self.log_path,
            db_path=self.db_path,
            uploads_dir=self.uploads_dir,
        )
        self.server.start_in_background()

    def tearDown(self):
        self.server.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_persistent_control_and_chunked_file_upload(self):
        secret = Session.derive_secret("naoki_dual", "senha_forte_123")

        with ControlConnection(host="127.0.0.1", port=self.server.control_port) as conn:
            self.assertEqual(conn.session_key, DEFAULT_HANDSHAKE_KEY)

            # 1. Registro com emissão automática de chave de sessão dinâmica
            ok_reg, msg_reg = conn.register("naoki_dual", secret)
            self.assertTrue(ok_reg, msg_reg)
            self.assertNotEqual(conn.session_key, DEFAULT_HANDSHAKE_KEY)
            self.assertEqual(len(conn.session_key), 32)

            # Captura a porta efêmera local do socket do cliente para provar que a conexão é a mesma
            first_local_port = conn.sock.getsockname()[1]

            # 2. Envia múltiplas mensagens de texto na MESMA conexão TCP persistente
            self.assertTrue(conn.send_text("naoki_dual", "Primeira mensagem na sessão persistente"))
            self.assertEqual(conn.sock.getsockname()[1], first_local_port)

            self.assertTrue(conn.send_text("naoki_dual", "Segunda mensagem sem novo handshake TCP"))
            self.assertEqual(conn.sock.getsockname()[1], first_local_port)

            # 3. Cria um arquivo binário de 165 KB (3 chunks de até 64 KB) para upload no Canal de Dados
            source_file = Path(self.temp_dir) / "foto_homelab.png"
            source_bytes = os.urandom(165 * 1024)
            source_file.write_bytes(source_bytes)
            expected_sha256 = hashlib.sha256(source_bytes).hexdigest()

            ok_up, msg_up = conn.upload_file(source_file, data_port=self.server.data_port)
            self.assertTrue(ok_up, msg_up)

            # A conexão de controle permanece intacta após o upload no canal de dados
            self.assertTrue(conn.send_text("naoki_dual", "Mensagem enviada logo após o upload"))
            self.assertEqual(conn.sock.getsockname()[1], first_local_port)

            # 4. Verifica se o arquivo salvo no disco do servidor é idêntico bit a bit
            user_uploads = list((self.uploads_dir / "naoki_dual").glob("*foto_homelab.png"))
            self.assertEqual(len(user_uploads), 1)
            saved_bytes = user_uploads[0].read_bytes()
            self.assertEqual(len(saved_bytes), len(source_bytes))
            self.assertEqual(hashlib.sha256(saved_bytes).hexdigest(), expected_sha256)

        # 5. Após sair do bloco `with`, o cliente envia logout e o status volta para offline
        time.sleep(0.05)
        client_record = self.server.repo.get_by_username("naoki_dual")
        self.assertIsNotNone(client_record)
        self.assertEqual(client_record.status, "offline")


if __name__ == "__main__":
    unittest.main()
