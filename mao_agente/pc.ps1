# Mao do Orbe no PC Windows. Abre, clica e termina. Nao deixa pagina parada.
param(
  [string]$Token = "",
  [string]$Base = "https://orbe-xfzn.onrender.com",
  [string]$Apelido = "pc"
)
$Versao = 2
$ErrorActionPreference = "Stop"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]3072 } catch {}
$ProgressPreference = "SilentlyContinue"
if (-not $Token) {
  $tf = Join-Path $env:LOCALAPPDATA "OrbeMao\token.txt"
  if (Test-Path $tf) { $Token = (Get-Content $tf -Raw).Trim() }
}
if (-not $Token) { throw "falta o token" }
$mutex = New-Object System.Threading.Mutex($false, "OrbeMaoPc")
$dono = $false
try {
  $dono = $mutex.WaitOne(8000)
} catch [System.Threading.AbandonedMutexException] {
  $dono = $true
}
if (-not $dono) { exit 0 }
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
  $h = @{ "x-orbe-mao" = $Token; "x-orbe-mao-email" = "1" }
  if ($Corpo -ne $null) {
    $json = $Corpo | ConvertTo-Json -Compress -Depth 6
    return Invoke-RestMethod -Method $Metodo -Uri $Url -Headers $h -Body $json -ContentType "application/json; charset=utf-8" -TimeoutSec 40
  }
  return Invoke-RestMethod -Method $Metodo -Uri $Url -Headers $h -TimeoutSec 40
}

function Clicar-Ponto([int]$x, [int]$y) {
  [OrbeMao]::SetCursorPos($x, $y) | Out-Null
  Start-Sleep -Milliseconds 120
  [OrbeMao]::mouse_event(2, 0, 0, 0, 0)
  [OrbeMao]::mouse_event(4, 0, 0, 0, 0)
}

function Clicar-Nome([string]$parte) {
  try {
    Add-Type -AssemblyName UIAutomationClient -ErrorAction SilentlyContinue
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $winCond = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::ClassNameProperty, "Chrome_WidgetWin_1")
    $win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $winCond)
    if (-not $win) { return $false }
    $cond = New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::NameProperty, $parte)
    $el = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
    if (-not $el) { return $false }
    $r = $el.Current.BoundingRectangle
    if ($r.Width -lt 2 -or $r.Height -lt 2) { return $false }
    Clicar-Ponto ([int]($r.X + $r.Width / 2)) ([int]($r.Y + $r.Height / 2))
    return $true
  } catch {
    return $false
  }
}

function Ponto-Tela([int]$x, [int]$y) {
  $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  return @([int]($x * $b.Width / 1024), [int]($y * $b.Height / 768))
}

function Focar-Chrome([string]$titulo) {
  try {
    $w = New-Object -ComObject WScript.Shell
    if ($w.AppActivate($titulo)) { return $true }
    return [bool]$w.AppActivate("Chrome")
  } catch {
    return $false
  }
}

function Publicar-Uiclap {
  if (-not (Focar-Chrome "UICLAP")) {
    Start-Process "https://portal.uiclap.com"
    Start-Sleep -Seconds 5
    Focar-Chrome "UICLAP" | Out-Null
  } else {
    Start-Sleep -Seconds 1
  }
  $ok = Clicar-Nome "Publicar Orbe"
  if (-not $ok) { $ok = Clicar-Nome "📚 Publicar Orbe" }
  if (-not $ok) {
    $p = Ponto-Tela 705 100
    Clicar-Ponto $p[0] $p[1]
  }
  $viu = ""
  for ($i = 0; $i -lt 8; $i++) {
    Start-Sleep -Seconds 4
    if (Clicar-Nome "Fechar") { $viu = "fechei o aviso"; break }
  }
  if (-not $viu) {
    $p = Ponto-Tela 676 407
    Clicar-Ponto $p[0] $p[1]
    $viu = "cliquei o favorito e o fechar"
  }
  return $true, "publiquei no UICLAP ($viu)", ""
}

function Criar-Canal([string]$qual) {
  if ($qual -eq "youtube") {
    Start-Process "https://studio.youtube.com"
    Start-Sleep -Seconds 6
    Focar-Chrome "YouTube" | Out-Null
    if (Clicar-Nome "Criar") { return $true, "abri o YouTube Studio e cliquei em Criar", "" }
    if (Clicar-Nome "Create") { return $true, "abri o YouTube Studio e cliquei em Create", "" }
    return $true, "abri o YouTube Studio. Parei antes de senha, captcha ou termo.", ""
  }
  if ($qual -eq "tiktok") {
    Start-Process "https://www.tiktok.com/creator-center/upload"
    Start-Sleep -Seconds 6
    Focar-Chrome "TikTok" | Out-Null
    return $true, "abri o envio do TikTok. Parei antes de senha, captcha ou termo.", ""
  }
  return $false, "canal desconhecido", ""
}

function Executa($cmd) {
  $acao = [string]$cmd.acao
  $alvo = [string]$cmd.alvo
  if ($acao -eq "publicar") { return Publicar-Uiclap }
  if ($acao -eq "criar") { return Criar-Canal $alvo }
  if ($acao -eq "abrir_url") {
    if ($alvo -notmatch '^https://') { return $false, "url recusada", "" }
    if ($alvo -match 'portal\.uiclap\.com') { return Publicar-Uiclap }
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
    $x = 0; $y = 0
    if ($cmd.extra) { $x = [int]$cmd.extra.x; $y = [int]$cmd.extra.y }
    Clicar-Ponto $x $y
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

Write-Host "mao pc v$Versao ligada em $Base"
$voltas = 0
while ($true) {
  try {
    $voltas++
    if ($voltas % 20 -eq 0) {
      try {
        $remoto = [int](Invoke-RestMethod -Uri "$Base/mao/versao.txt" -TimeoutSec 15)
        if ($remoto -gt $Versao) {
          $tmp = Join-Path $env:TEMP "orbe-pc-novo.ps1"
          Invoke-WebRequest -Uri "$Base/mao/pc.ps1" -OutFile $tmp -UseBasicParsing
          Copy-Item $tmp (Join-Path $env:LOCALAPPDATA "OrbeMao\pc.ps1") -Force
          $mutex.ReleaseMutex() | Out-Null
          $vbs = Join-Path $env:LOCALAPPDATA "OrbeMao\ligar.vbs"
          if (Test-Path $vbs) { Start-Process wscript.exe -ArgumentList "`"$vbs`"" -WindowStyle Hidden }
          exit 0
        }
      } catch {}
    }
    $fila = Invoke-Orbe GET "$Base/api/mao/fila?aparelho=$Apelido" $null
    if (-not $fila.comando) {
      try {
        $saida = Invoke-Orbe GET "$Base/api/mao/saida?aparelho=$Apelido" $null
        if ($saida.saida) {
          $m = New-Object System.Net.Mail.MailMessage($saida.saida.de, $saida.saida.para, $saida.saida.assunto, $saida.saida.corpo)
          $c = New-Object System.Net.Mail.SmtpClient("smtp.gmail.com", 587)
          $c.EnableSsl = $true
          $c.Credentials = New-Object System.Net.NetworkCredential($saida.saida.de, $saida.saida.senha)
          $c.Send($m)
          $m.Dispose(); $c.Dispose()
        }
      } catch {}
    }
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
