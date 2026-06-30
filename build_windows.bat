@echo off
setlocal
cd /d %~dp0
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
python -m unittest discover -s tests -v
pyinstaller --noconfirm --clean BitgetPaperScalper.spec
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" installer\BitgetPaperScalper.iss
  echo Installer tersedia di dist-installer\BitgetPaperScalper-Setup.exe
) else (
  echo Inno Setup 6 belum terpasang. EXE tersedia di dist\BitgetPaperScalper.exe
)
pause
