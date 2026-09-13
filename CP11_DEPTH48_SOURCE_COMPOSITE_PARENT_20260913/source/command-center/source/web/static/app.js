const b64ToBuf = value => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), char => char.charCodeAt(0));
const bufToB64 = value => btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
const surface = document.body.dataset.surface || 'owner';
const isOps = surface === 'ops';
const transientReplies = new Set(['GO AI 正在思考…', '正在按负责人要求生成正式任务草稿…']);
const api = async (url, options = {}) => { const response = await fetch(url, {headers: {'Content-Type': 'application/json'}, ...options}); const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.error || 'request_failed'); return data; };

function publicKey(options) { const result = structuredClone(options); result.challenge = b64ToBuf(result.challenge); for (const item of result.allowCredentials || []) item.id = b64ToBuf(item.id); return result; }
function credentialJSON(credential) { return {id: credential.id, rawId: bufToB64(credential.rawId), type: credential.type, response: {authenticatorData: bufToB64(credential.response.authenticatorData), clientDataJSON: bufToB64(credential.response.clientDataJSON), signature: bufToB64(credential.response.signature), userHandle: credential.response.userHandle ? bufToB64(credential.response.userHandle) : null}}; }
async function authenticate() { const options = await api('/api/auth/options', {method: 'POST', body: '{}'}); const credential = await navigator.credentials.get({publicKey: publicKey(options)}); await api('/api/auth/verify', {method: 'POST', body: JSON.stringify(credentialJSON(credential))}); location.reload(); }
function node(tag, content, className = '') { const element = document.createElement(tag); element.textContent = content; if (className) element.className = className; return element; }
function action(label, handler, className = 'quiet') { const button = node('button', label, className); button.type = 'button'; button.onclick = () => handler().catch(() => alert('操作未完成，请刷新后重试。')); return button; }
function setLiveStatus(message) { const status = document.querySelector('#live-status'); if (status) status.textContent = message; }
function draftStatus(status) { if (status === 'confirmed') return '已确认并记录 · 不执行'; if (status === 'cancelled') return '已取消 · 未执行'; return '待确认 · 不执行'; }

function editorForDraft(draft) {
  const editor = document.createElement('details'); editor.className = 'task-editor'; editor.append(node('summary', isOps ? '修改结构化草稿' : '技术细节与 Agent 计划'));
  const field = document.createElement('textarea'); field.value = JSON.stringify(draft.analysis, null, 2); field.setAttribute('aria-label', '任务草稿 JSON'); editor.append(field);
  editor.append(action('保存修改', async () => { let analysis; try { analysis = JSON.parse(field.value); } catch (_) { alert('请输入有效 JSON'); return; } await api(`/api/task-drafts/${draft.id}`, {method: 'PATCH', body: JSON.stringify({analysis})}); setLiveStatus('草稿已更新 · 未执行'); await load(); }, 'confirm'));
  return editor;
}

function renderDraftCard(draft) {
  const analysis = draft.analysis; const card = document.createElement('section'); card.className = 'task-card'; const heading = document.createElement('div'); heading.className = 'task-card-heading'; heading.append(node('strong', analysis.title), node('span', isOps ? `${analysis.complexity} · ${analysis.risk}` : draftStatus(draft.status), `task-chip risk-${analysis.risk}`)); card.append(heading, node('p', analysis.objective, 'task-objective'));
  if (isOps) { const facts = document.createElement('div'); facts.className = 'task-facts'; facts.append(node('span', `类型：${analysis.task_type}`), node('span', `建议模型：${analysis.recommended_model_alias}`), node('span', `推理：${analysis.recommended_reasoning_level}`)); const agents = document.createElement('ul'); agents.className = 'agent-plan'; for (const agentPlan of analysis.agent_plan) agents.append(node('li', `${agentPlan.role}：${agentPlan.objective}`)); card.append(facts, agents, node('p', analysis.reason_summary, 'task-reason')); }
  card.append(node('p', draftStatus(draft.status), 'task-status'));
  if (draft.status === 'draft') { const editor = editorForDraft(draft); const controls = document.createElement('div'); controls.className = 'task-actions'; controls.append(action('确认', async () => { await api(`/api/task-drafts/${draft.id}/confirm`, {method: 'POST', body: '{}'}); setLiveStatus('任务已确认并记录 · 不执行'); await load(); }, 'confirm'), action('修改', async () => { editor.open = true; editor.scrollIntoView({block: 'nearest'}); }), action('取消', async () => { await api(`/api/task-drafts/${draft.id}/cancel`, {method: 'POST', body: '{}'}); setLiveStatus('任务草稿已取消 · 未执行'); await load(); })); card.append(controls, editor); }
  return card;
}

function renderOpsInspector(draft) {
  const target = document.querySelector('#ops-draft-detail'); if (!target) return; target.innerHTML = '';
  if (!draft) { target.append(node('p', '选择或创建一份任务草稿后，可在此查看目标、Agent 计划、边界与审批信息。', 'ops-empty')); return; }
  const analysis = draft.analysis; target.append(node('h2', analysis.title), node('p', `${draft.id} · ${draftStatus(draft.status)}`)); const grid = document.createElement('div'); grid.className = 'ops-detail-grid';
  for (const [label, value] of [['复杂度', analysis.complexity], ['风险', analysis.risk], ['模型建议', `${analysis.recommended_model_alias} · ${analysis.recommended_reasoning_level}`]]) { const row = document.createElement('div'); row.append(node('span', label), node('strong', value)); grid.append(row); } target.append(grid);
  const section = (title, text) => { const element = document.createElement('section'); element.className = 'ops-detail-section'; element.append(node('h3', title), node('p', text)); return element; }; target.append(section('目标', analysis.objective));
  const agents = document.createElement('section'); agents.className = 'ops-detail-section'; agents.append(node('h3', 'Agent 调度预演')); const list = document.createElement('ul'); for (const agentPlan of analysis.agent_plan) list.append(node('li', `${agentPlan.role}：${agentPlan.objective}`)); agents.append(list); target.append(agents, section('边界', analysis.scope_out.join(' · ')), section('验收', analysis.acceptance_criteria.join(' · ')));
}

function renderConversation(messages) {
  const list = document.querySelector('#messages'); list.innerHTML = ''; const drafts = [];
  for (const message of messages) { if (message.kind === 'assistant' && transientReplies.has(message.body)) continue; const article = document.createElement('article'); article.className = `message ${message.kind}`; const label = message.kind === 'assistant' ? 'GO AI' : (message.author || '成员'); const avatar = node('div', message.kind === 'assistant' ? 'GO' : label.slice(0, 1), 'avatar'); const bubble = document.createElement('div'); bubble.className = 'bubble'; bubble.append(node('div', label, 'message-meta'), node('p', message.body));
    if (message.kind === 'human' && message.task_draft) { drafts.push(message.task_draft); bubble.append(renderDraftCard(message.task_draft)); }
    if (message.kind === 'human' && !message.task_draft && message.task_id) bubble.append(action('转为任务', async () => { await api(`/api/tasks/${message.task_id}/convert-to-task`, {method: 'POST', body: '{}'}); setLiveStatus('正在生成任务草稿…'); await load(); }));
    article.append(avatar, bubble); if (message.kind === 'human') article.classList.add('human'); list.append(article);
  }
  if (!messages.length) list.append(node('p', '欢迎来到 GO AI 协作群。说点什么吧。', 'empty')); if (isOps) renderOpsInspector(drafts.at(-1)); list.scrollTop = list.scrollHeight;
}

async function load() {
  try { const me = await api('/api/me'); document.querySelector('#login').hidden = true; document.querySelector('#app').hidden = false; const userMenu = document.querySelector('#user-menu'); if (userMenu) userMenu.hidden = false; const userName = document.querySelector('#user-name'); if (userName) userName.textContent = me.name; const opsLink = document.querySelector('#ops-link'); if (opsLink) opsLink.hidden = !me.can_access_ops;
    const requests = [api('/api/conversation'), api('/api/capabilities')]; if (isOps) requests.push(api('/api/usage/summary')); const [messages, capabilities, usage] = await Promise.all(requests); const modeStatus = document.querySelector('#mode-status'); if (modeStatus) modeStatus.textContent = capabilities.execution_enabled ? '执行模式' : (isOps ? 'COMMAND_ONLY · 不执行' : '仅指挥模式'); const usageSummary = document.querySelector('#usage-summary'); if (usageSummary && usage) usageSummary.textContent = `今日 $${usage.today.estimated_cost_usd.toFixed(4)} · 本月 $${usage.month.estimated_cost_usd.toFixed(4)}`; renderConversation(messages); setLiveStatus(isOps ? '共享会话 · 实时同步' : '可讨论、可记录，不执行');
  } catch (_) { /* Signed-out state stays visible until Passkey login. */ }
}

const signIn = document.querySelector('#sign-in'); if (signIn) signIn.onclick = () => authenticate().catch(() => alert('设备验证未完成，请重试。'));
const logout = document.querySelector('#logout'); if (logout) logout.onclick = async () => { await api('/api/logout', {method: 'POST', body: '{}'}); location.href = '/'; };
const refresh = document.querySelector('#refresh'); if (refresh) refresh.onclick = load;
const pasteGPT = document.querySelector('#paste-gpt'); if (pasteGPT) pasteGPT.onclick = async () => { try { document.querySelector('#task-body').value = await navigator.clipboard.readText(); } catch (_) { alert('请允许浏览器读取剪贴板，或直接粘贴。'); } };
const sendTask = document.querySelector('#send-task'); if (sendTask) sendTask.onclick = async () => { const field = document.querySelector('#task-body'); const body = field.value.trim(); if (!body) return; const source = body.length > 600 ? 'gpt_paste' : 'manual'; await api('/api/tasks', {method: 'POST', body: JSON.stringify({body, source})}); field.value = ''; setLiveStatus('GO AI 正在分析…'); await load(); };
load();
