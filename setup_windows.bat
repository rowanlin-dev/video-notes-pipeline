@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title video-notes-pipeline 一键安装（国内网络 / 无 VPN）
echo ================================================================
echo   video-notes-pipeline 一键安装向导
echo   目标环境：Windows 10，未挂 VPN / 代理
echo   全程使用国内镜像，无需手动下载任何东西
echo ================================================================
echo.

set "PY_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
set "PY_EXE_URL=https://registry.npmmirror.com/-/binary/python/3.11.9/python-3.11.9-amd64.exe"
set "REPO_ZIP=https://ghproxy.net/https://github.com/rowanlin-dev/video-notes-pipeline/archive/refs/heads/main.zip"
set "FFMPEG_ZIP=https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
set "FFMPEG_DIR=C:\ffmpeg"
set "INSTALL_DIR=%USERPROFILE%\video-notes-pipeline"

:: ------------------------------------------------------------------
:: 1) Python（Win10 默认没有，先检测，缺失则从国内镜像静默装）
:: ------------------------------------------------------------------
echo [1/5] 检查 Python 3.9+ ...
where python >nul 2>nul
if errorlevel 1 (
    echo   未检测到 Python，从 npmmirror 下载安装（约 25MB）...
    powershell -NoProfile -Command "Invoke-WebRequest -Uri '%PY_EXE_URL%' -OutFile '%TEMP%\vnp_python.exe'"
    echo   正在静默安装（自动加入 PATH）...
    %TEMP%\vnp_python.exe /quiet PrependPath=1 Include_pip=1 Include_test=0
    :: 把当前用户的 Python 路径补进本会话 PATH
    set "PATH=%LOCALAPPDATA%\Programs\Python\Python311\;%LOCALAPPDATA%\Programs\Python\Python311\Scripts\;%PATH%"
    echo   Python 安装完成。
) else (
    python --version
)
:: 永久把 pip 切到清华源（之后所有 pip 都走国内）
python -m pip config set global.index-url %PY_MIRROR% >nul 2>nul
python -m pip install --upgrade pip -i %PY_MIRROR% >nul 2>nul
echo.

:: ------------------------------------------------------------------
:: 2) 拉代码（用 ghproxy 镜像，免 git 也能装）
:: ------------------------------------------------------------------
echo [2/5] 获取仓库代码（via ghproxy 镜像）...
if exist "%INSTALL_DIR%" (
    echo   已存在 %INSTALL_DIR%，跳过下载。
) else (
    powershell -NoProfile -Command "Invoke-WebRequest -Uri '%REPO_ZIP%' -OutFile '%TEMP%\vnp_repo.zip'"
    powershell -NoProfile -Command "Expand-Archive -Path '%TEMP%\vnp_repo.zip' -DestinationPath '%USERPROFILE%' -Force"
    if not exist "%INSTALL_DIR%" (
        ren "%USERPROFILE%\video-notes-pipeline-main" "video-notes-pipeline"
    )
)
cd /d "%INSTALL_DIR%"
echo   代码目录：%INSTALL_DIR%
echo.

:: ------------------------------------------------------------------
:: 3) FFmpeg（解压到 C:\ffmpeg\bin，pipeline 会自动识别，无需加 PATH）
:: ------------------------------------------------------------------
echo [3/5] 检查 FFmpeg ...
if exist "%FFMPEG_DIR%\bin\ffmpeg.exe" (
    echo   已存在：%FFMPEG_DIR%\bin\ffmpeg.exe
) else (
    echo   下载便携版 ffmpeg（约 50MB）...
    powershell -NoProfile -Command "Invoke-WebRequest -Uri '%FFMPEG_ZIP%' -OutFile '%TEMP%\vnp_ff.zip'"
    powershell -NoProfile -Command "Expand-Archive -Path '%TEMP%\vnp_ff.zip' -DestinationPath '%TEMP%\vnp_ff' -Force"
    if not exist "%FFMPEG_DIR%" mkdir "%FFMPEG_DIR%"
    for /d %%d in ("%TEMP%\vnp_ff\ffmpeg-*") do (
        xcopy "%%d\bin" "%FFMPEG_DIR%\bin\" /E /I /Y >nul
    )
    echo   ffmpeg 已放到 %FFMPEG_DIR%\bin，pipeline 会自动识别。
)
echo.

:: ------------------------------------------------------------------
:: 4) Python 依赖（清华镜像）
:: ------------------------------------------------------------------
echo [4/5] 安装 Python 依赖（清华镜像，可能要几分钟）...
python -m pip install -r scripts/requirements.txt -i %PY_MIRROR%
echo.

:: ------------------------------------------------------------------
:: 5) 预下载 ASR 模型（HF 镜像 + 内存自适应，避免首次跑视频时卡住）
:: ------------------------------------------------------------------
echo [5/5] 预下载 faster-whisper 模型（HF 镜像）...

:: 检测可用内存（GB）
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "& { (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB - [math]::Round(1.5) }"`) do set "AVAIL_GB=%%a"
if "!AVAIL_GB!"=="" set "AVAIL_GB=8"
echo   检测到物理内存：约 !AVAIL_GB! GB

set "HF_ENDPOINT=https://hf-mirror.com"
set "HF_HUB_DISABLE_XET=1"
python -m pip install -U huggingface_hub -i %PY_MIRROR% >nul 2>nul

:: 模型 A：small（稳定运行，效率较好，~2GB）— 内存充裕时用
echo.
echo   下载模型 A：faster-whisper-small（稳定运行，效率较好，约 2GB）
echo     适用场景：内存 ≥ 8GB 的机器，默认 ASR 使用此模型
huggingface-cli download Systran/faster-whisper-small --local-dir models/faster-whisper-small
if errorlevel 1 (
    echo   [提示] small 模型下载失败，可稍后手动重试：
    echo   set HF_ENDPOINT=https://hf-mirror.com ^& huggingface-cli download Systran/faster-whisper-small --local-dir models/faster-whisper-small
) else (
    echo   small 模型下载完成
)

:: 模型 B：base（内存紧张时使用，~0.6GB）— 低内存机器/并行 ASR 时自动切换
echo.
echo   下载模型 B：faster-whisper-base（内存紧张时使用，约 0.6GB）
echo     适用场景：内存 < 8GB 或运行其他应用时，ASR 自动切换到此模型
echo     相比 small 精度略低，但内存占用仅 1/3，速度更快
huggingface-cli download Systran/faster-whisper-base --local-dir models/faster-whisper-base
if errorlevel 1 (
    echo   [提示] base 模型下载失败，可稍后手动重试：
    echo   set HF_ENDPOINT=https://hf-mirror.com ^& huggingface-cli download Systran/faster-whisper-base --local-dir models/faster-whisper-base
) else (
    echo   base 模型下载完成
)

:: 检测结果摘要
echo.
if !AVAIL_GB! GEQ 8 (
    echo   [建议] 内存充足（!AVAIL_GB!GB），默认使用 small 模型即可获得最佳效果。
    echo         运行 ASR 时会自动检测可用内存，紧张时降级到 base 模型。
) else (
    echo   [建议] 内存较紧张（!AVAIL_GB!GB），ASR 会优先使用 base 模型。
    echo         如需更好识别精度，可关闭其他应用后再试 small 模型。
)
echo.

:: ------------------------------------------------------------------
:: 收尾
:: ------------------------------------------------------------------
if not exist .env copy .env.example .env >nul
echo ================================================================
echo   安装完成！下一步：
echo   1) 用记事本打开 %INSTALL_DIR%\.env，填入 VISION_API_KEY
echo      （智谱 GLM 免费档：https://open.bigmodel.cn/）
echo   2) 可选但强烈建议：配置 bilibili_cookies.txt（拿官方字幕）
echo   3) 跑起来：python run_pipeline.py ^<BV号^>
echo   详细用法见 %INSTALL_DIR%\README.md
echo ================================================================
pause
