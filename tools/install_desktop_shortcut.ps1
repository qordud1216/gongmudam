$ErrorActionPreference = 'Stop'

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'service\.venv\Scripts\pythonw.exe'))
$launcherPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'tools\launch_gongmudam.py'))
$desktopPath = [Environment]::GetFolderPath([Environment+SpecialFolder]::Desktop)

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw "프로젝트 Python 실행 파일이 없습니다: $pythonPath" }
if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) { throw "공무담 실행 파일이 없습니다: $launcherPath" }
if (-not $desktopPath -or -not (Test-Path -LiteralPath $desktopPath -PathType Container)) { throw '현재 Windows 바탕 화면 폴더를 찾을 수 없습니다.' }

$arguments = '"{0}"' -f $launcherPath
$workingDirectory = $repoRoot
$shell = $null
$shortcut = $null
$shortcutPath = Join-Path $desktopPath '공무담 실행.lnk'

function Get-NormalizedPath([string] $Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return '' }
    try { return [System.IO.Path]::GetFullPath($Path.Trim('"')) } catch { return $Path.Trim('"') }
}

function New-LauncherIcon([string] $IconPath, [string] $SourcePath) {
    $bitmap = $null
    $graphics = $null
    $image = $null
    $icon = $null
    $stream = $null
    $handle = [IntPtr]::Zero
    try {
        if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) { return $false }
        Add-Type -AssemblyName System.Drawing
        if (-not ('GongmudamNativeIcon' -as [type])) {
            Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class GongmudamNativeIcon { [DllImport("user32.dll", SetLastError = true)] public static extern bool DestroyIcon(IntPtr handle); }'
        }
        $image = [System.Drawing.Image]::FromFile($SourcePath)
        $bitmap = New-Object -TypeName System.Drawing.Bitmap -ArgumentList @(64, 64, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.DrawImage($image, 0, 0, 64, 64)
        $handle = $bitmap.GetHicon()
        $icon = [System.Drawing.Icon]::FromHandle($handle).Clone()
        $stream = [System.IO.File]::Open($IconPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        $icon.Save($stream)
        return $true
    } catch {
        if (Test-Path -LiteralPath $IconPath) { Remove-Item -LiteralPath $IconPath -Force -ErrorAction SilentlyContinue }
        return $false
    } finally {
        if ($stream) { $stream.Dispose() }
        if ($icon) { $icon.Dispose() }
        if ($handle -ne [IntPtr]::Zero -and ('GongmudamNativeIcon' -as [type])) { [void][GongmudamNativeIcon]::DestroyIcon($handle) }
        if ($graphics) { $graphics.Dispose() }
        if ($bitmap) { $bitmap.Dispose() }
        if ($image) { $image.Dispose() }
    }
}

try {
    $shell = New-Object -ComObject WScript.Shell
    if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
        $existing = $shell.CreateShortcut($shortcutPath)
        $sameLauncher = (Get-NormalizedPath $existing.TargetPath) -ieq (Get-NormalizedPath $pythonPath) -and
            $existing.Arguments.Trim('"') -ieq $launcherPath -and
            (Get-NormalizedPath $existing.WorkingDirectory) -ieq (Get-NormalizedPath $workingDirectory)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($existing)
        if (-not $sameLauncher) {
            $number = 2
            do {
                $shortcutPath = Join-Path $desktopPath ("공무담 실행 ({0}).lnk" -f $number)
                $number++
            } while (Test-Path -LiteralPath $shortcutPath)
        }
    }

    $iconDirectory = Join-Path $repoRoot '.local-runtime\launcher'
    $iconPath = Join-Path $iconDirectory 'gongmudam.ico'
    $iconSource = Join-Path $repoRoot 'desktop\assets\seomu-otter-v1.png'
    $iconLocation = Join-Path $env:SystemRoot 'System32\shell32.dll,167'
    try { $null = New-Item -ItemType Directory -Path $iconDirectory -Force -ErrorAction Stop } catch { }
    if ((Test-Path -LiteralPath $iconDirectory -PathType Container) -and (New-LauncherIcon $iconPath $iconSource)) {
        $iconLocation = $iconPath
    }

    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $pythonPath
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $workingDirectory
    $shortcut.Description = '공무담 서버를 실행합니다. 고정 Cloudflare 주소 https://gongmudam.visanu81.workers.dev 에서 엽니다.'
    $shortcut.WindowStyle = 1
    $shortcut.IconLocation = $iconLocation
    $shortcut.Save()
    [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut)
    $shortcut = $shell.CreateShortcut($shortcutPath)

    if ((Get-NormalizedPath $shortcut.TargetPath) -ine (Get-NormalizedPath $pythonPath) -or
        $shortcut.Arguments.Trim('"') -ine $launcherPath -or
        (Get-NormalizedPath $shortcut.WorkingDirectory) -ine (Get-NormalizedPath $workingDirectory)) {
        throw '바탕 화면 바로 가기 속성을 다시 읽어 확인하지 못했습니다.'
    }

    [pscustomobject]@{
        created_path = $shortcutPath
        target = $shortcut.TargetPath
        arguments = $shortcut.Arguments
        working_dir = $shortcut.WorkingDirectory
        icon_path = $iconLocation
    } | ConvertTo-Json -Compress
} finally {
    if ($shortcut) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut) }
    if ($shell) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) }
}
