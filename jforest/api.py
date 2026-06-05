from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator

from jforest.rag import RagAnswer, answer_question

CHAT_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>숲나들e 안내 에이전트</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 760px;
         margin: 0 auto; padding: 16px; background: #f7f7f8; color: #1d1d1f; }
  h1 { font-size: 1.2rem; }
  #log { display: flex; flex-direction: column; gap: 12px; margin-bottom: 96px; }
  .msg { padding: 12px 14px; border-radius: 12px; white-space: pre-wrap; line-height: 1.5; }
  .user { background: #0a84ff; color: #fff; align-self: flex-end; max-width: 80%; }
  .bot { background: #fff; border: 1px solid #e2e2e6; align-self: flex-start; max-width: 92%; }
  .evidence { margin-top: 8px; font-size: 0.8rem; color: #666; border-top: 1px dashed #ddd; padding-top: 6px; }
  .evidence div { margin: 2px 0; }
  form { position: fixed; bottom: 0; left: 0; right: 0; display: flex; gap: 8px;
         padding: 12px; background: #f7f7f8; border-top: 1px solid #e2e2e6; }
  form > * { font-size: 1rem; }
  input { flex: 1; padding: 10px 12px; border: 1px solid #ccc; border-radius: 10px; }
  button { padding: 10px 18px; border: 0; border-radius: 10px; background: #0a84ff; color: #fff; cursor: pointer; }
  button:disabled { opacity: 0.5; cursor: default; }
</style>
</head>
<body>
<h1>🌲 숲나들e 안내 에이전트 (PoC)</h1>
<div id="log"></div>
<form id="form">
  <input id="q" autocomplete="off" placeholder="예: 장애인 할인이 되는 휴양림 알려줘" autofocus>
  <button id="send" type="submit">질문</button>
</form>
<script>
const log = document.getElementById('log');
const form = document.getElementById('form');
const input = document.getElementById('q');
const send = document.getElementById('send');

function bubble(text, cls) {
  const el = document.createElement('div');
  el.className = 'msg ' + cls;
  el.textContent = text;
  log.appendChild(el);
  window.scrollTo(0, document.body.scrollHeight);
  return el;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = input.value.trim();
  if (!question) return;
  bubble(question, 'user');
  input.value = '';
  send.disabled = true;
  const pending = bubble('답변 생성 중…', 'bot');
  try {
    const resp = await fetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question })
    });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    pending.textContent = data.answer || '(빈 답변)';
    if (data.evidence && data.evidence.length) {
      const ev = document.createElement('div');
      ev.className = 'evidence';
      data.evidence.forEach((d, i) => {
        const row = document.createElement('div');
        const forest = d.instt_name ? d.instt_name + ' · ' : '';
        const title = d.title_or_name || d.doc_type;
        row.textContent = `[${i+1}] ${forest}${title} (${d.source_table}:${d.source_pk}, score=${d.score.toFixed(3)})`;
        ev.appendChild(row);
      });
      pending.appendChild(ev);
    }
  } catch (err) {
    pending.textContent = '오류: ' + err.message;
  } finally {
    send.disabled = false;
    input.focus();
  }
});
</script>
</body>
</html>
"""


class AskRequest(BaseModel):
    question: str
    candidate: str = "openai-large"
    limit: int = 8
    model: str = "gpt-4.1-mini"

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


def create_app(
    *,
    answer_fn: Callable[..., RagAnswer] = answer_question,
    db_path: str = "data/jforest.db",
    qdrant_root: str = "data/qdrant",
) -> FastAPI:
    app = FastAPI(title="jforest agent")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return CHAT_HTML

    @app.post("/ask")
    def ask(req: AskRequest) -> dict:
        result = answer_fn(
            req.question,
            candidate_name=req.candidate,
            limit=req.limit,
            chat_model=req.model,
            db_path=db_path,
            qdrant_root=qdrant_root,
        )
        return asdict(result)

    return app


app = create_app()
