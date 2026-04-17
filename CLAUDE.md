# CLAUDE.md — BGDrop Development Guide

## Project Overview
AI-powered background remover desktop app.
- **레거시**: Python (tkinter + rembg) — `python/` 디렉터리 (참조용)
- **현재 개발 중**: Rust + Tauri — `tauri/` 디렉터리
Working directory: `BgDrop/` only. Do not create/modify files outside.

## Folder Structure
```
BgDrop/
├── python/         # Python 앱 (레거시, 참조용)
│   ├── core/       # remover, auto_selector, simulator
│   ├── ui/         # tkinter UI 컴포넌트
│   └── main.py
├── tauri/          # Tauri 앱 (현재 개발 중)
│   ├── src/        # SvelteKit 프런트엔드
│   │   ├── lib/    # DropZone, ImagePanel, AutoPanel 컴포넌트
│   │   └── routes/ # +page.svelte (메인 페이지)
│   ├── src-tauri/  # Rust 백엔드
│   │   └── src/lib.rs  # 모든 Tauri 커맨드
│   ├── vite.config.js  # dev port: 1430
│   └── package.json
├── models/         # ONNX 모델 파일 (gitignored, ~/.u2net/에서 복사)
├── assets/         # 아이콘 등
└── docs/
```

## Tauri App (tauri/) — 현재 메인
- **스택**: Tauri 2 + SvelteKit + TypeScript / Rust (ort 2.0.0-rc.12)
- **실행**: `cd tauri && npm run tauri dev`
- **dev port**: 1430 (다른 Tauri 앱과 충돌 방지)
- **모델 경로**: `BgDrop/models/*.onnx` (dev 시 CARGO_MANIFEST_DIR 기준)

## Tauri Architecture

### Rust (src-tauri/src/lib.rs)
```
ModelCache              # 세션 캐시 (모델별 한 번만 로드) + last_raw 저장
run_pipeline_raw()      # ONNX 추론 → raw RGBA (alpha clean 미적용)
do_alpha_clean()        # lo/hi 임계값으로 알파 채널 재매핑
post_process_mask()     # morphological close+open (노이즈 제거)
analyze_image()         # 엣지 밀도 + 피부색 휴리스틱 → 후보 조합 반환
start_simulations()     # 스레드에서 후보 시뮬레이션, Tauri 이벤트로 결과 전송
reapply_alpha_clean()   # 재추론 없이 alpha clean 파라미터만 재적용
remove_background()     # 메인 배경 제거 커맨드 (raw 저장 포함)
save_result()           # 파일 저장 다이얼로그 + BG 합성
```

### Svelte 컴포넌트 (src/lib/)
```
DropZone.svelte     # 드래그&드롭 / 클릭 브라우저
ImagePanel.svelte   # Before/After 이미지 패널 (줌/팬, 하단 progress bar)
AutoPanel.svelte    # Auto Selector 썸네일 갤러리 (이벤트로 수신)
```

## Pipeline Flow (Tauri)
Model → Post Process Mask (morphological) → Alpha Clean (lo/hi 슬라이더) → [Alpha Matting: 미구현]

- lo 미만 → 완전 투명, hi 초과 → 완전 불투명, 사이는 선형 보간
- Alpha Clean lo/hi 기본값: lo=80, hi=200 (튜닝 필요)
- ISNet: 1024×1024 입력, U2Net: 320×320 입력
- 전처리 resize: Triangle (bilinear, 속도 우선)

## Auto Selector
- 이미지 분석: Sobel gradient(엣지 밀도) + Kovac rule(피부색 비율)
- 6개 사전 정의 조합에서 4개 선택 (휴리스틱 기반, 24조합 전체 탐색은 아님)
- 시뮬레이션: 512px 다운스케일로 각 후보 실행 → Tauri 이벤트로 스트리밍
- 썸네일 클릭 → 즉시 미리보기(tick() 후) → 백그라운드 풀해상도 처리

## Known Issues / TODO
- [ ] Alpha Matting 미구현 (pymatting → Rust 포팅 복잡)
- [ ] Edit Panel (Crop/Mosaic) 미이식 — Python 버전 참조
- [ ] Auto Selector 선별 로직 개선 — MobileNet-SSD ONNX로 교체 고려
- [ ] 상용 모델 추가 — BiRefNet (CC BY-NC 4.0, 라이선스 동의 모달 필요)
- [ ] 속도 최적화 — base64 PNG 인코딩 병목, temp file 방식으로 전환 고려

## Python App (python/) — 레거시 참조용
- Python 3.13, tkinter + tkinterdnd2, rembg (ISNet/U2Net), Pillow, onnxruntime
- 실행: `cd python && python main.py`
- 빌드: `cd python && build.bat` (Windows) / `build.sh` (macOS)

## Rules
- 버전 숫자 변경, git push는 반드시 사용자에게 먼저 물어볼 것
- 라이선스: MIT 모델만 기본 사용 (u2net, isnet-general-use, u2net_human_seg)
  - BiRefNet/BRIA RMBG는 CC BY-NC 4.0 → 사용자 동의 기반으로만 추가 가능
- BgDrop/ 내부에서만 작업
