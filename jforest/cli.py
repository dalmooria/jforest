# jforest/cli.py
import click

from jforest.db import get_conn, init_db
from jforest.http import Client
from jforest.reparse import reparse as do_reparse, status_counts
from jforest.crawlers import forests, rooms, room_details, discounts, policies, notices
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
}
ORDER = ["forests", "rooms", "room-details", "discounts", "policies", "notices"]
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
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def agent_ask(ctx, question, candidate, qdrant_root, chat_model, retrieval_limit, as_json):
    """색인된 데이터 근거로 질문에 답한다."""
    import json
    from dataclasses import asdict

    from jforest.rag import answer_question

    result = answer_question(
        question,
        candidate_name=candidate,
        qdrant_root=qdrant_root,
        chat_model=chat_model,
        limit=retrieval_limit,
        db_path=ctx.obj["db"],
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


@main.command()
@click.pass_context
def status(ctx):
    counts = status_counts(ctx.obj["conn"])
    for table, n in counts.items():
        click.echo(f"{table:24} {n}")
