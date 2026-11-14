param([string]$ExtensionId = '')
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskExtensionPath = [IO.Path]::GetFullPath((Join-Path $taskRoot 'extension')).TrimEnd('\')
$taskIds = @()
if ($ExtensionId) {
    $taskIds = @($ExtensionId)
} else {
    $taskChromeData = Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data'
    foreach ($taskProfile in (Get-ChildItem -LiteralPath $taskChromeData -Directory | Where-Object { $_.Name -eq 'Default' -or $_.Name -like 'Profile *' })) {
        foreach ($taskFile in @('Secure Preferences', 'Preferences')) {
            $taskPrefsPath = Join-Path $taskProfile.FullName $taskFile
            if (-not (Test-Path -LiteralPath $taskPrefsPath)) { continue }
            $taskPrefs = Get-Content -LiteralPath $taskPrefsPath -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($taskEntry in $taskPrefs.extensions.settings.psobject.Properties) {
                $taskPath = $taskEntry.Value.path
                if ($taskPath -and [IO.Path]::IsPathRooted($taskPath) -and
                    [IO.Path]::GetFullPath($taskPath).TrimEnd('\') -eq $taskExtensionPath) {
                    $taskIds += $taskEntry.Name
                }
            }
        }
    }
}
$taskIds = @($taskIds | Sort-Object -Unique)
if (-not $taskIds.Count) { throw 'Load the extension once, then run install-launcher.cmd again.' }
foreach ($taskId in $taskIds) {
    if ($taskId -notmatch '^[a-p]{32}$') { throw 'Invalid Chrome extension ID.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot '.venv\Scripts\python.exe'))) {
    throw 'Run setup.ps1 once to prepare the local environment.'
}
$taskManifestPath = Join-Path $taskRoot 'native\com.cs2.live_translator.json'
$taskManifest = @{
    name = 'com.cs2.live_translator'
    description = 'Start the local CS2 subtitle models on demand'
    path = Join-Path $taskRoot 'native\host.cmd'
    type = 'stdio'
    allowed_origins = @($taskIds | ForEach-Object { "chrome-extension://$_/" })
}
[IO.File]::WriteAllText($taskManifestPath, ($taskManifest | ConvertTo-Json -Depth 3), [Text.UTF8Encoding]::new($false))
$taskKey = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Software\Google\Chrome\NativeMessagingHosts\com.cs2.live_translator')
try { $taskKey.SetValue('', $taskManifestPath, [Microsoft.Win32.RegistryValueKind]::String) }
finally { $taskKey.Dispose() }
Write-Host "Installed for this user. Extension: $($taskIds -join ', ')"
Write-Host 'Reload the extension once. Daily use: open YouTube and click Start subtitles.'
