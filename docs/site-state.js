(() => {
  'use strict';

  const SOURCE_NAMES = {
    domain_web: 'Domain',
    domain: 'Domain',
    farmbuy: 'Farmbuy',
    elders: 'Elders',
    rea_apify: 'REA',
    rea_web: 'REA',
    cre: 'Commercial Real Estate alerts',
    listing_loop: 'Listing Loop'
  };

  function setText(name, value) {
    if (value === null || value === undefined || value === '') return;
    document.querySelectorAll(`[data-state="${name}"]`).forEach((element) => {
      element.textContent = String(value);
    });
  }

  function formatScore(value) {
    const number = Number(value);
    return Number.isFinite(number) ? `${Math.round(number)}%` : 'Not available';
  }

  function sourceLabel(sources) {
    return Object.entries(sources || {})
      .filter(([, count]) => Number(count) > 0)
      .map(([source]) => SOURCE_NAMES[source] || source.replaceAll('_', ' '))
      .join(', ');
  }

  function applyState(state) {
    const inventory = state.inventory || {};
    const run = state.run || {};
    const scores = state.scores || {};
    const top = state.top_match || {};
    const market = state.market_data || {};

    setText('search-display', state.search_display);
    setText('available', inventory.available);
    setText('archived', inventory.archived);
    setText('possibly-unavailable', inventory.possibly_unavailable);
    setText('under-offer', inventory.under_offer);
    setText('source-count', inventory.source_count);
    setText('feed-count', inventory.automated_feed_count);
    setText('source-labels', sourceLabel(inventory.sources));
    setText('scanned', run.scanned || 'Not recorded');
    setText('passed-gates', run.passed_gates);
    setText('pass-rate', run.pass_rate === null || run.pass_rate === undefined ? 'Not recorded' : `${run.pass_rate}%`);
    setText('score-min', formatScore(scores.minimum));
    setText('score-max', formatScore(scores.maximum));
    setText('score-range', scores.minimum === null || scores.maximum === null ? 'Not available' : `${formatScore(scores.minimum)}–${formatScore(scores.maximum)}`);
    setText('top-match', top.headline || top.address);
    setText('top-score', formatScore(top.score));
    setText('market-sales', market.sales?.toLocaleString('en-AU'));
    setText('market-through', market.through);

    document.documentElement.dataset.siteState = 'ready';
  }

  fetch('site-state.json', { cache: 'no-store' })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(applyState)
    .catch((error) => {
      document.documentElement.dataset.siteState = 'unavailable';
      console.error('Current Bolt Hole publication state unavailable', error);
    });
})();
