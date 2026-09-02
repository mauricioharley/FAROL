# Painel gerencial

**Construído e em funcionamento.** Responde "estamos melhorando? quem precisa de atenção?" - risco
agregado, não achado individual. Voltado a quem decide (secretário, DPO, coordenação de dados
abertos), diferente do [painel técnico](painel-tecnico.md) (nível recurso, "por que isso foi
sinalizado?").

!!! info "Captura de tela pendente"
    Esta página ainda não tem captura de tela embutida - pendência de documentação, não do
    componente em si (que está funcional e testado). Segue a mesma regra do painel técnico
    quando for gerada: só ambiente sintético, nunca achado real.

## Acesso e login

`https://<host>:8080/gerencial` - mesmo domínio e certificado do painel técnico, atrás do
mesmo terminador TLS (`painel-nginx`), mas **credencial e sessão próprias** desde 2026-08-22
(`FAROL_GERENCIAL_USER`/`FAROL_GERENCIAL_PASSWORD`, separadas de
`FAROL_TECNICO_USER`/`FAROL_TECNICO_PASSWORD` do painel técnico - são públicos diferentes, quem
decide não é necessariamente quem opera o motor). O painel gerencial continua sem tela de
login própria dentro do próprio app React: se a sessão não existir ou tiver expirado, qualquer
chamada à API do painel gerencial devolve `401` e a página redireciona para o formulário
server-rendered em `/login-gerencial`. Uma sessão do painel técnico **não** abre a API do
gerencial, e vice-versa.

## Seletor de ambiente

Como no painel técnico, alterna entre **Produção** e **Sintético** - cada achado é gravado com
uma tag de ambiente, os dois nunca se misturam.

## Visão geral (cartões)

- **Taxa de liberação** - `liberados / (liberados + alertados + bloqueados)`, em
  percentual. Indicador operacional (quanto do que foi avaliado saiu liberado), não uma
  auditoria de conformidade LGPD - deliberadamente simples e explicável, não um índice
  composto opaco. Fica em branco (`-`) quando não há nenhum achado avaliado ainda - `0%`
  seria enganoso (sugeriria um cenário de risco onde na verdade não há dado nenhum).
- **Cobertura do catálogo** - fração de achados com resultado definitivo (fora
  `nao_analisado`, que não chegou a ser avaliado) sobre o total. "Não olhamos" e "olhamos e
  não achamos nada" são informações diferentes - por isso ficam em dois números separados, não
  misturados no score de conformidade.
- **Recursos auditados**, **Pendentes de revisão**, **Confirmados como positivo** - mesmos
  conceitos do painel técnico, agregados.

## Achados por dia (tendência)

Gráfico de barra dos últimos 30 dias corridos - barra cinza é o total de achados do dia,
sobreposição vermelha é a fatia que virou `alertar`/`bloquear`. Sem seleção de período
customizado ainda (ver limitação abaixo).

## Ranking por órgão

Tabela ordenada por achado de alto risco (`alertar`/`bloquear`), decrescente - até 30
organizações. Colunas: recursos auditados, achados de alto risco, pendentes de revisão, não
analisados, mais uma barra horizontal proporcional ao maior valor da lista, para comparação
visual rápida.

## Limitações conhecidas

- Sem seleção de período customizado no gráfico de tendência (sempre os últimos 30 dias).
- Ranking por órgão limitado às 30 primeiras organizações por volume de achado de alto risco.
- Sem teste automatizado próprio (o backend que ele consome, sim - ver
  [Referência de API](../referencia-api/pii-engine.md) e o README de `painel/`).
