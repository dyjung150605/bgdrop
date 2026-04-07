# CLAUDE.md — BGDrop Development Guide

## Project Overview
AI-powered background remover desktop app (tkinter + rembg).
Working directory: `BgDrop/` only. Do not create/modify files outside.

## Tech Stack
- Python 3.13, tkinter + tkinterdnd2, rembg (ISNet/U2Net), Pillow, onnxruntime
- Cross-platform: Windows (primary), macOS (supported), Windows ARM (native)
- Platform detection: `ui/platform.py` → `FONT_FAMILY`, `HAS_DND`, `IS_WINDOWS`, `IS_MACOS`

## Architecture
```
main.py                 # Entry point, DPI fix, conditional DnD
core/remover.py         # rembg wrapper, threaded processing, alpha clean
ui/platform.py          # OS detection, font, DnD availability
ui/app_window.py        # Main controller, pipeline, view switching
ui/drop_zone.py         # Drag & drop canvas
ui/result_panel.py      # Before/After preview, zoom/pan, save
ui/edit_panel.py        # Crop + mosaic tools, zoom/pan
ui/bg_combo.py          # Background color selector (horizontal circles)
ui/tooltip.py           # Hover tooltip widget
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
