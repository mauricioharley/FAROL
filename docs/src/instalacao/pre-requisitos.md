# Pré-requisitos

## Infraestrutura

- **Docker** e **Docker Compose** (plugin `compose`, não o binário `docker-compose` antigo) - todo o FAROL roda containerizado, nenhum componente instala pacote Python direto no host.
- **~4 GB de RAM livres** no mínimo para os serviços do motor (`pii-engine` + Presidio/spaCy);
  some mais **~3 GB** se for subir a Camada 3 (`llm`, Qwen3-4B quantizado via llama.cpp) no mesmo
  host. Sem GPU - tudo roda em CPU, inclusive o LLM.
- **CKAN de destino acessível por HTTP/HTTPS** - o FAROL nunca precisa de acesso a disco do CKAN;
  fala só API + download do `resource["url"]`. Um mount local read-only é uma otimização
  opcional quando scanner e CKAN rodam na mesma máquina, nunca um requisito.

## Rede

Se o CKAN de destino estiver atrás de VPN ou rede interna, o host que roda o `scanner` e o
`pii-engine` precisa alcançar essa rede - eles fazem chamadas HTTP de saída para o CKAN, não o
contrário.

## Conhecimento prévio útil, não obrigatório

- Familiaridade com `docker compose` (build/up/run) - usado em toda a instalação.
- Se for integrar com um CKAN existente via API: uma API key com permissão de leitura no catálogo
  que será auditado.

Próximo passo: [Subir com Docker Compose](subir-com-docker-compose.md).
