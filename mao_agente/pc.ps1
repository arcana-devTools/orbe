# Mao do Orbe no PC Windows. So abre aba/app, print, clique e tecla. Sem shell da rede.
param(
  [Parameter(Mandatory = $true)][string]$Token,
  [string]$Base = "https://orbe-xfzn.onrender.com",
  [string]$Apelido = "pc"
)
$ErrorActionPreference = "Stop"
# Windows PowerShell 5.1 nasce em TLS 1.0 e o Render recusa. Sem isto, irm e o poll quebram.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]3072 } catch {}
$ProgressPreference = "SilentlyContinue"
$Base = $Base.TrimEnd("/")
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class OrbeMao {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, int e);
}
"@

function Invoke-Orbe([string]$Metodo, [string]$Url, $Corpo) {
  $h = @{ "x-orbe-mao" = $Token }
  if ($Corpo -ne $null) {
    $json = $Corpo | ConvertTo-Json -Compress
    return Invoke-RestMethod -Method $Metodo -Uri $Url -Headers $h -Body $json -ContentType "application/json; charset=utf-8" -TimeoutSec 40
  }
  return Invoke-RestMethod -Method $Metodo -Uri $Url -Headers $h -TimeoutSec 40
}

function Executa($cmd) {
  $acao = [string]$cmd.acao
  $alvo = [string]$cmd.alvo
  if ($acao -eq "abrir_url") {
    if ($alvo -notmatch '^https://') { return $false, "url recusada", "" }
    Start-Process $alvo
    return $true, "abri a aba", ""
  }
  if ($acao -eq "abrir_app") {
    if ($alvo -notmatch '^[a-z0-9 ]+$') { return $false, "app recusado", "" }
    Start-Process $alvo
    return $true, "abri $alvo", ""
  }
  if ($acao -eq "print") {
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Jpeg)
    $b64 = [Convert]::ToBase64String($ms.ToArray())
    $g.Dispose(); $bmp.Dispose(); $ms.Dispose()
    if ($b64.Length -gt 1800000) { return $true, "print grande demais", "" }
    return $true, "print", $b64
  }
  if ($acao -eq "clicar") {
    $x = [int]$cmd.extra.x; $y = [int]$cmd.extra.y
    [OrbeMao]::SetCursorPos($x, $y) | Out-Null
    [OrbeMao]::mouse_event(2, 0, 0, 0, 0)
    [OrbeMao]::mouse_event(4, 0, 0, 0, 0)
    return $true, "cliquei", ""
  }
  if ($acao -eq "digitar") {
    if ($alvo -match '[`$;|&]') { return $false, "texto recusado", "" }
    [System.Windows.Forms.SendKeys]::SendWait($alvo)
    return $true, "digitei", ""
  }
  if ($acao -eq "tecla") {
    $map = @{ enter = "{ENTER}"; tab = "{TAB}"; esc = "{ESC}"; backspace = "{BS}"; space = " " }
    if (-not $map.ContainsKey($alvo)) { return $false, "tecla recusada", "" }
    [System.Windows.Forms.SendKeys]::SendWait($map[$alvo])
    return $true, "tecla", ""
  }
  return $false, "acao desconhecida", ""
}

Write-Host "mao pc ligada em $Base"
while ($true) {
  try {
    $fila = Invoke-Orbe GET "$Base/api/mao/fila?aparelho=$Apelido" $null
    if ($fila.comando) {
      $ok, $resumo, $img = Executa $fila.comando
      $corpo = @{ id = $fila.comando.id; ok = [bool]$ok; resumo = [string]$resumo; aparelho = $Apelido }
      if ($img) { $corpo.imagem = $img }
      Invoke-Orbe POST "$Base/api/mao/resultado" $corpo | Out-Null
      Write-Host "$(if ($ok) {'ok'} else {'falhou'}) $resumo"
    }
  } catch {
    Write-Host "sem ligacao"
    Start-Sleep -Seconds 5
  }
}
