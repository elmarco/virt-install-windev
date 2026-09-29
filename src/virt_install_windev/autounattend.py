from __future__ import annotations

import re
from pathlib import Path

from virt_install_windev.config import Config, WinVersion, VERSION_PARAMS
from virt_install_windev.util import xml_escape


_GVLK: dict[WinVersion, str] = {
    WinVersion.WIN11: "NPPR9-FWDCX-D2C8J-H872K-2YT43",
    WinVersion.SERVER2016: "WC2BQ-8NRM3-FDDYY-2BFGV-KHKQY",
    WinVersion.SERVER2022: "VDYBN-27WPP-V4HQT-9VMD4-VMK7H",
}


def user_data_for(version: WinVersion) -> str:
    gvlk = _GVLK.get(version)
    if gvlk:
        return (
            "<UserData>\n"
            "        <AcceptEula>true</AcceptEula>\n"
            "        <ProductKey>\n"
            "          <Key>" + gvlk + "</Key>\n"
            "          <WillShowUI>Never</WillShowUI>\n"
            "        </ProductKey>\n"
            "      </UserData>"
        )
    return (
        "<UserData>\n"
        "        <AcceptEula>true</AcceptEula>\n"
        "      </UserData>"
    )


# ---------------------------------------------------------------------------
# Command builders — assemble RunSynchronous / FirstLogonCommands XML
# from Config.settings.
# ---------------------------------------------------------------------------

def _sync_cmd(order: int, path: str) -> str:
    return (
        f'        <RunSynchronousCommand wcm:action="add">\n'
        f'          <Order>{order}</Order>\n'
        f'          <Path>{xml_escape(path)}</Path>\n'
        f'        </RunSynchronousCommand>'
    )


def _firstlogon_cmd(order: int, cmdline: str) -> str:
    return (
        f'        <SynchronousCommand wcm:action="add">\n'
        f'          <Order>{order}</Order>\n'
        f'          <CommandLine>{xml_escape(cmdline)}</CommandLine>\n'
        f'        </SynchronousCommand>'
    )


def _specialize_cmds(config: Config) -> list[str]:
    """Return list of command paths for the specialize RunSynchronous section."""
    s = config.settings
    v = config.win_version
    cmds: list[str] = []

    cmds.append(
        'cmd /c "echo [SPECIALIZE] Configuring system settings > COM1 || exit /b 0"')

    # ConX workaround: copy answer file for oobeSystem pass
    cmds.append(
        'cmd /c for %d in (D E F G H I) do @if exist'
        ' %d:\\autounattend.xml copy /y %d:\\autounattend.xml C:\\unattend.xml')

    # Bypass network requirement for OOBE
    cmds.append(
        'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\OOBE"'
        ' /v BypassNRO /t REG_DWORD /d 1 /f')

    if not s.uac:
        cmds.append(
            'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion'
            '\\Policies\\System" /v EnableLUA /t REG_DWORD /d 0 /f')

    if not s.vbs:
        cmds.append(
            'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\DeviceGuard"'
            ' /v EnableVirtualizationBasedSecurity /t REG_DWORD /d 0 /f')
        cmds.append(
            'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\DeviceGuard'
            '\\Scenarios\\HypervisorEnforcedCodeIntegrity"'
            ' /v Enabled /t REG_DWORD /d 0 /f')

    if not s.defender:
        cmds.append(
            'cmd /c "echo [SPECIALIZE] Disabling Defender services'
            ' > COM1 || exit /b 0"')
        for svc in ("Sense", "WdBoot", "WdFilter",
                     "WdNisDrv", "WdNisSvc", "WinDefend"):
            cmds.append(
                f'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\{svc}"'
                ' /v Start /t REG_DWORD /d 4 /f')

    if not s.hibernation:
        cmds.append(
            'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control'
            '\\Session Manager\\Power"'
            ' /v HiberbootEnabled /t REG_DWORD /d 0 /f')

    cmds.append(
        'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows'
        '\\DataCollection"'
        f' /v AllowTelemetry /t REG_DWORD /d {s.telemetry} /f')

    if s.update_notify:
        cmds.append(
            'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows'
            '\\WindowsUpdate\\AU" /v AUOptions /t REG_DWORD /d 2 /f')
    if s.no_auto_reboot:
        cmds.append(
            'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows'
            '\\WindowsUpdate\\AU"'
            ' /v NoAutoRebootWithLoggedOnUsers /t REG_DWORD /d 1 /f')

    if not s.consumer_features:
        cmds.append(
            'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows'
            '\\CloudContent"'
            ' /v DisableWindowsConsumerFeatures /t REG_DWORD /d 1 /f')

    if not s.widgets:
        cmds.append(
            'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Dsh"'
            ' /v AllowNewsAndInterests /t REG_DWORD /d 0 /f')

    if s.developer_mode:
        cmds.append(
            'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion'
            '\\AppModelUnlock"'
            ' /v AllowDevelopmentWithoutDevLicense /t REG_DWORD /d 1 /f')

    if s.long_paths:
        cmds.append(
            'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem"'
            ' /v LongPathsEnabled /t REG_DWORD /d 1 /f')

    if not s.lock_screen:
        cmds.append(
            'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows'
            '\\Personalization" /v NoLockScreen /t REG_DWORD /d 1 /f')

    if not s.recall:
        cmds.append(
            'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows'
            '\\WindowsAI" /v DisableAIDataAnalysis /t REG_DWORD /d 1 /f')

    if s.dark_mode:
        cmds.append(
            'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion'
            '\\Themes\\Personalize"'
            ' /v AppsUseLightTheme /t REG_DWORD /d 0 /f')
        cmds.append(
            'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion'
            '\\Themes\\Personalize"'
            ' /v SystemUsesLightTheme /t REG_DWORD /d 0 /f')

    if s.rdp_usb_redirection:
        cmds.append(
            'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows NT'
            '\\Terminal Services"'
            ' /v fDisablePNPRedir /t REG_DWORD /d 0 /f')
        cmds.append(
            'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows NT'
            '\\Terminal Services"'
            ' /v fUsbRedirectionEnable /t REG_DWORD /d 1 /f')
        cmds.append(
            'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows NT'
            '\\Terminal Services"'
            ' /v fUsbRedirectionUseDefaultList /t REG_DWORD /d 1 /f')

    if s.openssh and v in (WinVersion.WIN10, WinVersion.SERVER2016):
        cmds.append(
            'cmd /c for %d in (D E F G H I) do @if exist'
            ' %d:\\OpenSSH-Win64.zip copy /y %d:\\OpenSSH-Win64.zip'
            ' C:\\Windows\\Temp\\OpenSSH-Win64.zip')

    cmds.append(
        'cmd /c "echo [SPECIALIZE] Running setup.ps1 > COM1 || exit /b 0"')
    cmds.append(
        'cmd /c mkdir C:\\Windows\\Setup\\Scripts 2>nul'
        ' & for %d in (D E F G H I) do @if exist %d:\\setup.ps1'
        ' copy /y %d:\\setup.ps1 C:\\Windows\\Setup\\Scripts\\setup.ps1')
    cmds.append(
        'powershell -ExecutionPolicy Bypass'
        ' -File C:\\Windows\\Setup\\Scripts\\setup.ps1')

    for script_path in config.post_install_scripts:
        name = script_path.name
        cmds.append(
            f'cmd /c for %d in (D E F G H I) do @if exist %d:\\{name}'
            f' copy /y %d:\\{name}'
            f' C:\\Windows\\Setup\\Scripts\\{name}')

    cmds.append('bcdedit /timeout 0')
    cmds.append(
        'cmd /c "echo [SPECIALIZE] Done, rebooting into OOBE'
        ' > COM1 || exit /b 0"')

    return cmds


def _firstlogon_cmds(config: Config) -> list[str]:
    """Return list of command lines for the oobeSystem FirstLogonCommands."""
    s = config.settings
    v = config.win_version
    cmds: list[str] = []

    cmds.append(
        'cmd /c "echo [OOBE] First login, installing VirtIO guest tools'
        ' > COM1 || exit /b 0"')
    cmds.append(
        'cmd /c for %d in (D E F G H I) do @if exist'
        ' %d:\\virtio-win-guest-tools.exe'
        ' %d:\\virtio-win-guest-tools.exe /install /passive /norestart')

    if v in (WinVersion.SERVER2016, WinVersion.SERVER2022):
        cmds.append(
            'cmd /c "echo [OOBE] Installing RDSH role for USB redirection'
            ' > COM1 || exit /b 0"')
        cmds.append(
            'powershell -Command "Install-WindowsFeature -Name RDS-RD-Server'
            ' -ErrorAction Continue"')

    # Set network profile to Private (needed for RDP/SSH)
    cmds.append(
        "powershell -Command \"Get-NetConnectionProfile"
        " | Set-NetConnectionProfile -NetworkCategory Private"
        " -ErrorAction SilentlyContinue;"
        " Enable-NetFirewallRule -DisplayGroup 'Remote Desktop'"
        ' -ErrorAction SilentlyContinue"')

    if s.openssh:
        cmds.append(
            'cmd /c "echo [OOBE] Installing OpenSSH Server'
            ' > COM1 || exit /b 0"')

        if v in (WinVersion.WIN11, WinVersion.SERVER2022):
            cmds.append(
                'powershell -Command "'
                "Add-WindowsCapability -Online"
                " -Name 'OpenSSH.Server~~~~0.0.1.0'"
                " -ErrorAction Continue;"
                " $n=0; while (-not (Get-Service sshd"
                " -ErrorAction SilentlyContinue)"
                " -and $n -lt 30) { Start-Sleep 1; $n++ };"
                " Set-Service -Name sshd -StartupType Automatic"
                " -ErrorAction Continue;"
                " Start-Service sshd -ErrorAction Continue;"
                " netsh advfirewall firewall add rule name='OpenSSH Server'"
                ' dir=in action=allow protocol=TCP localport=22"')
        else:
            cmds.append(
                'powershell -Command'
                ' "Start-Service sshd -ErrorAction Continue"')

        # Deploy authorized keys
        cmds.append(
            "powershell -Command"
            " \"$f = 'C:\\ProgramData\\ssh\\administrators_authorized_keys';"
            " foreach ($d in 'D','E','F','G','H','I')"
            ' { $p = \\"${d}:\\authorized_keys\\";'
            " if (Test-Path $p) { Copy-Item $p $f -Force; break } };"
            " if (Test-Path $f)"
            " { icacls $f /inheritance:r /grant 'SYSTEM:(F)'"
            " /grant 'Administrators:(F)' }\"")

    if s.remove_bloatware:
        cmds.append(
            'cmd /c "echo [OOBE] Removing bloatware > COM1 || exit /b 0"')
        keep = '|'.join(s.bloatware_keep)
        cmds.append(
            'powershell -Command "Get-AppxProvisionedPackage -Online'
            f" | Where-Object {{ $_.DisplayName -notmatch '{keep}' }}"
            ' | Remove-AppxProvisionedPackage -AllUsers -Online'
            ' -ErrorAction Continue"')

    if s.winget_packages:
        cmds.append(
            'cmd /c "echo [OOBE] Installing packages > COM1 || exit /b 0"')
        # Bootstrap winget if needed
        cmds.append(
            'powershell -Command "'
            "if (Get-Command winget -ErrorAction SilentlyContinue) { exit };"
            " $ProgressPreference='SilentlyContinue'; $t=$env:TEMP;"
            " try { Invoke-WebRequest"
            " 'https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx'"
            " -OutFile $t\\vcl.appx -UseBasicParsing;"
            " Add-AppxPackage $t\\vcl.appx } catch {};"
            " try { Invoke-WebRequest"
            " 'https://www.nuget.org/api/v2/package/Microsoft.UI.Xaml/2.8.6'"
            " -OutFile $t\\uix.zip -UseBasicParsing;"
            " Expand-Archive $t\\uix.zip $t\\uix -Force;"
            " Add-AppxPackage"
            " (Get-ChildItem $t\\uix\\tools\\AppX\\x64\\Release\\*.appx)"
            ".FullName } catch {};"
            " try { Invoke-WebRequest"
            " 'https://github.com/microsoft/winget-cli/releases/latest"
            "/download/Microsoft.DesktopAppInstaller_8wekyb3d8bbwe"
            ".msixbundle'"
            " -OutFile $t\\wg.msix -UseBasicParsing;"
            ' Add-AppxPackage $t\\wg.msix } catch {}"')
        for pkg in s.winget_packages:
            cmds.append(
                f'cmd /c winget install {pkg}'
                ' --accept-source-agreements --accept-package-agreements'
                ' --silent')

    if config.post_install_scripts:
        cmds.append(
            'cmd /c "echo [OOBE] Running post-install scripts'
            ' > COM1 || exit /b 0"')
        for script_path in config.post_install_scripts:
            cmds.append(
                'powershell -ExecutionPolicy Bypass'
                f' -File C:\\Windows\\Setup\\Scripts\\{script_path.name}')

    cmds.append(
        'cmd /c "echo INSTALLATION_COMPLETE > COM1 || exit /b 0"')
    cmds.append('shutdown /s /t 30 /c "Installation complete"')

    return cmds


def _render_specialize_commands(config: Config) -> str:
    cmds = _specialize_cmds(config)
    parts = [_sync_cmd(i, path) for i, path in enumerate(cmds, 1)]
    return '\n'.join(parts)


def _render_firstlogon_commands(config: Config) -> str:
    cmds = _firstlogon_cmds(config)
    parts = [_firstlogon_cmd(i, cmdline) for i, cmdline in enumerate(cmds, 1)]
    return '\n'.join(parts)


def _rdp_components(config: Config) -> str:
    if not config.settings.rdp:
        return ""
    return r"""
    <component name="Microsoft-Windows-TerminalServices-LocalSessionManager"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <fDenyTSConnections>false</fDenyTSConnections>
    </component>

    <component name="Networking-MPSSVC-Svc"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <FirewallGroups>
        <FirewallGroup wcm:action="add" wcm:keyValue="RemoteDesktop">
          <Active>true</Active>
          <Group>Remote Desktop</Group>
          <Profile>all</Profile>
        </FirewallGroup>
      </FirewallGroups>
    </component>
"""


# ---------------------------------------------------------------------------
# Template: the full autounattend.xml with token placeholders.
# ---------------------------------------------------------------------------

_TEMPLATE = r"""<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">

  <settings pass="windowsPE">

    <component name="Microsoft-Windows-International-Core-WinPE"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <SetupUILanguage>
        <UILanguage>LOCALE_VALUE</UILanguage>
      </SetupUILanguage>
      <InputLocale>LOCALE_VALUE</InputLocale>
      <SystemLocale>LOCALE_VALUE</SystemLocale>
      <UILanguage>LOCALE_VALUE</UILanguage>
      <UserLocale>LOCALE_VALUE</UserLocale>
    </component>

    <component name="Microsoft-Windows-PnpCustomizationsWinPE"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <DriverPaths>
        <PathAndCredentials wcm:action="add" wcm:keyValue="1">
          <Path>E:\NetKVM\VIRTIO_DRIVER_DIR\amd64</Path>
        </PathAndCredentials>
        <PathAndCredentials wcm:action="add" wcm:keyValue="2">
          <Path>E:\viostor\VIRTIO_DRIVER_DIR\amd64</Path>
        </PathAndCredentials>
        <PathAndCredentials wcm:action="add" wcm:keyValue="3">
          <Path>E:\qxldod\VIRTIO_DRIVER_DIR\amd64</Path>
        </PathAndCredentials>
        <PathAndCredentials wcm:action="add" wcm:keyValue="4">
          <Path>E:\vioscsi\VIRTIO_DRIVER_DIR\amd64</Path>
        </PathAndCredentials>
        <PathAndCredentials wcm:action="add" wcm:keyValue="5">
          <Path>E:\Balloon\VIRTIO_DRIVER_DIR\amd64</Path>
        </PathAndCredentials>
        <PathAndCredentials wcm:action="add" wcm:keyValue="6">
          <Path>E:\vioserial\VIRTIO_DRIVER_DIR\amd64</Path>
        </PathAndCredentials>
        <PathAndCredentials wcm:action="add" wcm:keyValue="7">
          <Path>E:\viorng\VIRTIO_DRIVER_DIR\amd64</Path>
        </PathAndCredentials>
      </DriverPaths>
    </component>

    <component name="Microsoft-Windows-Setup"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">

      <RunSynchronous>
        <RunSynchronousCommand wcm:action="add">
          <Order>1</Order>
          <Path>reg add "HKLM\SYSTEM\Setup\LabConfig" /v BypassTPMCheck /t REG_DWORD /d 1 /f</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>2</Order>
          <Path>reg add "HKLM\SYSTEM\Setup\LabConfig" /v BypassSecureBootCheck /t REG_DWORD /d 1 /f</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>3</Order>
          <Path>reg add "HKLM\SYSTEM\Setup\LabConfig" /v BypassRAMCheck /t REG_DWORD /d 1 /f</Path>
        </RunSynchronousCommand>
      </RunSynchronous>

      <DiskConfiguration>
        <Disk wcm:action="add">
          <DiskID>0</DiskID>
          <WillWipeDisk>true</WillWipeDisk>
          <CreatePartitions>
            <CreatePartition wcm:action="add">
              <Order>1</Order>
              <Size>260</Size>
              <Type>EFI</Type>
            </CreatePartition>
            <CreatePartition wcm:action="add">
              <Order>2</Order>
              <Size>16</Size>
              <Type>MSR</Type>
            </CreatePartition>
            <CreatePartition wcm:action="add">
              <Order>3</Order>
              <Extend>true</Extend>
              <Type>Primary</Type>
            </CreatePartition>
          </CreatePartitions>
          <ModifyPartitions>
            <ModifyPartition wcm:action="add">
              <Order>1</Order>
              <PartitionID>1</PartitionID>
              <Format>FAT32</Format>
              <Label>EFI</Label>
            </ModifyPartition>
            <ModifyPartition wcm:action="add">
              <Order>2</Order>
              <PartitionID>3</PartitionID>
              <Format>NTFS</Format>
              <Label>Windows</Label>
            </ModifyPartition>
          </ModifyPartitions>
        </Disk>
      </DiskConfiguration>

      <ImageInstall>
        <OSImage>
          <InstallFrom>
            <MetaData wcm:action="add">
              <Key>/IMAGE/INDEX</Key>
              <Value>{IMAGE_INDEX}</Value>
            </MetaData>
          </InstallFrom>
          <InstallTo>
            <DiskID>0</DiskID>
            <PartitionID>3</PartitionID>
          </InstallTo>
        </OSImage>
      </ImageInstall>


      {USERDATA}

    </component>
  </settings>

  <settings pass="specialize">

    <component name="Microsoft-Windows-Shell-Setup"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <ComputerName>YOURCOMPUTERNAME</ComputerName>
    </component>
{RDP_COMPONENTS}
    <component name="Microsoft-Windows-Deployment"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <RunSynchronous>
{SPECIALIZE_COMMANDS}
      </RunSynchronous>
    </component>
  </settings>

  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-International-Core"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <InputLocale>LOCALE_VALUE</InputLocale>
      <SystemLocale>LOCALE_VALUE</SystemLocale>
      <UILanguage>LOCALE_VALUE</UILanguage>
      <UserLocale>LOCALE_VALUE</UserLocale>
    </component>

    <component name="Microsoft-Windows-Shell-Setup"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">

      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideLocalAccountScreen>true</HideLocalAccountScreen>
        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <ProtectYourPC>3</ProtectYourPC>
      </OOBE>

      <UserAccounts>
        <LocalAccounts>
          <LocalAccount wcm:action="add">
            <Name>YOURUSER</Name>
            <Group>Administrators</Group>
            <Password>
              <Value>YOURPASSWORD</Value>
              <PlainText>true</PlainText>
            </Password>
          </LocalAccount>
        </LocalAccounts>
      </UserAccounts>

      <AutoLogon>
        <Enabled>true</Enabled>
        <Username>YOURUSER</Username>
        <Password>
          <Value>YOURPASSWORD</Value>
          <PlainText>true</PlainText>
        </Password>
        <LogonCount>1</LogonCount>
      </AutoLogon>

      <TimeZone>TIMEZONE_VALUE</TimeZone>

      <FirstLogonCommands>
{FIRSTLOGON_COMMANDS}
      </FirstLogonCommands>
    </component>
  </settings>
</unattend>
"""


def _render(template: str, config: Config) -> str:
    version = config.win_version
    params = VERSION_PARAMS[version]
    replacements = {
        "{USERDATA}": user_data_for(version),
        "{RDP_COMPONENTS}": _rdp_components(config),
        "{SPECIALIZE_COMMANDS}": _render_specialize_commands(config),
        "{FIRSTLOGON_COMMANDS}": _render_firstlogon_commands(config),
        "VIRTIO_DRIVER_DIR": params.virtio_driver_dir,
        "{IMAGE_INDEX}": str(params.image_index),
        "LOCALE_VALUE": config.settings.locale,
        "TIMEZONE_VALUE": config.settings.timezone,
        "YOURCOMPUTERNAME": xml_escape(config.computer_name),
        "YOURPASSWORD": xml_escape(config.user_password),
        "YOURUSER": xml_escape(config.user_name),
    }
    pattern = re.compile(
        "|".join(re.escape(k) for k in sorted(replacements, key=len, reverse=True))
    )
    return pattern.sub(lambda m: replacements[m.group()], template)


def generate_autounattend(config: Config) -> str:
    return _render(_TEMPLATE, config)
