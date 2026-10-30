# Módulo 03: Serviços Web, Dev e Bancos de Dados

Neste módulo, configuraremos a pilha de desenvolvimento nativa do Termux (Python, Node.js, Git), bancos de dados relacionais (PostgreSQL e SQLite), proxy reverso leve (Caddy ou Nginx) e ferramentas de gerenciamento de processos em segundo plano (`termux-services` e `PM2`).

---

## 1. Stack Nativa de Desenvolvimento

O Snapdragon 720G possui 8 núcleos de CPU com arquitetura ARM64 de alta eficiência, capaz de compilar e executar ferramentas modernas com facilidade.

### A. Ferramentas Básicas e Compiladores
No terminal Termux (via SSH pelo Mac):
```bash
pkg update -y
pkg install -y build-essential clang make pkg-config git curl wget jq tmux
```

### B. Python 3 e Gerenciadores de Pacotes
```bash
pkg install -y python python-pip
python -m pip install --upgrade pip

# Criando um ambiente virtual de teste
python -m venv ~/my-env
source ~/my-env/bin/activate
pip install fastapi uvicorn
deactivate
```

### C. Node.js LTS e Gerenciadores
```bash
pkg install -y nodejs-lts
npm install -g pnpm yarn
node -v
npm -v
```

---

## 2. Bancos de Dados

### A. PostgreSQL (Porta 5432)
O PostgreSQL roda de forma 100% nativa e rápida no Termux.

1. **Instalação**:
   ```bash
   pkg install -y postgresql
   ```
2. **Inicialização do Cluster de Dados**:
   ```bash
   # Criar o diretório e inicializar a base se ainda não existir
   mkdir -p $PREFIX/var/lib/postgresql
   initdb -D $PREFIX/var/lib/postgresql
   ```
3. **Iniciar o Servidor Manualmente para Teste**:
   ```bash
   pg_ctl -D $PREFIX/var/lib/postgresql -l $PREFIX/var/log/postgresql.log start
   ```
4. **Criar Banco de Dados e Usuário**:
   ```bash
   # Criar banco padrão
   createdb homelab

   # Acessar o console interativo do Postgres
   psql -d homelab
   ```
   No prompt do `psql`:
   ```sql
   CREATE USER dev WITH ENCRYPTED PASSWORD 'senha_segura';
   GRANT ALL PRIVILEGES ON DATABASE homelab TO dev;
   \q
   ```
5. **Parar o Servidor Manualmente**:
   ```bash
   pg_ctl -D $PREFIX/var/lib/postgresql stop
   ```

### B. SQLite
Ideal para aplicações leves, dashboards e automações locais que não demandam um servidor TCP separado:
```bash
pkg install -y sqlite
sqlite3 homelab.db "CREATE TABLE status (id INTEGER PRIMARY KEY, status TEXT);"
```

---

## 3. Proxy Reverso e Servidor Web: Caddy & Nginx

Como não temos root, portas abaixo de 1024 estão bloqueadas. Usamos as portas **`8080`** (HTTP) e **`8443`** (HTTPS) para expor nossos serviços web.

### Por que Caddy?
O **Caddy** é distribuído como um único binário Go compilado para ARM64, consome pouquíssima memória (~25MB) e sua sintaxe de configuração (`Caddyfile`) é extremamente limpa.

1. **Instalar Caddy**:
   ```bash
   pkg install -y caddy
   ```
2. **Exemplo de Configuração (`$PREFIX/etc/caddy/Caddyfile`)**:
   ```caddy
   :8080 {
       # Servir arquivos estáticos HTML/JS
       root * /data/data/com.termux/files/home/www
       file_server

       # Roteamento de API Node.js rodando na porta 3000
       handle_path /api/* {
           reverse_proxy localhost:3000
       }

       # Roteamento de API Python FastAPI rodando na porta 8000
       handle_path /py/* {
           reverse_proxy localhost:8000
       }
   }
   ```
3. **Iniciar e Recarregar Caddy**:
   ```bash
   caddy start --config $PREFIX/etc/caddy/Caddyfile
   caddy reload --config $PREFIX/etc/caddy/Caddyfile
   ```

---

## 4. Gerenciamento de Processos e Daemons

Para que seus servidores continuem rodando após fechar a sessão SSH ou reiniciar o aparelho, usamos duas ferramentas complementares:

### A. `termux-services` (Baseado no Runit)
Gerencia serviços de sistema nativos do Termux (PostgreSQL, SSHD, etc.):

```bash
# Instalar o pacote
pkg install -y termux-services

# Habilitar o PostgreSQL para iniciar com o Termux
sv-enable postgresql

# Comandos de controle
sv up postgresql       # Iniciar
sv down postgresql     # Parar
sv status postgresql   # Checar status
```

### B. PM2 (Process Manager para Node.js, Python e Binários)
Excelente para aplicações customizadas, com monitoramento de CPU/memória e reinicialização automática em caso de falha:

```bash
# Instalar PM2 globalmente
npm install -g pm2

# Exemplo: subir uma aplicação Node.js
pm2 start app.js --name "api-node"

# Exemplo: subir uma aplicação Python FastAPI
pm2 start "uvicorn main:app --host 0.0.0.0 --port 8000" --name "api-python"

# Ver status de todos os processos
pm2 list
pm2 monit

# Salvar o estado atual para restauração automática
pm2 save
```

---

## 5. Ambientes Linux Completos com `proot-distro`

O Termux utiliza a biblioteca C do Android (`Bionic libc`). Caso você precise rodar algum pacote Linux tradicional compilado para GNU C (`glibc`), use o `proot-distro`:

```bash
# Instalar a ferramenta
pkg install -y proot-distro

# Instalar o Debian ARM64
proot-distro install debian

# Entrar no ambiente Debian completo
proot-distro login debian
```
Dentro do Debian, você terá o gerenciador `apt`, caminhos padrão do Linux (`/etc`, `/var`, `/usr/bin`) e compatibilidade total sem necessidade de root. Para sair, basta digitar `exit`.

---

## 6. Próximo Passo

Para rodar containers OCI e Docker Compose no Redmi Note 9S, prossiga para o [**Módulo 04: Containers e Docker Sem Root**](file:///Users/naokiteruya/Projects/homelab/docs/04-containers-docker-sem-root.md).
