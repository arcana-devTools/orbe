# Troca a mao do PC pela versao do servidor e sobe de novo. Sem abrir pagina.
$ErrorActionPreference = "Stop"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]3072 } catch {}
$ProgressPreference = "SilentlyContinue"
$dir = Join-Path $env:LOCALAPPDATA "OrbeMao"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$dest = Join-Path $dir "pc.ps1"
Invoke-WebRequest -Uri "https://orbe-xfzn.onrender.com/mao/pc.ps1" -OutFile $dest -UseBasicParsing
Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" | Where-Object {
  $_.CommandLine -like "*OrbeMao*pc.ps1*"
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
$vbs = Join-Path $dir "ligar.vbs"
$args = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$dest`""
for ($i = 0; $i -lt 3; $i++) {
  if (Test-Path $vbs) {
    Start-Process -FilePath "wscript.exe" -ArgumentList "`"$vbs`"" -WindowStyle Hidden
  } else {
    Start-Process -FilePath "powershell.exe" -ArgumentList $args -WindowStyle Hidden
  }
  Start-Sleep -Seconds 5
  $vivo = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" | Where-Object {
    $_.CommandLine -like "*OrbeMao*pc.ps1*"
  }
  if ($vivo) { break }
}
if (-not $vivo) {
  Write-Output "nao subiu escondida, abrindo na janela"
  powershell -NoProfile -ExecutionPolicy Bypass -File $dest
} else {
  Write-Output "atualizei"
}
