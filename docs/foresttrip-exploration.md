# 숲나들e 자연휴양림 정보 탐색 결과

탐색일: 2026-05-06 KST  
대상: 자연휴양림 안내 사이트 구축을 위한 숙소/예약/할인 정보 수집 가능성 확인

## 결론

필요 정보는 대부분 숲나들e 웹페이지에서 취합 가능하다. 다만 데이터가 하나의 공개 JSON API로 정리되어 있지 않고, 다음처럼 여러 페이지에 나뉘어 있다.

- 휴양림 기본 목록: `자연휴양림안내` 목록 HTML
- 객실 목록/객실별 가격: 각 휴양림 개별 홈페이지의 `시설물안내 > 숙박시설` 및 객실 상세 HTML
- 할인정책: `휴양림별 할인정책` 페이지에 `insttId`를 넣어 휴양림별 조회
- 예약정책: `휴양림별예약정책안내` 전체 표 및 각 휴양림의 `예약안내` 하위 정책 페이지

자동 수집은 가능하지만, 객실 이용안내의 바베큐/물놀이 여부는 정형 필드가 아니라 자유 텍스트에 들어가는 경우가 있어 키워드 기반 추출 뒤 검수 플래그가 필요하다.

## 확인한 원천 페이지

| 구분 | URL | 확인 결과 |
| --- | --- | --- |
| 자연휴양림안내 | `https://www.foresttrip.go.kr/pot/is/fs/selectFcltSrchView.do?hmpgId=FRIP&menuId=002001` | 전체 184곳, 46페이지. 휴양림명, 기관구분, 요약, 공지, 태그, 홈페이지 링크, 예약 접수 유형, `insttId` 확인 가능 |
| 휴양림별예약정책안내 | `https://www.foresttrip.go.kr/pot/cc/bb/selectFripRsrvtPolcyView.do?hmpgId=FRIP&menuId=002002` | 전체 예약정책 표가 HTML에 포함됨. 객실/야영장/대기 운영 여부, 선착순 방식, 추첨제 종류, 우선예약 종류 확인 가능 |
| 휴양림별할인정책 | `https://www.foresttrip.go.kr/pot/rm/ug/selectDcPolicyView.do?hmpgId=FRIP&menuId=002004` | 초기 화면은 선택 필요. `insttId`를 붙이면 휴양림별 할인정책 표가 HTML로 반환됨 |

## 수집 대상별 가능 여부

| 필요 필드 | 수집 가능성 | 수집 경로 | 비고 |
| --- | --- | --- | --- |
| 휴양림 목록/식별자 | 가능 | 자연휴양림안내 목록 또는 `/pot/rm/cs/selectInsttHuyangList.do?srchSido={1..9}` | 지역별 JSON 목록 합계 184곳 확인 |
| 객실 목록 | 가능 | `/pot/rm/fa/selectFcltsArmpListView.do?hmpgId={insttId}&menuId=002002001` | 유형, 시설물명, 최대인원/면적, 객실 상세 URL 포함 |
| 객실 가격 | 가능 | `/pot/rm/fa/selectFcltsArmpDtlView.do?insttId={insttId}&goodsId={goodsId}` | 비수기/성수기, 평일/주말 요금 확인 가능. "오늘일자 기준 가격정보" 문구 있음 |
| 할인정책 | 가능 | `/pot/rm/ug/selectDcPolicyView.do?hmpgId=FRIP&menuId=002004&insttId={insttId}` | 할인 대상, 구분, 시점, 객실/야영장/부대시설 할인율 표 |
| 물놀이 가능 여부 | 부분 가능 | 자연휴양림 태그, 객실/시설 이용안내 자유 텍스트, 공지 | `#수영장`, `물놀이`, `수영`, `계곡` 등 키워드 추출 필요. 공식 여부 판정은 검수 권장 |
| 바베큐 가능 여부 | 부분 가능 | 객실 상세 이용안내 자유 텍스트 | `바비큐`, `바베큐`, `숯불`, `장작`, `사용 금지` 등 긍정/부정 문맥 파싱 필요 |
| 선착순 예약 시점 | 가능 | 예약정책 전체 표 + 개별 `선착순 예약정책` | 전체 표는 6주/익월말 방식, 개별 페이지는 세부 문구 제공 |
| 추첨 예약 시점 | 가능 | 예약정책 전체 표 + 개별 `주말추첨제/성수기추첨제 예약정책` | 어떤 추첨제를 운영하는지는 전체 표, 정확한 접수/발표 시각은 개별 정책 페이지 |

## 검증 예시

### 휴양림 목록

- 자연휴양림안내 마지막 페이지에서 `46/46 총 184곳` 확인.
- 지역별 휴양림 JSON 목록 확인:
  - `https://www.foresttrip.go.kr/pot/rm/cs/selectInsttHuyangList.do?srchSido=1`
  - `srchSido` 1~9 합계: 25 + 30 + 21 + 18 + 14 + 17 + 29 + 26 + 4 = 184
- 응답에는 `insttId`, `insttNm`, `insttTpcd` 등이 포함됨.

### 객실 목록/가격

객실 목록 예시:

```text
https://www.foresttrip.go.kr/pot/rm/fa/selectFcltsArmpListView.do?hmpgId=ID02030124&menuId=002002001
```

확인된 필드 예시:

- 유형: `숲속의집`
- 시설물명: `A동-101호(거류산)`
- 최대인원/면적: `3인실, 20㎡`
- 상세 URL의 `goodsId`: `GID020301240100101001001000004`

객실 상세 예시:

```text
https://www.foresttrip.go.kr/pot/rm/fa/selectFcltsArmpDtlView.do?insttId=ID02030124&goodsId=GID020301240100101001001000004
```

확인된 필드 예시:

- 기준인원: 2
- 최대인원: 3
- 면적: 20㎡
- 편의시설: 에어컨 등
- 입/퇴실 시간: 15:00 ~ 11:00
- 가격: 비수기 평일 60,000원, 비수기 주말 80,000원, 성수기 평일 80,000원, 성수기 주말 80,000원

### 바베큐 여부

객실 상세의 이용안내 문구에서 확인 가능했다.

- 가리산 객실 상세 예시: `바베큐시설(숯, 철망 개인지참)` 문구 확인
- 가리왕산 객실 상세 예시: `연중 바비큐 사용 금지`, `외부 취사 및 숯불, 바베큐가 금지` 문구 확인

따라서 단순 키워드 존재 여부가 아니라 긍정/부정 문맥을 함께 저장해야 한다.

### 할인정책

예시:

```text
https://www.foresttrip.go.kr/pot/rm/ug/selectDcPolicyView.do?hmpgId=FRIP&menuId=002004&insttId=0113
```

확인된 구조:

- 할인 대상
- 할인 구분
- 할인 시점
- 객실 할인율: 비수기/성수기, 주중/주말
- 야영장 할인율
- 부대시설 할인율

### 예약정책

전체 정책 표에서 확인 가능한 항목:

- 구분, 지역, 휴양림
- 운영현황: 객실, 야영장, 대기
- 예약방법: 선착순 6주 수요일, 익월말, 추첨제, 우선예약

개별 정책 페이지 예시:

```text
https://www.foresttrip.go.kr/pot/rm/ug/selectRsrvtGdncView.do?hmpgId=0113&menuId=004001001&ruleId=101
https://www.foresttrip.go.kr/pot/rm/ug/selectRsrvtGdncView.do?hmpgId=0113&menuId=004001002&ruleId=102
https://www.foresttrip.go.kr/pot/rm/ug/selectRsrvtGdncView.do?hmpgId=0113&menuId=004001003&ruleId=103
```

검증한 문구:

- 선착순: 매주 수요일 오전 9시부터 6주차 월요일까지 신청 가능
- 주말추첨: 매월 4일 오전 9시부터 9일 오후 6시까지 접수, 매월 10일 오후 16시 발표, 미선정/취소 객실은 매월 15일 오전 9시 일반 오픈
- 성수기추첨: 접수 기간 확정 시 숲나들e 공지사항에 기재. 발표는 마이페이지/공지사항 확인

## 자동 수집 설계 메모

1. 지역별 `selectInsttHuyangList.do?srchSido={1..9}`로 184개 휴양림 식별자 수집
2. 각 `insttId`를 `hmpgId`로 사용해 메뉴 목록 조회
   - `https://www.foresttrip.go.kr/com/sub/selectMenuList.do?hmpgId={insttId}`
   - 숙박시설, 이용요금, 할인정책, 예약정책 메뉴 존재 여부 확인
3. 숙박시설 목록에서 객실별 `goodsId` 수집
4. 객실 상세에서 기본정보/가격정보/이용안내 텍스트 파싱
5. 할인정책 페이지에서 휴양림별 할인 표 파싱
6. 예약정책 전체 표와 개별 예약정책 페이지를 결합
7. 바베큐/물놀이는 `source_text`, `detected_value`, `confidence`, `needs_review` 형태로 저장

## 주의사항

- 객실 가격 상세에는 `가격정보는 오늘일자 기준 가격정보`라는 문구가 있어, 장기 캐시보다 수집일을 함께 저장해야 한다.
- 예약 가능 객실 조회 페이지는 NetFunnel 및 로그인 흐름에 걸릴 수 있다. 이번 요구사항의 "예약정책" 수집은 공개 정책 페이지로 충분하지만, 실시간 빈 객실/예약 가능 여부까지 수집하려면 별도 검토가 필요하다.
- 일부 휴양림은 개별 홈페이지 URL이 `foresttrip.go.kr/{숫자}` 형태이고 일부는 `indvz/main.do?hmpgId=...` 형태다. 내부 API는 대체로 `hmpgId={insttId}`로 동작했다.
- 자유 텍스트에는 `바비큐`, `바베큐`, `숯불`, `장작`, `금지`, `제한`처럼 표기가 섞여 있어 정규화 사전이 필요하다.
