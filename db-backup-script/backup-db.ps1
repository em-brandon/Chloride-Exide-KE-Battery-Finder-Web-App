<#
On-demand backup of the local Docker Postgres dev database.
Same steps as Jenkinsfile.db-backup, run locally without Jenkins.

Usage:
  powershell -File scripts/backup-db.ps1
  powershell -File scripts/backup-db.ps1 -KeepCount 20
#>

param(
    [string]$ContainerName = "battery-finder-postgres",
    [string]$DbUser = "batteryfinder",
    [string]$DbName = "batteryfinderdev",
    [int]$KeepCount = 10
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackupDir = Join-Path $RepoRoot "backups"

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
}

# Verify container is running
$running = docker ps --filter "name=$ContainerName" --filter "status=running" --format "{{.Names}}"
if ($running -ne $ContainerName) {
    Write-Error "Container '$ContainerName' is not running. Start it with: docker compose up -d"
    exit 1
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$DumpFile = "${DbName}_${Timestamp}.dump"

Write-Host "Dumping $DbName from $ContainerName..."
docker exec $ContainerName pg_dump -U $DbUser -d $DbName -F c -f "/tmp/$DumpFile"
docker exec $ContainerName test -s "/tmp/$DumpFile"

Write-Host "Copying dump to $BackupDir..."
docker cp "${ContainerName}:/tmp/$DumpFile" (Join-Path $BackupDir $DumpFile)
docker exec $ContainerName rm "/tmp/$DumpFile"

# Retention: keep only the newest $KeepCount dumps
$AllDumps = Get-ChildItem -Path $BackupDir -Filter "${DbName}_*.dump" | Sort-Object LastWriteTime -Descending
if ($AllDumps.Count -gt $KeepCount) {
    $ToDelete = $AllDumps | Select-Object -Skip $KeepCount
    foreach ($old in $ToDelete) {
        Write-Host "Removing old backup: $($old.Name)"
        Remove-Item $old.FullName -Force
    }
}

$FullPath = Join-Path $BackupDir $DumpFile
Write-Host ""
Write-Host "Backup complete: $FullPath"
Write-Host ""
Write-Host "To restore on this or another machine:"
Write-Host "  docker cp `"$FullPath`" ${ContainerName}:/tmp/$DumpFile"
Write-Host "  docker exec $ContainerName pg_restore -U $DbUser -d $DbName --clean --if-exists -F c /tmp/$DumpFile"
