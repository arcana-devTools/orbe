# Uma vez só. Instala a mão, esconde a janela e sobe sozinha ao entrar no Windows.
param(
  [Parameter(Mandatory = $true)][string]$Token,
  [string]$Base = "https://orbe-xfzn.onrender.com"
)
$ErrorActionPreference = "Stop"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]3072 } catch {}
$ProgressPreference = "SilentlyContinue"
$Base = $Base.TrimEnd("/")
$dir = Join-Path $env:LOCALAPPDATA "OrbeMao"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$script = Join-Path $dir "pc.ps1"
Invoke-WebRequest -Uri "$Base/mao/pc.ps1" -OutFile $script -UseBasicParsing
Set-Content -Path (Join-Path $dir "token.txt") -Value $Token.Trim() -Encoding ascii
$vbs = Join-Path $dir "ligar.vbs"
$linha = 'Set sh = CreateObject("Wscript.Shell")' + "`r`n" +
  'sh.Run "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""' + $script + '""", 0, False' + "`r`n"
Set-Content -Path $vbs -Value $linha -Encoding ascii
$startup = [Environment]::GetFolderPath("Startup")
Copy-Item -Force $vbs (Join-Path $startup "OrbeMao.vbs")
Start-Process -FilePath "wscript.exe" -ArgumentList "`"$vbs`"" -WindowStyle Hidden
Write-Host "Pronto. A mao sobe sozinha quando voce entra no Windows. Pode fechar esta janela."
