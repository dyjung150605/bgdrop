# BGDrop - AI Background Remover

Portable desktop application for instant AI-powered background removal via drag & drop.

## Features

- **Drag & Drop** or click to browse (JPG, PNG, WebP, BMP)
- **AI Models** (all MIT licensed, commercial use OK)
  - ISNet General Use - high detail, fine edges
  - U2Net - general purpose, fast
  - U2Net Human Seg - portrait optimized
- **Pipeline Controls**
  - Alpha Clean - removes semi-transparent halo artifacts
  - Alpha Matting - refines hair/fur edges (slower, higher quality)
- **Before / After Preview** with synchronized zoom & pan
- **Background Preview** - checker, white, black, chroma green, or custom color
- **Edit Mode** - crop (Shift for square) and mosaic brush (scroll to resize)
- **Save** as PNG (lossless) or WebP (lossless)
- **Portable** - no installation needed (PyInstaller onedir build)

## Quick Start

```bash
# Activate virtual environment
cd BgDrop
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

First run downloads the AI model (~170MB) automatically.

## Build Portable Executables

```bash
build.bat
```

Produces two builds in `dist/`:
- **BGDrop-Online** (~50MB) - downloads model on first run
- **BGDrop-Offline** (~230MB) - model bundled, fully offline

## Requirements

- Python 3.13+
- Windows 10/11

## Dependencies

| Package | License | Purpose |
|---------|---------|---------|
| [rembg](https://github.com/danielgatis/rembg) | MIT | AI background removal |
| [Pillow](https://python-pillow.org/) | MIT-like (HPND) | Image processing |
| [tkinterdnd2](https://github.com/pmgagne/tkinterdnd2) | MIT | Drag & drop support |
| [onnxruntime](https://onnxruntime.ai/) | MIT | AI model inference |
| tkinter | Python PSF | GUI (bundled with Python) |

All AI models used (`isnet-general-use`, `u2net`, `u2net_human_seg`) are **MIT licensed** and free for commercial use.

## License

Copyright (c) 2026 dyjung150605. All rights reserved.

Permission is hereby granted to use this software for personal and commercial purposes, subject to the following conditions:

1. **Modification prohibited** - You may not modify, adapt, or create derivative works of this software without prior written permission from the author.
2. **Redistribution prohibited** - You may not redistribute, sublicense, or share copies of this software in any form without prior written permission from the author.
3. **Attribution required** - Any permitted use must retain this copyright notice and license terms.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.

For licensing inquiries, contact the author via GitHub.
