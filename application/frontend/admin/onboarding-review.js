/* GO supplier onboarding review console.
 *
 * One queue, one case, one decision. The three decisions are not equivalent and
 * the interface must not let them look equivalent: APPROVE creates a public hotel
 * identity; NEEDS_CHANGES must say what is missing or the applicant cannot act;
 * REJECT ends the application and deliberately leaves the legal entity alone.
 * Resolving a hotel conflict takes the hotel from somebody, so it asks twice.
 */
(function (global) {
  'use strict';
  const BASE = '/internal/v1/onboarding-review';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // CONTRACT_PENDING is absent on purpose: no version of the product has ever put a
  // case into it, so a label for it would imply a state that cannot exist. The two
  // contract states that older code *did* write keep their labels, because stored
  // rows may still carry them.
  const STATES = {
    REGISTERED: '已注册', PROFILE_DRAFT: '资料填写中', NEEDS_CHANGES: '需修改',
    UNDER_REVIEW: '待审核', CLAIM_CONFLICT: '酒店归属冲突', VERIFIED: '主体已通过',
    CONTRACT_NEEDS_CHANGES: '合同需重新确认',
    CONTRACT_UNDER_REVIEW: '合同待确认（旧流程）', CONTRACT_ACTIVE: '合同已生效',
    BUSINESS_ENABLED: '已开通经营', REJECTED: '已驳回',
  };
  const QUEUE_STATES = {
    UNDER_REVIEW: '待审核', CLAIM_CONFLICT: '酒店归属冲突',
  };
  const FINDINGS = {
    LEGAL_ENTITY_MISMATCH: '主体信息与营业执照不一致',
    LICENSE_ILLEGIBLE: '营业执照不清晰或无法核验',
    LICENSE_EXPIRED: '营业执照已过期',
    RELATIONSHIP_UNPROVEN: '与酒店的关系缺少证明',
    PROOF_ILLEGIBLE: '关系证明不清晰或无法核验',
    HOTEL_INFO_MISMATCH: '酒店信息与所选酒店不一致',
    DOCUMENT_REQUIRED: '还需补充其他材料',
    OTHER: '其他（见备注）',
  };
  const RELATIONSHIPS = {
    OWNER: '业主（自有物业）', OPERATOR: '经营方',
    MANAGEMENT_COMPANY: '管理公司', AUTHORIZED_AGENT: '授权代理',
  };
  const DOC_TYPES = {
    BUSINESS_LICENSE: '营业执照', HOTEL_OPERATION_PROOF: '酒店经营证明',
    FRANCHISE_OR_MANAGEMENT_CONTRACT: '加盟或管理合同', SIGNED_CONTRACT: '已签署合同',
  };
  const ENTITY_STATES = { UNVERIFIED: '未核验', PENDING: '待核验', VERIFIED: '已核验', REJECTED: '未通过' };
  const CONFLICT_TEXT = {
    HOTEL_HELD_BY_ANOTHER_SUPPLIER: '该酒店已由其他主体持有',
    CANONICAL_HOTEL_ALREADY_EXISTS: '这家酒店已在库中',
  };

  const stateText = x => STATES[x] || String(x || '未知');
  const relationshipText = x => RELATIONSHIPS[x] || String(x || '未选择');
  const conflictText = x => CONFLICT_TEXT[x] || '存在归属争议，需要人工判定';
  const when = value => value ? String(value).replace('T', ' ').slice(0, 16) : '—';

  function queueRow(item) {
    return `<article class="business-fact">
      <span>${esc(item.organization_name || item.legal_name || item.supplier_id)} ·
        ${esc(item.hotel_name || '未选择酒店')} · ${esc(stateText(item.state))}</span>
      <span>等待自 ${esc(when(item.waiting_since))}${item.conflict_reason ? ' · ' + esc(conflictText(item.conflict_reason)) : ''}</span>
      <button class="btn" data-open="${esc(item.supplier_id)}">查看并审核</button>
    </article>`;
  }

  function documentRow(doc, index) {
    return `<article class="business-fact">
      <span>${esc(DOC_TYPES[doc.document_type] || doc.document_type)} · 第 ${esc(doc.revision)} 版 ·
        ${esc(doc.original_filename)}</span>
      <button class="btn" data-doc="${index}">查看文件</button>
      <div data-doc-view="${index}"></div>
    </article>`;
  }

  function caseHtml(d) {
    const entity = d.legal_entity || {};
    const claim = d.hotel_claim || {};
    const display = claim.hotel_display || {};
    const proposed = claim.proposed_hotel || {};
    const lastReview = d.review || null;
    const findings = d.review_findings || [];
    return `
    <section class="card">
      <h2>${esc(entity.legal_name || d.supplier_id)}</h2>
      <p>当前状态：<span class="status">${esc(stateText(d.state))}</span>
         · 提交于 ${esc(when(d.submitted_at))} · 最近更新 ${esc(when(d.updated_at))}</p>
      ${lastReview ? `<div class="notice">上次决定：${esc(stateText(
        lastReview.decision === 'APPROVE' ? 'VERIFIED' : lastReview.decision === 'REJECT' ? 'REJECTED' : 'NEEDS_CHANGES'))}
        · ${esc(lastReview.decided_by || '')} · ${esc(when(lastReview.decided_at))}
        ${lastReview.note ? '<br>备注：' + esc(lastReview.note) : ''}</div>` : ''}
      ${d.reopen ? `<div class="notice">曾于 ${esc(when(d.reopen.at))} 由 ${esc(d.reopen.by)} 重新开启（原状态 ${esc(stateText(d.reopen.from_state))}）：${esc(d.reopen.reason)}</div>` : ''}
    </section>

    <section class="card">
      <h3>法人主体</h3>
      ${entity.legal_name ? `<div class="business-facts-grid">
        <p>企业名称：${esc(entity.legal_name)}</p>
        <p>统一社会信用代码：<span class="mono">${esc(entity.unified_social_credit_code)}</span></p>
        <p>法定代表人：${esc(entity.legal_representative_name || '—')}</p>
        <p>核验状态：${esc(ENTITY_STATES[entity.verification_state] || entity.verification_state || '—')}</p>
        <p>注册地址：${esc(entity.registered_address || '—')}</p>
      </div>` : '<p>尚未填写法人主体信息。</p>'}
    </section>

    <section class="card">
      <h3>证明材料（${(d.documents || []).length} 份）</h3>
      <p>仅在需要时加载原文件；未打开的文件不会被下载。</p>
      ${(d.documents || []).map(documentRow).join('') || '<p>尚未上传任何材料。</p>'}
    </section>

    <section class="card">
      <h3>酒店与关系</h3>
      <div class="business-facts-grid">
        <p>认领方式：${claim.mode === 'PROPOSED' ? '申请新建酒店' : claim.mode === 'EXISTING' ? '认领已在库酒店' : '未提交'}</p>
        <p>酒店：${esc(display.name || proposed.name || '—')}</p>
        <p>城市：${esc(display.city || proposed.city || '—')}</p>
        <p>与酒店关系：${esc(relationshipText(claim.relationship_type))}</p>
        <p>关系证明：${claim.proof_document_type ? esc(DOC_TYPES[claim.proof_document_type] || claim.proof_document_type) : (claim.relationship_type === 'OWNER' ? '业主无需额外证明' : '尚未提供')}</p>
        <p>酒店归属：${d.hotel_id ? '<span class="mono">' + esc(d.hotel_id) + '</span>' : '尚未确立'}</p>
      </div>
      ${claim.conflict ? `<div class="notice error">${esc(conflictText(claim.conflict.reason))}
        （记录于 ${esc(when(claim.conflict.recorded_at))}）。判定前不会把酒店判给任何一方。</div>` : ''}
      ${claim.revoked ? `<div class="notice">该主体的原酒店归属已于 ${esc(when(claim.revoked.at))} 被撤销：${esc(claim.revoked.reason)}</div>` : ''}
    </section>

    ${findings.length ? `<section class="card"><h3>待申请人补充</h3>
      ${findings.map(f => `<p>· ${esc(FINDINGS[f.code] || f.code)}${f.message ? '：' + esc(f.message) : ''}</p>`).join('')}
    </section>` : ''}`;
  }

  function decisionHtml(d) {
    const a = d.actions || {};
    return `<section class="card">
      <h3>作出决定</h3>
      <p>通过即创建该酒店的平台身份并写入唯一归属；退回必须指明缺什么；驳回只结束本次申请，不会改动法人主体。</p>
      <div class="field"><label for="rvNote">审核备注（申请人可见）</label>
        <input id="rvNote" maxlength="2000" placeholder="一句话说明理由"></div>
      <fieldset class="field">
        <legend>退回时勾选缺什么（至少一项）</legend>
        ${(d.finding_codes || []).map(code =>
          `<label><input type="checkbox" data-finding="${esc(code)}"> ${esc(FINDINGS[code] || code)}</label>`).join('')}
      </fieldset>
      <div class="structured-actions">
        <button class="btn primary" data-decide="APPROVE" ${a.can_approve ? '' : 'disabled'}>通过并建立酒店归属</button>
        <button class="btn" data-decide="NEEDS_CHANGES" ${a.can_decide ? '' : 'disabled'}>退回修改</button>
        <button class="btn danger" data-decide="REJECT" ${a.can_reject ? '' : 'disabled'}>驳回入驻</button>
      </div>
      <div data-confirm></div>
    </section>

    ${a.can_resolve_conflict ? `<section class="card">
      <h3>处理酒店归属冲突</h3>
      <p>这家酒店同时被两个主体认领。请判定归谁；无论哪种判定都会写入审计，且不问两次不会执行。</p>
      <div class="structured-actions">
        <button class="btn" data-resolve="REJECT_LATE_CLAIMANT">驳回后到方，原归属不变</button>
        <button class="btn danger" data-resolve="REVOKE_INCUMBENT">撤销原归属，改判给本申请人</button>
      </div>
      <div data-confirm-resolve></div>
    </section>` : ''}

    ${a.can_reopen ? `<section class="card">
      <h3>重新开启</h3>
      <p>把这个已结束的申请退回草稿，让申请人可以再次提交。理由会留在审计里。</p>
      <div class="field"><label for="reopenReason">重新开启理由</label>
        <input id="reopenReason" maxlength="500" placeholder="例如：申请人补充了新的经营权证明"></div>
      <button class="btn" data-reopen>重新开启</button>
      <div data-confirm-reopen></div>
    </section>` : ''}`;
  }

  function confirmPanel(id, title, body, commitLabel, danger) {
    return `<div class="notice" data-panel="${id}"><strong>${esc(title)}</strong><br>${esc(body)}
      <div class="field"><label for="cf-${id}">理由（写入审计）</label>
        <input id="cf-${id}" value="人工复核" maxlength="500"></div>
      <div class="structured-actions">
        <button class="btn ${danger ? 'danger' : 'primary'}" data-commit="${id}">${esc(commitLabel)}</button>
        <button class="btn" data-cancel="${id}">取消</button>
      </div></div>`;
  }

  function mount(ctx) {
    const { root, api, notice } = ctx;
    root.innerHTML = `
      <section class="card">
        <h2>合作伙伴入驻审核</h2>
        <p>先核对法人主体、营业执照和酒店关系，再作出决定。等待最久的申请排在最前。</p>
        <div class="structured-actions">
          <label>状态 <select data-filter>
            <option value="">全部待处理</option>
            <option value="UNDER_REVIEW">仅待审核</option>
            <option value="CLAIM_CONFLICT">仅归属冲突</option>
          </select></label>
          <button class="btn" data-load>刷新队列</button>
          <button class="btn" data-back>返回供应商管理</button>
        </div>
        <p data-status role="status" aria-live="polite"></p>
      </section>
      <section class="card">
        <h3>待处理申请</h3>
        <div data-list>加载中…</div>
        <div class="structured-actions">
          <button class="btn" data-prev>上一页</button>
          <button class="btn" data-next>下一页</button>
        </div>
      </section>
      <div data-detail></div>`;

    const listBox = root.querySelector('[data-list]');
    const detailBox = root.querySelector('[data-detail]');
    const statusBox = root.querySelector('[data-status]');
    const sessionAtMount = api.csrf ? api.csrf() : null;
    let epoch = 0;
    let offset = 0;
    let total = 0;
    let current = null;
    let pending = null;
    let viewUrls = [];

    const active = () => {
      if (!root.contains(listBox) || !listBox.isConnected) return false;
      if (api.csrf && api.csrf() !== sessionAtMount) {
        listBox.innerHTML = '';
        detailBox.innerHTML = '';
        statusBox.textContent = '登录会话已变化，请重新打开审核页面。';
        return false;
      }
      return true;
    };
    const release = () => { viewUrls.forEach(URL.revokeObjectURL); viewUrls = []; };
    const say = (text, bad) => { statusBox.textContent = text; if (bad) notice?.(text, true); };
    const fail = error => {
      const code = String(error?.message || error);
      if (code === 'REVIEW_CASE_NOT_REVIEWABLE') return '这条申请已经被处理过，请刷新后再看。';
      if (code === 'REVIEW_FINDINGS_REQUIRED') return '退回修改时必须勾选至少一项需要补充的内容。';
      if (code.startsWith('REVIEW_FINDING_CODE_INVALID')) return '所选的问题类型无效，请重新勾选。';
      if (code === 'CLAIM_CONFLICT_MUST_BE_RESOLVED_FIRST') return '这家酒店还在归属冲突中，请先处理冲突。';
      if (code === 'CLAIM_CONFLICT_CONFIRMATION_REQUIRED') return '这个操作会把酒店从原归属方转走，需要明确确认。';
      if (code === 'CLAIM_CONFLICT_REASON_REQUIRED' || code === 'REVIEW_REOPEN_REASON_REQUIRED') return '请填写理由。';
      if (code === 'CLAIM_CONFLICT_INCUMBENT_NOT_FOUND') return '找不到当前持有方，可能已被其他操作改变，请刷新。';
      return '操作未完成，请刷新核对当前状态。';
    };
    const note = () => detailBox.querySelector('#rvNote')?.value || null;
    const checkedFindings = () =>
      Array.from(detailBox.querySelectorAll('[data-finding]:checked')).map(b => b.dataset.finding);

    async function load() {
      const ticket = ++epoch;
      const filter = root.querySelector('[data-filter]').value;
      const query = new URLSearchParams({ limit: '25', offset: String(offset) });
      if (filter) query.set('states', filter);
      listBox.textContent = '加载中…';
      try {
        const payload = (await api.request(`${BASE}/cases?${query}`)).data;
        if (ticket !== epoch || !active()) return;
        total = payload.total || 0;
        listBox.innerHTML = (payload.items || []).map(queueRow).join('') ||
          '<p>当前没有等待人工处理的申请。</p>';
        say(`共 ${total} 条，当前第 ${Math.floor(offset / 25) + 1} 页`);
        root.querySelector('[data-prev]').disabled = offset === 0;
        root.querySelector('[data-next]').disabled = offset + 25 >= total;
      } catch (error) {
        if (ticket === epoch && active()) { listBox.textContent = fail(error); }
      }
    }

    async function open(supplierId) {
      const ticket = ++epoch;
      release();
      pending = null;
      current = null;
      detailBox.textContent = '加载中…';
      try {
        const data = (await api.request(`${BASE}/cases/${encodeURIComponent(supplierId)}`)).data;
        if (ticket !== epoch || !active()) return;
        current = data;
        detailBox.innerHTML = caseHtml(data) + decisionHtml(data);
      } catch (error) {
        if (ticket === epoch && active()) detailBox.textContent = fail(error);
      }
    }

    async function submitDecision(decision, extra = {}) {
      if (!current) return;
      const ticket = epoch;
      const supplierId = current.supplier_id;
      try {
        await api.request(`${BASE}/cases/${encodeURIComponent(supplierId)}/decision`, {
          method: 'POST',
          body: { decision, note: note(), ...extra },
        });
        if (ticket !== epoch || !active()) return;
        say('决定已提交，正在重新读取该申请的最新状态。');
        notice?.('决定已提交并写入审计。');
        pending = null;
        await open(supplierId);
        await load();
      } catch (error) {
        if (ticket === epoch && active()) say(fail(error), true);
      }
    }

    root.onclick = async event => {
      const button = event.target.closest('button');
      if (!button || !root.contains(button) || button.disabled) return;
      if (!active()) return;
      const { dataset } = button;

      if (dataset.back !== undefined) { release(); root.onclick = null; return ctx.back?.(); }
      if (dataset.load !== undefined) { offset = 0; return load(); }
      if (dataset.prev !== undefined) { offset = Math.max(0, offset - 25); return load(); }
      if (dataset.next !== undefined) { offset += 25; return load(); }
      if (dataset.open !== undefined) return open(dataset.open);

      if (dataset.doc !== undefined) {
        const doc = current.documents[Number(dataset.doc)];
        const target = detailBox.querySelector(`[data-doc-view="${dataset.doc}"]`);
        button.disabled = true;
        try {
          const blob = await api.requestBlob(
            `${BASE}/documents/${encodeURIComponent(doc.document_id)}/content`);
          if (!active() || !target?.isConnected) return;
          const url = URL.createObjectURL(blob);
          viewUrls.push(url);
          target.innerHTML = blob.type === 'application/pdf'
            ? `<a class="btn" href="${esc(url)}" target="_blank" rel="noopener">在新标签打开 PDF</a>`
            : `<img src="${esc(url)}" alt="申请人上传的材料" style="max-width:100%;height:auto" loading="lazy">`;
          button.textContent = '已加载';
        } catch (error) {
          button.disabled = false;
          say(fail(error), true);
        }
        return;
      }

      if (dataset.decide !== undefined) {
        const action = dataset.decide;
        const box = detailBox.querySelector('[data-confirm]');
        if (action === 'NEEDS_CHANGES') {
          const findings = checkedFindings();
          // Say what is missing before sending it, so the reviewer does not have to
          // learn that rule from a refusal.
          if (!findings.length) return say('退回修改前请先勾选需要申请人补充的内容。', true);
          return submitDecision('NEEDS_CHANGES', { findings });
        }
        pending = { kind: 'decision', action };
        box.innerHTML = action === 'APPROVE'
          ? confirmPanel('approve', '确认通过？',
              '通过会立即创建该酒店的平台身份，并写入唯一归属，之后无法自动撤销。',
              '确认通过', false)
          : confirmPanel('reject', '确认驳回？',
              '驳回会结束本次入驻申请。法人主体信息不会被改动，之后仍可由治理角色重新开启。',
              '确认驳回', true);
        return;
      }

      if (dataset.resolve !== undefined) {
        pending = { kind: 'resolve', action: dataset.resolve };
        detailBox.querySelector('[data-confirm-resolve]').innerHTML = dataset.resolve === 'REVOKE_INCUMBENT'
          ? confirmPanel('revoke', '确认撤销原归属？',
              '这家酒店将从当前持有方转给本申请人。原持有方会收到待修改状态，操作会写入审计。',
              '确认改判', true)
          : confirmPanel('late', '确认驳回后到方？',
              '后到方会回到「需修改」并重新选择酒店，原持有方不受影响。',
              '确认驳回后到方', false);
        return;
      }

      if (dataset.reopen !== undefined) {
        const reason = detailBox.querySelector('#reopenReason')?.value?.trim();
        if (!reason) return say('请填写重新开启的理由。', true);
        try {
          await api.request(`${BASE}/cases/${encodeURIComponent(current.supplier_id)}/reopen`, {
            method: 'POST', body: { reason },
          });
          if (!active()) return;
          say('已重新开启，申请人可以再次提交。');
          notice?.('已重新开启该申请。');
          await open(current.supplier_id);
          await load();
        } catch (error) { if (active()) say(fail(error), true); }
        return;
      }

      if (dataset.cancel !== undefined) {
        pending = null;
        detailBox.querySelectorAll('[data-panel]').forEach(panel => { panel.innerHTML = ''; });
        return;
      }

      if (dataset.commit !== undefined && pending) {
        const reason = detailBox.querySelector(`#cf-${dataset.commit}`)?.value?.trim();
        if (!reason) return say('请填写理由。', true);
        if (pending.kind === 'decision') return submitDecision(pending.action, { note: reason });
        try {
          await api.request(`${BASE}/cases/${encodeURIComponent(current.supplier_id)}/resolve-conflict`, {
            method: 'POST',
            body: { resolution: pending.action, reason, confirmed: true },
          });
          if (!active()) return;
          pending = null;
          say('冲突已处理，正在重新读取。');
          notice?.('冲突判定已写入审计。');
          await open(current.supplier_id);
          await load();
        } catch (error) { if (active()) say(fail(error), true); }
      }
    };

    void load();
    return { dispose() { epoch += 1; release(); current = null; root.onclick = null; } };
  }

  global.GO_ONBOARDING_REVIEW = { mount, caseHtml, decisionHtml, stateText, conflictText };
})(typeof window === 'undefined' ? globalThis : window);
