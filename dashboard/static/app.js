(() => {
  'use strict';

  const money = value => `$${Number(value || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

  function buildParticles() {
    const field = document.querySelector('#pixel-particles');
    if (!field || field.children.length) return;

    const fragment = document.createDocumentFragment();
    const count = 42;
    for (let index = 0; index < count; index += 1) {
      const particle = document.createElement('i');
      const size = 2 + ((index * 7) % 4);
      const left = (index * 37 + 11) % 100;
      const top = (index * 61 + 7) % 100;
      const duration = 0.9 + ((index * 13) % 17) / 10;
      const delay = -((index * 19) % 23) / 10;

      particle.className = `particle${index % 7 === 0 ? ' cross' : ''}`;
      particle.style.left = `${left}%`;
      particle.style.top = `${top}%`;
      particle.style.setProperty('--size', `${size}px`);
      particle.style.setProperty('--duration', `${duration}s`);
      particle.style.setProperty('--delay', `${delay}s`);
      particle.style.setProperty(
        '--particle-color',
        index % 4 === 0 ? 'var(--lime)' : 'var(--cream)',
      );
      fragment.appendChild(particle);
    }
    field.appendChild(fragment);
  }

  function setupNavigation() {
    const button = document.querySelector('#menu-button');
    const navigation = document.querySelector('#primary-nav');
    if (!button || !navigation) return;

    button.addEventListener('click', () => {
      const open = navigation.classList.toggle('open');
      button.setAttribute('aria-expanded', String(open));
    });

    navigation.addEventListener('click', event => {
      if (event.target instanceof HTMLAnchorElement) {
        navigation.classList.remove('open');
        button.setAttribute('aria-expanded', 'false');
      }
    });
  }

  function setupWalletNotice() {
    const button = document.querySelector('#wallet-button');
    const dialog = document.querySelector('#wallet-dialog');
    if (!button || !(dialog instanceof HTMLDialogElement)) return;
    button.addEventListener('click', () => dialog.showModal());
  }

  async function refresh() {
    try {
      const response = await fetch('/api/status', {cache: 'no-store'});
      if (!response.ok) return;
      const state = await response.json();
      const status = document.querySelector('#bot-status');
      const balance = document.querySelector('#balance');
      const equity = document.querySelector('#equity');
      if (status) status.textContent = state.bot_status;
      if (balance) balance.textContent = money(state.balance);
      if (equity) equity.textContent = money(state.equity);
    } catch (_) {
      // The latest local snapshot remains visible during a temporary disconnect.
    }
  }

  buildParticles();
  setupNavigation();
  setupWalletNotice();
  refresh();
  setInterval(refresh, 5000);
})();
