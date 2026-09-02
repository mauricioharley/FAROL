# Rodar o scanner

O `scanner` audita um catálogo CKAN inteiro: lista organizações e recursos via API, chama o
`pii-engine` recurso por recurso, e grava o resultado no Postgres do FAROL.

Desde 2026-08-22, disparar, acompanhar e cancelar uma auditoria acontece **pela tela `/scan`
do painel técnico** - nenhuma linha de comando é necessária, nem de administrador técnico. O
`scanner` roda como serviço permanente, alcançável só de dentro da rede interna do compose; o
painel autentica o humano e repassa a chamada.

## Disparar um scan

Em `https://<host>:8080/scan`:

1. **URL base do CKAN a auditar** - o portal alvo (o CKAN de teste local, o portal de
   produção da prefeitura, ou qualquer outro CKAN de terceiro, seguindo a mesma disciplina de
   escopo mínimo já usada contra portal de terceiro quando o alvo não é seu próprio catálogo).
2. **Carregar organizações** - busca ao vivo a lista de organizações do CKAN informado
   (`organization_list`, endpoint público do próprio CKAN). Marque as que quer incluir -
   nenhuma marcada inclui todas.
3. **Formatos de arquivo** - marque os formatos a incluir (`.csv`, `.xlsx` etc.) - nenhum
   marcado inclui todos os formatos que a Camada 0 sabe extrair. Um recurso cuja extensão não
   bate com nenhum formato marcado é excluído do escopo, sem ser baixado.
4. **Modo incremental** - quando marcado, um novo scan contra o mesmo CKAN inclui só dataset
   novo ou alterado desde a última vez (comparando a data de modificação que o próprio CKAN já
   devolve, sem baixar nada a mais só pra descobrir isso). Útil pra reauditar um catálogo já
   conhecido sem pagar o custo de reprocessar tudo de novo.
5. **Verificar certificado TLS** - desmarque só contra um CKAN de teste com certificado
   autoassinado (ex. o CKAN local da Fase 0-2); contra qualquer portal real, mantenha marcado.

O ambiente (`Sintético`/`Produção`) rotula a origem do achado - mesmo significado de sempre
(ver [Segurança e privacidade](../seguranca-e-privacidade.md)).

## Acompanhar e cancelar

A seção "Execuções" mostra as últimas rodadas, com barra de progresso (atualizada a cada 3
segundos), o recurso sendo processado no momento, e um botão **Cancelar** em qualquer execução
ainda rodando. O cancelamento para entre um recurso e outro, nunca no meio de um download já
em andamento - tudo que já foi processado até ali continua visível no painel técnico
normalmente, mesmo com o scan interrompido (achado é gravado recurso a recurso, não em lote no
final).

## O que ele grava

Cada resposta do `pii-engine` (`veredito`, `score_risco`, `achados`) é persistida em `achados`,
e o progresso da execução (`total`, `processados`, `status`) em `execucoes` - o painel técnico
lê as duas tabelas.

## Sobre agendamento automático

Não existe agendamento automático implementado (nenhum cron/scheduler embutido) - cada scan é
disparado manualmente, pela tela `/scan`. O modo incremental (acima) cobre a necessidade mais
comum (reavaliar dataset novo ou alterado) sem precisar de agendamento. Ver
[roadmap](roadmap.md) para o que está planejado, não construído.
