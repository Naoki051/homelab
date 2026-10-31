# Documento Técnico: Arquitetura Dual-Protocol (Framing de Controle Persistente e Chunks de Mídia com HMAC)

> **Status:** Implementado  
> **Branch:** `feature/dual-protocol-and-infra-limits`  
> **Linguagem:** Python 3 (Biblioteca padrão: `struct`, `hmac`, `hashlib`, `socket`, `threading`)

---

## 1. Visão Geral e Motivação

O TCP é um protocolo orientado a fluxo contínuo de bytes (*byte stream*), não preservando fronteiras de mensagens nativamente. Além disso, o envio de arquivos pesados (como imagens, áudios ou vídeos) pelo mesmo canal de mensagens de texto causa **Bloqueio de Cabeça de Fila (*Head-of-Line Blocking*)** e risco de esgotamento da memória RAM no servidor (**Xiaomi Redmi Note 9S**).

Para solucionar esses dois problemas, a comunicação do Homelab foi dividida em **dois protocolos complementares**:

1. **Protocolo de Controle — Canal 1 (Porta `9000`):**
   - Conexão TCP **persistente** (*Keep-Alive*).
   - Enquadramento (*Length-Prefixed Framing*) para mensagens JSON leves (login, registro, chat, solicitação de upload).
   - Autenticidade e integridade via **HMAC-SHA256** com chave de sessão dinâmica.
2. **Protocolo de Dados/Mídia — Canal 2 (Porta `9001`):**
   - Conexão TCP sob demanda dedicada ao transporte de arquivos binários pesados.
   - Fatiamento em **Chunks Indexados de até 64 KB (`65536 bytes`)**.
   - Cada chunk carrega seu próprio cabeçalho binário e assinatura **HMAC-SHA256**, sendo gravado diretamente no disco (*streaming*) sem acumular o arquivo na RAM.

---

## 2. Gerenciamento Dinâmico da Chave Compartilhada (HMAC)

A autenticação criptográfica dos pacotes utiliza **HMAC-SHA256** com uma estratégia em duas fases:

1. **Fase de Handshake Inicial (Pré-Autenticação):**
   - Antes do login ou cadastro, o cliente ainda não possui uma sessão ativa.
   - Os pacotes iniciais (`register` ou `login`) são assinados com a chave de inicialização do protocolo (`DEFAULT_HANDSHAKE_KEY` de 32 bytes).
2. **Fase de Sessão Autenticada (Chave Dinâmica de 32 Bytes):**
   - Assim que o servidor valida as credenciais do usuário no banco SQLite (`login` ou `register` com sucesso), o servidor gera uma **chave de sessão criptográfica exclusiva de 32 bytes (256 bits)** usando `os.urandom(32)`.
   - Essa chave é enviada ao cliente (codificada em hexadecimal no campo `session_key` da resposta).
   - A partir desse instante, **todas as mensagens subsequentes no Canal de Controle e todos os Chunks enviados no Canal de Dados** são assinados e verificados exclusivamente com essa `session_key` dinâmica.

---

## 3. Especificação Binária do Protocolo 1: Canal de Controle (Porta `9000`)

Cada quadro (*frame*) transmitido no Canal de Controle possui um **cabeçalho binário fixo de 40 bytes** em formato *Big-Endian* (`>2sHI32s`), seguido pelo payload JSON em UTF-8:

```text
+---------------+-----------------+--------------------+--------------------+-----------------------+
|  Magic (2B)   |  MsgType (2B)   | PayloadLength (4B) | HMAC-SHA256 (32B)  |   Payload JSON (NB)   |
|     b"HC"     | 1=Req, 2=Resp   |  uint32 Big-Endian | Assinatura Binária |  UTF-8 (máx. 64 KB)   |
+---------------+-----------------+--------------------+--------------------+-----------------------+
|<------------------------------------- 40 bytes fixos ------------------------------------>|
```

### Cálculo do HMAC no Canal de Controle:
Para impedir adulteração tanto do tamanho/tipo no cabeçalho quanto do conteúdo JSON, o HMAC é calculado sobre a concatenação dos metadados e do payload:

$$\text{HMAC}_{\text{controle}} = \text{HMAC-SHA256}(K_{\text{sessão}}, \text{Magic} \parallel \text{MsgType} \parallel \text{PayloadLength} \parallel \text{Payload})$$

---

## 4. Especificação Binária do Protocolo 2: Canal de Dados em Chunks (Porta `9001`)

Quando o cliente precisa enviar uma imagem, áudio ou arquivo binário, ele não bloqueia o Canal de Controle. O processo ocorre em duas etapas:

### Etapa 1: Solicitação de Ticket no Canal de Controle (`request_upload`)
O cliente envia uma mensagem `request_upload` na porta `9000` informando:
* `filename`: Nome original do arquivo (sanitizado no servidor).
* `file_size`: Tamanho total em bytes.
* `sha256`: Hash SHA-256 completo do arquivo para conferência final.

O servidor valida a sessão, reserva o destino em `app/data/uploads/` e responde com:
* `ticket`: Identificador único de 16 bytes (32 caracteres hexadecimais).
* `chunk_size`: `65536` (64 KB).
* `total_chunks`: Quantidade total de blocos esperada.
* `data_port`: Porta do Canal de Dados (padrão `9001`).

### Etapa 2: Transmissão de Chunks Indexados na Porta `9001`
O cliente abre uma conexão para a porta `9001` e transmite os blocos sequencialmente. Cada bloco possui um **cabeçalho binário fixo de 62 bytes** (`>2s16sIII32s`), seguido pelos bytes brutos do bloco (até `65536` bytes):

```text
+------------+--------------+-----------------+------------------+-----------------+-------------------+--------------------+
| Magic (2B) | Ticket (16B) | ChunkIndex (4B) | TotalChunks (4B) | DataLength (4B) | HMAC-Chunk (32B)  | Raw Bytes (<=64KB) |
|   b"HD"    | UUID Binário |  uint32 (0..N)  |     uint32 N     |  uint32 <=65536 | Assinatura Bloco  | Dados do Arquivo   |
+------------+--------------+-----------------+------------------+-----------------+-------------------+--------------------+
|<----------------------------------------------- 62 bytes fixos ---------------------------------------------->|
```

> [!NOTE]
> O campo `DataLength` utiliza um inteiro sem sinal de 4 bytes (`uint32`) porque um bloco cheio de 64 KB possui `65536` bytes, o que excede em 1 unidade o limite de um inteiro de 2 bytes (`uint16` máximo = `65535`).

### Cálculo do HMAC por Chunk:
Cada bloco é autenticado individualmente com a `session_key` vinculada ao `Ticket`:

$$\text{HMAC}_{\text{chunk}} = \text{HMAC-SHA256}(K_{\text{sessão}}, \text{Magic} \parallel \text{Ticket} \parallel \text{ChunkIndex} \parallel \text{TotalChunks} \parallel \text{DataLength} \parallel \text{RawBytes})$$

### Streaming Direto para Disco:
1. O servidor lê os 62 bytes do cabeçalho.
2. Localiza a sessão correspondente ao `Ticket` de 16 bytes.
3. Lê exatamente `DataLength` bytes do socket.
4. Verifica o `HMAC-Chunk` em tempo constante (`hmac.compare_digest`).
5. Posiciona o ponteiro no arquivo em disco (`offset = ChunkIndex * 65536`) e grava os bytes diretamente no armazenamento UFS.
6. Ao receber todos os chunks, valida o hash final do arquivo e retorna um quadro de confirmação (`STATUS_OK`) ao cliente.
