# FAROL - detecção de dados pessoais em catálogos de dados abertos

**FAROL** - Framework Aberto de Rastreamento e Observância da LGPD.

FAROL é um motor de detecção de dados pessoais e sensíveis (LGPD) em recursos publicados num
portal CKAN de dados abertos. Ele existe em dois modos, que compartilham o mesmo motor de
detecção e nunca gravam o valor de PII encontrado - só metadados do achado:

- **Auditoria em lote** (`scanner`) - varre um catálogo CKAN já publicado, via API HTTP, e grava
  os achados num painel.
- **Prevenção no upload** (plugin `ckanext-farol-guard`) - intercepta a criação de um recurso
  dentro do próprio CKAN, antes de publicar, e pode recusar o upload na hora. Ver
  [Plugin preventivo](guia-do-administrador/plugin-ckan.md).

## Por que isto existe

Portais de dados abertos publicam recursos vindos de dezenas de sistemas e planilhas diferentes,
muitas vezes sem revisão de conteúdo campo a campo. Um CSV de "diárias de servidores" ou um
GeoJSON de "rede de atendimento" pode carregar CPF, endereço ou nome de pessoa junto do dado que
era, de fato, a intenção publicar. O FAROL audita isso - sinalizando, não corrigindo sozinho.

## Arquitetura em uma página

```
CKAN (produção ou terceiro) → scanner → pii-engine (/v1/scan) → farol-db (Postgres) → painéis
```

O `pii-engine` é o motor de verdade - um serviço HTTP único, sem estado, chamado tanto pelo
scanner quanto pelo plugin preventivo. Ele nunca chama o CKAN de volta: recebe um recurso,
devolve um veredito, e para por aí. Internamente, roda até três camadas de detecção, em ordem
crescente de custo - cada camada só processa o que a anterior não resolveu:

| Camada | Técnica | O que resolve |
|---|---|---|
| **1** | Heurística de nome de coluna + regex de valor (CPF, CNPJ, e-mail, telefone, CEP) | Identificadores estruturados e nomes de campo óbvios (`cpf`, `email`...) |
| **2** | NER (Presidio + spaCy `pt_core_news_lg`), local, nunca um serviço de terceiro | Texto livre: nomes de pessoa, local, organização; mais um reconhecedor customizado para menção categórica de saúde (`saúde mental`, `hiv`...) e CPF/CNPJ dentro de texto corrido |
| **3** | Classificador LLM (Qwen3-4B via llama.cpp, local), só roda sobre o que a Camada 2 já sinalizou | Refina a categoria exata do Art. 5º, II da LGPD (ex. distinguir "convicção religiosa" de menção institucional neutra) |

A Camada 3 nunca decide `bloquear` sozinha - sua confiança é limitada a 0,89 (abaixo do limiar de
bloqueio), então no máximo reforça `alertar` para revisão humana. Ver
[Referência de API](referencia-api/pii-engine.md) para o cálculo exato do veredito.

## Glossário

**Veredito** - resultado agregado de um recurso, um dos quatro valores abaixo:

<span class="chip chip-liberar">liberar</span> nenhum achado, ou achados de baixa confiança.
<span class="chip chip-alertar">alertar</span> achado de risco médio - fila de revisão humana.
<span class="chip chip-bloquear">bloquear</span> achado de alta confiança (Camada 1 ou 2).
<span class="chip chip-nao-analisado">não_analisado</span> o recurso **não foi examinado** - formato
sem extrator, arquivo corrompido, falha de rede ou download que nunca terminou. Distinto de
"examinado e nada encontrado": para efeito de cobertura/auditoria, silêncio nunca significa "sem
risco".

**Ambiente** - `sintetico` (CKAN de teste, só dado fabricado) ou `producao` (dado real do
portal auditado, lido em memória, nunca copiado). Um portal de terceiro (fora da própria
organização que opera o FAROL) também usa a tag `producao`, mas com regras de divulgação
mais restritas - ver [Segurança e privacidade](seguranca-e-privacidade.md).

**Achado** - um registro `campo/categoria/confiança/camada`, nunca o valor bruto encontrado.

**Camada** - qual das três técnicas acima gerou o achado (`1`, `2` ou `3`).

## Onde ir a partir daqui

- Primeira instalação → [Instalação](instalacao/pre-requisitos.md)
- Já rodando, quer usar o painel → [Guia do usuário](guia-do-usuario/painel-tecnico.md)
- Quer rodar uma auditoria → [Guia do administrador](guia-do-administrador/rodar-o-scanner.md)
- Vai integrar outro sistema com o `pii-engine` → [Referência de API](referencia-api/pii-engine.md)
- Algo não funcionou como esperado → [Solução de problemas](solucao-de-problemas.md)
