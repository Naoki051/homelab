#!/usr/bin/env python3
"""
Testes automatizados para Protocolo, Banco de Dados e Sessão do Homelab
"""

from datetime import datetime, timedelta
from pathlib import Path
import shutil
import tempfile
import unittest

from app.client_session import Session
from app.database import ClientRepository, hash_password, verify_password
from app.protocol import Message


class TestProtocolMessage(unittest.TestCase):
    def test_message_serialization(self):
        msg = Message(
            action=Message.ACTION_LOGIN,
            payload={"username": "user1", "password": "secret_hash"},
        )
        json_str = msg.to_json()
        recovered = Message.from_json(json_str)

        self.assertEqual(recovered.action, Message.ACTION_LOGIN)
        self.assertEqual(recovered.payload["username"], "user1")
        self.assertEqual(recovered.payload["password"], "secret_hash")
        self.assertIsNotNone(recovered.timestamp)

    def test_message_bytes_and_response(self):
        resp = Message.response(
            status=Message.STATUS_OK,
            message="Operação concluída",
            extra={"client_id": 42},
        )
        data_bytes = resp.to_bytes()
        recovered = Message.from_bytes(data_bytes)

        self.assertEqual(recovered.action, Message.ACTION_RESPONSE)
        self.assertEqual(recovered.payload["status"], "ok")
        self.assertEqual(recovered.payload["client_id"], 42)


class TestClientDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_homelab.db"
        self.repo = ClientRepository(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_password_hashing(self):
        pwd = "minhasenhasecreta"
        hashed = hash_password(pwd)
        self.assertTrue(verify_password(pwd, hashed))
        self.assertFalse(verify_password("senhaerrada", hashed))

    def test_client_registration_and_duplicate_error(self):
        ok, msg, client = self.repo.register("naoki", "segredo123")
        self.assertTrue(ok)
        self.assertIsNotNone(client)
        self.assertEqual(client.username, "naoki")
        self.assertEqual(client.status, "offline")
        self.assertIsNotNone(client.created_at)

        # Tentativa de duplicado deve falhar
        ok2, msg2, client2 = self.repo.register("naoki", "outrasenha")
        self.assertFalse(ok2)
        self.assertIn("já existe", msg2)
        self.assertIsNone(client2)

    def test_client_authentication_requires_explicit_account(self):
        # Usuário inexistente deve falhar (não cria conta automaticamente)
        ok, msg, client = self.repo.authenticate("fantasma", "senha")
        self.assertFalse(ok)
        self.assertIn("não encontrado", msg)
        self.assertIsNone(client)

        # Cadastra explicitamente
        self.repo.register("usuario_valido", "senha123")

        # Senha errada
        ok_err, msg_err, _ = self.repo.authenticate("usuario_valido", "senha_errada")
        self.assertFalse(ok_err)
        self.assertIn("Senha incorreta", msg_err)

        # Senha correta
        ok_succ, msg_succ, client_succ = self.repo.authenticate("usuario_valido", "senha123")
        self.assertTrue(ok_succ)
        self.assertIsNotNone(client_succ)
        self.assertEqual(client_succ.username, "usuario_valido")

    def test_update_status_and_presence(self):
        self.repo.register("status_user", "segredo")
        self.repo.update_status("status_user", "online")

        client = self.repo.get_by_username("status_user")
        self.assertEqual(client.status, "online")
        self.assertIsNotNone(client.last_seen)

        self.repo.update_status("status_user", "offline")
        client_off = self.repo.get_by_username("status_user")
        self.assertEqual(client_off.status, "offline")


class TestClientSessionStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.session_path = Path(self.temp_dir) / "client_session.json"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_session_lifecycle_and_validity(self):
        # Cria sessão com 7 dias de validade
        session = Session.create("naoki", "senha_bruta", is_already_derived=False, days=7)
        self.assertTrue(session.is_valid())
        self.assertNotEqual(session.last_password, "senha_bruta")  # Não deve ser texto puro

        # Salva em arquivo
        session.save(path=self.session_path)
        self.assertTrue(self.session_path.exists())

        # Carrega do arquivo
        loaded = Session.load(path=self.session_path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.last_username, "naoki")
        self.assertEqual(loaded.last_password, session.last_password)
        self.assertTrue(loaded.is_valid())

    def test_expired_session(self):
        # Sessão expirada no passado
        past_time = (datetime.now() - timedelta(hours=1)).isoformat()
        expired_session = Session("antigo", "hash_qualquer", expire_date_time=past_time)
        self.assertFalse(expired_session.is_valid())
        self.assertEqual(expired_session.time_remaining(), "expirada")


if __name__ == "__main__":
    unittest.main()
