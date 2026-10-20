(() => {
  const tools = document.querySelector('.blog-tools');
  if (!tools) return;
  const cards = [...document.querySelectorAll('.blog-card')];
  if (!cards.length) return;
  tools.hidden = false;
  const buttons = [...tools.querySelectorAll('[data-filter]')];
  const input = tools.querySelector('input');
  let selected = 'all';
  function update() {
    const query = input.value.trim().toLocaleLowerCase();
    let count = 0;
    for (const card of cards) {
      const visible = (selected === 'all' || selected === card.dataset.format) && card.dataset.search.toLocaleLowerCase().includes(query);
      card.hidden = !visible;
      if (visible) count++;
    }
    document.querySelector('.blog-no-results').hidden = count > 0;
    document.querySelector('#blog-count').textContent = `${count} ${count === 1 ? 'post' : 'posts'} shown`;
  }
  buttons.forEach(button => button.addEventListener('click', () => {
    selected = button.dataset.filter;
    buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    update();
  }));
  input.addEventListener('input', update);
  update();
})();
