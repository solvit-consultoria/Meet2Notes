[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$JobId,
    [Parameter(Mandatory)][string]$OutputPath,
    [int]$IntervalSeconds = 3,
    [int]$MaxMinutes = 120
)

$ErrorActionPreference = 'Stop'
$baseUrl = 'http://127.0.0.1:8765'
$connection = Get-NetTCPConnection -LocalPort 8765 -State Listen | Select-Object -First 1
if (-not $connection) { throw 'Meeting by Solvit is not listening on port 8765.' }
$serverPid = [int]$connection.OwningProcess
$logicalCores = [Environment]::ProcessorCount
$started = Get-Date
$previousCpuSeconds = $null
$previousSampleTime = $null
$rows = [System.Collections.Generic.List[object]]::new()

while (((Get-Date) - $started).TotalMinutes -lt $MaxMinutes) {
    $now = Get-Date
    $job = try { Invoke-RestMethod "$baseUrl/api/jobs/$JobId" -TimeoutSec 10 } catch { $null }
    $process = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
    $cpuSeconds = if ($process) { [double]$process.CPU } else { 0.0 }
    $cpuPercentOfMachine = $null
    if ($previousSampleTime -and $process) {
        $elapsed = ($now - $previousSampleTime).TotalSeconds
        if ($elapsed -gt 0) {
            $cpuPercentOfMachine = [math]::Round(
                100 * ($cpuSeconds - $previousCpuSeconds) / ($elapsed * $logicalCores), 1
            )
        }
    }
    $previousCpuSeconds = $cpuSeconds
    $previousSampleTime = $now

    $gpuUtil = $null
    $gpuMemoryMb = $null
    try {
        $gpuLine = & nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits 2>$null | Select-Object -First 1
        if ($gpuLine -match '^\s*(\d+)\s*,\s*(\d+)') {
            $gpuUtil = [int]$Matches[1]
            $gpuMemoryMb = [int]$Matches[2]
        }
    } catch { }
    $availableRamMb = $null
    try {
        $memory = Get-CimInstance Win32_OperatingSystem
        $availableRamMb = [math]::Round($memory.FreePhysicalMemory / 1024)
    } catch { }

    $row = [pscustomobject]@{
        timestamp = $now.ToString('o')
        elapsed_seconds = [math]::Round(($now - $started).TotalSeconds, 1)
        status = if ($job) { $job.status } else { 'api_unavailable' }
        progress = if ($job) { $job.progress } else { $null }
        app_private_mb = if ($process) { [math]::Round($process.PrivateMemorySize64 / 1MB) } else { $null }
        app_working_set_mb = if ($process) { [math]::Round($process.WorkingSet64 / 1MB) } else { $null }
        app_cpu_percent_of_machine = $cpuPercentOfMachine
        system_available_ram_mb = $availableRamMb
        gpu_util_percent = $gpuUtil
        gpu_memory_used_mb = $gpuMemoryMb
    }
    $rows.Add($row)
    if ($rows.Count -eq 1 -or $rows.Count % 10 -eq 0 -or ($job -and $job.status -in @('completed','failed','cancelled'))) {
        Write-Output ("{0} elapsed={1}s status={2} progress={3:P1} appRAM={4}MB gpu={5}% gpuRAM={6}MB" -f `
            $now.ToString('HH:mm:ss'), $row.elapsed_seconds, $row.status, $row.progress,
            $row.app_private_mb, $row.gpu_util_percent, $row.gpu_memory_used_mb)
        $rows | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding utf8
    }
    if ($job -and $job.status -in @('completed','failed','cancelled')) { break }
    Start-Sleep -Seconds $IntervalSeconds
}
$rows | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding utf8
