# Suporte local e IA opcional do QG RENDA

O atendimento do portal oferece dois modos. Quando escolhido diretamente, o **modo local** usa os conteúdos, guias e estados das fontes do próprio QG RENDA, sem enviar a pergunta a um provedor de IA. Ele continua disponível quando a integração externa não está configurada ou não pode responder.

O **modo IA** usa a API da OpenAI para responder de forma conversacional sobre os temas do portal. É uma opção adicional: a existência do site não depende de contratar esse serviço. O assistente não representa órgãos públicos, não consulta cadastros pessoais, não movimenta dinheiro e não realiza procedimentos administrativos em nome do visitante.

## Escolha do visitante e contexto enviado

O visitante deve optar explicitamente pelo modo IA antes de qualquer envio ao provedor. A opção fica desmarcada inicialmente e só aparece quando o servidor indica disponibilidade. O aviso explica, de forma visível, que a mensagem e o histórico recente usado para continuidade serão enviados à OpenAI. Continuar no modo local permanece possível.

Exemplo de aviso: “No modo IA, sua mensagem e o histórico recente serão enviados à OpenAI para gerar uma resposta. Você pode continuar usando o atendimento local.”

O contexto automático da IA deve se limitar aos guias e às fontes públicas permitidas do portal. Não inclui nome, e-mail, endereço, idade ou outros dados pessoais do responsável, nem o requerimento ou o protocolo particular. Não deve ser construído copiando toda a página HTML, que também contém dados de contato.

O atendimento local e suas correções são consultados antes da IA. Perguntas sobre contato e dados pessoais do responsável são resolvidas localmente, sem encaminhar esses dados ao provedor. Se uma solicitação optativa à IA falhar depois de iniciada, o portal pode produzir uma resposta local; isso não significa que a chamada externa não tenha sido tentada.

As perguntas não são gravadas nos caches de fontes, no relatório mensal, em banco de dados ou em logs da aplicação. O histórico curto da conversa serve apenas à continuidade do atendimento; não deve virar registro de manutenção. O aviso ao visitante deve orientá-lo a não escrever senhas, documentos ou dados sensíveis na mensagem que será enviada ao provedor.

## Credencial e configuração no Render

O responsável fornece sua própria chave da API. Ela fica somente no ambiente do servidor; não deve ser inserida no JavaScript, no HTML, em commits, exemplos de configuração, mensagens de chat ou capturas do painel.

Variáveis da integração:

| Variável | Finalidade |
| --- | --- |
| `OPENAI_API_KEY` | Chave opcional da conta/projeto do responsável. Sem chave válida configurada, a IA fica indisponível e o modo local continua funcionando. |
| `OPENAI_MODEL` | Modelo da API. Padrão recomendado e usado na integração: `gpt-6-luna`. A conta do responsável precisa ter acesso a ele. |
| `QG_AI_DAILY_LIMIT` | Limite de tentativas de IA por dia e por instância: padrão `100`, máximo `1000`; `0` desabilita o modo IA. |

Para incluir a chave sem expô-la nesta conversa:

1. Abra o serviço **qg-renda-portal-independente** no [painel de ambiente do Render](https://dashboard.render.com/web/srv-dbs46sdg1s2s73e4mseg/env).
2. Entre em **Environment → Add Environment Variable**.
3. Informe `OPENAI_API_KEY` e cole o valor diretamente no campo **Value** do painel. Se desejar, ajuste `OPENAI_MODEL` e `QG_AI_DAILY_LIMIT`.
4. Use **Save and deploy** para aplicar as variáveis ao build existente. **Save only** guarda a configuração, mas o serviço só passa a usá-la no próximo deploy.
5. Após a publicação, confira o estado de disponibilidade da IA no próprio atendimento do site ou em `GET /api/support/config`. Essa rota retorna somente `{"ai_available": true}` ou `{"ai_available": false}`, sem retornar ou listar valores de variáveis.

Se o estado público já indicar que a integração está configurada, não é necessário copiar a chave novamente. Esse indicador não é uma chamada paga de teste e, sozinho, não comprova crédito ou permissão efetiva para gerar respostas; uma solicitação real e optativa ainda pode receber erro do provedor.

O conector disponível `mcp__codex_apps__render_update_environment_variables` permite atualizar variáveis por mesclagem, com `replace: false`, sem primeiro recuperar os valores existentes. Ele pode ser usado para parâmetros não secretos autorizados. A chave deve ser inserida pelo responsável no painel; a operação não exige que um agente leia ou publique credenciais.

## Contrato do atendimento do portal

- `GET /api/support/config`: informa se o modo IA está configurado e disponível para seleção, pelo booleano `ai_available`.
- `GET /api/support/status`: diagnóstico de configuração com `ai_available` e `configuration_issue`. O motivo é uma categoria fixa: `key_missing`, `key_invalid`, `model_invalid`, `ai_disabled`, `usage_unavailable` ou `null` quando disponível. Não retorna chave, trecho, tamanho, modelo configurado nem valores de variáveis. O diagnóstico não chama o provedor e não comprova crédito ou autorização da conta.
- `POST /api/support/respond`: recebe o pedido de atendimento e retorna `mode`, `reply` e `links`, além de um `reason` opcional quando houver fallback. A interface usa o modo efetivamente retornado para identificar a origem da resposta.

Sem chave própria configurada, o suporte local continua funcionando e a opção externa permanece indisponível. A chave não é necessária para abrir o site, ler os guias ou consultar as fontes públicas.

## Modelo e chamada à OpenAI

Na documentação oficial consultada, **`gpt-6-luna`** é indicado para tarefas focadas, de alto volume e sensíveis a custo. O modelo suporta `v1/responses` e aceita `reasoning.effort: "none"`. Esse ajuste evita destinar o orçamento curto de saída a raciocínio nessa configuração.

Os IDs `gpt-4.1-mini` e `gpt-5-mini` ainda aparecem em páginas oficiais, mas estão marcados como **Deprecated** na documentação atual; não são a recomendação inicial desta integração.

A chamada ocorre somente no backend:

```http
POST https://api.openai.com/v1/responses
Authorization: Bearer <chave mantida no servidor>
Content-Type: application/json
```

Estrutura de referência, sem dados pessoais:

```json
{
  "model": "gpt-6-luna",
  "instructions": "Oriente em português com base no contexto público autorizado do QG RENDA. O projeto é independente e não representa o governo.",
  "input": [
    {"role": "user", "content": "Onde encontro o catálogo de serviços oficiais?"}
  ],
  "reasoning": {"effort": "none"},
  "max_output_tokens": 600,
  "store": false,
  "tools": []
}
```

`max_output_tokens` limita os tokens gerados, incluindo texto visível e tokens de raciocínio quando estes são usados. `store: false` desabilita o armazenamento da resposta para recuperação posterior pela API; **não equivale a uma promessa de retenção zero pelo provedor**. As regras de retenção e monitoramento aplicáveis são as da conta e da política da OpenAI.

Em HTTP/JSON puro, extraia o texto percorrendo `output`, selecionando itens `type: "message"` e blocos de conteúdo `type: "output_text"`. Não presuma que o primeiro item de saída é texto: o formato também admite outros tipos de item. A propriedade agregada `output_text` descrita na documentação é uma conveniência dos SDKs Python e JavaScript, não um campo obrigatório da resposta HTTP.

Resposta vazia, erro do provedor, limite excedido ou indisponibilidade devem produzir uma resposta local, identificada como tal. A integração não precisa de ferramentas externas, navegação arbitrária ou execução de ações para responder sobre os guias do portal.

## Limites operacionais e custos

Os limites definidos para esta implementação são:

- mensagem atual de até **300 caracteres**;
- histórico de até **quatro entradas**, com até **300 caracteres** por entrada;
- saída de até **600 tokens**;
- timeout total de **25 segundos**, sem tentativas automáticas adicionais;
- até **10 pedidos por minuto por cliente**, **30 por minuto globalmente** e **duas chamadas simultâneas**;
- orçamento padrão de **100 tentativas de IA por dia e por instância**, configurável por `QG_AI_DAILY_LIMIT`.

O contador diário usa um arquivo local em `/tmp`, sem perguntas ou endereços IP no registro, e muda de dia em **America/Belem**. Esse armazenamento é efêmero: reinícios, novos deploys e múltiplas instâncias impedem tratá-lo como teto financeiro garantido para toda a conta.

O uso real da API segue a cobrança e as permissões da conta do responsável. Os limites do portal reduzem o volume de solicitações, mas não substituem o acompanhamento de consumo e os controles disponíveis no provedor. Não é informado preço fixo ou promessa de gratuidade: os valores atuais devem ser consultados na página oficial de preços. Esta configuração não cria conta, crédito ou recurso pago automaticamente.

## Referências oficiais

Conferidas em **20 de novembro de 2026**, por leitura pública de documentação, sem autenticação ou chamada de inferência:

- [Criar uma resposta — Responses API](https://platform.openai.com/docs/api-reference/responses/create): endpoint, `max_output_tokens`, `store`, itens de saída e conveniência `output_text` dos SDKs.
- [Catálogo atual de modelos](https://developers.openai.com/api/docs/models.md).
- [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna.md): ID, suporte a Responses e níveis de raciocínio.
- [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini.md) e [GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini.md): situação de depreciação.
- [Controles de dados da API](https://platform.openai.com/docs/guides/your-data): armazenamento de estado e monitoramento de abuso.
- [Preços atuais da API](https://developers.openai.com/api/docs/pricing).
- [Variáveis e segredos no Render](https://render.com/docs/configure-environment-variables): configuração no painel e diferença entre salvar e publicar.
