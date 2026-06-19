# virt-install-windev

Create a fully-unattended Windows 10 or 11 development VM on Linux using libvirt/QEMU/KVM.

One command, no clicking — the script handles partitioning, driver injection, account creation, and post-install configuration automatically. The Windows version is auto-detected from the ISO filename.

## Quick start

```bash
# Install dependencies (Fedora)
sudo dnf install virt-install qemu-img genisoimage swtpm virtio-win edk2-ovmf

# Create a VM (downloads the evaluation ISO automatically)
./virt-install-windev.sh
```

Or with an existing ISO (version auto-detected from filename):

```bash
./virt-install-windev.sh --iso ~/Downloads/Win11_24H2_English_x64.iso
./virt-install-windev.sh --iso ~/Downloads/Win10_22H2_English_x64.iso
```

The script waits for installation to complete (~30-60 minutes), showing real-time progress via serial port logging. When it finishes, the VM is shut down and ready to use.

## Prerequisites

| Package | Purpose |
|---------|---------|
| `virt-install` | Creates and launches VMs |
| `qemu-img` | Creates virtual disk images |
| `genisoimage` | Builds the answer-file ISO |
| `swtpm` | Software TPM 2.0 emulator (required by Win11, optional for Win10) |
| `virtio-win` | Paravirtualized drivers for fast disk/network I/O |
| `edk2-ovmf` | UEFI firmware for VMs |

## Usage

```
./virt-install-windev.sh [OPTIONS]

Options:
  --name NAME         VM name (default: windev)
  --iso PATH          Use an existing Windows ISO instead of downloading
  --win10             Use Windows 10 (auto-detected from ISO filename if omitted)
  --insider           Download Insider Preview ISO via browser automation
  --edition MATCH     Insider edition substring (default: 'Release Preview')
  --lang MATCH        Insider language substring (default: 'English (United States)')
  --vcpus N           Number of vCPUs (default: 4)
  --ram MB            RAM in MiB (default: 8192)
  --disk GB           Disk size in GiB (default: 64)
  --user NAME         Local admin username (default: Developer)
  --password PASS     Local admin password (default: password)
  --no-wait           Don't wait for installation to finish
  --force             Destroy and replace an existing VM with the same name
```

## What gets configured

The unattended install sets up a dev-friendly Windows environment:

- **VirtIO drivers** — fast paravirtualized disk, network, display, and memory balloon
- **VirtIO guest tools** — SPICE agent (clipboard sharing, resolution), QEMU guest agent
- **OpenSSH Server** — enabled and started automatically on port 22
- **RDP** — enabled for remote desktop access
- **WSL** — Windows Subsystem for Linux enabled (install a distro after first boot)
- **No Defender** — all Windows Defender services disabled
- **No bloatware** — pre-installed apps removed (keeps Calculator, Terminal, Store, Notepad)
- **No UAC prompts** — User Account Control set to "Never notify"
- **No hibernation** — disabled (pointless in a VM)
- **Telemetry minimal** — set to Security level only
- **Updates notify-only** — no surprise downloads or reboots
- **File Explorer** — shows file extensions, hidden files, opens to "This PC"
- **Dark mode** — system-wide dark theme
- **Developer Mode** — symlinks without elevation, sideloading enabled
- **Long paths** — removes the 260-character path limit (needed for git/node_modules)
- **No lock screen** — skips straight to login
- **No screen timeout** — monitor and sleep timers disabled
- **No animations** — snappier UI in a VM
- **No Recall/AI** — Windows AI data analysis disabled (Win11 24H2+)
- **No Widgets/Copilot** — disabled
- **RDP USB redirection** — RemoteFX USB policy enabled (functional on Win10, broken on Win11 24H2+)

## Connecting to the VM

```bash
# Start the VM
virsh start windev

# Get the IP address
virsh domifaddr windev --source agent
```

**SSH:**
```bash
ssh Developer@<IP>
```

**RDP:**
```bash
xfreerdp /v:<IP> /u:Developer /p:password /dynamic-resolution
```

**SPICE (graphical console):**
```bash
virt-viewer windev
```

## Snapshots & cloning

**Save a clean baseline:**
```bash
virsh snapshot-create-as windev clean-install --description "Fresh install"
```

**Revert to it later:**
```bash
virsh snapshot-revert windev clean-install
```

**List snapshots:**
```bash
virsh snapshot-list windev
```

**Clone the VM** (full disk copy — VM must be shut down):
```bash
virsh shutdown windev
virt-clone --original windev --name windev2 --auto-clone
virsh start windev2
```

## VM management

```bash
virsh start windev              # start
virsh shutdown windev            # graceful shutdown
virsh destroy windev             # force stop
virsh undefine windev --nvram --tpm  # delete completely
```

## How it works

The script generates an `autounattend.xml` answer file and packages it into an ISO alongside a PowerShell setup script. This ISO is attached as a virtual CD-ROM. Windows automatically finds and processes the answer file during boot.

Installation proceeds through three passes:

1. **windowsPE** — partitions the disk (GPT/UEFI), loads VirtIO drivers, bypasses hardware checks
2. **specialize** — configures registry settings (Defender, UAC, telemetry, updates), runs `setup.ps1` for SSH, WSL, and Explorer defaults
3. **oobeSystem** — skips all OOBE screens, creates a local admin account, installs VirtIO guest tools, removes bloatware, shuts down

The script monitors installation progress via serial port (COM1) logging and handles intermediate reboots automatically.

## Troubleshooting

**Watch installation in real time:**
```bash
# Serial log (text)
tail -F ~/.cache/virt-install-windev/windev-install.log

# Graphical console
virt-viewer windev
```

**Full serial log** (across all reboots):
```
~/.cache/virt-install-windev/windev-install.log.full
```

**Installation stuck at OOBE screens:** Windows 11 24H2+ uses a new "ConX" OOBE engine. The script handles this by setting locale in the oobeSystem pass (automatically skipped for Win10). Insider Preview builds sometimes change behavior — check `virt-viewer` to see what's on screen.

**VM won't boot from CD:** The script sends Enter keys at the right time to trigger "Press any key to boot from CD." If OVMF times out, try running the script again — timing depends on host CPU speed and TPM initialization.

**OpenSSH not working (Win11):** `Add-WindowsCapability` sometimes fails if Windows Update service isn't ready. Connect via RDP and run:
```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service sshd -StartupType Automatic
Start-Service sshd
```

**OpenSSH not working (Win10):** The built-in OpenSSH capability on Win10 22H2 ships a broken `sshd.exe`. The script downloads Win32-OpenSSH from GitHub instead, which requires internet during first boot. If it fails, connect via RDP and install manually:
```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$tag = (Invoke-RestMethod https://api.github.com/repos/PowerShell/Win32-OpenSSH/releases/latest).tag_name
Invoke-WebRequest "https://github.com/PowerShell/Win32-OpenSSH/releases/download/$tag/OpenSSH-Win64.zip" -OutFile $env:TEMP\OpenSSH.zip
Expand-Archive $env:TEMP\OpenSSH.zip 'C:\Program Files' -Force
& 'C:\Program Files\OpenSSH-Win64\install-sshd.ps1'
& 'C:\Program Files\OpenSSH-Win64\ssh-keygen.exe' -A
Set-Service sshd -StartupType Automatic
Start-Service sshd
```
