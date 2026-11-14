'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { normalize, selectAnswer, safeLinkHref } = require('../institutional_site/assets/assistant.js');

const knowledge = {
  faqs: [
    { question: 'Este site é da Receita Federal?', answer: 'Não. O QG RENDA é um portal independente e não representa a Receita Federal, o gov.br ou qualquer órgão público.', links: [] },
    { question: 'Posso consultar CPF, restituições ou declaração de Imposto de Renda aqui?', answer: 'Não. Esses serviços devem ser realizados nos canais oficiais.', links: [{ href: 'https://www.gov.br/receitafederal/pt-br', label: 'Receita Federal' }] },
    { question: 'As atividades pagam dinheiro?', answer: 'Não. O portal não oferece Pix, carteira, saque, prêmios ou promessas de renda.', links: [] },
    { question: 'Preciso criar uma conta ou enviar meus documentos?', answer: 'Não. O acesso é aberto e não pede CPF, documentos, fotos, senhas nem dados bancários.', links: [] },
    { question: 'O que é atualizado automaticamente?', answer: 'O sistema confere os links e renova os títulos, resumos disponíveis e datas de verificação das fontes. Os passos escritos pelo QG RENDA mantêm a data de revisão editorial indicada em cada guia.', links: [] },
    { question: 'Como funciona o atendimento automático?', answer: 'O assistente consulta os guias e as perguntas frequentes para oferecer orientações. Se não encontrar uma resposta, indica o contato do responsável. As consultas não são enviadas a serviços externos de atendimento.', links: [{ href: '#assistente', label: 'Assistente do portal' }, { href: '#contato', label: 'Contato do responsável' }] }
  ],
  guides: [
    { id: 'guia-seguranca', title: 'Segurança na internet', intro: 'Cuide das suas contas e arquivos.', steps: ['Confira o endereço.', 'Use senhas diferentes.', 'Mantenha cópias dos arquivos.'], links: [{ href: 'https://cartilha.cert.br/fasciculos/', label: 'CERT.br' }] },
    { id: 'guia-planejamento', title: 'Planeje seu orçamento', intro: 'Organize receitas e despesas no seu próprio caderno.', steps: ['Defina o objetivo.', 'Registre e agrupe os valores.', 'Compare o previsto com o realizado.'], links: [{ href: 'https://www.bcb.gov.br/cidadaniafinanceira', label: 'Banco Central' }], liveInfo: 'Fonte verificada em 14/11/2026.' },
    { id: 'guia-missoes', title: 'Uma ideia para sua comunidade', intro: 'Organize sua proposta.', steps: ['Identifique o órgão.', 'Escreva de forma objetiva.', 'Guarde o protocolo.'], links: [{ href: 'https://www.gov.br/ouvidorias/pt-br/falabr', label: 'Fala.BR' }] },
    { id: 'guia-fontes', title: 'Encontre o serviço oficial', intro: 'Consulte a instituição responsável.', steps: ['Pesquise o serviço.', 'Leia os requisitos.', 'Confira o endereço.'], links: [{ href: 'https://www.gov.br/pt-br/servicos', label: 'Catálogo gov.br' }] },
    { id: 'guia-acessibilidade', title: 'Ferramentas de leitura', intro: 'Ajuste a exibição neste dispositivo.', steps: ['Use Texto maior.', 'Experimente o zoom.', 'Consulte outras ferramentas.'], links: [{ href: 'https://www.gov.br/governodigital/pt-br/acessibilidade-e-usuario/acessibilidade-digital', label: 'Acessibilidade Digital' }] }
  ],
  contact: { email: 'contato@example.com', href: 'mailto:contato@example.com?subject=Contato%20pelo%20portal%20QG%20RENDA' },
  about: ['O QG RENDA é uma iniciativa informativa e educativa.', 'O acesso é gratuito e exclusivamente digital.']
};

test('normalização trata acentos, caixa e espaços sem alterar o conteúdo de origem', () => {
  assert.equal(normalize('  ORÇAMENTO  e SEGURANÇA\n'), 'orcamento e seguranca');
  assert.equal(normalize(null), '');
});

test('perguntas de afiliação nunca atribuem condição governamental ao projeto', () => {
  for (const question of ['O QG RENDA é do governo?', 'O site é oficial?', 'É da Receita Federal?', 'O portal já foi aprovado pelo governo?', 'governo?']) {
    const answer = selectAnswer(question, knowledge);
    assert.equal(answer.kind, 'faq', question);
    assert.match(answer.paragraphs.join(' '), /Não|independente/);
    assert.match(answer.title, /independente/);
  }
});

test('Pix, saques e promessas de renda recebem a resposta negativa publicada', () => {
  for (const question of ['Como ganhar dinheiro no QG RENDA?', 'Vocês pagam Pix?', 'Como sacar meu saldo?', 'Tem prêmio?']) {
    const answer = selectAnswer(question, knowledge);
    assert.match(answer.paragraphs.join(' '), /não oferece Pix/);
    assert.equal(answer.steps.length, 0);
  }
});

test('organização financeira usa o guia com os passos e a fonte atuais', () => {
  for (const question of ['Como organizar meu dinheiro?', 'Preciso de ajuda com orçamento', 'Como planejar minhas despesas?']) {
    const answer = selectAnswer(question, knowledge);
    assert.equal(answer.kind, 'guide');
    assert.equal(answer.title, 'Planeje seu orçamento');
    assert.deepEqual(answer.steps, knowledge.guides[1].steps);
    assert.equal(answer.links[0].href, 'https://www.bcb.gov.br/cidadaniafinanceira');
    assert.match(answer.paragraphs.join(' '), /Fonte verificada/);
  }
});

test('uma atualização do conteúdo de origem é usada na próxima resposta', () => {
  const updated = structuredClone(knowledge);
  updated.guides[1].steps[0] = 'Escolha o próximo período do orçamento.';
  updated.guides[1].liveInfo = 'Fonte verificada em 15/11/2026.';
  const answer = selectAnswer('orçamento', updated);
  assert.equal(answer.steps[0], updated.guides[1].steps[0]);
  assert.match(answer.paragraphs.join(' '), /15\/11\/2026/);
});

test('contato apresenta somente o endereço publicado, sem enviar mensagem', () => {
  const answer = selectAnswer('Como falar com o responsável?', knowledge);
  assert.equal(answer.kind, 'contact');
  assert.match(answer.paragraphs[0], /contato@example.com/);
  assert.equal(answer.links[0].href, knowledge.contact.href);
});

test('CPF e restituição apontam para a Receita Federal, sem consulta de documentos', () => {
  for (const question of ['Quero consultar CPF', 'Como receber restituição de imposto?', 'Declaração de imposto de renda']) {
    const answer = selectAnswer(question, knowledge);
    assert.match(answer.paragraphs[0], /^Não\./);
    assert.ok(answer.links.some(link => link.href === 'https://www.gov.br/receitafederal/pt-br'));
  }
});

test('participação e acessibilidade localizam os guias certos', () => {
  assert.equal(selectAnswer('Como acompanhar meu protocolo no Fala.BR?', knowledge).title, 'Uma ideia para sua comunidade');
  assert.equal(selectAnswer('Quero aumentar a letra', knowledge).title, 'Ferramentas de leitura');
  assert.equal(selectAnswer('Como evitar golpes e proteger senha?', knowledge).title, 'Segurança na internet');
});

test('autoatualização explica os dados renovados sem fingir revisão autoral dos passos', () => {
  for (const question of ['O site atualiza sozinho?', 'O que é atualizado automaticamente?', 'Como funciona o sistema automático?', 'Como é o monitoramento dos links?']) {
    const answer = selectAnswer(question, knowledge);
    assert.equal(answer.kind, 'faq', question);
    assert.equal(answer.title, 'Atualização automática das fontes', question);
    assert.match(answer.paragraphs.join(' '), /títulos, resumos disponíveis e datas/);
    assert.match(answer.paragraphs.join(' '), /passos escritos.*revisão editorial/);
    assert.ok(answer.links.some(link => link.href === '#automacao'));
  }
});

test('atendimento automático informa suas fontes e o processamento local', () => {
  for (const question of ['Como funciona atendimento automático?', 'Quem responde no assistente?', 'O atendimento automático é uma pessoa?']) {
    const answer = selectAnswer(question, knowledge);
    assert.equal(answer.kind, 'faq', question);
    assert.equal(answer.title, 'Como funciona o atendimento automático');
    assert.match(answer.paragraphs.join(' '), /guias e as perguntas frequentes/);
    assert.match(answer.paragraphs.join(' '), /não são enviadas a serviços externos/);
  }
  assert.match(selectAnswer('O site virou oficial com atualização automática?', knowledge).title, /independente/);
});

test('consultas desconhecidas e vazias não geram informações inventadas', () => {
  assert.equal(selectAnswer('Qual a previsão do tempo em uma cidade amanhã?', knowledge).kind, 'fallback');
  assert.equal(selectAnswer('', knowledge).kind, 'empty');
  assert.equal(selectAnswer('  ', knowledge).kind, 'empty');
  assert.equal(selectAnswer('x'.repeat(50000), knowledge).kind, 'fallback');
});

test('fontes maliciosas e esquemas ativos não viram links nas respostas', () => {
  for (const url of ['javascript:alert(1)', 'data:text/html,<script>alert(1)</script>', 'https://evil.test/', 'https://www.gov.br@evil.test/', 'http://www.gov.br/', 'https://www.gov.br:444/', 'mailto:a@example.com?subject=Oi%0Abcc=evil@example.com']) {
    assert.equal(safeLinkHref(url), null, url);
  }
  assert.equal(safeLinkHref('#guia-fontes'), '#guia-fontes');
  assert.equal(safeLinkHref('https://www.gov.br/pt-br/servicos'), 'https://www.gov.br/pt-br/servicos');
});

test('entradas com HTML não são transformadas em comandos ou conteúdo de resposta', () => {
  const answer = selectAnswer('<img src=x onerror=alert(1)>', knowledge);
  assert.equal(answer.kind, 'fallback');
  assert.doesNotMatch(JSON.stringify(answer), /onerror|<img/);
  const poisoned = structuredClone(knowledge);
  poisoned.guides[0].links.push({ href: 'javascript:alert(1)', label: 'Clique' });
  assert.ok(selectAnswer('senha', poisoned).links.every(link => !link.href.startsWith('javascript:')));
});

test('sem conteúdo no DOM, as invariantes críticas ainda são negativas e seguras', () => {
  assert.match(selectAnswer('O site é do governo?', {}).paragraphs[0], /Não é um órgão público/);
  assert.match(selectAnswer('Tem Pix?', {}).paragraphs[0], /Não oferece Pix/);
  assert.equal(selectAnswer('qual a temperatura?', {}).kind, 'fallback');
});
