param(
    [string]$EdgeHost = "10.20.13.157",
    [string]$EdgeUser = "n2sl",
    [string]$RemoteCert = "/home/n2sl/yeon/qos/pki/output/qos-ca.crt"
)

$ErrorActionPreference = "Stop"

# 관리자 권한 확인
$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)

if (-not $principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)) {
    Write-Error "Run PowerShell as Administrator."
    exit 1
}

# scp 확인
if (-not (Get-Command scp.exe -ErrorAction SilentlyContinue)) {
    Write-Error "scp.exe was not found. Install/enable Windows OpenSSH Client."
    exit 1
}

$TempCert = Join-Path $env:TEMP "qos-ca.crt"

Write-Host "========================================"
Write-Host "[1] Downloading QOS CA from Edge"
Write-Host "========================================"

$RemoteSource = "${EdgeUser}@${EdgeHost}:${RemoteCert}"

& scp.exe $RemoteSource $TempCert

if ($LASTEXITCODE -ne 0) {
    Write-Error "SCP failed."
    exit 1
}

Write-Host ""
Write-Host "========================================"
Write-Host "[2] Checking certificate"
Write-Host "========================================"

$cert = New-Object `
    System.Security.Cryptography.X509Certificates.X509Certificate2($TempCert)

Write-Host "Subject    : $($cert.Subject)"
Write-Host "Issuer     : $($cert.Issuer)"
Write-Host "Thumbprint : $($cert.Thumbprint)"

Write-Host ""
Write-Host "========================================"
Write-Host "[3] Installing QOS CA"
Write-Host "========================================"

$existing = Get-ChildItem Cert:\LocalMachine\Root |
    Where-Object { $_.Thumbprint -eq $cert.Thumbprint }

if ($existing) {
    Write-Host "[QOS-CA] Certificate is already installed."
}
else {
    Import-Certificate `
        -FilePath $TempCert `
        -CertStoreLocation "Cert:\LocalMachine\Root" |
        Out-Null

    Write-Host "[QOS-CA] Certificate installed."
}

Remove-Item $TempCert -Force

Write-Host ""
Write-Host "========================================"
Write-Host "[QOS-CA] Installation complete"
Write-Host "========================================"
Write-Host ""
Write-Host "Restart Chrome/Edge before testing."