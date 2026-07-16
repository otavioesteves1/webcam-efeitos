# Gera o executavel portatil WebcamEfeitos (pasta dist\WebcamEfeitos)
# Uso: .\build_exe.ps1   (precisa de: pip install pyinstaller)
Set-Location $PSScriptRoot

python -m PyInstaller --noconfirm --windowed --name WebcamEfeitos `
  --add-data "..\03_MOLDURA-CAM\molduras;molduras" `
  --add-data "..\02_GIF-WEBCAM\sprites;sprites" `
  --add-data "..\01_PIS-CAM\face_landmarker.task;." `
  --collect-all mediapipe `
  --collect-all pyvirtualcam `
  webcam_efeitos_app.py

if ($LASTEXITCODE -eq 0) {
    Compress-Archive -Force -Path "dist\WebcamEfeitos" -DestinationPath "dist\WebcamEfeitos-windows.zip"
    Write-Output "Pronto: dist\WebcamEfeitos-windows.zip"
}
