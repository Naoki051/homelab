# Diretrizes de Desenvolvimento do Projeto Homelab

Este projeto utiliza um sistema integrado de governança, guard rails e navegação documental distribuído em:
- [Fluxo de Trabalho e Guard Rails por Branch](.gemini/rules/branch-workflow.md)
- [Diretrizes de Commits, Proteção da Main e Actions](.gemini/rules/commit-rules.md)
- [Matriz de Permissões e Guard Rails de Execução Git](.gemini/rules/git-execution-guardrails.md)
- [Navegação de Contexto e Documentação (Docs-First)](.gemini/rules/context-and-doc-navigation.md)
- [Ciclo de Vida de Testes e Comandos de Infraestrutura](.gemini/rules/testing-and-infra-lifecycle.md)
- [Ciclo de Propagação e Rastreamento de Documentação](.gemini/rules/doc-propagation-lifecycle.md)
- [Catálogo Canônico de Comandos Úteis e Operações](.gemini/rules/commands.md)
- [Padrões de Código, TDD e Workflow de Execução](.gemini/rules/code-standards-and-workflow.md)
- [Roteador Central de Documentação](docs/INDEX.md)

---

## Regras Ativas Mandatórias:

1. **Navegação Orientada a Documentação (Docs-First):**
   - **NUNCA vasculhar código-fonte às cegas.** Ao receber uma tarefa, consulte a documentação técnica antes de abrir o código.
   - Siga a hierarquia obrigatória: `GEMINI.md` $\rightarrow$ [`docs/INDEX.md`](docs/INDEX.md) (Roteador Temático) $\rightarrow$ Especificação Técnica do Domínio (`docs/app/` ou `docs/infra/`) $\rightarrow$ Código Seletivo em `app/` ou `scripts/`.
   - Detalhado em: [`.gemini/rules/context-and-doc-navigation.md`](.gemini/rules/context-and-doc-navigation.md).

2. **Fluxo de Trabalho e Guard Rails por Branch:**
   - Todo trabalho em uma branch deve iniciar com um alinhamento prévio cobrindo o escopo, as propostas de implementação, os arquivos a serem alterados e os arquivos a serem criados.
   - Template oficial de alinhamento: [.gemini/templates/branch-scope-template.md](.gemini/templates/branch-scope-template.md).
   - **Guard rail inegociável:** Não alterar arquivos além do estritamente acordado para o objetivo da branch.
   - Detalhado em: [`.gemini/rules/branch-workflow.md`](.gemini/rules/branch-workflow.md).

3. **Proteção da Branch `main` e Matriz Git:**
   - **NUNCA realizar commits diretos na branch `main`.**
   - Comandos de leitura (`status`, `diff`, `show`, `log`, `branch`, `worktree list`) estão **100% liberados**.
   - Comandos de mutação (`checkout`, `switch`, `branch`, `commit`, `push`, `rebase`, `merge`, `reset`, `stash`) **exigem alinhamento e autorização prévia obrigatória**.
   - Conflitos de merge/rebase devem ser resolvidos manualmente com o usuário; proibido forçamento com `--ours`/`--theirs`.
   - Detalhado em: [`.gemini/rules/git-execution-guardrails.md`](.gemini/rules/git-execution-guardrails.md) e [`.gemini/rules/commit-rules.md`](.gemini/rules/commit-rules.md).

4. **Governança de Commits e Actions:**
   - Realizar commits atômicos e progressivos por actions/checklist concluída.
   - Padrão obrigatório: **Conventional Commits** (`feat:`, `chore:`, `docs:`, `test:`, `fix:`, `refactor:`, `perf:`).
   - Validar testes e funcionamento antes de cada commit.
   - Detalhado em: [`.gemini/rules/commit-rules.md`](.gemini/rules/commit-rules.md).

5. **Padrão Exclusivo de Testes (`unittest`) e Ciclo de Infraestrutura:**
   - O framework oficial e exclusivo de testes é o **`unittest`** nativo do Python 3 (`python3 -m unittest ...`). Proibido buscar ou rodar `pytest`.
   - Testes unitários estão liberados para execução automática a qualquer momento.
   - Comandos de infraestrutura física e probes de rede remota (`scripts/check-infra.sh`, SSH, probes de porta) são reservados **estritamente para a fase final de integração** e **apenas se o servidor estiver acessível na rede local**. Se offline, encerra-se com testes locais e `--env-only`.
   - Detalhado em: [`.gemini/rules/testing-and-infra-lifecycle.md`](.gemini/rules/testing-and-infra-lifecycle.md).

6. **Propagação em Cadeia de Documentação (Origem e Destino):**
   - Sempre que uma modificação alterar contratos, interfaces, portas, variáveis ou regras, auditar e propagar as alterações em cadeia para todos os documentos dependentes consultando o grafo em [`docs/INDEX.md`](docs/INDEX.md).
   - Detalhado em: [`.gemini/rules/doc-propagation-lifecycle.md`](.gemini/rules/doc-propagation-lifecycle.md).

7. **Execução Padronizada de Comandos:**
   - Utilizar o [Catálogo Canônico de Comandos Úteis](.gemini/rules/commands.md) para execução de rotinas operacionais, testes, manutenção e daemons.

8. **Padrões de Código, TDD e Workflow de Execução:**
   - Adoção mandatória do ciclo TDD via `unittest` nativo (Red $\rightarrow$ Green $\rightarrow$ Refactor) e linting via `flake8`.
   - Arquitetura cliente-servidor orientada a objetos com separação estrita de responsabilidades (SRP).
   - Proibição absoluta de exceptions genéricas (`except Exception:`) e mensagens sem contexto em favor da hierarquia oficial em [`app/exceptions.py`](app/exceptions.py).
   - Mascaramento e sanitização obrigatória de dados sensíveis (senhas, hashes e chaves de sessão HMAC) em logs e telas.
   - Detalhado em: [`.gemini/rules/code-standards-and-workflow.md`](.gemini/rules/code-standards-and-workflow.md) e inventário de débitos em [`docs/debts.md`](docs/debts.md).
