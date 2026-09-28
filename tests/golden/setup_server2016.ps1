# 'Continue' means: if a command fails, print the error but keep going.
# We don't want one failed tweak to abort the entire setup.
$ErrorActionPreference = 'Continue'

# Log to serial port (COM1) so the host can see progress in real time.
# We open the port once and keep it open for the duration of the script.
try {
    $serial = [System.IO.Ports.SerialPort]::new('COM1', 115200)
    $serial.Open()
} catch {
    $serial = $null
}
function Log($msg) {
    Write-Host $msg
    if ($serial -and $serial.IsOpen) {
        try { $serial.WriteLine($msg) } catch {}
    }
}

Log "[SETUP] Starting PowerShell configuration"

# =====================================================================
# DEFAULT USER REGISTRY SETTINGS
# =====================================================================
# Windows stores per-user settings in each user's NTUSER.DAT file (a
# registry hive). C:\Users\Default\NTUSER.DAT is the TEMPLATE — when a
# new user profile is created, Windows copies this file as the starting
# point. By modifying it now, every future user gets these settings.
#
# "reg load" mounts the hive at HKU\DefaultUser so we can edit it.
# After we're done, we MUST unload it — if we don't, the file stays
# locked and new user profile creation will fail.
Log "[SETUP] Loading DefaultUser registry hive"
reg.exe load "HKU\DefaultUser" "C:\Users\Default\NTUSER.DAT"

# FILE EXPLORER: show file extensions (.txt, .exe, etc.) and open
# to "This PC" instead of the default "Quick Access" / "Home" view.
reg.exe add "HKU\DefaultUser\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" /v HideFileExt /t REG_DWORD /d 0 /f
reg.exe add "HKU\DefaultUser\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" /v LaunchTo /t REG_DWORD /d 1 /f

# COPILOT: disable the AI assistant sidebar per-user
reg.exe add "HKU\DefaultUser\Software\Policies\Microsoft\Windows\WindowsCopilot" /v TurnOffWindowsCopilot /t REG_DWORD /d 1 /f

# CONTENT DELIVERY MANAGER: disable all "suggested" content.
# These are the mechanisms Windows uses to install apps you didn't
# ask for, show "tips" that are really ads, and push notifications
# about Microsoft services. Each SubscribedContent-NNNN key controls
# a specific type of suggestion (Start menu, lock screen, etc.)
$cdm = "HKU\DefaultUser\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"
foreach ($v in @(
    "ContentDeliveryAllowed",
    "FeatureManagementEnabled",
    "OEMPreInstalledAppsEnabled",
    "PreInstalledAppsEnabled",
    "PreInstalledAppsEverEnabled",
    "SilentInstalledAppsEnabled",
    "SoftLandingEnabled",
    "SubscribedContentEnabled",
    "SubscribedContent-310093Enabled",
    "SubscribedContent-338387Enabled",
    "SubscribedContent-338388Enabled",
    "SubscribedContent-338389Enabled",
    "SubscribedContent-338393Enabled",
    "SubscribedContent-353694Enabled",
    "SubscribedContent-353696Enabled",
    "SubscribedContent-353698Enabled",
    "SystemPaneSuggestionsEnabled"
)) {
    reg.exe add $cdm /v $v /t REG_DWORD /d 0 /f
}

# Disable Bing web results in Start menu search
reg.exe add "HKU\DefaultUser\Software\Policies\Microsoft\Windows\Explorer" /v DisableSearchBoxSuggestions /t REG_DWORD /d 1 /f

# DARK MODE: set per-user default for apps and system chrome
$personalize = "HKU\DefaultUser\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
reg.exe add $personalize /v AppsUseLightTheme /t REG_DWORD /d 0 /f
reg.exe add $personalize /v SystemUsesLightTheme /t REG_DWORD /d 0 /f

# SHOW HIDDEN FILES: Hidden=1 means show, 2 means don't show
reg.exe add "HKU\DefaultUser\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" /v Hidden /t REG_DWORD /d 1 /f

# DISABLE ANIMATIONS: reduces visual effects for snappier VM feel
reg.exe add "HKU\DefaultUser\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects" /v VisualFXSetting /t REG_DWORD /d 2 /f
reg.exe add "HKU\DefaultUser\Control Panel\Desktop" /v UserPreferencesMask /t REG_BINARY /d 9012038010000000 /f
reg.exe add "HKU\DefaultUser\Control Panel\Desktop\WindowMetrics" /v MinAnimate /t REG_SZ /d 0 /f

# CRITICAL: Force garbage collection and wait before unloading.
# PowerShell/.NET may hold references to registry keys. If we unload
# the hive while it's still referenced, the unload fails silently and
# the file stays locked. [gc]::Collect() forces .NET to release all
# references, and the sleep gives the OS time to flush.
[gc]::Collect()
Start-Sleep -Seconds 1
reg.exe unload "HKU\DefaultUser"
Log "[SETUP] DefaultUser hive unloaded"

# =====================================================================
# POWER SETTINGS
# =====================================================================
# In a VM, there's no battery and no physical monitor. Disable screen
# timeout and sleep so the VM doesn't go dark during long builds.
Log "[SETUP] Disabling screen timeout and sleep"
powercfg.exe /change monitor-timeout-ac 0
powercfg.exe /change standby-timeout-ac 0



Log "[SETUP] Suppressing Server Manager auto-launch"
reg.exe add "HKLM\SOFTWARE\Microsoft\ServerManager" /v DoNotOpenServerManagerAtLogon /t REG_DWORD /d 1 /f

# =====================================================================
# SAN POLICY: auto-online new disks (Server defaults to OfflineShared)
# =====================================================================
Log "[SETUP] Setting SAN policy to OnlineAll"
Set-StorageSetting -NewDiskPolicy OnlineAll

# =====================================================================
# OPENSSH (Win10 / Server 2016 — installed from bundled ZIP)
# =====================================================================
# Win11 and Server 2022 use Add-WindowsCapability in FirstLogonCommands.
# Win10 and Server 2016 need the standalone Win32-OpenSSH binary, which
# is pre-downloaded on the host and bundled into the answer-file ISO.
# The ZIP was copied to C:\Windows\Temp during the specialize pass.
$opensshZip = 'C:\Windows\Temp\OpenSSH-Win64.zip'
if (Test-Path $opensshZip) {
    Log "[SETUP] Installing Win32-OpenSSH from bundled ZIP"
    Expand-Archive $opensshZip 'C:\Program Files' -Force
    & 'C:\Program Files\OpenSSH-Win64\install-sshd.ps1'
    & 'C:\Program Files\OpenSSH-Win64\ssh-keygen.exe' -A
    Set-Service sshd -StartupType Automatic
    netsh advfirewall firewall add rule name='OpenSSH Server' dir=in action=allow protocol=TCP localport=22
}

Log "[SETUP] PowerShell configuration complete"
if ($serial -and $serial.IsOpen) { $serial.Close() }
