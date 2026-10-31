# Diretriz de Commits: Proteção da Main, Conventional Commits e Commits por Actions

> **Escopo da Regra:** Exclusiva deste projeto (`homelab`).  
> **Aplicação:** Mandatória para qualquer sessão, agente de IA, automação ou desenvolvedor atuando neste repositório.

---

## 1. 🛑 Proteção Absoluta da Branch `main`

1. **Proibição de Commit Direto:**
   - **NUNCA realizar commits diretamente na branch `main`.**
   - Nenhuma linha de código, documentação ou configuração deve ser commitada na `main` sem que haja uma pergunta e autorização explícita do usuário antes.
2. **Fluxo Padrão Obrigatório:**
   - Toda alteração — seja nova funcionalidade, documentação, refatoração ou correção de bug (`fix`) — deve ser desenvolvida em uma **branch dedicada** (`feature/`, `fix/`, `chore/`, `docs/`).
   - Apenas após a validação completa na branch de trabalho e a **autorização explícita do usuário**, o merge para a `main` poderá ser realizado.

---

## 2. 📝 Padrão Obrigatório: Conventional Commits

Todo commit deve seguir rigorosamente a especificação do [Conventional Commits](https://www.conventionalcommits.org/):

```text
<tipo>(<escopo opcional>): <descrição concisa no imperativo e minúsculo>
```

### Tipos Permitidos:
* **`feat:`** Nova funcionalidade, novo endpoint ou novo componente da aplicação.
* **`fix:`** Correção de bug ou ajuste de comportamento não esperado.
* **`docs:`** Criação ou atualização de documentação técnica, tutoriais ou README.
* **`test:`** Adição ou correção de testes automatizados ou scripts de validação.
* **`chore:`** Tarefas de manutenção, governança, configuração de tooling, `.gitignore` ou scripts de ambiente.
* **`refactor:`** Mudança no código que não altera funcionalidade nem corrige bug.
* **`perf:`** Alteração de código com foco estrito em ganho de performance.

### Exemplos:
* `feat(app): implementar classe Session para quick login`
* `fix(app): adicionar fallback de import para execucao direta em app/`
* `docs(infra): atualizar instrucoes de acesso SSH no android`
* `test(app): adicionar teste de expiracao de sessao`

---

## 3. ⚡ Regras de Commits por Actions e Checklist

1. **Commits Incrementais e Atômicos por Ação:**
   - O desenvolvimento não deve ser acumulado em um único commit monolítico ao final da tarefa.
   - A cada ação concluída e testada do checklist/plano de implementação, um commit atômico correspondente deve ser gerado imediatamente.
2. **Validação Prévia Mandatória:**
   - Antes de efetuar o commit de uma action, certifique-se de que a alteração compila, executa e passa nos testes automatizados (`python3 -m unittest ...`).
   - Não realize commits de código quebrado ou intermediário que viole a integridade do repositório.
3. **Escopo Restrito:**
   - Cada commit deve conter apenas os arquivos pertinentes àquela action específica. Não incluir arquivos não relacionados (`staging` seletivo via `git add <arquivos>`).
