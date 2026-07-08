<#
Restore a Postgres dump into the local Docker dev database.
Counterpart to backup-db.ps1 / Jenkinsfile.db-backup's restore instructions.

WARNING: this overwrites the target database's contents (pg_restore --clean --if-exists).

Usage:
  powershell -File db-backup-script/restore-db.ps1
      # drop a .dump file into db-restore/, then run this with no args:
      # restores the newest *.dump file found in db-restore/, after a confirmation prompt

  powershell -File db-backup-script/restore-db.ps1 -DumpFile backups\batteryfinderdev_20260708_082639.dump
      # restore a specific file from anywhere (e.g. an automated backup in backups/)

  powershell -File db-backup-script/restore-db.ps1 -DumpFile path\to\some.dump -Force
      # skip the confirmation prompt
#>

param(
    [string]$DumpFile,
    [string]$ContainerName = "battery-finder-postgres",
    [string]$DbUser = "batteryfinder",
    [string]$DbName = "batteryfinderdev",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$RestoreDir = Join-Path $RepoRoot "db-restore"

if (-not $DumpFile) {
    $Candidates = Get-ChildItem -Path $RestoreDir -Filter "*.dump" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    if (-not $Candidates) {
        Write-Error "No dump file specified and no *.dump files found in $RestoreDir. Drop a dump file there, or pass -DumpFile <path>."
        exit 1
    }
    if ($Candidates.Count -gt 1) {
        Write-Host "Multiple dump files found in $RestoreDir; using the newest: $($Candidates[0].Name)"
    }
    $DumpFile = $Candidates[0].FullName
}

if (-not (Test-Path $DumpFile)) {
    Write-Error "Dump file not found: $DumpFile"
    exit 1
}
$DumpFile = (Resolve-Path $DumpFile).Path

# Verify container is running
$running = docker ps --filter "name=$ContainerName" --filter "status=running" --format "{{.Names}}"
if ($running -ne $ContainerName) {
    Write-Error "Container '$ContainerName' is not running. Start it with: docker compose up -d"
    exit 1
}

Write-Host "About to restore '$DumpFile' into database '$DbName' on container '$ContainerName'."
Write-Host "This will DROP and recreate existing objects in that database (pg_restore --clean --if-exists)."
if (-not $Force) {
    $confirm = Read-Host "Type 'yes' to continue"
    if ($confirm -ne "yes") {
        Write-Host "Aborted."
        exit 1
    }
}

$RemoteFile = "/tmp/" + (Split-Path -Leaf $DumpFile)

Write-Host "Copying dump into container..."
docker cp $DumpFile "${ContainerName}:${RemoteFile}"

Write-Host "Restoring..."
docker exec $ContainerName pg_restore -U $DbUser -d $DbName --clean --if-exists -F c $RemoteFile

Write-Host "Cleaning up temp file in container..."
docker exec $ContainerName rm $RemoteFile

Write-Host ""
Write-Host "Restore complete: $DbName now reflects $DumpFile"
