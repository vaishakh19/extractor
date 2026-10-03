(() => {
  const money = value => `$${Number(value || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
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
    } catch (_) { /* dashboard remains useful with its last local snapshot */ }
  }
  setInterval(refresh, 5000);
})();
