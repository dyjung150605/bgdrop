@echo off

echo ============================================
echo [1/2] Building BGDrop-Online (model auto-download)
echo ============================================
pyinstaller ^
  --onedir --windowed ^
  --name BGDrop-Online ^
  --icon assets/icon.ico ^
  --add-data "assets;assets" ^
  --collect-all rembg ^
  --collect-all tkinterdnd2 ^
  --hidden-import onnxruntime ^
  main.py

echo.
echo ============================================
echo [2/2] Building BGDrop-Offline (model bundled)
echo ============================================
echo NOTE: models/u2net.onnx must exist before running this step.
if not exist "models\u2net.onnx" (
  echo ERROR: models/u2net.onnx not found. Download it first.
  echo Download from: https://github.com/danielgatis/rembg
  pause
  exit /b 1
)
pyinstaller ^
  --onedir --windowed ^
  --name BGDrop-Offline ^
  --icon assets/icon.ico ^
  --add-data "assets;assets" ^
  --add-data "models;models" ^
  --collect-all rembg ^
  --collect-all tkinterdnd2 ^
  --hidden-import onnxruntime ^
  main.py

echo.
echo ============================================
echo Build complete.
echo   dist/BGDrop-Online/   ~50MB  (internet required on first run)
echo   dist/BGDrop-Offline/  ~230MB (fully offline)
echo ============================================
pause
