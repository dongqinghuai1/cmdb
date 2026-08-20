# Docker Desktop (WSL2) → AnyConnect VPN 路由打通脚本
# 管理员 PowerShell 运行
#
# 原理：
#   WSL2 VM (172.27.128.0/20) -> Windows 宿主机 -> AnyConnect VPN (10.10.13.x)
#   需要在 Windows 上启用 IP 转发 + NAT，让 WSL 容器的流量能通过 VPN 隧道转发
#
# 使用：右键"以管理员身份运行" PowerShell，然后执行本脚本

# ===== 1. 启用 IP 转发（所有相关网卡） =====
Write-Host "[1/5] 启用 IP 转发..." -ForegroundColor Cyan
$adapters = @("vEthernet (WSL (Hyper-V firewall))", "以太网 2")
foreach ($a in $adapters) {
    try {
        Set-NetIPInterface -Forwarding Enabled -InterfaceAlias $a
        Write-Host "  OK: $a"
    } catch { Write-Host "  SKIP: $a ($($_.Exception.Message))" -ForegroundColor Yellow }
}

# 注册表全局开关（重启后仍生效）
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters" -Name "IPEnableRouter" -Value 1
Write-Host "  注册表 IPEnableRouter=1 (重启后仍生效)"

# ===== 2. 获取网络信息 =====
Write-Host "`n[2/5] 获取网络信息..." -ForegroundColor Cyan
$wslAdapter = Get-NetIPAddress -InterfaceAlias "vEthernet (WSL (Hyper-V firewall))" -AddressFamily IPv4 -ErrorAction SilentlyContinue
if (-not $wslAdapter) { Write-Host "ERROR: 找不到 WSL 虚拟网卡" -ForegroundColor Red; exit 1 }
$wslIP = $wslAdapter.IPAddress          # e.g. 172.27.128.1
$wslPrefix = $wslAdapter.PrefixLength   # e.g. 20
$wslNet = [IPAddress]($wslAdapter.IPAddress -replace '\.\d+$', '.0')
Write-Host "  WSL: $wslIP/$wslPrefix (网段 $wslNet)"

$vpnAdapter = Get-NetIPAddress | Where-Object { $_.InterfaceAlias -eq "以太网 2" -and $_.AddressFamily -eq "IPv4" } | Select-Object -First 1
if (-not $vpnAdapter) { Write-Host "ERROR: 找不到 AnyConnect VPN 网卡（确认 VPN 已连接）" -ForegroundColor Red; exit 1 }
$vpnIP = $vpnAdapter.IPAddress  # e.g. 10.10.13.254
Write-Host "  VPN: $vpnIP"

# ===== 3. 创建 NAT（WSL -> VPN） =====
Write-Host "`n[3/5] 配置 NAT..." -ForegroundColor Cyan
# 删除旧 NAT（如果有）
try { Remove-NetNat -Name "DockerVPN" -Confirm:$false -ErrorAction SilentlyContinue } catch {}
# 创建 NAT：把 WSL 网段通过 VPN 接口转发
$maskBytes = ([Math]::Pow(2, $wslPrefix) - 1)
$maskBytes = [IPAddress]([Convert]::ToUInt32($maskBytes) -band 0xFFFFFFFF)
try {
    New-NetNat -Name "DockerVPN" -InternalIPInterfaceAddressPrefix "$wslIP/$wslPrefix" -ErrorAction Stop
    Write-Host "  NAT 已创建: WSL($wslIP/$wslPrefix) -> 外部"
} catch {
    Write-Host "  NAT 创建失败或已存在: $($_.Exception.Message)" -ForegroundColor Yellow
    # 尝试只添加路由
}

# ===== 4. 添加路由（公司网段走 VPN 接口） =====
Write-Host "`n[4/5] 添加公司网段路由..." -ForegroundColor Cyan
# AnyConnect 下发的所有公司路由（从路由表提取走 VPN 接口的目标网段）
$vpnRoutes = route print | Select-String "^\s+(10\.|172\.|192\.168\.)" | ForEach-Object {
    $parts = $_.Line.Trim() -split '\s+'
    if ($parts.Count -ge 5 -and $parts[3] -eq $vpnIP) {
        @{Destination=$parts[0]; Mask=$parts[1]; Gateway=$parts[2]}
    }
}
Write-Host "  发现 $($vpnRoutes.Count) 条 VPN 路由"

# 为 WSL 网段添加到公司网段的静态路由（通过 VPN 网关）
$vpnGateway = ($vpnRoutes | Select-Object -First 1).Gateway
if (-not $vpnGateway) { $vpnGateway = $vpnIP -replace '\.\d+$', '.1' }
Write-Host "  VPN 网关: $vpnGateway"

# 汇总路由：把 10.0.0.0/8 全走 VPN（如果你公司还有其他网段，手动添加）
route add -p 10.0.0.0 mask 255.0.0.0 $vpnGateway metric 1 if $vpnAdapter.InterfaceIndex 2>&1 | ForEach-Object { Write-Host "  $_" }

# ===== 5. 验证 =====
Write-Host "`n[5/5] 验证连通性..." -ForegroundColor Cyan
Start-Sleep 2
$testIP = Read-Host "输入一个公司内网可达的设备 IP（如 10.10.13.1 或 10.1.1.1）"
if ($testIP) {
    $result = docker exec nops-api python -c "import ping3; ms=ping3.ping('$testIP', timeout=3); print('%.1fms' % ms if ms else 'FAIL')"
    if ($result -match 'FAIL') {
        Write-Host "  容器 -> $testIP : FAIL" -ForegroundColor Red
        Write-Host "  尝试宿主机 ping..."
        ping -n 2 -w 2000 $testIP | Select-String "TTL|超时"
    } else {
        Write-Host "  容器 -> $testIP : $result" -ForegroundColor Green
        Write-Host "  成功！设备现在可以上线了。" -ForegroundColor Green
    }
}

Write-Host "`n===== 完成 =====" -ForegroundColor Cyan
Write-Host @"
如果仍然不通，按顺序排查：
1. 宿主机能 ping 通公司设备吗？  ping 10.1.1.1
2. AnyConnect 设置 -> 防火墙 -> 取消勾选"阻止来自局域网的流量"
3. 管理员运行: netsh interface ip show joins  （看 VPN 是否有 NAT/共享配置冲突）
4. 最后一招：把 AnyConnect 的"VPN Access"里加入 WSL 虚拟网卡（需要管理员在 ASA 侧改）
"@