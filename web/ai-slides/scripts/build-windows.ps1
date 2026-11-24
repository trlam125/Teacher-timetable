param([switch]$Test)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$sourcePath = Join-Path $projectRoot 'web/ai-slides'
$outputPath = Join-Path $projectRoot 'app/static/ai-slides'
# codex-skill-env already exists. Its persistent /workspace keeps dependencies.
docker exec codex-skill-env mkdir -p /workspace/teacher-timetable/web/ai-slides
if ($LASTEXITCODE -ne 0) { throw 'Start the existing codex-skill-env container first.' }
docker cp "$sourcePath/." codex-skill-env:/workspace/teacher-timetable/web/ai-slides
if ($LASTEXITCODE -ne 0) { throw 'Could not copy Studio source.' }
docker exec codex-skill-env mkdir -p /workspace/teacher-timetable/app/static/ai-slides
if ($LASTEXITCODE -ne 0) { throw 'Could not prepare resource directory.' }
docker cp (Join-Path $projectRoot 'app/static/ai-slides/resources.json') codex-skill-env:/workspace/teacher-timetable/app/static/ai-slides/resources.json
if ($LASTEXITCODE -ne 0) { throw 'Could not copy Studio resource catalog.' }
docker cp (Join-Path $projectRoot 'app/static/ai-slides/link-policy.json') codex-skill-env:/workspace/teacher-timetable/app/static/ai-slides/link-policy.json
if ($LASTEXITCODE -ne 0) { throw 'Could not copy Studio link policy.' }
docker exec -w /workspace/teacher-timetable/web/ai-slides codex-skill-env npm ci --ignore-scripts
if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
if ($Test) {
    docker exec -w /workspace/teacher-timetable/web/ai-slides codex-skill-env npm test
    if ($LASTEXITCODE -ne 0) { throw 'Studio export tests failed.' }
    docker exec -w /workspace/teacher-timetable/web/ai-slides codex-skill-env npm run spike
    if ($LASTEXITCODE -ne 0) { throw 'Native motion spike failed.' }
}
docker exec -w /workspace/teacher-timetable/web/ai-slides codex-skill-env npm run build
if ($LASTEXITCODE -ne 0) { throw 'Studio build failed.' }
$distPath = [System.IO.Path]::GetFullPath((Join-Path $outputPath 'dist'))
$expectedDist = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'app/static/ai-slides/dist'))
if ($distPath -ne $expectedDist) { throw 'Unexpected generated bundle directory.' }
if (Test-Path -LiteralPath $distPath) {
    Remove-Item -LiteralPath $distPath -Recurse -Force
}
docker cp codex-skill-env:/workspace/teacher-timetable/app/static/ai-slides/dist $outputPath
if ($LASTEXITCODE -ne 0) { throw 'Could not copy browser bundle.' }
Write-Host 'Studio browser bundle built successfully.'
