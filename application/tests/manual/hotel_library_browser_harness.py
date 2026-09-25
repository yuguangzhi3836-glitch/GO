"""Isolated browser acceptance fixture, never a production application entrypoint.

Run with PYTHONPATH=src python tests/manual/hotel_library_browser_harness.py.
Serves localhost:8765; Ctrl-C ends the fixture. All database/media data live in a
fresh temporary directory. Authentication is overridden ONLY in this test app.
The supplier component is sliced verbatim from the current candidate app.js.
This proves component/route integration, not full-shell or login acceptance.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
TEMP = tempfile.TemporaryDirectory(prefix="go-hotel-browser-fixture-")
DATA = Path(TEMP.name)
os.environ["DATABASE_URL"] = f"sqlite:///{DATA / 'fixture.sqlite3'}"
os.environ["GO_MEDIA_CACHE_DIR"] = str(DATA / "media")

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from PIL import Image
from go_hotel.api.routes import hotel_partner_core as candidate_api
from go_hotel.db.models import Base
from go_hotel.db.session import engine
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as core

Base.metadata.create_all(engine)
SUPPLIER = "synthetic-browser-supplier"
ACTOR = "synthetic-browser-owner"
hotels = []
for label in ("验收酒店甲", "验收酒店乙"):
    hotel = core.create_property(SUPPLIER, ACTOR, {"name_zh": label, "property_type": "HOTEL", "contacts": {"phone": "000-TEST"}})
    for name in ("标准大床房", "景观套房"):
        core.create_room_type(SUPPLIER, ACTOR, hotel["property_id"], {
            "name_zh": name, "physical_room_count": 5,
            "occupancy": {"max_occupancy": 2, "max_adults": 2, "max_children": 0},
        })
    hotels.append(hotel)

app = FastAPI(title="GO isolated supplier browser acceptance fixture")
app.include_router(candidate_api.router)
app.dependency_overrides[candidate_api.supplier_principal] = lambda: SimpleNamespace(supplier_id=SUPPLIER, user_id=ACTOR)
requests = []


@app.middleware("http")
async def record_request(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/v1/"):
        requests.append({"method": request.method, "path": request.url.path, "status": response.status_code})
    return response


def component_source():
    source = (ROOT / "frontend/shared/app.js").read_text()
    marker = "// Hotel selection is scoped"
    start = source.find(marker)
    if start < 0:
        start = source.index("const HOTEL_IMPORT_FIELDS=")
    end = source.index("async function supplierPropertyProfile()", start)
    return source[start:end], hashlib.sha256(source.encode()).hexdigest()


@app.get("/", response_class=HTMLResponse)
def page():
    _, digest = component_source()
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>GO 酒店资料候选验收</title>
<style>body{font:16px/1.6 system-ui;margin:20px auto;max-width:1100px;padding:0 16px;background:#f5f5f3;color:#202528}*{box-sizing:border-box}.card{background:white;border:1px solid #ddd;padding:18px;margin:14px 0;border-radius:8px}label{display:block;margin:10px 0}input:not([type=checkbox]),select,textarea{font:inherit;max-width:100%;padding:8px}textarea{width:100%}button,.btn{font:inherit;padding:9px 14px;margin:6px 8px 6px 0;cursor:pointer}button:disabled{opacity:.5}pre{white-space:pre-wrap;overflow-wrap:anywhere}img{max-width:100%}.fixture{background:#fff7d8;border:1px solid #ddc877;padding:12px}#notice{color:#9d3500}.structured-body{min-width:0}</style>
<div class="fixture">隔离候选组件验收：仅使用两家合成酒店和测试图片，真实服务路由；身份验证使用测试依赖替身，不代表完整应用登录验收。<details><summary>源码身份</summary><code>""" + digest + """</code></details></div>
<h1>酒店信息库</h1><label>验收酒店切换<select id="supplierPropertySelect"></select></label><div id="notice" role="alert"></div>
<details><summary>测试资料</summary><p>复制以下资料到导入框；映射到所选酒店已有房型。</p><pre id="fixturePackage"></pre><a href="/fixture-image.jpg" download="synthetic-1600x900.jpg">下载合成高清测试图（1600×900）</a></details><main id="view"></main>
<script>
const $=selector=>document.querySelector(selector);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const unwrap=x=>x?.data??x;
const supplierFriendlyValue=value=>({DRAFT:'草稿',PUBLISHED:'已发布',ACTIVE:'正常'}[value]||String(value??''));
const supplierStructuredShell=(_route,body)=>'<div class="structured-body">'+body+'</div>';
const notice=(message)=>{$('#notice').textContent=String(message)};
const api={request:async(url,options={})=>{const init={method:options.method||'GET',headers:{...options.headers}};if(options.body!==undefined){init.headers['Content-Type']='application/json';init.body=JSON.stringify(options.body)}const response=await fetch(url,init);const body=await response.json();if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));return body}};
const state={};let currentSupplierRoute='/one-click-build';
async function route(){await supplierOneClickBuild()}
$('#fixturePackage').textContent=JSON.stringify({hotel:{name_zh:'酒店自主选择的新名称',contacts:{phone:'000-NEW-TEST'}},room_types:[{source_room_id:'synthetic-ctrip-room-1',name_zh:'来源景观大床房',physical_room_count:5,occupancy:{max_occupancy:2,max_adults:2,max_children:0}}]},null,2);
</script><script src="/candidate-component.js"></script><script>route().catch(e=>notice(e.stack||e.message))</script></html>"""


@app.get("/candidate-component.js")
def javascript():
    code, _ = component_source()
    return Response(code, media_type="text/javascript", headers={"Cache-Control": "no-store"})


@app.get("/fixture-image.jpg")
def fixture_image():
    stream = io.BytesIO()
    image = Image.new("RGB", (1600, 900), (110, 145, 167))
    image.save(stream, "JPEG", quality=92)
    return Response(stream.getvalue(), media_type="image/jpeg")


@app.get("/fixture-state")
def fixture_state():
    _, digest = component_source()
    return {"synthetic": True, "authentication": "TEST_DEPENDENCY_OVERRIDE", "app_js_sha256": digest,
            "hotels": [core.graph(SUPPLIER, item["property_id"]) for item in hotels], "requests": requests}


if __name__ == "__main__":
    import uvicorn
    print(json.dumps({"url": "http://127.0.0.1:8765", "synthetic": True, "properties": [item["property_id"] for item in hotels]}, ensure_ascii=False), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8765)
