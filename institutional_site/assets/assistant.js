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
    var aboutNode = doc.querySelector('#sobre .about-text');
    return {
      faqs: faqs,
      guides: guides,
      contact: contactNode ? { email: cleanText(contactNode.textContent), href: safeLinkHref(contactNode.getAttribute('href')) } : null,
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
    if ((affiliation && asksAboutPortal) || /^(e |eh |do |da )?(do |da )?(governo|gov[ .]*br|oficial|receita federal)[?!. ]*$/.test(query)) {
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
    if (/\b(atendiment\w*|assistente|respost\w*|chatbot|robo)\b/.test(query) && (automatic || /\b(como funciona|como responde|quem responde|inteligencia artificial|humano|pessoa)\b/.test(query))) {
      return faqAnswer(findFaq(knowledge, /como funciona o atendimento automatico/), 'Como funciona o atendimento automático', 'O assistente consulta os guias e as perguntas frequentes do portal. Se não encontrar uma resposta, indica o contato do responsável. As consultas são processadas neste navegador e não são enviadas a serviços externos de atendimento.', [{ href: '#assistente', label: 'Consultar o assistente do portal' }]);
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

  function mount(doc) {
    var input = doc.getElementById('assistant-question');
    var send = doc.getElementById('assistant-send');
    var messages = doc.getElementById('assistant-messages');
    var status = doc.getElementById('assistant-status');
    if (!input || !send || !messages || !status || messages.dataset.assistantMounted === 'true') return false;
    messages.dataset.assistantMounted = 'true';

    function addText(parent, tag, text) {
      var node = doc.createElement(tag);
      node.textContent = text;
      parent.appendChild(node);
      return node;
    }

    function submit(value) {
      var question = cleanText(value, 300);
      if (!question) {
        status.textContent = 'Escreva uma dúvida antes de consultar.';
        input.focus();
        return;
      }
      var answer = selectAnswer(question, buildKnowledge(doc));
      var questionNode = doc.createElement('div');
      questionNode.className = 'assistant-message assistant-question';
      addText(questionNode, 'strong', 'Sua pergunta');
      addText(questionNode, 'p', question);
      messages.appendChild(questionNode);
      var answerNode = doc.createElement('div');
      answerNode.className = 'assistant-message assistant-answer';
      addText(answerNode, 'h3', answer.title);
      answer.paragraphs.forEach(function (paragraph) { addText(answerNode, 'p', paragraph); });
      if (answer.steps.length) {
        var list = doc.createElement('ol');
        answer.steps.forEach(function (step) { addText(list, 'li', step); });
        answerNode.appendChild(list);
      }
      if (answer.links.length) {
        var links = doc.createElement('div');
        links.className = 'guide-actions';
        sanitizeLinks(answer.links).forEach(function (link) {
          var anchor = addText(links, 'a', link.label);
          anchor.setAttribute('href', link.href);
          if (link.href.startsWith('https://')) {
            anchor.setAttribute('target', '_blank');
            anchor.setAttribute('rel', 'noopener noreferrer');
          } else if (link.href.startsWith('#guia-')) {
            anchor.addEventListener('click', function () {
              var target = doc.getElementById(link.href.slice(1));
              var details = target && target.querySelector('details.guide-steps');
              if (details) details.open = true;
            });
          }
        });
        answerNode.appendChild(links);
      }
      messages.appendChild(answerNode);
      while (messages.children.length > 8) messages.removeChild(messages.firstElementChild);
      messages.scrollTop = messages.scrollHeight;
      input.value = '';
      status.textContent = answer.kind === 'fallback' ? 'Não encontrei uma resposta para essa pergunta. Consulte os temas disponíveis ou o contato do projeto.' : 'Resposta localizada nos guias e perguntas do portal.';
      input.focus();
    }

    send.addEventListener('click', function () { submit(input.value); });
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.isComposing) {
        event.preventDefault();
        submit(input.value);
      }
    });
    doc.querySelectorAll('[data-assistant-question]').forEach(function (button) {
      button.addEventListener('click', function () { submit(button.getAttribute('data-assistant-question') || button.textContent); });
    });
    return true;
  }

  return { normalize: normalize, safeLinkHref: safeLinkHref, buildKnowledge: buildKnowledge, selectAnswer: selectAnswer, mount: mount };
});
