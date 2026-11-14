# Integração Asaas Sandbox — QG RENDA

**Estado:** integração técnica em testes, **sem pagamentos ou saques reais**. Toda movimentação remota usa somente `https://api-sandbox.asaas.com/v3`. Não configure chaves de produção.

## Passo 1 — Sandbox Asaas
Uma pessoa elegível para operar a conta, acompanhada de responsável legal quando necessário, deve criar e habilitar sua conta de **Sandbox** no [portal Asaas](https://docs.asaas.com/docs/sandbox). O Sandbox não movimenta valores verdadeiros.

Crie uma chave exclusiva de **Sandbox** (prefixo `$aact_hmlg_`). Não compartilhe a chave em conversas, prints, arquivos, GitHub ou frontend. Nunca envie documento pessoal de terceiros em testes; use dados fictícios aceitos pelo provedor.

## Passo 2 — Configuração no Render (serviço já existente)
Serviço correto: [qg-renda-demo-tsjn](https://dashboard.render.com/web/srv-dbs2kok9v7es73bh92t0).

No painel **Environment**, mantenha:

| Variável | Valor |
|---|---|
| `DEMO_ONLY` | `true` |
| `ASAAS_SANDBOX_ENABLED` | `true` |
| `ASAAS_SANDBOX_OUTBOUND_ENABLED` | `false` inicialmente |
| `ASAAS_SANDBOX_TRANSFER_TESTS_ENABLED` | `false` |
| `COOKIE_SECURE` | `true` |

Após obter a conta Sandbox, configure **somente no Render**:
- `ASAAS_SANDBOX_API_KEY`: chave de API exclusiva da homologação, nunca de produção;
- `ASAAS_SANDBOX_WEBHOOK_TOKEN`: token aleatório com no mínimo 32 caracteres, diferente da API key; configure exatamente o mesmo token no Asaas, caso ative o webhook.

A URL de webhook é:
`https://qg-renda-demo-tsjn.onrender.com/api/integrations/asaas/sandbox/webhook`

Se/quando a chave de Sandbox estiver configurada, `ASAAS_SANDBOX_OUTBOUND_ENABLED=true` libera **apenas requisições de cobrança Sandbox feitas por administrador autenticado**. Não há vínculo com a carteira. Testes de transferência permanecem bloqueados até habilitar separadamente `ASAAS_SANDBOX_TRANSFER_TESTS_ENABLED=true` (somente para simulações autorizadas).

## Rotas disponíveis para a administração

| Método e caminho | Função |
|---|---|
| `GET /api/admin/asaas/status` | Mostra flags, sem revelar segredos |
| `POST /api/admin/asaas/sandbox/charges` | Cria cobrança Pix fictícia se habilitada |
| `POST /api/admin/asaas/sandbox/transfers` | Solicita transferência fictícia, **desativada** |
| `GET /api/admin/asaas/sandbox/events` | Lista IDs dos webhooks já registrados |
| `POST /api/integrations/asaas/sandbox/webhook` | Recebe eventos autenticados; deduplica e não altera saldos |

As rotas administrativas exigem sessão de administrador e header de proteção `X-CSRF-Token` nas requisições POST. Os webhooks exigem o header `asaas-access-token`.

O código rejeita chaves com prefixo de produção e não permite URL do provedor personalizada. Valores máximos em testes: R$ 100 por cobrança ou transferência de Sandbox.

## Limitações importantes

- O serviço Render Free não fornece armazenamento persistente para SQLite. Webhooks salvos podem desaparecer em reinícios. **Não** use essa base como contabilidade financeira.
- Não há integração que converta eventos Asaas em `balance_cents`, `ledger` ou `withdrawals`.
- Transferências Sandbox **não** atendem pedidos de saque de usuários. Nem uma transação concluída no Sandbox significa pagamento real.
- Ainda faltam banco de dados persistente, auditoria, antifraude, conciliação, controle de saldo lastreado em fundos, identificação fiscal e revisão legal/contratual antes de qualquer migração.
- O uso em produção precisa de outro projeto revisado, credenciais separadas e ativação deliberada após aprovação do provedor, sem reaproveitar os endpoints de demonstração.

### Documentação oficial Asaas
- https://docs.asaas.com/docs/sandbox
- https://docs.asaas.com/docs/autentica%C3%A7%C3%A3o-1
- https://docs.asaas.com/reference/create-new-payment
- https://docs.asaas.com/reference/transferir-para-conta-de-outra-instituicao-ou-chave-pix
- https://docs.asaas.com/docs/receba-eventos-do-asaas-no-seu-endpoint-de-webhook
