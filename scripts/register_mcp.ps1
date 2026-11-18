param(
    [switch]$Install,
    [switch]$Uninstall,
    [string]$AppPath = ""
)

$targetConfigs = @(
    (Join-Path $env:USERPROFILE ".gemini\config\mcp_config.json"),
    (Join-Path $env:USERPROFILE ".gemini\antigravity\mcp_config.json"),
    (Join-Path $env:USERPROFILE ".gemini\antigravity-ide\mcp_config.json")
)

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

foreach ($configPath in $targetConfigs) {
    if ($Install) {
        if (-not $AppPath) {
            $AppPath = "arch.exe"
        }
        $configDir = Split-Path $configPath
        if (-not (Test-Path $configDir)) {
            New-Item -ItemType Directory -Path $configDir -Force | Out-Null
        }
        if (Test-Path $configPath) {
            try {
                $json = Get-Content $configPath -Raw | ConvertFrom-Json
            } catch {
                $json = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
            }
        } else {
            $json = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
        }
        if (-not $json.mcpServers) {
            $json | Add-Member -MemberType NoteProperty -Name "mcpServers" -Value ([PSCustomObject]@{}) -Force
        }
        $json.mcpServers | Add-Member -MemberType NoteProperty -Name "arch" -Value ([PSCustomObject]@{
            command = $AppPath
            args = @("mcp", "--stdio")
        }) -Force
        $jsonStr = $json | ConvertTo-Json -Depth 10
        [System.IO.File]::WriteAllText($configPath, $jsonStr, $utf8NoBom)
    }

    if ($Uninstall) {
        if (Test-Path $configPath) {
            try {
                $json = Get-Content $configPath -Raw | ConvertFrom-Json
                if ($json.mcpServers.arch) {
                    $json.mcpServers.PSObject.Properties.Remove("arch")
                    $jsonStr = $json | ConvertTo-Json -Depth 10
                    [System.IO.File]::WriteAllText($configPath, $jsonStr, $utf8NoBom)
                }
            } catch {}
        }
    }
}
