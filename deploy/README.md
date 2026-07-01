# Vercel 배포 & 일일 갱신 런북

Open Report 웹서비스를 Vercel에 배포하고, 로컬 맥이 매일 데이터를 갱신해 스냅샷을 밀어넣는 구성.

## 아키텍처 (요약)

```
[로컬 맥]  jforest.db(1.3GB, 크롤+LLM 소유)
   │ 매일 04:00 launchd
   ├─ jforest refresh-daily        (Phase 2: 공지 증분크롤 + alerts 추출)
   ├─ jforest export-serving       → api/serving.sqlite (약 2MB)
   └─ git push  ───────────────────────────────▶ [Vercel] 자동 재배포
                                                     api/index.py (ASGI, torch 無)
                                                     ← api/serving.sqlite 읽기전용
                                                     build_open_events(date) 계산
```

- **왜 스냅샷?** 원본 1.3GB는 Vercel(무상태·250MB 함수한도)에 못 올림. 웹이 쓰는 4개 테이블만 뽑으면 ~2MB.
- **왜 torch 격리?** `jforest.rag`는 torch/qdrant를 끌어와 번들 한도를 초과 → 함수는 `fcfs_report`(순수 파이썬)만 import. `.vercelignore`가 무거운 서브모듈 제외.

## 최초 배포 (1회)

1. Vercel 프로젝트 생성 후 이 레포 연결 (`vercel` CLI 또는 대시보드 Git 연동).
2. 스냅샷 최초 생성 + 커밋:
   ```bash
   .venv/bin/python -c "from jforest.export_serving import export_serving; print(export_serving())"
   git add api/serving.sqlite && git commit -m "chore(serving): initial snapshot"
   git push
   ```
3. 배포 확인:
   - `https://<project>.vercel.app/api/health` → `{"ok":true,"generated_at":...,"counts":{...}}`
   - serving.sqlite가 함수에 번들되어 읽히면 성공.

## 일일 갱신 설치 (launchd)

```bash
cp deploy/com.jforest.refresh.plist ~/Library/LaunchAgents/
# plist 안 경로가 실제 설치 위치인지 확인 후:
launchctl load ~/Library/LaunchAgents/com.jforest.refresh.plist
# 수동 테스트:
launchctl start com.jforest.refresh
tail -f data/refresh.log
```

갱신 흐름: `deploy/refresh_and_publish.sh` → export-serving → `api/serving.sqlite` 변경 시 자동 커밋/푸시 → Vercel 재배포. 락파일로 중복 실행 방지.

## 주의사항

- **Python import 경로**: Phase 1의 `api/index.py`가 `from jforest.fcfs_report import ...` 할 때 Vercel이 레포 루트를 sys.path에 두지 않으면 실패 → `api/index.py` 상단에 `sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))` 추가.
- **스냅샷 git 용량**: 2MB 바이너리를 매일 커밋 → 장기적으로 히스토리 팽창. 필요 시 git LFS 또는 Vercel Blob으로 이전(§10 대안).
- **비밀정보**: LLM 키 등은 로컬 파이프라인에만 필요. Vercel 함수는 읽기전용 스냅샷만 쓰므로 시크릿 불필요.
- **맥 상시 켜짐 전제**: 꺼져 있으면 그날 갱신 누락(다음 실행 때 최신 스냅샷으로 복구). 상시성이 필요하면 §9.3의 VM/GitHub Actions로 이전.
