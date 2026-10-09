# 一键启动：后端 + 桌面宠物（避免端口冲突与重复实例）
# 用法：右键"使用 PowerShell 运行"，或在终端执行 .\start_all.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. 后端：8300 端口已被占用则跳过（说明已在运行）
$portBusy = Get-NetTCPConnection -LocalPort 8300 -State Listen -ErrorAction SilentlyContinue
if ($portBusy) {
    Write-Host "[跳过] 后端已在运行 (端口 8300)" -ForegroundColor Yellow
} else {
    Write-Host "[启动] 后端..." -ForegroundColor Green
    Start-Process -WindowStyle Hidden -FilePath "python" `
        -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8300" `
        -WorkingDirectory "$root\backend"
    Start-Sleep 4
}

# 2. 桌面宠物：通过互斥锁防重复（pet 自带单实例锁，重复启动会自行退出）
Write-Host "[启动] 桌面宠物..." -ForegroundColor Green
Start-Process -FilePath "python" -ArgumentList "main.py" -WorkingDirectory "$root\desktop"

Write-Host "`n完成！浏览器打开 http://localhost:5173 ｜ 宠物在屏幕右下角" -ForegroundColor Cyan
