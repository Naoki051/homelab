# Test Infrastructure Specification: Homelab Client-Server E2E

> **Documento:** `TEST_INFRA.md`  
> **Status:** Normativo / Aprovado  
> **Módulo:** `tests/test_e2e_opaque_box.py`  
> **Framework:** Python 3 Native `unittest` (`python3 -m unittest`)  
> **Metodologia:** Suíte Opaque-Box em 4 Tiers (Caixa-Preta Orientada a Requisitos)  
> **Referência:** `ORIGINAL_REQUEST.md`, `docs/app/SPEC-client-architecture.md`, `docs/app/SPEC-server-architecture.md`

---

## 1. Filosofia de Testes e Metodologia Opaque-Box

A infraestrutura de testes ponta a ponta (E2E) do ecossistema Homelab é fundamentada no princípio de **verificação por caixa-opaca (opaque-box)**, garantindo que o comportamento do sistema seja avaliado estritamente contra os contratos públicos de protocolo, interfaces de alto nível (`HomelabClient`, `HomelabServer`) e pontos de entrada de linha de comando (`CLI`), sem qualquer dependência ou violação de estados internos privados.

### 1.1. Princípios Norteadores
1. **Zero-Mocking / Verificação Realista:** Todos os testes executam sobre sockets TCP reais em loopback (`127.0.0.1`), instâncias SQLite reais em arquivos temporários isolados, diretórios de upload efêmeros e cálculo real de streaming HMAC-SHA256 e SHA-256. Não são admitidos mocks, patches ou stubs que mascarem a dinâmica de rede.
2. **Framework Nativo Exclusivo (`unittest`):** Em conformidade com o guard rail de governança do projeto, utiliza-se exclusivamente `unittest.TestCase` do Python 3 padrão. É vedado o uso de runners externos (como `pytest`).
3. **Isolamento e Determinismo:** Cada caso de teste aloca portas dinâmicas de sistema operacional (`port=0` / ephemeral ports), diretórios temporários dedicados (`tempfile.mkdtemp`), e executa rotinas determinísticas de teardown que encerram daemons de controle/dados e removem resíduos do sistema de arquivos.
4. **Alinhamento com Restrições de Hardware:** Simula o comportamento real do servidor implantado no smartphone Xiaomi Redmi Note 9S (Qualcomm Snapdragon 720G / Debian 11 UserLAnd), validando limites de memória através de streaming posicional em chunks de 64 KB e pre-allocation com `truncate()`.
5. **Prevenção contra Regressões de Segurança:** Validação constante de não-vazamento de credenciais em logs, rotação de chaves criptográficas pós-autenticação e saneamento de permissões POSIX (`0600` para arquivos de sessão).

---

## 2. Inventário de Funcionalidades e Mapeamento de Cobertura

| ID | Funcionalidade Avaliada | Componentes Envolvidos | Tier | Contrato / Especificação |
|---|---|---|:---:|---|
| **F1** | Hierarquia Polimórfica de Protocolo | `Package(ABC)`, `Message`, `MediaChunk`, `ControlPackage`, `DataPackage` | Tier 1 | `SPEC-client-architecture.md` §2 |
| **F2** | Fachadas Públicas de Servidor e CLI | `HomelabServer`, `Server`, `DualChannelServer`, `python3 -m app.server` | Tier 1 | `SPEC-server-architecture.md` §3 |
| **F3** | Cadastro e Autenticação de Usuários | `HomelabClient.register`, `HomelabClient.login`, `ClientRepository` | Tier 1 | `SPEC-client-architecture.md` §3.4 |
| **F4** | Troca de Mensagens no Canal de Controle (:9000) | `HomelabClient.send_message`, `ServerCommandDispatcher`, `log_message` | Tier 1 | `SPEC-server-architecture.md` §3.2 |
| **F5** | Upload de Mídia via Canal de Dados (:9001) | `HomelabClient.upload_file`, `UploadTicketManager`, `MediaChunk` | Tier 1 | `SPEC-server-architecture.md` §3.1 |
| **F6** | Persistência Local de Sessão e Quick-Login | `Session.create`, `save` (0600), `load`, `app.client_session.Session` | Tier 1 | `SPEC-client-architecture.md` §3.1 |
| **F7** | Ciclo de Vida de Presença e Logout | `LogoutCommand`, `repo.update_status`, status online/offline | Tier 1 | `SPEC-server-architecture.md` §4 |
| **F8** | Sanitização de Entradas Extremas | Credenciais vazias, espaços em branco, inputs nulos | Tier 2 | `SPEC-client-architecture.md` §5 |
| **F9** | Rejeição de Duplicidade e Credenciais Inválidas | Tentativa de cadastro duplicado, login com senha incorreta | Tier 2 | `SPEC-server-architecture.md` §3.2 |
| **F10** | Rejeição de Ações Não-Autenticadas | Envio de mensagens ou solicitação de upload sem login | Tier 2 | `SPEC-server-architecture.md` §3.2 |
| **F11** | Limites de Carga e Fronteiras de Chunk (64KB) | Arquivo de 0 bytes, fronteira exata de 65.536 bytes, frame >64KB | Tier 2 | `SPEC-server-architecture.md` §1 |
| **F12** | Resiliência a Magic Bytes Inválidos e Corrupção HMAC | Frames com magic b"XX", HMAC adulterado, truncamento | Tier 2 | `SPEC-server-architecture.md` §3.3 |
| **F13** | Detecção de Adulteração de Payload em Streaming | Hash SHA-256 inconsistente, deleção de arquivo corrompido | Tier 2 | `SPEC-server-architecture.md` §3.3 |
| **F14** | Resiliência a Reset Abrupto de Sockets (TCP RST) | Queda de rede por `SO_LINGER=0`, transição garantida para offline | Tier 2 | `SPEC-server-architecture.md` §4 |
| **F15** | Fluxo Completo de Sessão e Quick-Login | Registro, salvamento de sessão NoSQL, carregamento e reautenticação | Tier 3 | `SPEC-client-architecture.md` §3.1 |
| **F16** | Continuidade de Sessão em Canal Duplo (Controle + Dados) | Upload de 80KB + Envio de Mensagem na mesma sessão persistente | Tier 3 | `SPEC-client-architecture.md` §2 |
| **F17** | Recuperação de Upload Interrompido e Reemissão | Queda do socket de dados e reemissão de ticket de upload | Tier 3 | `SPEC-server-architecture.md` §3.1 |
| **F18** | Uploads Sequenciais de Tamanhos Variados | Envio consecutivo de 256B, 64KB, 100KB, 192KB com validação SHA | Tier 3 | `SPEC-server-architecture.md` §3.1 |
| **F19** | Entrelaçamento de Mensagens e Uploads | Alternância de envio de texto e upload de arquivo na mesma conexão | Tier 3 | `SPEC-server-architecture.md` §3.2 |
| **F20** | Simulação Concorrente de Chat Multi-Cliente | Conexões simultâneas de clientes independentes com auditoria | Tier 4 | `SPEC-server-architecture.md` §3.2 |
| **F21** | Uploads Concorrentes de Mídia Multi-Cliente | Uploads simultâneos via ThreadPool sem colisão de tickets | Tier 4 | `SPEC-server-architecture.md` §3.1 |
| **F22** | Ciclo de Vida Completo de Usuário | Ciclo ponta a ponta: erro, cadastro, uso, logout, login, crash e reconexão | Tier 4 | `SPEC-server-architecture.md` §4 |
| **F23** | Execução Ponta a Ponta via CLI em Subprocesso | Invocação real de `python3 -m app.client` via subprocess do SO | Tier 4 | `SPEC-client-architecture.md` §3.5 |

---

## 3. Arquitetura da Suíte de Testes (4 Tiers)

A suíte está estruturada em `tests/test_e2e_opaque_box.py` sob 4 níveis hierárquicos:

```text
tests/test_e2e_opaque_box.py
├── OpaqueBoxTestCase (Base Fixture com Servidor Efêmero e Isolamento de IO)
├── TestTier1FeatureCoverage (9 testes de caminho feliz isolado)
├── TestTier2BoundaryAndCornerCases (10 testes de limites, ataques e falhas de rede)
├── TestTier3CrossFeatureCombinations (5 testes de fluxos cruzados e transições de estado)
└── TestTier4RealWorldScenarios (4 testes de estresse concorrente, ciclo completo e CLI do SO)
```

### 3.1. Tier 1 — Feature Coverage (Caminho Feliz Isolado)
Valida cada recurso de forma atômica e independente através das interfaces públicas:
- Inicialização e encerramento determinístico de servidores (`HomelabServer`, `Server`, `DualChannelServer`).
- Registro de nova conta e emissão de chave HMAC dinâmica de 32 bytes (`client.register`).
- Autenticação e rotação de chave de sessão (`client.login`).
- Despacho de mensagens de texto persistentes para auditoria no servidor (`client.send_message`).
- Upload de arquivos de chunk único (< 64 KB) e múltiplos chunks (> 64 KB) com cálculo de integridade SHA-256 (`client.upload_file`).
- Criação e recuperação de sessão NoSQL com permissão restrita POSIX `0600`.
- Encerramento voluntário de sessão (`logout`) com reversão de chave e presença offline.
- Herança e despacho polimórfico da hierarquia `Package(ABC)`.

### 3.2. Tier 2 — Boundary & Corner Cases (Limites e Condições Adversas)
Testa a robustez do sistema sob condições limites e dados maliciosos:
- Rejeição de strings vazias e compostas exclusivamente por espaços.
- Bloqueio de cadastros duplicados com mensagens de erro amigáveis.
- Proteção contra tentativas de login com usuário inexistente ou credenciais incorretas.
- Rejeição estrita de operações de mensageria e upload solicitadas por clientes não autenticados.
- Manipulação de arquivos vazios (0 bytes) e verificação do hash padrão `e3b0c44...`.
- Alinhamento em fronteiras de potência binária (exatos 65.536 bytes por chunk).
- Resiliência contra injeção de Magic Bytes desconhecidos e pacotes corrompidos no canal de controle.
- Rejeição imediata de frames com assinatura HMAC violada.
- Detecção e exclusão automática de arquivos com hash SHA-256 inconsistente no canal de dados.
- Recuperação graciosa e atualização de presença em quedas abruptas de conexão (TCP RST via `SO_LINGER=0`).

### 3.3. Tier 3 — Cross-Feature Combinations (Fluxos Sequenciais Cruzados)
Exercita a máquina de estados através de combinações entre múltiplos subsistemas:
- Fluxo Registro $\rightarrow$ Persistência de Sessão Local $\rightarrow$ Quick-Login $\rightarrow$ Mensagem.
- Continuidade de sessão criptográfica entre canais: Autenticação no canal de controle (:9000), upload de arquivo de 80 KB no canal de dados (:9001) usando a mesma chave de sessão dinâmica, e envio imediato de mensagem de controle confirmando o envio.
- Queda induzida do socket de dados a meio do streaming, seguida de recuperação e reemissão de ticket bem-sucedida.
- Sucessão de múltiplos uploads de tamanhos heterogêneos sem interferência de estado no gerenciador de tickets.
- Intercalação repetida de mensagens e uploads na mesma conexão mantida aberta (*keep-alive*).

### 3.4. Tier 4 — Real-World Application Scenarios (Cenários Reais de Aplicação)
Simula o uso realista do ecossistema Homelab em produção:
1. **Chat Simultâneo Multi-Cliente:** Múltiplos clientes conectam concorrentemente através de threads, autenticam-se com chaves independentes e enviam mensagens que são devidamente registradas e ordenadas cronologicamente pelo servidor.
2. **Uploads Concorrentes de Mídia:** Execução simultânea de transferências de arquivos de diversos tamanhos via `ThreadPoolExecutor`, validando a thread-safety do `UploadTicketManager`, integridade dos arquivos salvos e ausência de vazamento de descritores de arquivo.
3. **Ciclo de Vida Completo do Usuário:** Percurso completo cobrindo tentativa inválida, cadastro, transição para online, troca de mensagens, transferência de mídia, logout, novo login via credenciais salvas, desconexão abrupta de rede simulada e reconexão posterior.
4. **Execução de Subprocesso CLI do Sistema Operacional:** Invocação real do cliente via terminal (`python3 -m app.client --host 127.0.0.1 --port ... -m ...`), simulando o operador interagindo diretamente com o executável em ambiente de produção.

---

## 4. Invariantes de Segurança e Critérios de Aceitação

Para que a suíte seja considerada apta e pronta para produção, todos os seguintes critérios devem ser atendidos:

1. **Taxa de Aprovação:** 100% dos testes devem passar (`Ran 28 tests ... OK`).
2. **Tempo de Execução:** A suíte completa deve rodar em menos de 15 segundos em ambiente de desenvolvimento local.
3. **Isolamento de Recursos:** Nenhum socket TCP, thread daemon ou arquivo temporário pode permanecer aberto ou órfão após a execução do teste.
4. **Conformidade PEP 8 / Flake8:**
   - Comprimento máximo de linha: 100 caracteres.
   - Complexidade ciclomática por método: $\le 12$.
   - Zero ocorrências de exceções genéricas (`except Exception:`).
5. **Auditoria de Dados Sensíveis:** Nenhuma senha em texto puro, hash PBKDF2 completo ou chave de sessão HMAC integral pode ser gravada nos arquivos de log durante os testes.
