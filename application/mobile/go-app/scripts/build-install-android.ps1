# From the repository root:
#   .\application\mobile\go-app\scripts\build-install-android.cmd -Launch
#   .\application\mobile\go-app\scripts\build-install-android.cmd -NoInstall -OutputPath .\application\mobile\go-app\artifacts\GO-consumer-staging.apk
# From the mobile app root:
#   .\scripts\build-install-android.cmd -Launch
#   .\scripts\build-install-android.cmd -ApiBaseUrl https://api.example.com -Launch -Logcat
#   .\scripts\build-install-android.cmd -DeviceSerial emulator-5554 -NoInstall
[CmdletBinding()]
param(
    [string]$DeviceSerial,
    [string]$ApiBaseUrl,
    [string]$OutputPath,
    [switch]$NoInstall,
    [switch]$Launch,
    [switch]$Logcat,
    [ValidateRange(10, 3600)]
    [int]$LogcatSeconds = 120
)

$ErrorActionPreference = 'Stop'

$mobileRoot = Split-Path -Parent $PSScriptRoot
$androidRoot = Join-Path $mobileRoot 'android'
$repoRoot = (Get-Item (Join-Path $mobileRoot '..\..\..')).FullName
$gradleWrapper = Join-Path $androidRoot 'gradlew.bat'
$apkPath = Join-Path $androidRoot 'app\build\outputs\apk\debug\app-debug.apk'
$applicationId = 'travel.go.consumer'
$localPropertiesPath = Join-Path $androidRoot 'local.properties'
$effectiveApiBaseUrl = if ($ApiBaseUrl) { $ApiBaseUrl.TrimEnd('/') } else { 'https://staging-api.goaidirect.com' }

$sdkRootFromLocalProperties = $null
if (Test-Path -LiteralPath $localPropertiesPath -PathType Leaf) {
    $sdkLine = Get-Content -LiteralPath $localPropertiesPath -Encoding UTF8 |
        Where-Object { $_ -match '^\s*sdk\.dir\s*=' } |
        Select-Object -First 1
    if ($sdkLine) {
        $sdkValue = $sdkLine.Substring($sdkLine.IndexOf('=') + 1).Trim()
        $sdkRootFromLocalProperties = $sdkValue.Replace('\\\\', '\\').Replace('\\', '\').Replace('\:', ':')
    }
}

function Resolve-AdbPath {
    $adbCommand = Get-Command 'adb.exe' -ErrorAction SilentlyContinue
    if ($adbCommand) {
        return $adbCommand.Source
    }

    $sdkRoots = @(
        $sdkRootFromLocalProperties,
        $env:ANDROID_SDK_ROOT,
        $env:ANDROID_HOME,
        (Join-Path $env:LOCALAPPDATA 'Android\Sdk')
    ) | Where-Object { $_ } | Select-Object -Unique

    foreach ($sdkRoot in $sdkRoots) {
        $candidate = Join-Path $sdkRoot 'platform-tools\adb.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    $wingetLink = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\adb.exe'
    if (Test-Path -LiteralPath $wingetLink -PathType Leaf) {
        return $wingetLink
    }

    return $null
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $nativeErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = @(& $FilePath @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
        return [pscustomobject]@{ Output = $output; ExitCode = $exitCode }
    }
    finally {
        $ErrorActionPreference = $nativeErrorPreference
    }
}

function Get-LocalHttpContent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    # Metro is a loopback service. HttpClientHandler.UseProxy = false is important
    # on machines that set HTTP_PROXY/HTTPS_PROXY/ALL_PROXY for external traffic.
    Add-Type -AssemblyName System.Net.Http
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
    $response = $null
    try {
        $response = $client.GetAsync($Uri).GetAwaiter().GetResult()
        $content = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            $responseExcerpt = $content
            if ($responseExcerpt.Length -gt 800) {
                $responseExcerpt = $responseExcerpt.Substring(0, 800)
            }
            throw "Local HTTP request failed with status $([int]$response.StatusCode): $responseExcerpt"
        }
        return $content
    }
    finally {
        if ($response) { $response.Dispose() }
        $client.Dispose()
        $handler.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $gradleWrapper -PathType Leaf)) {
    throw "Gradle wrapper not found: $gradleWrapper"
}
if (-not (Get-Command 'node.exe' -ErrorAction SilentlyContinue)) {
    throw 'Node.js was not found on PATH. Install Node.js and reopen PowerShell.'
}

# Repair the known Metro dependency failure automatically, but only when the
# locked install is incomplete. Running npm ci on every build would slow down
# the normal build/install loop.
$requiredMobileFiles = @(
    (Join-Path $mobileRoot 'node_modules\expo\package.json'),
    (Join-Path $mobileRoot 'node_modules\caniuse-lite\dist\unpacker\agents.js')
)
$missingMobileFiles = @($requiredMobileFiles | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($missingMobileFiles.Count -gt 0) {
    $npmCommand = Get-Command 'npm.cmd' -ErrorAction SilentlyContinue
    if (-not $npmCommand) {
        throw "Mobile dependencies are incomplete and npm.cmd was not found. Run 'npm ci' in $mobileRoot after installing Node.js."
    }

    Write-Host 'Mobile dependencies are incomplete; restoring the locked dependencies with npm ci...'
    Push-Location $mobileRoot
    try {
        $nativeErrorPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & $npmCommand.Source 'ci' '--no-audit' '--no-fund' 2>&1 |
                ForEach-Object { Write-Host $_ }
            $npmExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $nativeErrorPreference
        }
        if ($npmExitCode -ne 0) {
            throw "npm ci failed with exit code $npmExitCode."
        }
    }
    finally {
        Pop-Location
    }

    $missingMobileFiles = @($requiredMobileFiles | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
    if ($missingMobileFiles.Count -gt 0) {
        throw "npm ci completed, but required mobile dependencies are still missing: $($missingMobileFiles -join ', ')"
    }
}

$environmentNames = @('EXPO_PUBLIC_API_URL', 'EXPO_NO_TYPESCRIPT_SETUP', 'JAVA_HOME', 'GRADLE_USER_HOME', 'GRADLE_OPTS', 'JAVA_TOOL_OPTIONS', 'TEMP', 'TMP')
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$mappedGradleDrive = $null
try {
    $gradleHome = Join-Path $env:USERPROFILE '.gradle'
    $usedDrives = @(Get-PSDrive -PSProvider FileSystem | ForEach-Object { $_.Name })
    $driveLetter = @('G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z') |
        Where-Object { $usedDrives -notcontains $_ } |
        Select-Object -First 1
    if (-not $driveLetter) {
        throw 'No free drive letter is available for the temporary ASCII Gradle cache mapping.'
    }

    $mappedGradleDrive = "${driveLetter}:"
    & subst.exe $mappedGradleDrive $gradleHome
    if ($LASTEXITCODE -ne 0) {
        throw "Could not map the Gradle cache to $mappedGradleDrive."
    }

    $gradleUserHome = "${driveLetter}:\"
    $jdkRoot = Join-Path $gradleUserHome 'jdks'
    $jdk17 = Get-ChildItem -LiteralPath $jdkRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like '*17-amd64-windows*' } |
        Select-Object -First 1
    if (-not $jdk17) {
        throw "Gradle-managed JDK 17 was not found under $jdkRoot."
    }

    $asciiTemp = Join-Path $repoRoot '.gradle-tmp-ascii'
    New-Item -ItemType Directory -Path $asciiTemp -Force | Out-Null
    $env:JAVA_HOME = $jdk17.FullName
    $env:GRADLE_USER_HOME = $gradleUserHome
    $env:TEMP = $asciiTemp
    $env:TMP = $asciiTemp
    $env:JAVA_TOOL_OPTIONS = $null
    $env:GRADLE_OPTS = "-Djava.io.tmpdir=$asciiTemp -Dfile.encoding=UTF-8"

    $env:EXPO_PUBLIC_API_URL = $effectiveApiBaseUrl
    if ($ApiBaseUrl) {
        Write-Host "Using API base URL from -ApiBaseUrl: $env:EXPO_PUBLIC_API_URL"
    }
    else {
        Write-Host "Using default API base URL: $env:EXPO_PUBLIC_API_URL"
    }

    Write-Host 'Building Android Debug APK...'
    Push-Location $androidRoot
    try {
        # Keep Gradle output flowing to the console while the build runs. The
        # plain console mode also keeps task progress readable in PowerShell.
        $nativeErrorPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & $gradleWrapper ':app:assembleDebug' '--console=plain' 2>&1 |
                ForEach-Object { Write-Host $_ }
            $buildExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $nativeErrorPreference
        }
        if ($buildExitCode -ne 0) {
            throw "Gradle build failed with exit code $buildExitCode."
        }
    }
    finally {
        Pop-Location
    }

    if (-not (Test-Path -LiteralPath $apkPath -PathType Leaf)) {
        throw "Gradle completed but the expected APK was not found: $apkPath"
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $apkArchive = [System.IO.Compression.ZipFile]::OpenRead($apkPath)
    try {
        $hasEmbeddedJsBundle = @($apkArchive.Entries | Where-Object { $_.FullName -eq 'assets/index.android.bundle' }).Count -gt 0
    }
    finally {
        $apkArchive.Dispose()
    }
    if (-not $hasEmbeddedJsBundle) {
        throw 'The APK is missing assets/index.android.bundle. Refusing to install an APK that requires Metro.'
    }
    Write-Host 'Embedded JavaScript bundle verified; this APK does not require Metro.'

    Write-Host "APK ready: $apkPath"

    if ($OutputPath) {
        $resolvedOutputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
        if ([System.IO.Path]::GetExtension($resolvedOutputPath) -ine '.apk') {
            throw '-OutputPath must name an .apk file.'
        }
        $outputDirectory = Split-Path -Parent $resolvedOutputPath
        if ($outputDirectory -and -not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
            New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
        }
        Copy-Item -LiteralPath $apkPath -Destination $resolvedOutputPath -Force
        $artifact = Get-Item -LiteralPath $resolvedOutputPath
        $sha256 = (Get-FileHash -LiteralPath $resolvedOutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-Host "Shareable APK copy: $($artifact.FullName)"
        Write-Host "APK size: $($artifact.Length) bytes"
        Write-Host "APK SHA-256: $sha256"
    }

    if ($NoInstall) {
        return
    }

    $adbPath = Resolve-AdbPath
    if (-not $adbPath) {
        throw @"
adb.exe was not found. Install Android SDK Platform-Tools in Android Studio (Tools > SDK Manager > SDK Tools),
then rerun this script. The SDK path can be supplied through ANDROID_SDK_ROOT or ANDROID_HOME.
"@
    }

    $devicesResult = Invoke-NativeCommand -FilePath $adbPath -Arguments @('devices', '-l')
    $deviceLines = $devicesResult.Output
    $devicesExitCode = $devicesResult.ExitCode
    if ($devicesExitCode -ne 0) {
        throw "adb devices failed using '$adbPath'."
    }
    $deviceRows = @($deviceLines | Where-Object { $_ -match '^\S+\s+(device|unauthorized|offline)\b' })

    if ($DeviceSerial) {
        $selectedRow = $deviceRows | Where-Object { $_ -match ('^' + [regex]::Escape($DeviceSerial) + '\s+') } | Select-Object -First 1
        if (-not $selectedRow) {
            $deviceLines | ForEach-Object { Write-Host $_ }
            throw "Device '$DeviceSerial' is not listed by adb."
        }
    }
    else {
        $readyRows = @($deviceRows | Where-Object { $_ -match '^\S+\s+device\b' })
        if ($readyRows.Count -eq 0) {
            $deviceLines | ForEach-Object { Write-Host $_ }
            throw 'No authorized ADB device found. Unlock the phone, enable USB debugging, accept its RSA prompt, and check the Windows USB driver.'
        }
        if ($readyRows.Count -gt 1) {
            $deviceLines | ForEach-Object { Write-Host $_ }
            throw 'More than one ADB device is connected. Rerun with -DeviceSerial <serial>.'
        }
        $selectedRow = $readyRows[0]
    }

    if ($selectedRow -match '^\S+\s+(unauthorized|offline)\b') {
        $deviceLines | ForEach-Object { Write-Host $_ }
        throw "ADB device is $($Matches[1]). Unlock the phone and accept the USB debugging prompt, or reconnect it if offline."
    }
    $selectedSerial = ($selectedRow -split '\s+')[0]

    if ($Launch -or $Logcat) {
        $apiUri = [System.Uri]$effectiveApiBaseUrl
        if ($apiUri.IsLoopback) {
            $apiPort = $apiUri.Port
            Write-Host "Forwarding local API port $apiPort to device $selectedSerial..."
            $apiReverseResult = Invoke-NativeCommand -FilePath $adbPath -Arguments @('-s', $selectedSerial, 'reverse', "tcp:$apiPort", "tcp:$apiPort")
            $apiReverseResult.Output | ForEach-Object { Write-Host $_ }
            if ($apiReverseResult.ExitCode -ne 0) {
                throw "Could not configure adb reverse for local API port $apiPort."
            }
        }
    }

    Write-Host "Installing on device: $selectedSerial"
    $installResult = Invoke-NativeCommand -FilePath $adbPath -Arguments @('-s', $selectedSerial, 'install', '-r', $apkPath)
    $installOutput = $installResult.Output
    $installExitCode = $installResult.ExitCode
    $installOutput | ForEach-Object { Write-Host $_ }
    if ($installExitCode -ne 0) {
        throw "APK installation failed with exit code $installExitCode."
    }

    $logProcess = $null
    $logFile = $null
    if ($Logcat) {
        $logDirectory = Join-Path ([System.IO.Path]::GetTempPath()) 'go-mobile-android-logs'
        New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
        $safeSerial = $selectedSerial -replace '[^A-Za-z0-9_.-]', '_'
        $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $logFile = Join-Path $logDirectory "go-android-$safeSerial-$timestamp.log"
        $stderrFile = Join-Path $logDirectory "go-android-$safeSerial-$timestamp-adb-stderr.log"
        $logProcess = Start-Process -FilePath $adbPath `
            -ArgumentList @('-s', $selectedSerial, 'logcat', '-v', 'time') `
            -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $logFile -RedirectStandardError $stderrFile
        Start-Sleep -Milliseconds 800
        if ($logProcess.HasExited) {
            throw "Could not start adb logcat. See $stderrFile"
        }
    }

    if ($Launch -or $Logcat) {
        Write-Host 'Launching APK with its embedded JavaScript bundle; Metro and adb reverse are not required.'
        Write-Host "Launching $applicationId..."
        $launchResult = Invoke-NativeCommand -FilePath $adbPath -Arguments @('-s', $selectedSerial, 'shell', 'monkey', '-p', $applicationId, '1')
        $launchOutput = $launchResult.Output
        $launchExitCode = $launchResult.ExitCode
        $launchOutput | ForEach-Object { Write-Host $_ }
        if ($launchExitCode -ne 0) {
            if ($logProcess -and -not $logProcess.HasExited) { Stop-Process -Id $logProcess.Id -Force }
            throw 'APK installed, but the app launch command failed.'
        }
    }

    if ($Logcat) {
        Write-Host "Capturing device logcat for $LogcatSeconds seconds. Reproduce the issue on the phone now."
        Write-Host "Log file: $logFile"
        Wait-Process -Id $logProcess.Id -Timeout $LogcatSeconds -ErrorAction SilentlyContinue
        if (-not $logProcess.HasExited) {
            Stop-Process -Id $logProcess.Id -Force
        }
        Write-Host "Log capture complete: $logFile"
        Write-Host 'Review logs for tokens, personal data, and other secrets before sharing.'
    }
}
finally {
    if ($mappedGradleDrive) {
        & subst.exe $mappedGradleDrive /d | Out-Null
    }
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
}
