const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const label = value => String(value || '').replaceAll('_', ' ');
const safeURL = value => { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? esc(url.href) : '#'; } catch { return '#'; } };
const state = {project: '', run: '', projects: [], result: null, busy: false, fingerprint: '', offset: 0, search: false};
const terminal = ['cancelled', 'failed', 'insufficient_evidence', 'budget_exhausted', 'released', 'withdrawn'];
let identity = {tenant: 'TEN-LOCAL', user: 'local-user'};
try { identity = {...identity, ...JSON.parse(localStorage.getItem('regula-identity') || '{}')}; } catch {}
$('tenant').value = identity.tenant; $('user').value = identity.user;

async function api(path, method = 'GET', body) {
  const response = await fetch('/api/v1' + path, {method, headers: {'Content-Type': 'application/json', 'X-Tenant-Id': identity.tenant, 'X-User-Id': identity.user}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof (data.error || data.detail) === 'string' ? (data.error || data.detail) : 'Please check the entered values and try again.');
  return data;
}
const runPath = () => `/projects/${encodeURIComponent(state.project)}/runs/${encodeURIComponent(state.run)}`;
function notice(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }
function canWrite() { const project = state.projects.find(p => p.project_id === state.project); return (project?.members?.[identity.user] || []).some(r => ['admin', 'researcher'].includes(r)); }
async function action(callback, form) {
  if (state.busy) return;
  state.busy = true; notice();
  const buttons = [...document.querySelectorAll('button')];
  const prior = buttons.map(button => button.disabled);
  buttons.forEach(button => button.disabled = true);
  if (form) form.querySelector('.form-error').textContent = '';
  try { await callback(); }
  catch (error) { if (form && form.closest('dialog').open) form.querySelector('.form-error').textContent = error.message; else notice(error.message); }
  finally { buttons.forEach((button, i) => button.disabled = prior[i]); state.busy = false; $('new-run').disabled = !canWrite(); if (state.result) controls(state.result.run, state.result.execution); }
}
function remember() { const params = new URLSearchParams(); if (state.project) params.set('project', state.project); if (state.run) params.set('run', state.run); history.replaceState(null, '', '/dashboard' + (params.size ? '?' + params : '')); }
async function all(path, key) { let result = [], offset = 0; while (true) { const page = (await api(`${path}?limit=100&offset=${offset}`))[key]; result.push(...page); if (page.length < 100) return result; offset += 100; } }
async function projects() {
  state.projects = await all('/projects', 'projects');
  $('project').innerHTML = '<option value="">Select a project</option>' + state.projects.map(p => `<option value="${esc(p.project_id)}">${esc(p.name)}</option>`).join('');
  if (!state.projects.some(p => p.project_id === state.project)) state.project = state.projects[0]?.project_id || '';
  $('project').value = state.project;
  $('project-title').textContent = state.projects.find(p => p.project_id === state.project)?.name || 'Your research, with evidence.';
  $('new-run').disabled = !canWrite();
  $('empty-action').textContent = state.project ? 'New research' : 'Create project';
  $('empty-action').disabled = !!state.project && !canWrite();
  await runs();
}
async function runs() {
  const list = state.project ? await all(`/projects/${encodeURIComponent(state.project)}/runs`, 'runs') : [];
  $('runs').innerHTML = list.length ? list.map(r => `<button data-run="${esc(r.run_id)}" class="${r.run_id === state.run ? 'active' : ''}">${esc(r.research_request.title)}<small>${esc(label(r.state))}</small></button>`).join('') : '<p class="muted">No research runs yet.</p>';
  if (!list.some(r => r.run_id === state.run)) state.run = list[0]?.run_id || '';
  state.fingerprint = ''; state.offset = 0; state.search = false; $('search').value = '';
  remember(); await results();
}
async function results() {
  $('workspace').hidden = !state.run; $('empty').hidden = !!state.run;
  if (!state.run) { state.result = null; return; }
  const path = runPath();
  const data = await api(path + '/results');
  if (path !== runPath()) return;
  state.result = data;
  const fingerprint = JSON.stringify(data);
  if (fingerprint === state.fingerprint) return;
  state.fingerprint = fingerprint;
  render(data);
  document.querySelectorAll('[data-run]').forEach(button => { button.classList.toggle('active', button.dataset.run === state.run); if (button.dataset.run === state.run) button.querySelector('small').textContent = label(data.run.state); });
}
function controls(run, job) {
  const roles = state.projects.find(p => p.project_id === state.project)?.members?.[identity.user] || [];
  const reviewer = roles.some(r => ['reviewer','admin'].includes(r));
  const publisher = roles.some(r => ['publisher','admin'].includes(r));
  const result = state.result || {};
  $('review-button').hidden = run.state !== 'reviewing' || !reviewer;
  $('review-button').disabled = state.busy;
  $('approval-form').hidden = run.state !== 'awaiting_approval' || !reviewer || !result.release_enabled;
  $('release-button').hidden = run.state !== 'approved' || !publisher || !result.release_enabled;
  $('release-button').disabled = state.busy;
  const review = result.model_review;
  $('review-summary').textContent = review ? (review.passed ? 'Model review passed. Human approval is required.' : 'Blocked: ' + review.blockers.join(' ')) : 'Model review has not run.';
  $('release-links').textContent = result.release ? 'Released: ' + result.release.release_id : '';

  const pending = run.state === 'awaiting_scope_confirmation';
  const reserved = job && ['queued','running'].includes(job.status);
  $('plan-button').hidden = !pending || !!run.research_plan;
  $('plan-button').disabled = state.busy || !canWrite();
  $('execute-options').hidden = !(run.research_plan && (pending || run.state === 'queued'));
  $('execute-button').textContent = pending ? 'Confirm scope & start research' : 'Start research';
  $('execute-button').disabled = state.busy || !canWrite();
  $('full-text').disabled = !run.research_request.approved_source_domains.length;
  if ($('full-text').disabled) $('full-text').checked = false;
  $('cancel').hidden = terminal.includes(run.state) || run.state === 'release_pending';
  $('cancel').disabled = state.busy || !canWrite();
  $('retry').hidden = !terminal.includes(run.state);
  $('retry').disabled = state.busy || !canWrite();
  $('plan-panel').hidden = !pending && run.state !== 'queued' && !!reserved;
}
function render({run, execution: job, draft, evidence, findings}) {
  $('run-id').textContent = run.run_id;
  $('run-title').textContent = run.research_request.title;
  $('question').textContent = run.research_request.primary_question;
  $('state').textContent = label(run.state);
  $('scope').textContent = run.research_request.scope_description;
  const plan = run.research_plan;
  $('plan-content').innerHTML = plan ? `<h4>Questions to explore</h4><ul>${(plan.subquestions || []).map(q => `<li>${esc(typeof q === 'string' ? q : JSON.stringify(q))}</li>`).join('')}</ul><h4>Search queries</h4><ul>${(plan.search_queries || []).map(q => `<li>${esc(q)}</li>`).join('')}</ul><p class="muted">Approved domains: ${esc(run.research_request.approved_source_domains.join(', ') || 'No domain restriction for abstracts')}</p>` : '<p class="muted">Generate a plan, then review it before starting collection.</p>';
  const index = {awaiting_scope_confirmation: 0, queued: 1, collecting: 2, synthesizing: 3, reviewing: 4}[run.state] ?? -1;
  $('stages').innerHTML = ['Plan','Confirm','Collect','Draft','Review'].map((name, i) => `<li class="${i <= index ? 'reached' : ''}">${name}</li>`).join('');
  $('job-message').textContent = terminal.includes(run.state) ? (job?.message || label(run.state)) : (job?.message || (plan ? 'Review the plan and confirm the research scope.' : 'Ready to plan your research.'));
  $('metrics').innerHTML = [[job?.source_count ?? '—','Sources discovered'],[job?.evidence_count ?? evidence.length,'Passages collected'],[job?.citation_check?.validated_claims ?? '—','Claims checked for citation integrity']].map(([n,t]) => `<div class="metric"><strong>${esc(n)}</strong><span>${t}</span></div>`).join('');
  if (!state.search && state.offset === 0) showEvidence(evidence);
  $('draft').innerHTML = draft ? `<p>${esc(draft.abstract)}</p><div class="draft-copy">${esc(draft.conclusions)}</div><h4>References</h4><ol>${draft.references.map(r => `<li><a href="${safeURL(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)} ↗</a></li>`).join('')}</ol><p class="muted">Citation checks verify links and passage text. They do not establish factual correctness or authorize release.</p>` : '<p class="muted">The draft appears after evidence collection.</p>';
  $('outcomes').innerHTML = '<h4>Discovery providers</h4>' + (job?.provider_outcomes?.length ? job.provider_outcomes.map(o => `<p>${esc(o.provider)} · ${esc(label(o.status))}${o.fallback ? ' · fallback used' : ''}</p>`).join('') : '<p class="muted">No provider outcomes yet.</p>') + '<h4>Full documents</h4>' + (job?.documents?.length ? job.documents.map(d => `<p>${esc(d.title)} · ${esc(d.status)}</p>`).join('') : '<p class="muted">Full-document collection has not run.</p>') + '<h4>Citation findings</h4>' + (findings.length ? findings.map(f => `<p>${esc(f.severity)} · ${esc(f.explanation)}</p>`).join('') : '<p class="muted">No findings recorded.</p>');
  controls(run, job);
}
function showEvidence(evidence, append = false) {
  const html = evidence.map(e => `<div class="evidence-item"><h4><a href="${safeURL(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.title)} ↗</a></h4><span class="muted">${esc((e.authors || []).join(', ') || 'Author not listed')} · ${esc(label(e.source_type))}</span><p>${esc(e.passage)}</p><details><summary>Citation & provenance</summary><p>${esc(e.source_use_decision)} · ${esc(e.eligibility_status)}</p><code>${esc(e.evidence_id)}<br>${esc(e.source_snapshot_id)}</code></details></div>`).join('');
  if (append) $('evidence').insertAdjacentHTML('beforeend', html); else $('evidence').innerHTML = html || '<p class="muted">No matching evidence yet.</p>';
  $('more-evidence').hidden = state.search || evidence.length < 100;
  $('evidence-count').textContent = `${$('evidence').querySelectorAll('.evidence-item').length} shown${state.search ? ' · search results (up to 100)' : ''}`;
}
function openDialog(id) { $(id).querySelector('.form-error').textContent = ''; $(id).showModal(); }
$('new-project').onclick = () => openDialog('project-dialog');
$('new-run').onclick = () => { $('run-form').reset(); openDialog('run-dialog'); };
$('empty-action').onclick = () => state.project ? $('new-run').click() : $('new-project').click();
document.querySelectorAll('[data-close]').forEach(button => button.onclick = () => $(button.dataset.close).close());
$('project').onchange = () => action(async () => { state.project = $('project').value; state.run = ''; await projects(); });
$('runs').onclick = event => { const button = event.target.closest('[data-run]'); if (button) action(async () => { state.run = button.dataset.run; await runs(); }); };
$('refresh').onclick = () => action(projects);
$('project-form').onsubmit = event => { event.preventDefault(); action(async () => { const data = Object.fromEntries(new FormData(event.target)); if (!data.name.trim()) throw new Error('Enter a project name.'); const created = await api('/projects','POST',data); state.project = created.project.project_id; state.run = ''; $('project-dialog').close(); event.target.reset(); await projects(); }, event.target); };
$('run-form').onsubmit = event => { event.preventDefault(); action(async () => {
  const data = Object.fromEntries(new FormData(event.target));
  for (const key of ['title','primary_question','scope_description']) { data[key] = data[key].trim(); if (!data[key]) throw new Error('Enter a title, question, and scope.'); }
  for (const key of ['approved_source_domains','excluded_domains']) { data[key] = data[key].split(',').map(s => s.trim().toLowerCase()).filter(Boolean); if (data[key].some(d => !/^(\*\.)?[a-z0-9.-]+\.[a-z]{2,}$/i.test(d))) throw new Error('Enter domain names without https:// or paths.'); }
  data.date_range_start ||= null; data.date_range_end ||= null;
  if (data.date_range_start && data.date_range_end && data.date_range_start > data.date_range_end) throw new Error('The end date must be on or after the start date.');
  data.max_sources = Number(data.max_sources);
  const created = await api(`/projects/${encodeURIComponent(state.project)}/runs`, 'POST', data);
  state.run = created.run.run_id; $('run-dialog').close(); await runs();
}, event.target); };
$('plan-button').onclick = () => action(async () => { await api(runPath() + '/plan','POST'); await results(); });
$('execute-button').onclick = () => action(async () => { const full_text = $('full-text').checked; if (state.result.run.state === 'awaiting_scope_confirmation') await api(runPath() + '/confirm-scope','POST',{confirmed:true}); try { await api(runPath() + '/execute','POST',{full_text}); } finally { await results(); } });
$('cancel').onclick = () => action(async () => { await api(runPath() + '/cancel','POST'); await results(); });
$('retry').onclick = () => { $('run-form').reset(); const data = state.result.run.research_request; for (const [key, value] of Object.entries(data)) { const field = $('run-form').elements.namedItem(key); if (field) field.value = Array.isArray(value) ? value.join(', ') : (key.startsWith('date_range') ? (value || '').slice(0,10) : value ?? ''); } openDialog('run-dialog'); };
$('search-form').onsubmit = event => { event.preventDefault(); action(async () => { const query = $('search').value.trim(); if (!query) { state.search = false; state.offset = 0; showEvidence(state.result.evidence); return; } const result = await api(runPath() + '/search','POST',{query, limit:100, search_type:'keyword'}); state.search = true; showEvidence(result.results || result.evidence || []); }); };
$('clear-search').onclick = () => { $('search').value = ''; state.search = false; state.offset = 0; if (state.result) showEvidence(state.result.evidence); };
$('more-evidence').onclick = () => action(async () => { const next = state.offset + 100; const data = await api(runPath() + `/results?offset=${next}&limit=100`); state.offset = next; showEvidence(data.evidence, true); });
$('identity-form').onsubmit = event => { event.preventDefault(); action(async () => { const tenant = $('tenant').value.trim(), user = $('user').value.trim(); if (!tenant || !user) throw new Error('Enter both tenant and user.'); identity = {tenant,user}; localStorage.setItem('regula-identity', JSON.stringify(identity)); state.project = ''; state.run = ''; state.result = null; $('identity').open = false; await projects(); }); };
async function boot() {
  const params = new URLSearchParams(location.search); state.project = params.get('project') || ''; state.run = params.get('run') || '';
  await action(async () => { const info = await api('/ai/status'); $('provider').textContent = info.provider === 'mock' ? 'Offline planner · no model charges' : `${label(info.provider)} planner`; await projects(); });
  setInterval(async () => { if (state.busy || !state.run || document.hidden) return; try { await results(); } catch (error) { notice('Could not refresh: ' + error.message); } }, 1500);
}
boot();

$('review-button').onclick = () => action(async () => { await api(runPath() + '/review', 'POST'); await results(); });
$('approval-form').onsubmit = event => { event.preventDefault(); action(async () => { await api(runPath() + '/request-approval', 'POST', {approval_rationale: $('approval-rationale').value}); await results(); }); };
$('release-button').onclick = () => action(async () => { if (!confirm('Publish the exact approved report for this project?')) return; await api(runPath() + '/release', 'POST', {approval_id: state.result.approval.approval_id}); await results(); });
