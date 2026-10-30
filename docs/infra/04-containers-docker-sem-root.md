# Módulo 04: Containers e Docker Sem Root

Este módulo aborda como executar containers no Xiaomi Redmi Note 9S sem root, explicando as limitações do kernel Android e apresentando duas soluções práticas complementares: **`udocker`** (ultra-leve) e **QEMU + Alpine Linux** (Docker Engine e Docker Compose completos).

---

## 1. Por que o Docker Nativo Não Roda no Android Sem Root?

O Docker padrão (`dockerd`) depende diretamente de recursos de baixo nível do kernel Linux:
- **Namespaces** (PID, rede, montagem, IPC) restritos ao usuário root.
- **Control Groups (cgroups)** para limitação de CPU/RAM.
- **Overlay2 / UnionFS** para camadas de imagem do sistema de arquivos.
- **Iptables / Nftables** com privilégios administrativos para criar pontes de rede (`docker0`).

No Android original não rooteado, o usuário comum do Termux não tem acesso a essas chamadas de sistema. Felizmente, existem duas soluções consagradas para superar essa barreira:

| Recurso | Opção A: `udocker` | Opção B: QEMU + Alpine Linux |
| :--- | :--- | :--- |
| **Arquitetura** | Execução OCI em Userspace via PRoot | Máquina Virtual Linux Real (ARM64 no ARM64) |
| **Consumo de Memória (RAM)** | Mínimo (~20MB + o app) | 1GB a 2.5GB (configurável para a VM) |
| **Suporte a `docker-compose`** | Limitado (não suporta redes virtuais complexas) | **100% Completo** (`docker compose up -d`) |
| **Daemon do Docker (`dockerd`)** | Não utiliza daemon | **Sim**, daemon oficial do Docker ativo |
| **Desempenho de CPU** | Praticamente nativo | Excelente (ARM64 convidado em ARM64 nativo) |
| **Ideal para...** | Rodar containers isolados leves | Stacks complexas, microserviços e Compose |

---

## 2. Opção A: Executando Containers com `udocker`

O `udocker` é uma ferramenta desenvolvida pelo consórcio europeu INDIGO-DataCloud. Ele baixa imagens de registros Docker (Docker Hub, GitHub Container Registry) e executa os containers inteiramente em modo de usuário (*user space*) usando PRoot.

### Instalação Dentro do `proot-distro` (Recomendado)
A melhor maneira de rodar o `udocker` é dentro do ambiente Debian do `proot-distro`:

```bash
# 1. No Termux, entre no Debian
proot-distro login debian

# 2. Instale dependências no Debian
apt update && apt install -y python3 curl tar git

# 3. Baixe e instale o udocker
curl https://raw.githubusercontent.com/indigo-dc/udocker/master/udocker.py -o /usr/local/bin/udocker
chmod +x /usr/local/bin/udocker

# 4. Inicialize o udocker (ele baixará os binários de suporte em userspace)
udocker install
```

### Exemplos Práticos de Uso

#### A. Baixar e Rodar um Container Nginx:
```bash
# Baixar imagem
udocker pull nginx:alpine

# Criar container
udocker create --name=meu-nginx nginx:alpine

# Executar com mapeamento de porta (ex: porta 8081 local apontando para a porta 80 do container)
udocker run -p 8081:80 meu-nginx
```

#### B. Rodar um Container com Volume Mapeado:
```bash
udocker run -v /root/meus-dados:/data -p 8000:8000 minha-api:latest
```

---

## 3. Opção B: Docker e Docker Compose Completos via QEMU (Alpine Linux ARM64)

Como o Redmi Note 9S possui processador Snapdragon 720G de 64 bits (ARM64) e 4GB ou 6GB de memória RAM, podemos executar uma máquina virtual Linux ARM64 com o **Alpine Linux** usando o QEMU. Por estarmos rodando um sistema operacional ARM64 sobre um processador físico ARM64, não há o peso de emulação de arquitetura cruzada!

Dentro desta VM Alpine, temos um **kernel Linux padrão completo**, onde o `dockerd`, `docker build` e `docker-compose` rodam nativamente.

### Passo 1: Instalar o QEMU no Termux
No terminal do Termux:
```bash
pkg update -y
pkg install -y qemu-system-aarch64 qemu-utils wget
```

### Passo 2: Criar Diretório e Disco Virtual
```bash
mkdir -p ~/alpine-vm
cd ~/alpine-vm

# Criar disco virtual de 15GB em formato qcow2 (cresce sob demanda, não consome 15GB de imediato)
qemu-img create -f qcow2 alpine-disk.qcow2 15G

# Baixar imagem Virt do Alpine Linux para ARM64
wget https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/alpine-virt-3.20.0-aarch64.iso
```

### Passo 3: Iniciar a VM para Instalação
Inicie o QEMU com redirecionamento da porta SSH da VM (`22`) para a porta `2222` do celular:

```bash
qemu-system-aarch64 \
  -M virt -cpu cortex-a57 -smp 4 -m 2048M \
  -drive file=alpine-disk.qcow2,if=virtio,format=qcow2 \
  -cdrom alpine-virt-3.20.0-aarch64.iso -boot d \
  -netdev user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::8088-:80 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

### Passo 4: Instalar o Alpine no Disco Virtual
Quando o prompt do Alpine surgir no terminal (`localhost login:`), digite `root` (sem senha) e execute:
```bash
setup-alpine
```
- Siga o assistente de instalação (layout de teclado `us` ou `br-abnt2`).
- Defina uma senha para o usuário `root`.
- Na etapa *"Which disk(s) would you like to use"*, digite `vda`.
- Na etapa *"How would you like to use it"*, escolha `sys`.
- Digite `y` para confirmar e aguarde a cópia dos arquivos.
- Ao concluir, desligue a VM com: `poweroff`.

### Passo 5: Script de Inicialização da VM Alpine (`start-docker-vm.sh`)
Crie o script para iniciar a VM no dia a dia (sem a ISO):

```bash
#!/data/data/com.termux/files/usr/bin/sh
cd ~/alpine-vm
qemu-system-aarch64 \
  -M virt -cpu cortex-a57 -smp 4 -m 2048M \
  -drive file=alpine-disk.qcow2,if=virtio,format=qcow2 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::8088-:80,hostfwd=tcp::9000-:9000 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

### Passo 6: Ativar o Docker Dentro da VM Alpine
Conecte-se à VM a partir do Termux ou do seu Mac:
```bash
ssh -p 2222 root@localhost
```

Dentro da VM Alpine, habilite e inicie o Docker:
```bash
# Habilitar repositórios community
sed -i 's/^#//g' /etc/apk/repositories
apk update

# Instalar Docker e Docker Compose
apk add docker docker-cli-compose

# Habilitar no boot da VM e iniciar o serviço
rc-update add docker boot
service docker start

# Testar
docker run --rm hello-world
```

Agora você tem um ambiente Docker completo pronto para rodar qualquer `docker-compose.yml`!

---

## 4. Próximo Passo

Para automatizar a subida de todos os serviços no boot do celular e proteger a bateria, continue para o [**Módulo 05: Automação de Boot e Manutenção**](file:///Users/naokiteruya/Projects/homelab/docs/05-automacao-boot-e-manutencao.md).
