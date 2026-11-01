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

### 2.1. Execução do Servidor (`app/server.py`)
```bash
# Iniciar com configurações padrão de envs/server.env
python3 app/server.py

# Iniciar especificando arquivo de ambiente customizado
python3 app/server.py --env-file envs/server.env

# Iniciar com sobrescrita explícita de porta de controle e dados via CLI
python3 app/server.py --control-port 9000 --data-port 9001

# Iniciar escutando apenas em loopback para testes locais
python3 app/server.py --host 127.0.0.1
```

### 2.2. Execução do Cliente (`app/client.py`)
```bash
# Executar o cliente em modo interativo (menu CLI)
python3 app/client.py

# Apontar diretamente para IP do smartphone na rede LAN
python3 app/client.py --host 192.168.0.246

# Quick Login direto sem prompt interativo de credenciais
python3 app/client.py --quick-login

# Login explícito passando usuário diretamente
python3 app/client.py --user naoki

# Envio de mensagem direta via linha de comando
python3 app/client.py --message "Olá Homelab via CLI!"

# Upload de arquivo de mídia em chunks indexados de 64KB
python3 app/client.py --upload caminho/para/imagem.png
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
```

---

## 4. Inspeção de Dados, Banco SQLite e Logs

### 4.1. Banco de Dados SQLite (`app/data/homelab.db`)
```bash
# Inspecionar contas de clientes cadastradas
sqlite3 app/data/homelab.db "SELECT id, username, status, datetime(created_at, 'unixepoch', 'localtime') FROM clients;"

# Inspecionar mensagens armazenadas
sqlite3 app/data/homelab.db "SELECT id, client_id, message, datetime(created_at, 'unixepoch', 'localtime') FROM messages ORDER BY id DESC LIMIT 10;"

# Verificar integridade estrutural do banco
sqlite3 app/data/homelab.db "PRAGMA integrity_check;"
```

### 4.2. Sessão Local do Cliente (`app/data/client_session.json`)
```bash
# Visualizar conteúdo da sessão salva (JSON formatado)
python3 -m json.tool app/data/client_session.json 2>/dev/null || cat app/data/client_session.json
```

### 4.3. Logs do Servidor e Arquivos de Upload
```bash
# Acompanhar o log de mensagens em tempo real
tail -f app/logs/server_messages.log

# Listar arquivos e mídias recebidos no canal de dados
ls -lh app/data/uploads/
```

---

## 5. Manutenção do Host (Debian 11 / UserLAnd / Termux)

### 5.1. Acesso SSH ao Host
```bash
# Acesso ao Debian 11 UserLAnd no Redmi Note 9S (porta 2022)
ssh -p 2022 debian@192.168.0.246

# Acesso ao Termux nativo (porta 8022)
ssh -p 8022 -i ~/.ssh/id_ed25519 192.168.0.246
```

### 5.2. Gerenciamento de Serviços no Debian UserLAnd
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

### 5.3. Otimizações de Rede e Processos no Android
```bash
# Elevar limite de descritores de arquivos na sessão
ulimit -n 4096

# No Termux: Ativar wake-lock para impedir suspensão de CPU pelo Android
termux-wake-lock

# No Termux: Checar status da bateria via termux-api
termux-battery-status
```

### 5.4. Execução Contínua em Background com PM2
```bash
# Iniciar o servidor Homelab gerenciado pelo PM2
pm2 start app/server.py --name "homelab-server" --interpreter python3

# Visualizar status dos daemons
pm2 status

# Visualizar logs em tempo real
pm2 logs homelab-server

# Salvar lista de processos para autostart
pm2 save
```

---

## 6. Governança Git, Worktrees e Commits Atômicos

### 6.1. Gestão de Worktrees Isoladas
```bash
# Listar worktrees ativas
git worktree list

# Criar nova worktree para uma branch isolada
git worktree add ../homelab-<nome-da-branch> -b <nome-da-branch>

# Remover uma worktree após merge e finalização
git worktree remove ../homelab-<nome-da-branch>
```

### 6.2. Proteção da Branch `main` e Verificação
```bash
# NUNCA commitar na branch main! Sempre checar branch ativa antes de commitar:
git branch --show-current
```

### 6.3. Padrão de Commits Atômicos (Conventional Commits)
```bash
# Formato: <tipo>(<escopo>): <descrição em minúsculas>
git add <arquivos-estritos-da-action>
git commit -m "feat(infra): implementar nova checagem no check-infra.sh"
git commit -m "test(infra): adicionar testes unitários para o script de pré-voo"
git commit -m "docs(infra): documentar matriz de portas e health check"
git commit -m "chore(gemini): atualizar catalogo de comandos"
```
