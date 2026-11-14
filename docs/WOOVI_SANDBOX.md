# Integração Woovi Sandbox — QG RENDA

**Status: branch de desenvolvimento, não implantada no Render.**
Esta integração realiza apenas testes de cobranças Pix fictícias e webhooks assinados.
**Não faz transferências reais, não gera saldos financeiros nem ativa saques.**

## Referências oficiais

- Ambiente Sandbox: https://developers.woovi.com/docs/test-environment
- API Sandbox: https://api.woovi-sandbox.com
- Documentação de cobrança: https://developers.woovi.com/docs/charge/how-to-create-charge-using-api
- Autenticação AppID: https://developers.woovi.com/en/docs/apis/getting-started-api
- Assinatura de webhook: https://developers.woovi.com/docs/webhook/seguranca/webhook-public-keys
- Chave pública específica do Sandbox: https://developers.woovi.com/en/docs/webhook/seguranca/webhook-sandbox-public-key

## Cadastro Sandbox

Crie uma **conta separada no Sandbox** da Woovi em https://app.woovi-sandbox.com/ conforme requisitos de cadastro e elegibilidade do provedor. Uma conta Sandbox não equivale à aprovação para movimentar dinheiro em produção. Use dados de teste autorizados, nunca documentos de terceiros.

Crie um AppID de **API Sandbox**, separado de qualquer chave real. Conforme a documentação, envie o AppID bruto no header `Authorization`, sem `Bearer`. **Não publique o AppID** em GitHub, frontend, README, chat, prints ou logs.

## Configuração local exclusivamente para testes

Defina em ambiente local seguro, **nunca no repositório**:

| Variável | Valor/descrição |
|---|---|
| `DEMO_ONLY` | `true` |
| `WOOVI_SANDBOX_ENABLED` | `true` para testar as rotas |
| `WOOVI_SANDBOX_OUTBOUND_ENABLED` | `false` por padrão |
| `WOOVI_SANDBOX_APP_ID` | segredo de API **apenas do Sandbox**; não versionar |
| `WOOVI_SANDBOX_WEBHOOK_PUBLIC_KEY_PEM` | chave **pública** RSA do Sandbox obtida nas instruções oficiais |
| `COOKIE_SECURE` | `true` quando rodar com HTTPS |

Só depois de conferir a conta de testes é possível configurar `WOOVI_SANDBOX_OUTBOUND_ENABLED=true` para **criar cobrança fictícia via Sandbox**. O domínio de saída está fixo em `https://api.woovi-sandbox.com`; não há modo para redirecionar à API real.

Não altere as variáveis do serviço de produção `qg-renda-demo-tsjn`. Esta branch não está implantada nele.

## Rotas implementadas (ainda não publicadas)

| Método | Rota | Proteção |
|---|---|---|
| `GET` | `/api/admin/woovi/status` | Apenas administrador autenticado; sem exibir segredos |
| `POST` | `/api/admin/woovi/sandbox/charges` | Apenas administrador + CSRF + duas flags + AppID de Sandbox |
| `POST` | `/api/integrations/woovi/sandbox/webhook` | RSA-SHA256 do corpo bruto com a chave pública **do Sandbox** |
| `GET` | `/api/admin/woovi/sandbox/events` | Apenas administrador + modo demo |

Cobrança fictícia de teste aceita `value_cents` entre 100 e 10000 (R$ 1,00–100,00 em unidades nominais do Sandbox), `correlation_id` único e `comment` opcional. A API externa recebe `value` **em centavos**, `correlationID` e `comment`. Nenhum QR Code, boleto ou link de pagamento é publicado para usuários.

O webhook valida `x-webhook-signature` por RSA-SHA256 em cima do corpo bruto, **antes** de analisar o JSON. Registra metadados mínimos do evento para deduplicação, mas **nunca altera** `users.balance_cents`, `ledger` nem `withdrawals`. A chave pública do Sandbox pode mudar: consulte a documentação e atualize a configuração verificada quando houver rotação.

A persistência atual é **SQLite temporário**: a tabela de webhooks de teste pode ser perdida ao reiniciar o container. Não serve para conciliação financeira, saldos, reembolsos ou contabilidade de produção.

### Executar testes automáticos

`python -m pip install -r requirements-dev.txt`
`python -m unittest discover -s tests -v`

Os testes de criação de cobrança utilizam um cliente HTTP simulado; não há chamada real à Woovi nem movimentação de valores.

## Antes de qualquer produção

Exigem-se responsável/entidade elegíveis, verificação exigida pelo provedor, contrato comercial, autorizações de API, PostgreSQL persistente com backup, conciliação, autorização de saques, limites, prevenção de fraude e revisão de segurança/privacidade. **Não use esta integração de Sandbox como gateway de produção.**

O site público permanecerá no Asaas Sandbox e `DEMO_ONLY=true` até aprovação técnica/comercial independente.
