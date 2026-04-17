# BGDrop Development Log

개발 과정, 기술 선택의 배경, 주요 의사결정 기록.

## 프로젝트 개요

AI 기반 배경제거 데스크톱 앱. 드래그&드롭으로 즉시 배경 제거, 포터블 실행 파일로 배포.

**설계 목표:**
- 설치 없이 바로 실행 (포터블 빌드)
- CPU만으로 충분한 속도 (GPU 비의존)
- 상업 배포 가능 (MIT 모델만 사용)
- 크로스 플랫폼 (Windows/macOS)

---

## 기술 스택 선택 이유

### UI: tkinter + tkinterdnd2

- **tkinter** — Python 기본 포함, 별도 설치 불필요, 포터블 빌드 시 유리
- **tkinterdnd2** — 드래그&드롭 구현. 이 프로젝트의 핵심 UX
- Electron/Qt 대신 선택한 이유: 경량성과 설치 간편함
- 트레이드오프: 모던한 룩앤필은 포기, 기능성 우선

### AI 엔진: rembg + onnxruntime

- **rembg** — 배경제거 전용 래퍼, 여러 모델을 일관된 API로 제공
- **onnxruntime** — CPU에서 충분히 빠름, GPU 의존성 제거
- PyTorch 대신 ONNX로 간 이유: 포터블 빌드 크기, 초기 로드 속도

### AI 모델 선택: ISNet / U2Net 계열만

- 현재 SOTA급인 **BiRefNet / BRIA RMBG**는 CC BY-NC 4.0 → 상업 배포 불가
- MIT 라이선스 모델 중 품질이 가장 좋은 **ISNet**을 기본값으로 선정
- 자세한 라이선스 정리: `docs/AI_MODEL_LICENSE_NOTES.md`

---

## 버전 히스토리

### v1.0 — 초기 릴리즈
- 드래그&드롭 배경제거 기본 기능
- ISNet/U2Net 모델 선택
- 포터블 PyInstaller 빌드

### v1.1 — UI 폴리시 & 성능 개선
- 줌/팬 성능 개선 — 캐시(1200px) 기반 fast render → 멈추면 sharp render
- 파이프라인 다듬기 (Alpha Clean 로직 정리)
- **의사결정**: `show_after`에서 Before 캐시는 건드리지 않도록 분리 → 토글 성능 대폭 향상

### v1.2 — 크로스 플랫폼 지원
- macOS 대응 + Windows ARM 네이티브 빌드
- 플랫폼별 분기를 `ui/platform.py`에 집약 (`FONT_FAMILY`, `HAS_DND`, `IS_WINDOWS`, `IS_MACOS`)
- **의사결정**: 플랫폼 분기를 한 파일로 모아 분산 방지

### v1.3 — macOS 호환성 & 이미지 처리 개선
- 줌 슬라이더 추가 (키보드 단축키 외 마우스 UI 제공)
- EXIF 회전 처리 (iPhone 등 모바일 사진 자동 정방향)
- 이미지 크기 제한 핸들링 (초대형 이미지 자동 축소)

---

## Tauri 이주 — v2.x 시리즈

> Python(tkinter) → Rust + Tauri 2 + SvelteKit 전면 이주.
> 배포 크기: ~380MB(PyInstaller) → 앱 자체 ~8MB (모델 별도)

### 환경 구성
- **스택**: Tauri 2.10.1, Rust 1.95.0 (MSVC), Node.js 24.14.0, SvelteKit
- **ONNX**: ort 2.0.0-rc.12 (download-binaries feature)
- **dev port**: 1430 (다른 Tauri 앱과 포트 충돌 방지)
- **모델**: `~/.u2net/*.onnx` → `BgDrop/models/`로 복사해 사용

### v2.0 (P1) — 앱 셸 + 드롭존 + 이미지 표시
- Tauri 2 + SvelteKit 스캐폴드
- 파일 드롭/클릭 브라우저로 이미지 로드 (asset protocol)
- Before/After 패널 (기본 줌/팬)
- 상태바 + Reset 버튼

### v2.1 (P2) — Rust ONNX 배경 제거
- ort 2.0.0-rc.12로 ISNet/U2Net ONNX 추론 구현
- 전처리: NCHW Vec<f32>, sigmoid 마스크, 모델별 입력 크기 (ISNet 1024, U2Net 320)
- 세션 캐싱 (모델별 한 번만 로드)
- 결과: base64 PNG로 프런트 전달
- **의사결정**: ndarray 대신 `(Vec<i64>, Vec<f32>)` 튜플로 ORT 텐서 생성 (ort rc.12 API 호환)

### v2.2 (P3) — 파이프라인 컨트롤 + BG 색상 + 저장
- 모델 선택 (ISNet/U2Net/Portrait)
- Post Process Mask: Rust morphological close+open 직접 구현
- Alpha Clean 체크박스 + lo/hi 슬라이더 (재추론 없이 즉시 재적용)
- BG 색상: Checker/White/Black/Chroma(#00ff00)/Custom — Python 버전과 동일
- Before 패널도 BG 색상 공유 (원본이 투명하지 않음을 시각적으로 표시)
- Save (PNG/WebP, BG 합성 포함)
- **의사결정**: Alpha Clean lo/hi를 Rust 앱 상태(last_raw)로 저장 → 슬라이더 변경 시 재추론 없이 재적용

### v2.3 (P4) — Auto Selector (Smart Match)
- 이미지 분석: Sobel gradient(엣지 밀도) + Kovac rule(피부색 비율)
- 6개 사전 정의 조합 → 휴리스틱으로 4개 선택
- 시뮬레이션: 512px 다운스케일, Tauri 이벤트(`sim-result`)로 스트리밍
- AutoPanel: 썸네일 갤러리, Claude Code amber(#d97757) thinking 텍스트
- 썸네일 클릭 → `tick()` 후 즉시 미리보기 → 백그라운드 풀해상도 처리
- 메인 창 로딩: 원형 스피너 → 하단 shimmer 막대 바
- **의사결정**: 24조합 전체 탐색 대신 6개 레시피 + 휴리스틱 (속도 vs 정확도 트레이드오프)

---

## 주요 의사결정 기록

### 파이프라인 구성

**ISNet/U2Net → Post Process Mask → Alpha Clean → Alpha Matting**

실험 결과:
- Post Process Mask + Alpha Clean **단독**: 각각 50~60% 품질 개선
- **병용** 시: 90% 품질 (시너지 효과)
- Alpha Matting은 2~3배 느리지만 머리카락/털 경계에 효과적
- ISNet이 U2Net보다 경계 품질 우수 → 기본값

### 이미지 로드 전략

- **RGBA 보존** (Before 표시용) + **RGB 변환** (rembg 처리용) **분리 보관**
- rembg는 RGB만 받지만, Before 미리보기엔 원본 알파 유지가 필요
- 단일 버퍼로 운영 시 변환 반복으로 성능/품질 손실 발생

### 편집화면 조작 분리

- 줌: `Ctrl+wheel`, 팬: `Ctrl+drag`
- 크롭/모자이크 도구 조작과 분리해야 충돌 없음 → 모디파이어 키로 구분

### 배경색 렌더링

- 체커보드 = 투명 그대로 (UI 표시용)
- 단색 배경 선택 시 저장 결과에도 반영
- 사용자가 "이 색상으로 배경 채운 PNG"를 바로 받을 수 있음

---

## 개발 환경 정착 과정

### Python 버전 관리

- 초기: Python 3.10으로 시작
- v1.3 이후: Python 3.13으로 업그레이드 (최신 기능 + 성능)
- **이슈**: 시스템에 3.10이 이미 설치된 상태에서 3.13 추가 시 PATH 순서 문제 발생
  - 시스템 PATH가 사용자 PATH보다 먼저 검색됨
  - 해결: 시스템 PATH에서 3.13을 3.10보다 위로 배치

### 가상환경

- `.venv` (VS Code 기본값, 현대 Python 관례) 사용
- VS Code 인터프리터 선택 → 자동 활성화 (새 터미널 한정)

---

## 알려진 버그

- **After 라벨이 Before 쪽으로 밀리는 현상** — header grid 레이아웃 이슈, 창 크기에 따라 재현 (v1.3 시점 미해결)

---

---

# 향후 계획

## 진행 예정 (Next)

### ✅ 완료된 항목
- Tauri 이주 P1~P4 (앱 셸, ONNX 추론, 파이프라인 컨트롤, Auto Selector)
- 폴더 구조 재편: `python/` (레거시) + `tauri/` (현재) 분리

### 🔜 미완성 / 다음 작업

#### Edit Panel 이식
- Python 버전의 Crop + Mosaic 도구를 Tauri/Svelte로 포팅
- `python/ui/edit_panel.py` 참조

#### Alpha Matting 구현
- pymatting 알고리즘의 Rust 포팅 또는 대안 탐색
- 현재 UI만 있고 기능은 disabled

#### Auto Selector 선별 로직 강화
- 현재: Sobel + Kovac 픽셀 통계 휴리스틱
- 개선안: MobileNet-SSD ONNX (Apache 2.0, ~7MB) — 이미 ort 크레이트 보유
- "person 감지됨 → u2net_human_seg 우선" 판단이 Kovac보다 정확할 것

#### Alpha Clean 튜닝
- 현재 기본값 lo=80, hi=200 — 최적값 미확정
- 슬라이더로 조정 가능하도록 구현됨 → 테스트 후 디폴트 확정 필요

### 🛒 상용(비상업 제약) 고품질 모델 선택지 추가

**BiRefNet / BRIA RMBG** 등 CC BY-NC 4.0 모델을 별도 옵션으로 추가.

- **배경**: MIT 모델(ISNet/U2Net)로 90% 품질 도달했지만, 최신 SOTA 모델 대비 경계 디테일 차이는 존재. 개인용·비상업 사용자에게는 최고 품질 선택지를 주는 게 합리적.
- **구현 방향**:
  - 기본은 MIT 모델 유지 (상업 배포 호환성)
  - UI에 "프리미엄 모델" 섹션 분리 + 라이선스 경고 고지 모달
  - 모델 파일은 앱 내장하지 않고 **사용자가 수동 다운로드** 또는 최초 사용 시 동의 후 다운로드
  - 자동 프리셋에도 후보로 포함 (라이선스 동의 플래그 기준)
- **주의**: CLAUDE.md 규칙("MIT만 사용")과 충돌 → 규칙을 "기본 모델은 MIT, 확장 모델은 사용자 동의 기반"으로 수정 필요

### 📦 실행 파일 경량화 — 패키징/언어 대안 모색

**현재 상태**: PyInstaller 빌드 50MB(Online) / 230MB(Offline) — 데스크톱 앱으로는 무거움.

**조사 대상:**

| 방식 | 예상 효과 | 리스크 |
|---|---|---|
| **Nuitka** (Python → C 컴파일) | 시작 속도↑, 크기 비슷 | PyInstaller 대비 호환성 이슈 가능 |
| **Pyoxidizer** | 단일 바이너리, 빠른 시작 | tkinter/onnxruntime 번들 복잡 |
| **briefcase (BeeWare)** | 진짜 네이티브 배포 | tkinter 앱은 비권장 |
| **PyInstaller 최적화** (onefile, UPX, exclude) | 기존 크기에서 30~50% 감량 가능 | 디버깅 어려움, UPX는 안티바이러스 오탐 |
| **Tauri + Rust + rembg CLI** | ~20MB, 빠름 | 현재 Python 코드 전면 재작성 |
| **Electron** | 웹 UI 사용 가능 | 크기 오히려 증가 (100MB+) |

**우선 순위:**
1. PyInstaller 최적화 (exclude 리스트 다듬기) — 1순위, 기존 파이프라인 유지하며 효과적
2. Nuitka 실험 — 2순위, 코드 수정 최소
3. Tauri 포팅 — 3순위, 장기 옵션 (UI 모던화 겸)

#### 🔀 전면 이주 시 3가지 스택 비교 (개인 메모)

BgDrop의 UI 자유도/크기/시작속도를 근본적으로 개선할 3가지 후보를 검토.

##### 총평 (요약)

| 스택 | 바이너리 | 시작 | 외관 자유도 | 학습 비용 | BgDrop 적합도 |
|---|---|---|---|---|---|
| **Python + PyInstaller (현재)** | 380MB | 10초 | 중 (tkinter 제약) | 없음 (유지) | ⭐⭐ |
| **C# + Avalonia** | ~40-60MB | <1초 | 중상 (Fluent + XAML 스타일) | 중 (C# + XAML) | ⭐⭐⭐⭐⭐ |
| **Rust + Tauri** | ~15MB | <0.5초 | **최상** (HTML/CSS/JS 전면) | 상 (Rust + 웹프런트) | ⭐⭐⭐⭐ |

##### Python + PyInstaller (현재)

**장점**
- 코드 유지 비용 0 — 이주 공수 없음
- rembg/PIL/numpy/scipy 생태계 유지, ML 관련 실험 용이

**단점**
- 바이너리 **380MB** (onnxruntime + numpy + scipy + numba 등 누적)
- 시작 10초 (onedir 언팩 + Python 초기화 + 의존성 import)
- tkinter UI 자유도 낮음 (모던 애니메이션/스타일링 약함)
- 플랫폼별 패키징 장애 (pymatting metadata, tkdnd 로딩 이슈 등 반복)

##### C# + Avalonia

**장점**
- **ONNX Runtime C# 바인딩이 first-class** — 파이썬만큼 깔끔
- 크로스플랫폼 (Win/Mac/Linux) 유지
- 바이너리 **40-60MB**, 시작 **<1초**
- XAML + MVVM 패턴이 UI/로직 분리에 명확
- Visual Studio/Rider 도구가 Python 대비 압도적 (리팩토링/디버깅)
- C 경험자에게 C# 문법/개념 이해가 빠름

**단점**
- XAML 스타일링은 CSS보다 verbose, 디자인 에셋 생태계 좁음
- Fluent 기본 테마는 깔끔하지만 "트렌디"한 느낌은 Tauri보다 덜함
- 완전히 새로운 언어/GUI 패러다임 학습 필요
- Win32 경험자 기준: **WindowProc/메시지 루프가 사라져서 디스패치 흐름이 추상화됨** — 당황 포인트

**BgDrop 관점**
- 실용적인 "파이썬에서 벗어나 빠르게 완성" 경로
- 외관은 현재보다 크게 나아지지만, Tauri만큼 화려하진 않음

##### Rust + Tauri

**장점**
- 바이너리 **~15MB** (충격적), 시작 **<0.5초**
- UI는 HTML/CSS/JS → **외관 자유도 최상** (Tailwind, shadcn/ui, Framer Motion 등 모두 가능)
- BgDrop의 "썸네일 갤러리 + Before/After + 드래그드롭" 패턴은 웹 UI가 홈그라운드 (Canvas, CSS filter, object-fit, 브라우저 DnD API 등)
- `ort` crate로 ONNX Runtime Rust 바인딩 사용 가능
- 완성 후 **배포 편의성 + 사용자 경험 최고 수준**

**단점**
- **학습 비용 가장 큼**: Rust(소유권/라이프타임) + 웹 프런트(React/Svelte 등) + Tauri IPC — 3축 동시 학습
- ONNX Rust 바인딩은 파이썬/C# 대비 API 거침, 문서 빈약
- 빌드 파이프라인 복잡 (rustup, cargo, Node.js, bundler 모두 필요)
- 디버깅은 프런트/백엔드 2개 도구 필요

**BgDrop 관점**
- 이 프로젝트가 "학습 도구 + 완성도 있는 결과물" 두 역할을 한다면 최적
- 러닝 자체를 즐기는 스타일이면 BgDrop 이주는 훌륭한 실전 프로젝트

##### 내 생각 요약

- **"빨리 끝내고 다른 프로젝트 하고 싶다"** → C# + Avalonia
- **"이 프로젝트를 브랜드 있는 앱으로 키우고 싶다 + Rust 배워볼 때"** → Rust + Tauri
- **"Python은 이 도메인에선 이미 우회적(ONNX는 C++)으로 돌고 있어 이주 명분은 충분"** — 어느 쪽이든 이주는 정당화됨

**타협안 검토 (Tauri + Python 백엔드)**
- UI만 Tauri, AI는 파이썬 서브프로세스 호출
- 장점: Rust 최소화하면서 UI 외관 챙김
- 단점: Python 런타임 포함해야 해서 바이너리 경량화 이득 사라짐, 아키텍처 복잡
- **비추천** — 갈 거면 Rust까지, 아니면 C#로 실용적으로.

---

### 🎯 자동 조합 선택 기능

이미지별로 최적의 모델 + 파이프라인 옵션 조합을 자동 추천 / 선택.

**배경:**
- 이미지 특성(인물/제품/복잡한 엣지 등)에 따라 최적 조합이 다름
- 현재는 사용자가 직접 조합을 바꿔가며 테스트해야 함 → 품질 편차 발생

**접근 방식:**

```
원본 드롭
  ↓
① 축소 이미지 생성 (512px 미리보기)
  ↓
② [1단계: 선별] 축소본으로 빠른 판단
   - MediaPipe: 얼굴/인체 감지
   - OpenCV: 엣지 복잡도, 콘트라스트
   → 후보 조합 3~4개로 압축
  ↓
③ [2단계: 시뮬레이션] 후보만 축소본에서 실제 실행
  ↓
④ 썸네일 갤러리로 사용자에게 제시
  ↓
⑤ 선택된 조합을 원본 해상도에 적용
```

**이득:**
- 선별 덕분에 시뮬레이션 횟수 최소화 (20+ → 3~4개)
- 축소 이미지 덕분에 시뮬레이션 1~2초/조합
- 사용자 경험: "드롭 → 잠깐 대기 → 4개 중 클릭 → 완료"

**구현 고려사항:**
- MediaPipe는 별도 의존성 (설치 크기 증가 검토 필요)
- 휴리스틱 규칙은 코드에 직접 기술 (별도 모델 학습 불필요)
- 사용자가 자동 모드 / 수동 모드 토글 가능하도록

## 차후 계획 (Future)

### 🔜 Outpainting 전단 추가 — 잘린 얼굴/부분 복원

원본 이미지 가장자리에서 잘린 인물/얼굴/오브젝트를 AI로 확장 복원.

**파이프라인 위치: 배경제거 *앞* 에 배치**
```
원본 → [Outpainting] → 배경제거 → ...
```
배경제거 *뒤* 에 두면 투명 배경 상태라 모델이 맥락을 파악 못함. 반드시 전단.

**후보 모델:**

| 모델 | 라이선스 | 크기 | 품질 | 비고 |
|---|---|---|---|---|
| **LaMa** | Apache 2.0 ✅ | 경량 | 단순 채우기 양호 / 의미 이해 약함 | 상업용 OK |
| **Stable Diffusion Inpaint/Outpaint** | Open RAIL-M (주의) | 2~4GB | 최고, 잘린 얼굴 복원 가능 | GPU 권장, 설치 크기 증가 |
| **CodeFormer / GFPGAN** | — | 중간 | **잘린 부분 생성 불가** | 얼굴 "복원"(손상 복구) 용도, 혼동 주의 |

**구현 고려사항:**
- 현재 BgDrop은 CPU 기반 경량 앱 → SD 추가 시 설치 크기 급증
- 별도 옵션으로 분리, 필요 시만 실행 + 모델 필요 시 다운로드
- 이 기능 자체가 별도 프로젝트 규모 → 자동 조합 선택 완성 후 착수

## 장기 아이디어 (Ideas)

- **조합 학습**: 사용자 선택 데이터가 쌓이면 자동 선별 규칙을 실제 ML로 고도화
- **자동 품질 스코어링**: ground truth 없이 알파 채널 통계(엣지 부드러움, 구멍 개수 등)로 조합 품질 자동 평가
- **배치 처리**: 여러 이미지를 동일 조합으로 한 번에 처리
- **설정 프리셋 저장**: 사용자가 자주 쓰는 조합을 이름 붙여 저장
