@echo off
chcp 65001 >nul
title DOGE 币本位 OI 提醒
cd /d "%~dp0"
echo ============================================
echo   DOGE 币本位 OI 提醒  启动器 (Windows)
echo ============================================
echo.
echo  请把这个 .bat 和 doge_oi_alert_v2.py 放在同一个文件夹
echo.

if "%DOGE_TG_TOKEN%"=="" set /p DOGE_TG_TOKEN="粘贴 Bot Token: "
if "%DOGE_TG_CHAT_ID%"=="" set /p DOGE_TG_CHAT_ID="粘贴 Chat ID: "
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 没找到 python, 请先安装 Python 3 并勾选 Add to PATH
  pause
  exit /b 1
)

echo [1/2] 正在自检配置和网络...
python "%~dp0doge_oi_alert_v2.py" --check
echo.
echo --------------------------------------------
echo  若上面 1/2/3 不是全 OK, 先按提示修好再继续
echo --------------------------------------------
echo.
echo  当前 mode.conf 设置:
findstr /b "MODE=" "%~dp0mode.conf" 2>nul
echo.
echo  注意: MODE=actions 时本地进程只判定、不推送 Telegram;
echo        如需本地收到提醒, 请把 mode.conf 改成 MODE=worker
echo.
echo [2/2] 启动监控 (按 Ctrl+C 停止)...
python "%~dp0doge_oi_alert_v2.py"
pause
