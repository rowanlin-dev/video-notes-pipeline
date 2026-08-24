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
:: 5) 预下载 ASR 模型（HF 镜像，避免首次跑视频时卡在 HuggingFace）
:: ------------------------------------------------------------------
echo [5/5] 预下载 faster-whisper 模型（HF 镜像，约 480MB）...
set "HF_ENDPOINT=https://hf-mirror.com"
set "HF_HUB_DISABLE_XET=1"
python -m pip install -U huggingface_hub -i %PY_MIRROR% >nul 2>nul
huggingface-cli download Systran/faster-whisper-small --local-dir models/faster-whisper-small
if errorlevel 1 (
    echo   [提示] 模型下载失败，可稍后手动跑下面这行（不影响基础功能）：
    echo   set HF_ENDPOINT=https://hf-mirror.com ^& huggingface-cli download Systran/faster-whisper-small --local-dir models/faster-whisper-small
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
