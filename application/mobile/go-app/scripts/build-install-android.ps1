# From the repository root:
#   .\application\mobile\go-app\scripts\build-install-android.cmd -Launch
# From the mobile app root:
#   .\scripts\build-install-android.cmd -Launch
#   .\scripts\build-install-android.cmd -ApiBaseUrl https://api.example.com -Launch -Logcat
#   .\scripts\build-install-android.cmd -DeviceSerial emulator-5554 -NoInstall
[CmdletBinding()]
param(
    [string]$DeviceSerial,
    [string]$ApiBaseUrl,
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

if (-not (Test-Path -LiteralPath $gradleWrapper -PathType Leaf)) {
    throw "Gradle wrapper not found: $gradleWrapper"
}
if (-not (Test-Path -LiteralPath (Join-Path $mobileRoot 'node_modules\expo\package.json') -PathType Leaf)) {
    throw "Mobile dependencies are missing. Run 'npm ci' in $mobileRoot first."
}
if (-not (Get-Command 'node.exe' -ErrorAction SilentlyContinue)) {
    throw 'Node.js was not found on PATH. Install Node.js and reopen PowerShell.'
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

    if ($ApiBaseUrl) {
        $env:EXPO_PUBLIC_API_URL = $ApiBaseUrl.TrimEnd('/')
        Write-Host "Using API base URL from -ApiBaseUrl: $env:EXPO_PUBLIC_API_URL"
    }

    Write-Host 'Building Android Debug APK...'
    Push-Location $androidRoot
    try {
        $buildResult = Invoke-NativeCommand -FilePath $gradleWrapper -Arguments @(':app:assembleDebug')
        $buildOutput = $buildResult.Output
        $buildExitCode = $buildResult.ExitCode
        $buildOutput | ForEach-Object { Write-Host $_ }
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
    Write-Host "APK ready: $apkPath"

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
        $metroStatusUrl = 'http://127.0.0.1:8081/status'
        $metroReady = $false
        try {
            $metroStatus = Invoke-WebRequest -UseBasicParsing -Uri $metroStatusUrl -TimeoutSec 2
            $metroReady = $metroStatus.Content -match 'packager-status:running'
        }
        catch {
            $metroReady = $false
        }

        if (-not $metroReady) {
            $npmCommand = Get-Command 'npm.cmd' -ErrorAction SilentlyContinue
            if (-not $npmCommand) {
                throw 'Metro is not running and npm.cmd was not found on PATH. Start Metro manually from the mobile app directory.'
            }
            $metroLogDirectory = Join-Path ([System.IO.Path]::GetTempPath()) 'go-mobile-android-logs'
            New-Item -ItemType Directory -Path $metroLogDirectory -Force | Out-Null
            $metroLog = Join-Path $metroLogDirectory 'metro-8081.log'
            $metroErrorLog = Join-Path $metroLogDirectory 'metro-8081-stderr.log'
            $env:EXPO_NO_TYPESCRIPT_SETUP = '1'
            Start-Process -FilePath $npmCommand.Source `
                -ArgumentList @('run', 'start', '--', '--localhost', '--port', '8081') `
                -WorkingDirectory $mobileRoot -WindowStyle Hidden `
                -RedirectStandardOutput $metroLog -RedirectStandardError $metroErrorLog | Out-Null

            $metroDeadline = (Get-Date).AddSeconds(60)
            while ((Get-Date) -lt $metroDeadline) {
                Start-Sleep -Seconds 2
                try {
                    $metroStatus = Invoke-WebRequest -UseBasicParsing -Uri $metroStatusUrl -TimeoutSec 2
                    if ($metroStatus.Content -match 'packager-status:running') {
                        $metroReady = $true
                        break
                    }
                }
                catch {
                    # Metro can take several seconds to initialize its Expo config.
                }
            }
            if (-not $metroReady) {
                throw "Metro did not become ready at $metroStatusUrl within 60 seconds. See $metroLog and $metroErrorLog"
            }
            Write-Host "Metro started. Log: $metroLog"
        }

        $reverseResult = Invoke-NativeCommand -FilePath $adbPath -Arguments @('-s', $selectedSerial, 'reverse', 'tcp:8081', 'tcp:8081')
        $reverseOutput = $reverseResult.Output
        $reverseExitCode = $reverseResult.ExitCode
        $reverseOutput | ForEach-Object { Write-Host $_ }
        if ($reverseExitCode -ne 0) {
            throw 'Metro is running, but adb reverse for tcp:8081 failed.'
        }

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
