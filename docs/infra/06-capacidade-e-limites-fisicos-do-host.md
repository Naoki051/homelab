# Módulo 06: Spike de Capacidade, Concorrência e Limites Físicos do Host

> **Status:** Documentado  
> **Host Alvo:** Xiaomi Redmi Note 9S (`curtana` / `miatoll` — Qualcomm Snapdragon 720G / ARM64)  
> **Ambiente Operacional:** Android (MIUI) + Termux sem Root  

---

## 1. Objetivo desta Spike

Este documento registra a investigação técnica (*spike*) sobre os limites físicos, operacionais e de rede do smartphone **Xiaomi Redmi Note 9S** operando como servidor TCP contínuo (24/7). O objetivo é responder:
1. O uso de uma *thread* por cliente gera limitação de portas no servidor?
2. Quantos clientes simultâneos o hardware suporta nos modelos **Thread-per-Client** vs **I/O Assíncrono (`asyncio`)**?
3. Quais são os verdadeiros gargalos físicos (CPU, térmica, memória RAM, armazenamento UFS e rede Wi-Fi)?

---

## 2. O Mito da Limitação de Portas em Servidores TCP

Uma dúvida recorrente ao implementar conexões TCP persistentes com 1 *thread* por cliente é se o servidor esgotará as portas locais disponíveis (`1024` a `65535`).

### 2.1. Identificação de Conexões pelo Kernel (4-Tuple)
No kernel Linux/Android, um socket TCP conectado **não** aloca uma nova porta local no servidor. Toda conexão TCP ativa é identificada de forma única por uma **tupla de 4 elementos (*4-tuple*)**:

$$\text{Socket ID} = (\text{IP}_{\text{origem}}, \text{Porta}_{\text{origem}}, \text{IP}_{\text{destino}}, \text{Porta}_{\text{destino}})$$

* **No Servidor:** Os campos $\text{IP}_{\text{destino}}$ (ex: `192.168.0.246`) e $\text{Porta}_{\text{destino}}$ (ex: `9000` para controle ou `9001` para dados) permanecem **fixos** para todos os clientes.
* **No Cliente:** Cada cliente possui seu próprio $\text{IP}_{\text{origem}}$ e sorteia uma $\text{Porta}_{\text{origem}}$ efêmera na sua própria máquina.

> [!IMPORTANT]
> **Conclusão:** O servidor utiliza **apenas 1 porta por serviço** (ex: `9000` e `9001`), independentemente de haver 10 ou 10.000 clientes conectados simultaneamente. O limite de conexões do servidor **nunca é o número de portas**, mas sim **Descritores de Arquivo (*File Descriptors*)**, **Memória RAM** e **Troca de Contexto de CPU**.

---

## 3. Raio-X dos Limites Físicos do Redmi Note 9S

| Recurso | Especificação do Redmi Note 9S | Comportamento sob Carga e Gargalo Real |
| :--- | :--- | :--- |
| **SoC / CPU** | Qualcomm Snapdragon 720G (8 núcleos Kryo 465: 2x Gold @ 2.3 GHz + 6x Silver @ 1.8 GHz) | Arquitetura *big.LITTLE*. Processos em segundo plano no Termux tendem a ser alocados nos 6 núcleos de eficiência (1.8 GHz) pelo escalonador EAS (*Energy Aware Scheduling*) do Android. |
| **Dissipação Térmica** | **100% Passiva (sem cooler/ventoinha)** | **Gargalo Crítico:** Cargas contínuas de CPU (ex: cálculo intensivo de hashes HMAC ou compressão em múltiplas threads por >3 minutos) elevam a temperatura do SoC acima de 65°C, acionando *thermal throttling* que reduz o clock em até 45%. |
| **Memória RAM** | 4 GB ou 6 GB LPDDR4X | O sistema Android + interface MIUI consomem entre 2.2 GB e 2.8 GB. Sobram **1.2 GB a 2.5 GB de RAM livre real** para o Termux, banco SQLite/PostgreSQL e buffers da aplicação Python. |
| **Armazenamento** | 64 GB / 128 GB UFS 2.1 | Velocidade sequencial alta (~250 MB/s escrita), porém memória NAND Flash móvel possui desgaste (TBW limitado). Uploads de mídia devem ser gravados em blocos (*chunks* de 64 KB) direto no disco sem *swap* em RAM. |
| **Interface de Rede** | **Wi-Fi 5 (802.11ac 2x2 MIMO)** | O meio sem fio é **Half-Duplex** (não transmite e recebe simultaneamente na mesma frequência). Uploads pesados de imagens concorrendo no mesmo canal Wi-Fi aumentam o *jitter* e a latência se não houver separação e controle de pacotes. |

---

## 4. Restrições do Sistema Operacional (Android sem Root)

1. **Limite de File Descriptors (`ulimit -n`):**
   - No Linux/Android, cada socket TCP aberto consome 1 *File Descriptor* (FD).
   - No Termux, o limite *soft* padrão geralmente é `1024` ou `4096`, podendo ser consultado via `ulimit -n` e elevado até o limite *hard* do kernel (tipicamente `32768` ou `65536` no Android).
2. **Phantom Process Killer (Android 12+ / MIUI 13+):**
   - O gerenciador de atividades do Android monitora processos filhos e *threads* criadas por aplicativos em background. Se o limite padrão de 32 processos/threads de alto consumo for excedido sem a desativação via ADB (`max_phantom_processes`), o sistema envia `SIGKILL` ao Termux.
3. **Low Memory Killer (LMK):**
   - Se o processo Python alocar imagens ou vídeos inteiros na memória RAM durante um upload, o *Low Memory Killer* do Android encerrará o servidor instantaneamente para proteger a interface do telefone.

---

## 5. Capacidade Estimada: Thread-per-Client vs Event Loop (`asyncio`)

### 5.1. Modelo 1: Uma Thread por Cliente (`threading.Thread`)
Cada conexão TCP persistente é atendida por uma thread dedicada em Python (CPython):
* **Consumo de Memória por Thread:** Cada thread aloca uma pilha (*stack*) no espaço do processo e estruturas do interpretador, consumindo cerca de **100 KB a 512 KB de RAM efetiva** (além de até 8 MB de endereço virtual).
* **Troca de Contexto (*Context Switching*) e GIL:** Embora chamadas de rede (`socket.recv`) liberem o *Global Interpreter Lock* (GIL), quando centenas de threads acordam simultaneamente para validar HMAC e gravar no SQLite, há forte contenção pelo GIL e overhead no escalonador do kernel.

### 5.2. Modelo 2: Multiplexação de I/O Assíncrona (`asyncio` / `selectors`)
Uma única thread gerencia todas as conexões usando `epoll` do kernel Linux:
* **Consumo de Memória por Conexão:** Apenas o estado da corrotina e o buffer do protocolo (~4 KB a 16 KB por cliente).
* **Troca de Contexto:** Zero troca de threads no nível do sistema operacional.

### 5.3. Tabela Comparativa de Capacidade no Redmi Note 9S

| Métrica | Modelo Thread-per-Client (Atual) | Modelo Assíncrono (`asyncio` / Futuro) |
| :--- | :--- | :--- |
| **Clientes Simultâneos (Confortável)** | **150 a 400 conexões** | **3.000 a 8.000 conexões** |
| **Limite Máximo antes de Degradação** | ~600 a 800 conexões | Limitado pelo `ulimit -n` (~32.000) |
| **Impacto Térmico em Alta Carga** | Alto (múltiplas threads disputando CPU) | Baixo (execução cooperativa em 1 core) |
| **Complexidade de Implementação** | Baixa (ideal para fase atual e estudo) | Média/Alta (exige drivers assíncronos) |

---

## 6. Diretrizes Arquiteturais Derivadas desta Spike

Para garantir que o **Xiaomi Redmi Note 9S** opere com estabilidade mesmo sob sobrecarga de mensagens e uploads ocasionais de imagens/arquivos pesados, adotamos as seguintes decisões de engenharia:

1. **Separação Física em Dois Protocolos/Canais:**
   - **Canal de Controle (Porta `9000`):** Exclusivo para comandos, autenticação e mensagens leves (< 64 KB) usando *Length-Prefixed Framing*. Evita *Head-of-Line Blocking*.
   - **Canal de Dados/Mídia (Porta `9001`):** Exclusivo para upload de arquivos pesados fatiados em *Chunks* indexados.
2. **Teto Rígido de Memória por Upload (Chunks de 64 KB):**
   - Nenhum arquivo enviado pelo cliente é mantido inteiro na RAM. O servidor recebe blocos de no máximo **64 KB (`65536 bytes`)**, valida o HMAC-SHA256 do bloco e descarrega imediatamente no armazenamento UFS (`file.write` + `flush`).
3. **Autenticação Leve via HMAC-SHA256:**
   - A instrução criptográfica SHA-256 possui aceleração por hardware na arquitetura ARMv8-A (Snapdragon 720G), permitindo validar centenas de pacotes por segundo com impacto térmico desprezível.
