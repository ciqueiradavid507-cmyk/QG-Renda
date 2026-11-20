(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    root.QGRendaAssistant = api;
    if (root.document.readyState === 'loading') {
      root.document.addEventListener('DOMContentLoaded', function () { api.mount(root.document); });
    } else {
      api.mount(root.document);
    }
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var SOURCE_HOSTS = new Set(['www.gov.br', 'gov.br', 'www.bcb.gov.br', 'bcb.gov.br', 'cartilha.cert.br', 'www.cert.br', 'cert.br']);
  var STOP_WORDS = new Set(('a ao aos as com como da das de do dos e em entre essa esse esta este eu me meu minha minhas meus na nas no nos o os ou para pelo pela pelos pelas por qual quais que quem se sem seu sua seus suas sobre tem ter um uma uns umas voce voces aqui site portal projeto qg renda quero queria preciso duvida duvidas favor pode posso fazer saber gostaria sao ser ja onde quando isso dessa desse essa esse').split(' '));
  var GUIDE_TOPICS = {
    'guia-seguranca': /\b(seguranc\w*|senha\w*|golpe\w*|phishing|backup\w*|fraude\w*|2fa|duas etapas|link suspeito|atualizar aplicativos)\b/,
    'guia-planejamento': /\b(orcament\w*|financ\w*|despesa\w*|receitas|gasto\w*|economiz\w*|planej\w*|metas|organizar (o |meu |seu )?dinheiro|organizo (o |meu )?dinheiro)\b/,
    'guia-missoes': /\b(comunidade|bairro|particip\w*|sugest\w*|reclam\w*|denunci\w*|manifest\w*|protocolo|fala[ .]*br|falabr|proposta\w*)\b/,
    'guia-fontes': /\b(servico\w*|documentacao|canal oficial|canais oficiais|fontes oficiais)\b/,
    'guia-acessibilidade': /\b(acessibil\w*|contraste|zoom|texto maior|leitura|teclado|tab|tamanho (do |da )?(texto|letra)|aumentar (o |a )?(texto|letra))\b/
  };

  function normalize(value) {
    return String(value == null ? '' : value).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function words(value) {
    return Array.from(new Set(normalize(value).split(/[^a-z0-9]+/).filter(function (word) {
      return word.length > 2 && !STOP_WORDS.has(word);
    })));
  }

  function cleanText(value, limit) {
    return String(value == null ? '' : value).replace(/\s+/g, ' ').trim().slice(0, limit || 2000);
  }

  function safeLinkHref(value) {
    if (typeof value !== 'string') return null;
    var href = value.trim();
    if (/^#[A-Za-z][\w:-]*$/.test(href)) return href;
    if (/^mailto:[^\s@?]+@[^\s@?]+\.[^\s@?]+(?:\?subject=[^#\r\n]*)?$/i.test(href)) {
      try { return /[\r\n]/.test(decodeURIComponent(href)) ? null : href; } catch (_) { return null; }
    }
    try {
      var url = new URL(href);
      return url.protocol === 'https:' && SOURCE_HOSTS.has(url.hostname) && !url.username && !url.password && (!url.port || url.port === '443') ? url.href : null;
    } catch (_) {
      return null;
    }
  }

  function sanitizeLinks(links) {
    var seen = new Set();
    return (Array.isArray(links) ? links : []).reduce(function (result, link) {
      var href = safeLinkHref(link && link.href);
      if (href && !seen.has(href)) {
        seen.add(href);
        result.push({ href: href, label: cleanText(link.label || 'Abrir referência', 180) });
      }
      return result;
    }, []);
  }

  function readLinks(node) {
    return sanitizeLinks(Array.from(node.querySelectorAll('a[href]')).map(function (link) {
      return { href: link.getAttribute('href'), label: link.textContent };
    }));
  }

  function buildKnowledge(doc) {
    var faqs = Array.from(doc.querySelectorAll('#perguntas details')).map(function (detail, index) {
      var question = detail.querySelector('summary');
      return {
        id: 'faq-' + index,
        question: cleanText(question && question.textContent),
        answer: Array.from(detail.querySelectorAll('p')).map(function (p) { return cleanText(p.textContent); }).join(' '),
        links: readLinks(detail)
      };
    });
    var guides = Array.from(doc.querySelectorAll('article[id^="guia-"]')).map(function (guide) {
      var title = guide.querySelector('h3');
      var intro = Array.from(guide.children).find(function (child) { return child.tagName === 'P'; });
      var details = guide.querySelector('details.guide-steps');
      var liveInfo = guide.querySelector('[data-source-update], .source-update, .source-info');
      return {
        id: guide.id,
        title: cleanText(title && title.textContent),
        intro: cleanText(intro && intro.textContent),
        steps: Array.from(guide.querySelectorAll('details.guide-steps ol li')).map(function (li) { return cleanText(li.textContent); }),
        links: details ? readLinks(details) : [],
        liveInfo: cleanText(liveInfo && liveInfo.textContent, 700)
      };
    });
    var contactNode = doc.querySelector('#contato a[href^="mailto:"]');
    var contactName = doc.querySelector('#sobre .project-facts dd');
    var aboutNode = doc.querySelector('#sobre .about-text');
    return {
      faqs: faqs,
      guides: guides,
      contact: contactNode ? { email: cleanText(contactNode.textContent), href: safeLinkHref(contactNode.getAttribute('href')) } : null,
      contactName: cleanText(contactName && contactName.textContent, 180),
      about: aboutNode ? Array.from(aboutNode.querySelectorAll('p')).map(function (p) { return cleanText(p.textContent); }).slice(0, 2) : []
    };
  }

  function findFaq(knowledge, expression) {
    return (knowledge.faqs || []).find(function (faq) { return expression.test(normalize(faq.question)); });
  }

  function faqAnswer(faq, title, fallback, extraLinks) {
    return {
      kind: 'faq', title: title,
      paragraphs: [faq && faq.answer ? cleanText(faq.answer) : fallback],
      steps: [], links: sanitizeLinks((faq && faq.links || []).concat(extraLinks || []))
    };
  }

  function guideAnswer(guide) {
    var paragraphs = [cleanText(guide.intro)];
    if (guide.liveInfo) paragraphs.push(cleanText(guide.liveInfo, 700));
    return {
      kind: 'guide', title: cleanText(guide.title), paragraphs: paragraphs.filter(Boolean),
      steps: (guide.steps || []).slice(0, 6).map(function (step) { return cleanText(step); }),
      links: sanitizeLinks((guide.links || []).concat([{ href: '#' + guide.id, label: 'Ver o guia no portal' }]))
    };
  }

  function fallbackAnswer(empty) {
    return {
      kind: empty ? 'empty' : 'fallback',
      title: empty ? 'Qual é a sua dúvida?' : 'Não encontrei essa resposta no portal',
      paragraphs: [empty ? 'Escreva uma pergunta sobre os guias, os recursos ou o contato do QG RENDA.' : 'Posso localizar orientações sobre segurança na internet, orçamento, participação cidadã, serviços oficiais e acessibilidade. Para outros assuntos, fale com o responsável pelo projeto.'],
      steps: [],
      links: [{ href: '#servicos', label: 'Explorar os recursos' }, { href: '#contato', label: 'Contato do projeto' }]
    };
  }

  function selectAnswer(value, knowledge) {
    knowledge = knowledge || {};
    var query = normalize(String(value == null ? '' : value).slice(0, 300));
    if (!query) return fallbackAnswer(true);

    var affiliation = /\b(governo|governamental\w*|gov[ .]*br|oficial|orgao publico|receita federal)\b/.test(query);
    var asksAboutPortal = /\b(qg|site|portal|voces|projeto|pertence|representa|vinculo|afiliacao|credenciamento|credenciado|reconhecimento|aprovad\w*|parceria)\b/.test(query);
    if ((affiliation && asksAboutPortal) || /^(nao )?(e |eh |do |da )?(um |uma )?(do |da )?(governo|governamental|gov[ .]*br|oficial|receita federal|orgao publico)[?!. ]*$/.test(query)) {
      return faqAnswer(findFaq(knowledge, /este site.*receita federal|site.*governo/), 'O QG RENDA é independente', 'O QG RENDA é um portal cívico independente. Não é um órgão público, não integra o gov.br e não representa o governo.', [{ href: '#sobre', label: 'Sobre o projeto' }]);
    }

    if (/\b(contato|e[ -]?mail|responsavel|david|falar com|entrar em contato)\b/.test(query)) {
      var contact = knowledge.contact || {};
      return {
        kind: 'contact', title: 'Contato do QG RENDA',
        paragraphs: [contact.email ? 'Você pode falar com o responsável pelo projeto pelo e-mail ' + cleanText(contact.email, 180) + '. O contato é para dúvidas e sugestões sobre o portal.' : 'Use a seção Contato para falar com o responsável pelo projeto sobre dúvidas ou sugestões.'],
        steps: [], links: sanitizeLinks([{ href: contact.href, label: contact.email || 'Enviar e-mail' }, { href: '#contato', label: 'Ver os detalhes de contato' }])
      };
    }

    var fiscal = /\b(cpf|restituic\w*|imposto\w*|irpf|declaracao|receita federal)\b/.test(query);
    var budget = GUIDE_TOPICS['guia-planejamento'].test(query);
    var payments = /\b(pix|saque\w*|sacar|carteira|premio\w*|recompensa\w*|ganhar|ganho\w*|renda extra|receber dinheiro|pagam|paga|pagamento\w*|saldo)\b/.test(query);
    if (payments && !fiscal && (!budget || /\b(pix|sacar|saque\w*|ganhar|premio\w*|recompensa\w*)\b/.test(query))) {
      return faqAnswer(findFaq(knowledge, /pagam dinheiro|pagamento/), 'O portal não oferece pagamentos', 'O QG RENDA é informativo. Não oferece Pix, carteira, saque, prêmios ou promessas de renda.', [{ href: '#perguntas', label: 'Ler as perguntas frequentes' }]);
    }

    if (fiscal) {
      return faqAnswer(findFaq(knowledge, /consultar cpf|restituic/), 'Use os canais oficiais para esses serviços', 'O QG RENDA não consulta CPF nem realiza serviços fiscais. Procure o canal oficial da instituição responsável.', [{ href: 'https://www.gov.br/receitafederal/pt-br', label: 'Receita Federal — canal oficial' }, { href: '#guia-fontes', label: 'Guia para encontrar o serviço oficial' }]);
    }

    if (/\b(cadastro|cadastrar|login|criar (uma )?conta|enviar (meus |os )?documentos|dados bancarios)\b/.test(query)) {
      return faqAnswer(findFaq(knowledge, /criar.*conta|enviar.*documentos/), 'O acesso ao portal é aberto', 'O QG RENDA não exige conta, CPF, documentos, fotos, senhas ou dados bancários para consultar os conteúdos.', [{ href: '#sobre', label: 'Como o projeto funciona' }]);
    }

    var automatic = /\b(automatic\w*|sozinh\w*|automacao|automatizacao)\b/.test(query);
    if ((automatic && /\b(atualiz\w*|renov\w*|verific\w*|monitor\w*|manutencao|sistema|fontes|links)\b/.test(query)) || /\b(verificacao|monitoramento|manutencao) (das |dos |de )?(fontes|links)\b/.test(query)) {
      return faqAnswer(findFaq(knowledge, /atualizado automaticamente/), 'Atualização automática das fontes', 'O sistema confere os links e renova os títulos, resumos disponíveis e datas de verificação das fontes. Os passos escritos pelo QG RENDA mantêm a data de revisão editorial indicada em cada guia.', [{ href: '#automacao', label: 'Ver o acompanhamento das fontes' }]);
    }
    if (/\b(atendiment\w*|assistente|suporte|respost\w*|chatbot|robo|ia|inteligencia artificial)\b/.test(query) && (automatic || /\b(como funciona|como responde|quem responde|ia|inteligencia artificial|openai|privacidade|humano|pessoa)\b/.test(query))) {
      return faqAnswer(findFaq(knowledge, /como funciona.*(atendimento|suporte)|suporte.*ia/), 'Como funciona o atendimento automático', 'O suporte local consulta os guias e perguntas do portal neste navegador. O modo IA é opcional quando disponível: ao ativá-lo, perguntas gerais e um histórico curto são enviados à OpenAI para gerar respostas. Dúvidas sobre identificação, pagamentos, documentos e contato continuam locais.', [{ href: '#assistente', label: 'Consultar o assistente do portal' }]);
    }

    var guides = knowledge.guides || [];
    var topicIds = ['guia-acessibilidade', 'guia-seguranca', 'guia-planejamento', 'guia-missoes', 'guia-fontes'];
    for (var i = 0; i < topicIds.length; i++) {
      if (GUIDE_TOPICS[topicIds[i]].test(query)) {
        var matchedGuide = guides.find(function (guide) { return guide.id === topicIds[i]; });
        if (matchedGuide) return guideAnswer(matchedGuide);
      }
    }

    if (/\b(o que e|como funciona|como (usar|uso|utilizar)|quais (recursos|guias)|sobre o qg|finalidade|objetivo)\b/.test(query) || /^(ola|oi|bom dia|boa tarde|boa noite)[!?. ]*$/.test(query)) {
      var paragraphs = (knowledge.about || []).slice(0, 2).map(function (p) { return cleanText(p); });
      return { kind: 'about', title: 'Como usar o QG RENDA', paragraphs: paragraphs.length ? paragraphs : ['Consulte os guias gratuitos, encontre fontes oficiais e use o contato para enviar dúvidas sobre o projeto. O QG RENDA é um portal independente.'], steps: [], links: [{ href: '#servicos', label: 'Explorar recursos' }, { href: '#sobre', label: 'Sobre o projeto' }] };
    }

    var queryWords = words(query);
    var best = null;
    var candidates = (knowledge.faqs || []).map(function (faq) { return { entry: faq, type: 'faq', title: faq.question, text: faq.answer }; }).concat(guides.map(function (guide) { return { entry: guide, type: 'guide', title: guide.title, text: guide.intro + ' ' + (guide.steps || []).join(' ') }; }));
    candidates.forEach(function (candidate) {
      var titleWords = words(candidate.title), textWords = words(candidate.text);
      var hits = queryWords.filter(function (word) { return titleWords.includes(word) || textWords.includes(word); });
      var score = hits.reduce(function (sum, word) { return sum + (titleWords.includes(word) ? 3 : 1); }, 0);
      if (hits.length >= 2 && (!best || score > best.score)) best = { entry: candidate.entry, type: candidate.type, score: score };
    });
    if (best) return best.type === 'guide' ? guideAnswer(best.entry) : faqAnswer(best.entry, cleanText(best.entry.question), '', [{ href: '#perguntas', label: 'Ver perguntas frequentes' }]);
    return fallbackAnswer(false);
  }

  function planSupportAction(value, state) {
    var query = normalize(String(value == null ? '' : value).slice(0, 300));
    if (!query) return null;
    if (/\b(ainda preciso de ajuda|nao resolveu|nao funcionou|continua (o |com )?problema|continuo com problema)\b/.test(query) || (state && state.followup && /^(nao|ainda nao|continua)[.!? ]*$/.test(query))) return { type: 'handoff' };
    if (/\b(resolveu|funcionou|deu certo)\b/.test(query) || (state && state.followup && /^(sim|sim obrigado|obrigado|obrigada)[.!? ]*$/.test(query))) return { type: 'resolved' };
    if (/\b(busca|buscar|pesquisa|pesquisar|resultado\w*|filtro\w*)\b/.test(query) && /\b(nao (encontra|encontro|encontrou|aparece|mostra|funciona)|sem resultado\w*|nenhum resultado|nao tem nada|nada|limp\w*|reset\w*|restaur\w*|zer\w*)\b/.test(query)) return { type: 'reset-search' };
    var text = /\b(texto maior|fonte|letra\w*|tamanho (do |da )?(texto|letra)|texto (normal|menor))\b/.test(query);
    var contrast = /\b(contraste)\b/.test(query);
    var request = /\b(ativ\w*|desativ\w*|lig\w*|deslig\w*|aument\w*|diminu\w*|reduz\w*|remov\w*|tire|tirar|coloque|deixe|quero|preciso|volte|voltar|restaur\w*|normal|nao consigo ler|dificil de ler)\b/.test(query);
    if ((text || contrast) && request && !/^(como|onde|qual|o que)\b/.test(query) && !/\bnao (quero )?(ativ\w*|desativ\w*|lig\w*|deslig\w*|remov\w*|aument\w*)\b/.test(query)) {
      if (text && contrast && /\b(ative|ativar|ligue|ligar|aumente|aumentar)\b/.test(query) && /\b(desative|desativar|desligue|desligar|reduza|reduzir|diminuir|diminua|remova|remover)\b/.test(query)) return { type: 'reading-clarify' };
      var off = /\b(desativ\w*|deslig\w*|diminu\w*|reduz\w*|remov\w*|tire|tirar|volte|voltar|restaur\w*|normal)\b/.test(query) || /\bnao quero\b/.test(query);
      var settings = [];
      if (text) settings.push({ control: 'large', enabled: !off });
      if (contrast) settings.push({ control: 'high-contrast', enabled: !off });
      return { type: 'set-reading', settings: settings };
    }
    if (/\b(link\w*|fonte\w*|pagina\w*|site)\b/.test(query) && /\b(quebrad\w*|nao abre|nao abrem|nao funciona|erro\w*|indispon\w*|fora do ar|falh\w*|problema\w*|verific\w*)\b/.test(query)) return { type: 'check-links', query: query };
    return null;
  }

  function supportAnswer(title, paragraphs, links, changed) {
    return { kind: 'support', title: title, paragraphs: paragraphs, steps: [], links: sanitizeLinks(links || []), changed: changed === true, followUps: [{ label: 'Resolveu', question: 'Resolveu, obrigado' }, { label: 'Ainda preciso de ajuda', question: 'Ainda preciso de ajuda' }] };
  }

  function checkedDate(value) {
    if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) return '';
    return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Belem' }).format(new Date(value)) + ' (UTC−3)';
  }

  function diagnoseLinks(plan, snapshot) {
    var data = snapshot && (snapshot.snapshot || snapshot);
    var sources = data && Array.isArray(data.sources) ? data.sources.slice(0, 20).filter(function (source) { return source && safeLinkHref(source.url) && String(source.url).startsWith('https://'); }) : [];
    if (!sources.length) return supportAnswer('Ainda não há uma verificação disponível', ['O acompanhamento das fontes ainda não forneceu dados para esta página. Os links originais continuam nos guias.', 'Consulte o acompanhamento das fontes ou tente o canal oficial diretamente. Isso ajuda a acessar o que você precisa?'], [{ href: '#automacao', label: 'Ver acompanhamento das fontes' }, { href: '#canais-oficiais', label: 'Abrir canais oficiais' }], false);
    var terms = words(plan.query).filter(function (word) { return !/^(link|links|fonte|fontes|pagina|paginas|funciona|funcionam|abre|abrem|erro|problema|problemas|quebrado|quebrados|verificar|indisponivel)$/.test(word); });
    var targeted = sources.filter(function (source) { var corpus = normalize(source.id + ' ' + source.name + ' ' + source.url); return terms.some(function (term) { return corpus.includes(term); }); });
    var selected = targeted.length ? targeted : sources.filter(function (source) { return source.status === 'unavailable'; });
    if (!selected.length) selected = sources.slice(0, 2);
    var paragraphs = selected.slice(0, 3).map(function (source) {
      var availability = source.status === 'ok' ? 'estava acessível' : source.status === 'unavailable' ? 'não pôde ser confirmada' : 'ainda aguarda confirmação';
      var when = checkedDate(source.checked_at);
      return cleanText(source.name || source.title || 'Fonte', 180) + ': ' + availability + ' na última verificação' + (when ? ' de ' + when : '') + '.';
    });
    paragraphs.push('Esse diagnóstico usa a última verificação do portal. Ele não altera o site externo nem confirma como a fonte está respondendo no seu dispositivo. Tente o endereço original abaixo. Isso resolveu o acesso?');
    return supportAnswer('Diagnóstico dos links', paragraphs, selected.slice(0, 3).map(function (source) { return { href: source.url, label: 'Abrir ' + cleanText(source.name || 'fonte original', 160) }; }).concat([{ href: '#automacao', label: 'Ver todas as verificações' }]), false);
  }

  function applySupportAction(plan, doc, snapshot) {
    if (!plan) return null;
    if (plan.type === 'check-links') return diagnoseLinks(plan, snapshot);
    if (plan.type === 'handoff') return { kind: 'support', title: 'Vamos continuar pelo contato do projeto', paragraphs: ['Descreva ao responsável qual página ou recurso apresenta o problema e o que aconteceu ao tentar usá-lo. O contato está disponível na seção abaixo.'], steps: [], links: [{ href: '#contato', label: 'Contato do responsável' }], changed: false, followUps: [] };
    if (plan.type === 'resolved') return { kind: 'support', title: 'Orientação concluída', paragraphs: ['Você pode continuar usando os recursos e os guias do portal. Se surgir outra dificuldade, descreva o que aconteceu no suporte.'], steps: [], links: [{ href: '#servicos', label: 'Voltar aos recursos' }], changed: false, followUps: [] };
    if (plan.type === 'reading-clarify') return { kind: 'support', title: 'Vamos ajustar uma opção por vez', paragraphs: ['Sua mensagem pede ativação e desativação de opções diferentes. Para confirmar cada ajuste, escolha a opção desejada ou escreva um pedido por vez.'], steps: [], links: [{ href: '#guia-acessibilidade', label: 'Ferramentas de leitura' }], changed: false, followUps: [{ label: 'Ativar texto maior', question: 'Ative texto maior' }, { label: 'Desativar texto maior', question: 'Desative texto maior' }, { label: 'Ativar contraste', question: 'Ative contraste' }, { label: 'Desativar contraste', question: 'Desative contraste' }] };
    if (plan.type === 'reset-search') {
      var search = doc.getElementById('busca');
      var all = doc.querySelector('[data-filter="todos"]');
      if (!search || !all) return supportAnswer('Não encontrei os controles da busca', ['Não consegui aplicar o ajuste nesta página. Abra a área de recursos ou entre em contato com o responsável.'], [{ href: '#servicos', label: 'Abrir recursos' }, { href: '#contato', label: 'Contato' }], false);
      var changed = Boolean(search.value) || all.getAttribute('aria-pressed') !== 'true';
      search.value = '';
      var EventType = doc.defaultView && doc.defaultView.Event || Event;
      search.dispatchEvent(new EventType('input', { bubbles: true }));
      if (all.getAttribute('aria-pressed') !== 'true') all.click();
      var visible = Array.from(doc.querySelectorAll('#cards article')).filter(function (card) { return !card.hidden; }).length;
      return supportAnswer('Busca e filtros conferidos', [changed ? 'Limpei o texto da busca e restabeleci o filtro Todos.' : 'A busca já estava vazia e o filtro Todos já estava selecionado.', visible + ' recurso' + (visible === 1 ? ' está disponível' : 's estão disponíveis') + ' agora. Isso resolveu a dificuldade para encontrar os conteúdos?'], [{ href: '#servicos', label: 'Ver os recursos' }], changed);
    }
    if (plan.type === 'set-reading') {
      var anyChanged = false;
      var results = (plan.settings || []).slice(0, 2).map(function (setting) {
        var id = setting.control === 'large' ? 'larger-text' : setting.control === 'high-contrast' ? 'contrast' : '';
        var label = setting.control === 'large' ? 'Texto maior' : 'Mais contraste';
        var button = id && doc.getElementById(id);
        if (!button) return 'Não encontrei o controle ' + label + ' nesta página.';
        var before = doc.documentElement.classList.contains(setting.control);
        if (before !== setting.enabled) button.click();
        var after = doc.documentElement.classList.contains(setting.control);
        anyChanged = anyChanged || before !== after;
        return after === setting.enabled ? label + (before === after ? ' já estava ' : ' foi ') + (after ? 'ativado.' : 'desativado.') : 'Não consegui confirmar o ajuste de ' + label + '.';
      });
      results.push('O ajuste vale para a exibição neste navegador. Isso resolveu a leitura?');
      return supportAnswer('Ajustes de leitura', results, [{ href: '#guia-acessibilidade', label: 'Ver ferramentas de leitura' }], anyChanged);
    }
    return null;
  }

  function containsPersonalData(value, knowledge) {
    var text = cleanText(value, 4000);
    var query = normalize(text);
    if (/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i.test(text) || /(?:\d[\s().+\-]*){8,}/.test(text) || /\b(meu nome e|me chamo|minha senha|senha e|meu endereco|moro na|moro em|meu telefone|meu celular|meu cpf|meu rg)\b/.test(query) || /[?&](token|key|api_key|password|senha|auth|code|cpf|email)=/i.test(text)) return true;
    var name = knowledge && (knowledge.contactName || knowledge.contact && knowledge.contact.name);
    return words(name || '').filter(function (word) { return word.length > 3; }).some(function (word) { return new RegExp('\\b' + word + '\\b').test(query); });
  }

  function isRestrictedLocal(value) {
    var query = normalize(value);
    return /\b(governo|governamental\w*|gov[ .]*br|receita federal|orgao\w*|oficial|reconhecimento|parceria|aprovad\w*|vincul\w*|representa|credenciado|credenciamento|afiliacao|cpf|restituic\w*|imposto\w*|irpf|declaracao|pix|saque\w*|sacar|carteira|premio\w*|recompensa\w*|ganhar|ganho\w*|renda extra|receber dinheiro|pagam|paga|pagamento\w*|saldo|contato|e[ -]?mail|responsavel|david|identific\w*|document\w*|telefone|celular|endereco|nome completo|cadastro|cadastrar|login|criar (uma )?conta|dados bancarios|contraste|texto maior|tamanho (do |da )?(texto|letra)|suporte|atendimento|assistente|ia|inteligencia artificial|openai|privacidade)\b/.test(query);
  }

  function buildAIHistory(history, knowledge) {
    return (Array.isArray(history) ? history : []).filter(function (entry) {
      return entry && (entry.role === 'user' || entry.role === 'assistant') && typeof entry.content === 'string' && (!entry.mode || entry.mode === 'ai') && !containsPersonalData(entry.content, knowledge) && !isRestrictedLocal(entry.content);
    }).map(function (entry) { return { role: entry.role, content: cleanText(entry.content, 300) }; }).filter(function (entry) { return Boolean(entry.content); }).slice(-4);
  }

  function shouldUseAI(value, options) {
    options = options || {};
    return options.aiEnabled === true && options.aiAvailable === true && Boolean(cleanText(value, 300)) && !options.plan && !planSupportAction(value) && !containsPersonalData(value, options.knowledge) && !isRestrictedLocal(value);
  }

  function prohibitedAIClaim(value) {
    var text = normalize(value);
    var subject = '(?:qg\\s*renda|este (?:site|portal)|nosso (?:site|portal)|somos|sou)';
    var declarations = [
      new RegExp('\\b' + subject + '\\s+(?:(?:e|eh|um|uma|o|a|site|portal)\\s+){0,4}(?:orgao publico|governamental\\w*|oficial(?: do governo)?|do governo|parte do governo|representantes? do governo|parceir\\w* do governo|(?:da )?receita federal|(?:do )?gov[ .]*br)\\b', 'g'),
      new RegExp('\\b' + subject + '\\s+(?:representa (?:o governo|a receita federal|o gov[ .]*br)|integra (?:o governo|a receita federal|o gov[ .]*br)|pertence (?:ao governo|a receita federal|ao gov[ .]*br)|oferece pix|paga|pagamos|processa pagamentos|gera saldo|permite saque|ganha dinheiro)\\b', 'g'),
      new RegExp('\\b' + subject + '\\s+(?:(?:e|eh|foi|esta|um|uma|o|a)\\s+){0,4}(?:aprovad\\w*|credenciad\\w*|autorizad\\w*|reconhecid\\w*)\\b', 'g')
    ];
    return declarations.some(function (expression) {
      var match;
      while ((match = expression.exec(text))) {
        if (!/\b(?:nao|nunca|jamais)\s+$/.test(text.slice(Math.max(0, match.index - 12), match.index))) return true;
      }
      return false;
    });
  }

  async function requestAIResponse(message, history, fetchImpl, options) {
    options = options || {};
    if (typeof fetchImpl !== 'function') throw new Error('ai_unavailable');
    var controller = new AbortController();
    var abort = function () { controller.abort(); };
    if (options.signal) {
      if (options.signal.aborted) controller.abort();
      else options.signal.addEventListener('abort', abort, { once: true });
    }
    var timer = setTimeout(abort, options.timeoutMs || 25000);
    try {
      var response = await fetchImpl('/api/support/respond', { method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify({ message: cleanText(message, 300), history: buildAIHistory(history, options.knowledge) }), signal: controller.signal });
      if (!response || !response.ok) throw new Error('ai_failed');
      var data = await response.json();
      if (!data || data.mode !== 'ai') return { mode: 'local', reason: 'ai_fallback' };
      if (typeof data.reply !== 'string' || !data.reply.trim() || !Array.isArray(data.links) || prohibitedAIClaim(data.reply)) throw new Error('ai_invalid');
      return { mode: 'ai', reply: data.reply.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').trim().slice(0, 5000), links: sanitizeLinks(data.links).filter(function (link) { return !link.href.startsWith('mailto:'); }) };
    } finally {
      clearTimeout(timer);
      if (options.signal) options.signal.removeEventListener('abort', abort);
    }
  }

  async function respond(value, knowledge, options) {
    options = options || {};
    var question = cleanText(value, 300);
    var history = buildAIHistory(options.history, knowledge);
    var local = options.localAnswer || selectAnswer(question, knowledge);
    if (containsPersonalData(question, knowledge) && !options.plan && !isRestrictedLocal(question)) local = { kind: 'support', title: 'Vamos manter esses dados no suporte local', paragraphs: ['Sua pergunta contém dados de identificação ou contato. Descreva a dificuldade sem esses dados para continuar a orientação.'], steps: [], links: [{ href: '#contato', label: 'Contato do projeto' }] };
    if (!shouldUseAI(question, { aiEnabled: options.aiEnabled, aiAvailable: options.aiAvailable, knowledge: knowledge, plan: options.plan })) return { answer: local, mode: 'local', history: history, reason: 'local' };
    try {
      var remote = await requestAIResponse(question, history, options.fetchImpl, { signal: options.signal, knowledge: knowledge, timeoutMs: options.timeoutMs });
      if (remote.mode !== 'ai') return { answer: local, mode: 'local', history: history, reason: remote.reason };
      return { answer: { kind: 'ai', title: 'Resposta por IA', paragraphs: remote.reply.split(/\n\s*\n/).filter(Boolean), steps: [], links: remote.links }, mode: 'ai', history: buildAIHistory(history.concat([{ role: 'user', content: question }, { role: 'assistant', content: remote.reply }]), knowledge), reason: 'ai' };
    } catch (_) {
      return { answer: local, mode: 'local', history: history, reason: 'ai_failed' };
    }
  }

  function mount(doc) {
    var input = doc.getElementById('assistant-question');
    var send = doc.getElementById('assistant-send');
    var messages = doc.getElementById('assistant-messages');
    var status = doc.getElementById('assistant-status');
    if (!input || !send || !messages || !status || messages.dataset.assistantMounted === 'true') return false;
    messages.dataset.assistantMounted = 'true';
    var view = doc.defaultView;
    var fetchImpl = view && typeof view.fetch === 'function' ? view.fetch.bind(view) : null;
    var aiOption = doc.getElementById('assistant-ai-option');
    var aiMode = doc.getElementById('assistant-ai-mode');
    var modeStatus = doc.getElementById('assistant-mode-status');
    var privacy = doc.getElementById('assistant-privacy-note');
    var aiAvailable = false, history = [], busy = false, followup = false, pending = null;
    if (aiMode) { aiMode.checked = false; aiMode.disabled = true; }
    if (aiOption) aiOption.hidden = true;

    function updateMode() {
      var enabled = aiAvailable && aiMode && aiMode.checked;
      if (modeStatus) modeStatus.textContent = enabled ? 'Modo IA ativado para perguntas gerais do portal.' : 'Suporte local disponível.';
      if (privacy) privacy.textContent = enabled ? 'Com a IA ativada, perguntas gerais e um histórico curto são enviados ao serviço de IA da OpenAI. Identificação, pagamentos, documentos, contato e correções locais continuam no suporte local.' : 'O suporte local processa as perguntas neste navegador, sem enviá-las a um serviço de IA.';
    }

    if (aiMode) aiMode.addEventListener('change', function () {
      if (!aiAvailable) aiMode.checked = false;
      if (!aiMode.checked) { history = []; if (pending) pending.abort(); }
      updateMode();
    });
    updateMode();
    if (aiMode && fetchImpl) {
      (async function () {
        var controller = new AbortController();
        var timer = setTimeout(function () { controller.abort(); }, 7000);
        try {
          var response = await fetchImpl('/api/support/config', { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' }, signal: controller.signal });
          var config = response && response.ok ? await response.json() : null;
          aiAvailable = Boolean(config && config.ai_available === true);
        } catch (_) { aiAvailable = false; }
        finally { clearTimeout(timer); }
        aiMode.disabled = !aiAvailable;
        if (aiOption) aiOption.hidden = !aiAvailable;
        updateMode();
      })();
    }

    function addText(parent, tag, text) {
      var node = doc.createElement(tag); node.textContent = text; parent.appendChild(node); return node;
    }
    function trimMessages() {
      while (messages.children.length > 8) {
        messages.removeChild(messages.firstElementChild);
        if (messages.firstElementChild && messages.firstElementChild.classList.contains('assistant-answer')) messages.removeChild(messages.firstElementChild);
      }
    }
    function renderAnswer(answer, mode) {
      var node = doc.createElement('div'); node.className = 'assistant-message assistant-answer';
      addText(node, 'h3', answer.title);
      addText(node, 'small', mode === 'ai' ? 'Resposta por IA' : 'Suporte local');
      (answer.paragraphs || []).forEach(function (paragraph) { addText(node, 'p', paragraph); });
      if (answer.steps && answer.steps.length) { var list = doc.createElement('ol'); answer.steps.forEach(function (step) { addText(list, 'li', step); }); node.appendChild(list); }
      if (answer.links && answer.links.length) {
        var links = doc.createElement('div'); links.className = 'guide-actions';
        sanitizeLinks(answer.links).forEach(function (link) {
          var anchor = addText(links, 'a', link.label); anchor.setAttribute('href', link.href);
          if (link.href.startsWith('https://')) { anchor.setAttribute('target', '_blank'); anchor.setAttribute('rel', 'noopener noreferrer'); }
          else if (link.href.startsWith('#guia-')) anchor.addEventListener('click', function () { var target = doc.getElementById(link.href.slice(1)); var details = target && target.querySelector('details.guide-steps'); if (details) details.open = true; });
        }); node.appendChild(links);
      }
      if (answer.followUps && answer.followUps.length) {
        var actions = doc.createElement('div'); actions.className = 'guide-actions';
        answer.followUps.forEach(function (item) { var button = addText(actions, 'button', item.label); button.type = 'button'; button.className = 'assistant-followup'; button.addEventListener('click', function () { submit(item.question); }); }); node.appendChild(actions);
      }
      messages.appendChild(node); trimMessages(); messages.scrollTop = messages.scrollHeight;
    }
    async function submit(value) {
      if (busy) { status.textContent = 'Aguarde a resposta em andamento.'; return; }
      var question = cleanText(value, 300);
      if (!question) { status.textContent = 'Escreva uma dúvida antes de consultar.'; input.focus(); return; }
      busy = true; send.disabled = true; input.value = '';
      var queryNode = doc.createElement('div'); queryNode.className = 'assistant-message assistant-question'; addText(queryNode, 'strong', 'Sua pergunta'); addText(queryNode, 'p', question); messages.appendChild(queryNode); trimMessages();
      var knowledge = buildKnowledge(doc), plan = planSupportAction(question, { followup: followup });
      var local = plan ? applySupportAction(plan, doc, view && view.QGRendaAutomation) : selectAnswer(question, knowledge);
      followup = Boolean(local && local.followUps && local.followUps.length);
      pending = new AbortController();
      status.textContent = shouldUseAI(question, { aiEnabled: Boolean(aiMode && aiMode.checked), aiAvailable: aiAvailable, plan: plan, knowledge: knowledge }) ? 'Consultando a IA...' : 'Conferindo as orientações locais...';
      try {
        var result = await respond(question, knowledge, { localAnswer: local, plan: plan, aiEnabled: Boolean(aiMode && aiMode.checked), aiAvailable: aiAvailable, history: history, fetchImpl: fetchImpl, signal: pending.signal });
        if ((!aiMode || !aiMode.checked || !aiAvailable) && (result.mode === 'ai' || pending.signal.aborted)) result = { answer: local, mode: 'local', history: [], reason: 'local' };
        history = result.history;
        renderAnswer(result.answer, result.mode);
        status.textContent = result.reason === 'ai_failed' || result.reason === 'ai_fallback' ? 'A IA não respondeu agora. Usei as orientações locais do portal.' : result.mode === 'ai' ? 'Resposta por IA. Confira as referências indicadas.' : result.answer.kind === 'fallback' ? 'Não encontrei uma resposta específica. Consulte os temas ou o contato do projeto.' : 'Orientação concluída no suporte local.';
      } finally { pending = null; busy = false; send.disabled = false; input.focus(); }
    }
    send.addEventListener('click', function () { submit(input.value); });
    input.addEventListener('keydown', function (event) { if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); submit(input.value); } });
    doc.querySelectorAll('[data-assistant-question]').forEach(function (button) { button.addEventListener('click', function () { submit(button.getAttribute('data-assistant-question') || button.textContent); }); });
    return true;
  }

  return { normalize: normalize, safeLinkHref: safeLinkHref, buildKnowledge: buildKnowledge, selectAnswer: selectAnswer, planSupportAction: planSupportAction, applySupportAction: applySupportAction, containsPersonalData: containsPersonalData, isRestrictedLocal: isRestrictedLocal, buildAIHistory: buildAIHistory, shouldUseAI: shouldUseAI, requestAIResponse: requestAIResponse, respond: respond, mount: mount };
});
