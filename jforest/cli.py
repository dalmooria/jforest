# jforest/cli.py
import click

from jforest.db import get_conn, init_db
from jforest.http import Client
from jforest.reparse import reparse as do_reparse, status_counts
from jforest.crawlers import forests, rooms, room_details, discounts, policies, notices

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
    ctx.obj = {"conn": conn, "limit": limit, "force": force, "delay": delay}


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
@click.pass_context
def status(ctx):
    counts = status_counts(ctx.obj["conn"])
    for table, n in counts.items():
        click.echo(f"{table:24} {n}")
