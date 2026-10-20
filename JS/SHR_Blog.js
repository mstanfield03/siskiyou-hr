(() => {
  const tools = document.querySelector('.blog-tools');
  if (!tools) return;
  const cards = [...document.querySelectorAll('.blog-card')];
  const buttons = [...tools.querySelectorAll('[data-filter]')];
  const input = tools.querySelector('input[name="q"]');
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase();
  const index = new Map(cards.map(card => [card, normalize(card.dataset.search)]));
  let selected = 'all';
  function readURL() {
    const params = new URLSearchParams(location.search);
    input.value = params.get('q') || '';
    selected = ['article', 'video'].includes(params.get('type')) ? params.get('type') : 'all';
  }
  function update(saveURL = true) {
    const query = input.value.trim();
    const words = normalize(query).split(/\s+/).filter(Boolean);
    let count = 0;
    for (const card of cards) {
      const visible = (selected === 'all' || selected === card.dataset.format) && words.every(word => index.get(card).includes(word));
      card.hidden = !visible;
      if (visible) count++;
    }
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filter === selected)));
    const active = Boolean(query) || selected !== 'all';
    document.querySelector('.blog-no-results').hidden = count > 0 || !active;
    const empty = document.querySelector('.blog-empty');
    if (empty) empty.hidden = active;
    const featured = document.querySelector('.blog-featured');
    if (featured) featured.hidden = active;
    document.querySelector('#blog-count').textContent = `${count} ${count === 1 ? 'post' : 'posts'} shown`;
    if (saveURL) {
      const url = new URL(location.href);
      query ? url.searchParams.set('q', query) : url.searchParams.delete('q');
      selected === 'all' ? url.searchParams.delete('type') : url.searchParams.set('type', selected);
      history.replaceState(null, '', url);
    }
  }
  buttons.forEach(button => button.addEventListener('click', () => { selected = button.dataset.filter; update(); }));
  input.addEventListener('input', () => update());
  tools.addEventListener('submit', event => { event.preventDefault(); update(); });
  window.addEventListener('popstate', () => { readURL(); update(false); });
  readURL();
  update(false);
})();
