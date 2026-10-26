# Explicit local setup + verification. Does not use Compose or any named volume.
[CmdletBinding()]
param(
    [string]$Python,
    [switch]$ProvisionTokenizer
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $relativePython = if ($env:OS -eq 'Windows_NT') { 'backend/.venv/Scripts/python.exe' } else { 'backend/.venv/bin/python' }
    $Python = Join-Path $repositoryRoot $relativePython
}
$Python = (Get-Command $Python -ErrorAction Stop).Source
$runId = [guid]::NewGuid().ToString('N')
$containerName = 'auron-verify-' + $runId
$evidenceDirectory = Join-Path $repositoryRoot ('artifacts/verify/' + $runId)
New-Item -ItemType Directory -Force -Path $evidenceDirectory | Out-Null
$savedEnvironment = @{}
foreach ($key in @('DATABASE_URL', 'TEST_DATABASE_URL', 'TIKTOKEN_CACHE_DIR')) {
    $savedEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
$savedPostgresEnvironment = @{}
foreach ($variable in Get-ChildItem Env:PG*) {
    $savedPostgresEnvironment[$variable.Name] = $variable.Value
    Remove-Item -LiteralPath ('Env:' + $variable.Name)
}
$containerId = $null
$result = 1
try {
    & docker image inspect postgres:17-alpine *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Provision Docker and docker pull postgres:17-alpine explicitly first.' }
    $containerId = (& docker run --detach --rm --name $containerName --label "auron.verify=$runId" --tmpfs /var/lib/postgresql/data:rw --publish 127.0.0.1::5432 --env POSTGRES_USER=auron_test --env POSTGRES_PASSWORD=auron_test --env POSTGRES_DB=auron_infra_test postgres:17-alpine)
    if ($LASTEXITCODE -ne 0 -or $containerId -notmatch '^[0-9a-f]{64}$') { throw 'Disposable PostgreSQL creation failed.' }
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        & docker exec $containerId pg_isready -U auron_test -d auron_infra_test *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Disposable PostgreSQL readiness timed out.' }
    $binding = (& docker port $containerId 5432/tcp)
    if ($LASTEXITCODE -ne 0 -or $binding -notmatch '^127\.0\.0\.1:(\d+)$') { throw 'Expected an exclusive loopback PostgreSQL port.' }
    $databasePort = $Matches[1]
    $env:DATABASE_URL = 'postgresql+psycopg://auron_verify:unused@127.0.0.1:1/auron_verify_no_application_db?connect_timeout=1'
    $env:TEST_DATABASE_URL = "postgresql+psycopg://auron_test:auron_test@127.0.0.1:$databasePort/auron_infra_test?connect_timeout=5"
    if (-not $env:TIKTOKEN_CACHE_DIR) { $env:TIKTOKEN_CACHE_DIR = Join-Path $repositoryRoot 'artifacts/tokenizer' }
    Push-Location (Join-Path $repositoryRoot 'backend')
    try {
        $tokenizerArguments = @('-m', 'app.scripts.provision_tokenizer')
        if (-not $ProvisionTokenizer) { $tokenizerArguments += '--check' }
        & $Python @tokenizerArguments
        if ($LASTEXITCODE -ne 0) { throw 'Tokenizer prerequisite failed; use -ProvisionTokenizer for explicit download.' }
        # Only this process's isolated test URL reaches migrations. Ignore root .env.
        $migrationScript = @'
import os
from app.config import Settings
Settings.model_config['env_file'] = None
os.environ['DATABASE_URL'] = os.environ['TEST_DATABASE_URL']
from alembic.config import CommandLine
CommandLine().main()
'@
        & $Python -c $migrationScript upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'Disposable migrations failed.' }
        & $Python -c $migrationScript check
        if ($LASTEXITCODE -ne 0) { throw 'Migration drift check failed.' }
    } finally { Pop-Location }
    & (Get-Command pwsh -ErrorAction Stop).Source -NoProfile -File (Join-Path $PSScriptRoot 'verify.ps1') -Mode full -Python $Python -DisposableTestDatabase 2>&1 | Tee-Object -FilePath (Join-Path $evidenceDirectory 'full.log')
    $result = $LASTEXITCODE
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    $result = 1
} finally {
    foreach ($key in $savedEnvironment.Keys) {
        if ($null -eq $savedEnvironment[$key]) {
            Remove-Item -LiteralPath ('Env:' + $key) -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($key, $savedEnvironment[$key], 'Process')
        }
    }
    foreach ($key in $savedPostgresEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($key, $savedPostgresEnvironment[$key], 'Process')
    }
    if ($containerId -match '^[0-9a-f]{64}$') {
        & docker logs $containerId 2>&1 | Out-File (Join-Path $evidenceDirectory 'postgres.log')
        $label = (& docker inspect --format '{{ index .Config.Labels "auron.verify" }}' $containerId)
        if ($LASTEXITCODE -ne 0 -or $label -ne $runId) {
            [Console]::Error.WriteLine('Cleanup refused: container ownership could not be confirmed.')
            $result = 1
        } else {
            & docker stop --time 5 $containerId | Out-Null
            if ($LASTEXITCODE -ne 0) { $result = 1 }
        }
    }
    Write-Host "Verification evidence: $evidenceDirectory"
}
exit $result
