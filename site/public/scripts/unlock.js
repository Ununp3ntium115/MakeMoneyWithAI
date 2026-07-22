(async () => {
  const el = document.getElementById('full-playbook');
  if (!el) return;
  const res = await fetch(`/api/playbook/${el.dataset.slug}`);
  if (res.status !== 200) return; // keep the subscribe prompt
  const pb = await res.json();
  const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  el.innerHTML =
    '<h2>Full playbook</h2>' +
    pb.business_models.map((b) =>
      `<h3>${esc(b.name)} (${esc(b.difficulty)})</h3><p>${esc(b.description)}</p>` +
      `<p>Cost: ${esc(b.startup_cost)} · Potential: ${esc(b.revenue_potential)}</p>`).join('') +
    '<h3>Getting started</h3><ol>' + pb.getting_started_steps.map((s) => `<li>${esc(s)}</li>`).join('') + '</ol>' +
    `<p><strong>Running cost:</strong> ${esc(pb.cost_estimate)}</p>` +
    '<h3>Risks</h3><ul>' + pb.risks.map((r) => `<li>${esc(r)}</li>`).join('') + '</ul>';
})();
