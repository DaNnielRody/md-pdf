param(
    [switch]$Uninstall,
    [switch]$Link
)

$ErrorActionPreference = "Stop"

$Src = $PSScriptRoot
$AppData = [Environment]::GetFolderPath("LocalApplicationData")
$Share = Join-Path $AppData "mdpdf"
$Bin = Join-Path $AppData "Programs\mdpdf\bin"

function Say($msg)  { Write-Host $msg }
function Warn($msg) { Write-Warning $msg }

if ($Uninstall) {
    if (Test-Path $Share) { Remove-Item -Recurse -Force $Share }
    if (Test-Path $Bin) { Remove-Item -Recurse -Force $Bin }
    Say "v mdpdf removed from $Share and $Bin"
    exit 0
}

# 1. Verificar comandos obrigatorios
$Missing = $false

# Verifica executavel Python
$PythonCmd = if (Get-Command "python" -ErrorAction SilentlyContinue) { "python" }
             elseif (Get-Command "python3" -ErrorAction SilentlyContinue) { "python3" }
             elseif (Get-Command "py" -ErrorAction SilentlyContinue) { "py" }
             else { $null }

if (-not $PythonCmd) {
    Warn "missing: python"
    $Missing = $true
} else {
    $pyCheck = 'import sys, tomllib; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
    & $PythonCmd -c $pyCheck 2>$null
    if ($LASTEXITCODE -ne 0) {
        Warn "python must be 3.11+ (tomllib)"
        $Missing = $true
    }
}

if (-not (Get-Command "pandoc" -ErrorAction SilentlyContinue)) {
    Warn "missing: pandoc"
    $Missing = $true
}

# Verifica WeasyPrint via comando ou pacote Python com bibliotecas nativas
$weasyCheck = "import os, sys; [os.add_dll_directory(p) for p in os.environ.get('PATH', '').split(';') if os.path.isdir(p)]; import weasyprint"

if ($PythonCmd) {
    $proc = Start-Process -FilePath $PythonCmd -ArgumentList "-c `"$weasyCheck`"" -NoNewWindow -Wait -PassThru -RedirectStandardError ([System.IO.Path]::GetTempFileName())
    if ($proc.ExitCode -ne 0) {
        if (-not (Get-Command "weasyprint" -ErrorAction SilentlyContinue)) {
            Warn "missing: weasyprint (or missing GTK/GObject libraries on Windows)"
            $Missing = $true
        }
    }
} else {
    $Missing = $true
}

# 2. Recomendacoes opcionais (Mermaid)
if (-not (Get-Command "npx" -ErrorAction SilentlyContinue)) {
    Warn "npx not found -- Mermaid diagrams will be skipped"
}

$programFilesX86 = [Environment]::GetFolderPath("ProgramFilesX86")
$programFiles = [Environment]::GetFolderPath("ProgramFiles")

$Browsers = @(
    (Join-Path $programFiles "Microsoft\Edge\Application\msedge.exe"),
    (Join-Path $programFilesX86 "Microsoft\Edge\Application\msedge.exe"),
    (Join-Path $programFiles "Google\Chrome\Application\chrome.exe"),
    (Join-Path $programFilesX86 "Google\Chrome\Application\chrome.exe")
)
$FoundBrowser = $Browsers | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $FoundBrowser) {
    Warn "no Chromium/Edge found -- Mermaid diagrams will be skipped"
}

if ($Missing) {
    Write-Host @"

Install what is missing and run again:

  winget:   winget install Python.Python.3.12 JohnMacFarlane.Pandoc
  pip:      pip install weasyprint
  scoop:    scoop install python pandoc weasyprint

  Note for WeasyPrint on Windows:
  WeasyPrint requires GTK3 / GObject libraries (e.g. from MSYS2, Scoop, or Graphviz) in your PATH.

"@ -ForegroundColor Yellow
    exit 1
}

# 3. Copiar ou Linkar arquivos
New-Item -ItemType Directory -Force -Path $Share | Out-Null
New-Item -ItemType Directory -Force -Path $Bin | Out-Null

if ($Link) {
    if (Test-Path $Share) { Remove-Item -Recurse -Force $Share }
    New-Item -ItemType SymbolicLink -Path $Share -Target $Src | Out-Null
    Say "-> $Share -> $Src (symlink)"
} else {
    if (Test-Path $Share) { Remove-Item -Recurse -Force $Share }
    New-Item -ItemType Directory -Force -Path $Share | Out-Null
    Copy-Item (Join-Path $Src "mdpdf.py") $Share
    Copy-Item (Join-Path $Src "design.py") $Share
    Copy-Item (Join-Path $Src "base.css") $Share
    Copy-Item -Recurse (Join-Path $Src "themes") $Share
    if (Test-Path (Join-Path $Src "README.md")) {
        Copy-Item (Join-Path $Src "README.md") $Share
    }
    Say "-> $Share"
}

# 4. Criar wrappers executaveis no PATH (mdpdf.cmd e mdpdf.ps1)
$MdpdfPy = Join-Path $Share "mdpdf.py"

# Wrapper .cmd
$CmdContent = "@echo off`r`n`"$PythonCmd`" `"$MdpdfPy`" %*"
Set-Content -Path (Join-Path $Bin "mdpdf.cmd") -Value $CmdContent -Encoding ASCII

# Wrapper .ps1
$Ps1Content = "& `"$PythonCmd`" `"$MdpdfPy`" @args"
Set-Content -Path (Join-Path $Bin "mdpdf.ps1") -Value $Ps1Content -Encoding UTF8

Say "-> $Bin\mdpdf.cmd"

# 5. Verificar e sugerir PATH
$CurrentPath = [Environment]::GetEnvironmentVariable("Path", "User")
$PathEntries = if ($CurrentPath) { $CurrentPath -split ';' } else { @() }

if ($PathEntries -notcontains $Bin) {
    Warn "$Bin is not on your User PATH."
    Say "  To add it automatically for your user, run in PowerShell:"
    Say "  [Environment]::SetEnvironmentVariable('Path', `"`$([Environment]::GetEnvironmentVariable('Path', 'User'));$Bin`", 'User')"
}

Say ""
Say "v installed. Check with:  mdpdf themes"
