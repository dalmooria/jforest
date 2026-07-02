"""Vercel serverless 진입점 (ASGI) — 날짜별 예약오픈 안내.

⚠ 경량: `jforest.rag`(torch/qdrant) 절대 import 금지. `jforest.fcfs_report`만 사용
   (re/unicodedata/datetime만 의존) → 함수 번들이 Vercel 한도 안에 들어온다.

읽기 데이터는 번들된 `api/serving.sqlite`(약 2MB, 읽기전용). 로컬 파이프라인이
`jforest export-serving`으로 갱신 → git push → 자동 재배포.
"""
import os
import sqlite3
import sys
from datetime import date, timedelta

try:
    from zoneinfo import ZoneInfo
    _KST = ZoneInfo("Asia/Seoul")
except Exception:  # zoneinfo 데이터 없을 때(드묾) UTC+9 근사
    from datetime import timezone
    _KST = timezone(timedelta(hours=9))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402

from jforest.fcfs_report import build_open_report  # noqa: E402

SERVING_DB = os.path.join(os.path.dirname(__file__), "serving.sqlite")

app = FastAPI(title="jforest open-report")


def _conn() -> sqlite3.Connection:
    if not os.path.exists(SERVING_DB):
        raise HTTPException(503, "serving.sqlite 미배포 — export-serving 필요")
    conn = sqlite3.connect(f"file:{SERVING_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _today_kst() -> date:
    from datetime import datetime
    return datetime.now(_KST).date()


def _generated_at(conn):
    try:
        row = conn.execute(
            "SELECT value FROM serving_meta WHERE key='generated_at'"
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


@app.get("/api/open-report")
def open_report(date_str: str = Query(None, alias="date"),
                region: str = Query(None)) -> dict:
    on_date = _today_kst()
    if date_str:
        try:
            on_date = date.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(400, "date 형식 오류 (YYYY-MM-DD)")
    conn = _conn()
    try:
        rep = build_open_report(conn, on_date)
        rep["generated_at"] = _generated_at(conn)
    finally:
        conn.close()
    if region:  # 지역 필터(서버측)
        for g in rep["groups"]:
            g["events"] = [e for e in g["events"] if e["region"] == region]
            g["count"] = len(g["events"])
        rep["groups"] = [g for g in rep["groups"] if g["count"]]
        rep["uncertain"] = [u for u in rep["uncertain"] if u["region"] == region]
        rep["total"] = sum(g["count"] for g in rep["groups"])
    return rep


@app.get("/api/health")
def health() -> dict:
    conn = _conn()
    try:
        return {"ok": True, "generated_at": _generated_at(conn)}
    finally:
        conn.close()


@app.get("/open", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _HTML


_HTML = """<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>날짜별 예약오픈 안내 · 자연휴양림</title>
<style>
  :root { --bd:#e2e2e6; --mut:#666; --accent:#0a84ff; --bg:#f7f7f8; }
  * { box-sizing: border-box; }
  body { font-family:-apple-system,system-ui,'Segoe UI',sans-serif; margin:0;
         background:var(--bg); color:#1d1d1f; padding:16px;
         padding-bottom:calc(24px + env(safe-area-inset-bottom)); }
  .wrap { max-width:760px; margin:0 auto; }
  h1 { font-size:1.15rem; margin:.2rem 0 .1rem; }
  .meta { color:var(--mut); font-size:.75rem; margin-bottom:12px; }
  .bar { display:flex; gap:8px; align-items:center; flex-wrap:wrap;
         position:sticky; top:0; background:var(--bg); padding:8px 0; z-index:5; }
  .bar button, .bar input, .bar select { font-size:16px; min-height:44px; border:1px solid #ccc;
         border-radius:10px; background:#fff; padding:0 12px; }
  .bar button { min-width:44px; cursor:pointer; }
  #date { flex:1; min-width:150px; }
  .hd { font-size:1rem; font-weight:700; margin:6px 0; }
  .grp { margin:16px 0 6px; font-weight:700; color:#1d1d1f; border-bottom:2px solid var(--bd);
         padding-bottom:4px; }
  .sub { font-size:.8rem; color:var(--mut); margin:10px 0 4px; }
  .cards { display:grid; grid-template-columns:1fr; gap:8px; }
  @media (min-width:768px){ .cards { grid-template-columns:1fr 1fr; } h1{font-size:1.35rem;} }
  .card { background:#fff; border:1px solid var(--bd); border-radius:12px; padding:12px 14px; }
  .card .nm { font-weight:600; }
  .card .rg { color:var(--mut); font-size:.8rem; }
  .row2 { margin-top:6px; display:flex; gap:6px; flex-wrap:wrap; align-items:center; font-size:.85rem; }
  .badge { border-radius:999px; padding:2px 8px; font-size:.75rem; }
  .b-type { background:#eef4ff; color:#0a5; color:#0a52c4; }
  .b-time { background:#f0f0f2; color:#333; }
  .b-est { background:#fff4e5; color:#a25b00; }
  .b-unk { background:#fdecec; color:#b3261e; }
  .fac { display:inline-flex; gap:4px; }
  .f { border-radius:6px; padding:1px 6px; font-size:.72rem; }
  .fO { background:#e5f5e8; color:#1a7f37; } .fX { background:#eee; color:#777; }
  .fT { background:#fff6d6; color:#8a6d00; }
  .resv { color:var(--mut); font-size:.8rem; margin-top:4px; }
  details { margin-top:14px; } summary { cursor:pointer; color:var(--mut); font-size:.85rem; }
  .note { margin-top:16px; font-size:.75rem; color:var(--mut); border-top:1px dashed var(--bd); padding-top:8px; }
  .empty { color:var(--mut); padding:20px 0; text-align:center; line-height:1.6; }
  .upwrap { margin:8px 0 4px; }
  .uptitle { font-size:.8rem; color:var(--mut); margin-bottom:6px; }
  .ups { display:flex; gap:8px; overflow-x:auto; padding-bottom:4px; -webkit-overflow-scrolling:touch; }
  .up { flex:0 0 auto; min-height:44px; display:flex; flex-direction:column; justify-content:center;
        background:#fff; border:1px solid var(--bd); border-radius:12px; padding:8px 12px;
        text-decoration:none; color:#1d1d1f; font-size:.78rem; }
  .up b { font-weight:700; margin:2px 0; }
  .up span { color:var(--accent); font-weight:700; font-size:.72rem; }
</style></head>
<body><div class="wrap">
  <h1>🌲 날짜별 예약오픈 안내</h1>
  <div class="meta" id="meta"></div>
  <div class="bar">
    <button id="prev" aria-label="이전날">◀</button>
    <input type="date" id="date">
    <button id="next" aria-label="다음날">▶</button>
    <select id="region"><option value="">전체 지역</option></select>
  </div>
  <div id="out"><div class="empty">불러오는 중…</div></div>
  <div class="note">정책·공사 기반 안내이며 실시간 잔여석과 다를 수 있습니다.</div>
</div>
<script>
const SIDO=["경기·인천","강원","충북","충남·대전","전북","전남·광주","경북·대구","경남·부산·울산","제주"];
const $=id=>document.getElementById(id);
const rsel=$('region');
SIDO.forEach(s=>{const o=document.createElement('option');o.value=s;o.textContent=s;rsel.appendChild(o);});
function kstToday(){const d=new Date(Date.now()+9*3600*1000);return d.toISOString().slice(0,10);}
$('date').value=kstToday();
function fmtFac(v){return v==='O'?'fO':v==='X'?'fX':'fT';}
function card(e){
  return `<div class="card"><div class="nm">${e.name} <span class="rg">${e.region}</span></div>
    <div class="row2">
      <span class="badge b-type">${e.type_label}</span>
      <span class="badge b-time">${e.open_time||'시각 미상'}</span>
      ${e.confidence==='추정'?'<span class="badge b-est">추정</span>':''}
      ${e.confidence==='미상'?'<span class="badge b-unk">일정 확인</span>':''}
      <span class="fac"><span class="f ${fmtFac(e.water_play)}">물${e.water_play}</span>
      <span class="f ${fmtFac(e.barbecue)}">바${e.barbecue}</span>
      <span class="f ${fmtFac(e.forest_guide)}">숲${e.forest_guide}</span></span>
    </div><div class="resv">${e.reservable_label}</div></div>`;
}
function section(title, evs){
  if(!evs.length) return '';
  return `<div class="sub">${title} (${evs.length})</div><div class="cards">${evs.map(card).join('')}</div>`;
}
function upcomingHtml(u){
  if(!u||!u.length) return '';
  const chips=u.map(x=>`<a class="up" href="#" data-d="${x.date}">${x.label}<b>${x.date.slice(5).replace('-','/')} (${x.weekday})</b><span>D-${x.dday} · ${x.open_time}</span></a>`).join('');
  return `<div class="upwrap"><div class="uptitle">📅 다가오는 주요 오픈 (탭하면 이동)</div><div class="ups">${chips}</div></div>`;
}
function render(rep){
  $('meta').textContent = `${rep.date} (${rep.weekday}) · 총 ${rep.total}곳`
    + (rep.generated_at?` · 최종 갱신 ${rep.generated_at.slice(0,10)}`:'');
  let h=upcomingHtml(rep.upcoming);
  if(rep.total===0) h+='<div class="empty">이 날짜엔 예약이 열리는 휴양림이 없어요.<br>위 <b>다가오는 주요 오픈</b>을 탭해 확인하세요.</div>';
  for(const g of rep.groups){
    h+=`<div class="grp">${g.type_group}</div>`;
    if(g.type_group==='선착순'){
      const today=g.events.filter(e=>e.kind!=='weekly');
      const weekly=g.events.filter(e=>e.kind==='weekly');
      h+=section('★ 오늘 지정 오픈', today);
      if(weekly.length) h+=`<details><summary>매주 반복 오픈 ${weekly.length}곳 (참고)</summary><div class="cards">${weekly.map(card).join('')}</div></details>`;
    } else {
      h+=`<div class="cards">${g.events.map(card).join('')}</div>`;
    }
  }
  if(rep.uncertain&&rep.uncertain.length){
    h+=`<details><summary>⚠ 일정 확인 필요 ${rep.uncertain.length}곳 (자동 파싱 불가)</summary><div class="cards">`
      +rep.uncertain.map(u=>`<div class="card"><div class="nm">${u.name} <span class="rg">${u.region}</span></div>
        <div class="row2"><span class="badge b-type">${u.type_label}</span><span class="badge b-unk">일정 확인</span></div></div>`).join('')
      +`</div></details>`;
  }
  h+=`<div class="note">${rep.seasonal_note}</div>`;
  $('out').innerHTML=h;
}
async function load(){
  $('out').innerHTML='<div class="empty">불러오는 중…</div>';
  const p=new URLSearchParams({date:$('date').value});
  if(rsel.value) p.set('region',rsel.value);
  try{
    const r=await fetch('/api/open-report?'+p);
    if(!r.ok) throw new Error('HTTP '+r.status);
    render(await r.json());
  }catch(err){ $('out').innerHTML='<div class="empty">오류: '+err.message+'</div>'; }
}
function shift(days){const d=new Date($('date').value);d.setDate(d.getDate()+days);$('date').value=d.toISOString().slice(0,10);load();}
$('prev').onclick=()=>shift(-1); $('next').onclick=()=>shift(1);
$('date').onchange=load; rsel.onchange=load;
$('out').addEventListener('click',e=>{
  const a=e.target.closest('.up'); if(!a) return;
  e.preventDefault(); $('date').value=a.dataset.d; load();
  window.scrollTo(0,0);
});
load();
</script>
</body></html>
"""
