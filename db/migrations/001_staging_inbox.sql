-- QG RENDA: persistência ISOLADA para testes. NUNCA registra pagamentos reais.
-- Este esquema NÃO é uma carteira e NÃO substitui um ledger auditável.
-- Aplicar somente num PostgreSQL efêmero e isolado de testes; não no Render produtivo.
BEGIN;

CREATE SCHEMA IF NOT EXISTS qgr_staging;

CREATE TABLE IF NOT EXISTS qgr_staging.webhook_events (
    event_id VARCHAR(128) PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'asaas_sandbox'
        CHECK (provider = 'asaas_sandbox'),
    event_type VARCHAR(80) NOT NULL CHECK (length(event_type) > 0),
    resource_id VARCHAR(128),
    payload_sha256 CHAR(64) NOT NULL CHECK (payload_sha256 ~ '^[a-f0-9]{64}$'),
    delivery_count INTEGER NOT NULL DEFAULT 1 CHECK (delivery_count > 0),
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qgr_staging.operations (
    operation_id UUID PRIMARY KEY,
    idempotency_key VARCHAR(96) NOT NULL UNIQUE
        CHECK (length(idempotency_key) >= 8),
    provider TEXT NOT NULL DEFAULT 'asaas_sandbox'
        CHECK (provider = 'asaas_sandbox'),
    operation_type TEXT NOT NULL
        CHECK (operation_type IN ('charge_simulation', 'transfer_simulation')),
    amount_cents BIGINT NOT NULL CHECK (amount_cents BETWEEN 100 AND 10000),
    state TEXT NOT NULL DEFAULT 'created'
        CHECK (state IN ('created', 'simulated', 'failed')),
    provider_reference VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_qgr_staging_webhook_received
    ON qgr_staging.webhook_events (received_at DESC);
CREATE INDEX IF NOT EXISTS idx_qgr_staging_operations_created
    ON qgr_staging.operations (created_at DESC);

COMMIT;
