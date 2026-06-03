# 숲나들e 휴양림 공지사항 및 이미지 OCR 탐색

조사일: 2026-05-06

## 결론

- 184개 휴양림 모두에서 `공지사항` 메뉴를 확인할 수 있다.
- 공지 목록/상세/첨부 다운로드는 공통 URL 패턴으로 자동 수집 가능하다.
- 공지 본문은 HTML 텍스트인 경우와 JPG/PDF 첨부인 경우가 섞여 있다.
- 공지사항 OCR은 초기 필수 기능이 아니라 기능 고도화 사항으로 분리한다.
- 이미지형 공지는 첨부 원본 파일 다운로드까지만 우선 수집 대상으로 보고, OCR/구조화는 고도화 단계에서 처리한다.
- 로컬 환경에는 `tesseract`, `magick`, `ocrmypdf`가 없어 JPG OCR은 바로 실행할 수 없었다. 다만 `pdftotext`, `pdfimages`는 설치되어 있어 텍스트 PDF는 OCR 없이 추출 가능하다.

## 공지사항 수집 경로

### 휴양림 목록

지역별 휴양림 목록:

```text
https://www.foresttrip.go.kr/pot/rm/cs/selectInsttHuyangList.do?srchSido={1..9}
```

확인 결과 총 184개 휴양림이 반환된다.

### 휴양림별 메뉴

```text
https://www.foresttrip.go.kr/com/sub/selectMenuList.do?hmpgId={hmpgId}
```

`menuNm == "공지사항"`인 메뉴를 우선 선택해야 한다.

검증 결과:

```text
total_ids 184
notice_found 184
missing 0
notice_menuId_counts [('005001', 184)]
bbrssMsterId_counts [('BBRSSMSTER_00000051', 184)]
```

주의: 일부 상위 메뉴 `참여마당(menuId=005)`의 `menuUrl`도 공지 목록으로 연결되지만 `bbrssMsterId` 값이 잘린 경우가 있었다. 자동 수집 시 상위 메뉴 URL을 쓰지 말고 `menuNm == "공지사항"`인 하위 메뉴 URL을 사용해야 한다.

### 공지 목록

공통 패턴:

```text
https://www.foresttrip.go.kr/pot/cc/nm/selectNticBbrssListView.do?hmpgId={hmpgId}&menuId=005001&bbrssMsterId=BBRSSMSTER_00000051
```

목록 페이지에서 상세 이동은 다음 JS 함수로 처리된다.

```javascript
fn_goDtlView(twbbsId)
```

상세 URL 패턴:

```text
https://www.foresttrip.go.kr/pot/cc/nm/selectNticBbrssDtlView.do?hmpgId={hmpgId}&menuId=005001&twbbsId={twbbsId}&bbrssMsterId=BBRSSMSTER_00000051
```

### 첨부 다운로드

상세 페이지의 첨부 다운로드는 다음 JS 함수 인자로 파일 ID를 노출한다.

```javascript
fn_goFileDown(attchFileMsterId, attchFileId)
```

다운로드 URL:

```text
https://www.foresttrip.go.kr/com/cm/fileDownload.do?ATTCH_FILE_ID={attchFileId}&ATTCH_FILE_MSTER_ID={attchFileMsterId}
```

응답 헤더에서 `Content-Disposition` 파일명과 `Content-Type`을 확인할 수 있다.

## 샘플 확인

### 고성갈모봉 자연휴양림

- `hmpgId`: `ID02030124`
- 공지 상세:

```text
https://www.foresttrip.go.kr/pot/cc/nm/selectNticBbrssDtlView.do?hmpgId=ID02030124&menuId=005001&twbbsId=213412&bbrssMsterId=BBRSSMSTER_00000051
```

- 제목: `고성갈모봉 자연휴양림 리플렛`
- 수정일: `2026-04-15`
- 본문: 짧은 HTML 텍스트
- 첨부:
  - `FILEMSTER_00170235`, `185417`, `2026 리플렛 앞면(이용안내)수정.jpg`
  - `FILEMSTER_00170235`, `185418`, `2025 리플렛 뒷면(조감도).jpg`
- 다운로드 검증:
  - `185417`: JPEG, 1187x841, 약 1.8MB
  - `185418`: JPEG, 1150x793, 약 1.4MB

`185417` 이미지는 리플렛이며 객실 요금, 성수기, 감면혜택, 시설 사진, 체험 프로그램 등 텍스트와 이미지가 섞여 있다. 이 유형은 OCR 후 표/항목 구조화가 필요하다.

### 국립가리왕산자연휴양림

- `hmpgId`: `0113`
- 공지 상세:

```text
https://www.foresttrip.go.kr/pot/cc/nm/selectNticBbrssDtlView.do?hmpgId=0113&menuId=005001&twbbsId=250396&bbrssMsterId=BBRSSMSTER_00000051
```

- 제목: `2026년 봄철 산불조심 기간 가리왕산 전면 통제 안내(1.20~5.15)`
- 수정일: `2026-01-14`
- 첨부:
  - `FILEMSTER_00172858`, `184669`, `2026년 봄철 산불조심기간 공고문.pdf`
- 다운로드 검증:
  - PDF 1.7, 2 pages, 약 229KB
- `pdftotext`로 텍스트 추출 가능. 단, 일부 숫자/기호가 누락되어 원문 검증 단계가 필요하다.

### 가리산 자연휴양림

- `hmpgId`: `ID02030002`
- 공지 상세:

```text
https://www.foresttrip.go.kr/pot/cc/nm/selectNticBbrssDtlView.do?hmpgId=ID02030002&menuId=005001&twbbsId=244656&bbrssMsterId=BBRSSMSTER_00000051
```

- 제목: `가리산자연휴양림 동절기 소형산막(1번~9번) 및 야영장 운영중지`
- 수정일: `2025-12-17`
- 첨부 없음
- 본문 HTML 텍스트만으로 수집 가능

## OCR 처리 방법

상태: 기능 고도화 사항

초기 구축 범위에서는 공지 목록, 상세 HTML 본문, 첨부파일 메타데이터와 원본 파일 다운로드 경로 확보까지만 처리한다. 이미지형 공지의 OCR, 표 인식, 요금/할인/운영정보 구조화는 후속 고도화 작업으로 둔다.

### 권장 수집 파이프라인

1. 지역별 휴양림 목록에서 `hmpgId`, 휴양림명을 수집한다.
2. `selectMenuList`에서 `menuNm == "공지사항"` 메뉴 URL을 찾는다.
3. 공지 목록에서 `twbbsId`, 제목, 수정일, 첨부 여부를 수집한다.
4. 공지 상세에서 HTML 본문 텍스트를 저장한다.
5. 상세 HTML에서 `fn_goFileDown(fileMasterId, fileId)` 인자를 추출한다.
6. 첨부를 다운로드하고 `Content-Type` 또는 파일 시그니처로 파일 종류를 판별한다.
7. 초기 구축에서는 원본 파일 URL, 공지 ID, 첨부 ID, 파일명을 저장한다.
8. 고도화 단계에서 파일 종류별 텍스트 추출/OCR을 실행한다.
9. 고도화 단계에서 숙소/요금/휴장/물놀이/바베큐/예약 관련 키워드를 후처리해 구조화한다.

### 파일 종류별 처리

- HTML 본문: HTML 태그 제거 후 바로 저장.
- 텍스트 PDF: `pdftotext` 우선 사용.
- 스캔/이미지 PDF: `pdfimages` 또는 `pdftoppm`으로 페이지 이미지를 만든 뒤 OCR.
- JPG/PNG/GIF: 이미지 OCR 필요.
- HWP/HWPX 첨부가 발견되면 별도 파서 또는 변환기가 필요하다.

### 로컬 OCR 후보

macOS 기준 설치:

```bash
brew install tesseract tesseract-lang imagemagick poppler
```

JPG OCR 예시:

```bash
magick input.jpg -resize 200% -colorspace Gray -contrast-stretch 0x20% -sharpen 0x1 preprocessed.png
tesseract preprocessed.png stdout -l kor+eng --psm 6
```

PDF 이미지화 후 OCR 예시:

```bash
pdftoppm -r 300 notice.pdf notice_page -png
tesseract notice_page-1.png stdout -l kor+eng --psm 6
```

장점:

- 서버 내부에서 처리 가능
- 비용 예측이 쉽다
- 단순 공문/스캔 이미지에는 충분할 수 있다

한계:

- 리플렛처럼 표, 사진, 색상 배경, 다단 레이아웃이 섞인 이미지는 정확도가 떨어질 가능성이 높다.
- 표 구조를 복원하려면 후처리 로직이 필요하다.

### 운영용 OCR 후보

이미지 공지가 많고 요금표/할인정책/운영중지 같은 정보를 자동 구조화해야 한다면 일반 OCR보다 비전 기반 OCR 또는 클라우드 OCR을 우선 검토하는 것이 좋다.

후보:

- Google Cloud Vision OCR
- Naver CLOVA OCR
- AWS Textract
- LLM 비전 모델 기반 OCR 및 구조화

권장 방식:

- 1차: 원본 HTML 텍스트와 PDF 텍스트 레이어 추출
- 2차: 이미지/PDF 스캔 OCR
- 3차: OCR 결과를 휴양림 안내 사이트용 스키마로 구조화
- 4차: 신뢰도 낮은 항목은 관리자 검수 큐로 보낸다

구조화 스키마 예시:

```json
{
  "noticeId": "213412",
  "forestId": "ID02030124",
  "title": "고성갈모봉 자연휴양림 리플렛",
  "updatedAt": "2026-04-15",
  "sourceType": "attachment_image",
  "files": [
    {
      "fileMasterId": "FILEMSTER_00170235",
      "fileId": "185417",
      "fileName": "2026 리플렛 앞면(이용안내)수정.jpg",
      "contentType": "image/jpeg"
    }
  ],
  "ocrText": "...",
  "extractedFacts": {
    "roomPrices": [],
    "discountPolicy": [],
    "waterPlay": null,
    "barbecue": null,
    "reservationNotes": []
  },
  "needsReview": true
}
```

## 구현 시 주의점

- 공지 메뉴는 반드시 `menuNm == "공지사항"` 기준으로 선택한다.
- 첨부 없는 공지도 많으므로 HTML 본문 수집을 먼저 수행한다.
- `Content-Type`만 믿지 말고 `file` 시그니처 또는 매직바이트도 확인한다.
- OCR 결과는 원문 공지와 파일 ID를 함께 저장해 추적 가능하게 만든다.
- 요금/예약/휴장 정보는 공지에서 임시 변경사항으로 올라올 수 있으므로 기존 숙소/예약 정책 데이터보다 최신성이 높을 수 있다.
- OCR은 100% 신뢰하기 어렵다. 가격, 날짜, 전화번호, 운영중지 기간은 정규식 검증과 관리자 검수 플래그가 필요하다.
