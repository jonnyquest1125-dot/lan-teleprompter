@echo off
setlocal
rem ============================================
rem  提词器 - 局域网启动脚本(双击运行)
rem  手机/平板须与本机在同一 Wi-Fi/局域网
rem  iPhone/iPad: Safari 打开地址 -> 分享 -> 添加到主屏幕
rem ============================================
cd /d "%~dp0"
set "PORT=8000"
set "PY="

rem --- 双击启动时 PATH 里只有商店占位符, 必须用绝对路径找真 Python ---
call :try "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
call :try "%APPDATA%\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe"
call :try "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
call :try "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

set "IP="
for /f "delims=" %%i in ('powershell -NoProfile -Command "$a=@(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like '192.168.*' }); if($a.Count -eq 0){$a=@(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '169.254.*' -and $_.IPAddress -ne '127.0.0.1' })}; if($a.Count -gt 0){Write-Host $a[0].IPAddress}"') do set "IP=%%i"
if "%IP%"=="" set "IP=127.0.0.1"
title 提词器  http://%IP%:%PORT%

echo.
echo   提词器 (端口 %PORT%)
echo   手机/平板看词:  http://%IP%:%PORT%
echo   电脑控台换词:  http://127.0.0.1:%PORT%/pc
echo.
echo   用法:
echo     1) 电脑浏览器打开上面的「电脑控台」, 粘整篇稿子 -^> 切分并发送
echo     2) 手机上那页自动出现第 1 段, 录完点「下一段」(电脑上点也行)
echo.
echo   iPhone / iPad 首次使用:
echo     1) 用 Safari 打开手机地址
echo     2) 点底部「分享」-^> 选「添加到主屏幕」
echo     3) 以后点主屏幕上的「提词器」图标即可打开(全屏无地址栏)
echo   打不开时: 确认手机连的是同一个 Wi-Fi(不是访客网络/手机热点)
echo.
echo   关闭本窗口即停止服务
echo.

if not defined PY (
  echo   [错误] 没找到可用的 Python, 服务无法启动。
  echo          请把本窗口的报错信息截图保存。
  goto :end
)
if /i "%~1"=="check" (
  echo   Python: %PY%
  echo   [check 模式] 未启动服务。
  goto :end
)

netstat -ano | findstr "LISTENING" | findstr ":%PORT%" >nul 2>nul
if not errorlevel 1 (
  echo   [提示] 端口 %PORT% 上已有服务在跑(可能是上次的窗口没关),
  echo          手机直接用上面的地址打开即可。
  goto :end
)

echo   启动中, 请勿关闭本窗口 ...
echo.
"%PY%" "%~dp0server.py"
echo.
echo   服务已停止。
goto :end

:try
if defined PY exit /b
if not exist %1 exit /b
%1 -c "import http.server, json, threading" >nul 2>nul || exit /b
set "PY=%1"
exit /b

:end
echo.
pause
