param(
    [switch]$Doctor,
    [switch]$Summary,
    [switch]$Integrations,
    [switch]$Tests,
    [switch]$Compile,
    [switch]$All
)

$ErrorActionPreference = "Stop"

$script:RepoRoot = Split-Path -Parent $PSScriptRoot

function Invoke-AxiomPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Code
    )

    Push-Location $script:RepoRoot
    try {
        python -c $Code
    }
    finally {
        Pop-Location
    }
}

function Invoke-AxiomTests {
    Push-Location $script:RepoRoot
    try {
        python -m unittest discover -s tests -p "test_*.py" -v
    }
    finally {
        Pop-Location
    }
}

function Invoke-AxiomCompile {
    Push-Location $script:RepoRoot
    try {
        python -m compileall actions agent core tests main.py ui.py
    }
    finally {
        Pop-Location
    }
}

function Show-Heading {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title
    )

    Write-Host ""
    Write-Host ("=" * 72)
    Write-Host $Title
    Write-Host ("=" * 72)
}

if (-not ($Doctor -or $Summary -or $Integrations -or $Tests -or $Compile -or $All)) {
    Write-Host "AXIOM ops helper"
    Write-Host ""
    Write-Host "Examples:"
    Write-Host "  .\scripts\axiom-ops.ps1 -Doctor"
    Write-Host "  .\scripts\axiom-ops.ps1 -Summary -Integrations"
    Write-Host "  .\scripts\axiom-ops.ps1 -Tests -Compile"
    Write-Host "  .\scripts\axiom-ops.ps1 -All"
    exit 0
}

if ($All -or $Summary) {
    Show-Heading "AXIOM Summary"
    Invoke-AxiomPython "from actions.system_capabilities import system_capabilities; print(system_capabilities({'action': 'summary'}))"
}

if ($All -or $Doctor) {
    Show-Heading "AXIOM Doctor"
    Invoke-AxiomPython "from actions.system_capabilities import system_capabilities; print(system_capabilities({'action': 'doctor'}))"
}

if ($All -or $Integrations) {
    Show-Heading "AXIOM Integrations"
    Invoke-AxiomPython "from actions.system_capabilities import system_capabilities; print(system_capabilities({'action': 'integrations'}))"
}

if ($All -or $Compile) {
    Show-Heading "Compile Check"
    Invoke-AxiomCompile
}

if ($All -or $Tests) {
    Show-Heading "Unit Tests"
    Invoke-AxiomTests
}
