# QG RENDA — Plataforma demonstrativa

Portal responsivo de microtarefas com API FastAPI, autenticação, envio e revisão de atividades, histórico e área administrativa.

**Não é uma plataforma de renda ativa.** A edição do Render Free executa com `DEMO_ONLY=true`, sem pagamentos, saques ou promessas de ganhos. Este repositório é público: **não envie senhas, dados reais ou arquivos .env**.

## Implantação com um clique (Render)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2Fciqueiradavid507-cmyk%2FQG-Renda)

Clique em **Deploy to Render**, entre na sua própria conta Render, autorize o GitHub, confira o repositório `ciqueiradavid507-cmyk/QG-Renda` e selecione o plano **Free**. Preencha **apenas no Render** os campos secretos `BOOTSTRAP_ADMIN_EMAIL` e `BOOTSTRAP_ADMIN_PASSWORD`; não os coloque em commits ou mensagens de chat. Revise os recursos apresentados antes de confirmar qualquer custo.

Esta implantação é uma **demonstração sem pagamentos reais**. O serviço precisa manter `DEMO_ONLY=true` e o plano gratuito pode perder dados locais ao reiniciar.

## Implantar gratuitamente no Render

1. Conecte o Render ao GitHub e selecione o repositório `ciqueiradavid507-cmyk/QG-Renda`.
2. No Render, use **New → Blueprint** e confirme a configuração do arquivo `render.yaml`, com plano `free`.
3. Quando solicitado, informe em campos secretos `BOOTSTRAP_ADMIN_EMAIL` e `BOOTSTRAP_ADMIN_PASSWORD` (pelo menos 12 caracteres, exclusiva). **Nunca registre a senha no GitHub.**
4. Confirme a implantação e verifique `https://DOMINIO.onrender.com/api/health` (retorna `status: ok`) e `/api/config` (deve retornar `demo_only: true`).
5. Faça um cadastro de teste e conclua a tarefa de demonstração.

### Observações importantes
- Render Free pode suspender o serviço por inatividade e reiniciar com perda dos dados locais SQLite. Não use com informações financeiras ou dados pessoais importantes.
- Não foi configurada integração Pix, nem um provedor de pagamento.
- A política de privacidade e os termos são modelos de demonstração e necessitam revisão jurídica para um serviço comercial.
- Não há declaração de certificação LGPD ou autorização governamental.

## Integração Asaas (somente Sandbox)

O projeto inclui um módulo **opcional** para homologar cobranças Pix e transferências fictícias do Asaas. Ele **não ativa pagamentos verdadeiros**, não credita carteiras e rejeita chaves de produção. A comunicação externa começa desativada; a ativação exige uma conta Sandbox e credenciais secretas configuradas exclusivamente no Render.

Consulte o guia completo: [docs/ASAAS_SANDBOX.md](docs/ASAAS_SANDBOX.md).

## Desenvolvimento local

```bash
python -m pip install -r requirements.txt
DEMO_ONLY=true python -m uvicorn main:app --reload --port 8000
```

Abra http://localhost:8000. Para executar checagens:

```bash
python -m pip install -r requirements-dev.txt
python -m compileall -q main.py
```

Cuidado: sem `DEMO_ONLY=true`, o código possui operações de carteira para uma futura versão comercial. **Nunca disponibilize publicamente esse modo sem auditoria, persistência adequada, adequação legal e integração de pagamentos.**
