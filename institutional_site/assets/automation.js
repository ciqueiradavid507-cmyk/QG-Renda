(function () {
  'use strict';

  function start() {
    var summary = document.getElementById('automation-summary');
    var checked = document.getElementById('automation-checked');
    if (!summary || !checked) return;
    var timer = null;
    var inFlight = false;

    function text(value, limit) {
      if (typeof value !== 'string') return '';
      var clean = value.replace(/\s+/g, ' ').trim();
      var maximum = limit || 300;
      if (clean.length <= maximum) return clean;
      var clipped = clean.slice(0, maximum - 1);
      var space = clipped.lastIndexOf(' ');
      if (space > maximum * 0.6) clipped = clipped.slice(0, space);
      return clipped.trim() + '…';
    }

    function date(value) {
      if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) return '';
      return new Intl.DateTimeFormat('pt-BR', {
        dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Belem'
      }).format(new Date(value)) + ' (UTC−3)';
    }

    function field(block, selector, value) {
      var node = block.querySelector(selector);
      if (!node) return;
      node.textContent = value;
      node.hidden = !value;
    }

    function renderSource(block, source) {
      var status = source.status === 'ok' ? 'ok' : source.status === 'unavailable' ? 'unavailable' : 'pending';
      block.dataset.state = status;
      var when = date(source.checked_at);
      var message = status === 'ok'
        ? 'Fonte acessível na última verificação.'
        : status === 'unavailable'
          ? 'Não foi possível confirmar esta fonte na última verificação.'
          : 'Aguardando a verificação automática da fonte.';
      if (when) message += ' Consulta: ' + when + '.';
      field(block, '.source-check', message);
      var title = text(source.title, 180);
      field(block, '.source-title', title ? 'Na fonte: ' + title : '');
      var description = source.description_origin === 'source' ? text(source.description, 280) : '';
      field(block, '.source-description', description ? 'Resumo publicado na fonte: ' + description : '');
      var success = date(source.last_success_at);
      var change = date(source.last_content_change_at);
      field(block, '.source-updated', status === 'unavailable' && success
        ? 'Últimas informações confirmadas em ' + success + '.'
        : change ? 'Dados da fonte capturados em ' + change + '.' : '');
    }

    function count(value) {
      return Number.isFinite(value) ? Math.max(0, Math.min(100, Math.floor(value))) : 0;
    }

    function render(data) {
      if (!data || data.enabled !== true || !Array.isArray(data.sources)) throw new Error('Dados indisponíveis');
      var sources = data.sources.slice(0, 20);
      var totals = data.summary || {};
      var total = count(totals.total) || sources.length;
      var ok = count(totals.ok);
      var unavailable = count(totals.unavailable);
      if (data.last_error) {
        summary.textContent = 'A verificação mais recente não pôde ser concluída. As referências dos guias continuam disponíveis.';
      } else if (!data.last_checked_at) {
        summary.textContent = data.refreshing ? 'Verificando as fontes agora...' : 'Aguardando a primeira verificação das fontes.';
      } else {
        summary.textContent = ok + ' de ' + total + ' fontes confirmadas na última verificação.'
          + (unavailable ? ' ' + unavailable + ' não puderam ser confirmadas.' : '')
          + (data.refreshing ? ' Uma nova verificação está em andamento.' : '');
      }
      var when = date(data.last_checked_at);
      checked.textContent = (when ? 'Última verificação: ' + when + '. ' : '')
        + 'Rotina programada a cada seis horas. A revisão editorial está indicada em cada guia.';
      document.querySelectorAll('[data-source-id]').forEach(function (block) {
        var id = block.getAttribute('data-source-id');
        var source = sources.find(function (entry) { return entry && entry.id === id; });
        if (source) renderSource(block, source);
      });
      window.QGRendaAutomation = {
        last_checked_at: data.last_checked_at || null,
        refreshing: data.refreshing === true,
        last_error: data.last_error || null,
        sources: sources.map(function (source) {
          return {
            id: text(source.id, 40), name: text(source.name, 120),
            url: text(source.url, 1200), status: source.status,
            http_status: source.http_status || null,
            checked_at: source.checked_at || null,
            last_success_at: source.last_success_at || null
          };
        })
      };
      document.dispatchEvent(new CustomEvent('qgrenda:automation-updated', { detail: window.QGRendaAutomation }));
      return data.refreshing === true;
    }

    function schedule(delay) {
      clearTimeout(timer);
      if (document.visibilityState !== 'hidden') timer = setTimeout(update, delay);
    }

    async function update() {
      if (inFlight || document.visibilityState === 'hidden') return;
      inFlight = true;
      var controller = new AbortController();
      var timeout = setTimeout(function () { controller.abort(); }, 15000);
      var delay = 300000;
      try {
        var response = await fetch('/api/automation', { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error('Verificação indisponível');
        delay = render(await response.json()) ? 5000 : 300000;
      } catch (_) {
        summary.textContent = 'Não foi possível consultar a verificação agora. Os links para as fontes continuam disponíveis nos guias.';
        if (window.QGRendaAutomation) window.QGRendaAutomation.last_error = 'status_unavailable';
        delay = 60000;
      } finally {
        clearTimeout(timeout);
        inFlight = false;
        schedule(delay);
      }
    }

    document.addEventListener('visibilitychange', function () {
      clearTimeout(timer);
      if (document.visibilityState !== 'hidden') update();
    });
    update();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
}());
