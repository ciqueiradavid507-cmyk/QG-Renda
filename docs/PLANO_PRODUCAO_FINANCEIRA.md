# Plano de migração do QG RENDA para operação financeira real

> **Status: NÃO APROVADO PARA PRODUÇÃO FINANCEIRA.** Não habilitar saques, cobranças, créditos reais ou alterar `DEMO_ONLY=true` antes do cumprimento dos requisitos abaixo. Este documento é um plano técnico, não autorização legal/regulatória.

## Ambiente verificado em 14/11/2026

- Serviço no Render: `qg-renda-demo-tsjn`, plano `free`, hospedagem `https://qg-renda-demo-tsjn.onrender.com`.
- Backend FastAPI em `main.py`, banco SQLite em disco temporário do container.
- Não há instância PostgreSQL no workspace do Render.
- Asaas: `asaas_sandbox.py` usa apenas `https://api-sandbox.asaas.com/v3`, proteção `DEMO_ONLY`, operações externas desabilitadas inicialmente, webhook Sandbox sem crédito de carteira.
- Repositório GitHub público: nenhum segredo, documento de identificação ou dados financeiros deve ser comitado.

## Pré-requisitos de negócio e operação (todos obrigatórios)

- [ ] Definir a entidade/organização operadora, responsável legal e sua elegibilidade para contratar serviços financeiros; quando houver menor de idade, tratar a operação com responsável adulto conforme as regras do provedor e a legislação aplicável.
- [ ] Obter aprovação comercial do Asaas para conta de produção **e**, separadamente, habilitação de recebimentos e transferências Pix para a finalidade de pagar terceiros.
- [ ] Ter fonte legítima, transparente e documentada de receitas (contratos com anunciantes/patrocinadores). Não prometer rendimento garantido, nem transformar depósitos de usuários em recompensas sem atividade econômica legítima.
- [ ] Definir regras de elegibilidade, verificação de usuários, moderação de tarefas, prevenção a fraude, política de saques, atendimento, termos, privacidade e obrigações tributárias com revisão profissional.
- [ ] Definir precificação/tarifas, limites de pagamentos e reserva financeira para taxas, estornos e falhas.

## Pré-requisitos técnicos de produção

- [ ] **Novo ambiente isolado de produção**: não migrar o banco da demonstração automaticamente nem reutilizar a conta Sandbox, seus tokens ou seus endpoints.
- [ ] **PostgreSQL persistente com backups testados** (não o Free Postgres de 30 dias). Migrar modelos SQLite para esquema PostgreSQL, aplicar migrations e garantir consistência transacional.
- [ ] **Ledger de dupla entrada** com saldos conferíveis e imutabilidade/auditoria, apoiado em recebimentos confirmados e lastreados; jamais confiar apenas em `funding_confirmed` marcado por um administrador.
- [ ] **Transferências com máquina de estados**: `requested -> verified -> reserved -> submitted -> confirmed/failed`; integrar idempotência de envio, identificação de destinatário, limites e reconciliação com extratos/provedor.
- [ ] **Webhooks seguros**: verificar token/assinatura quando aplicável; persistir evento antes de responder; deduplicar IDs; lidar com reenvios, eventos atrasados/fora de ordem, cancelamentos, estornos e inconsistências sem pagar duas vezes.
- [ ] **Controles anti-fraude**: proteção de contas de administração (MFA), limites de taxa e valor, contas de destino verificadas, detecção de tarefas abusivas, revisão de disputas.
- [ ] **Observabilidade**: logs sem dados sensíveis, alertas de falha em pagamentos, dashboards, reconciliação diária, trilha de auditoria, plano de resposta a incidentes e rollback.
- [ ] **Privacidade e segurança**: minimização de dados, consentimentos e bases legais apropriadas, proteção de informações pessoais/financeiras, retenção e exclusão quando aplicáveis.
- [ ] **Teste de carga e segurança**: revisão de código, análise de vulnerabilidades, teste de idempotência sob concorrência, falha de rede após envio de Pix, reinícios, repetição de webhook e restaurar backups.
- [ ] **Go/no-go**: aprovação formal de responsável pela operação, jurídico/compliance, finanças e segurança após validação em homologação; liberar produção gradualmente com limites.

## Etapas recomendadas

1. **Separar ambientes**: deixar `qg-renda-demo-tsjn` como demonstração, sem valores reais, e trabalhar em branch de preparação e homologação.
2. **Migrar persistência**: adotar PostgreSQL persistente, backups e testes transacionais; nunca usar o SQLite efêmero como fonte de verdade.
3. **Homologar Asaas**: usar somente chave Sandbox, exercitar cobranças fictícias, transferências fictícias, eventos repetidos/fora de ordem e reconciliação. O módulo atual **não movimenta saques reais**, mesmo quando chamadas de teste são ativadas.
4. **Obter habilitação comercial**: credenciais de produção do Asaas, contratos, identidade da empresa e permissões específicas. Segredos apenas em serviço de gerenciamento seguro, jamais no repositório.
5. **Implementar pagamentos de produção em serviço separado**: controles de idempotência, auditoria, autorização, saldo lastreado, conciliação e proibição de executar operações financeiras em modo demo. Requer revisão de segurança antes de expor endpoints.
6. **Aceitação assistida**: simular incidentes e erros, verificar políticas de usuários e optar por lançamento pequeno com monitoramento antes de ampliar.

## Restrições que permanecem agora

- `DEMO_ONLY=true` e `ASAAS_SANDBOX_OUTBOUND_ENABLED=false`: **não alterar em produção atual**.
- `ASAAS_SANDBOX_TRANSFER_TESTS_ENABLED=false`; não marcar saques como pagos sem confirmação externa verificável.
- Não utilizar nem compartilhar credenciais produtivas neste repositório, na conversa ou em arquivos de demonstração.
- Não contratar serviço pago, abrir conta comercial ou processar dinheiro sem autorização explícita da pessoa responsável.

## Referências técnicas oficiais

- Asaas — Sandbox: https://docs.asaas.com/docs/sandbox
- Asaas — Preparação para produção: https://docs.asaas.com/docs/preparação-para-produção
- Asaas — Eventos e entrega de webhooks: https://docs.asaas.com/docs/webhooks-2
- Render — Limitações do plano gratuito: https://render.com/docs/free
- Render — Armazenamento persistente: https://render.com/docs/disks
