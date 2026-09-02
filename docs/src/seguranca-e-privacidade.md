# Segurança e privacidade

Estas são regras de arquitetura, não recomendações - o FAROL existe para reduzir exposição de
dado pessoal, então a própria ferramenta não pode se tornar uma fonte nova de exposição.

## O motor nunca grava nem loga o valor bruto de PII

Em nenhuma camada (1, 2 ou 3) o valor do campo é persistido, logado ou retornado - só
`campo`/`categoria`/`confiança`/`camada`. O Postgres do FAROL (`achados`) nunca tem uma coluna
para o valor encontrado. Isso vale em dobro a partir do momento em que o dado por trás do achado
é real (não sintético).

## Camada 2 e 3 rodam sempre localmente

Presidio/spaCy (Camada 2) e o LLM (Camada 3, via llama.cpp) rodam no mesmo host, nunca como
chamada a uma API de terceiro (OpenAI, Anthropic, etc.). Mandar conteúdo de um recurso para fora
recriaria exatamente o tipo de vazamento que a ferramenta existe para prevenir - mesmo que a
intenção fosse só classificação, não armazenamento.

## O painel exige autenticação a partir do momento em que pode exibir achado real

Antes disso (só dado sintético), autenticação é discricionária. A partir daí, é obrigatória - o
FAROL usa login por sessão (formulário, cookie assinado, nunca HTTP Basic), nunca a mesma para
os dois painéis: **painel técnico** (`/login`, `FAROL_TECNICO_USER`/`PASSWORD`) e **painel
gerencial** (`/login-gerencial`, `FAROL_GERENCIAL_USER`/`PASSWORD`, credencial e sessão
próprias desde 2026-08-22 - uma nunca abre a rota da outra) são públicos diferentes, ver
[Variáveis de ambiente](instalacao/variaveis-de-ambiente.md). Dentro de cada painel, a
credencial ainda é única e compartilhada, não uma conta por pessoa - isso identifica "quem
passou pelo login daquele painel", não necessariamente uma pessoa única. Se mais de uma pessoa
revisar achado no mesmo painel, o próximo passo é credencial por pessoa ali, não voltar a um
campo de texto livre para "quem revisou".

## O painel nunca renderiza o valor de PII encontrado

Mesmo tendo achado com alta confiança, a tela de revisão não mostra o dado bruto - mostra
`campo`/`categoria`/`confiança` e, quando configurado (`FAROL_PORTAL_*`), um link direto para o
recurso original no portal de origem, onde quem revisa pode ver o dado no contexto real, sem o
FAROL precisar reproduzir PII na própria interface.

## Dado real só entra em ambiente de teste como exceção controlada, nunca como padrão

O CKAN de teste usado no desenvolvimento deste projeto só recebe dado sintético. A única exceção
documentada é a leitura em memória, direto de um mount read-only de produção, sem cópia para
nenhum outro lugar - um padrão específico de auditoria interna, não uma regra geral para qualquer
instalação do FAROL.

## Dado de terceiro (auditoria de catálogo que não é o seu) segue regra mais restrita

Ao apontar o scanner a um catálogo que não é da sua própria organização:

- Escopo mínimo - audite o que precisa auditar, não uma varredura completa do catálogo alheio
  sem necessidade.
- Sempre via download HTTP do `resource["url"]`, nunca um atalho de disco local (que só existe,
  quando existe, para o seu próprio CKAN).
- Download de recurso tem teto de tamanho (`_TAMANHO_MAXIMO_DOWNLOAD`, 200MB, `pii-engine`) -
  o conteúdo baixado fica inteiro em memória (nunca em arquivo em disco), então escanear um
  catálogo de terceiro com escopo amplo e recurso muito grande sem esse teto arriscaria estourar
  a RAM do serviço, não o disco. Rejeitado pelo `Content-Length` declarado quando existe; durante
  o streaming, como reforço, quando não.
- **Um achado real de PII em dado de terceiro nunca vira material de demonstração, documentação
  pública ou conteúdo de divulgação** - e não é uma decisão de quem opera o FAROL escalar
  sozinho. O canal correto é o DPO/encarregado de dados do órgão dono do dataset, não o seu.

## Escalação de achado confirmado

Um achado com revisão humana `confirmado_positivo` sobre dado real (da sua própria organização)
é um incidente real, que deve ser escalado ao canal oficial de DPO/encarregado de dados - trilha
independente do cronograma de qualquer projeto ou entrega. O FAROL sinaliza; a decisão e a ação
sobre o achado são sempre humanas.

## Base legal do tratamento feito pelo próprio FAROL

O FAROL, ao escanear um recurso publicado no catálogo, lê e classifica valores que podem ser
dado pessoal de terceiros (munícipe, servidor) - isso é, em si, tratamento de dado pessoal pelo
órgão que opera a ferramenta (Art. 5º, X, LGPD), mesmo que o valor bruto nunca seja persistido
(ver seção acima). As salvaguardas técnicas deste documento reduzem o risco desse tratamento;
não substituem a necessidade de uma base legal para ele.

A base primária é o cumprimento de obrigação legal/regulatória pelo controlador (Art. 7º, II,
c/c Art. 23, caput, LGPD): o próprio órgão é controlador do dado publicado no catálogo, e tem o
dever de segurança e prevenção (Art. 6º, VII; Art. 46) sobre esse dado - auditar o que ele mesmo
publicou, para identificar exposição indevida antes que um terceiro o faça, decorre desse dever,
não é uma finalidade nova e desvinculada.

Como fundamento subsidiário, cabe legítimo interesse (Art. 7º, IX) para a finalidade específica
de auditoria de conformidade e segurança do catálogo - sujeito ao teste de balanceamento entre
esse interesse e os direitos e liberdades fundamentais do titular (Art. 10), documentado
separadamente pelo órgão/encarregado, não pela ferramenta.

O enquadramento final entre essas hipóteses (e a formalização em ato normativo, política interna
ou registro de operações de tratamento do órgão) é decisão do controlador/encarregado, não algo
que o FAROL resolve sozinho ao rodar.

## Retenção do metadado de achados

A tabela `achados` nunca grava o valor bruto de PII (ver seção acima), mas grava `campo`,
`categoria`, `executado_por` e `revisado_por` - identificam quem operou o painel ou revelam que
tipo de dado pessoal existe num recurso específico, mesmo sem o valor. A retenção segue um
critério alinhado a auditoria e prestação de contas do órgão: achado retido por um prazo
definido pelo responsável (referência inicial: 2 a 5 anos, a confirmar), com anonimização de
`executado_por` e `revisado_por` após alguns meses da revisão - o agregado estatístico (contagem
por campo/categoria/veredito) permanece para fins de auditoria e série histórica, mas o vínculo
com a pessoa que operou o painel não.

**O expurgo/anonimização ainda não está implementado** - hoje o achado permanece indefinidamente
no banco, sem job de limpeza. Esta seção documenta o critério já decidido para a política; a
implementação do job periódico e o prazo exato ainda precisam ser definidos e construídos em
etapa separada.
