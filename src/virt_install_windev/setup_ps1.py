from __future__ import annotations

from virt_install_windev.config import Config, WinVersion


_LAUNCH_TO_VALUES = {"this_pc": 1, "quick_access": 2}


def _header() -> str:
    return r"""# 'Continue' means: if a command fails, print the error but keep going.
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
"""


def _file_extensions() -> str:
    return r"""
# FILE EXPLORER: show file extensions (.txt, .exe, etc.) and open
# to "This PC" instead of the default "Quick Access" / "Home" view.
reg.exe add "HKU\DefaultUser\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" /v HideFileExt /t REG_DWORD /d 0 /f
"""


def _launch_to(value: int) -> str:
    return (
        f'reg.exe add "HKU\\DefaultUser\\Software\\Microsoft\\Windows\\'
        f'CurrentVersion\\Explorer\\Advanced" /v LaunchTo /t REG_DWORD /d {value} /f\n'
    )


def _copilot_disable() -> str:
    return r"""
# COPILOT: disable the AI assistant sidebar per-user
reg.exe add "HKU\DefaultUser\Software\Policies\Microsoft\Windows\WindowsCopilot" /v TurnOffWindowsCopilot /t REG_DWORD /d 1 /f
"""


def _content_delivery_manager_disable() -> str:
    return r"""
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
"""


def _bing_search_disable() -> str:
    return r"""
# Disable Bing web results in Start menu search
reg.exe add "HKU\DefaultUser\Software\Policies\Microsoft\Windows\Explorer" /v DisableSearchBoxSuggestions /t REG_DWORD /d 1 /f
"""


def _dark_mode() -> str:
    return r"""
# DARK MODE: set per-user default for apps and system chrome
$personalize = "HKU\DefaultUser\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
reg.exe add $personalize /v AppsUseLightTheme /t REG_DWORD /d 0 /f
reg.exe add $personalize /v SystemUsesLightTheme /t REG_DWORD /d 0 /f
"""


def _hidden_files() -> str:
    return r"""
# SHOW HIDDEN FILES: Hidden=1 means show, 2 means don't show
reg.exe add "HKU\DefaultUser\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" /v Hidden /t REG_DWORD /d 1 /f
"""


def _animations_disable() -> str:
    return r"""
# DISABLE ANIMATIONS: reduces visual effects for snappier VM feel
reg.exe add "HKU\DefaultUser\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects" /v VisualFXSetting /t REG_DWORD /d 2 /f
reg.exe add "HKU\DefaultUser\Control Panel\Desktop" /v UserPreferencesMask /t REG_BINARY /d 9012038010000000 /f
reg.exe add "HKU\DefaultUser\Control Panel\Desktop\WindowMetrics" /v MinAnimate /t REG_SZ /d 0 /f
"""


def _hive_unload() -> str:
    return r"""
# CRITICAL: Force garbage collection and wait before unloading.
# PowerShell/.NET may hold references to registry keys. If we unload
# the hive while it's still referenced, the unload fails silently and
# the file stays locked. [gc]::Collect() forces .NET to release all
# references, and the sleep gives the OS time to flush.
[gc]::Collect()
Start-Sleep -Seconds 1
reg.exe unload "HKU\DefaultUser"
Log "[SETUP] DefaultUser hive unloaded"
"""


def _power_settings(monitor_timeout: int, sleep_timeout: int) -> str:
    return (
        "\n"
        "# =====================================================================\n"
        "# POWER SETTINGS\n"
        "# =====================================================================\n"
        "# In a VM, there's no battery and no physical monitor. Disable screen\n"
        "# timeout and sleep so the VM doesn't go dark during long builds.\n"
        'Log "[SETUP] Disabling screen timeout and sleep"\n'
        f"powercfg.exe /change monitor-timeout-ac {monitor_timeout}\n"
        f"powercfg.exe /change standby-timeout-ac {sleep_timeout}\n"
    )


def _windows_terminal_config(version: WinVersion) -> str:
    if version not in (WinVersion.WIN10, WinVersion.WIN11):
        return ""
    return r'''# =====================================================================
# WINDOWS TERMINAL: write default settings for all new users
# =====================================================================
Log "[SETUP] Configuring Windows Terminal defaults"
$wtDir = 'C:\Users\Default\AppData\Local\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState'
New-Item -ItemType Directory -Force -Path $wtDir | Out-Null
@'
{
    "$schema": "https://aka.ms/terminal-profiles-schema",
    "defaultProfile": "{61c54bbd-c2c6-5271-96e7-009a87ff44bf}",
    "theme": "dark",
    "confirmCloseAllTabs": false,
    "profiles": {
        "defaults": {
            "font": {
                "face": "Cascadia Mono",
                "size": 12
            },
            "opacity": 95,
            "useAcrylic": true,
            "padding": "8",
            "startingDirectory": "C:\\Users\\%USERNAME%"
        },
        "list": []
    },
    "actions": []
}
'@ | Set-Content (Join-Path $wtDir 'settings.json') -Encoding UTF8
'''


def _wsl(version: WinVersion) -> str:
    if version not in (WinVersion.WIN10, WinVersion.WIN11):
        return ""
    return (
        "# =====================================================================\n"
        "# ENABLE WSL (Windows Subsystem for Linux)\n"
        "# =====================================================================\n"
        "# WSL lets you run Linux distributions inside Windows. Two features\n"
        "# are needed:\n"
        "#   1. Microsoft-Windows-Subsystem-Linux: the WSL core\n"
        "#   2. VirtualMachinePlatform: required for WSL 2 (which runs a real\n"
        "#      Linux kernel in a lightweight VM — much faster than WSL 1)\n"
        "# After the VM boots, run \"wsl --install\" to pick a distro.\n"
        'Log "[SETUP] Enabling WSL and VirtualMachinePlatform"\n'
        "dism.exe /Online /Enable-Feature /FeatureName:Microsoft-Windows-Subsystem-Linux /All /NoRestart\n"
        "dism.exe /Online /Enable-Feature /FeatureName:VirtualMachinePlatform /All /NoRestart\n"
    )


def _server_manager(version: WinVersion) -> str:
    if version not in (WinVersion.SERVER2016, WinVersion.SERVER2022):
        return ""
    return (
        'Log "[SETUP] Suppressing Server Manager auto-launch"\n'
        'reg.exe add "HKLM\\SOFTWARE\\Microsoft\\ServerManager"'
        " /v DoNotOpenServerManagerAtLogon /t REG_DWORD /d 1 /f\n"
    )


def _san_policy(version: WinVersion) -> str:
    if version not in (WinVersion.SERVER2016, WinVersion.SERVER2022):
        return ""
    return (
        "# =====================================================================\n"
        "# SAN POLICY: auto-online new disks (Server defaults to OfflineShared)\n"
        "# =====================================================================\n"
        'Log "[SETUP] Setting SAN policy to OnlineAll"\n'
        "Set-StorageSetting -NewDiskPolicy OnlineAll\n\n"
    )


def _openssh_zip() -> str:
    return r"""# =====================================================================
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
"""


def _footer() -> str:
    return r"""Log "[SETUP] PowerShell configuration complete"
if ($serial -and $serial.IsOpen) { $serial.Close() }
"""


def generate_setup_ps1(config: Config) -> str:
    s = config.settings
    v = config.win_version
    parts: list[str] = []

    parts.append(_header())

    if s.file_extensions:
        parts.append(_file_extensions())

    launch_val = _LAUNCH_TO_VALUES.get(s.launch_to)
    if launch_val is not None:
        parts.append(_launch_to(launch_val))

    if not s.copilot:
        parts.append(_copilot_disable())

    if not s.consumer_features:
        parts.append(_content_delivery_manager_disable())

    if not s.bing_search:
        parts.append(_bing_search_disable())

    if s.dark_mode:
        parts.append(_dark_mode())

    if s.hidden_files:
        parts.append(_hidden_files())

    if not s.animations:
        parts.append(_animations_disable())

    parts.append(_hive_unload())
    parts.append(_power_settings(s.monitor_timeout, s.sleep_timeout))

    # Assemble version/settings-conditional middle sections.
    # Replicate the original template's whitespace: each token slot
    # contributes a \n separator, even when the replacement is empty.
    wt = _windows_terminal_config(v) if s.windows_terminal else ""
    wsl_block = _wsl(v) if s.wsl else ""
    sm_block = _server_manager(v)
    wsl_sm = wsl_block + sm_block
    san = _san_policy(v)
    parts.append("\n\n" + wt + "\n" + wsl_sm + "\n" + san)

    if s.openssh:
        parts.append(_openssh_zip())

    parts.append("\n" + _footer())

    return "".join(parts)
