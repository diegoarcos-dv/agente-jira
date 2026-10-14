$ErrorActionPreference = "Stop"

function Get-AgenteJiraRoot {
    return (Split-Path -Parent $PSScriptRoot)
}

function Invoke-Captured {
    param([string]$FilePath, [string[]]$ArgumentList)
    try {
        $output = & $FilePath @ArgumentList 2>&1 | Out-String
        [pscustomobject]@{ Ok = ($LASTEXITCODE -eq 0); Output = $output.Trim() }
    } catch {
        [pscustomobject]@{ Ok = $false; Output = $_.Exception.Message }
    }
}

function Get-VersionNumbers([string]$Text) {
    $match = [regex]::Match($Text, '(?<!\d)(\d+)(?:\.(\d+))?(?:\.(\d+))?')
    if (-not $match.Success) { return $null }
    @([int]$match.Groups[1].Value, [int]$match.Groups[2].Value, [int]$match.Groups[3].Value)
}

function Test-MinVersion([string]$Text, [int]$Major, [int]$Minor = 0) {
    $version = Get-VersionNumbers $Text
    if ($null -eq $version) { return $false }
    return ($version[0] -gt $Major) -or ($version[0] -eq $Major -and $version[1] -ge $Minor)
}

function Resolve-Python {
    $venvPython = Join-Path (Get-AgenteJiraRoot) '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) {
        $probe = Invoke-Captured $venvPython @('--version')
        if ($probe.Ok -and (Test-MinVersion $probe.Output 3 12)) { return $venvPython }
    }
    $configured = $env:AGENTE_JIRA_PYTHON
    if ($configured -and (Test-Path -LiteralPath $configured)) {
        $probe = Invoke-Captured $configured @('--version')
        if ($probe.Ok -and (Test-MinVersion $probe.Output 3 12)) { return $configured }
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) {
        $probe = Invoke-Captured $command.Source @('--version')
        if ($probe.Ok -and (Test-MinVersion $probe.Output 3 12)) { return $command.Source }
    }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $probe = Invoke-Captured $launcher.Source @('-3.12', '--version')
        if ($probe.Ok -and (Test-MinVersion $probe.Output 3 12)) { return "$($launcher.Source)|-3.12" }
    }
    return $null
}

function Invoke-ResolvedPython {
    param([string]$Resolved, [string[]]$Arguments)
    if ($Resolved -like '*|*') {
        $parts = $Resolved -split '\|', 2
        return Invoke-Captured $parts[0] (@($parts[1]) + $Arguments)
    }
    return Invoke-Captured $Resolved $Arguments
}

function Test-TcpPort([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        [void]$task.Wait(250)
        return ($task.Status -eq [System.Threading.Tasks.TaskStatus]::RanToCompletion)
    } catch { return $false } finally { $client.Dispose() }
}

function Get-PortOwner([int]$Port) {
    try {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
        if ($connection) {
            $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
            return "PID $($connection.OwningProcess)" + $(if ($process) { " ($($process.ProcessName))" } else { '' })
        }
    } catch { }
    return 'proceso no identificado'
}

function Test-AgenteHealth {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 1
        return ($health.status -eq 'ok')
    } catch { return $false }
}
