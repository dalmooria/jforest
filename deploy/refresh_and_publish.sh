#!/usr/bin/env bash
# 매일 갱신 → 서빙 스냅샷 export → git push(→ Vercel 자동 재배포).
# launchd(com.jforest.refresh.plist)가 매일 04:00 호출한다. 멱등·재실행 안전.
set -euo pipefail

REPO="/Users/sungwoojo/workspace/jforest"
cd "$REPO"

LOCK="data/.refresh.lock"
if [ -e "$LOCK" ]; then
  echo "$(date -u +%FT%TZ) 이미 실행 중(lock 존재) — 종료"; exit 0
fi
trap 'rm -f "$LOCK"' EXIT
touch "$LOCK"

PY="$REPO/.venv/bin/python"

echo "$(date -u +%FT%TZ) [1/3] 데이터 갱신"
# Phase 2 완료 후 활성화:
# "$REPO/.venv/bin/jforest" crawl notices --incremental || true
# "$REPO/.venv/bin/jforest" alerts-extract || true

echo "$(date -u +%FT%TZ) [2/3] 서빙 스냅샷 export"
"$PY" -c "from jforest.export_serving import export_serving; print(export_serving())"

echo "$(date -u +%FT%TZ) [3/3] 스냅샷 커밋/푸시"
if ! git diff --quiet -- api/serving.sqlite; then
  git add api/serving.sqlite
  git commit -m "chore(serving): daily snapshot $(date -u +%F)" -q
  git push -q
  echo "pushed → Vercel 재배포 트리거"
else
  echo "변경 없음 — 스킵"
fi
