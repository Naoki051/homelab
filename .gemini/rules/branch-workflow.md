# Regra de Desenvolvimento: Fluxo de Trabalho e Guard Rails por Branch

> **Escopo da Regra:** Exclusiva deste projeto (`homelab`).  
> **Aplicação:** Mandatória para qualquer sessão, agente de IA ou desenvolvedor atuando nas branches deste repositório.

---

## 1. Princípio Fundamental e Guard Rails

1. **Escopo Estrito e Mínimo:**
   - **NUNCA** alterar, refatorar, renomear ou excluir arquivos que não estejam explicitamente cobertos pelo objetivo da branch atual.
   - Guard rail inegociável: antes de editar qualquer linha de código ou arquivo de configuração, deve-se responder e validar as perguntas de alinhamento.

2. **Planejar Antes de Agir:**
   - Nenhum código deve ser implementado sem antes apresentar a proposta técnica e mapear exatamente onde e como o projeto será modificado.

---

## 2. Alinhamento Inicial Obrigatório (Perguntas de Kickoff)

Ao iniciar uma nova branch ou uma nova tarefa dentro de uma branch, **deve-se sempre conduzir uma conversa inicial estruturada respondendo obrigatoriamente aos 6 pontos abaixo**:

1. **O que vamos fazer nessa branch?**
   - Definir de forma clara, concisa e objetiva o propósito funcional da branch.
2. **Apresentar propostas de implementação:**
   - Se ainda não houver uma solução ou especificação definida, apresentar opções viáveis de arquitetura ou abordagem para decisão antes de codificar.
3. **Como vamos fazer?**
   - Descrever a estratégia técnica, bibliotecas/ferramentas a serem usadas e o fluxo lógico.
4. **Olhar dentro do projeto onde vamos atuar:**
   - Identificar a estrutura de diretórios e o estado atual do repositório relevante para a tarefa (ex: `app/`, `docs/`, `scripts/`).
5. **Será preciso alterar arquivos?**
   - Mapear quais arquivos existentes serão alterados e detalhar exatamente *como* e *por que* serão alterados.
6. **Vai precisar criar arquivos?**
   - Informar exatamente quais novos arquivos serão criados, seus caminhos relativos e os propósitos de cada um.

---

## 3. Uso Obrigatório do Template de Alinhamento

Para formalizar o alinhamento da branch, deve-se utilizar como base o template:
- [`.gemini/templates/branch-scope-template.md`](file://.gemini/templates/branch-scope-template.md)

Esse template pode ser usado na conversa inicial e, se necessário para rastreabilidade, registrado na documentação técnica da branch sob a pasta `docs/`.

---

## 4. Checklist de Guard Rails para Execução

Antes de submeter ou finalizar qualquer alteração na branch, verifique:
- [ ] As mudanças estão 100% restritas ao escopo inicial acordado?
- [ ] Foram criados apenas os arquivos previamente listados no kickoff?
- [ ] Nenhum arquivo fora do escopo foi modificado ou apagado acidentalmente?
- [ ] Arquivos de configuração e infraestrutura permaneceram intactos, a menos que fossem o objetivo direto da branch?

---

## 5. Diretriz de Commits

Para a especificação completa sobre commits atômicos por action, padrões do Conventional Commits e a regra inegociável de **proteção contra commits diretos na `main`**, consulte:
- [`.gemini/rules/commit-rules.md`](commit-rules.md)

