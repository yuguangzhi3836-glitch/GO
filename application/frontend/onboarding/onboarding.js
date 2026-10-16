/* GO 合作伙伴平台 · 入驻工作区
 *
 * Scope of this module
 * --------------------
 * Batch 1: account creation / login / onboarding overview + workspace shell.
 * Later batches plug their step screens into `SCREENS` and add their API calls
 * to `api` (see /partner/README-ONBOARDING.md).
 *
 * Hard product rules enforced here:
 *  - the human never sees or types an internal id (supplier_id / hotel_id /
 *    case id / document id); every screen works off server-side session state;
 *  - every internal error code is translated through ERROR_TEXT before display;
 *  - a failed submit never clears what the human typed.
 */
import { ApiClient, unwrap, esc } from '/console-assets/api.js';

const api = new ApiClient();
api.expectedActor = 'SUPPLIER_USER';

/* ------------------------------------------------------------------ *
 * Human-readable error text. Every internal code that can reach a real
 * applicant MUST appear here; unmapped codes fall back to a neutral
 * message instead of leaking the raw token.
 * ------------------------------------------------------------------ */
export const ERROR_TEXT = {
  // Account creation (three-in-one login: username / email / phone)
  USERNAME_ALREADY_REGISTERED: '这个用户名已经被占用，请换一个；如果这就是你的账号，请直接登录。',
  EMAIL_ALREADY_REGISTERED: '这个邮箱已经注册过账号，请直接登录；忘记密码可以点「找回密码 / 找回账号」。',
  PHONE_ALREADY_REGISTERED: '这个手机号已经注册过账号，请直接登录；忘记密码可以点「找回密码 / 找回账号」。',
  VALID_USERNAME_REQUIRED: '用户名需为 3–32 位，以字母或数字开头，可用字母、数字、下划线、点和短横线，并且至少包含一个字母（不能是纯数字）。',
  VALID_EMAIL_REQUIRED: '请输入有效的邮箱地址。',
  VALID_PHONE_REQUIRED: '请输入 11 位中国大陆手机号。',
  PASSWORD_LENGTH_INVALID: '密码长度需为 10–128 位。',
  PASSWORD_CONFIRMATION_MISMATCH: '两次输入的密码不一致。',
  NONBLANK_IDENTITY_REQUIRED: '联系人姓名不能为空。',
  // Verification codes (email + SMS). The sign-up refusal carries the channel as
  // a prefix so the form can mark the one code box that is actually wrong.
  EMAIL_REGISTRATION_CODE_INVALID_OR_EXPIRED: '邮箱验证码不正确或已过期，请重新获取。',
  SMS_REGISTRATION_CODE_INVALID_OR_EXPIRED: '短信验证码不正确或已过期，请重新获取。',
  EMAIL_REGISTRATION_CODE_RATE_LIMITED: '邮箱验证码发送太频繁，请 60 秒后再试。',
  SMS_REGISTRATION_CODE_RATE_LIMITED: '短信验证码发送太频繁，请 60 秒后再试。',
  REGISTRATION_CODE_INVALID_OR_EXPIRED: '验证码不正确或已过期，请重新获取。',
  REGISTRATION_CODE_RATE_LIMITED: '验证码发送太频繁，请 60 秒后再试。',
  REGISTRATION_CODE_REPLACED: '这条验证码已经被新的替换，请重新获取。',
  REGISTRATION_VERIFICATION_NOT_READY: '当前环境还没有接通验证码通道，这一步暂时做不到。请联系 GO。',
  REGISTRATION_SMS_NOT_READY: '短信通道还没有接通，请改用邮箱接收验证码。',
  REGISTRATION_EMAIL_SEND_FAILED: '验证码发送失败，请稍后重试，或改用另一种方式接收。',
  REGISTRATION_CHANNEL_INVALID: '操作没有完成，请刷新页面后重试。',
  // Account recovery
  RECOVERY_ACCOUNT_NOT_FOUND: '没有找到这个账号。请确认邮箱或手机号是否正确，或换一种方式再试。',
  REGISTRATION_TERMS_VERSION_MISMATCH: '服务条款已更新，请刷新页面后重新阅读确认。',
  REGISTRATION_TERMS_CONTENT_MISMATCH: '服务条款内容已变化，请刷新页面后重新确认。',
  SUPPLIER_TERMS_ACCEPTANCE_REQUIRED: '请先逐项确认服务条款与平台规则。',
  SUPPLIER_TERMS_VERSION_MISMATCH: '服务条款已更新，请重新阅读并确认。',
  SUPPLIER_TERMS_CONTENT_MISMATCH: '服务条款内容已变化，请重新阅读并确认。',
  REGISTRATION_TERMS_NOT_READY: '服务条款暂不可用，请稍后重试或联系 GO。',
  REGISTRATION_TERMS_UNAVAILABLE: '服务条款暂不可用，请稍后重试或联系 GO。',
  INVALID_CREDENTIALS: '账号或密码不正确。账号可以填用户名、邮箱或手机号。',
  ACCOUNT_TYPE_MISMATCH: '该账号不属于合作伙伴平台，请使用合作伙伴账号登录。',
  SESSION_REVOKED: '登录已过期，请重新登录。你填写的内容已保留。',
  REPLAY_DETECTED: '登录已过期，请重新登录。你填写的内容已保留。',
  ACTOR_CONTEXT_CHANGED: '账号已在其他页面切换，请重新登录。',
  REQUEST_RATE_LIMITED: '操作过于频繁，请稍后再试。',
  SUPPLIER_ONBOARDING_NOT_FOUND: '没有找到你的入驻申请，请重新登录或联系 GO。',
  INVALID_UNIFIED_SOCIAL_CREDIT_CODE_LENGTH: '统一社会信用代码应为 18 位，请核对营业执照上的号码。',
  INVALID_UNIFIED_SOCIAL_CREDIT_CODE_CHARSET: '统一社会信用代码含有无效字符，请核对营业执照上的号码。',
  INVALID_UNIFIED_SOCIAL_CREDIT_CODE_CHECKSUM: '统一社会信用代码校验不通过，请核对营业执照上的号码。',
  UNIFIED_SOCIAL_CREDIT_CODE_ALREADY_REGISTERED: '该统一社会信用代码已在本平台登记。如确属同一企业，请用原账号登录或联系 GO 客服。',
  SUPPLIER_PROFILE_INCOMPLETE: '还有必填项没有完成，请在页面上查看具体缺哪一项。',
  SUPPLIER_PROFILE_NOT_SUBMITTABLE: '当前状态不能提交，请刷新页面查看最新进度。',
  SUPPLIER_PROFILE_NOT_EDITABLE: '资料已提交审核，暂时不能修改。若需修改请等待审核结果。',
  LEGAL_ENTITY_ALREADY_EXISTS: '你的账号已经建立了企业主体，无需重复创建。',
  LEGAL_NAME_REQUIRED: '请填写企业法定名称（与营业执照一致）。',
  LEGAL_NAME_TOO_LONG: '企业法定名称过长，请与营业执照保持一致并精简到 200 字以内。',
  UNIFIED_SOCIAL_CREDIT_CODE_REQUIRED: '请填写统一社会信用代码（营业执照右上角 18 位号码）。',
  LEGAL_REPRESENTATIVE_NAME_REQUIRED: '请填写法定代表人姓名。',
  REGISTERED_ADDRESS_REQUIRED: '请填写企业注册地址（与营业执照一致）。',
  LICENSE_VALIDITY_INVALID: '营业执照有效期填写不正确，请核对起始日期与到期日期。',
  LEGAL_ENTITY_NOT_FOUND: '还没有填写企业主体信息，请先完成上一步。',
  LEGAL_ENTITY_REQUIRED: '请先完成上一步「企业主体」，再上传营业执照。',
  DOCUMENT_TYPE_UNSUPPORTED: '文件格式不支持，请上传 JPG、PNG 或 PDF 文件。',
  DOCUMENT_TYPE_MISMATCH: '文件内容与格式不一致，请确认上传的是真实的营业执照图片或 PDF。',
  DOCUMENT_TOO_LARGE: '文件超过 10MB，请压缩后重新上传。',
  DOCUMENT_BYTES_REQUIRED: '没有读到文件内容，请重新选择文件。',
  DOCUMENT_IMAGE_UNREADABLE: '图片无法读取或已损坏，请重新导出后再上传。',
  DOCUMENT_IMAGE_TOO_LARGE: '图片分辨率过高，请压缩后重新上传。',
  DOCUMENT_REVISION_STALE: '这份资料已被更新，请刷新页面后重新上传。',
  DOCUMENT_REVISION_CONFLICT: '同一时间有其他更新正在写入，请稍后重试。',
  DOCUMENT_INTEGRITY_FAILED: '文件校验不通过，请联系 GO 客服。',
  DOCUMENT_NOT_FOUND: '没有找到这份资料，可能已被更新，请刷新页面。',
  ONBOARDING_CASE_NOT_FOUND: '没有找到你的入驻申请，请重新登录或联系 GO。',
  DOCUMENT_STATUS_INVALID: '当前状态不能执行该操作，请刷新页面。',
  DOCUMENT_SCOPE_INVALID: '操作没有完成，请刷新页面后重试。',
  // Hotel claim (Batch 4)
  HOTEL_SEARCH_QUERY_REQUIRED: '请输入至少两个字，或填写所在城市再搜索。',
  HOTEL_NOT_FOUND: '没有找到这家酒店，可能已从平台目录移除。请刷新页面重新搜索。',
  HOTEL_CLAIM_MODE_INVALID: '操作没有完成，请刷新页面后重试。',
  HOTEL_CLAIM_HOTEL_REQUIRED: '请先搜索并选择你要认领的酒店。',
  HOTEL_CLAIM_NOT_EDITABLE: '资料已提交，暂时不能修改酒店关系。请等待审核结果。',
  HOTEL_CLAIM_NOT_REVIEWABLE: '当前状态不能审核酒店关系，请刷新页面查看最新进度。',
  HOTEL_CLAIM_REQUIRED: '这家申请还没有填写酒店关系，无法通过。',
  HOTEL_RELATIONSHIP_TYPE_REQUIRED: '请选择你与这家酒店的关系。',
  HOTEL_RELATIONSHIP_TYPE_INVALID: '请选择你与这家酒店的关系。',
  HOTEL_RELATIONSHIP_PROOF_REQUIRED: '这个关系需要上传经营证明或加盟／委托管理合同，请在下面先上传。',
  PROPOSED_HOTEL_NAME_REQUIRED: '请填写酒店名称。',
  PROPOSED_HOTEL_CITY_REQUIRED: '请填写酒店所在城市。',
  PROPOSED_HOTEL_ALREADY_EXISTS: '平台已经有同名同城的酒店，请在上面的搜索结果中选择它。',
  CLAIM_CONFLICT: '这家酒店已经有其他申请在办理。GO 会人工核对后与你联系，你暂时不需要再提交。',
  SUPPLIER_ONBOARDING_ALREADY_VERIFIED: '审核已经通过，无需重复操作。',
  // Contract / activation (Batch 6)
  CONTRACT_NOT_CONFIRMABLE: '现在还不能确认合同。请先完成审核通过这一步；如果合同已经确认，直接进入经营后台即可。',
  CONTRACT_AGREEMENT_REQUIRED: '请先勾选「我已阅读并同意本合同」，再提交确认。',
  CONTRACT_TEMPLATE_CHANGED: '合同内容已经更新到新版本，请重新打开合同阅读后再确认。',
  CONTRACT_TEMPLATE_UNAVAILABLE: '合同文件暂时无法读取，请联系 GO 客服。这不是你的操作问题。',
  CONTRACT_SIGNED_DOCUMENT_REQUIRED: '请先上传已盖章的合同扫描件，再确认合同。',
  CONTRACT_SIGNED_DOCUMENT_INVALID: '你确认的扫描件已经被新的版本替换，请刷新页面后重新确认。',
  CONTRACT_HOTEL_REQUIRED: '这份申请还没有确定酒店，无法确认合同。请先完成酒店关系。',
};

/* Which document a relationship type requires (frozen decision D-03). */
export const PROOF_FOR_RELATIONSHIP = {
  OWNER: null,
  OPERATOR: 'HOTEL_OPERATION_PROOF',
  MANAGEMENT_COMPANY: 'FRANCHISE_OR_MANAGEMENT_CONTRACT',
  AUTHORIZED_AGENT: 'FRANCHISE_OR_MANAGEMENT_CONTRACT',
};

export const RELATIONSHIP_LABEL = {
  OWNER: '我是业主',
  OPERATOR: '我是经营方（承租 / 承包经营）',
  MANAGEMENT_COMPANY: '我是管理公司（受托管理）',
  AUTHORIZED_AGENT: '我是授权代理方',
};

const PROOF_LABEL = {
  HOTEL_OPERATION_PROOF: '经营证明（租赁合同 / 承包经营合同）',
  FRANCHISE_OR_MANAGEMENT_CONTRACT: '加盟合同或委托管理合同',
};

/* "还差什么" is published by the server as stable codes; the server never sends
   prose. Translate each one so the applicant reads a sentence, not a token. */
const MISSING_TEXT = {
  LEGAL_ENTITY: '填写企业主体',
  BUSINESS_LICENSE: '上传营业执照',
  HOTEL_RELATIONSHIP: '选择你要认领的酒店',
  HOTEL_RELATIONSHIP_PROOF: '上传经营证明或加盟／委托管理合同',
};

export function humanError(err) {
  const raw = (err && (err.message || err.detail || err.code)) || '';
  if (ERROR_TEXT[raw]) return ERROR_TEXT[raw];
  if (raw.startsWith('SUPPLIER_PROFILE_INCOMPLETE')) {
    // The server lists exactly what is missing, so say exactly that instead of
    // "还有必填项没有完成" and leaving the human to hunt.
    const codes = raw.split(':')[1] ? raw.split(':')[1].split(',') : [];
    const items = codes.map((c) => MISSING_TEXT[c]).filter(Boolean);
    if (items.length) return '还差这些步骤：' + items.join('、') + '。';
    return ERROR_TEXT.SUPPLIER_PROFILE_INCOMPLETE;
  }
  if (/^HTTP_5\d\d$/.test(raw)) return '服务暂时不可用，请稍后重试。';
  if (/^HTTP_4\d\d$/.test(raw)) return '操作没有完成，请检查填写内容后重试。';
  return raw || '操作没有完成，请稍后重试。';
}

/* ------------------------------------------------------------------ *
 * Session / onboarding state
 * ------------------------------------------------------------------ */
const state = { me: null, onboarding: null, legalEntity: null, documents: [], hotelClaim: null, contract: null, business: false };

async function load() {
  state.me = unwrap(await api.me());
  state.onboarding = state.me?.onboarding || null;
  state.documents = [];
  state.hotelClaim = null;
  state.contract = null;
  if (state.me?.actor_type === 'SUPPLIER_USER') {
    // The legal entity is long-lived business truth in its own table, not a key
    // inside the onboarding case payload. A missing row is normal (step 1).
    try {
      state.legalEntity = unwrap(await api.supplierLegalEntity());
    } catch {
      state.legalEntity = null;
    }
    try {
      // Documents are knowledge about the applicant, not a flag inside the case.
      // The server returns both scopes, each row labelled with its own scope.
      state.documents = unwrap(await api.supplierDocuments()) || [];
    } catch {
      state.documents = [];
    }
    try {
      state.hotelClaim = unwrap(await api.supplierHotelClaim());
    } catch {
      state.hotelClaim = null;
    }
    try {
      // The contract step answers with its own blockers instead of failing, so a
      // normal early state does not look like a broken page.
      state.contract = unwrap(await api.supplierContract());
    } catch {
      state.contract = null;
    }
  }
  return state;
}

/* The saved hotel claim, as the backend actually has it. */
function savedClaim() {
  return (state.hotelClaim && state.hotelClaim.claim) || null;
}

/* The current licence revision, as the backend actually has it. */
function currentDocument(documentType = 'BUSINESS_LICENSE') {
  return state.documents.find((d) => d.document_type === documentType && d.status !== 'SUPERSEDED') || null;
}

/* ------------------------------------------------------------------ *
 * Step model — shared by the shell and every step screen
 *
 * "账号" is deliberately NOT a navigation item. By the time this workspace is
 * reachable an account already exists, so a step the person can never be "on"
 * would only add noise to the progress list. The navigation therefore lists the
 * work a real applicant still has to do, plus the contract phase once the case
 * reaches it.
 * ------------------------------------------------------------------ */
export const STEPS = [
  { key: 'overview', label: '入驻概览' },
  { key: 'entity', label: '企业主体' },
  { key: 'license', label: '营业执照' },
  { key: 'hotel', label: '酒店关系' },
  { key: 'submit', label: '提交审核' },
];

const CONTRACT_STEP = { key: 'contract', label: '合作合同' };

/* The contract only exists as a destination after a human has approved the
   application; before that the sidebar must not advertise a step the applicant
   cannot open. */
const CONTRACT_PHASE_STATES = [
  'VERIFIED', 'CONTRACT_NEEDS_CHANGES', 'CONTRACT_UNDER_REVIEW',
  'CONTRACT_ACTIVE', 'BUSINESS_ENABLED',
];
const ACTIVATED_STATES = ['CONTRACT_ACTIVE', 'BUSINESS_ENABLED'];

/* What the step bar shows as done. `submit` used to be missing from this map
   entirely, so the bar never marked the last step complete even after the
   application had been submitted — the applicant was told to do something they had
   already done. It is now derived from the case state, like the other steps. */
const SUBMITTED_STATES = [
  'UNDER_REVIEW', 'VERIFIED', 'CLAIM_CONFLICT', 'CONTRACT_NEEDS_CHANGES',
  'CONTRACT_UNDER_REVIEW', 'CONTRACT_ACTIVE', 'BUSINESS_ENABLED',
];

function stepProgress() {
  const claim = savedClaim() || {};
  const entity = state.legalEntity || {};
  const entityDone = Boolean(entity.legal_name && entity.unified_social_credit_code);
  const licenseDone = Boolean(currentDocument('BUSINESS_LICENSE'));
  const hotelDone = Boolean(
    claim.relationship_type && (claim.hotel_id || claim.proposed_hotel)
  );
  const submitted = SUBMITTED_STATES.includes((state.onboarding || {}).state);
  return { account: true, entity: entityDone, license: licenseDone, hotel: hotelDone, submit: submitted };
}

/* The proof a relationship type requires, and whether the applicant has uploaded
   it. Kept next to the step model so the step bar and the screen agree.

   The field is `proofDocument`, not `document`: a caller that destructures
   `{ document }` puts the *global* `document` into the temporal dead zone for the
   whole function body, so every earlier `document.getElementById(...)` in that
   function throws "Cannot access 'document' before initialization". */
function proofState(relationshipType) {
  const required = PROOF_FOR_RELATIONSHIP[relationshipType] || null;
  if (!required) return { required: null, proofDocument: null, satisfied: true };
  const proofDocument = state.documents.find(
    (d) => d.document_type === required && d.status !== 'SUPERSEDED'
  ) || null;
  return { required, proofDocument, satisfied: Boolean(proofDocument) };
}

/* Done / open / hidden for every navigation item, derived from the same server
   facts the screens read — so the sidebar can never disagree with the page. */
function stepStates() {
  const p = stepProgress();
  const caseState = (state.onboarding || {}).state || '';
  const contractVisible = CONTRACT_PHASE_STATES.includes(caseState);
  return {
    overview: 'open',
    entity: p.entity ? 'done' : 'open',
    license: p.license ? 'done' : 'open',
    hotel: p.hotel ? 'done' : 'open',
    submit: p.submit ? 'done' : 'open',
    contract: ACTIVATED_STATES.includes(caseState) ? 'done' : contractVisible ? 'open' : 'hidden',
  };
}

/* Builds the sidebar step navigation. With no explicit key it points at the
   first unfinished step, so the workspace never claims the human is somewhere
   they have not reached. */
export function renderStepBar(activeKey) {
  const st = stepStates();
  const items = [...STEPS, ...(st.contract === 'hidden' ? [] : [CONTRACT_STEP])];
  const firstOpen = STEPS.slice(1).find((s) => st[s.key] !== 'done') || STEPS[STEPS.length - 1];
  // A screen can be reached before its step exists in the navigation (for example
  // #/contract before the application is verified, where the contract item is
  // hidden). Marking nothing as current would leave the sidebar with no position
  // indicator at all, so the marker falls back to the step the applicant is
  // actually waiting on.
  const requested = activeKey || firstOpen.key;
  const current = items.some((s) => s.key === requested) ? requested : firstOpen.key;
  return `<nav class="side-nav" aria-label="入驻步骤">
      <p class="side-nav-title">入驻进度</p>
      <ol class="step-list">${items.map((s, i) => {
        const cls = s.key === current ? 'is-current' : st[s.key] === 'done' ? 'is-done' : '';
        const mark = st[s.key] === 'done' && s.key !== current ? '✓' : String(i + 1);
        return `<li class="step-item ${cls}"><a href="#/${esc(s.key)}"><span class="step-dot">${mark}</span><span class="step-label">${esc(s.label)}</span></a></li>`;
      }).join('')}</ol>
    </nav>`;
}

/* Onboarding states are internal tokens. The applicant sees a sentence.
   CONTRACT_PENDING has no entry because no version of the product has ever put a
   case into it. CONTRACT_UNDER_REVIEW keeps its entry: the previous contract flow
   could leave a case there, and an applicant looking at such a case should read a
   sentence rather than a raw token. */
const STATE_TEXT = {
  REGISTERED: '账号已创建，等待填写企业主体',
  PROFILE_DRAFT: '资料填写中',
  NEEDS_CHANGES: '资料被退回，需要修改后重新提交',
  UNDER_REVIEW: '资料已提交，正在审核',
  VERIFIED: '资料审核通过，等待签署合同',
  CLAIM_CONFLICT: '酒店归属存在争议，GO 正在人工核对',
  CONTRACT_NEEDS_CHANGES: '合同被退回，需要修改后重新提交',
  CONTRACT_UNDER_REVIEW: '合同已提交，等待确认',
  CONTRACT_ACTIVE: '合作已生效，可以进入经营后台',
  BUSINESS_ENABLED: '经营后台已开通',
};

export function stateText(value) {
  return STATE_TEXT[value] || '资料填写中';
}

/* Semantic tone per case state, so the topbar badge answers "what state am I in"
   without the applicant having to open anything. */
const STATE_TONE = {
  REGISTERED: '', PROFILE_DRAFT: '', NEEDS_CHANGES: 'bad', UNDER_REVIEW: 'warn',
  VERIFIED: 'ok', CLAIM_CONFLICT: 'warn', CONTRACT_NEEDS_CHANGES: 'bad',
  CONTRACT_UNDER_REVIEW: 'warn', CONTRACT_ACTIVE: 'ok', BUSINESS_ENABLED: 'ok',
};

/* The workspace topbar: breadcrumb + page title on the left, current state and
   the console entry on the right. */
export function topbar(activeKey, titleOverride) {
  const all = [...STEPS, CONTRACT_STEP];
  const s = all.find((x) => x.key === activeKey) || STEPS[0];
  const label = titleOverride || s.label;
  const caseState = (state.onboarding || {}).state || '';
  const activated = Boolean((state.onboarding || {}).business_ready)
    || ACTIVATED_STATES.includes(caseState);
  return `<header class="topbar">
      <div class="topbar-title">
        <div class="crumb"><b>合作伙伴平台</b><span>·</span><span>入驻</span><span>·</span><span>${esc(label)}</span></div>
        <h1>${esc(label)}</h1>
      </div>
      <div class="topbar-side">
        ${caseState ? `<span class="status ${STATE_TONE[caseState] || ''}">${esc(stateText(caseState))}</span>` : ''}
        ${activated ? '<a class="btn sm" href="/supplier-console/">进入经营后台</a>' : ''}
      </div>
    </header>`;
}

/* The workspace shell. Every business screen renders through this, so the brand
   area, the step navigation, the topbar and the content width are identical on
   all of them — and a business page can never end up inside a login card.
   `lead`, `body` and `aside` accept already-escaped HTML. `title` overrides the
   topbar heading for screens that are not one of the numbered steps (the
   activation screen, for example). */
export function shell({ active, lead, body, aside, title }) {
  const who = state.me?.username || '';
  return `<div class="shell">
    <aside class="side">
      <div class="side-brand">
        <div class="brandmark">G<i></i>O</div>
        <div class="brandtext"><b>合作伙伴平台</b><span>酒店入驻工作区</span></div>
      </div>
      ${renderStepBar(active)}
      <div class="side-foot">
        <div class="side-user"><b>${esc(who)}</b><span>合作伙伴账号</span></div>
        <button class="btn sm" id="onbLogout" type="button">退出登录</button>
      </div>
    </aside>
    <div class="main">
      ${topbar(active, title)}
      <div class="content">
        ${lead ? `<p class="page-lede">${lead}</p>` : ''}
        <div class="work-grid">
          <div class="work-main">${body}</div>
          ${aside ? `<aside class="work-aside">${aside}</aside>` : ''}
        </div>
      </div>
    </div>
  </div>`;
}

/* The context column. It answers the four questions a status area owes the
   reader: what state am I in, why, what is next, and who is waiting on whom.
   Every number here comes from state the server already returns. */
export function progressAside(note) {
  const p = stepProgress();
  const caseState = (state.onboarding || {}).state || '';
  const activated = Boolean((state.onboarding || {}).business_ready)
    || ACTIVATED_STATES.includes(caseState);
  const contractPhase = CONTRACT_PHASE_STATES.includes(caseState);
  const rows = [
    ['企业主体', p.entity], ['营业执照', p.license],
    ['酒店关系', p.hotel], ['提交审核', p.submit],
  ];
  const left = rows.filter(([, done]) => !done).map(([label]) => label);
  // The closing sentence has to match where the applicant actually stands: saying
  // "四项都已齐备，可以提交审核" on the contract screen (or after activation) is
  // true about the four rows and still the wrong instruction.
  const closing = activated
    ? '入驻已经完成。日常经营、房型房价都在经营后台进行。'
    : left.length
      ? `还需要完成 ${left.length} 项：${esc(left.join('、'))}。四项齐备后才能提交审核。`
      : contractPhase
        ? '这四项都已通过审核。当前需要处理的是合作合同。'
        : '四项都已齐备，可以提交审核。';
  return `<div class="aside-card">
      <h3>本次进度</h3>
      <div class="progress-segs">${rows.map(([, done]) => `<span class="${done ? 'on' : ''}"></span>`).join('')}</div>
      <ul class="aside-list">${rows.map(([label, done]) => `<li>
        <span class="mark ${done ? 'done' : 'todo'}">${done ? '✓' : '○'}</span>
        <span>${esc(label)}${done ? ' 已完成' : ' 待完成'}</span></li>`).join('')}</ul>
      <p class="mt-12">${closing}</p>
    </div>
    ${note || ''}
    <div class="aside-card">
      <h3>资料怎么被使用</h3>
      <p>营业执照等资料只用于资质审核，不对外公开，也不会出现在酒店公开页面上。</p>
      <p>审核期间资料不能修改；需要改动时请先等审核结果。</p>
    </div>`;
}

/* Every screen calls this right after rendering: it wires the account action and
   makes sure the step navigation shows where the human actually is.
   Below 1200px the step list is a horizontally scrolling rail, and the current
   step can sit outside the visible strip — a rail that hides "you are here" is
   worse than no rail. `block:'nearest'` keeps the page itself from jumping. */
function bindShell() {
  const btn = document.getElementById('onbLogout');
  if (btn) btn.onclick = async () => { try { await api.logout(); } catch {} state.me = null; state.onboarding = null; route(); };
  const cur = document.querySelector('.step-item.is-current');
  if (cur && typeof cur.scrollIntoView === 'function') {
    try { cur.scrollIntoView({ block: 'nearest', inline: 'center' }); } catch {}
  }
}

/* ------------------------------------------------------------------ *
 * Screens
 * ------------------------------------------------------------------ */
const SCREENS = {};

/* ------------------------------------------------------------------ *
 * Shared form validation for the register / login / recovery screens.
 *
 * Those three forms carry `novalidate`, and that is deliberate. The browser's
 * own validation bubble shows one problem at a time, cannot list everything that
 * is missing, and cannot take the person to the field it is complaining about —
 * so a submit that "does nothing" is the normal outcome. Instead every rule is
 * checked here, each problem is marked on its own field, all of them are
 * summarised in a red list under the form, and the page slides the first one
 * into the middle of the viewport and focuses it.
 * ------------------------------------------------------------------ */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const USERNAME_RE = /^(?=.*[A-Za-z])[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$/;
const PHONE_RE = /^1[3-9]\d{9}$/;
const CODE_RE = /^\d{4,6}$/;

/* The eye that toggles a password field. Drawn as inline SVG because the page
   CSP is `style-src 'self'` — an icon font or a background image would need an
   inline style, which the browser silently drops. */
const EYE_SVG = '<svg viewBox="0 0 20 20" width="17" height="17" aria-hidden="true" focusable="false">'
  + '<path d="M10 4.4c4.1 0 7.2 3.3 8.2 5.6-1 2.3-4.1 5.6-8.2 5.6S1.8 12.3.8 10C1.8 7.7 4.9 4.4 10 4.4z" fill="none" stroke="currentColor" stroke-width="1.5"/>'
  + '<circle cx="10" cy="10" r="2.5" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>';

function eyeMarkup(id, label) {
  return `<button class="btn sm eye" type="button" id="${id}" aria-label="${esc(label)}" `
    + `aria-pressed="false" title="${esc(label)}">${EYE_SVG}</button>`;
}

function bindEye(buttonId, inputId) {
  const btn = document.getElementById(buttonId);
  const input = document.getElementById(inputId);
  if (!btn || !input) return;
  btn.onclick = () => {
    const revealed = input.type === 'text';
    input.type = revealed ? 'password' : 'text';
    btn.classList.toggle('is-on', !revealed);
    btn.setAttribute('aria-pressed', String(!revealed));
  };
}

function digitsOnly(value) {
  return String(value || '').replace(/\D/g, '');
}

function fieldValue(id) {
  const el = document.getElementById(id);
  if (!el) return '';
  return el.type === 'checkbox' ? '' : String(el.value || '').trim();
}

function fieldProblem(spec) {
  const el = document.getElementById(spec.id);
  if (!el) return null;
  if (spec.type === 'checkbox') return el.checked ? null : (spec.empty || '请勾选后再继续。');
  const value = fieldValue(spec.id);
  if (!value) return spec.empty || '请填写这一项。';
  if (spec.test && !spec.test(value)) return spec.invalid || '填写内容不正确。';
  return null;
}

function showFieldError(spec, problem) {
  const el = document.getElementById(spec.id);
  const slot = document.getElementById('fe-' + spec.id);
  if (problem) {
    if (el) el.setAttribute('aria-invalid', 'true');
    if (slot) { slot.textContent = problem; slot.removeAttribute('hidden'); }
  } else {
    if (el) el.removeAttribute('aria-invalid');
    if (slot) { slot.textContent = ''; slot.setAttribute('hidden', ''); }
  }
}

function checkFields(specs) {
  const issues = [];
  for (const spec of specs) {
    const problem = fieldProblem(spec);
    if (problem) issues.push({ id: spec.id, label: spec.label, problem });
  }
  return issues;
}

/* Slide a field into the middle of the viewport and focus it. The person asked
   for the page to move to the thing that is wrong, not for a message that sits
   somewhere else on the screen. `prefers-reduced-motion` is respected. */
function revealField(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const still = typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  try { el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: still ? 'auto' : 'smooth' }); }
  catch { el.scrollIntoView(); }
  // preventScroll stops the browser from yanking the page back while the smooth
  // scroll is still running.
  try { el.focus({ preventScroll: true }); } catch { el.focus(); }
}

function reportIssues(listId, issues) {
  for (const slot of document.querySelectorAll('.field-error[data-role=field]')) {
    slot.textContent = '';
    slot.setAttribute('hidden', '');
  }
  const marked = document.querySelectorAll('#root [aria-invalid=true]');
  for (const el of marked) el.removeAttribute('aria-invalid');
  const box = document.getElementById(listId);
  if (!issues.length) {
    if (box) { box.innerHTML = ''; box.setAttribute('hidden', ''); }
    return 0;
  }
  for (const issue of issues) showFieldError(issue, issue.problem);
  if (box) {
    box.innerHTML = `<b>还有 ${issues.length} 项没有填好，点下面的提示可以直接跳到该项：</b><ul>`
      + issues.map((i) => `<li><button class="link" type="button" data-goto="${esc(i.id)}">`
        + `${esc(i.label)}：${esc(i.problem)}</button></li>`).join('')
      + '</ul>';
    box.removeAttribute('hidden');
    const jumps = box.querySelectorAll('button[data-goto]');
    for (const btn of jumps) btn.onclick = () => revealField(btn.getAttribute('data-goto'));
  }
  revealField(issues[0].id);
  return issues.length;
}

SCREENS.login = () => {
  const root = document.getElementById('root');
  root.innerHTML = `<div class="auth">
    <section class="auth-brand">
      <div class="brandmark">G<i></i>O</div>
      <h2>把酒店接进<br>GO 合作伙伴平台</h2>
      <p>面向酒店业主与经营方的一站式入驻：提交企业主体、上传营业执照、认领你经营的酒店；审核通过后在线签署合作协议，经营后台立即开通。</p>
      <ul class="auth-points">
        <li><span class="mark">1</span><span>创建账号后即可保存草稿，随时回来继续</span></li>
        <li><span class="mark">2</span><span>资料与证照只用于资质审核，不对外公开</span></li>
        <li><span class="mark">3</span><span>审核与合同进度都在同一工作区，随时可查</span></li>
      </ul>
    </section>
    <section class="auth-panel">
      <div class="auth-form">
        <h1>登录合作伙伴平台</h1>
        <p class="lead">登录后继续你的酒店入驻申请。</p>
        <form id="onbLogin" class="stack" novalidate>
          <div class="field">
            <label for="liId">账号<span class="req">*</span></label>
            <input id="liId" maxlength="128" autocomplete="username" spellcheck="false">
            <span class="hint">请使用用户名 / 邮箱 / 手机号登录</span>
            <span class="field-error" id="fe-liId" data-role="field" hidden></span>
          </div>
          <div class="field">
            <label for="liPass">密码<span class="req">*</span></label>
            <div class="pw-row">
              <input id="liPass" type="password" maxlength="128" autocomplete="current-password">
              ${eyeMarkup('liPassEye', '显示密码')}
            </div>
            <span class="field-error" id="fe-liPass" data-role="field" hidden></span>
          </div>
          <div class="issues" id="liIssues" role="alert" aria-live="polite" hidden></div>
          <div id="liErr"></div>
          <div class="btns">
            <button class="btn primary" type="submit">登录</button>
            <button class="btn" type="button" id="liRegister">申请成为 GO 合作伙伴</button>
          </div>
          <div class="linkrow">
            <button class="btn link" type="button" id="liRecover">忘记密码 / 找回账号？</button>
          </div>
        </form>
      </div>
    </section>
  </div>`;
  bindEye('liPassEye', 'liPass');
  document.getElementById('liRegister').onclick = () => (location.hash = '#/register');
  document.getElementById('liRecover').onclick = () => (location.hash = '#/recovery');
  document.getElementById('onbLogin').onsubmit = async (e) => {
    e.preventDefault();
    const errBox = document.getElementById('liErr');
    errBox.innerHTML = '';
    const issues = checkFields([
      { id: 'liId', label: '账号', empty: '请填写用户名、邮箱或手机号。' },
      { id: 'liPass', label: '密码', empty: '请填写密码。' },
    ]);
    if (reportIssues('liIssues', issues)) return;
    const btn = e.currentTarget.querySelector('button[type=submit]');
    if (btn) btn.disabled = true;
    try {
      await api.login(fieldValue('liId'), fieldValue('liPass'));
      await load();
      route();
    } catch (err) {
      errBox.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
    } finally {
      if (btn) btn.disabled = false;
    }
  };
};

/* Sign-up creates ONE account with three login identifiers (username / email /
   phone) and proves both contact channels before the account exists. The "send
   code" buttons issue the challenges; submission reuses whatever was issued, so
   the buttons are a convenience and never a ritual a person can get stuck on. */
SCREENS.register = () => {
  const root = document.getElementById('root');
  root.innerHTML = `<div class="auth">
    <section class="auth-brand">
      <div class="brandmark">G<i></i>O</div>
      <h2>先创建账号<br>再慢慢补资料</h2>
      <p>账号创建后就能保存草稿，资料齐全再提交。创建账号不代表已经通过审核，也不会产生任何对外承诺。</p>
      <ul class="auth-points">
        <li><span class="mark">1</span><span>用户名、邮箱、手机号都能登录同一个账号</span></li>
        <li><span class="mark">2</span><span>营业执照是必需材料，需与主体一致</span></li>
        <li><span class="mark">3</span><span>审核通过后才进入合同与开通环节</span></li>
      </ul>
    </section>
    <section class="auth-panel">
      <div class="auth-form">
        <h1>创建合作伙伴账号</h1>
        <p class="lead">带 <span class="req">*</span> 的为必填项。邮箱和手机号各会收到一条验证码，用来确认这两个联系方式确实是你本人的。</p>
        <div id="rgGate"></div>
        <form id="onbRegister" class="stack" novalidate>
          <div class="field">
            <label for="rgUsername">用户名<span class="req">*</span></label>
            <input id="rgUsername" maxlength="32" autocomplete="username" spellcheck="false">
            <span class="hint">3–32 位，以字母或数字开头，可用字母、数字、下划线、点和短横线。</span>
            <span class="field-error" id="fe-rgUsername" data-role="field" hidden></span>
          </div>
          <div class="field">
            <label for="rgEmail">邮箱<span class="req">*</span></label>
            <div class="code-row">
              <input id="rgEmail" type="email" maxlength="128" autocomplete="email">
              <button class="btn" type="button" id="rgEmailSend">发送验证码</button>
            </div>
            <span class="field-error" id="fe-rgEmail" data-role="field" hidden></span>
          </div>
          <div class="field">
            <label for="rgEmailCode">邮箱验证码<span class="req">*</span></label>
            <input id="rgEmailCode" inputmode="numeric" maxlength="6" autocomplete="one-time-code">
            <span class="hint" id="rgEmailHint">点「发送验证码」，再填入你收到的验证码。</span>
            <span class="field-error" id="fe-rgEmailCode" data-role="field" hidden></span>
          </div>
          <div class="field">
            <label for="rgPhone">手机号<span class="req">*</span></label>
            <div class="code-row">
              <input id="rgPhone" type="tel" inputmode="numeric" maxlength="20" autocomplete="tel">
              <button class="btn" type="button" id="rgPhoneSend">发送验证码</button>
            </div>
            <span class="field-error" id="fe-rgPhone" data-role="field" hidden></span>
          </div>
          <div class="field">
            <label for="rgPhoneCode">短信验证码<span class="req">*</span></label>
            <input id="rgPhoneCode" inputmode="numeric" maxlength="6" autocomplete="one-time-code">
            <span class="hint" id="rgPhoneHint">点「发送验证码」，再填入你收到的验证码。</span>
            <span class="field-error" id="fe-rgPhoneCode" data-role="field" hidden></span>
          </div>
          <div class="field">
            <label for="rgPass">密码<span class="req">*</span></label>
            <div class="pw-row">
              <input id="rgPass" type="password" maxlength="128" autocomplete="new-password">
              ${eyeMarkup('rgPassEye', '显示密码')}
            </div>
            <span class="hint">10–128 位。</span>
            <span class="field-error" id="fe-rgPass" data-role="field" hidden></span>
          </div>
          <div class="field">
            <label for="rgPass2">确认密码<span class="req">*</span></label>
            <div class="pw-row">
              <input id="rgPass2" type="password" maxlength="128" autocomplete="new-password">
              ${eyeMarkup('rgPass2Eye', '显示确认密码')}
            </div>
            <span class="field-error" id="fe-rgPass2" data-role="field" hidden></span>
          </div>
          <div class="field">
            <label class="checkline"><input id="rgTerms" type="checkbox">
              <span>我已阅读并同意《合作伙伴服务条款》《隐私政策》与《平台经营规则》。<span class="req">*</span></span></label>
            <span class="field-error" id="fe-rgTerms" data-role="field" hidden></span>
          </div>
          <div class="issues" id="rgIssues" role="alert" aria-live="polite" hidden></div>
          <div id="rgErr"></div>
          <div class="actionbar">
            <div class="actionbar-note">带 <span class="req">*</span> 的为必填项。</div>
            <div class="btns">
              <button class="btn primary" type="submit" id="rgSubmit">创建账号并继续</button>
              <button class="btn" type="button" id="rgBack">返回登录</button>
            </div>
          </div>
        </form>
      </div>
    </section>
  </div>`;

  bindEye('rgPassEye', 'rgPass');
  bindEye('rgPass2Eye', 'rgPass2');
  document.getElementById('rgBack').onclick = () => (location.hash = '#/login');

  const FIELDS = {
    username: { id: 'rgUsername', label: '用户名', empty: '请填写用户名。',
      test: (v) => USERNAME_RE.test(v),
      invalid: '3–32 位，以字母或数字开头，可用字母、数字、下划线、点和短横线，且至少一个字母。' },
    email: { id: 'rgEmail', label: '邮箱', empty: '请填写邮箱。',
      test: (v) => EMAIL_RE.test(v), invalid: '邮箱格式不正确。' },
    emailCode: { id: 'rgEmailCode', label: '邮箱验证码', empty: '请填写邮箱验证码。',
      test: (v) => CODE_RE.test(v), invalid: '验证码应为 4–6 位数字。' },
    phone: { id: 'rgPhone', label: '手机号', empty: '请填写手机号。',
      test: (v) => PHONE_RE.test(digitsOnly(v)), invalid: '请输入 11 位中国大陆手机号。' },
    phoneCode: { id: 'rgPhoneCode', label: '短信验证码', empty: '请填写短信验证码。',
      test: (v) => CODE_RE.test(v), invalid: '验证码应为 4–6 位数字。' },
    pass: { id: 'rgPass', label: '密码', empty: '请设置密码。',
      test: (v) => v.length >= 10 && v.length <= 128, invalid: '密码长度需为 10–128 位。' },
    pass2: { id: 'rgPass2', label: '确认密码', empty: '请再输入一遍密码。',
      test: (v) => v === fieldValue('rgPass'), invalid: '两次输入的密码不一致。' },
    terms: { id: 'rgTerms', label: '服务条款', type: 'checkbox',
      empty: '请先阅读并勾选同意服务条款与平台规则。' },
  };
  const ORDER = [FIELDS.username, FIELDS.email, FIELDS.emailCode, FIELDS.phone,
    FIELDS.phoneCode, FIELDS.pass, FIELDS.pass2, FIELDS.terms];

  /* When the server refuses, it names the field; the form marks that one. */
  const SERVER_FIELD = {
    VALID_USERNAME_REQUIRED: 'rgUsername', USERNAME_ALREADY_REGISTERED: 'rgUsername',
    VALID_EMAIL_REQUIRED: 'rgEmail', EMAIL_ALREADY_REGISTERED: 'rgEmail',
    VALID_PHONE_REQUIRED: 'rgPhone', PHONE_ALREADY_REGISTERED: 'rgPhone',
    PASSWORD_LENGTH_INVALID: 'rgPass',
    EMAIL_REGISTRATION_CODE_INVALID_OR_EXPIRED: 'rgEmailCode',
    SMS_REGISTRATION_CODE_INVALID_OR_EXPIRED: 'rgPhoneCode',
    SUPPLIER_TERMS_ACCEPTANCE_REQUIRED: 'rgTerms',
  };

  const gate = document.getElementById('rgGate');
  const sent = { email: null, sms: null };
  let policy = null;

  async function loadPolicy() {
    if (!policy) policy = unwrap(await api.supplierRegistrationTerms());
    return policy;
  }

  function gateNotice(html) {
    gate.innerHTML = html ? `<div class="notice warn">${html}</div>` : '';
  }

  async function issueChallenge(channel, value, p) {
    // Never re-derive the consent decision map on the client: the server
    // publishes `required_decisions` and `validate_decisions` compares it
    // byte-for-byte. Duplicating the rule here is how the two drift apart.
    const res = unwrap(await api.registrationChallenge({
      audience: 'supplier', email: value, channel, accepted_terms: true,
      term_versions: p.versions, term_hashes: p.term_hashes,
      registration_decisions: p.required_decisions,
    }));
    sent[channel] = { value, id: res.challenge_id, test_code: res.test_code || null, reused: false };
    return res;
  }

  // Reuse an outstanding challenge when the address has not changed. A code sent
  // to the previous address could never validate, so editing the address has to
  // retire the pair rather than leave a trap behind.
  async function ensureChallenge(channel, value, p) {
    if (sent[channel] && sent[channel].value === value) { sent[channel].reused = true; return sent[channel].id; }
    const res = await issueChallenge(channel, value, p);
    return res.challenge_id;
  }

  async function sendCode(channel, button) {
    const spec = channel === 'email' ? FIELDS.email : FIELDS.phone;
    const problem = fieldProblem(spec);
    showFieldError(spec, problem);
    if (problem) { revealField(spec.id); return; }
    const errBox = document.getElementById('rgErr');
    errBox.innerHTML = '';
    const original = button.textContent;
    button.disabled = true;
    button.textContent = '发送中…';
    try {
      const p = await loadPolicy();
      if (!p.enabled) { gateNotice('当前环境还没有接通验证码通道，暂时不能注册。请联系 GO。'); return; }
      const value = channel === 'email' ? fieldValue('rgEmail') : digitsOnly(fieldValue('rgPhone'));
      // Reuse the outstanding challenge rather than minting a second one: the
      // server enforces a 60-second resend interval per address, so a second
      // click used to answer with a rate-limit error the person could do nothing
      // about. Same address, same challenge, same code.
      const challengeId = await ensureChallenge(channel, value, p);
      const hint = document.getElementById(channel === 'email' ? 'rgEmailHint' : 'rgPhoneHint');
      const codeBox = document.getElementById(channel === 'email' ? 'rgEmailCode' : 'rgPhoneCode');
      const testCode = sent[channel] && sent[channel].test_code;
      if (testCode) {
        if (hint) hint.textContent = `当前是演示环境，验证码固定为 ${testCode}，已自动填入。`;
        if (codeBox) codeBox.value = testCode;
      } else if (hint) {
        hint.textContent = sent[channel].reused
          ? '验证码已经发过，10 分钟内有效，请填入收到的验证码。'
          : '验证码已发送，10 分钟内有效，请填入收到的验证码。';
      }
      button.textContent = '已发送';
      setTimeout(() => { button.textContent = original; button.disabled = false; }, 4000);
    } catch (err) {
      errBox.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
      button.textContent = original;
      button.disabled = false;
    }
  }

  document.getElementById('rgEmailSend').onclick = (e) => sendCode('email', e.currentTarget);
  document.getElementById('rgPhoneSend').onclick = (e) => sendCode('sms', e.currentTarget);

  document.getElementById('onbRegister').onsubmit = async (e) => {
    e.preventDefault();
    const errBox = document.getElementById('rgErr');
    errBox.innerHTML = '';
    if (reportIssues('rgIssues', checkFields(ORDER))) return;
    const submit = document.getElementById('rgSubmit');
    submit.disabled = true;
    submit.textContent = '正在创建…';
    try {
      const p = await loadPolicy();
      if (!p.enabled) { gateNotice('当前环境还没有接通验证码通道，暂时不能注册。请联系 GO。'); return; }
      const email = fieldValue('rgEmail');
      const phone = digitsOnly(fieldValue('rgPhone'));
      const emailId = await ensureChallenge('email', email, p);
      const smsId = await ensureChallenge('sms', phone, p);
      const { registration } = await api.supplierRegister({
        username: fieldValue('rgUsername'), email, phone, password: fieldValue('rgPass'),
        email_challenge_id: emailId, email_verification_code: fieldValue('rgEmailCode'),
        sms_challenge_id: smsId, sms_verification_code: fieldValue('rgPhoneCode'),
        accepted_terms: true, term_versions: p.versions, term_hashes: p.term_hashes,
        registration_decisions: p.required_decisions,
      });
      // The account is created either way; only the first session can be missing.
      // Saying "注册失败" here would send the applicant back to a form that now
      // rejects the identifier — because the account they just made owns it.
      if (registration && registration.authenticated === false) {
        errBox.innerHTML = `<div class="notice warn">${esc('账号已创建成功，但自动登录没有成功。请返回登录，用刚才设置的用户名和密码进入。')}</div>`;
        errBox.scrollIntoView({ block: 'center' });
        return;
      }
      await load();
      // Calling route() alone would render the overview while the address bar still
      // said "#/register" — and the router answers an *unauthenticated* "#/register"
      // with the sign-up form. So a person who registered and then logged out was
      // dropped back onto "创建合作伙伴账号" instead of the login form. Put the URL on
      // the screen that is actually being shown; the hashchange event routes it.
      if (location.hash === '#/overview') route(); else location.hash = '#/overview';
    } catch (err) {
      errBox.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
      const named = SERVER_FIELD[String(err.message || '')];
      if (named) revealField(named);
    } finally {
      submit.disabled = false;
      submit.textContent = '创建账号并继续';
    }
  };
};

/* Account recovery. Two questions, one screen: "which account is mine?" and "how
   do I get back in?". Both are answered by proving control of a contact channel
   with the same single-use challenge the sign-up flow uses. */
SCREENS.recovery = () => {
  const root = document.getElementById('root');
  root.innerHTML = `<div class="auth">
    <section class="auth-brand">
      <div class="brandmark">G<i></i>O</div>
      <h2>找回密码<br>或者找回账号</h2>
      <p>用注册时填写的邮箱或手机号接收验证码。验证通过后可以重设密码，也可以直接看到你的登录用户名。</p>
      <ul class="auth-points">
        <li><span class="mark">1</span><span>验证码 10 分钟内有效，而且只能用一次</span></li>
        <li><span class="mark">2</span><span>重设密码后，原来所有登录状态都会失效</span></li>
        <li><span class="mark">3</span><span>改完之后可以用用户名、邮箱或手机号登录</span></li>
      </ul>
    </section>
    <section class="auth-panel">
      <div class="auth-form">
        <h1>账号找回</h1>
        <p class="lead">带 <span class="req">*</span> 的为必填项。</p>
        <div id="rcGate"></div>
        <form id="onbRecovery" class="stack" novalidate>
          <div class="field">
            <label for="rcChannel">用哪种方式接收验证码<span class="req">*</span></label>
            <select id="rcChannel">
              <option value="email">发送到邮箱</option>
              <option value="sms">发送到手机</option>
            </select>
          </div>
          <div class="field">
            <label for="rcId" id="rcIdLabel">邮箱<span class="req">*</span></label>
            <div class="code-row">
              <input id="rcId" type="email" maxlength="128" autocomplete="username" spellcheck="false">
              <button class="btn" type="button" id="rcSend">发送验证码</button>
            </div>
            <span class="hint" id="rcIdHint">填写注册时登记的那个邮箱。</span>
            <span class="field-error" id="fe-rcId" data-role="field" hidden></span>
          </div>
          <div class="field">
            <label for="rcCode">验证码<span class="req">*</span></label>
            <input id="rcCode" inputmode="numeric" maxlength="6" autocomplete="one-time-code">
            <span class="hint" id="rcCodeHint">点「发送验证码」，再填入你收到的验证码。</span>
            <span class="field-error" id="fe-rcCode" data-role="field" hidden></span>
          </div>
          <div class="field">
            <label for="rcTarget">验证通过后要做什么<span class="req">*</span></label>
            <select id="rcTarget">
              <option value="reset">重设密码</option>
              <option value="find">只看登录用户名</option>
            </select>
          </div>
          <div id="rcPassBlock" class="stack">
            <div class="field">
              <label for="rcPass">新密码<span class="req">*</span></label>
              <div class="pw-row">
                <input id="rcPass" type="password" maxlength="128" autocomplete="new-password">
                ${eyeMarkup('rcPassEye', '显示新密码')}
              </div>
              <span class="hint">10–128 位。</span>
              <span class="field-error" id="fe-rcPass" data-role="field" hidden></span>
            </div>
            <div class="field">
              <label for="rcPass2">确认新密码<span class="req">*</span></label>
              <div class="pw-row">
                <input id="rcPass2" type="password" maxlength="128" autocomplete="new-password">
                ${eyeMarkup('rcPass2Eye', '显示确认新密码')}
              </div>
              <span class="field-error" id="fe-rcPass2" data-role="field" hidden></span>
            </div>
          </div>
          <div class="issues" id="rcIssues" role="alert" aria-live="polite" hidden></div>
          <div id="rcErr"></div>
          <div class="actionbar">
            <div class="actionbar-note">带 <span class="req">*</span> 的为必填项。</div>
            <div class="btns">
              <button class="btn primary" type="submit" id="rcSubmit">提交</button>
              <button class="btn" type="button" id="rcBack">返回登录</button>
            </div>
          </div>
        </form>
        <!-- The result lives OUTSIDE the form on purpose: a successful recovery
             hides the form, and a result rendered inside it would be hidden too. -->
        <div id="rcResult" hidden></div>
      </div>
    </section>
  </div>`;

  bindEye('rcPassEye', 'rcPass');
  bindEye('rcPass2Eye', 'rcPass2');
  document.getElementById('rcBack').onclick = () => (location.hash = '#/login');

  const channelSel = document.getElementById('rcChannel');
  const targetSel = document.getElementById('rcTarget');
  const gate = document.getElementById('rcGate');
  const errBox = document.getElementById('rcErr');
  const sent = { value: null, id: null };

  function syncChannel() {
    const mail = channelSel.value === 'email';
    document.getElementById('rcIdLabel').innerHTML = `${mail ? '邮箱' : '手机号'}<span class="req">*</span>`;
    document.getElementById('rcIdHint').textContent = mail
      ? '填写注册时登记的那个邮箱。' : '填写注册时登记的 11 位手机号。';
    const box = document.getElementById('rcId');
    box.type = mail ? 'email' : 'tel';
    box.setAttribute('inputmode', mail ? 'email' : 'numeric');
    // A code sent to the previous address could never validate, so changing the
    // channel retires the pending challenge instead of leaving a trap behind.
    sent.value = null;
    sent.id = null;
    showFieldError({ id: 'rcId' }, null);
    document.getElementById('rcCodeHint').textContent = '点「发送验证码」，再填入你收到的验证码。';
  }

  function syncTarget() {
    document.getElementById('rcPassBlock').classList.toggle('hidden', targetSel.value !== 'reset');
  }

  channelSel.onchange = syncChannel;
  targetSel.onchange = syncTarget;
  syncChannel();
  syncTarget();

  function idSpec() {
    return channelSel.value === 'email'
      ? { id: 'rcId', label: '邮箱', empty: '请填写邮箱。',
          test: (v) => EMAIL_RE.test(v), invalid: '邮箱格式不正确。' }
      : { id: 'rcId', label: '手机号', empty: '请填写手机号。',
          test: (v) => PHONE_RE.test(digitsOnly(v)), invalid: '请输入 11 位中国大陆手机号。' };
  }
  const CODE_SPEC = { id: 'rcCode', label: '验证码', empty: '请填写验证码。',
    test: (v) => CODE_RE.test(v), invalid: '验证码应为 4–6 位数字。' };
  const PASS_SPEC = { id: 'rcPass', label: '新密码', empty: '请设置新密码。',
    test: (v) => v.length >= 10 && v.length <= 128, invalid: '密码长度需为 10–128 位。' };
  const PASS2_SPEC = { id: 'rcPass2', label: '确认新密码', empty: '请再输入一遍新密码。',
    test: (v) => v === fieldValue('rcPass'), invalid: '两次输入的密码不一致。' };

  const SERVER_FIELD = {
    RECOVERY_ACCOUNT_NOT_FOUND: 'rcId', VALID_EMAIL_REQUIRED: 'rcId', VALID_PHONE_REQUIRED: 'rcId',
    REGISTRATION_CODE_INVALID_OR_EXPIRED: 'rcCode', REGISTRATION_CODE_REPLACED: 'rcCode',
    REGISTRATION_VERIFICATION_NOT_READY: 'rcId', REGISTRATION_SMS_NOT_READY: 'rcId',
    REGISTRATION_EMAIL_SEND_FAILED: 'rcId',
    PASSWORD_LENGTH_INVALID: 'rcPass', PASSWORD_CONFIRMATION_MISMATCH: 'rcPass2',
  };

  function identifier() {
    return channelSel.value === 'email' ? fieldValue('rcId') : digitsOnly(fieldValue('rcId'));
  }

  document.getElementById('rcSend').onclick = async (e) => {
    const button = e.currentTarget;
    const spec = idSpec();
    const problem = fieldProblem(spec);
    showFieldError(spec, problem);
    if (problem) { revealField(spec.id); return; }
    errBox.innerHTML = '';
    const original = button.textContent;
    button.disabled = true;
    button.textContent = '发送中…';
    try {
      const res = unwrap(await api.recoveryChallenge({ identifier: identifier(), channel: channelSel.value }));
      sent.value = identifier();
      sent.id = res.challenge_id;
      const hint = document.getElementById('rcCodeHint');
      if (res.test_code) {
        hint.textContent = `当前是演示环境，验证码固定为 ${res.test_code}，已自动填入。`;
        document.getElementById('rcCode').value = res.test_code;
      } else {
        hint.textContent = '验证码已发送，10 分钟内有效，请填入收到的验证码。';
      }
      button.textContent = '已发送';
      setTimeout(() => { button.textContent = original; button.disabled = false; }, 4000);
    } catch (err) {
      errBox.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
      button.textContent = original;
      button.disabled = false;
    }
  };

  document.getElementById('onbRecovery').onsubmit = async (e) => {
    e.preventDefault();
    errBox.innerHTML = '';
    const reset = targetSel.value === 'reset';
    const specs = [idSpec(), CODE_SPEC];
    if (reset) specs.push(PASS_SPEC, PASS2_SPEC);
    if (reportIssues('rcIssues', checkFields(specs))) return;
    const submit = document.getElementById('rcSubmit');
    submit.disabled = true;
    try {
      if (!sent.id || sent.value !== identifier()) {
        errBox.innerHTML = '<div class="notice error">请先点「发送验证码」，拿到这一条验证码后再提交。</div>';
        revealField('rcId');
        return;
      }
      const base = { identifier: identifier(), channel: channelSel.value,
        challenge_id: sent.id, verification_code: fieldValue('rcCode') };
      if (reset) {
        const res = unwrap(await api.recoveryPassword({ ...base,
          new_password: fieldValue('rcPass'), confirm_password: fieldValue('rcPass2') }));
        finish(`密码已重设。以后请用「${esc(res.username)}」作为账号登录，邮箱和手机号也可以。`);
      } else {
        const res = unwrap(await api.recoveryUsername(base));
        finish(`你的登录用户名是「${esc(res.username)}」。用它、邮箱或手机号都可以登录。`);
      }
    } catch (err) {
      errBox.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
      const named = SERVER_FIELD[String(err.message || '')];
      if (named) revealField(named);
    } finally {
      submit.disabled = false;
    }
  };

  function finish(html) {
    document.getElementById('onbRecovery').classList.add('hidden');
    const box = document.getElementById('rcResult');
    box.innerHTML = `<div class="notice ok">${html}</div>`
      + '<div class="btns mt-12"><button class="btn primary" type="button" id="rcDone">去登录</button></div>';
    box.removeAttribute('hidden');
    const go = document.getElementById('rcDone');
    if (go) go.onclick = () => { location.hash = '#/login'; };
  }

  (async () => {
    try {
      const p = unwrap(await api.supplierRegistrationTerms());
      if (!p.enabled) {
        gate.innerHTML = '<div class="notice warn">当前环境还没有接通验证码通道，找回功能暂时不可用。请联系 GO。</div>';
      }
    } catch {}
  })();
};

function overviewCards() {
  const claim = savedClaim() || {};
  const entity = state.legalEntity || {};
  const license = currentDocument('BUSINESS_LICENSE');
  const hotelDone = Boolean(claim.relationship_type && (claim.hotel_id || claim.proposed_hotel));
  const hotelDesc = hotelDone
    ? `${(claim.hotel_display || {}).name || '已选择酒店'} · ${RELATIONSHIP_LABEL[claim.relationship_type] || claim.relationship_type}${
        claim.mode === 'PROPOSED' ? '（新酒店，审核通过后才会建档）' : ''
      }`
    : '搜索并认领你经营的酒店，或提交新酒店资料';
  const cards = [
    { key: 'entity', title: '企业主体', done: Boolean(entity.legal_name && entity.unified_social_credit_code),
      desc: '企业法定名称、统一社会信用代码、法定代表人、注册地址' },
    { key: 'license', title: '营业执照', done: Boolean(license),
      desc: license ? `已上传：${license.original_filename}（第 ${license.revision} 版）` : '上传营业执照（JPG / PNG / PDF，≤10MB）' },
    { key: 'hotel', title: '酒店关系', done: hotelDone, desc: hotelDesc },
  ];
  // Once the application is approved the next thing to do is the contract, and it
  // belongs on the overview — otherwise an approved applicant sees "全部完成" and
  // has no idea what the platform is waiting for.
  const caseState = (state.onboarding || {}).state;
  if (['VERIFIED', 'CONTRACT_NEEDS_CHANGES', 'CONTRACT_UNDER_REVIEW'].includes(caseState)) {
    cards.push({
      key: 'contract',
      title: '合作合同',
      done: false,
      desc: '阅读合作协议、上传盖章件并确认；确认后经营后台立即开通',
    });
  }
  // Laid out as a 3-up grid so a 1440/1920 desktop actually uses its width
  // instead of rendering three full-bleed cards stacked in a single column.
  return `<div class="grid three">${cards
    .map((c) => `<div class="card">
      <h3>${esc(c.title)}</h3>
      <p class="mb-10"><span class="pill ${c.done ? 'ok' : 'neutral'}">${c.done ? '已完成' : '未完成'}</span></p>
      <p class="muted small mb-12">${esc(c.desc)}</p>
      <button class="btn sm" data-goto="${c.key}">${c.done ? '查看 / 修改' : '开始填写'}</button>
    </div>`)
    .join('')}</div>`;
}

SCREENS.overview = () => {
  const root = document.getElementById('root');
  const onb = state.onboarding || {};
  const caseState = onb.state || '';
  const contractPhase = ['VERIFIED', 'CONTRACT_NEEDS_CHANGES', 'CONTRACT_UNDER_REVIEW'].includes(caseState);
  const lead = contractPhase
    ? '主体与酒店审核已经通过。下一步完成合作合同，确认后经营后台立即开通。'
    : ['UNDER_REVIEW', 'CLAIM_CONFLICT'].includes(caseState)
      ? '资料已经提交，正在人工审核。审核完成前你不需要重复提交。'
      : '你好，' + (state.me?.username || '') + '。把下面三项补齐后即可提交审核。全部完成才能提交。';
  root.innerHTML = shell({
    active: 'overview',
    lead: esc(lead),
    body: `${overviewCards()}
      <div class="card">
        <div class="actionbar">
          <div class="actionbar-note">当前进度：${esc(stateText(onb.state))}</div>
          <div class="btns">
            <button class="btn primary" id="ovContinue" type="button">${contractPhase ? '去签署合作合同' : '继续上次'}</button>
          </div>
        </div>
      </div>`,
    aside: progressAside(),
  });
  bindShell();
  root.querySelectorAll('[data-goto]').forEach((b) => {
    b.onclick = () => { location.hash = '#/' + b.dataset.goto; };
  });
  document.getElementById('ovContinue').onclick = () => {
    const caseState = (state.onboarding || {}).state;
    if (['VERIFIED', 'CONTRACT_NEEDS_CHANGES', 'CONTRACT_UNDER_REVIEW'].includes(caseState)) {
      location.hash = '#/contract';
      return;
    }
    const p = stepProgress();
    const next = !p.entity ? 'entity' : !p.license ? 'license' : !p.hotel ? 'hotel' : 'submit';
    location.hash = '#/' + next;
  };
};

/* ------------------------------------------------------------------ *
 * Step 2 — 企业主体 (legal entity)
 *
 * One supplier tenant owns exactly one legal entity. The identity account is
 * only the operator holding credentials today, so the form never asks for a
 * user name and never shows an internal id.
 * ------------------------------------------------------------------ */
SCREENS.entity = () => {
  const root = document.getElementById('root');
  const e = state.legalEntity || {};
  root.innerHTML = shell({
    active: 'entity',
    lead: esc('请与营业执照保持一致。统一社会信用代码不区分大小写，系统会自动转为大写。'),
    body: `<div class="card">
        <div class="section-head"><h2>企业主体信息</h2><span class="section-note">带 <span class="req">*</span> 为必填</span></div>
        <div id="leMsg" class="mt-16"></div>
        <form id="leForm" class="form-grid mt-16" novalidate>
          <div class="field"><label for="leName">企业法定名称<span class="req">*</span></label>
            <input id="leName" type="text" maxlength="200" autocomplete="organization"
              value="${esc(e.legal_name || '')}" required></div>
          <div class="field"><label for="leUscc">统一社会信用代码<span class="req">*</span></label>
            <input id="leUscc" type="text" maxlength="18" spellcheck="false" autocomplete="off"
              value="${esc(e.unified_social_credit_code || '')}" required>
            <span class="hint">营业执照上的 18 位号码，由数字和大写字母组成。</span></div>
          <div class="field"><label for="leRep">法定代表人姓名<span class="req">*</span></label>
            <input id="leRep" type="text" maxlength="80" value="${esc(e.legal_representative_name || '')}" required></div>
          <div class="field"><label for="leAddr">企业注册地址<span class="req">*</span></label>
            <input id="leAddr" type="text" maxlength="300" value="${esc(e.registered_address || '')}" required>
            <span class="hint">与营业执照上的注册地址一致。</span></div>
          <div class="field span-2">
            <label class="checkline"><input id="leLong" type="checkbox" ${e.license_long_term ? 'checked' : ''}>
              <span>营业执照长期有效（执照上没有到期日）</span></label>
          </div>
          <div class="form-grid span-2" id="leWindow">
            <div class="field"><label for="leFrom">有效期起始</label>
              <input id="leFrom" type="date" value="${esc(e.license_valid_from || '')}"></div>
            <div class="field"><label for="leUntil">有效期至</label>
              <input id="leUntil" type="date" value="${esc(e.license_valid_until || '')}"></div>
          </div>
          <div class="actionbar span-2">
            <div class="actionbar-note">保存后即可继续上传营业执照；稍后可以回来修改。</div>
            <div class="btns">
              <button class="btn primary" type="submit" id="leSave">保存并继续</button>
              <button class="btn" type="button" id="leBack">返回概览</button>
            </div>
          </div>
        </form>
      </div>`,
    aside: progressAside(),
  });
  bindShell();

  // A CSP of `style-src 'self'` blocks `element.style` writes, so the toggle
  // must be a class swap.
  const toggleWindow = () => {
    const long = document.getElementById('leLong').checked;
    document.getElementById('leWindow').classList.toggle('hidden', long);
  };
  document.getElementById('leLong').onchange = toggleWindow;
  toggleWindow();
  document.getElementById('leBack').onclick = () => (location.hash = '#/overview');

  document.getElementById('leForm').onsubmit = async (ev) => {
    ev.preventDefault();
    const msg = document.getElementById('leMsg');
    const btn = document.getElementById('leSave');
    msg.innerHTML = '';
    const long = document.getElementById('leLong').checked;
    const body = {
      legal_name: document.getElementById('leName').value.trim(),
      unified_social_credit_code: document.getElementById('leUscc').value.trim(),
      legal_representative_name: document.getElementById('leRep').value.trim(),
      registered_address: document.getElementById('leAddr').value.trim(),
      license_long_term: long,
      license_valid_from: long ? null : document.getElementById('leFrom').value || null,
      license_valid_until: long ? null : document.getElementById('leUntil').value || null,
    };
    // The server is the authority on every rule; this is a courtesy prompt only.
    if (!body.legal_name || !body.unified_social_credit_code || !body.legal_representative_name || !body.registered_address) {
      msg.innerHTML = '<div class="notice warn">请把企业法定名称、统一社会信用代码、法定代表人和注册地址都填写完整。</div>';
      return;
    }
    btn.disabled = true;
    try {
      state.legalEntity = unwrap(await api.saveSupplierLegalEntity(body));
      msg.innerHTML = '<div class="notice ok">企业主体已保存。</div>';
      await load();
      location.hash = '#/license';
    } catch (err) {
      // A failed save must never wipe what the human typed: leave the form alone
      // and only show the translated reason.
      msg.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
    } finally {
      btn.disabled = false;
    }
  };
};

/* ------------------------------------------------------------------ *
 * Step 3 — 营业执照 (private applicant evidence)
 *
 * The file lives on a private volume, never in the public hotel media
 * library. Only the applicant and an authorised onboarding reviewer can read
 * it. Replacing it produces revision 2 and keeps revision 1 as history.
 *
 * Preview deliberately does not weaken the platform's framing headers: an
 * image renders inline (img-src 'self'), a PDF opens in a new tab. XFO DENY
 * and frame-ancestors 'none' stay in force.
 * ------------------------------------------------------------------ */
const DOC_STATUS = {
  UPLOADED: '已上传，等待审核',
  ACCEPTED: '审核通过',
  REJECTED: '审核不通过，请更换后重新上传',
  SUPERSEDED: '已被新版本替换',
};

const MAX_DOC_BYTES = 10 * 1024 * 1024;
const ALLOWED_DOC_TYPES = ['image/jpeg', 'image/png', 'application/pdf'];

const DOC_TYPE_TEXT = {
  'image/jpeg': 'JPG 图片',
  'image/png': 'PNG 图片',
  'application/pdf': 'PDF 文件',
};

function fmtBytes(n) {
  const v = Number(n) || 0;
  if (v >= 1048576) return (v / 1048576).toFixed(2) + ' MB';
  return Math.max(1, Math.round(v / 1024)) + ' KB';
}

/* Timestamps arrive as UTC ISO strings. Showing them verbatim puts a machine
   token and the wrong clock in front of a real person. */
function fmtWhen(iso) {
  if (!iso) return '—';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return String(iso);
  return at.toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' });
}

function fmtType(mime) {
  return DOC_TYPE_TEXT[String(mime || '').toLowerCase()] || String(mime || '—');
}

SCREENS.license = () => {
  const root = document.getElementById('root');
  const license = currentDocument('BUSINESS_LICENSE');
  if (!state.legalEntity) {
    root.innerHTML = shell({
      active: 'license',
      lead: esc('营业执照用于核验企业主体，只会登记在你填写的企业主体上。'),
      body: `<div class="card">
        <div class="notice warn">请先完成上一步「企业主体」。营业执照要登记在你填写的企业主体上，否则审核人员无法核对。</div>
        <div class="actionbar">
          <div class="actionbar-note">企业主体完成后，这一步会自动解锁。</div>
          <div class="btns"><button class="btn primary" id="licGoEntity" type="button">去填写企业主体</button></div>
        </div>
      </div>`,
      aside: progressAside(),
    });
    bindShell();
    document.getElementById('licGoEntity').onclick = () => (location.hash = '#/entity');
    return;
  }

  const meta = license
    ? `<dl class="kv">
        <dt>文件名</dt><dd>${esc(license.original_filename)}</dd>
        <dt>文件格式</dt><dd>${esc(fmtType(license.mime_type))}</dd>
        <dt>文件大小</dt><dd>${fmtBytes(license.size_bytes)}</dd>
        <dt>版本</dt><dd>第 ${Number(license.revision) || 1} 版</dd>
        <dt>上传时间</dt><dd>${esc(fmtWhen(license.uploaded_at))}</dd>
        <dt>状态</dt><dd><span class="pill ${
          license.status === 'REJECTED' ? 'bad' : license.status === 'ACCEPTED' ? 'ok' : 'neutral'
        }">${esc(DOC_STATUS[license.status] || license.status)}</span></dd>
      </dl>`
    : `<div class="notice info">还没有上传营业执照。请在下面选择营业执照的清晰照片或扫描件。</div>`;

  const inlinePreview = license && license.mime_type.startsWith('image/')
    ? `<div class="preview"><img alt="营业执照预览" src="/bff/supplier/legal-entity/documents/${encodeURIComponent(license.document_id)}/content?disposition=inline"><p class="muted small">这是当前生效的第 ${Number(license.revision) || 1} 版营业执照。</p></div>`
    : '';

  root.innerHTML = shell({
    active: 'license',
    lead: esc('营业执照用于核验企业主体。只有你本人和 GO 入驻审核人员可以看到这份文件，它不会出现在酒店公开页面。'),
    body: `<div class="card">
        <div class="section-head"><h2>当前营业执照</h2>
          <span class="section-note">${license ? `第 ${Number(license.revision) || 1} 版` : '尚未上传'}</span></div>
        <div id="licMsg" class="mt-16"></div>
        <div class="mt-16">${meta}</div>
        ${license ? `<div class="btns mt-16">
          <button class="btn" id="licPreview" type="button">预览</button>
          <button class="btn" id="licDownload" type="button">下载</button>
          <button class="btn" id="licToForm" type="button">更换营业执照</button>
        </div>` : ''}
      </div>

      <div class="card">
        <div class="section-head"><h2>${license ? '更换营业执照' : '上传营业执照'}</h2>
          <span class="section-note">JPG / PNG / PDF，单份 ≤ 10MB</span></div>
        <p class="muted small mt-16">重新上传会生成新版本（第 ${(Number(license?.revision) || 0) + 1} 版），旧版本保留作为记录，审核人员看到的是最新版本。</p>
        <div class="field mt-16">
          <label for="licFile">选择文件<span class="req">*</span></label>
          <input id="licFile" type="file" accept="image/jpeg,image/png,application/pdf,.jpg,.jpeg,.png,.pdf">
          <span class="hint">请确保企业名称、统一社会信用代码清晰可读，四角完整无遮挡。</span>
          <span class="err hidden" id="licFileErr"></span>
        </div>
        <div class="actionbar">
          <div class="actionbar-note">上传后仍可更换；只有最新版本会被审核。</div>
          <div class="btns">
            <button class="btn primary" id="licSave" type="button">${license ? '上传新版本' : '上传'}</button>
            <button class="btn" id="licBack" type="button">返回概览</button>
          </div>
        </div>
      </div>
      ${inlinePreview}`,
    aside: progressAside(),
  });

  bindShell();
  document.getElementById('licBack').onclick = () => (location.hash = '#/overview');
  const toForm = document.getElementById('licToForm');
  if (toForm) toForm.onclick = () => document.getElementById('licFile').click();

  if (license) {
    const openPreview = () => {
      // A PDF cannot be framed without relaxing XFO/frame-ancestors, so preview
      // is a same-origin new tab. The browser's own viewer renders it inline.
      window.open(
        `/bff/supplier/legal-entity/documents/${encodeURIComponent(license.document_id)}/content?disposition=inline`,
        '_blank',
        'noopener'
      );
    };
    document.getElementById('licPreview').onclick = openPreview;
    document.getElementById('licDownload').onclick = () => {
      const a = document.createElement('a');
      a.href = `/bff/supplier/legal-entity/documents/${encodeURIComponent(license.document_id)}/content?disposition=attachment`;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
    };
  }

  const fileInput = document.getElementById('licFile');
  fileInput.onchange = () => {
    const f = fileInput.files && fileInput.files[0];
    const err = document.getElementById('licFileErr');
    err.classList.add('hidden');
    if (!f) return;
    // Courtesy checks only. The server re-validates size, magic bytes and the
    // declared type; nothing here is a security boundary.
    if (f.size > MAX_DOC_BYTES) {
      err.textContent = '文件超过 10MB，请压缩后重新选择。';
      err.classList.remove('hidden');
      return;
    }
    const type = (f.type || '').toLowerCase();
    const ext = (f.name.split('.').pop() || '').toLowerCase();
    const extOk = ['jpg', 'jpeg', 'png', 'pdf'].includes(ext);
    if ((type && !ALLOWED_DOC_TYPES.includes(type)) || !extOk) {
      err.textContent = '文件格式不支持，请选择 JPG、PNG 或 PDF 文件。';
      err.classList.remove('hidden');
    }
  };

  document.getElementById('licSave').onclick = async () => {
    const msg = document.getElementById('licMsg');
    const btn = document.getElementById('licSave');
    const f = fileInput.files && fileInput.files[0];
    msg.innerHTML = '';
    if (!f) {
      msg.innerHTML = '<div class="notice warn">请先选择要上传的营业执照文件。</div>';
      return;
    }
    btn.disabled = true;
    msg.innerHTML = '<div class="notice info">正在上传并校验文件…</div>';
    try {
      // expected_revision is the guard for a stale page: if the licence was
      // replaced in another tab, this upload is refused instead of silently
      // overwriting a version the reviewer may already be looking at.
      await api.uploadSupplierDocument(
        { document_type: 'BUSINESS_LICENSE', expected_revision: Number(license?.revision) || 0 },
        f
      );
      await load();
      SCREENS.license();
      document.getElementById('licMsg').innerHTML =
        '<div class="notice ok">营业执照已上传。你可以继续下一步，或稍后回来更换版本。</div>';
    } catch (err) {
      // Never clear the chosen file on failure: the human should not have to
      // pick it again just because the server refused it.
      msg.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
      btn.disabled = false;
    }
  };
};

/* ------------------------------------------------------------------ *
 * Step 4 — 酒店关系 (hotel claim)
 *
 * Two ways to identify a hotel, and the difference matters:
 *   - the hotel is already in the GO catalogue  -> claim it;
 *   - it is not                                 -> submit it as a proposal,
 *     which creates NOTHING until a human approves it.
 * The applicant never types an internal id: search returns rows, the row's id
 * travels as an opaque option value in the request body only.
 * ------------------------------------------------------------------ */
const CLAIM_STATE_TEXT = {
  AVAILABLE: '可以认领',
  IN_PROGRESS: '已有申请在办理',
  CLAIMED: '已被认领',
};

let hotelDraft = null;
let hotelCandidates = [];

function draftFromSaved() {
  const claim = savedClaim();
  if (!claim) return null;
  return {
    mode: claim.mode,
    hotel_id: claim.hotel_id || null,
    proposed_hotel: claim.proposed_hotel || null,
    display: claim.hotel_display || {},
    relationship_type: claim.relationship_type || '',
  };
}

function candidateCard(candidate) {
  const tone = candidate.claim_state === 'AVAILABLE' ? 'ok' : 'neutral';
  const where = [candidate.city, candidate.address].filter(Boolean).join(' · ');
  return `<div class="card">
    <h3>${esc(candidate.name)}</h3>
    <p class="muted small mb-10">${esc(where || '地址待补充')}</p>
    <p class="mb-12"><span class="pill ${tone}">${esc(CLAIM_STATE_TEXT[candidate.claim_state] || '')}</span></p>
    <button class="btn sm" type="button" data-pick="${esc(candidate.hotel_id)}">选择这家</button>
  </div>`;
}

SCREENS.hotel = () => {
  const root = document.getElementById('root');
  if (!state.legalEntity) {
    root.innerHTML = shell({
      active: 'hotel',
      lead: esc('酒店关系要挂在你的企业主体上，否则审核人员无法核对。'),
      body: `<div class="card">
        <div class="notice warn">请先完成上一步「企业主体」。酒店关系要挂在你的企业主体上，否则审核人员无法核对。</div>
        <div class="actionbar">
          <div class="actionbar-note">企业主体完成后，这一步会自动解锁。</div>
          <div class="btns"><button class="btn primary" id="hotGoEntity" type="button">去填写企业主体</button></div>
        </div>
      </div>`,
      aside: progressAside(),
    });
    bindShell();
    document.getElementById('hotGoEntity').onclick = () => (location.hash = '#/entity');
    return;
  }

  if (!hotelDraft) hotelDraft = draftFromSaved();
  const draft = hotelDraft;
  const relationship = (draft && draft.relationship_type) || '';
  const claim = savedClaim() || {};
  // Once the application is in a human's hands the claim is frozen. CONTRACT_PENDING
  // is gone from this list because nothing ever set that state; the states that stay
  // are the ones the workflow (or an older version of it) can actually produce.
  const locked = ['UNDER_REVIEW', 'VERIFIED', 'CLAIM_CONFLICT', 'CONTRACT_NEEDS_CHANGES',
    'CONTRACT_UNDER_REVIEW', 'CONTRACT_ACTIVE', 'BUSINESS_ENABLED']
    .includes((state.onboarding || {}).state);

  const relOptions = ['', ...Object.keys(RELATIONSHIP_LABEL)].map((value) => {
    const label = value ? RELATIONSHIP_LABEL[value] : '请选择';
    return `<option value="${esc(value)}" ${value === relationship ? 'selected' : ''}>${esc(label)}</option>`;
  }).join('');

  root.innerHTML = shell({
    active: 'hotel',
    lead: esc('请选择你与这家酒店的关系，并认领平台上已有的酒店。资料提交后这里将不能修改，请确认无误再提交审核。'),
    body: `<div class="card">
        <div class="section-head"><h2>你与这家酒店的关系</h2>
          <span class="section-note">带 <span class="req">*</span> 为必填</span></div>
        <div id="hMsg" class="mt-16"></div>
        <div class="field mt-16">
          <label for="hRel">关系类型<span class="req">*</span></label>
          <select id="hRel" ${locked ? 'disabled' : ''}>${relOptions}</select>
          <span class="hint">不同关系需要的证明材料不同；非业主关系需要额外出具授权或管理证明。</span>
        </div>
        <div id="hProofBlock"></div>
      </div>

      <div class="card">
        <div class="section-head"><h2>第一步 · 搜索平台上已有的酒店</h2>
          <span class="section-note">按名称搜索，重名多时再填城市</span></div>
        <div class="form-grid mt-16">
          <div class="field"><label for="hQ">酒店名称</label>
            <input id="hQ" maxlength="80" value="${esc(((draft || {}).display || {}).name || '')}"></div>
          <div class="field"><label for="hCity">所在城市</label>
            <input id="hCity" maxlength="40" value="${esc(((draft || {}).display || {}).city || '')}"></div>
        </div>
        <div class="btns mt-16"><button class="btn" id="hSearch" type="button">搜索</button></div>
        <div id="hResults" class="mt-16"></div>
      </div>

      <div class="card">
        <div class="section-head"><h2>第二步 · 搜不到就提交新酒店资料</h2>
          <span class="section-note">审核通过后才会建档</span></div>
        <p class="muted small mt-16">提交后平台不会立刻建立酒店档案。GO 审核通过后才会创建，这样可以避免平台上出现重复酒店。</p>
        <div class="form-grid mt-16">
          <div class="field"><label for="hNewName">酒店名称</label>
            <input id="hNewName" maxlength="160" value="${esc(((draft || {}).proposed_hotel || {}).name || '')}"></div>
          <div class="field"><label for="hNewCity">所在城市</label>
            <input id="hNewCity" maxlength="80" value="${esc(((draft || {}).proposed_hotel || {}).city || '')}"></div>
          <div class="field span-2"><label for="hNewAddr">详细地址（选填）</label>
            <input id="hNewAddr" maxlength="300" value="${esc(((draft || {}).proposed_hotel || {}).address || '')}"></div>
        </div>
        <div class="btns mt-16"><button class="btn" id="hUseNew" type="button">就用这家新酒店</button></div>
      </div>

      <div class="card">
        <div class="section-head"><h2>当前选择</h2>
          <span class="section-note">${esc(stateText((state.onboarding || {}).state))}</span></div>
        <div id="hCurrent" class="mt-16"></div>
        ${
          claim.approved_at
            ? '<div class="notice ok">这家酒店已经审核通过，归属已确认。</div>'
            : claim.conflict
            ? `<div class="notice warn">这家酒店同时有其他申请，GO 正在人工核对。你暂时不需要再次提交。${
                (claim.conflict.hotel_display || {}).name
                  ? '平台已找到同名酒店：' + esc(claim.conflict.hotel_display.name) + '。'
                  : ''
              }</div>`
            : ''
        }
        <div class="actionbar">
          <div class="actionbar-note">保存后仍可回来修改，直到你提交审核为止。</div>
          <div class="btns">
            <button class="btn primary" id="hSave" type="button" ${locked ? 'disabled' : ''}>保存酒店关系</button>
            <button class="btn" id="hBack" type="button">返回概览</button>
          </div>
        </div>
      </div>`,
    aside: progressAside(),
  });

  bindShell();
  document.getElementById('hBack').onclick = () => (location.hash = '#/overview');

  function renderCurrent() {
    const el = document.getElementById('hCurrent');
    const current = hotelDraft;
    if (!current || (!current.hotel_id && !current.proposed_hotel)) {
      el.innerHTML = '<div class="notice info">还没有选择酒店。</div>';
      return;
    }
    const name = (current.display || {}).name || '';
    el.innerHTML = `<dl class="kv">
      <dt>酒店</dt><dd>${esc(name || '未命名')}</dd>
      <dt>识别方式</dt><dd>${current.mode === 'PROPOSED' ? '提交新酒店（审核通过后建档）' : '认领平台已有酒店'}</dd>
      <dt>关系</dt><dd>${esc(RELATIONSHIP_LABEL[current.relationship_type] || '未选择')}</dd>
    </dl>`;
  }

  function renderProof() {
    const el = document.getElementById('hProofBlock');
    const rel = document.getElementById('hRel').value;
    if (!rel) {
      el.innerHTML = '<p class="muted small mt-12">选择关系后，这里会说明需要哪些证明。</p>';
      return;
    }
    const { required, proofDocument } = proofState(rel);
    if (!required) {
      el.innerHTML = '<div class="notice info mt-12">业主关系无需额外证明，营业执照即可。</div>';
      return;
    }
    el.innerHTML = `<div class="notice ${proofDocument ? 'ok' : 'warn'} mt-12">${
      proofDocument
        ? `已上传${esc(PROOF_LABEL[required])}：${esc(proofDocument.original_filename)}（第 ${proofDocument.revision} 版）`
        : `这个关系需要上传${esc(PROOF_LABEL[required])}，未上传时无法保存。`
    }</div>
    <div class="field mt-12"><label for="hProofFile">上传${esc(PROOF_LABEL[required])}</label>
      <input id="hProofFile" type="file" accept="image/jpeg,image/png,application/pdf,.jpg,.jpeg,.png,.pdf">
      <span class="hint">支持 JPG / PNG / PDF，单份不超过 10MB。只有你本人和 GO 审核人员可以查看。</span></div>
    <div class="btns mt-12"><button class="btn" id="hProofUpload" type="button">上传</button></div>`;

    document.getElementById('hProofUpload').onclick = async () => {
      const msg = document.getElementById('hMsg');
      const fileInput = document.getElementById('hProofFile');
      const file = fileInput.files && fileInput.files[0];
      msg.innerHTML = '';
      if (!file) {
        msg.innerHTML = '<div class="notice warn">请先选择要上传的文件。</div>';
        return;
      }
      const btn = document.getElementById('hProofUpload');
      btn.disabled = true;
      msg.innerHTML = '<div class="notice info">正在上传并校验文件…</div>';
      try {
        await api.uploadSupplierDocument(
          { document_type: required, scope: 'ONBOARDING', expected_revision: Number(proofDocument?.revision) || 0 },
          file
        );
        await load();
        SCREENS.hotel();
        document.getElementById('hMsg').innerHTML =
          '<div class="notice ok">证明文件已上传，可以保存酒店关系了。</div>';
      } catch (err) {
        // A failed upload must not clear the chosen file.
        msg.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
        btn.disabled = false;
      }
    };
  }

  function renderResults(rows) {
    const box = document.getElementById('hResults');
    if (!rows.length) {
      box.innerHTML = '<div class="notice warn">没有找到匹配的酒店。请在下面提交新酒店资料。</div>';
      return;
    }
    hotelCandidates = rows;
    box.innerHTML = `<div class="grid three">${rows.map(candidateCard).join('')}</div>`;
    box.querySelectorAll('[data-pick]').forEach((button) => {
      button.onclick = () => {
        const picked = hotelCandidates.find((c) => c.hotel_id === button.dataset.pick);
        if (!picked) return;
        hotelDraft = {
          mode: 'EXISTING',
          hotel_id: picked.hotel_id,
          proposed_hotel: null,
          display: picked,
          relationship_type: document.getElementById('hRel').value,
        };
        renderCurrent();
        document.getElementById('hMsg').innerHTML =
          `<div class="notice ok">已选择「${esc(picked.name)}」。确认关系后点击最下方的「保存酒店关系」。</div>`;
      };
    });
  }

  document.getElementById('hRel').onchange = () => {
    if (!hotelDraft) hotelDraft = { mode: null, hotel_id: null, proposed_hotel: null, display: {}, relationship_type: '' };
    hotelDraft.relationship_type = document.getElementById('hRel').value;
    renderProof();
    renderCurrent();
  };

  document.getElementById('hSearch').onclick = async () => {
    const box = document.getElementById('hResults');
    const msg = document.getElementById('hMsg');
    msg.innerHTML = '';
    const q = document.getElementById('hQ').value.trim();
    const city = document.getElementById('hCity').value.trim();
    box.innerHTML = '<div class="notice info">正在搜索…</div>';
    try {
      const rows = unwrap(await api.hotelSearch(q, city || null)) || [];
      renderResults(rows);
    } catch (err) {
      box.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
    }
  };

  document.getElementById('hUseNew').onclick = () => {
    const name = document.getElementById('hNewName').value.trim();
    const city = document.getElementById('hNewCity').value.trim();
    const address = document.getElementById('hNewAddr').value.trim();
    const msg = document.getElementById('hMsg');
    msg.innerHTML = '';
    if (!name || !city) {
      msg.innerHTML = '<div class="notice warn">请填写酒店名称和所在城市。</div>';
      return;
    }
    hotelDraft = {
      mode: 'PROPOSED',
      hotel_id: null,
      proposed_hotel: { name, city, address },
      display: { name, city, address },
      relationship_type: document.getElementById('hRel').value,
    };
    renderCurrent();
  };

  document.getElementById('hSave').onclick = async () => {
    const msg = document.getElementById('hMsg');
    const button = document.getElementById('hSave');
    msg.innerHTML = '';
    const current = hotelDraft;
    if (!current || (!current.hotel_id && !current.proposed_hotel)) {
      msg.innerHTML = '<div class="notice warn">请先搜索并选择酒店，或提交新酒店资料。</div>';
      return;
    }
    const relationship = document.getElementById('hRel').value;
    if (!relationship) {
      msg.innerHTML = '<div class="notice warn">请选择你与这家酒店的关系。</div>';
      return;
    }
    const body = { mode: current.mode, relationship_type: relationship };
    if (current.mode === 'EXISTING') body.hotel_id = current.hotel_id;
    else body.proposed_hotel = current.proposed_hotel;
    button.disabled = true;
    try {
      await api.saveSupplierHotelClaim(body);
      await load();
      hotelDraft = draftFromSaved();
      SCREENS.hotel();
      document.getElementById('hMsg').innerHTML =
        '<div class="notice ok">酒店关系已保存。你可以继续下一步，或稍后回来修改。</div>';
    } catch (err) {
      msg.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
      button.disabled = false;
    }
  };

  renderProof();
  renderCurrent();
  if (claim.hotel_display) renderResults([claim.hotel_display].filter((c) => c && c.name));
};

/* ------------------------------------------------------------------ *
 * Step 5 — 提交审核 (submit) + the NEEDS_CHANGES loop
 *
 * This screen was a placeholder when Batch 5 closed: the API has always had
 * `POST /bff/supplier/onboarding/profile/submit`, but nothing in the workspace
 * called it, so an applicant who finished all three steps arrived at a stub. That
 * makes both the main journey and the "被退回 → 修改 → 重新提交" loop impossible
 * from the UI, so it is implemented here rather than left for later.
 *
 * The findings list is the whole point of NEEDS_CHANGES (JOURNEY S9): the reviewer
 * picked from a closed vocabulary so the applicant can be told which step to go
 * back to and why, instead of "资料不合格".
 * ------------------------------------------------------------------ */
const FINDING_TEXT = {
  LEGAL_ENTITY_MISMATCH: { text: '企业主体信息与营业执照不一致，请核对后再提交', go: 'entity' },
  LICENSE_ILLEGIBLE: { text: '营业执照图片看不清，请重新上传清晰的照片或扫描件', go: 'license' },
  LICENSE_EXPIRED: { text: '营业执照不在有效期内，请上传有效期内的执照', go: 'license' },
  RELATIONSHIP_UNPROVEN: { text: '没有看到你与这家酒店的关系证明，请补充上传', go: 'hotel' },
  PROOF_ILLEGIBLE: { text: '关系证明文件看不清，请重新上传', go: 'hotel' },
  HOTEL_INFO_MISMATCH: { text: '你填写的酒店信息与平台记录不一致，请重新选择或核对', go: 'hotel' },
  DOCUMENT_REQUIRED: { text: '审核需要你补充一份材料，请按下面的说明上传', go: 'license' },
  HOTEL_CLAIM_LOST: { text: '这家酒店的归属已判给另一方，请重新选择你经营的酒店', go: 'hotel' },
  OTHER: { text: '审核人员留下了说明，请按说明处理后重新提交', go: null },
};

function findingsBlock(findings) {
  const list = Array.isArray(findings) ? findings : [];
  if (!list.length) {
    return '<div class="notice error">资料被退回，但审核人员没有留下可执行的具体项。请直接联系 GO 客服，不要反复提交。</div>';
  }
  return list.map((f) => {
    const known = FINDING_TEXT[f?.code] || FINDING_TEXT.OTHER;
    const detail = f?.message ? `<p>${esc(f.message)}</p>` : '';
    return `<div class="finding">
      <h4>${esc(known.text)}</h4>
      ${detail}
      ${known.go ? `<button class="btn sm" type="button" data-goto="${known.go}">去修改</button>` : ''}
    </div>`;
  }).join('');
}

function submitReadyList() {
  const claim = savedClaim() || {};
  const entity = state.legalEntity || {};
  const rows = [
    ['企业主体', Boolean(entity.legal_name && entity.unified_social_credit_code), 'entity'],
    ['营业执照', Boolean(currentDocument('BUSINESS_LICENSE')), 'license'],
    ['酒店关系', Boolean(claim.relationship_type && (claim.hotel_id || claim.proposed_hotel)), 'hotel'],
  ];
  if (claim.relationship_type && claim.relationship_type !== 'OWNER') {
    const proof = proofState(claim.relationship_type);
    rows.push(['关系证明', proof.satisfied, 'hotel']);
  }
  return rows;
}

SCREENS.submit = () => {
  const root = document.getElementById('root');
  const onb = state.onboarding || {};
  const stateToken = onb.state || '';
  const busyStates = ['UNDER_REVIEW', 'VERIFIED', 'CLAIM_CONFLICT', 'CONTRACT_NEEDS_CHANGES',
    'CONTRACT_UNDER_REVIEW', 'CONTRACT_ACTIVE', 'BUSINESS_ENABLED'];

  if (busyStates.includes(stateToken)) {
    // Already in a human's hands (or past them). Saying "submit" here would invite
    // a duplicate application, so the screen becomes a status report instead.
    const rejected = stateToken === 'CLAIM_CONFLICT';
    const toContract = stateToken === 'VERIFIED' || stateToken === 'CONTRACT_NEEDS_CHANGES'
      || stateToken === 'CONTRACT_UNDER_REVIEW';
    root.innerHTML = shell({
      active: 'submit',
      lead: esc(rejected
        ? '这家酒店的归属正在人工核对。核对结束前不需要重复提交，GO 会与你联系。'
        : '资料已经提交。审核完成前你不需要再做任何操作，修改会被拒绝。'),
      body: `<div class="card">
        <div class="section-head"><h2>${esc(stateText(stateToken))}</h2>
          <span class="section-note">${rejected ? '等待人工核对' : '等待人工审核'}</span></div>
        <p class="mt-16 muted">审核由 GO 人工完成。期间你不需要重复提交；审核有结果时，这里的状态和顶部徽章都会同步更新。</p>
        <div class="actionbar">
          <div class="actionbar-note">${toContract
            ? '主体与酒店已通过审核，下一步是签署合作协议。'
            : '当前没有需要你操作的事，等审核结果即可。'}</div>
          <div class="btns">
            ${toContract ? '<button class="btn primary" id="subToContract" type="button">去签署合作合同</button>' : ''}
            <button class="btn" id="subToOverview" type="button">返回入驻概览</button>
          </div>
        </div>
      </div>`,
      aside: progressAside(),
    });
    bindShell();
    document.getElementById('subToOverview').onclick = () => (location.hash = '#/overview');
    const go = document.getElementById('subToContract');
    if (go) go.onclick = () => (location.hash = '#/contract');
    return;
  }

  const needChanges = stateToken === 'NEEDS_CHANGES';
  const rows = submitReadyList();
  const remaining = rows.filter(([, done]) => !done);
  root.innerHTML = shell({
    active: 'submit',
    lead: esc(needChanges
      ? '审核人员指出了下面这些问题。改完之后直接重新提交，不需要重新注册或重填全部内容。'
      : '提交后由 GO 人工审核主体、执照与酒店关系。审核完成前资料不能修改。'),
    body: `${needChanges ? `<div class="card">
        <div class="section-head"><h2>需要修改</h2>
          <span class="section-note">逐项列出，改完可直接重新提交</span></div>
        <div class="stack tight mt-16">${findingsBlock(onb.review_findings)}</div>
      </div>` : ''}
      <div class="card">
        <div class="section-head"><h2>提交前的检查</h2>
          <span class="section-note">四项齐备才能提交</span></div>
        <ul class="checklist mt-16">
          ${rows.map(([label, done, go]) => `<li>
            <span class="mark ${done ? 'done' : 'todo'}">${done ? '✓' : '○'}</span>
            <span>${esc(label)}${done ? ' 已完成' : ' 还没有完成'}</span>
            ${done ? '' : `<button class="btn sm" type="button" data-goto="${go}">去完成</button>`}
          </li>`).join('')}
        </ul>
        <div id="subMsg" class="mt-16"></div>
        <div class="actionbar">
          <div class="actionbar-note">${remaining.length
            ? `还有 ${remaining.length} 项没有完成，完成之后才能提交。`
            : '四项都已齐备，提交后进入人工审核。'}</div>
          <div class="btns">
            <button class="btn primary" id="subSubmit" type="button" ${remaining.length ? 'disabled' : ''}>
              ${needChanges ? '重新提交审核' : '提交审核'}
            </button>
          </div>
        </div>
      </div>`,
    aside: progressAside(),
  });
  bindShell();
  root.querySelectorAll('[data-goto]').forEach((b) => {
    b.onclick = () => { location.hash = '#/' + b.dataset.goto; };
  });
  const button = document.getElementById('subSubmit');
  if (!button) return;
  button.onclick = async () => {
    const msg = document.getElementById('subMsg');
    button.disabled = true;
    msg.innerHTML = '<div class="notice info">正在提交…</div>';
    try {
      await api.submitSupplierOnboardingProfile();
      // Re-read rather than assume: the screen must show what the server now holds.
      await load();
      SCREENS.submit();
    } catch (err) {
      msg.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
      button.disabled = false;
    }
  };
};

/* ------------------------------------------------------------------ *
 * Step 6 — 合作合同 (contract) — JOURNEY S10
 *
 * What the human has to be able to do, and does without typing any id:
 *   1. read the agreement text the platform is actually serving;
 *   2. download the same bytes;
 *   3. upload the signed scan;
 *   4. tick that they agree, and confirm.
 *
 * The confirmation sends back the sha256 of the version that was on screen. The
 * server refuses any other hash, so "I agreed to the old text" cannot be recorded
 * against a new one.
 * ------------------------------------------------------------------ */
const BLOCKER_TEXT = {
  CONTRACT_NOT_CONFIRMABLE: '合同确认现在还没有开放：需要先等人工审核通过。',
  CONTRACT_TEMPLATE_UNAVAILABLE: '合同文件暂时读不到，请联系 GO 客服。这是平台侧问题，不是你的操作问题。',
  CONTRACT_SIGNED_DOCUMENT_REQUIRED: '还需要上传已盖章的合同扫描件。',
  CONTRACT_HOTEL_REQUIRED: '这份申请还没有确定酒店，无法确认合同。请先完成酒店关系。',
};

// Object URLs are revoked when the screen is replaced; a leaked blob URL keeps the
// whole PDF in memory for the life of the tab.
let contractUrls = [];
function releaseContractUrls() {
  contractUrls.forEach((u) => { try { URL.revokeObjectURL(u); } catch {} });
  contractUrls = [];
}

function hotelSummary(hotel) {
  if (!hotel) return '<div class="notice warn">还没有确定酒店。</div>';
  // The name already has its own row above; repeating it inside "城市 / 地址" makes
  // that label wrong as well as redundant.
  const bits = [hotel.city, hotel.address].filter(Boolean).join(' · ');
  const proposed = hotel.hotel_id
    ? ''
    : '<p class="muted small">这是新提交的酒店，审核通过后才会在平台建档。</p>';
  return `<dl class="kv"><dt>酒店</dt><dd>${esc(hotel.name || '—')}</dd>
    <dt>城市 / 地址</dt><dd>${esc(bits || '—')}</dd></dl>${proposed}`;
}

SCREENS.contract = () => {
  releaseContractUrls();
  const root = document.getElementById('root');
  const c = state.contract;
  if (!c) {
    root.innerHTML = shell({
      active: 'contract',
      lead: esc('合同这一屏需要先读到你的入驻申请。'),
      body: `<div class="card">
        <div class="notice warn">没有读到入驻申请。请退出后重新登录；如果问题持续，请联系 GO 客服。</div>
        <div class="actionbar">
          <div class="actionbar-note">重新登录后通常即可恢复。</div>
          <div class="btns"><button class="btn primary" id="ctGoSubmit" type="button">返回提交审核</button></div>
        </div>
      </div>`,
      aside: progressAside(),
    });
    bindShell();
    document.getElementById('ctGoSubmit').onclick = () => (location.hash = '#/submit');
    return;
  }
  if (!c.activated && (c.blockers || []).includes('CONTRACT_NOT_CONFIRMABLE')) {
    root.innerHTML = shell({
      active: 'contract',
      lead: esc('合同这一步要等主体与酒店审核通过之后才能进行。'),
      body: `<div class="card">
        <div class="section-head"><h2>还没有到这一步</h2>
          <span class="section-note">${esc(stateText(c.state))}</span></div>
        <p class="mt-16 muted">合同只有在 GO 审核通过主体、营业执照与酒店关系之后才会开放。审核完成前你不需要做任何操作。</p>
        <div class="actionbar">
          <div class="actionbar-note">审核有结果后，这一步会自动解锁。</div>
          <div class="btns"><button class="btn primary" id="ctGoSubmit2" type="button">查看申请进度</button></div>
        </div>
      </div>`,
      aside: progressAside(),
    });
    bindShell();
    document.getElementById('ctGoSubmit2').onclick = () => (location.hash = '#/submit');
    return;
  }

  if (c.activated) {
    const conf = c.confirmation || {};
    root.innerHTML = shell({
      active: 'contract',
      lead: esc('合同已确认，经营后台已经为你的酒店开通。可以开始完善酒店资料、设置房型房价。'),
      body: `<div class="card">
          <div class="section-head"><h2>合作已生效</h2>
            <span class="section-note">合同版本 ${esc(conf.template_version || '—')}</span></div>
          <div class="notice ok mt-16">确认时间：${esc(fmtWhen(conf.confirmed_at))}。这条确认已写入不可修改的审计记录。</div>
          <div class="actionbar">
            <div class="actionbar-note">入驻流程到此结束，日常经营请到经营后台。</div>
            <div class="btns">
              <a class="btn primary" href="/supplier-console/">进入经营后台</a>
              <button class="btn" id="ctShowAgain" type="button">查看已确认的合同</button>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="section-head"><h2>已绑定的酒店</h2></div>
          <div class="mt-16">${hotelSummary(c.hotel)}</div>
        </div>
        <div class="card hidden" id="ctReShow"></div>`,
      aside: progressAside(),
    });
    bindShell();
    document.getElementById('ctShowAgain').onclick = async () => {
      const box = document.getElementById('ctReShow');
      box.classList.remove('hidden');
      box.innerHTML = '<h2>合同正文（已确认的版本）</h2><div id="ctInline"></div>';
      await openContract('inline', document.getElementById('ctInline'));
    };
    return;
  }

  const t = c.template;
  const signed = c.signed_document;
  const blockers = (c.blockers || []).filter((b) => b !== 'CONTRACT_NOT_CONFIRMABLE');
  const templateBlock = t
    ? `<dl class="kv">
        <dt>合同版本</dt><dd>${esc(t.version)}</dd>
        <dt>文件</dt><dd>${esc(t.filename)}（${fmtBytes(t.size_bytes)}）</dd>
        <dt>内容指纹</dt><dd class="mono small">${esc(String(t.sha256).slice(0, 16))}…</dd>
      </dl>
      <p class="muted small mt-12">确认时平台会核对上面的内容指纹，确保你同意的是你正在看的这一版。</p>`
    : '<div class="notice error">合同文件暂时读不到，请联系 GO 客服。</div>';
  const fixtureWarn = t && t.is_test_fixture
    ? `<div class="notice warn"><b>这是测试用合同模板，不是正式合同。</b>模板正文已明确标注 ${esc(t.marking)}，仅供本轮技术验收使用。正式对外签署前必须替换为已批准的 GO 合作协议（${esc(t.blocked_external_asset || '')}）。</div>`
    : '';

  root.innerHTML = shell({
    active: 'contract',
    lead: esc('主体与酒店审核已通过。请阅读下面的合作协议，上传已盖章的扫描件，然后确认。'),
    body: `<div class="card">
        <div class="section-head"><h2>第一步 · 阅读合作协议</h2>
          <span class="section-note">确认时以本版本为准</span></div>
        <div class="mt-16">${fixtureWarn}${templateBlock}</div>
        <div class="btns mt-16">
          <button class="btn" id="ctOpen" type="button">打开合同</button>
          <button class="btn" id="ctDownload" type="button">下载合同</button>
        </div>
        <div id="ctMsg" class="mt-12"></div>
        <div id="ctInline"></div>
      </div>

      <div class="card">
        <div class="section-head"><h2>签约双方与酒店</h2>
          <span class="section-note">合同上的双方信息</span></div>
        <div class="mt-16">${c.legal_entity
          ? `<dl class="kv">
              <dt>企业法定名称</dt><dd>${esc(c.legal_entity.legal_name)}</dd>
              <dt>统一社会信用代码</dt><dd class="mono">${esc(c.legal_entity.unified_social_credit_code)}</dd>
            </dl>`
          : '<div class="notice warn">还没有企业主体信息。</div>'}</div>
        <div class="mt-16">${hotelSummary(c.hotel)}</div>
      </div>

      <div class="card">
        <div class="section-head"><h2>第二步 · 上传已盖章的合同</h2>
          <span class="section-note">JPG / PNG / PDF，单份 ≤ 10MB</span></div>
        <div class="mt-16">${signed
          ? `<dl class="kv">
              <dt>文件名</dt><dd>${esc(signed.original_filename)}</dd>
              <dt>格式 / 大小</dt><dd>${esc(fmtType(signed.mime_type))} · ${fmtBytes(signed.size_bytes)}</dd>
              <dt>版本</dt><dd>第 ${Number(signed.revision) || 1} 版</dd>
              <dt>上传时间</dt><dd>${esc(fmtWhen(signed.uploaded_at))}</dd>
            </dl>`
          : '<div class="notice info">还没有上传盖章后的合同扫描件。</div>'}</div>
        <p class="muted small mt-16">重新上传会生成新版本，旧版本保留作为记录，审核人员与合同证据以最新版本为准。</p>
        <div class="field mt-16">
          <label for="ctFile">选择文件</label>
          <input id="ctFile" type="file" accept="image/jpeg,image/png,application/pdf,.jpg,.jpeg,.png,.pdf">
          <span class="hint">请确保盖章与签字页清晰可读。</span>
          <span class="err hidden" id="ctFileErr"></span>
        </div>
        <div class="btns mt-16">
          <button class="btn" id="ctUpload" type="button">上传盖章件</button>
        </div>
      </div>

      <div class="card">
        <div class="section-head"><h2>第三步 · 确认合同</h2>
          <span class="section-note">确认即开通经营后台</span></div>
        <div class="mt-16">${blockers.length
          ? `<div class="stack tight">${blockers.map((b) => `<div class="notice warn">${esc(BLOCKER_TEXT[b] || '还有一项没有完成。')}</div>`).join('')}</div>`
          : ''}</div>
        <label class="checkline mt-16" for="ctAgree">
          <input type="checkbox" id="ctAgree" ${c.can_confirm ? '' : 'disabled'}>
          <span>我已阅读并同意本合同（版本 <span class="mono">${esc(t ? t.version : '—')}</span>），并确认上传的盖章件与平台上的合同版本一致。</span>
        </label>
        <div id="ctConfirmMsg" class="mt-16"></div>
        <div class="actionbar">
          <div class="actionbar-note">确认后 GO 会立即为你的酒店开通经营后台。确认动作会写入不可修改的审计记录。</div>
          <div class="btns">
            <button class="btn primary" id="ctConfirm" type="button" ${c.can_confirm ? '' : 'disabled'}>确认合同</button>
          </div>
        </div>
      </div>`,
    aside: progressAside(),
  });
  bindShell();

  async function openContract(disposition, container) {
    const msg = document.getElementById('ctMsg');
    try {
      const { blob, type } = await api.supplierContractTemplateBlob(disposition);
      if (disposition === 'inline') {
        const url = URL.createObjectURL(new Blob([blob], { type: type || 'application/pdf' }));
        contractUrls.push(url);
        const host = container || document.getElementById('ctInline');
        // The frame is sized by a class, not by a style attribute: the page CSP is
        // `style-src 'self'`, so an inline style is silently dropped and the frame
        // would collapse to zero height with no error anywhere.
        host.innerHTML = `<div class="preview"><iframe class="contract-frame" title="合作合同预览" src="${url}"></iframe>
          <p class="muted small">如果上面看不到内容，请点「下载合同」后用本地阅读器打开。</p></div>`;
      } else {
        const url = URL.createObjectURL(blob);
        contractUrls.push(url);
        const a = document.createElement('a');
        a.href = url;
        a.download = t ? t.filename : 'contract.pdf';
        a.rel = 'noopener';
        document.body.appendChild(a);
        a.click();
        a.remove();
      }
      if (msg) msg.innerHTML = '';
    } catch (err) {
      // Never silently do nothing: the human pressed a button and must learn why.
      if (msg) msg.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
    }
  }
  document.getElementById('ctOpen').onclick = () => openContract('inline');
  document.getElementById('ctDownload').onclick = () => openContract('attachment');

  const fileInput = document.getElementById('ctFile');
  fileInput.onchange = () => {
    const f = fileInput.files && fileInput.files[0];
    const err = document.getElementById('ctFileErr');
    err.classList.add('hidden');
    if (!f) return;
    // Courtesy checks only; the server re-validates magic bytes, size and type.
    if (f.size > MAX_DOC_BYTES) {
      err.textContent = '文件超过 10MB，请压缩后重新选择。';
      err.classList.remove('hidden');
      return;
    }
    const type = (f.type || '').toLowerCase();
    const ext = (f.name.split('.').pop() || '').toLowerCase();
    if ((type && !ALLOWED_DOC_TYPES.includes(type)) || !['jpg', 'jpeg', 'png', 'pdf'].includes(ext)) {
      err.textContent = '文件格式不支持，请选择 JPG、PNG 或 PDF 文件。';
      err.classList.remove('hidden');
    }
  };

  document.getElementById('ctUpload').onclick = async () => {
    const msg = document.getElementById('ctMsg');
    const btn = document.getElementById('ctUpload');
    const f = fileInput.files && fileInput.files[0];
    msg.innerHTML = '';
    if (!f) {
      msg.innerHTML = '<div class="notice warn">请先选择要上传的盖章合同文件。</div>';
      return;
    }
    btn.disabled = true;
    msg.innerHTML = '<div class="notice info">正在上传并校验文件…</div>';
    try {
      // No expected_revision: the last upload is always the one that counts, and a
      // byte-identical re-upload is de-duplicated by the server rather than burning
      // a revision.
      await api.uploadSupplierDocument({ document_type: 'SIGNED_CONTRACT', scope: 'ONBOARDING' }, f);
      await load();
      SCREENS.contract();
      document.getElementById('ctMsg').innerHTML =
        '<div class="notice ok">盖章合同已上传。勾选下面的同意项后即可确认。</div>';
    } catch (err) {
      // The chosen file is deliberately kept: a refusal is not a reason to make the
      // human pick it again.
      msg.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
      btn.disabled = false;
    }
  };

  document.getElementById('ctConfirm').onclick = async () => {
    const agree = document.getElementById('ctAgree');
    const msg = document.getElementById('ctConfirmMsg');
    const btn = document.getElementById('ctConfirm');
    msg.innerHTML = '';
    if (!agree.checked) {
      // Checked here as well as on the server: the server is the boundary, but a
      // round trip to be told "you did not tick the box" is a worse experience.
      msg.innerHTML = `<div class="notice error">${esc(ERROR_TEXT.CONTRACT_AGREEMENT_REQUIRED)}</div>`;
      return;
    }
    btn.disabled = true;
    msg.innerHTML = '<div class="notice info">正在确认…</div>';
    try {
      await api.confirmSupplierContract({
        agreed: true,
        template_sha256: t.sha256,
        signed_document_id: signed ? signed.document_id : null,
      });
      await load();
      SCREENS.contract();
    } catch (err) {
      msg.innerHTML = `<div class="notice error">${esc(humanError(err))}</div>`;
      btn.disabled = false;
    }
  };
};

/* ------------------------------------------------------------------ *
 * Step 7 — 经营后台入口 — JOURNEY S11
 *
 * Shown to an activated supplier who opens the onboarding workspace again. The
 * console itself is the existing supplier console; this screen only makes sure the
 * human is told where to go and what the first thing to do is.
 * ------------------------------------------------------------------ */
SCREENS.business = () => {
  const root = document.getElementById('root');
  root.innerHTML = shell({
    active: 'contract',
    title: '入驻完成',
    lead: esc('你的酒店已经认领成功，经营后台已开通。日常经营不再需要回到这个入驻工作区。'),
    body: `<div class="card">
      <div class="section-head"><h2>入驻已完成</h2>
        <span class="section-note">经营后台已开通</span></div>
      <p class="mt-16 muted">从这里开始完善酒店资料、设置房型与房价。入驻工作区会保留，方便你随时回看合同与审核记录。</p>
      <div class="actionbar">
        <div class="actionbar-note">日常经营都在经营后台进行。</div>
        <div class="btns"><a class="btn primary" href="/supplier-console/">进入经营后台</a></div>
      </div>
    </div>`,
    aside: progressAside(),
  });
  bindShell();
};

/* Steps not yet implemented. They render an honest notice instead of pretending
   the capability exists. */
for (const key of ['review']) {
  SCREENS[key] = () => {
    const root = document.getElementById('root');
    root.innerHTML = shell({
      active: 'submit',
      lead: esc('这一步目前只有状态回看，没有额外的操作入口。'),
      body: `<div class="card">
        <div class="section-head"><h2>${esc((STEPS.find((s) => s.key === key) || {}).label || '入驻')}</h2>
          <span class="section-note">后续批次接入</span></div>
        <div class="notice info mt-16">本步骤将在后续施工批次接入。</div>
      </div>`,
      aside: progressAside(),
    });
    bindShell();
  };
}

/* ------------------------------------------------------------------ *
 * Router
 * ------------------------------------------------------------------ */
function route() {
  const hash = (location.hash || '#/').replace(/^#\/?/, '');
  if (!state.me) {
    if (hash === 'register') return SCREENS.register();
    if (hash === 'recovery') return SCREENS.recovery();
    return SCREENS.login();
  }
  if (state.me.actor_type !== 'SUPPLIER_USER') {
    const root = document.getElementById('root');
    root.innerHTML = `<main class="center-screen"><div class="card">
      <div class="notice error">${esc(ERROR_TEXT.ACCOUNT_TYPE_MISMATCH)}</div>
      <div class="btns mt-12"><button class="btn" id="onbLogout2">退出登录</button></div>
    </div></main>`;
    document.getElementById('onbLogout2').onclick = async () => { try { await api.logout(); } catch {} state.me = null; route(); };
    return;
  }
  // Landing: an applicant whose contract is confirmed has nothing left to do in
  // the onboarding workspace, so they are sent to the console entry instead of a
  // progress page that would only tell them to come back here.
  if (!hash || hash === 'login' || hash === 'register' || hash === 'recovery') {
    if ((state.onboarding || {}).business_ready) return SCREENS.business();
    return SCREENS.overview();
  }
  const screen = SCREENS[hash];
  return (screen || SCREENS.overview)();
}

window.addEventListener('hashchange', route);

(async function boot() {
  try { await load(); } catch { state.me = null; }
  route();
})();

export { api, state, route, load };
