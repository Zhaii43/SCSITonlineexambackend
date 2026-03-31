param(
  [string]$OutputDir = ".\\backups"
)

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$filename = "onlineexam_$timestamp.sql"

if (!(Test-Path $OutputDir)) {
  New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

if (!$env:DB_NAME -or !$env:DB_USER -or !$env:DB_HOST -or !$env:DB_PORT) {
  Write-Error "DB_NAME, DB_USER, DB_HOST, and DB_PORT must be set in the environment."
  exit 1
}

$env:PGPASSWORD = $env:DB_PASSWORD
pg_dump -h $env:DB_HOST -p $env:DB_PORT -U $env:DB_USER -d $env:DB_NAME -F p -f (Join-Path $OutputDir $filename)

if ($LASTEXITCODE -eq 0) {
  Write-Host "Backup created at $OutputDir\\$filename"
} else {
  Write-Error "Backup failed."
  exit $LASTEXITCODE
}
