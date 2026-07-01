# jforest/cli.py
import click

from jforest.db import get_conn, init_db
from jforest.http import Client
from jforest.reparse import reparse as do_reparse, status_counts
from jforest.crawlers import forests, rooms, room_details, discounts, policies, notices, facilities
from jforest.bench import index_candidate, run_candidate, snapshot_corpus, summarize_run, write_report
from jforest.embeddings import CANDIDATES
from jforest.extract import (
    run_pdf_text_extraction, run_hwpx_text_extraction, run_hwp_text_extraction, run_vision_ocr,
)

EXTRACT_STEPS = {"pdf-text", "hwpx-text", "hwp-text", "vision"}

STEPS = {
    "forests": forests.run,
    "rooms": rooms.run,
    "room-details": room_details.run,
    "discounts": discounts.run,
    "policies": policies.run,
    "notices": notices.run,
    "facilities": facilities.run,
}
ORDER = ["forests", "rooms", "room-details", "discounts", "policies", "notices", "facilities"]
REPARSE_STEPS = {"forests", "rooms", "room-details", "discounts", "policies", "notices"}


@click.group()
@click.option("--db", default="data/jforest.db", help="SQLite 경로")
@click.option("--limit", type=int, default=None, help="휴양림 N곳만")
@click.option("--force", is_flag=True, help="이미 수집된 항목도 다시 수집")
@click.option("--delay", type=float, default=1.0, help="요청 간 딜레이(초)")
@click.pass_context
def main(ctx, db, limit, force, delay):
    import os
    os.makedirs(os.path.dirname(db) or ".", exist_ok=True)
    conn = get_conn(db)
    init_db(conn)
    ctx.obj = {"conn": conn, "db": db, "limit": limit, "force": force, "delay": delay}


@main.command()
@click.argument("step")
@click.pass_context
def crawl(ctx, step):
    o = ctx.obj
    conn = o["conn"]
    client = Client(conn, delay=o["delay"])
    steps = ORDER if step == "all" else [step]
    for st in steps:
        if st not in STEPS:
            raise click.ClickException(f"알 수 없는 단계: {st}. 가능: {', '.join(ORDER)} 또는 all")
    for st in steps:
        click.echo(f"== crawl {st} ==")
        summary = STEPS[st](conn, client, limit=o["limit"], force=o["force"])
        click.echo(summary.line())
        if st == "notices":
            click.echo("== download attachments ==")
            ds = notices.download_attachments(conn, client, limit=o["limit"])
            click.echo("첨부 " + ds.line())
        if summary.failures:
            click.echo(f"  실패 {len(summary.failures)}건 중 상위 {min(20, len(summary.failures))}건:")
            for fail in summary.failures[:20]:
                click.echo(f"  FAIL: {fail}")


@main.command()
@click.argument("step")
@click.pass_context
def reparse(ctx, step):
    if step not in REPARSE_STEPS:
        raise click.ClickException(f"reparse 미지원 단계: {step}. 가능: {', '.join(sorted(REPARSE_STEPS))}")
    n = do_reparse(ctx.obj["conn"], step)
    click.echo(f"reparse {step}: {n}건 처리")


@main.command()
@click.argument("step")
@click.pass_context
def extract(ctx, step):
    if step not in EXTRACT_STEPS:
        raise click.ClickException(f"extract 미지원 단계: {step}. 가능: {', '.join(sorted(EXTRACT_STEPS))}")
    o = ctx.obj
    if step == "pdf-text":
        n = run_pdf_text_extraction(o["conn"], limit=o["limit"])
        click.echo(f"extract pdf-text: {n}건 처리")
    elif step == "hwpx-text":
        n = run_hwpx_text_extraction(o["conn"], limit=o["limit"])
        click.echo(f"extract hwpx-text: {n}건 처리")
    elif step == "hwp-text":
        n = run_hwp_text_extraction(o["conn"], limit=o["limit"])
        click.echo(f"extract hwp-text: {n}건 처리")
    elif step == "vision":
        n = run_vision_ocr(o["conn"], limit=o["limit"])
        click.echo(f"extract vision: {n}건 처리")


@main.command()
@click.option("--model", default="gemini-2.5-flash", help="Vertex Gemini 모델")
@click.pass_context
def structure(ctx, model):
    """고가치 공지를 Vertex Gemini로 구조화(extractedFacts)한다."""
    import threading
    from jforest.structure import run_fact_extraction, make_gemini_generator
    o = ctx.obj
    # Vertex 클라이언트는 첫 호출 때 한 번만 생성(대상 0건이면 만들지 않음). 동시 호출 안전.
    box = []
    lock = threading.Lock()

    def lazy_generator(prompt):
        if not box:
            with lock:
                if not box:
                    box.append(make_gemini_generator(model=model))
        return box[0](prompt)

    n = run_fact_extraction(o["conn"], generator=lazy_generator, model=model, limit=o["limit"])
    click.echo(f"structure: {n}건 처리")


@main.command("facilities")
@click.option("--model", default="gemini-2.5-flash", help="Vertex Gemini 모델")
@click.pass_context
def facilities_cmd(ctx, model):
    """수집된 소개/프로그램 페이지에서 물놀이·바베큐·숲해설을 LLM으로 구조화한다."""
    import threading
    from jforest.facilities import run_facility_extraction
    from jforest.structure import make_gemini_generator
    o = ctx.obj
    box = []
    lock = threading.Lock()

    def lazy_generator(prompt):
        if not box:
            with lock:
                if not box:
                    box.append(make_gemini_generator(model=model))
        return box[0](prompt)

    n = run_facility_extraction(o["conn"], generator=lazy_generator, model=model, limit=o["limit"])
    click.echo(f"facilities: {n}건 처리")


@main.group()
@click.pass_context
def bench(ctx):
    """검색/임베딩 벤치마크."""


@bench.command("corpus")
@click.option("--output", default="data/bench/corpus.jsonl")
@click.pass_context
def bench_corpus(ctx, output):
    n = snapshot_corpus(ctx.obj["conn"], output)
    click.echo(f"wrote {n} documents to {output}")


@bench.command("embeddings")
@click.option("--candidate", type=click.Choice(sorted(CANDIDATES)), required=True)
@click.option("--questions", default="tests/fixtures/bench/questions.jsonl")
@click.option("--corpus", default=None, help="고정 corpus JSONL 경로")
@click.option("--qdrant-root", default="data/qdrant")
@click.option("--runs-dir", default="data/bench/runs")
@click.option("--reindex", is_flag=True)
@click.pass_context
def bench_embeddings(ctx, candidate, questions, corpus, qdrant_root, runs_dir, reindex):
    conn = ctx.obj["conn"]
    if reindex:
        def progress(done, total):
            click.echo(f"indexed {done}/{total} documents for {candidate}")

        n = index_candidate(conn, candidate, qdrant_root, corpus_path=corpus, progress=progress)
        click.echo(f"indexed {n} documents for {candidate}")
    output_path = f"{runs_dir}/{candidate}.jsonl"
    run_candidate(conn, candidate, questions, qdrant_root, output_path, corpus_path=corpus)
    click.echo(f"wrote {output_path}")


@bench.command("report")
@click.option("--runs-dir", default="data/bench/runs")
@click.option("--output", default="data/bench/reports/embedding-benchmark.md")
def bench_report(runs_dir, output):
    for candidate in sorted(CANDIDATES):
        path = f"{runs_dir}/{candidate}.jsonl"
        try:
            summary = summarize_run(path)
        except FileNotFoundError:
            click.echo(f"{candidate}: no run")
            continue
        click.echo(
            f"{candidate}: n={summary['count']} "
            f"recall@5={summary['recall_at_5']:.3f} "
            f"recall@10={summary['recall_at_10']:.3f} "
            f"mrr@10={summary['mrr_at_10']:.3f} "
            f"latency={summary['average_latency_ms']:.1f}ms"
        )
    write_report(runs_dir, output)
    click.echo(f"wrote {output}")


@main.command()
@click.option("--export", "export_path", default="data/review_queue.jsonl", help="검수 큐 출력 경로")
@click.pass_context
def review(ctx, export_path):
    """needs_review를 객관 검증으로 재계산하고 검수 큐를 내보낸다."""
    from jforest.review import run_revalidation, export_review_queue
    conn = ctx.obj["conn"]
    stats = run_revalidation(conn)
    n = export_review_queue(conn, export_path)
    click.echo(f"재검증: 검수필요 {stats['flagged']} / 통과 {stats['cleared']}")
    click.echo(f"검수 큐 {n}건 → {export_path}")


@main.group()
def agent():
    """AI 에이전트 PoC."""


@agent.command("ask")
@click.argument("question")
@click.option("--candidate", default="openai-large", type=click.Choice(sorted(CANDIDATES)))
@click.option("--qdrant-root", default="data/qdrant")
@click.option("--model", "chat_model", default="gpt-4.1-mini")
@click.option("--limit", "retrieval_limit", default=8, type=int)
@click.option("--rerank", is_flag=True, help="cross-encoder 리랭킹(품질↑, 지연↑)")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def agent_ask(ctx, question, candidate, qdrant_root, chat_model, retrieval_limit, rerank, as_json):
    """색인된 데이터 근거로 질문에 답한다."""
    import json
    from dataclasses import asdict

    from jforest.rag import BgeReranker, answer_question

    result = answer_question(
        question,
        candidate_name=candidate,
        qdrant_root=qdrant_root,
        chat_model=chat_model,
        limit=retrieval_limit,
        db_path=ctx.obj["db"],
        reranker=BgeReranker() if rerank else None,
    )
    if as_json:
        click.echo(json.dumps(asdict(result), ensure_ascii=False))
        return

    click.echo(result.answer)
    click.echo("")
    click.echo("근거:")
    for index, doc in enumerate(result.evidence, start=1):
        forest = f"{doc.instt_name} · " if doc.instt_name else ""
        click.echo(
            f"[{index}] {doc.source_table}:{doc.source_pk} "
            f"{forest}{doc.title_or_name or doc.doc_type} score={doc.score:.3f}"
        )


@agent.command("eval")
@click.option("--cases", "cases_path", default="tests/fixtures/bench/questions.jsonl")
@click.option("--candidate", default="openai-large", type=click.Choice(sorted(CANDIDATES)))
@click.option("--qdrant-root", default="data/qdrant")
@click.option("--model", "chat_model", default="gpt-4.1-mini")
@click.option("--judge-model", default="gpt-4.1-mini")
@click.option("--limit", "retrieval_limit", default=8, type=int)
@click.option("--rerank", is_flag=True, help="cross-encoder 리랭킹 적용 후 평가")
@click.option("--output", "output_path", default="data/bench/runs/answer-eval.jsonl")
@click.pass_context
def agent_eval(ctx, cases_path, candidate, qdrant_root, chat_model, judge_model, retrieval_limit, rerank, output_path):
    """RAG 답변 품질을 LLM-judge로 평가(faithfulness/answer_relevance)한다."""
    import json
    from dataclasses import asdict
    from pathlib import Path

    from jforest.answer_eval import (
        OpenAIJudge,
        load_eval_cases,
        run_answer_eval,
        summarize_answer_eval,
    )
    from jforest.rag import BgeReranker

    cases = load_eval_cases(cases_path)
    results = run_answer_eval(
        cases,
        judge=OpenAIJudge(model=judge_model),
        candidate_name=candidate,
        qdrant_root=qdrant_root,
        chat_model=chat_model,
        limit=retrieval_limit,
        db_path=ctx.obj["db"],
        reranker=BgeReranker() if rerank else None,
    )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
    summary = summarize_answer_eval(results)
    click.echo(
        f"답변 평가: n={summary['count']} "
        f"faithfulness={summary['faithfulness']:.3f} "
        f"answer_relevance={summary['answer_relevance']:.3f} "
        f"insufficient_rate={summary['insufficient_rate']:.3f}"
    )
    click.echo(f"상세 → {output_path}")


@agent.command("serve")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
@click.pass_context
def agent_serve(ctx, host, port):
    """웹 채팅 UI + /ask API 서버를 띄운다."""
    import uvicorn

    from jforest.api import create_app

    app = create_app(db_path=ctx.obj["db"])
    click.echo(f"숲나들e 에이전트: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


@main.command("fcfs-report")
@click.option("--date", "date_str", default=None, help="기준일 YYYY-MM-DD (기본: 오늘)")
@click.pass_context
def fcfs_report(ctx, date_str):
    """해당일에 선착순 예약이 열리는 휴양림을 리포팅한다."""
    from datetime import date as _date

    from jforest.fcfs_report import build_fcfs_report, format_report

    on_date = _date.fromisoformat(date_str) if date_str else _date.today()
    rows = build_fcfs_report(ctx.obj["conn"], on_date)
    click.echo(format_report(rows, on_date))


@main.command("export-serving")
@click.option("--out", "out_path", default="api/serving.sqlite",
              help="서빙 스냅샷 경로 (기본: api/serving.sqlite)")
@click.pass_context
def export_serving_cmd(ctx, out_path):
    """웹 서빙용 경량 SQLite 스냅샷을 만든다(Vercel 배포용, ~2MB)."""
    from jforest.export_serving import export_serving

    counts = export_serving(ctx.obj["db"], out_path)
    for table, n in counts.items():
        if table == "_bytes":
            click.echo(f"{'→ 크기':32} {n/1024/1024:.2f} MB  ({out_path})")
        else:
            click.echo(f"{table:32} {n}")


@main.command()
@click.pass_context
def status(ctx):
    counts = status_counts(ctx.obj["conn"])
    for table, n in counts.items():
        click.echo(f"{table:24} {n}")
