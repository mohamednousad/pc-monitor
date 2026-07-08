@echo off
echo ============================================
echo   PC Performance Monitor - Build Script
echo ============================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)

echo [1/3] Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)
echo.

echo [2/3] Building executable...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "PC-Monitor" ^
    --add-data "C:\Python*\Lib\site-packages\customtkinter;customtkinter" ^
    main.py

if %errorlevel% neq 0 (
    echo.
    echo NOTE: If the --add-data path failed, run this to find your customtkinter path:
    echo   python -c "import customtkinter; print(customtkinter.__path__[0])"
    echo Then replace the --add-data line with:
    echo   --add-data "YOUR_PATH;customtkinter"
    echo.
    echo Trying alternative build...
    for /f "delims=" %%i in ('python -c "import customtkinter; print(customtkinter.__path__[0])"') do set CTK_PATH=%%i
    pyinstaller ^
        --onefile ^
        --windowed ^
        --name "PC-Monitor" ^
        --add-data "%CTK_PATH%;customtkinter" ^
        main.py
)
echo.

if exist "dist\PC-Monitor.exe" (
    echo [3/3] Build successful!
    echo.
    echo   Output: dist\PC-Monitor.exe
    echo   Size:   
    for %%A in ("dist\PC-Monitor.exe") do echo     %%~zA bytes
    echo.
    echo You can distribute this single .exe file.
) else (
    echo ERROR: Build failed. Check output above for details.
)

echo.
pause
