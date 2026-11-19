$ErrorActionPreference='Stop'
$path=Join-Path $PSScriptRoot '.env'
if (!(Test-Path -LiteralPath $path)) {throw 'Start RepoMind once to initialize .env.'}
$inputKey=Read-Host 'Paste your Google Gemini API key (hidden)' -AsSecureString
$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($inputKey)
try {
    $value=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr).Trim()
    if ($value -notmatch '^[A-Za-z0-9._-]{16,256}$') {throw 'Unexpected key format. Settings were not changed.'}
    $lines=@([IO.File]::ReadAllLines($path) | Where-Object {$_ -notmatch '^GOOGLE_API_KEY='})
    $temp=Join-Path $PSScriptRoot ('.env.'+[guid]::NewGuid())
    [IO.File]::WriteAllLines($temp,[string[]]($lines+('GOOGLE_API_KEY='+$value)))
    [IO.File]::Replace($temp,$path,[System.Management.Automation.Language.NullString]::Value)
    Write-Host 'Key saved locally. Run Start RepoMind.cmd to apply it.'
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    $inputKey.Dispose()
    if ($temp -and (Test-Path -LiteralPath $temp)) {Remove-Item -LiteralPath $temp}
}
