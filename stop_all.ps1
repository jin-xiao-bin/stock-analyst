# 一键停止：停掉后端(8300)与桌面宠物进程
# 用法：.\stop_all.ps1

Write-Host "[停止] 后端 (端口 8300)..." -ForegroundColor Yellow
$conn = Get-NetTCPConnection -LocalPort 8300 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $conn | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
        try { Stop-Process -Id $_ -Force; Write-Host "  已停止 PID $_" }
        catch { Write-Host "  停止失败: $_" -ForegroundColor Red }
    }
} else {
    Write-Host "  后端未在运行"
}

Write-Host "[停止] 桌面宠物..." -ForegroundColor Yellow
# 宠物特征：python 进程且命令行含 desktop\main.py
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*desktop*main.py*" } |
    ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -Force; Write-Host "  已停止 PID $($_.ProcessId)" }
        catch { Write-Host "  停止失败: $_" -ForegroundColor Red }
    }

Write-Host "`n全部停止完成" -ForegroundColor Cyan
