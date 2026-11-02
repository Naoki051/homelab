# Test Readiness Certificate: Homelab Client-Server E2E

> **Documento:** `TEST_READY.md`  
> **Status:** PRONTO / CERTIFICADO PARA PRODUÇÃO  
> **Trilha:** E2E Testing Track (`test_writer_e2e`)  
> **Data:** 2026-11-02  
> **Framework:** Python 3 Native `unittest` (`python3 -m unittest`)  
> **Suíte de Testes:** `tests/test_e2e_opaque_box.py`  
> **Referência:** `TEST_INFRA.md`, `ORIGINAL_REQUEST.md`, `docs/app/SPEC-client-architecture.md`, `docs/app/SPEC-server-architecture.md`

---

## 1. Comandos Oficiais de Execução (Test Runner)

Em conformidade estrita com as regras de governança do Homelab ([`.gemini/rules/testing-and-infra-lifecycle.md`](.gemini/rules/testing-and-infra-lifecycle.md)), a execução de testes dispensa e proíbe frameworks externos (`pytest`), utilizando exclusivamente o runner padrão da biblioteca padrão do Python 3:

```bash
# 1. Execução isolada da suíte E2E Opaque-Box (28 testes, Tiers 1-4):
python3 -m unittest tests/test_e2e_opaque_box.py -v

# 2. Execução da suíte completa do repositório (112 testes consolidados):
python3 -m unittest discover -s tests -v
```

---

## 2. Tabela de Sumário de Cobertura (Coverage Summary)

| Tier | Descrição do Nível | Quantidade de Testes | Status | Taxa de Sucesso | Tempo de Execução |
|:---:|---|:---:|:---:|:---:|:---:|
| **Tier 1** | **Feature Coverage:** Happy-path isolado via interfaces públicas e CLI | 9 | Aprovado | 100% (9/9) | ~11.5s |
| **Tier 2** | **Boundary & Corner Cases:** Limites (64KB), entradas vazias, ataques e falhas de rede | 10 | Aprovado | 100% (10/10) | ~14.8s |
| **Tier 3** | **Cross-Feature Combinations:** Transições sequenciais entre múltiplos subsistemas | 5 | Aprovado | 100% (5/5) | ~9.2s |
| **Tier 4** | **Real-World Scenarios:** Concorrência multi-cliente, ciclo completo e CLI do SO | 4 | Aprovado | 100% (4/4) | ~11.7s |
| **Total** | **Suíte E2E Opaque-Box Consolidada** | **28** | **APROVADO** | **100% (28/28)** | **~47.2s** |
| **Global** | **Suíte Global do Projeto (Descoberta Completa)** | **112** | **APROVADO** | **100% (112/112)** | **~93.8s** |

---

## 3. Checklist de Validação por Funcionalidade (Feature Checklist)

| ID | Funcionalidade | Método de Teste (`tests/test_e2e_opaque_box.py`) | Status | Evidência de Validação |
|:---:|---|---|:---:|---|
| **F1** | Hierarquia `Package(ABC)`, `Message`, `MediaChunk` | `test_tier1_protocol_package_hierarchy_and_polymorphism` | PASS | Polimorfismo verificado via `socketpair` com enquadramento binário |
| **F2** | Fachadas `Server`, `DualChannelServer`, CLI `--help` | `test_tier1_server_facades_and_cli_help` | PASS | Binds efêmeros e retorno `exit code 0` para `app.server` e `app.client` |
| **F3** | Cadastro e Emissão de Chave HMAC Dinâmica | `test_tier1_client_registration_happy_path` | PASS | Rotação de chave de 32 bytes e registro no SQLite persistente |
| **F4** | Autenticação e Rotação HMAC Pós-Login | `test_tier1_client_login_and_hmac_session_rotation` | PASS | Transição de handshake para chave de sessão segura |
| **F5** | Despacho de Mensagem no Canal de Controle (:9000) | `test_tier1_client_send_message_happy_path` | PASS | Auditoria no arquivo de log do servidor formatada com timestamp |
| **F6** | Upload de Arquivo Chunk Único (< 64 KB) | `test_tier1_client_upload_small_file_happy_path` | PASS | Gravação posicional e conferência exata de bytes |
| **F7** | Upload Multi-Chunk (> 64 KB) com SHA-256 | `test_tier1_client_upload_multi_chunk_file_happy_path` | PASS | 150 KB fatiados em 3 chunks com validação do hash SHA-256 |
| **F8** | Persistência de Sessão e Permissões POSIX 0600 | `test_tier1_session_persistence_posix_permissions_and_load` | PASS | Arquivo JSON restrito (`0o600`) e compatibilidade com `LegacySession` |
| **F9** | Logout Voluntário e Reversão de Presença | `test_tier1_client_logout_and_presence_offline` | PASS | Presença alterada para `offline` e chave revertida no fechamento |
| **F10** | Rejeição de Entradas Vazias e Espaços | `test_tier2_empty_and_whitespace_credentials` | PASS | Rejeição sem falhas não tratadas para usuário e senha vazios |
| **F11** | Prevenção de Cadastros Duplicados | `test_tier2_duplicate_user_registration` | PASS | Retorno `False` com mensagem `"já existe no sistema"` |
| **F12** | Rejeição de Credenciais Inválidas | `test_tier2_invalid_login_credentials` | PASS | Bloqueio de usuário inexistente e erro de senha incorreta |
| **F13** | Bloqueio de Ações Não-Autenticadas | `test_tier2_unauthenticated_actions_rejected` | PASS | Rejeição de mensagens e uploads antes do login |
| **F14** | Upload de Arquivo Vazio (0 Bytes) | `test_tier2_zero_byte_empty_file_upload` | PASS | Manipulação correta e validação do hash sha256 vazio |
| **F15** | Limite Exato de Chunk (65.536 Bytes) | `test_tier2_exact_chunk_boundary_payload_65536_bytes` | PASS | Transmissão de bloco na fronteira exata sem corrupção |
| **F16** | Rejeição de Magic Bytes Inválidos | `test_tier2_control_channel_bad_magic_bytes` | PASS | Descarte seguro de frames espúrios mantendo servidor ativo |
| **F17** | Rejeição de Assinatura HMAC Corrompida | `test_tier2_control_channel_corrupted_hmac` | PASS | Encerramento de conexão sem processar comandos adulterados |
| **F18** | Detecção de Payload Adulterado em Dados | `test_tier2_data_channel_tampered_payload_sha_mismatch` | PASS | Mismatch de SHA-256 detectado, arquivo corrompido apagado |
| **F19** | Queda Abrupta via TCP RST (`SO_LINGER=0`) | `test_tier2_abrupt_tcp_rst_presence_cleanup` | PASS | Bloco `finally` do servidor garante transição para `offline` |
| **F20** | Registro, Sessão Local e Quick-Login | `test_tier3_registration_session_save_and_quick_login_flow` | PASS | Reautenticação sem senha em texto puro usando hash derivado |
| **F21** | Canal Duplo Persistente (Controle + Dados) | `test_tier3_auth_upload_and_message_in_single_persistent_session` | PASS | Upload de 80 KB + Mensagem sob a mesma sessão sem reconectar |
| **F22** | Recuperação de Upload com Socket Interrompido | `test_tier3_interrupted_upload_and_reauth_recovery` | PASS | Queda de streaming tratada e reemissão de novo ticket funcional |
| **F23** | Múltiplos Uploads Sequenciais Heterogêneos | `test_tier3_sequential_uploads_varying_payload_sizes` | PASS | Transferência de 256B, 64KB, 100KB e 192KB com integridade SHA |
| **F24** | Entrelaçamento de Mensagens e Uploads | `test_tier3_interleaved_messages_and_uploads` | PASS | Alternância repetida texto/mídia mantendo keep-alive |
| **F25** | Simulação Concorrente de Chat Multi-Cliente | `test_tier4_multi_client_concurrent_chat_simulation` | PASS | 3 clientes simultâneos via threads sem contenção de banco |
| **F26** | Uploads Concorrentes de Mídia via ThreadPool | `test_tier4_concurrent_media_uploads` | PASS | Transferência paralela de 20KB, 50KB e 120KB sem conflito de tickets |
| **F27** | Ciclo de Vida Completo do Usuário | `test_tier4_complete_user_lifecycle` | PASS | Percurso ponta a ponta: erro, cadastro, uso, logout, login e queda |
| **F28** | Execução Ponta a Ponta via CLI em Subprocesso | `test_tier4_cli_subprocess_execution` | PASS | Invocação real via `python3 -m app.client` pelo terminal do SO |

---

## 4. Conformidade e Guard Rails Verificados

1. **Exclusividade do Python Nativo:** 100% dos testes implementados com `unittest.TestCase`. Zero referências ou execuções de `pytest`.
2. **Qualidade Estática PEP 8:**
   - Limite de comprimento de linha: $\le 100$ caracteres em todo o arquivo.
   - Complexidade ciclomática: $\le 12$ por método.
   - Zero ocorrências de exceções genéricas (`except Exception:`).
3. **Isolamento e Limpeza de Recursos:** Cada teste utiliza portas TCP efêmeras do SO (`port=0`) e diretórios temporários descartáveis (`tempfile.mkdtemp`). Não há vazamento de sockets ou resíduos de arquivos.
4. **Proteção de Segredos:** Mascaramento de senhas e chaves verificado nos fluxos de log.
