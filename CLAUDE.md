# CLAUDE.md — BGDrop Development Guide

## Project Overview
AI-powered background remover desktop app.
- **현재**: Python (tkinter + rembg) — `python/` 디렉터리
- **이주 중**: Rust + Tauri — `tauri/` 디렉터리 (환경 준비 후 생성 예정)
Working directory: `BgDrop/` only. Do not create/modify files outside.

## Folder Structure
```
BgDrop/
├── python/         # Python 앱 (레거시, 참조용)
│   ├── core/       # remover, auto_selector, simulator
│   ├── ui/         # tkinter UI 컴포넌트
│   └── main.py
├── tauri/          # Tauri 앱 (이주 대상, 미생성)
├── models/         # ONNX 모델 파일 (gitignored)
├── assets/         # 아이콘 등
└── docs/
```

## Python App (python/)
- Python 3.13, tkinter + tkinterdnd2, rembg (ISNet/U2Net), Pillow, onnxruntime
- 실행: `cd python && python main.py`
- 빌드: `cd python && build.bat` (Windows) / `build.sh` (macOS)
- Platform detection: `ui/platform.py` → `FONT_FAMILY`, `HAS_DND`, `IS_WINDOWS`, `IS_MACOS`

## Python Architecture
```
python/main.py              # Entry point, DPI fix, conditional DnD
python/core/remover.py      # rembg wrapper, threaded processing, alpha clean
python/core/auto_selector.py # 이미지 분석, 파이프라인 후보 선정
python/core/simulator.py    # 다운스케일 시뮬레이션 (멀티스레드)
python/ui/platform.py       # OS detection, font, DnD availability
python/ui/app_window.py     # Main controller, pipeline, view switching
python/ui/auto_dialog.py    # Auto Selector 썸네일 갤러리 다이얼로그
python/ui/drop_zone.py      # Drag & drop canvas
python/ui/result_panel.py   # Before/After preview, zoom/pan, save
python/ui/edit_panel.py     # Crop + mosaic tools, zoom/pan
python/ui/bg_combo.py       # Background color selector (horizontal circles)
python/ui/tooltip.py        # Hover tooltip widget
```

## Pipeline Flow
Model (ISNet/U2Net/Portrait) → Post Process Mask (rembg morphology) → Alpha Clean (threshold remap) → Alpha Matting (edge refinement)

- Post Process Mask + Alpha Clean 병용 시 시너지 효과 (각각 단독 50-60%, 병용 90%)
- Alpha Matting은 2-3x 느림, 머리카락/털 등에 효과적
- ISNet이 U2Net보다 경계 품질 우수

## Key Design Decisions
- `show_after`는 After 캐시만 갱신 (Before 건드리지 않음) — 토글 성능
- 줌: 캐시(1200px) 기반 fast render → 멈추면 sharp render
- 편집화면 줌: Ctrl+wheel, 팬: Ctrl+drag (도구와 분리)
- 이미지 로드: RGBA 보존(Before 표시용), RGB 변환(rembg 처리용) 분리
- 배경색 선택 시 저장에도 반영 (checker=투명 그대로)

## Known Bugs
- [ ] After 라벨이 Before 쪽으로 밀리는 현상 (header grid 레이아웃 이슈, 창 크기에 따라 재현)

## Rules
- 버전 숫자 변경, git push는 반드시 사용자에게 먼저 물어볼 것
- 라이선스 제약: AI 모델은 MIT만 사용 (u2net, isnet-general-use, u2net_human_seg). birefnet/bria-rmbg는 CC BY-NC 4.0이므로 금지
- BgDrop/ 내부에서만 작업
