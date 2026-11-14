# PostgreSQL fictício — teste isolado do QG RENDA

Este conteúdo pertence à branch de preparação de pagamentos, **não está implantado no site** e **não habilita transações reais**.

## Finalidade

Executar as primeiras verificações de persistência, eventos repetidos e atomicidade com um PostgreSQL efêmero em GitHub Actions, sem cadastrar clientes reais ou dados pessoais.

- Migração: `db/migrations/001_staging_inbox.sql`
- Testes: `tests/test_staging_postgres.py`
- CI: `.github/workflows/staging-postgres.yml`

O banco de teste existe apenas durante a execução do workflow. Os nomes `qgr_staging.webhook_events` e `qgr_staging.operations` foram criados para simular eventos do **Asaas Sandbox**. Não representam confirmação de recebimentos, reserva financeira, saldo ou pagamentos de usuários.

## Controles validados

- Eventos com mesmo `event_id` não criam linhas duplicadas; o contador de entregas é incrementado.
- Operações fictícias com mesma `idempotency_key` não criam duas solicitações.
- Restrições SQL recusam a identificação `asaas_production` e valores negativos.
- Transações abortadas fazem rollback.
- Não há chave de produção, rota de Pix real nem acesso a dados de usuários.

## Pendências antes de criar infraestrutura financeira real

1. Definir organização e responsável elegíveis; aprovação de conta Asaas e escopos específicos não foram verificadas pela API.
2. Contratar/autorizar explicitamente PostgreSQL persistente e backup restaurável. O PostgreSQL gratuito do Render expira após 30 dias; não é adequado para saldos ou dados financeiros reais.
3. Migrar o domínio do backend atual de SQLite para PostgreSQL com testes de concorrência e reconciliação de dados. **Esta migração é apenas das tabelas fictícias**, não de `users`, `ledger` ou `withdrawals`.
4. Implantar staging em ambiente separado, sem apontar o site demonstrativo para o banco de produção.
5. Criar e auditar lógica de dinheiro real em um futuro serviço independente, com controles antifraude, conciliação, autorização e liberação explícita.

## Como acompanhar

O workflow `Validar PostgreSQL fictício em CI` é executado automaticamente quando arquivos da branch são alterados e na revisão do Pull Request. Não há necessidade de colocar credenciais pessoais no GitHub.

**Não** utilize estas tabelas como carteira ou comprovante financeiro e **não** coloque chave API do Asaas em commits, prints ou comentários de Pull Request.

Referências:
- [Render Free](https://render.com/docs/free)
- [Asaas Sandbox](https://docs.asaas.com/docs/sandbox)
