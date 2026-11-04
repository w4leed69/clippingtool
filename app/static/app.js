const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
let META = null;

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = msg.map(d => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
    throw new Error(msg || `Request failed (${res.status})`);
  }
  return data;
}
const postJSON = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

function toast(msg, isErr = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (isErr ? ' err' : '');
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), isErr ? 6000 : 3000);
}
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ---------- tabs ---------- */
function showTab(name) {
  $$('#nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  $$('.tab').forEach(t => t.classList.toggle('active', t.id === `tab-${name}`));
  try { localStorage.setItem('tab', name); } catch { /* storage unavailable */ }
}
$$('#nav button').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));

/* ---------- meta / selects ---------- */
function fillSelect(sel, items, value) {
  sel.innerHTML = items.map(i => `<option value="${esc(i.id)}">${esc(i.name)}</option>`).join('');
  if (value !== undefined) sel.value = value;
}

async function loadMeta() {
  META = await api('/api/meta');
  $$('[data-voices]').forEach(s => fillSelect(s, META.voices, s.name === 'voice_them' ? 'edge:en-US-EmmaMultilingualNeural'
    : s.name === 'voice_me' ? 'edge:en-US-BrianMultilingualNeural' : 'edge:en-US-AndrewMultilingualNeural'));
  $$('[data-styles]').forEach(s => fillSelect(s, META.caption_styles));
  $$('[data-themes]').forEach(s => fillSelect(s, META.chat_themes.map(t => ({ id: t, name: t[0].toUpperCase() + t.slice(1) }))));
  $('#broll-hint').textContent = META.pexels_enabled
    ? 'Free stock footage from Pexels is matched to what is said, plus your own B-roll library.'
    : 'Uses clips from your Library > B-roll (named after what they show). Add PEXELS_API_KEY for automatic stock footage.';
  renderBroll();
  renderMusic();
  renderBackgrounds();
  $('#ai-status').innerHTML = META.ai_enabled ? '✨ Claude AI connected' : 'AI writing off: set ANTHROPIC_API_KEY';
}

function renderMusic() {
  const items = [{ id: '', name: 'No music' }, ...(META.music.length ? [{ id: 'random', name: 'Random track' }] : []), ...META.music];
  $$('[data-music]').forEach(s => { const v = s.value; fillSelect(s, items); s.value = v || ''; });
  $('#library-music').innerHTML = META.music.length
    ? META.music.map(m => `<li><audio controls preload="none" src="${esc(m.url)}"></audio>${esc(m.name)}</li>`).join('')
    : '<li class="empty">No music yet. Upload royalty-free tracks you can use.</li>';
}

const bgChoice = {};
function renderBackgrounds() {
  $$('[data-bg-picker]').forEach(p => {
    const key = p.dataset.bgPicker;
    bgChoice[key] = bgChoice[key] || 'random';
    p.innerHTML = `<div class="bg-item random" data-id="random">🎲<span>Random</span></div>` + META.backgrounds.map(b =>
      `<div class="bg-item" data-id="${esc(b.id)}"><video muted loop playsinline preload="metadata" src="${esc(b.url)}#t=1"></video><span>${esc(b.name)}</span></div>`).join('');
    $$('.bg-item', p).forEach(item => {
      item.classList.toggle('selected', item.dataset.id === bgChoice[key]);
      item.addEventListener('click', () => { bgChoice[key] = item.dataset.id; $$('.bg-item', p).forEach(i => i.classList.toggle('selected', i === item)); });
      const v = $('video', item);
      if (v) { item.addEventListener('mouseenter', () => v.play().catch(() => {})); item.addEventListener('mouseleave', () => v.pause()); }
    });
  });
  $('#library-bgs').innerHTML = META.backgrounds.map(b =>
    `<div class="bg-item"><video muted loop playsinline preload="metadata" src="${esc(b.url)}#t=1"></video><span>${esc(b.name)}</span></div>`).join('');
  $$('#library-bgs .bg-item').forEach(item => {
    const v = $('video', item);
    item.addEventListener('mouseenter', () => v.play().catch(() => {}));
    item.addEventListener('mouseleave', () => v.pause());
  });
}

/* ---------- form helpers ---------- */
function formData(form) {
  const out = {};
  $$('input[name], select[name], textarea[name]', form).forEach(el => {
    if (el.type === 'checkbox') out[el.name] = el.checked;
    else if (el.value === '') return;
    else if (el.type === 'number' || el.type === 'range') out[el.name] = Number(el.value);
    else if (el.name === 'part_seconds') out[el.name] = Number(el.value);
    else out[el.name] = el.value;
  });
  return out;
}

async function withBusy(btn, fn) {
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = 'Working…';
  try { return await fn(); }
  catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; btn.textContent = label; }
}

/* ---------- source widgets (upload or URL) ---------- */
$$('[data-source]').forEach(slot => {
  slot.appendChild($('#source-tpl').content.cloneNode(true));
  $$('.seg button', slot).forEach(b => b.addEventListener('click', () => {
    $$('.seg button', slot).forEach(x => x.classList.toggle('active', x === b));
    $$('[data-pane]', slot).forEach(p => (p.hidden = p.dataset.pane !== b.dataset.mode));
  }));
});

async function resolveSource(form) {
  const slot = $('[data-source]', form);
  const mode = $('.seg button.active', slot).dataset.mode;
  if (mode === 'url') {
    const url = $('[data-url]', slot).value.trim();
    if (!url) throw new Error('Paste a video URL');
    return { url };
  }
  const file = $('[data-file]', slot).files[0];
  if (!file) throw new Error('Choose a video file');
  if (slot._uploaded && slot._uploaded.file === file) return { upload_id: slot._uploaded.id };
  const status = $('[data-upload-status]', slot);
  status.textContent = 'Uploading…';
  const fd = new FormData();
  fd.append('file', file);
  const res = await api('/api/uploads', { method: 'POST', body: fd });
  slot._uploaded = { file, id: res.id };
  status.textContent = 'Uploaded ✓';
  return { upload_id: res.id };
}

/* ---------- story ---------- */
$('#form-story').addEventListener('submit', e => {
  e.preventDefault();
  const btn = $('button[type=submit]', e.target);
  withBusy(btn, async () => {
    const body = { ...formData(e.target), background: bgChoice.story };
    await postJSON('/api/jobs/story', body);
    toast('Rendering started');
    refreshJobs();
  });
});
$('#story-ai').addEventListener('click', e => withBusy(e.target, async () => {
  const idea = $('#story-idea').value.trim();
  if (!idea) throw new Error('Describe your story idea first');
  const res = await postJSON('/api/ai/script', { kind: 'story', idea, seconds: Number($('#story-seconds').value) });
  const f = $('#form-story');
  f.elements.title.value = res.title;
  f.elements.body.value = res.body;
  toast('Story written. Edit it if you like, then generate.');
}));

/* ---------- chat ---------- */
function addMessage(sender, text = '') {
  const row = document.createElement('div');
  row.className = `msg ${sender}`;
  row.dataset.sender = sender;
  row.innerHTML = `<span class="who">${sender === 'me' ? 'Me' : 'Them'}</span><input maxlength="1000" placeholder="Message…">` +
    `<button type="button" title="Swap sender">⇄</button><button type="button" title="Remove">✕</button>`;
  $('input', row).value = text;
  const [swap, del] = $$('button', row);
  swap.addEventListener('click', () => {
    const s = row.dataset.sender === 'me' ? 'them' : 'me';
    row.dataset.sender = s;
    row.className = `msg ${s}`;
    $('.who', row).textContent = s === 'me' ? 'Me' : 'Them';
  });
  del.addEventListener('click', () => row.remove());
  $('#chat-messages').appendChild(row);
  return row;
}
$$('[data-add]').forEach(b => b.addEventListener('click', () => $('input', addMessage(b.dataset.add)).focus()));
[['them', 'Why is there a goat in the backyard'], ['me', 'what goat'], ['them', 'The one eating my roses'], ['me', "Oh. That's Kevin. He lives here now."]]
  .forEach(([s, t]) => addMessage(s, t));

$('#form-chat').addEventListener('submit', e => {
  e.preventDefault();
  const btn = $('button[type=submit]', e.target);
  withBusy(btn, async () => {
    const messages = $$('#chat-messages .msg').map(r => ({ sender: r.dataset.sender, text: $('input', r).value.trim() })).filter(m => m.text);
    if (!messages.length) throw new Error('Add at least one message');
    await postJSON('/api/jobs/chat', { ...formData(e.target), messages, background: bgChoice.chat });
    toast('Rendering started');
    refreshJobs();
  });
});
$('#chat-ai').addEventListener('click', e => withBusy(e.target, async () => {
  const idea = $('#chat-idea').value.trim();
  if (!idea) throw new Error('Describe the conversation first');
  const res = await postJSON('/api/ai/script', { kind: 'chat', idea, seconds: 60 });
  $('#form-chat').elements.contact_name.value = res.contact_name.slice(0, 40);
  $('#chat-messages').innerHTML = '';
  res.messages.forEach(m => addMessage(m.sender, m.text));
  toast('Conversation written');
}));

/* ---------- AI studio ---------- */
const studioForm = $('#form-studio');
function syncFeatures() {
  $$('.feature', studioForm).forEach(f => {
    const sw = $('.feature-head .switch', f);
    const on = sw ? sw.checked : true;
    f.classList.toggle('on', on);
    const body = $('.feature-body', f), off = $('.feature-off', f);
    if (body) body.hidden = !on;
    if (off) off.hidden = on;
  });
  $('.feature-split', studioForm).hidden = studioForm.elements.reframe.value !== 'split';
}
studioForm.addEventListener('change', syncFeatures);
syncFeatures();

studioForm.addEventListener('submit', e => {
  e.preventDefault();
  const btn = $('button[type=submit]', studioForm);
  withBusy(btn, async () => {
    const data = formData(studioForm);
    if (data.voiceover && !data.vo_script && !META.ai_enabled)
      throw new Error('AI voice-over needs ANTHROPIC_API_KEY to write the script, or write one yourself');
    if (!data.clip) { delete data.clip_count; delete data.clip_min; delete data.clip_max; }
    const src = await resolveSource(studioForm);
    await postJSON('/api/jobs/studio', { ...data, ...src, background: bgChoice.studio });
    toast('Working on it. Longer videos take a few minutes.');
    refreshJobs();
  });
});

async function renderBroll() {
  try {
    const items = await api('/api/broll');
    $('#library-broll').innerHTML = items.length
      ? items.map(b => `<li>🎞️ ${esc(b.name)}</li>`).join('')
      : '<li class="empty">No B-roll clips yet.</li>';
  } catch { /* ignore */ }
}

/* ---------- library ---------- */
async function uploadTo(path, input) {
  const file = input.files[0];
  if (!file) throw new Error('Choose a file first');
  const fd = new FormData();
  fd.append('file', file);
  await api(path, { method: 'POST', body: fd });
  input.value = '';
  await loadMeta();
  toast('Added to library');
}
$('#bg-upload').addEventListener('click', e => withBusy(e.target, () => uploadTo('/api/backgrounds', $('#bg-file'))));
$('#broll-upload').addEventListener('click', e => withBusy(e.target, () => uploadTo('/api/broll', $('#broll-file'))));
$('#music-upload').addEventListener('click', e => withBusy(e.target, () => uploadTo('/api/music', $('#music-file'))));
$('#bg-download').addEventListener('click', e => withBusy(e.target, async () => {
  const url = $('#bg-url').value.trim();
  if (!url) throw new Error('Paste a URL');
  await postJSON('/api/backgrounds/url', { url });
  $('#bg-url').value = '';
  await loadMeta();
  toast('Background downloaded');
}));

/* ---------- jobs ---------- */
const KIND = { studio: 'AI Studio', story: 'Story video', chat: 'Text story' };
function jobTitle(j) {
  const p = j.params || {};
  if (j.kind === 'studio') {
    const on = [p.clip && 'clips', p.captions && 'captions', p.broll && 'B-roll', p.enhance && 'audio', p.voiceover && 'voice-over'].filter(Boolean);
    return `${p.reframe === 'ai' ? 'AI reframe' : p.reframe}${on.length ? ' + ' + on.join(', ') : ''}`;
  }
  return p.title || p.contact_name || KIND[j.kind];
}
function renderJobs(list) {
  const box = $('#jobs');
  if (!list.length) { box.innerHTML = '<p class="empty">Your rendered videos will show up here.</p>'; return; }
  box.innerHTML = list.map(j => `
    <div class="job" data-id="${j.id}">
      <div class="job-head"><span class="job-kind">${esc(KIND[j.kind] || j.kind)}</span>
        <span class="job-status ${j.status}">${j.status === 'running' ? Math.round(j.progress * 100) + '%' : j.status}</span></div>
      <div class="job-msg">${esc(jobTitle(j)).slice(0, 90)}</div>
      ${j.status === 'running' || j.status === 'queued' ? `<div class="bar"><i style="width:${Math.round(j.progress * 100)}%"></i></div><div class="job-msg">${esc(j.message)}</div>` : ''}
      ${j.status === 'error' ? `<div class="job-msg" style="color:var(--err)">${esc(j.error)}</div>` : ''}
      ${j.outputs.length ? `<div class="outs">${j.outputs.map((o, i) => `
        <div class="out" data-job="${j.id}" data-i="${i}">${o.thumbnail ? `<img src="${esc(o.thumbnail)}" alt="">` : ''}
        ${o.score ? `<b>${o.score}</b>` : `<b>${Math.round(o.duration)}s</b>`}</div>`).join('')}</div>` : ''}
      ${j.status === 'done' || j.status === 'error' ? `<div class="job-actions"><button data-del="${j.id}">Delete</button></div>` : ''}
    </div>`).join('');
  $$('.out', box).forEach(el => el.addEventListener('click', () => {
    const j = list.find(x => x.id === el.dataset.job);
    openPlayer(j.outputs[Number(el.dataset.i)]);
  }));
  $$('[data-del]', box).forEach(b => b.addEventListener('click', async () => {
    try { await api(`/api/jobs/${b.dataset.del}`, { method: 'DELETE' }); refreshJobs(); } catch (e) { toast(e.message, true); }
  }));
}
let pollTimer = null;
async function refreshJobs() {
  clearTimeout(pollTimer);
  let active = false;
  try {
    const list = await api('/api/jobs');
    renderJobs(list);
    active = list.some(j => j.status === 'queued' || j.status === 'running');
  } catch { /* server restarting */ }
  pollTimer = setTimeout(refreshJobs, active ? 1500 : 8000);
}

/* ---------- player ---------- */
function openPlayer(o) {
  $('#player-video').src = o.url;
  $('#player-meta').innerHTML = `<strong>${esc(o.title || 'Video')}</strong>` +
    (o.hook ? `<span class="hint">${esc(o.hook)}</span>` : '') +
    (o.start !== undefined ? `<span class="hint">From ${o.start}s to ${o.end}s${o.picker ? ` · picked by ${esc(o.picker)}` : ''}</span>` : '') +
    (o.features && o.features.length ? `<div class="chips">${o.features.map(f => `<span>${esc(f)}</span>`).join('')}</div>` : '') +
    (o.broll && o.broll.length ? `<span class="hint">B-roll: ${o.broll.map(b => `${esc(b.query)} @ ${b.start}s`).join(', ')}</span>` : '') +
    (o.script ? `<details><summary>Voice-over script</summary><p class="hint">${esc(o.script)}</p></details>` : '') +
    (o.notes || []).map(n => `<span class="hint">ℹ️ ${esc(n)}</span>`).join('') +
    `<div class="row"><a href="${esc(o.url)}" download>⬇ Download MP4</a>${o.srt ? `<a href="${esc(o.srt)}" download>⬇ Captions (.srt)</a>` : ''}</div>`;
  $('#player').hidden = false;
  $('#player-video').play().catch(() => {});
}
function closePlayer() { $('#player').hidden = true; $('#player-video').pause(); }
$('#player-close').addEventListener('click', closePlayer);
$('#player').addEventListener('click', e => { if (e.target.id === 'player') closePlayer(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closePlayer(); });

/* ---------- boot ---------- */
(async () => {
  try { const t = localStorage.getItem('tab'); if (t && $(`#tab-${t}`)) showTab(t); } catch { /* storage unavailable */ }
  try { await loadMeta(); } catch (e) { toast('Could not reach the server: ' + e.message, true); }
  refreshJobs();
})();
