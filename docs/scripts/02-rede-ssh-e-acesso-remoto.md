# Módulo 02: Rede, SSH e Acesso Remoto

Este módulo orienta a configuração da camada de rede, acesso via OpenSSH seguro com chaves criptográficas e túnel seguro com Tailscale para acessar seu Redmi Note 9S de qualquer lugar do mundo sem abrir portas no roteador residencial.

---

## 1. Configurações Iniciais no Termux

Abra o aplicativo **Termux** no celular e execute os seguintes comandos:

### A. Conceder Acesso ao Armazenamento Interno
```bash
termux-setup-storage
```
Uma janela pop-up do Android surgirá pedindo permissão de acesso aos arquivos. Toque em **Permitir**. Isso cria o diretório `~/storage` apontando para o armazenamento compartilhado do celular.

### B. Ativar o Wake-Lock (Impede o processador de dormir)
```bash
termux-wake-lock
```
Isso faz com que o Termux mantenha um *wake-lock* no Android, garantindo que o processador Snapdragon 720G continue ativo mesmo com a tela do aparelho desligada. Uma notificação permanente do Termux aparecerá na barra de notificações com a mensagem `(wake lock held)`.

---

## 2. Estabilidade do Wi-Fi na MIUI

Por padrão, os smartphones modernos utilizam endereços MAC aleatórios que mudam periodicamente, o que quebra reservas de IP no roteador:

1. **Fixar o Endereço MAC Real no Wi-Fi**:
   - No celular, vá em **Configurações** > **Wi-Fi**.
   - Toque na seta `>` ao lado da sua rede Wi-Fi conectada.
   - Toque em **Privacidade**.
   - Altere de *"Usar MAC aleatório (padrão)"* para **"Usar MAC do dispositivo"**.
2. **Definir Reserva de IP no Roteador (DHCP Estático)**:
   - Acesse o painel de administração do seu roteador residencial (normalmente `192.168.1.1` ou `192.168.0.1`).
   - Vá na seção **DHCP** / **IP Binding** / **Reserva de Endereço**.
   - Adicione o endereço MAC do Redmi Note 9S e fixe um IP local (ex: `192.168.1.150`).
3. **Verifique o IP atual no Termux**:
   ```bash
   ip route get 1.1.1.1 | awk '{print $7}'
   ```

---

## 3. Configuração do Servidor OpenSSH (Porta 8022)

Como o Termux opera sem privilégios de root, a porta padrão do SSH não pode ser a `22` (que exige root). Por convenção, o Termux utiliza a porta **`8022`**.

### Passo 1: Instalar e Iniciar o OpenSSH no Celular
No terminal do Termux no celular:
```bash
# Atualizar repositórios e instalar OpenSSH
pkg update -y
pkg install -y openssh

# Definir uma senha forte para seu usuário no Termux
passwd

# Iniciar o servidor SSH
sshd
```

### Passo 2: Testar o Acesso pelo Terminal do seu Mac
No terminal do Mac, substitua `<IP_DO_CELULAR>` pelo IP do Redmi Note 9S:
```bash
ssh -p 8022 <IP_DO_CELULAR>
```
Digite a senha que você definiu no comando `passwd`. Você já estará conectado ao shell do celular diretamente pelo seu computador!

---

## 4. Configurar Autenticação por Chave Pública (Sem Senha)

A autenticação por chave SSH é mais segura e elimina a necessidade de digitar senhas a cada conexão.

### Passo 1: Gerar a Chave no Mac (se já não tiver uma)
No terminal do Mac:
```bash
ssh-keygen -t ed25519 -C "homelab-note9s" -f ~/.ssh/id_ed25519_note9s
```

### Passo 2: Copiar a Chave Pública para o Termux
No terminal do Mac:
```bash
ssh-copy-id -p 8022 -i ~/.ssh/id_ed25519_note9s.pub <IP_DO_CELULAR>
```
*(Caso o comando `ssh-copy-id` falhe no Termux, você pode simplesmente copiar o conteúdo de `~/.ssh/id_ed25519_note9s.pub` e colar no arquivo `~/.ssh/authorized_keys` dentro do Termux)*.

### Passo 3: Criar um Atalho no `~/.ssh/config` do seu Mac
Abra ou crie o arquivo `~/.ssh/config` no seu Mac e adicione o bloco:

```sshconfig
Host note9s
    HostName 192.168.1.150
    Port 8022
    User u0_aXXX           # opcional, o Termux aceita qualquer usuário
    IdentityFile ~/.ssh/id_ed25519_note9s
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

Agora, você pode acessar seu miniservidor a partir do Mac com apenas:
```bash
ssh note9s
```

---

## 5. Acesso Externo Remoto Seguro via Tailscale

Para acessar seu servidor de qualquer rede (4G/5G, trabalho, café) sem precisar de IP público fixo e sem abrir portas no roteador (livre de problemas com CGNAT):

### Instalação do Tailscale no Redmi Note 9S
1. Baixe o aplicativo oficial do **Tailscale** pela Google Play Store ou F-Droid/GitHub no Redmi Note 9S.
2. Faça login com sua conta (Google, GitHub ou Microsoft).
3. Ative a conexão VPN. O aparelho receberá um IP no formato `100.x.y.z` e um nome MagicDNS (ex: `redmi-note-9s`).
4. **Configuração de Conexão Permanente no Android**:
   - No celular, vá em **Configurações** > **Conexão e compartilhamento** > **VPN**.
   - Toque no ícone de engrenagem ao lado do Tailscale.
   - Ative a opção **"VPN sempre ativa"** (*Always-on VPN*).

### Acessando pelo Mac via Tailscale
1. Instale o Tailscale no seu Mac e faça login com a mesma conta.
2. Agora você pode conectar ao seu miniservidor via SSH de qualquer lugar do planeta usando:
   ```bash
   ssh -p 8022 <IP_DO_TAILSCALE>
   # ou usando MagicDNS:
   ssh -p 8022 redmi-note-9s
   ```

---

## 6. Próximo Passo

Com o acesso SSH e a rede estabilizados, continue para o [**Módulo 03: Serviços Web, Dev e Bancos de Dados**](file:///Users/naokiteruya/Projects/homelab/docs/03-servicos-web-dev-e-bancos.md).
