[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet(
        "triposr",
        "triposg",
        "partcrafter",
        "trellis1",
        "3dtopia-xl",
        "trellis2",
        "direct3d-s2",
        "step1x-3d",
        "pixal3d",
        "hunyuan3d-21",
        "sf3d"
    )]
    [string] $Model,

    [string] $Tag,

    [switch] $Load,

    [switch] $Push
)

$ErrorActionPreference = "Stop"

if ($Load -and $Push) {
    throw "Use either -Load or -Push, not both."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workspaceRoot = $repoRoot
try {
    $gitCommonDir = (& git -C $repoRoot rev-parse --path-format=absolute --git-common-dir 2>$null)
    if ($LASTEXITCODE -eq 0 -and $gitCommonDir) {
        $gitCommonDir = [System.IO.Path]::GetFullPath($gitCommonDir.Trim())
        if ((Split-Path $gitCommonDir -Leaf) -eq ".git") {
            $workspaceRoot = Split-Path $gitCommonDir -Parent
        }
    }
} catch {
    $workspaceRoot = $repoRoot
}
$cacheBase = Join-Path $workspaceRoot ".docker-build"
$cacheRoot = Join-Path $cacheBase "buildx-cache\$Model"
$newCacheRoot = Join-Path $cacheBase "buildx-cache\$Model-new"
$imageRoot = Join-Path $cacheBase "images"

function Assert-UnderPath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,
        [Parameter(Mandatory = $true)]
        [string] $Root
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullRoot = [System.IO.Path]::GetFullPath($Root)
    if (-not $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify path outside ${fullRoot}: ${fullPath}"
    }
}

New-Item -ItemType Directory -Force -Path $cacheBase, (Join-Path $cacheBase "buildx-cache"), $imageRoot | Out-Null
Assert-UnderPath -Path $cacheRoot -Root $cacheBase
Assert-UnderPath -Path $newCacheRoot -Root $cacheBase

if (-not $Tag) {
    $Tag = "3dgen/${Model}:issue-11"
}

if (Test-Path $newCacheRoot) {
    Remove-Item -LiteralPath $newCacheRoot -Recurse -Force
}

$dockerArgs = @(
    "buildx",
    "build",
    "--progress=plain",
    "--tag",
    $Tag,
    "--file",
    (Join-Path "models\$Model" "Dockerfile"),
    "--cache-to",
    "type=local,dest=$newCacheRoot,mode=max"
)

if (Test-Path $cacheRoot) {
    $dockerArgs += @("--cache-from", "type=local,src=$cacheRoot")
}

if ($Load) {
    $dockerArgs += "--load"
} elseif ($Push) {
    $dockerArgs += "--push"
} else {
    $safeImageName = ($Tag -replace "[/:\\]", "-")
    $imageTar = Join-Path $imageRoot "$safeImageName.tar"
    Assert-UnderPath -Path $imageTar -Root $cacheBase
    if (Test-Path $imageTar) {
        Remove-Item -LiteralPath $imageTar -Force
    }
    $dockerArgs += @("--output", "type=docker,dest=$imageTar")
}

$dockerArgs += "."

Write-Host "Using Docker build cache under $cacheBase"
& docker @dockerArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (Test-Path $cacheRoot) {
    Remove-Item -LiteralPath $cacheRoot -Recurse -Force
}
Move-Item -LiteralPath $newCacheRoot -Destination $cacheRoot

if (-not $Load -and -not $Push) {
    Write-Host "Image archive written under $imageRoot"
    Write-Host "Load it only when needed: docker load -i <archive>"
}
