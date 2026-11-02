# Catálogo de Comandos Úteis do Homelab

> **Guia Rápido de Referência Operacional e de Desenvolvimento**  
> Diretório base: Raiz do repositório (`homelab/`)

---

## 1. Checagem de Infraestrutura e Pré-Voo (`scripts/check-infra.sh`)

### 1.1. Setup Inicial dos Arquivos de Ambiente
```bash
# Criar arquivos de ambiente locais a partir dos modelos oficiais (.sample)
cp envs/server.env.sample envs/server.env
cp envs/client.env.sample envs/client.env
cp envs/.env.sample envs/.env
```

### 1.2. Validação Estrita de Configuração (Fail-Fast / CI)
```bash
# Validar arquivo do servidor (variáveis obrigatórias e portas não-privilegiadas)
./scripts/check-infra.sh --mode server --env-only

# Validar arquivo do cliente
./scripts/check-infra.sh --mode client --env-only

# Validar arquivos específicos ou customizados
./scripts/check-infra.sh --mode server --env-file envs/server.env.sample --env-only
./scripts/check-infra.sh --mode client --env-file envs/client.env.sample --env-only
./scripts/check-infra.sh --mode server --env-file envs/.env.sample --env-only
```

### 1.3. Diagnóstico Completo de Saúde do Host (Servidor)
```bash
# Executa identificação do SO, venv Python, RAM livre (< 300MB), ulimit, processo ativo e portas
./scripts/check-infra.sh --local
```

### 1.4. Diagnóstico Remoto de Rede e Probes TCP (Cliente)
```bash
# Probe de ping ICMP e portas de Controle (:9000) e Dados (:9001) no host alvo
./scripts/check-infra.sh --remote

# Probe completo incluindo verificação de SSH no host remoto (UserLAnd Debian :2022)
./scripts/check-infra.sh --remote --ssh --ssh-port 2022

# Probe remoto apontando para porta SSH do Termux (:8022)
./scripts/check-infra.sh --remote --ssh --ssh-port 8022
```

---

## 2. Execução da Aplicação (Servidor e Cliente Dual-Protocol)

### 2.1. Execução do Servidor (`app/server` / `app.server`)
```bash
# Iniciar como módulo padrão via Python (recomendado)
python3 -m app.server

# Ou iniciar via diretório de pacote
python3 app/server

# Iniciar especificando arquivo de ambiente customizado
python3 -m app.server --env-file envs/server.env

# Iniciar com sobrescrita explícita de porta de controle e dados via CLI
python3 -m app.server --port 9000 --data-port 9001

# Iniciar escutando apenas em loopback para testes locais
python3 -m app.server --host 127.0.0.1
```

### 2.2. Execução do Cliente (`app/client` / `app.client`)
```bash
# Executar o cliente em modo interativo (menu CLI com Quick Login automático)
python3 -m app.client

# Ou executar via diretório de pacote
python3 app/client

# Apontar diretamente para IP do smartphone na rede LAN
python3 -m app.client --host 192.168.0.246

# Envio de mensagem direta via linha de comando (após login interativo/automático)
python3 -m app.client --message "Olá Homelab via CLI!"

# Upload de arquivo de mídia em chunks indexados de 64KB
python3 -m app.client --upload caminho/para/imagem.png
```

---

## 3. Testes Automatizados (`tests/`)

### 3.1. Executar a Suíte Completa
```bash
# Descoberta e execução de todos os testes unitários e de integração
python3 -m unittest discover -s tests -v
```

### 3.2. Executar Módulos de Teste Específicos
```bash
# Testes do script de verificação e saúde da infraestrutura
python3 -m unittest tests/test_check_infra.py -v

# Testes de carregamento, precedência e validação de configurações (.env)
python3 -m unittest tests/test_config.py -v

# Testes de autenticação, sessões, PBKDF2 e persistência SQLite
python3 -m unittest tests/test_auth_and_session.py -v

# Testes do protocolo duplo (Controle 40B, HMAC dinâmico e Chunks de 64KB)
python3 -m unittest tests/test_dual_protocol_and_chunks.py -v

# Testes de padrões de código, exceções de domínio e conformidade
python3 -m unittest tests/test_code_standards.py -v
```

### 3.3. Ciclo de Desenvolvimento TDD (Red -> Green -> Refactor)
```bash
# 1. Red: Executar teste recém-criado para confirmar falha esperada
python3 -m unittest tests/test_novo_recurso.py -v

# 2. Green: Implementar o código mínimo e rodar novamente até passar
python3 -m unittest tests/test_novo_recurso.py -v

# 3. Refactor: Validar não-regressão rodando a suíte completa
python3 -m unittest discover -s tests -v
```

---

## 4. Qualidade de Código e Linting (`flake8`)

O projeto utiliza o arquivo canônico `.flake8` na raiz do repositório como guia estrito de formatação PEP 8 e complexidade ciclomática.

### 4.1. Execução via Script Auxiliar Automatizado
```bash
# Script com autoverificação de ambiente e execução conforme .flake8:
./scripts/run-lint.sh

# Passando parâmetros ou arquivos específicos:
./scripts/run-lint.sh app/ tests/
```

### 4.2. Execução Direta do Flake8 (Terminal ou venv)
```bash
# Executar verificação completa em todos os arquivos de código:
flake8 app/ tests/

# Checar apenas o diretório de aplicação:
flake8 app/

# Checar complexidade ciclomática estrita (max-complexity = 12):
flake8 --select=C901 app/
```

### 4.3. Instalação do Flake8 no Host ou Ambiente Virtual
```bash
# Instalação direta no venv do projeto:
python3 -m pip install flake8
```

---

## 5. Inspeção de Dados, Banco SQLite e Logs

### 5.1. Banco de Dados SQLite (`app/data/homelab.db`)
```bash
# Inspecionar contas de clientes cadastradas
sqlite3 app/data/homelab.db "SELECT id, username, status, datetime(created_at, 'unixepoch', 'localtime') FROM clients;"

# Inspecionar mensagens armazenadas
sqlite3 app/data/homelab.db "SELECT id, client_id, message, datetime(created_at, 'unixepoch', 'localtime') FROM messages ORDER BY id DESC LIMIT 10;"

# Verificar integridade estrutural do banco
sqlite3 app/data/homelab.db "PRAGMA integrity_check;"
```

### 5.2. Sessão Local do Cliente (`app/data/client_session.json`)
```bash
# Visualizar conteúdo da sessão salva (JSON formatado)
python3 -m json.tool app/data/client_session.json 2>/dev/null || cat app/data/client_session.json
```

### 5.3. Logs do Servidor e Arquivos de Upload
```bash
# Acompanhar o log de mensagens em tempo real
tail -f app/logs/server_messages.log

# Listar arquivos e mídias recebidos no canal de dados
ls -lh app/data/uploads/
```

---

## 6. Manutenção do Host (Debian 11 / UserLAnd / Termux)

### 6.1. Acesso SSH ao Host
```bash
# Acesso ao Debian 11 UserLAnd no Redmi Note 9S (porta 2022)
ssh -p 2022 debian@192.168.0.246

# Acesso ao Termux nativo (porta 8022)
ssh -p 8022 -i ~/.ssh/id_ed25519 192.168.0.246
```

### 6.2. Gerenciamento de Serviços no Debian UserLAnd
```bash
# Iniciar o serviço SSH dentro do UserLAnd
sudo service ssh start

# Verificar status do serviço SSH
sudo service ssh status

# Monitorar consumo de CPU e memória RAM
htop

# Verificar memória RAM livre em megabytes
free -m

# Verificar espaço em disco
df -h
```

### 6.3. Otimizações de Rede e Processos no Android
```bash
# Elevar limite de descritores de arquivos na sessão
ulimit -n 4096

# No Termux: Ativar wake-lock para impedir suspensão de CPU pelo Android
termux-wake-lock

# No Termux: Checar status da bateria via termux-api
termux-battery-status
```

### 6.4. Execução Contínua em Background com PM2
```bash
# Iniciar o servidor Homelab gerenciado pelo PM2 (executa o pacote app/server)
pm2 start app/server --name "homelab-server" --interpreter python3

# Visualizar status dos daemons
pm2 status

# Visualizar logs em tempo real
pm2 logs homelab-server

# Salvar lista de processos para autostart
pm2 save
```

---

## 7. Governança Git, Worktrees e Commits Atômicos

### 7.1. Gestão de Worktrees Isoladas
```bash
# Listar worktrees ativas
git worktree list

# Criar nova worktree para uma branch isolada
git worktree add ../homelab-<nome-da-branch> -b <nome-da-branch>

# Remover uma worktree após merge e finalização
git worktree remove ../homelab-<nome-da-branch>
```

### 7.2. Proteção da Branch `main` e Verificação
```bash
# NUNCA commitar na branch main! Sempre checar branch ativa antes de commitar:
git branch --show-current
```

### 7.3. Padrão de Commits Atômicos (Conventional Commits)
```bash
# Formato: <tipo>(<escopo>): <descrição em minúsculas>
git add <arquivos-estritos-da-action>
git commit -m "feat(infra): implementar nova checagem no check-infra.sh"
git commit -m "test(infra): adicionar testes unitários para o script de pré-voo"
git commit -m "docs(infra): documentar matriz de portas e health check"
git commit -m "chore(gemini): atualizar catalogo de comandos"
```
