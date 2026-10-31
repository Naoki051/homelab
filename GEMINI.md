# Diretrizes de Desenvolvimento do Projeto Homelab

Este projeto utiliza regras de governança e guard rails documentadas em:
- [Fluxo de Trabalho e Guard Rails por Branch](.gemini/rules/branch-workflow.md)
- [Diretrizes de Commits, Proteção da Main e Actions](.gemini/rules/commit-rules.md)

## Regras Ativas:

1. **Fluxo de Trabalho e Guard Rails por Branch:**
   - Todo trabalho em uma branch deve iniciar com um alinhamento prévio cobrindo o escopo, as propostas de implementação, os arquivos a serem alterados e os arquivos a serem criados.
   - Template oficial de alinhamento: [.gemini/templates/branch-scope-template.md](.gemini/templates/branch-scope-template.md).
   - **Guard rail mandatório:** Não alterar arquivos além do estritamente necessário para o objetivo da branch.

2. **Proteção da Branch `main`:**
   - **NUNCA realizar commits diretos na branch `main`.**
   - Caso seja estritamente necessário commitar na `main`, deve-se **sempre perguntar e obter autorização explícita do usuário antes**.
   - Toda alteração deve ser desenvolvida em branch própria e integrada via merge aprovado.

3. **Governança de Commits e Commits por Actions:**
   - Realizar commits atômicos e progressivos por actions/checklist conforme detalhado em [.gemini/rules/commit-rules.md](.gemini/rules/commit-rules.md).
   - Padrão obrigatório: **Conventional Commits** (`feat:`, `chore:`, `docs:`, `test:`, `fix:`, `refactor:`, `perf:`).
   - Validar testes e funcionamento antes de cada commit.
