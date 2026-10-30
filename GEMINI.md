# Diretrizes de Desenvolvimento do Projeto Homelab

Este projeto utiliza regras de governança e guard rails por branch documentadas em [.gemini/rules/branch-workflow.md](file://.gemini/rules/branch-workflow.md).

## Regras Ativas:
1. **Fluxo de Trabalho e Guard Rails por Branch:**
   - Todo trabalho em uma branch deve iniciar com um alinhamento prévio cobrindo o escopo, as propostas de implementação, os arquivos a serem alterados e os arquivos a serem criados.
   - Template oficial de alinhamento: [.gemini/templates/branch-scope-template.md](file://.gemini/templates/branch-scope-template.md).
   - **Guard rail mandatório:** Não alterar arquivos além do estritamente necessário para o objetivo da branch.
2. **Commits Incrementais via Conventional Commits:**
   - Realizar commits atômicos e progressivos conforme os itens do checklist da branch forem sendo entregues.
   - Padrão obrigatório: Conventional Commits (`feat:`, `chore:`, `docs:`, `test:`, `fix:`).
