# Avaliação da Camada 3

Conjuntos rotulados para medir precisão/recall do classificador LLM (`app/core/camada3.py`)
por categoria da LGPD, e para orientar ajuste de prompt/few-shot sem depender só de intuição.

Todo o conteúdo aqui é **100% fictício** - município, órgãos, nomes, processos e endereços
foram inventados para este fim, não são dados reais de nenhuma pessoa ou órgão. Por isso,
diferente de outros arquivos de avaliação usados durante o desenvolvimento (que continham
excertos reais e por isso nunca vão a um repositório público), estes ficam versionados.

## Arquivos

- `sintetico_ampliacao_tuning.jsonl` - usado para olhar erros e ajustar o prompt/few-shot.
  Depois de qualquer ajuste em `_EXEMPLOS_POUCOS_DISPAROS`, é normal (e esperado) que a
  acurácia aqui suba - é o conjunto de "treino".
- `sintetico_ampliacao_validacao.jsonl` - nunca deve ser usado para decidir um ajuste de
  prompt. Só serve para reportar o número final, depois que o ajuste já foi decidido a partir
  do conjunto de tuning. Se um ajuste de prompt melhora o tuning mas piora a validação, é sinal
  de overfitting ao conjunto de tuning, não ganho real.

Cada linha tem `campo`, `amostras` (lista de valores fictícios) e `categoria_lgpd_correta`
(uma das chaves de `_CATEGORIA_DESCRICAO` em `camada3.py`).

## Como rodar

Precisa do serviço `llm` de pé (mesma rede do `docker-compose.yml`):

```bash
docker compose run --rm \
  -v $(pwd)/pii-engine/scripts:/app/scripts \
  -v $(pwd)/pii-engine/eval:/app/eval \
  --entrypoint python pii-engine scripts/avaliar_camada3.py \
  eval/sintetico_ampliacao_tuning.jsonl eval/sintetico_ampliacao_validacao.jsonl
```

O script nunca imprime o conteúdo das amostras nos erros reportados, só o nome do campo e a
categoria esperada/prevista - mesma regra de não logar PII que vale para o motor em produção.

## Limitação conhecida

Este conjunto é sintético. Ele é útil para medir se um ajuste de prompt/few-shot generaliza
(em vez de só decorar os poucos exemplos já embutidos no prompt), mas não substitui
validação contra dado real de produção, que é ruidosa por natureza (poucos achados sensíveis
de verdade aparecem por varredura) mas é a medida que finalmente importa.
