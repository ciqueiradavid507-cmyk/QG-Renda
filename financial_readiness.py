"""Barreira técnica para impedir ativação financeira acidental no QG RENDA.

O repositório atual é exclusivamente demonstrativo. Declarar uma conta Asaas
aprovada ou preencher uma variável de ambiente não equivale a homologação.
Não há rotas de pagamento reais neste módulo.
"""
from __future__ import annotations

from typing import Any


def require_demonstration_mode(demo_only: bool) -> None:
    """Falha ao inicializar caso o backend de demonstração seja posto em modo real."""
    if not demo_only:
        raise RuntimeError(
            "QG RENDA: esta versão aceita somente DEMO_ONLY=true. "
            "Produção financeira requer outro backend auditado, banco persistente "
            "e credenciamento do provedor, sem reutilizar o serviço de demo."
        )


def financial_readiness_report(demo_only: bool) -> dict[str, Any]:
    """Relatório administrativo sem qualquer credencial ou dado financeiro sensível.

    O sistema existente usa sqlite3 diretamente e o gateway Asaas instalado
    suporta somente Sandbox. Portanto os requisitos produtivos nunca são
    inferidos a partir de variáveis de ambiente definidas pelo usuário.
    """
    checks = [
        {
            "id": "conta_comercial",
            "status": "validacao_pendente",
            "description": "Verificar no painel do Asaas a titularidade da conta e as permissões de Pix e transferências."
        },
        {
            "id": "operacao_elegivel",
            "status": "validacao_pendente",
            "description": "Confirmar operador e requisitos contratuais, cadastrais e legais."
        },
        {
            "id": "banco_persistente",
            "status": "bloqueado",
            "description": "O código atual utiliza SQLite local, sem garantias de persistência do Render Free."
        },
        {
            "id": "contabilidade",
            "status": "bloqueado",
            "description": "Faltam ledger de dupla entrada, controle de fundos e conciliação auditável."
        },
        {
            "id": "pagamentos_producao",
            "status": "bloqueado",
            "description": "Apenas o Asaas Sandbox está integrado; não existe gateway Pix produtivo aprovado."
        },
        {
            "id": "verificacoes_seguranca",
            "status": "bloqueado",
            "description": "Exige testes de segurança, idempotência, antifraude, recuperação e revisão profissional."
        },
    ]
    return {
        "environment": "demonstracao" if demo_only else "configuracao_insegura",
        "real_payments_enabled": False,
        "real_payouts_enabled": False,
        "production_ready": False,
        "may_enable_production_by_env_flag": False,
        "checks": checks,
        "message": "Preparação em curso. Não inserir credenciais de produção nem movimentar dinheiro.",
    }
