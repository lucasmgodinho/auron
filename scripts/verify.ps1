[CmdletBinding()]
param(
    [ValidateSet('fast', 'full')]
    [string]$Mode = 'fast',
    [string]$Python,
    [switch]$DisposableTestDatabase
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repositoryRoot 'backend'
$frontend = Join-Path $repositoryRoot 'frontend'
$onWindows = $env:OS -eq 'Windows_NT'
if (-not $Python) {
    $pythonRelativePath = if ($onWindows) { '.venv/Scripts/python.exe' } else { '.venv/bin/python' }
    $Python = Join-Path $backend $pythonRelativePath
}

function Invoke-Check {
    param([string]$Name, [string]$Directory, [string]$Executable, [string[]]$Arguments)
    Write-Host "`n[$Name]"
    Push-Location -LiteralPath $Directory
    try {
        & $Executable @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$Name failed (exit $LASTEXITCODE)"
        }
    } finally {
        Pop-Location
    }
}

try {
    $Python = (Get-Command $Python -ErrorAction Stop).Source
    $npmCommand = if ($onWindows) { 'npm.cmd' } else { 'npm' }
    $npm = (Get-Command $npmCommand -ErrorAction Stop).Source
    $node = (Get-Command node -ErrorAction Stop).Source
    $tsc = Join-Path $frontend 'node_modules/typescript/bin/tsc'
    if (-not (Test-Path -LiteralPath $tsc -PathType Leaf)) {
        throw 'Frontend dependencies missing. Provision them explicitly; verification installs nothing.'
    }

    if ($Mode -eq 'full') {
        if (-not $DisposableTestDatabase) {
            throw 'Full requires -DisposableTestDatabase and an explicitly prepared disposable TEST_DATABASE_URL. DB tests can write/commit data.'
        }
        $databaseCheck = @'
from app.config import get_settings
from sqlalchemy.engine import make_url
import os
if any(key.startswith('PG') for key in os.environ):
    raise SystemExit('Full rejects ambient PG* connection settings; remove them or use verify-disposable.ps1.')
s = get_settings()
def target(value):
    u = make_url(value)
    host = (u.host or '').lower()
    return ('localhost' if host in {'localhost', '127.0.0.1', '::1'} else host, u.port or 5432, u.database)
if not s.test_database_url:
    raise SystemExit('TEST_DATABASE_URL is required; no database was provisioned.')
test_url = make_url(s.test_database_url)
timeout = test_url.query.get('connect_timeout', '5')
if (set(test_url.query) - {'connect_timeout'} or not isinstance(timeout, str)
        or not timeout.isdigit() or not 1 <= int(timeout) <= 10):
    raise SystemExit('TEST_DATABASE_URL only permits connect_timeout=1..10; connection overrides are forbidden.')
if target(s.test_database_url) == target(s.database_url):
    raise SystemExit('The test database must differ from the application database.')
print('Dedicated test DB configured; no connection/migration performed by preflight.')
'@
        Invoke-Check 'Full database prerequisite' $backend $Python @('-c', $databaseCheck)
        Invoke-Check 'Offline tokenizer prerequisite' $backend $Python @('-m', 'app.scripts.provision_tokenizer', '--check')
    }

    Invoke-Check 'Backend lint' $backend $Python @('-m', 'ruff', 'check', '--no-cache', '.')
    Invoke-Check 'Backend collection' $backend $Python @('-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider')
    # An unused checkout-local path avoids unrelated OS temp ACLs and never
    # asks pytest to clean an existing directory belonging to another run.
    $tempParent = Join-Path $repositoryRoot '.pytest_cache'
    New-Item -ItemType Directory -Path $tempParent -Force | Out-Null
    $testTemp = Join-Path $tempParent ('verify-' + [guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $testTemp) { throw 'Refusing to reuse an existing pytest temp directory.' }
    $pureTests = @(
        '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--basetemp', $testTemp,
        'tests/test_tokenizer_initialization.py', 'tests/test_module_registry.py',
        'tests/test_analytics_contract.py', 'tests/test_module_tooling.py',
        'tests/test_debug.py', 'tests/test_health.py',
        'tests/test_competitive_intelligence_benchmark.py::test_frozen_benchmark_checksums_remain_valid'
    )
    Invoke-Check 'Backend offline/pure regression scope' $backend $Python $pureTests
    Invoke-Check 'Auron module contract' $repositoryRoot $Python @('scripts/validate_module.py', 'competitive_intelligence')
    Invoke-Check 'Alembic revision graph (no DB)' $backend $Python @('-m', 'alembic', 'heads')
    Invoke-Check 'Frontend lint' $frontend $npm @('run', 'lint')
    foreach ($project in @('tsconfig.app.json', 'tsconfig.node.json', 'tsconfig.test.json')) {
        # Override the configured cache path so shared worktree dependencies stay untouched.
        $buildInfo = Join-Path $tempParent ($project + '.tsbuildinfo')
        Invoke-Check "TypeScript $project" $frontend $node @($tsc, '-p', $project, '--noEmit', '--incremental', 'false', '--tsBuildInfoFile', $buildInfo)
    }
    Invoke-Check 'Frontend tests (Node/JSDOM)' $frontend $npm @('test')

    if ($Mode -eq 'full') {
        # Subprocess tests may bypass pytest's DB fixture overrides. Keep their
        # fallback application engine away from any real/shared database too.
        $fullSuite = @'
import os
import sys
os.environ['DATABASE_URL'] = 'postgresql+psycopg://auron_verify:unused@127.0.0.1:1/auron_verify_no_application_db?connect_timeout=1'
from app.config import Settings
from app.config import ENV_FILE
from pydantic_settings.sources import DotEnvSettingsSource
from unittest.mock import patch
isolated_setting_names = set(Settings.model_fields) - {'database_url', 'test_database_url'}
for name in list(os.environ):
    if name.lower() in isolated_setting_names:
        os.environ.pop(name)
read_env_files = DotEnvSettingsSource._read_env_files
def read_test_env(source):
    # Preserve configuration metadata and explicit synthetic dotenv test fixtures.
    return {} if source.env_file == ENV_FILE else read_env_files(source)
import pytest
with patch.object(DotEnvSettingsSource, '_read_env_files', read_test_env):
    raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', '--basetemp', sys.argv[1]]))
'@
        $fullTemp = Join-Path $tempParent ('verify-full-' + [guid]::NewGuid().ToString('N'))
        if (Test-Path -LiteralPath $fullTemp) { throw 'Refusing to reuse an existing pytest temp directory.' }
        Invoke-Check 'Full backend suite (disposable DB)' $backend $Python @('-c', $fullSuite, $fullTemp)
        # Type checks above cover all projects; Vite emits this checkout's production bundle.
        $vite = Join-Path $frontend 'node_modules/vite/bin/vite.js'
        Invoke-Check 'Production frontend bundle' $frontend $node @($vite, 'build')
    }
    Write-Host "`nVerification $Mode passed. See docs/AI_FIRST_WORKFLOW.md for scope and exclusions."
    exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
