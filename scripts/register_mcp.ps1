param(
    [switch]$Install,
    [switch]$Uninstall,
    [string]$AppPath = "",
    [string]$SkillSourceDir = ""
)

# Collect relevant user profiles (handles running under current user and UAC elevation)
$userProfiles = [System.Collections.Generic.List[string]]::new()
if ($env:USERPROFILE -and (Test-Path $env:USERPROFILE)) {
    $userProfiles.Add($env:USERPROFILE)
}

try {
    $loggedUser = (Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue).UserName
    if ($loggedUser) {
        $account = $loggedUser.Split('\')[-1]
        $interactiveProfile = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\*" -ErrorAction SilentlyContinue | Where-Object { $_.ProfileImagePath -like "*\$account" }).ProfileImagePath
        if ($interactiveProfile -and (Test-Path $interactiveProfile) -and (-not $userProfiles.Contains($interactiveProfile))) {
            $userProfiles.Add($interactiveProfile)
        }
    }
} catch {}

# Resolve skill source directory if installing
if ($Install -and (-not $SkillSourceDir)) {
    if (Test-Path (Join-Path $PSScriptRoot "resources\arch")) {
        $SkillSourceDir = Join-Path $PSScriptRoot "resources\arch"
    } elseif (Test-Path (Join-Path $PSScriptRoot "..\resources\arch")) {
        $SkillSourceDir = (Resolve-Path (Join-Path $PSScriptRoot "..\resources\arch")).Path
    }
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

foreach ($profilePath in $userProfiles) {
    # 1. MCP Configuration targets
    $targetConfigs = @(
        (Join-Path $profilePath ".gemini\config\mcp_config.json"),
        (Join-Path $profilePath ".gemini\antigravity\mcp_config.json"),
        (Join-Path $profilePath ".gemini\antigravity-ide\mcp_config.json")
    )

    # 2. Global Skill targets
    $targetSkillDirs = [System.Collections.Generic.List[string]]::new()
    $targetSkillDirs.Add((Join-Path $profilePath ".gemini\config\skills\arch"))
    $antigravityDir = Join-Path $profilePath ".gemini\antigravity"
    if (Test-Path $antigravityDir) {
        $targetSkillDirs.Add((Join-Path $antigravityDir "skills\arch"))
    }

    if ($Install) {
        if (-not $AppPath) {
            $AppPath = "arch.exe"
        }

        # Update MCP configs
        foreach ($configPath in $targetConfigs) {
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

        # Install Global Skill
        if ($SkillSourceDir -and (Test-Path $SkillSourceDir)) {
            foreach ($destSkillDir in $targetSkillDirs) {
                if (-not (Test-Path $destSkillDir)) {
                    New-Item -ItemType Directory -Path $destSkillDir -Force | Out-Null
                }
                Copy-Item -Path (Join-Path $SkillSourceDir "*") -Destination $destSkillDir -Recurse -Force
            }
        }
    }

    if ($Uninstall) {
        # Remove MCP configs
        foreach ($configPath in $targetConfigs) {
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

        # Remove Global Skill
        foreach ($destSkillDir in $targetSkillDirs) {
            if (Test-Path $destSkillDir) {
                Remove-Item -Path $destSkillDir -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
}
