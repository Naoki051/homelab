# Módulo 01: Preparação da MIUI e Android (Redmi Note 9S)

Este módulo cobre todas as etapas necessárias no sistema Android original (MIUI 11, 12, 13 ou 14 baseadas no Android 10, 11 ou 12) do **Xiaomi Redmi Note 9S** para que ele possa operar como um servidor contínuo sem que o sistema encerre os serviços em segundo plano.

---

## 1. Limpeza Inicial do Aparelho

Para obter o máximo de memória RAM livre e estabilidade:

1. **Restauração de Fábrica (Recomendado se o aparelho for dedicado)**:
   - Vá em **Configurações** > **Sobre o telefone** > **Redefinir dados** (Factory reset).
   - Configure o aparelho sem vincular conta Google nem conta Mi se não for estritamente necessário (ou use uma conta secundária).
2. **Desative Animações e Recursos Desnecessários**:
   - Vá em **Configurações** > **Tela** > defina tempo de suspensão de tela para o mínimo (ex: 15 ou 30 segundos) para economizar energia quando não estiver em uso direto.
   - Desative vibrações, sons de toque, sincronizações desnecessárias e Bluetooth (se não for usar).
3. **Remova ou Desative Aplicativos Inúteis (Bloatware)**:
   - Desinstale aplicativos comerciais pré-instalados (jogos, redes sociais, navegadores extras).

---

## 2. Blindagem contra o Gerenciamento de Memória da MIUI

A MIUI possui um dos sistemas mais agressivos do ecossistema Android para matar processos em segundo plano. Para garantir que o Termux continue vivo 24/7:

### A. Economia de Bateria: Nenhuma Restrição
Para cada um dos seguintes aplicativos instalados (**Termux**, **Termux:Boot** e **Termux:API**):
1. Mantenha pressionado o ícone do aplicativo na tela inicial e toque em **Informações do app** (ou vá em **Configurações** > **Apps** > **Gerenciar apps**).
2. Role até **Economia de bateria**.
3. Altere de *"Economia de bateria da MIUI (recomendado)"* para **"Nenhuma restrição"**.

### B. Início Automático (Autostart)
1. Ainda na tela de **Informações do app** do **Termux** e do **Termux:Boot**:
2. Ative a chave **"Início automático"** (Autostart).
3. Confirme o alerta do sistema.

### C. Travar o App na Tela de Recentes (Cadeado)
1. Abra o aplicativo **Termux**.
2. Abra a tela de aplicativos recentes (gesto de deslizar para cima e segurar ou botão quadrado de navegação).
3. Pressione e segure o cartão do Termux até aparecer os ícones laterais.
4. Toque no ícone do **Cadeado** para fechá-lo. (Isso impede que a MIUI encerre o Termux quando você usar a função de "limpar memória").

---

## 3. Desativando o Phantom Process Killer (Android 12+ / MIUI 13-14)

A partir do Android 12, o Google introduziu o *Phantom Process Killer*, que encerra qualquer aplicativo em segundo plano que dispare mais de 32 processos/threads simultâneos. Isso afeta diretamente Termux rodando Node.js, PostgreSQL, PM2 ou QEMU.

### Passo a passo para desativar via ADB (pelo Mac):

1. **Habilite as Opções do Desenvolvedor no Redmi Note 9S**:
   - Vá em **Configurações** > **Sobre o telefone**.
   - Toque repetidamente (7 vezes) em **"Versão da MIUI"** até surgir a mensagem *"Você agora é um desenvolvedor!"*.
2. **Ative a Depuração USB**:
   - Vá em **Configurações adicionais** > **Opções do desenvolvedor**.
   - Ative **"Depuração USB"**.
   - (Se aplicável) Ative também **"Depuração USB (Configurações de segurança)"**.
3. **Conecte o celular ao Mac via cabo USB**:
   - No terminal do Mac, instale o `adb` (caso não tenha: `brew install android-platform-tools`).
   - Execute:
     ```bash
     adb devices
     ```
   - No visor do celular, autorize a chave RSA do Mac selecionando *"Sempre permitir a partir deste computador"*.
4. **Execute os comandos de liberação de processos**:
   ```bash
   adb shell "/system/bin/device_config set_sync_disabled_for_tests persistent"
   adb shell "/system/bin/device_config put activity_manager max_phantom_processes 2147483647"
   ```
5. **Confirme se o valor foi aplicado**:
   ```bash
   adb shell "/system/bin/device_config get activity_manager max_phantom_processes"
   # A resposta deve ser: 2147483647
   ```

*(Nota: Esta configuração persiste até que o celular sofra uma atualização completa do sistema operacional Android).*

---

## 4. Instalação do Ecossistema Termux (F-Droid)

> [!CAUTION]
> **NÃO instale o Termux pela Google Play Store!**
> A versão da Google Play Store foi descontinuada em 2020 devido a restrições do SDK do Android e não recebe atualizações de repositórios nem correções críticas.

Instale os aplicativos a partir do **F-Droid** ou baixando os APKs oficiais do repositório do Termux no GitHub:

1. Baixe e instale o [F-Droid](https://f-droid.org/) no Redmi Note 9S ou baixe diretamente as seguintes versões APK do GitHub oficial:
   - **Termux**: [Releases GitHub](https://github.com/termux/termux-app/releases) (baixe a versão `termux-app_v..._arm64-v8a.apk` ou universal).
   - **Termux:API**: [Releases GitHub](https://github.com/termux/termux-api/releases) (permite ler nível e temperatura da bateria, controlar notificações, etc.).
   - **Termux:Boot**: [Releases GitHub](https://github.com/termux/termux-boot/releases) (permite iniciar seus serviços automaticamente quando o celular liga).
2. **Atenção às assinaturas**: Todos os apps Termux (`Termux`, `Termux:API`, `Termux:Boot`) **precisam ter a mesma assinatura digital**. Portanto, instale todos pelo F-Droid OU todos pelos APKs do GitHub oficial.

---

## 5. Cuidados Físicos e Elétricos para Operação 24/7

Operar um smartphone conectado à energia ininterruptamente exige precauções simples para preservar a vida útil da bateria de 5020 mAh do Redmi Note 9S:

1. **Remova a Capinha de Proteção**:
   - Capinhas retêm o calor gerado pela placa-mãe e pelo carregamento. Deixar o aparelho sem capinha garante melhor dissipação passiva.
2. **Posicionamento**:
   - Mantenha o aparelho em pé (em um suporte plástico ou de metal) ou sobre uma superfície sólida e fresca. Evite superfícies de tecido ou madeira isolante.
3. **Use um Carregador Lento (5V 1A / 5W)**:
   - O Redmi Note 9S vem com carregador de 18W/22.5W (Fast Charging). Para operação 24/7, **evite carregadores turbo**, pois eles elevam a temperatura da bateria desnecessariamente. Um carregador simples padrão de 5V 1A ou 5V 2A supre o consumo do servidor (1.5W a 4W) sem esquentar o aparelho.
4. **Ciclo Inteligente de Bateria (30% - 80%)**:
   - Manter a bateria estática em 100% sob tensão constante acelera a degradação química.
   - No [Módulo 05](file:///Users/naokiteruya/Projects/homelab/docs/05-automacao-boot-e-manutencao.md), disponibilizamos o script `battery-guard.sh` que integra com tomadas inteligentes Wi-Fi (Tuya, Sonoff, Tapo, Home Assistant) ou envia alertas para ligar a tomada aos 30% e desligar aos 80%.
