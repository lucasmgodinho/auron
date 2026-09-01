$ErrorActionPreference = "Stop"

$repositoryRoot = $PSScriptRoot
$backendDirectory = Join-Path $repositoryRoot "backend"
$frontendDirectory = Join-Path $repositoryRoot "frontend"
$pythonExecutable = Join-Path $backendDirectory ".venv\Scripts\python.exe"
$viteExecutable = Join-Path $frontendDirectory "node_modules\.bin\vite.cmd"

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "Backend dependencies are missing. Follow the Backend setup section in README.md."
}

if (-not (Test-Path -LiteralPath $viteExecutable)) {
    throw "Frontend dependencies are missing. Run 'npm.cmd install' from frontend/."
}

Write-Host "Starting local infrastructure..."
& docker compose --project-directory $repositoryRoot up -d --wait postgres mailpit
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose could not start the local infrastructure."
}

Write-Host "Applying database migrations..."
Push-Location $backendDirectory
try {
    & $pythonExecutable -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic could not apply the database migrations."
    }
}
finally {
    Pop-Location
}

$services = @()

try {
    Write-Host "Starting backend with automatic reload..."
    $backendProcess = Start-Process `
        -FilePath $env:ComSpec `
        -ArgumentList @("/d", "/s", "/c", ".venv\Scripts\python.exe -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000") `
        -WorkingDirectory $backendDirectory `
        -NoNewWindow `
        -PassThru
    $services += @{ Name = "backend"; Process = $backendProcess }

    Write-Host "Starting frontend with Hot Module Replacement..."
    $frontendProcess = Start-Process `
        -FilePath $env:ComSpec `
        -ArgumentList @("/d", "/s", "/c", "npm.cmd run dev") `
        -WorkingDirectory $frontendDirectory `
        -NoNewWindow `
        -PassThru
    $services += @{ Name = "frontend"; Process = $frontendProcess }

    Write-Host "Development environment ready:"
    Write-Host "  Frontend: http://127.0.0.1:5173"
    Write-Host "  Backend:  http://127.0.0.1:8000"
    Write-Host "Edit files normally; changes are applied automatically. Press Ctrl+C to stop."

    while ($true) {
        foreach ($service in $services) {
            $service.Process.Refresh()
            if ($service.Process.HasExited) {
                throw "$($service.Name) stopped unexpectedly with exit code $($service.Process.ExitCode)."
            }
        }

        Start-Sleep -Seconds 1
    }
}
finally {
    foreach ($service in $services) {
        if (-not $service.Process.HasExited) {
            & taskkill.exe /PID $service.Process.Id /T /F 2>$null | Out-Null
        }
    }
}
