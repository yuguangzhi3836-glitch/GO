import base64
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, session, url_for
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from project_context import PROJECT_CONTEXT
from task_routing import TaskRoutingValidationError, display_draft, validate_model_envelope, validate_task_draft

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("GOAI_DATA_DIR", os.path.join(APP_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "command-center.sqlite3")
RP_ID = os.environ.get("GOAI_RP_ID", "control.goaidirect.cn")
ORIGIN = os.environ.get("GOAI_ORIGIN", f"https://{RP_ID}")
BOOTSTRAP_TOKEN = os.environ.get("GOAI_BOOTSTRAP_TOKEN", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("GOAI_DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_INPUT_USD_PER_MILLION = float(os.environ.get("GOAI_DEEPSEEK_INPUT_USD_PER_MILLION", "1.32"))
DEEPSEEK_OUTPUT_USD_PER_MILLION = float(os.environ.get("GOAI_DEEPSEEK_OUTPUT_USD_PER_MILLION", "3.96"))
LOCAL_TZ = ZoneInfo("Asia/Shanghai")

# This application is deliberately a discussion and approval surface. Keep
# this value in code (rather than an environment toggle) so a deployment
# setting cannot accidentally turn a natural-language request into execution.
OPERATION_MODE = "command_only"
CAPABILITIES = {
    "mode": OPERATION_MODE,
    "execution_enabled": False,
    "allowed": ["discussion", "analysis", "planning", "drafting", "task_recording"],
    "blocked": ["shell", "remote_access", "deployment", "database_write", "external_system_write"],
}
# The owner chat entry and the administrator workbench are distinct authority
# surfaces.  Access to /ops is enforced server-side, never by menu visibility.
OPS_ROLES = {"admin"}

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("GOAI_SESSION_SECRET", secrets.token_urlsafe(48)),
    SESSION_COOKIE_NAME="goai_session",
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=256 * 1024,
)


def now():
    return int(time.time())


@contextmanager
def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize():
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)
    with db() as connection:
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
          created_at INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS credentials (
          credential_id BLOB PRIMARY KEY, user_id TEXT NOT NULL,
          public_key BLOB NOT NULL, sign_count INTEGER NOT NULL,
          created_at INTEGER NOT NULL, last_used_at INTEGER,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS invites (
          token_hash TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
          expires_at INTEGER NOT NULL, used_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, body TEXT NOT NULL, source TEXT NOT NULL,
          status TEXT NOT NULL, created_by TEXT NOT NULL, created_at INTEGER NOT NULL,
          confirmed_at INTEGER, confirmed_by TEXT
        );
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT, event TEXT NOT NULL,
          detail TEXT, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT,
          kind TEXT NOT NULL, body TEXT NOT NULL, sender TEXT,
          created_at INTEGER NOT NULL,
          FOREIGN KEY(task_id) REFERENCES tasks(id)
        );
        CREATE TABLE IF NOT EXISTS usage_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, model TEXT NOT NULL,
          input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
          estimated_cost_usd REAL NOT NULL, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_drafts (
          id TEXT PRIMARY KEY, source_task_id TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL, analysis_json TEXT NOT NULL,
          created_by TEXT NOT NULL, created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL, confirmed_at INTEGER,
          confirmed_by TEXT, cancelled_at INTEGER, cancelled_by TEXT,
          FOREIGN KEY(source_task_id) REFERENCES tasks(id),
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        """)


def audit(actor, event, detail=""):
    with db() as connection:
        connection.execute(
            "INSERT INTO audit(actor,event,detail,created_at) VALUES(?,?,?,?)",
            (actor, event, detail[:500], now()),
        )


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with db() as connection:
        return connection.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "authentication_required"}), 401
        g.user = user
        return view(*args, **kwargs)
    return wrapped


def can_access_ops(user):
    return user is not None and user["role"] in OPS_ROLES


def ops_required(view):
    """Server-side access control for the administrator workbench."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            abort(401)
        if not can_access_ops(user):
            abort(403)
        g.user = user
        return view(*args, **kwargs)
    return wrapped


def json_body():
    content = request.get_json(silent=True)
    if not isinstance(content, dict):
        abort(400)
    return content


def challenge_key(kind):
    return f"webauthn_{kind}_challenge"


def make_task_id():
    with db() as connection:
        count = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] + 1
    return f"GO-{count:04d}"


def make_draft_id():
    return f"DRAFT-{secrets.token_urlsafe(12)}"


def usage_summary(start_at, end_at):
    with db() as connection:
        row = connection.execute("""
            SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
            FROM usage_events WHERE created_at >= ? AND created_at < ?
        """, (start_at, end_at)).fetchone()
    return dict(row)


def local_day_start(value):
    return int(datetime(value.year, value.month, value.day, tzinfo=LOCAL_TZ).timestamp())


def deepseek_input_for_task(task_id, force_task_candidate=False):
    """Return a bounded, server-side-only conversation for the model."""
    with db() as connection:
        rows = connection.execute("""
            SELECT m.kind, m.body, u.name AS author
            FROM messages m
            LEFT JOIN users u ON u.id=m.sender
            WHERE m.id IN (
              SELECT id FROM messages ORDER BY id DESC LIMIT 24
            )
            ORDER BY m.id ASC
        """).fetchall()
    instructions = (
        "你是 GO AI 指挥中心里自然、可靠的协作助手。用简洁中文直接回答；普通聊天、"
        "测试和简单问题不需要套用检查清单或反复提示确认。"
        "当前是 COMMAND_ONLY（仅指挥）模式：每一条回复都只是讨论、分析、草案或计划，"
        "不能声称已经登录、部署、修改云服务器、数据库或任何外部系统。确认任务仅记录"
        "负责人的意图，绝不会触发执行。遇到高风险操作时，简洁列出影响和拟议动作，等待"
        "负责人确认。"
        "不要索要、复述或输出 API 密钥、密码、私钥、令牌或其他敏感信息。"
        "\n\n每次都必须只返回一个 JSON 对象，不要 Markdown，不要代码围栏。对象只能有"
        "message_type、assistant_reply、task_draft 三个键。message_type 只能是 discussion、"
        "question 或 task_candidate。discussion/question 的 task_draft 必须为 null。"
        "task_candidate 的 task_draft 必须严格包含：title、objective、task_type、scope_in、"
        "scope_out、constraints、acceptance_criteria、complexity、risk、domains、"
        "recommended_model_alias、recommended_reasoning_level、agent_plan、"
        "requires_human_approval、reason_summary。complexity 只能是 L1/L2/L3/L4；risk"
        "只能是 low/medium/high/critical；requires_human_approval 必须为 true。agent_plan"
        "必须是非空数组，且每项只含 role、objective、deliverables。模型与 Agent 选择仅是"
        "建议，绝不代表已调用其他模型或已开始执行。"
        + ("\n本次由负责人明确要求转为正式任务草稿：message_type 必须为 task_candidate。" if force_task_candidate else "")
        + "\n\n以下是必须遵守的项目大脑：\n"
        + PROJECT_CONTEXT
    )
    messages = [{"role": "system", "content": instructions}]
    for row in rows:
        content = row["body"][:6000]
        if row["kind"] == "human":
            author = row["author"] or "成员"
            messages.append({"role": "user", "content": f"{author}：{content}"})
        elif not content.startswith("GO AI 正在思考"):
            messages.append({"role": "assistant", "content": content})
    return messages


def generate_ai_reply(task_id, force_task_candidate=False):
    """Generate a reply and, only when valid, a non-executing task draft."""
    if not DEEPSEEK_API_KEY or OpenAI is None:
        return
    draft = None
    message_type = "discussion"
    try:
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
        result = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=deepseek_input_for_task(task_id, force_task_candidate),
            stream=False,
            reasoning_effort="high",
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "enabled"}},
        )
        raw_reply = (result.choices[0].message.content or "").strip()
        try:
            envelope = validate_model_envelope(json.loads(raw_reply), force_task_candidate)
            reply = envelope["assistant_reply"]
            message_type = envelope["message_type"]
            draft = envelope["task_draft"]
        except (json.JSONDecodeError, TaskRoutingValidationError):
            # A malformed model response may remain a chat reply, but it can
            # never become a formal task draft through free-text parsing.
            reply = raw_reply or "本次没有生成可显示的回复，请稍后重试。"
            if force_task_candidate:
                reply = "任务草稿格式校验未通过，尚未创建正式任务。请再次点击“转为任务”。"
                audit(None, "task_draft_validation_failed", task_id)
        usage = getattr(result, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        estimated_cost_usd = (
            input_tokens * DEEPSEEK_INPUT_USD_PER_MILLION
            + output_tokens * DEEPSEEK_OUTPUT_USD_PER_MILLION
        ) / 1_000_000
        with db() as connection:
            connection.execute(
                "INSERT INTO usage_events(task_id,model,input_tokens,output_tokens,estimated_cost_usd,created_at) VALUES(?,?,?,?,?,?)",
                (task_id, DEEPSEEK_MODEL, input_tokens, output_tokens, estimated_cost_usd, now()),
            )
            connection.execute("UPDATE tasks SET status=? WHERE id=?", (message_type, task_id))
            if draft is not None:
                source = connection.execute("SELECT created_by FROM tasks WHERE id=?", (task_id,)).fetchone()
                if source is not None:
                    connection.execute(
                        "INSERT OR IGNORE INTO task_drafts(id,source_task_id,status,analysis_json,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                        (make_draft_id(), task_id, "draft", json.dumps(draft, ensure_ascii=False, separators=(",", ":")), source["created_by"], now(), now()),
                    )
        audit(None, "deepseek_reply_generated", task_id)
        if draft is not None:
            audit(None, "task_draft_created", task_id)
    except Exception:
        reply = "GO AI 暂时无法生成回复。请稍后重试；密钥和对话内容没有显示在页面上。"
        audit(None, "deepseek_reply_failed", task_id)
    with db() as connection:
        connection.execute(
            "INSERT INTO messages(task_id,kind,body,sender,created_at) VALUES(?,?,?,?,?)",
            (task_id, "assistant", reply[:24000], None, now()),
        )


initialize()


@app.after_request
def security_headers(response):
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.get("/")
def index():
    return render_template("chat_owner.html", user=current_user())


@app.get("/ops")
@ops_required
def ops_index():
    return render_template("ops_index.html", user=g.user)


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "mode": OPERATION_MODE, "execution_enabled": False})


@app.get("/setup/<token>")
def setup(token):
    if not BOOTSTRAP_TOKEN or not secrets.compare_digest(token, BOOTSTRAP_TOKEN):
        abort(404)
    return render_template("setup.html", token=token)


@app.get("/invite/<token>")
def invite(token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with db() as connection:
        record = connection.execute("SELECT * FROM invites WHERE token_hash=? AND used_at IS NULL AND expires_at>?", (token_hash, now())).fetchone()
    if not record:
        abort(404)
    return render_template("invite.html", token=token, name=record["name"])


@app.post("/api/invite/register/options")
def invite_options():
    body = json_body()
    token = body.get("token", "")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with db() as connection:
        record = connection.execute("SELECT * FROM invites WHERE token_hash=? AND used_at IS NULL AND expires_at>?", (token_hash, now())).fetchone()
    if not record:
        return jsonify({"error": "invite_invalid"}), 404
    user_id = secrets.token_urlsafe(18)
    session["pending_setup"] = {"user_id": user_id, "name": record["name"], "role": record["role"], "invite_hash": token_hash, "expires": now() + 300}
    options = generate_registration_options(
        rp_id=RP_ID, rp_name="GO AI 指挥中心", user_id=user_id.encode(),
        user_name=record["name"], user_display_name=record["name"],
        authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.PREFERRED, user_verification=UserVerificationRequirement.REQUIRED),
    )
    session[challenge_key("registration")] = bytes_to_base64url(options.challenge)
    return options_to_json(options), 200, {"Content-Type": "application/json"}


@app.post("/api/setup/register/options")
def setup_options():
    body = json_body()
    token = body.get("token", "")
    name = body.get("name", "").strip()
    if not BOOTSTRAP_TOKEN or not secrets.compare_digest(token, BOOTSTRAP_TOKEN) or not 1 <= len(name) <= 48:
        abort(400)
    with db() as connection:
        if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return jsonify({"error": "already_initialized"}), 409
    user_id = secrets.token_urlsafe(18)
    session["pending_setup"] = {"user_id": user_id, "name": name, "expires": now() + 300}
    options = generate_registration_options(
        rp_id=RP_ID,
        rp_name="GO AI 指挥中心",
        user_id=user_id.encode(),
        user_name=name,
        user_display_name=name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    session[challenge_key("registration")] = bytes_to_base64url(options.challenge)
    return options_to_json(options), 200, {"Content-Type": "application/json"}


@app.post("/api/setup/register/verify")
def setup_verify():
    pending = session.get("pending_setup", {})
    challenge = session.get(challenge_key("registration"))
    if not pending or pending.get("expires", 0) < now() or not challenge:
        return jsonify({"error": "registration_expired"}), 400
    try:
        verification = verify_registration_response(
            credential=json_body(),
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=RP_ID,
            expected_origin=ORIGIN,
            require_user_verification=True,
        )
    except Exception:
        return jsonify({"error": "registration_failed"}), 400
    with db() as connection:
        connection.execute("INSERT INTO users(id,name,role,created_at) VALUES(?,?,?,?)", (pending["user_id"], pending["name"], pending.get("role", "owner"), now()))
        connection.execute("INSERT INTO credentials(credential_id,user_id,public_key,sign_count,created_at) VALUES(?,?,?,?,?)", (verification.credential_id, pending["user_id"], verification.credential_public_key, verification.sign_count, now()))
        if pending.get("invite_hash"):
            connection.execute("UPDATE invites SET used_at=? WHERE token_hash=? AND used_at IS NULL", (now(), pending["invite_hash"]))
    session.clear()
    session["user_id"] = pending["user_id"]
    session.permanent = True
    audit(pending["user_id"], "owner_registered", pending["name"])
    return jsonify({"ok": True})


@app.post("/api/auth/options")
def auth_options():
    with db() as connection:
        credentials = connection.execute("SELECT credential_id FROM credentials").fetchall()
    if not credentials:
        return jsonify({"error": "not_initialized"}), 409
    options = generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=[PublicKeyCredentialDescriptor(id=row["credential_id"]) for row in credentials],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    session[challenge_key("authentication")] = bytes_to_base64url(options.challenge)
    return options_to_json(options), 200, {"Content-Type": "application/json"}


@app.post("/api/auth/verify")
def auth_verify():
    challenge = session.get(challenge_key("authentication"))
    body = json_body()
    credential_id = body.get("rawId", "")
    if not challenge or not credential_id:
        return jsonify({"error": "authentication_expired"}), 400
    try:
        key = base64url_to_bytes(credential_id)
    except Exception:
        abort(400)
    with db() as connection:
        record = connection.execute("SELECT c.*, u.active FROM credentials c JOIN users u ON u.id=c.user_id WHERE c.credential_id=?", (key,)).fetchone()
    if not record or not record["active"]:
        return jsonify({"error": "credential_unknown"}), 401
    try:
        verification = verify_authentication_response(
            credential=body,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=RP_ID,
            expected_origin=ORIGIN,
            credential_public_key=record["public_key"],
            credential_current_sign_count=record["sign_count"],
            require_user_verification=True,
        )
    except Exception:
        return jsonify({"error": "authentication_failed"}), 401
    with db() as connection:
        connection.execute("UPDATE credentials SET sign_count=?, last_used_at=? WHERE credential_id=?", (verification.new_sign_count, now(), key))
    session.clear()
    session["user_id"] = record["user_id"]
    session.permanent = True
    audit(record["user_id"], "login")
    return jsonify({"ok": True})


@app.post("/api/logout")
def logout():
    user = current_user()
    if user:
        audit(user["id"], "logout")
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
@login_required
def me():
    return jsonify({
        "name": g.user["name"],
        "role": g.user["role"],
        "can_access_ops": can_access_ops(g.user),
    })


@app.get("/api/usage/summary")
@login_required
def usage_summary_api():
    current = datetime.now(LOCAL_TZ)
    today_start = local_day_start(current)
    month_start = local_day_start(current.replace(day=1))
    return jsonify({
        "today": usage_summary(today_start, now()),
        "month": usage_summary(month_start, now()),
        "currency": "USD",
        "basis": "peak_rate_estimate",
    })


@app.get("/api/capabilities")
@login_required
def capabilities():
    """Expose the enforced boundary to signed-in owners and the UI."""
    return jsonify(CAPABILITIES)


@app.get("/api/tasks")
@login_required
def tasks():
    with db() as connection:
        rows = connection.execute("SELECT t.*, u.name AS author FROM tasks t JOIN users u ON u.id=t.created_by ORDER BY t.created_at DESC LIMIT 50").fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/api/conversation")
@login_required
def conversation():
    with db() as connection:
        rows = connection.execute("""
            SELECT m.*, t.status, u.name AS author,
                   d.id AS draft_id, d.status AS draft_status, d.analysis_json AS draft_analysis_json
            FROM messages m
            LEFT JOIN tasks t ON t.id=m.task_id
            LEFT JOIN users u ON u.id=m.sender
            LEFT JOIN task_drafts d ON d.source_task_id=m.task_id
            ORDER BY m.created_at ASC, m.id ASC LIMIT 200
        """).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        raw_draft = item.pop("draft_analysis_json", None)
        draft_id = item.pop("draft_id", None)
        draft_status = item.pop("draft_status", None)
        if draft_id and raw_draft:
            try:
                item["task_draft"] = {
                    "id": draft_id,
                    "status": draft_status,
                    "analysis": display_draft(json.loads(raw_draft)),
                }
            except (json.JSONDecodeError, TaskRoutingValidationError):
                item["task_draft"] = None
        else:
            item["task_draft"] = None
        result.append(item)
    return jsonify(result)


@app.get("/api/events")
@login_required
def events():
    def stream():
        last_marker = None
        # Gunicorn has a 30-second worker timeout.  Keep each SSE response
        # deliberately shorter, then let EventSource reconnect automatically.
        # This prevents an otherwise healthy idle chat tab from tying up (and
        # eventually timing out) a worker.
        deadline = time.monotonic() + 20
        yield "retry: 2500\n\n"
        while time.monotonic() < deadline:
            with db() as connection:
                marker = connection.execute("SELECT COALESCE(MAX(id),0) FROM messages").fetchone()[0]
            if marker != last_marker:
                last_marker = marker
                yield f"data: {marker}\n\n"
            else:
                yield ": keepalive\n\n"
            time.sleep(2)
    return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/tasks")
@login_required
def create_task():
    body = json_body()
    text = body.get("body", "").strip()
    source = body.get("source", "manual")
    if not 1 <= len(text) <= 12000 or source not in {"manual", "gpt_paste"}:
        abort(400)
    task_id = make_task_id()
    with db() as connection:
        connection.execute("INSERT INTO tasks(id,body,source,status,created_by,created_at) VALUES(?,?,?,?,?,?)", (task_id, text, source, "classifying", g.user["id"], now()))
        connection.execute("INSERT INTO messages(task_id,kind,body,sender,created_at) VALUES(?,?,?,?,?)", (task_id, "human", text, g.user["id"], now()))
    audit(g.user["id"], "task_created", task_id)
    if DEEPSEEK_API_KEY and OpenAI is not None:
        threading.Thread(target=generate_ai_reply, args=(task_id,), daemon=True).start()
    return jsonify({"id": task_id, "status": "classifying"}), 201


@app.post("/api/tasks/<task_id>/convert-to-task")
@login_required
def convert_to_task(task_id):
    """Explicit human fallback: generate a draft for an existing message."""
    with db() as connection:
        source = connection.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone()
        message = connection.execute("SELECT id FROM messages WHERE task_id=? AND kind='human'", (task_id,)).fetchone()
        draft = connection.execute("SELECT id FROM task_drafts WHERE source_task_id=?", (task_id,)).fetchone()
        if source is None or message is None:
            abort(404)
        if draft is not None:
            return jsonify({"error": "task_draft_already_exists", "id": draft["id"]}), 409
        connection.execute("UPDATE tasks SET status='task_candidate' WHERE id=?", (task_id,))
        connection.execute(
            "INSERT INTO messages(task_id,kind,body,sender,created_at) VALUES(?,?,?,?,?)",
            (task_id, "assistant", "正在按负责人要求生成正式任务草稿…", None, now()),
        )
    audit(g.user["id"], "task_draft_requested", task_id)
    if DEEPSEEK_API_KEY and OpenAI is not None:
        threading.Thread(target=generate_ai_reply, args=(task_id, True), daemon=True).start()
        return jsonify({"id": task_id, "status": "task_candidate"}), 202
    return jsonify({"error": "model_unavailable"}), 503


@app.patch("/api/task-drafts/<draft_id>")
@login_required
def update_task_draft(draft_id):
    body = json_body()
    try:
        analysis = validate_task_draft(body.get("analysis"))
    except TaskRoutingValidationError as error:
        return jsonify({"error": str(error)}), 400
    with db() as connection:
        result = connection.execute(
            "UPDATE task_drafts SET analysis_json=?, updated_at=? WHERE id=? AND status='draft'",
            (json.dumps(analysis, ensure_ascii=False, separators=(",", ":")), now(), draft_id),
        )
    if result.rowcount != 1:
        return jsonify({"error": "task_draft_not_editable"}), 409
    audit(g.user["id"], "task_draft_updated", draft_id)
    return jsonify({"ok": True, "analysis": analysis})


@app.post("/api/task-drafts/<draft_id>/confirm")
@login_required
def confirm_task_draft(draft_id):
    with db() as connection:
        record = connection.execute("SELECT source_task_id FROM task_drafts WHERE id=? AND status='draft'", (draft_id,)).fetchone()
        if record is None:
            return jsonify({"error": "task_draft_not_confirmable"}), 409
        connection.execute(
            "UPDATE task_drafts SET status='confirmed', confirmed_at=?, confirmed_by=?, updated_at=? WHERE id=?",
            (now(), g.user["id"], now(), draft_id),
        )
        connection.execute("UPDATE tasks SET status='confirmed' WHERE id=?", (record["source_task_id"],))
        connection.execute(
            "INSERT INTO messages(task_id,kind,body,sender,created_at) VALUES(?,?,?,?,?)",
            (record["source_task_id"], "assistant", "任务草稿已确认并记录。当前仍为指挥模式，不会触发任何执行。", None, now()),
        )
    audit(g.user["id"], "task_draft_confirmed", draft_id)
    return jsonify({"ok": True, "execution_enabled": False})


@app.post("/api/task-drafts/<draft_id>/cancel")
@login_required
def cancel_task_draft(draft_id):
    with db() as connection:
        record = connection.execute("SELECT source_task_id FROM task_drafts WHERE id=? AND status='draft'", (draft_id,)).fetchone()
        if record is None:
            return jsonify({"error": "task_draft_not_cancellable"}), 409
        connection.execute(
            "UPDATE task_drafts SET status='cancelled', cancelled_at=?, cancelled_by=?, updated_at=? WHERE id=?",
            (now(), g.user["id"], now(), draft_id),
        )
        connection.execute("UPDATE tasks SET status='discussion' WHERE id=?", (record["source_task_id"],))
        connection.execute(
            "INSERT INTO messages(task_id,kind,body,sender,created_at) VALUES(?,?,?,?,?)",
            (record["source_task_id"], "assistant", "任务草稿已取消；原始聊天记录保留，未触发任何执行。", None, now()),
        )
    audit(g.user["id"], "task_draft_cancelled", draft_id)
    return jsonify({"ok": True})


@app.post("/api/tasks/<task_id>/confirm")
@login_required
def confirm_task(task_id):
    with db() as connection:
        result = connection.execute("UPDATE tasks SET status='approved', confirmed_at=?, confirmed_by=? WHERE id=? AND status='received'", (now(), g.user["id"], task_id))
        if result.rowcount == 1:
            connection.execute("INSERT INTO messages(task_id,kind,body,sender,created_at) VALUES(?,?,?,?,?)", (task_id, "assistant", f"{task_id} 已由负责人确认。执行器尚未启用，不会自动修改任何环境。", None, now()))
    if result.rowcount != 1:
        return jsonify({"error": "task_not_confirmable"}), 409
    audit(g.user["id"], "task_approved", task_id)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8080")))
