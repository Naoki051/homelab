#!/usr/bin/env python3
"""
Testes automatizados para Protocolo, Banco de Dados, Sessão e Integração de Rede do Homelab
"""

from datetime import datetime, timedelta
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import time
import unittest

from app.client import (
    HomelabClient,
    do_login_request,
    do_register_request,
    send_user_message,
)
from app.client_session import Session
from app.database import ClientRepository, hash_password, verify_password
from app.protocol import Message
from app.server import HomelabServer, handle_client_payload


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


class TestNetworkIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "integration_homelab.db"
        self.log_path = Path(self.temp_dir) / "integration_messages.log"
        self.repo = ClientRepository(db_path=self.db_path)

        # Inicializa socket servidor em porta efêmera aleatória
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind(("127.0.0.1", 0))
        self.server_socket.listen(5)
        self.port = self.server_socket.getsockname()[1]
        self.running = True

        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

    def tearDown(self):
        self.running = False
        try:
            # Conexão dummy para destravar accept
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as dummy:
                dummy.connect(("127.0.0.1", self.port))
        except Exception:
            pass
        self.server_socket.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _run_server(self):
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                if not self.running:
                    conn.close()
                    break
                data = conn.recv(4096)
                if data:
                    resp_bytes, _ = handle_client_payload(
                        data, addr, self.repo, self.log_path
                    )
                    conn.sendall(resp_bytes)
                conn.close()
            except Exception:
                break

    def test_end_to_end_auth_and_messaging(self):
        secret = Session.derive_secret("integration_user", "senha123")

        # 1. Login antes de registrar deve falhar (registro obrigatório)
        ok_login_fail, msg_fail = do_login_request("127.0.0.1", self.port, "integration_user", secret)
        self.assertFalse(ok_login_fail)
        self.assertIn("não encontrado", msg_fail)

        # 2. Cadastro de usuário
        ok_reg, msg_reg = do_register_request("127.0.0.1", self.port, "integration_user", secret)
        self.assertTrue(ok_reg)
        self.assertIn("sucesso", msg_reg)

        # 3. Login bem-sucedido
        ok_login, msg_login = do_login_request("127.0.0.1", self.port, "integration_user", secret)
        self.assertTrue(ok_login)

        # 4. Envio de mensagem autenticada
        send_ok = send_user_message(
            "127.0.0.1", self.port, "integration_user", secret, "Olá Homelab!"
        )
        self.assertTrue(send_ok)

        # 5. Verifica se o log foi gravado com a tag do usuário
        self.assertTrue(self.log_path.exists())
        log_content = self.log_path.read_text(encoding="utf-8")
        self.assertIn("integration_user@", log_content)
        self.assertIn("Olá Homelab!", log_content)


class TestHomelabClientOO(unittest.TestCase):
    """Valida a arquitetura orientada a objetos e ciclo de vida de HomelabClient (DEBT-01 e DEBT-03)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "client_oo_homelab.db"
        self.log_path = Path(self.temp_dir) / "client_oo_server.log"
        self.uploads_dir = Path(self.temp_dir) / "client_oo_uploads"
        self.session_path = Path(self.temp_dir) / "client_oo_session.json"

        # Inicializa o servidor completo HomelabServer em background em portas efêmeras
        self.server = HomelabServer(
            host="127.0.0.1",
            control_port=0,
            data_port=0,
            log_path=self.log_path,
            db_path=self.db_path,
            uploads_dir=self.uploads_dir,
        )
        self.server.start_in_background()

    def tearDown(self) -> None:
        self.server.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_client_context_manager_lifecycle(self) -> None:
        """Valida abertura e fechamento determinístico da conexão via context manager."""
        client = HomelabClient(
            host="127.0.0.1",
            control_port=self.server.control_port,
            data_port=self.server.data_port,
            session_path=self.session_path,
        )
        self.assertFalse(client.is_connected)
        self.assertIsNone(client.control_conn)

        with client as active_client:
            self.assertIs(active_client, client)
            self.assertTrue(active_client.is_connected)
            self.assertIsNotNone(active_client.control_conn)
            self.assertEqual(active_client.host, "127.0.0.1")
            self.assertEqual(active_client.control_port, self.server.control_port)
            self.assertEqual(active_client.data_port, self.server.data_port)

        self.assertFalse(client.is_connected)
        self.assertIsNone(client.control_conn)

    def test_client_register_and_login_flow(self) -> None:
        """Valida cadastro de conta, login explícito e persistência de sessão."""
        with HomelabClient(
            host="127.0.0.1",
            control_port=self.server.control_port,
            data_port=self.server.data_port,
            session_path=self.session_path,
        ) as client:
            # 1. Login sem cadastro prévio deve falhar
            ok, msg = client.login("novo_usuario", "senha123")
            self.assertFalse(ok)
            self.assertIn("não encontrado", msg)

            # 2. Cadastro do novo usuário
            ok_reg, msg_reg = client.register("novo_usuario", "senha123")
            self.assertTrue(ok_reg, msg_reg)
            self.assertIn("sucesso", msg_reg)
            self.assertEqual(client.username, "novo_usuario")
            self.assertIsNotNone(client.session)
            self.assertTrue(client.session.is_valid())
            self.assertTrue(self.session_path.is_file())

        # 3. Novo cliente autentica usando os dados cadastrados
        with HomelabClient(
            host="127.0.0.1",
            control_port=self.server.control_port,
            data_port=self.server.data_port,
            session_path=self.session_path,
        ) as client2:
            # Senha errada deve falhar
            ok_bad, msg_bad = client2.login("novo_usuario", "senha_incorreta")
            self.assertFalse(ok_bad)
            self.assertIn("Senha incorreta", msg_bad)

            # Senha correta
            ok_login, msg_login = client2.login("novo_usuario", "senha123")
            self.assertTrue(ok_login, msg_login)
            self.assertEqual(client2.username, "novo_usuario")

    def test_client_send_message_dispatch(self) -> None:
        """Valida despacho de mensagens autenticadas através do HomelabClient."""
        with HomelabClient(
            host="127.0.0.1",
            control_port=self.server.control_port,
            data_port=self.server.data_port,
            session_path=self.session_path,
        ) as client:
            # Tentativa de envio sem login prévio
            ok_unauth, msg_unauth = client.send_message("Mensagem sem auth")
            self.assertFalse(ok_unauth)
            self.assertIn("não autenticado", msg_unauth)

            # Cadastro e login
            client.register("autor_msg", "chave_secreta")

            # Envio com sucesso
            ok_send, msg_send = client.send_message("Mensagem enviada via HomelabClient OO!")
            self.assertTrue(ok_send, msg_send)
            self.assertIn("sucesso", msg_send.lower())

            # Valida gravação no log do servidor
            self.assertTrue(self.log_path.is_file())
            server_logs = self.log_path.read_text(encoding="utf-8")
            self.assertIn("autor_msg@", server_logs)
            self.assertIn("Mensagem enviada via HomelabClient OO!", server_logs)

    def test_client_upload_file(self) -> None:
        """Valida upload de arquivo em chunks através do HomelabClient."""
        with HomelabClient(
            host="127.0.0.1",
            control_port=self.server.control_port,
            data_port=self.server.data_port,
            session_path=self.session_path,
        ) as client:
            client.register("uploader_client", "segredo_upload")

            # Cria arquivo de teste
            test_file = Path(self.temp_dir) / "documento_teste.txt"
            test_content = b"Conteudo de teste para upload em chunks via HomelabClient OO!"
            test_file.write_bytes(test_content)

            ok, msg = client.upload_file(test_file)
            self.assertTrue(ok, msg)
            self.assertIn("sucesso", msg.lower())

            # Verifica arquivo salvo no servidor
            user_uploads = list((self.uploads_dir / "uploader_client").glob("*documento_teste.txt"))
            self.assertEqual(len(user_uploads), 1)
            self.assertEqual(user_uploads[0].read_bytes(), test_content)


if __name__ == "__main__":
    unittest.main()

