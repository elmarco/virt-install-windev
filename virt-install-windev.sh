#!/bin/bash
#
# virt-install-windev.sh — Create a fully-unattended Windows 10/11/Server 2016/2022 development VM
#
# This script automates the entire process of creating a Windows 10 or 11 VM using
# libvirt/QEMU/KVM. It downloads the ISO, generates an "answer file"
# (autounattend.xml) that tells the Windows installer how to proceed without
# any human interaction, and launches the VM.
#
# HOW WINDOWS UNATTENDED INSTALLATION WORKS
# ==========================================
# Windows uses an XML file called "autounattend.xml" to automate installation.
# The installer looks for this file on removable media (CD/DVD/USB) during
# boot. The file is organized into "passes" — stages of the install process:
#
#   Pass 1 - windowsPE:   Runs in the installer environment (WinPE) before
#                         Windows is installed. This is where we partition the
#                         disk, load drivers, and bypass hardware checks.
#
#   Pass 4 - specialize:  Runs after Windows is copied to disk, on the first
#                         boot into the installed OS. Used for machine-specific
#                         settings like computer name, network config, and
#                         registry tweaks. Runs as SYSTEM (no user logged in).
#
#   Pass 7 - oobeSystem:  Runs during the "Out-of-Box Experience" — the screens
#                         you normally see asking about region, Microsoft account,
#                         privacy settings, etc. We skip all of these and create
#                         a local admin account instead.
#
# HOW LIBVIRT / QEMU / KVM FIT TOGETHER
# ======================================
# KVM is a Linux kernel module that turns your CPU into a hypervisor.
# QEMU is the userspace program that emulates the VM hardware (disk, network,
# display, etc.) and uses KVM for near-native CPU performance.
# libvirt is a management layer on top of QEMU — it provides the virsh CLI,
# virt-install, virt-viewer, and handles VM lifecycle, storage, and networking.
#
# This script uses "qemu:///session" (the default for non-root users), which
# runs QEMU as your regular user without needing root privileges.
#
# VIRTIO DRIVERS
# ==============
# By default, QEMU emulates legacy hardware (IDE disks, e1000 NICs) that
# Windows already has drivers for. But this emulation is slow. "virtio" is a
# paravirtualized I/O standard — the guest OS knows it's in a VM and talks
# directly to the hypervisor, which is much faster. The catch: Windows doesn't
# ship with virtio drivers, so we inject them from the virtio-win ISO during
# the windowsPE pass. Without these drivers, Windows can't even see the disk.

# -e: exit immediately if any command fails
# -u: treat unset variables as errors
# -o pipefail: a pipeline fails if ANY command in it fails, not just the last
set -euo pipefail

# --- Defaults ---
VM_NAME="windev"
VCPUS=4
RAM_MB=8192
DISK_GB=64
EVAL_URL="https://go.microsoft.com/fwlink/?linkid=2334167&clcid=0x409&culture=en-us&country=us"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/virt-install-windev"

# virtio-win: Fedora/RHEL package containing Windows virtio drivers
VIRTIO_ISO="/usr/share/virtio-win/virtio-win.iso"
# OVMF: open-source UEFI firmware for VMs (replaces legacy BIOS)
OVMF_CODE="/usr/share/OVMF/OVMF_CODE.secboot.fd"
OVMF_VARS="/usr/share/OVMF/OVMF_VARS.fd"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="Developer"
USER_PASSWORD="password"
COMPUTER_NAME="WinDev"
NO_WAIT=0
FORCE=0
ISO_PATH=""
OPENSSH_ZIP=""
INSIDER=0
WIN_VERSION=""

usage() {
    cat <<'EOF'
Usage: virt-install-windev.sh [OPTIONS]

Download a Windows ISO and create a fully-unattended libvirt VM with
virtio drivers, UEFI, and TPM 2.0.

By default, downloads the Windows 11 Enterprise Evaluation ISO. The Windows
version is auto-detected from the ISO filename, or can be set with --win10,
--server2016, or --server2022.

Options:
  --name NAME         VM name (default: windev)
  --iso PATH          Use an existing Windows ISO instead of downloading
  --win10             Use Windows 10 (auto-detected from ISO filename if omitted)
  --server2016        Use Windows Server 2016 (auto-detected from ISO filename if omitted)
  --server2022        Use Windows Server 2022 (auto-detected from ISO filename if omitted)
  --insider           Download Insider Preview ISO via browser automation
  --edition MATCH     Insider edition substring (default: 'Release Preview')
  --lang MATCH        Insider language substring (default: 'English (United States)')
  --vcpus N           Number of vCPUs (default: 4)
  --ram MB            RAM in MiB (default: 8192)
  --disk GB           Disk size in GiB (default: 64)
  --user NAME         Local admin username (default: Developer)
  --password PASS     Local admin password (default: password)
  --no-wait           Don't wait for installation to finish
  --force             Destroy and remove existing VM with the same name
  -h, --help          Show this help
EOF
}

INSIDER_EDITION="Release Preview"
INSIDER_LANG="English (United States)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name)     VM_NAME="$2"; shift 2 ;;
        --iso)      ISO_PATH="$2"; shift 2 ;;
        --win10)    WIN_VERSION=10; shift ;;
        --server2016) WIN_VERSION=server2016; shift ;;
        --server2022) WIN_VERSION=server2022; shift ;;
        --insider)  INSIDER=1; shift ;;
        --edition)  INSIDER_EDITION="$2"; shift 2 ;;
        --lang)     INSIDER_LANG="$2"; shift 2 ;;
        --vcpus)    VCPUS="$2"; shift 2 ;;
        --ram)      RAM_MB="$2"; shift 2 ;;
        --disk)     DISK_GB="$2"; shift 2 ;;
        --user)     USER_NAME="$2"; shift 2 ;;
        --password) USER_PASSWORD="$2"; shift 2 ;;
        --no-wait)  NO_WAIT=1; shift ;;
        --force)    FORCE=1; shift ;;
        -h|--help)  usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

# --- Dependency checks ---
# virt-install: creates VMs  |  virsh: manages VMs  |  qemu-img: creates disk images
# genisoimage: creates ISO images  |  curl: downloads files  |  swtpm: software TPM emulator
missing=()
for cmd in virt-install virsh qemu-img genisoimage curl swtpm; do
    command -v "$cmd" &>/dev/null || missing+=("$cmd")
done
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Error: missing required commands: ${missing[*]}" >&2
    exit 1
fi
if [[ ! -f "$VIRTIO_ISO" ]]; then
    echo "Error: virtio-win ISO not found at $VIRTIO_ISO" >&2
    echo "Install it with: sudo dnf install virtio-win" >&2
    exit 1
fi
if [[ ! -f "$OVMF_CODE" ]]; then
    echo "Error: OVMF firmware not found at $OVMF_CODE" >&2
    echo "Install it with: sudo dnf install edk2-ovmf" >&2
    exit 1
fi

# --- Check for existing VM ---
if virsh dominfo "$VM_NAME" &>/dev/null; then
    if [[ "$FORCE" -eq 1 ]]; then
        echo "Removing existing VM '$VM_NAME'..."
        virsh destroy "$VM_NAME" 2>/dev/null || true
        virsh undefine "$VM_NAME" --nvram --tpm 2>/dev/null || true
        rm -f "$CACHE_DIR/${VM_NAME}.qcow2"
    else
        echo "Error: VM '$VM_NAME' already exists." >&2
        echo "Remove it with: virsh destroy $VM_NAME; virsh undefine $VM_NAME --nvram --tpm" >&2
        echo "Or use --force to replace it." >&2
        exit 1
    fi
fi

# --- ISO download ---
mkdir -p "$CACHE_DIR"

if [[ -n "$ISO_PATH" ]]; then
    WIN_ISO="$ISO_PATH"
    if [[ ! -f "$WIN_ISO" ]]; then
        echo "Error: ISO not found at $WIN_ISO" >&2
        exit 1
    fi
    echo "Using provided ISO: $WIN_ISO"
elif [[ "$INSIDER" -eq 1 ]]; then
    WIN_ISO="$CACHE_DIR/win11-insider.iso"
    if [[ -f "$WIN_ISO" ]]; then
        echo "Insider ISO already cached: $WIN_ISO"
        echo "Delete it to re-download: rm $WIN_ISO"
    else
        echo "Launching browser to download Windows Insider Preview ISO..."
        echo "You will need to sign in with your Microsoft (Insider) account."
        DOWNLOAD_URL=$(python3 "$SCRIPT_DIR/download-insider-iso.py" \
            --edition "$INSIDER_EDITION" --lang "$INSIDER_LANG") || {
            echo "Error: failed to get Insider Preview download URL." >&2
            echo "You can download manually from:" >&2
            echo "  https://www.microsoft.com/en-us/software-download/windowsinsiderpreviewiso" >&2
            echo "Then re-run with: $0 --iso /path/to/downloaded.iso" >&2
            exit 1
        }
        echo "Downloading: $DOWNLOAD_URL"
        echo "This is ~6 GB and may take a while."
        if ! curl -L -o "${WIN_ISO}.part" --progress-bar "$DOWNLOAD_URL"; then
            rm -f "${WIN_ISO}.part"
            echo "Error: download failed." >&2
            exit 1
        fi
        mv "${WIN_ISO}.part" "$WIN_ISO"
        echo "ISO saved to: $WIN_ISO"
    fi
else
    if [[ "$WIN_VERSION" == "server2016" ]]; then
        echo "Error: Windows Server 2016 evaluation ISOs require manual download." >&2
        echo "Download from: https://www.microsoft.com/en-us/evalcenter/evaluate-windows-server-2016" >&2
        echo "Then re-run with: $0 --server2016 --iso /path/to/server2016.iso" >&2
        exit 1
    fi
    if [[ "$WIN_VERSION" == "server2022" ]]; then
        echo "Error: Windows Server 2022 evaluation ISOs require manual download." >&2
        echo "Download from: https://www.microsoft.com/en-us/evalcenter/evaluate-windows-server-2022" >&2
        echo "Then re-run with: $0 --server2022 --iso /path/to/SERVER_EVAL.iso" >&2
        exit 1
    fi
    if [[ "$WIN_VERSION" == "10" ]]; then
        echo "Error: Microsoft no longer offers Windows 10 evaluation ISOs for download." >&2
        echo "Provide a Windows 10 ISO with: $0 --iso /path/to/Win10.iso" >&2
        exit 1
    fi
    WIN_ISO="$CACHE_DIR/win11-enterprise-eval.iso"
    if [[ -f "$WIN_ISO" ]]; then
        echo "ISO already cached: $WIN_ISO"
    else
        echo "Downloading Windows 11 Enterprise Evaluation ISO..."
        echo "This is ~6 GB and may take a while."
        if ! curl -L -o "${WIN_ISO}.part" --progress-bar "$EVAL_URL"; then
            rm -f "${WIN_ISO}.part"
            echo "" >&2
            echo "Error: download failed." >&2
            echo "Download manually from:" >&2
            echo "  https://www.microsoft.com/en-us/evalcenter/download-windows-11-enterprise" >&2
            echo "Then re-run with: $0 --iso /path/to/downloaded.iso" >&2
            exit 1
        fi
        mv "${WIN_ISO}.part" "$WIN_ISO"
        echo "ISO saved to: $WIN_ISO"
    fi
fi

# --- Detect Windows version from ISO filename ---
# Matches: Win10, Windows_10, windows.10, Win_Pro_10, Win11, etc.
if [[ -z "$WIN_VERSION" ]]; then
    iso_name="$(basename "$WIN_ISO")"
    re10='[Ww]in(dows)?([-_ .][A-Za-z]+)*[-_ .]*10'
    re11='[Ww]in(dows)?([-_ .][A-Za-z]+)*[-_ .]*11'
    resvr2016='[Ss]erver.*2016'
    resvr2022='([Ss]erver.*2022|SERVER_EVAL)'
    if [[ "$iso_name" =~ $resvr2016 ]]; then
        WIN_VERSION=server2016
    elif [[ "$iso_name" =~ $resvr2022 ]]; then
        WIN_VERSION=server2022
    elif [[ "$iso_name" =~ $re10 ]]; then
        WIN_VERSION=10
    elif [[ "$iso_name" =~ $re11 ]]; then
        WIN_VERSION=11
    fi
fi
WIN_VERSION="${WIN_VERSION:-11}"

case "$WIN_VERSION" in
    10)          VIRTIO_DRIVER_DIR="w10";  OS_VARIANT="win10";   IMAGE_INDEX=1 ;;
    server2016)  VIRTIO_DRIVER_DIR="2k16"; OS_VARIANT="win2k16"; IMAGE_INDEX=2 ;;
    server2022)  VIRTIO_DRIVER_DIR="2k22"; OS_VARIANT="win2k22"; IMAGE_INDEX=2 ;;
    *)           VIRTIO_DRIVER_DIR="w11";  OS_VARIANT="win11";   IMAGE_INDEX=1 ;;
esac
echo "Windows version: $WIN_VERSION (virtio drivers: $VIRTIO_DRIVER_DIR)"

# --- Generate autounattend.xml ---
# We build the XML in a temp directory, then package it into an ISO that gets
# attached to the VM as a virtual CD-ROM. Windows searches all removable media
# for "autounattend.xml" at boot — no need to modify the Windows ISO itself.
WORK_DIR=$(mktemp -d "${CACHE_DIR}/windev-setup.XXXXXX")
TAIL_PID=""
trap 'kill "$TAIL_PID" 2>/dev/null || true; rm -rf "$WORK_DIR"' EXIT

cat > "$WORK_DIR/autounattend.xml" <<'XMLEOF'
<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">

  <!--
    ================================================================
    PASS 1: windowsPE
    ================================================================
    This runs inside the Windows installer environment (WinPE) before
    anything is written to disk. We use it to:
      1. Set the installer language (so it doesn't ask)
      2. Load virtio drivers (so Windows can see our fast virtual disk)
      3. Bypass hardware checks (TPM, SecureBoot, RAM)
      4. Partition the disk and select the Windows edition to install
  -->
  <settings pass="windowsPE">

    <!-- Tell the installer to use English without asking -->
    <component name="Microsoft-Windows-International-Core-WinPE"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <SetupUILanguage>
        <UILanguage>en-US</UILanguage>
      </SetupUILanguage>
      <InputLocale>en-US</InputLocale>
      <SystemLocale>en-US</SystemLocale>
      <UILanguage>en-US</UILanguage>
      <UserLocale>en-US</UserLocale>
    </component>

    <!--
      Load virtio drivers from the virtio-win ISO (attached as 2nd CD-ROM,
      typically drive E: in WinPE). Without these, the Windows installer
      can't see our virtio disk or network adapter.

      Each driver folder corresponds to a virtual device:
        NetKVM   = virtio network adapter (fast paravirtualized NIC)
        viostor  = virtio block storage (fast paravirtualized disk)
        qxldod   = QXL display driver (better resolution/performance)
        vioscsi  = virtio SCSI controller
        Balloon  = memory ballooning (dynamic RAM adjustment)
        vioserial= virtio serial port (host-guest communication)
        viorng   = virtio random number generator (entropy source)
    -->
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

    <!--
      Microsoft-Windows-Setup: the main installer component.
      We use it to:
        - Bypass Windows 11 hardware checks (TPM, SecureBoot, RAM)
        - Partition the virtual disk (GPT: EFI + MSR + Windows)
        - Select which Windows edition to install (by image index)
        - Accept the EULA and provide a product key
    -->
    <component name="Microsoft-Windows-Setup"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">

      <!--
        BYPASS HARDWARE CHECKS
        Windows 11 requires TPM 2.0, Secure Boot, and 4 GB RAM.
        Even though our VM has all of these, we bypass the checks
        anyway — it avoids edge cases and is what Schneegans does.
        The "LabConfig" key is Microsoft's official lab/test bypass.
      -->
      <!-- NOTE: No serial logging here — WinPE may not have COM1 drivers
           loaded, and a failed RunSynchronous command aborts Setup entirely. -->
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

      <!--
        DISK PARTITIONING (GPT layout for UEFI boot)
        ┌─────────────────────────────────────────────┐
        │ Partition 1: EFI System Partition (260 MB)  │
        │   Format: FAT32  — holds the UEFI bootloader│
        │ Partition 2: MSR (16 MB)                    │
        │   Microsoft Reserved — used internally      │
        │ Partition 3: Windows (rest of disk)          │
        │   Format: NTFS — the actual OS partition    │
        └─────────────────────────────────────────────┘
        This is the standard GPT layout for UEFI Windows.
        No recovery partition — in a VM, you just recreate it.
      -->
      <DiskConfiguration>
        <Disk wcm:action="add">
          <DiskID>0</DiskID>
          <WillWipeDisk>true</WillWipeDisk>
          <CreatePartitions>
            <!-- EFI System Partition -->
            <CreatePartition wcm:action="add">
              <Order>1</Order>
              <Size>260</Size>
              <Type>EFI</Type>
            </CreatePartition>
            <!-- MSR -->
            <CreatePartition wcm:action="add">
              <Order>2</Order>
              <Size>16</Size>
              <Type>MSR</Type>
            </CreatePartition>
            <!-- Windows -->
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

      <!--
        IMAGE SELECTION
        A Windows ISO can contain multiple editions (Home, Pro, Enterprise).
        InstallFrom picks which one by image index (1 = first edition).
        InstallTo tells it where to put it (disk 0, partition 3 = NTFS).

        IMPORTANT: Windows 11 24H2+ requires BOTH <InstallFrom> AND
        <InstallTo>. Older answer files with only <InstallTo> will fail
        with a generic "installation has failed" error. This was a breaking
        change in the "ConX" setup engine introduced in 24H2.
      -->
      <ImageInstall>
        <OSImage>
          <InstallFrom>
            <MetaData wcm:action="add">
              <Key>/IMAGE/INDEX</Key>
              <Value>IMAGE_INDEX</Value>
            </MetaData>
          </InstallFrom>
          <InstallTo>
            <DiskID>0</DiskID>
            <PartitionID>3</PartitionID>
          </InstallTo>
        </OSImage>
      </ImageInstall>

      <!-- BEGIN_WIN11_ONLY: PRODUCT KEY
        GVLK for Windows Enterprise — tells the Win11 installer which
        edition to install. Not needed for Win10 (image index suffices)
        and can cause the edition-selection screen on non-VL Win10 ISOs. -->
      <UserData>
        <AcceptEula>true</AcceptEula>
        <ProductKey>
          <Key>NPPR9-FWDCX-D2C8J-H872K-2YT43</Key>
          <WillShowUI>Never</WillShowUI>
        </ProductKey>
      </UserData>
      <!-- END_WIN11_ONLY -->
      <!-- BEGIN_WIN10_ONLY: Accept EULA without product key -->
      <UserData>
        <AcceptEula>true</AcceptEula>
      </UserData>
      <!-- END_WIN10_ONLY -->
      <!-- BEGIN_SERVER2016_ONLY: PRODUCT KEY
        GVLK for Windows Server 2016 Standard. -->
      <UserData>
        <AcceptEula>true</AcceptEula>
        <ProductKey>
          <Key>WC2BQ-8NRM3-FDDYY-2BFGV-KHKQY</Key>
          <WillShowUI>Never</WillShowUI>
        </ProductKey>
      </UserData>
      <!-- END_SERVER2016_ONLY -->
      <!-- BEGIN_SERVER2022_ONLY: PRODUCT KEY
        GVLK for Windows Server 2022 Standard. -->
      <UserData>
        <AcceptEula>true</AcceptEula>
        <ProductKey>
          <Key>VDYBN-27WPP-V4HQT-9VMD4-VMK7H</Key>
          <WillShowUI>Never</WillShowUI>
        </ProductKey>
      </UserData>
      <!-- END_SERVER2022_ONLY -->
    </component>
  </settings>

  <!--
    ================================================================
    PASS 4: specialize
    ================================================================
    This runs on the FIRST BOOT into the installed OS, as SYSTEM,
    before any user account exists. It's the right place for:
      - Machine-specific settings (computer name)
      - Enabling services (RDP, firewall rules)
      - Registry tweaks that need HKLM access
      - Disabling Defender (must happen here — once OOBE finishes,
        Tamper Protection blocks changes to Defender services)

    All the "reg add" commands below modify the Windows registry.
    The registry is a hierarchical database where Windows stores
    configuration. Key paths work like filesystem paths:
      HKLM = HKEY_LOCAL_MACHINE (system-wide settings)
      HKU  = HKEY_USERS (per-user settings)
    Values have types: REG_DWORD = 32-bit integer, REG_SZ = string.
  -->
  <settings pass="specialize">

    <!-- Set the computer/hostname -->
    <component name="Microsoft-Windows-Shell-Setup"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
XMLEOF

# Inject the configurable computer name
cat >> "$WORK_DIR/autounattend.xml" <<XMLEOF
      <ComputerName>${COMPUTER_NAME}</ComputerName>
XMLEOF

cat >> "$WORK_DIR/autounattend.xml" <<'XMLEOF'
    </component>

    <!--
      ENABLE REMOTE DESKTOP (RDP)
      Two steps: (1) tell Terminal Services to accept connections,
      (2) open the firewall to allow inbound RDP traffic.
      After install, you can connect from your Linux host with:
        xfreerdp /v:<vm-ip> /u:Developer /p:password /dynamic-resolution
    -->
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

    <!--
      DEPLOYMENT — RunSynchronous commands
      These commands run sequentially during the specialize pass.
      Think of it as a batch script that Windows runs automatically.
      Each command gets an Order number for sequencing.

      WHY SPECIALIZE?
      This pass runs as SYSTEM before any user exists. It's the only
      window where Defender services can be disabled via registry —
      once OOBE finishes, Tamper Protection kicks in and blocks
      registry changes to security-related services.
    -->
    <component name="Microsoft-Windows-Deployment"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <RunSynchronous>

        <!-- Log progress to the serial port (COM1) so the host script
             can display real-time installation status. -->
        <RunSynchronousCommand wcm:action="add">
          <Order>1</Order>
          <Path>cmd /c "echo [SPECIALIZE] Configuring system settings &gt; COM1 || exit /b 0"</Path>
        </RunSynchronousCommand>

        <!--
          WORKAROUND: Windows 11 24H2+ "ConX" setup engine bug
          The new setup engine doesn't cache autounattend.xml from
          CD for the oobeSystem pass. So we manually copy it to
          C:\unattend.xml — Windows checks that path automatically.
          The "for %d in (D E F G H I)" loop tries each CD-ROM
          drive letter since we don't know which one it'll be.
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>2</Order>
          <Path>cmd /c for %d in (D E F G H I) do @if exist %d:\autounattend.xml copy /y %d:\autounattend.xml C:\unattend.xml</Path>
        </RunSynchronousCommand>

        <!--
          Skip the "network required" OOBE screen.
          BypassNRO = Bypass Network Requirement for OOBE.
          Without this, Windows insists on an internet connection
          and a Microsoft account during first-run setup.
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>3</Order>
          <Path>reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\OOBE" /v BypassNRO /t REG_DWORD /d 1 /f</Path>
        </RunSynchronousCommand>

        <!--
          UAC (User Account Control): set to "Never notify"
          EnableLUA=0 disables the elevation prompt entirely.
          In a dev VM, this avoids constant "Allow this app?" popups.
          (Don't do this on a production machine!)
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>4</Order>
          <Path>reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v EnableLUA /t REG_DWORD /d 0 /f</Path>
        </RunSynchronousCommand>

        <!--
          DISABLE VBS (Virtualization-Based Security)
          VBS uses the hypervisor to isolate security processes.
          In a VM, this means nested virtualization overhead for
          minimal benefit. Disabling it improves VM performance.
          HVCI (Hypervisor-enforced Code Integrity) is part of VBS.
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>5</Order>
          <Path>reg add "HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard" /v EnableVirtualizationBasedSecurity /t REG_DWORD /d 0 /f</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>6</Order>
          <Path>reg add "HKLM\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity" /v Enabled /t REG_DWORD /d 0 /f</Path>
        </RunSynchronousCommand>

        <RunSynchronousCommand wcm:action="add">
          <Order>7</Order>
          <Path>cmd /c "echo [SPECIALIZE] Disabling Defender services &gt; COM1 || exit /b 0"</Path>
        </RunSynchronousCommand>

        <!--
          DISABLE WINDOWS DEFENDER
          Setting a service's Start value to 4 means "Disabled".
          (0=Boot, 1=System, 2=Automatic, 3=Manual, 4=Disabled)
          We disable all Defender-related services:
            Sense     = Microsoft Defender Advanced Threat Protection
            WdBoot    = Defender boot-time driver
            WdFilter  = Defender mini-filter driver (real-time scanning)
            WdNisDrv  = Defender Network Inspection driver
            WdNisSvc  = Defender Network Inspection service
            WinDefend = Defender antimalware service
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>8</Order>
          <Path>reg add "HKLM\SYSTEM\CurrentControlSet\Services\Sense" /v Start /t REG_DWORD /d 4 /f</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>9</Order>
          <Path>reg add "HKLM\SYSTEM\CurrentControlSet\Services\WdBoot" /v Start /t REG_DWORD /d 4 /f</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>10</Order>
          <Path>reg add "HKLM\SYSTEM\CurrentControlSet\Services\WdFilter" /v Start /t REG_DWORD /d 4 /f</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>11</Order>
          <Path>reg add "HKLM\SYSTEM\CurrentControlSet\Services\WdNisDrv" /v Start /t REG_DWORD /d 4 /f</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>12</Order>
          <Path>reg add "HKLM\SYSTEM\CurrentControlSet\Services\WdNisSvc" /v Start /t REG_DWORD /d 4 /f</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>13</Order>
          <Path>reg add "HKLM\SYSTEM\CurrentControlSet\Services\WinDefend" /v Start /t REG_DWORD /d 4 /f</Path>
        </RunSynchronousCommand>

        <!--
          DISABLE HIBERNATION / FAST STARTUP
          Hibernation writes RAM to disk on shutdown — pointless in
          a VM (snapshots are better). Fast Startup is a hybrid
          hibernate that also wastes disk space in a VM context.
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>14</Order>
          <Path>reg add "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power" /v HiberbootEnabled /t REG_DWORD /d 0 /f</Path>
        </RunSynchronousCommand>

        <!--
          TELEMETRY: set to "Security" level (the minimum).
          AllowTelemetry=0 means only security-critical data is sent.
          (1=Basic, 2=Enhanced, 3=Full)
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>15</Order>
          <Path>reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection" /v AllowTelemetry /t REG_DWORD /d 0 /f</Path>
        </RunSynchronousCommand>

        <!--
          WINDOWS UPDATE: notify before downloading
          AUOptions=2 means "Notify for download and auto install".
          This prevents surprise reboots during development.
          NoAutoRebootWithLoggedOnUsers=1 adds another safety net.
          (1=Auto download+install, 2=Notify, 3=Auto download,
           4=Auto download + schedule install)
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>16</Order>
          <Path>reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" /v AUOptions /t REG_DWORD /d 2 /f</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>17</Order>
          <Path>reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" /v NoAutoRebootWithLoggedOnUsers /t REG_DWORD /d 1 /f</Path>
        </RunSynchronousCommand>

        <!--
          DISABLE CONSUMER FEATURES / WIDGETS
          ConsumerFeatures = pre-installed games, "suggested" apps.
          Dsh (AllowNewsAndInterests=0) = the Widgets panel on the
          taskbar that shows news, weather, stocks, etc.
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>18</Order>
          <Path>reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\CloudContent" /v DisableWindowsConsumerFeatures /t REG_DWORD /d 1 /f</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>19</Order>
          <Path>reg add "HKLM\SOFTWARE\Policies\Microsoft\Dsh" /v AllowNewsAndInterests /t REG_DWORD /d 0 /f</Path>
        </RunSynchronousCommand>

        <!--
          DEVELOPER MODE: allows sideloading apps, creating symlinks
          without elevation, and other dev-friendly behaviors.
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>20</Order>
          <Path>reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock" /v AllowDevelopmentWithoutDevLicense /t REG_DWORD /d 1 /f</Path>
        </RunSynchronousCommand>

        <!--
          LONG PATHS: Win32 APIs normally cap paths at 260 characters.
          Git repos with deep nesting and node_modules hit this constantly.
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>21</Order>
          <Path>reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 1 /f</Path>
        </RunSynchronousCommand>

        <!--
          DISABLE LOCK SCREEN: in a VM, the lock screen is just
          an obstacle. NoLockScreen skips straight to the login prompt.
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>22</Order>
          <Path>reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\Personalization" /v NoLockScreen /t REG_DWORD /d 1 /f</Path>
        </RunSynchronousCommand>

        <!--
          DISABLE RECALL / AI DATA ANALYSIS (Windows 11 24H2+).
          Recall takes periodic screenshots and indexes them with AI.
          Pointless in a dev VM and wastes disk/CPU.
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>23</Order>
          <Path>reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsAI" /v DisableAIDataAnalysis /t REG_DWORD /d 1 /f</Path>
        </RunSynchronousCommand>

        <!--
          DARK MODE (system-wide): sets the default theme for the
          taskbar, Start menu, and apps. Per-user defaults are also
          set in setup.ps1 via the DefaultUser hive.
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>24</Order>
          <Path>reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize" /v AppsUseLightTheme /t REG_DWORD /d 0 /f</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>25</Order>
          <Path>reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize" /v SystemUsesLightTheme /t REG_DWORD /d 0 /f</Path>
        </RunSynchronousCommand>

        <!--
          RDP USB REDIRECTION: allow RemoteFX USB device redirection.
          This lets xfreerdp's /usb:auto forward host USB devices into
          the VM over RDP. Three settings are needed:
            1. fDisablePNPRedir=0: server-side, allow PnP device redirection
               (defaults to blocked on Server 2016+)
            2. fUsbRedirectionEnable=1: client-side RemoteFX USB policy
            3. fUsbRedirectionUseDefaultList=1: use the default device list
        -->
        <RunSynchronousCommand wcm:action="add">
          <Order>26</Order>
          <Path>reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services" /v fDisablePNPRedir /t REG_DWORD /d 0 /f</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>27</Order>
          <Path>reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services" /v fUsbRedirectionEnable /t REG_DWORD /d 1 /f</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>28</Order>
          <Path>reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services" /v fUsbRedirectionUseDefaultList /t REG_DWORD /d 1 /f</Path>
        </RunSynchronousCommand>

        <!--
          COPY AND RUN POWERSHELL SETUP SCRIPT
          Some settings need PowerShell or DefaultUser hive
          manipulation, which is too complex for single reg commands.
          We copy setup.ps1 from the answer-file CD to disk, then run it.
        -->
        <!-- BEGIN_WIN10_ONLY: Copy OpenSSH ZIP from answer-file CD to disk -->
        <RunSynchronousCommand wcm:action="add">
          <Order>29</Order>
          <Path>cmd /c for %d in (D E F G H I) do @if exist %d:\OpenSSH-Win64.zip copy /y %d:\OpenSSH-Win64.zip C:\Windows\Temp\OpenSSH-Win64.zip</Path>
        </RunSynchronousCommand>
        <!-- END_WIN10_ONLY -->
        <!-- BEGIN_SERVER2016_ONLY: Copy OpenSSH ZIP from answer-file CD to disk -->
        <RunSynchronousCommand wcm:action="add">
          <Order>29</Order>
          <Path>cmd /c for %d in (D E F G H I) do @if exist %d:\OpenSSH-Win64.zip copy /y %d:\OpenSSH-Win64.zip C:\Windows\Temp\OpenSSH-Win64.zip</Path>
        </RunSynchronousCommand>
        <!-- END_SERVER2016_ONLY -->
        <RunSynchronousCommand wcm:action="add">
          <Order>30</Order>
          <Path>cmd /c "echo [SPECIALIZE] Running setup.ps1 &gt; COM1 || exit /b 0"</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>31</Order>
          <Path>cmd /c mkdir C:\Windows\Setup\Scripts 2>nul &amp; for %d in (D E F G H I) do @if exist %d:\setup.ps1 copy /y %d:\setup.ps1 C:\Windows\Setup\Scripts\setup.ps1</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>32</Order>
          <Path>powershell -ExecutionPolicy Bypass -File C:\Windows\Setup\Scripts\setup.ps1</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>33</Order>
          <Path>bcdedit /timeout 0</Path>
        </RunSynchronousCommand>
        <RunSynchronousCommand wcm:action="add">
          <Order>34</Order>
          <Path>cmd /c "echo [SPECIALIZE] Done, rebooting into OOBE &gt; COM1 || exit /b 0"</Path>
        </RunSynchronousCommand>
      </RunSynchronous>
    </component>
  </settings>

  <!--
    ================================================================
    PASS 7: oobeSystem
    ================================================================
    The Out-of-Box Experience (OOBE) is what you normally see when
    you first turn on a new Windows PC — region, keyboard, Microsoft
    account, privacy settings, etc. We skip ALL of it and instead:
      1. Create a local admin account (no Microsoft account needed)
      2. Auto-login once (to run FirstLogonCommands)
      3. Install VirtIO guest tools (clipboard sharing, etc.)
      4. Remove bloatware (pre-installed apps nobody asked for)
      5. Shut down (signaling to our script that install is done)
  -->
  <settings pass="oobeSystem">
    <!-- Pre-set locale so OOBE skips the region and keyboard screens.
         Required for both Win10 and Win11 — without this, the interactive
         region selector appears even when Shell-Setup OOBE is configured. -->
    <component name="Microsoft-Windows-International-Core"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <InputLocale>en-US</InputLocale>
      <SystemLocale>en-US</SystemLocale>
      <UILanguage>en-US</UILanguage>
      <UserLocale>en-US</UserLocale>
    </component>

    <component name="Microsoft-Windows-Shell-Setup"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">

      <!-- Hide every OOBE screen. ProtectYourPC=3 means "don't enable
           SmartScreen" — we just want to get to the desktop. -->
      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideLocalAccountScreen>true</HideLocalAccountScreen>
        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <ProtectYourPC>3</ProtectYourPC>
      </OOBE>

      <!-- Create a local admin account. The username and password
           are substituted by sed from the script's command-line options. -->
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

      <!--
        AUTO-LOGIN: log in as our user ONCE (LogonCount=1).
        This is needed so that FirstLogonCommands can run —
        they execute as the user, not as SYSTEM. After the
        one login, auto-logon is disabled automatically.
      -->
      <AutoLogon>
        <Enabled>true</Enabled>
        <Username>YOURUSER</Username>
        <Password>
          <Value>YOURPASSWORD</Value>
          <PlainText>true</PlainText>
        </Password>
        <LogonCount>1</LogonCount>
      </AutoLogon>

      <TimeZone>UTC</TimeZone>

      <!--
        FIRST-LOGIN COMMANDS
        These run as the logged-in user on the very first login.
        Order matters — we install drivers, clean up bloat, then shut down.
      -->
      <FirstLogonCommands>

        <SynchronousCommand wcm:action="add">
          <Order>1</Order>
          <CommandLine>cmd /c "echo [OOBE] First login, installing VirtIO guest tools &gt; COM1 || exit /b 0"</CommandLine>
        </SynchronousCommand>

        <!--
          Install VirtIO guest tools — provides:
            - SPICE agent (clipboard sharing, dynamic resolution)
            - QEMU guest agent (graceful shutdown from host)
            - Memory balloon service
          The installer is on the virtio-win CD; we search drive letters.
        -->
        <SynchronousCommand wcm:action="add">
          <Order>2</Order>
          <CommandLine>cmd /c for %d in (D E F G H I) do @if exist %d:\virtio-win-guest-tools.exe %d:\virtio-win-guest-tools.exe /install /passive /norestart</CommandLine>
        </SynchronousCommand>

        <!-- BEGIN_SERVER2016_ONLY: Install RDSH for RDP USB redirection.
             Must run at FirstLogon — Install-WindowsFeature silently fails
             during specialize because the servicing stack isn't ready. -->
        <SynchronousCommand wcm:action="add">
          <Order>3</Order>
          <CommandLine>cmd /c "echo [OOBE] Installing RDSH role for USB redirection &gt; COM1 || exit /b 0"</CommandLine>
        </SynchronousCommand>
        <SynchronousCommand wcm:action="add">
          <Order>4</Order>
          <CommandLine>powershell -Command "Install-WindowsFeature -Name RDS-RD-Server -ErrorAction Continue"</CommandLine>
        </SynchronousCommand>
        <!-- END_SERVER2016_ONLY -->
        <!-- BEGIN_SERVER2022_ONLY: Install RDSH for RDP USB redirection. -->
        <SynchronousCommand wcm:action="add">
          <Order>3</Order>
          <CommandLine>cmd /c "echo [OOBE] Installing RDSH role for USB redirection &gt; COM1 || exit /b 0"</CommandLine>
        </SynchronousCommand>
        <SynchronousCommand wcm:action="add">
          <Order>4</Order>
          <CommandLine>powershell -Command "Install-WindowsFeature -Name RDS-RD-Server -ErrorAction Continue"</CommandLine>
        </SynchronousCommand>
        <!-- END_SERVER2022_ONLY -->

        <!--
          Set network profile to Private. libvirt's NAT network defaults
          to "Public" which blocks inbound RDP/SSH. Must run at FirstLogon
          (not specialize) because the profile resets after OOBE reboot.
        -->
        <SynchronousCommand wcm:action="add">
          <Order>5</Order>
          <CommandLine>powershell -Command "Get-NetConnectionProfile | Set-NetConnectionProfile -NetworkCategory Private -ErrorAction SilentlyContinue; Enable-NetFirewallRule -DisplayGroup 'Remote Desktop' -ErrorAction SilentlyContinue"</CommandLine>
        </SynchronousCommand>

        <SynchronousCommand wcm:action="add">
          <Order>6</Order>
          <CommandLine>cmd /c "echo [OOBE] Installing OpenSSH Server &gt; COM1 || exit /b 0"</CommandLine>
        </SynchronousCommand>

        <!-- BEGIN_WIN11_ONLY: OpenSSH via built-in capability -->
        <SynchronousCommand wcm:action="add">
          <Order>7</Order>
          <CommandLine>powershell -Command "Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' -ErrorAction Continue; Set-Service -Name sshd -StartupType Automatic -ErrorAction Continue; Start-Service sshd -ErrorAction Continue; netsh advfirewall firewall add rule name='OpenSSH Server' dir=in action=allow protocol=TCP localport=22"</CommandLine>
        </SynchronousCommand>
        <!-- END_WIN11_ONLY -->
        <!-- BEGIN_WIN10_ONLY: OpenSSH installed from bundled ZIP during specialize (setup.ps1).
             Just start the service here since it was set to Automatic but hasn't booted yet. -->
        <SynchronousCommand wcm:action="add">
          <Order>7</Order>
          <CommandLine>powershell -Command "Start-Service sshd -ErrorAction Continue"</CommandLine>
        </SynchronousCommand>
        <!-- END_WIN10_ONLY -->
        <!-- BEGIN_SERVER2016_ONLY: OpenSSH installed from bundled ZIP during specialize (setup.ps1). -->
        <SynchronousCommand wcm:action="add">
          <Order>7</Order>
          <CommandLine>powershell -Command "Start-Service sshd -ErrorAction Continue"</CommandLine>
        </SynchronousCommand>
        <!-- END_SERVER2016_ONLY -->
        <!-- BEGIN_SERVER2022_ONLY: OpenSSH via built-in capability -->
        <SynchronousCommand wcm:action="add">
          <Order>7</Order>
          <CommandLine>powershell -Command "Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' -ErrorAction Continue; Set-Service -Name sshd -StartupType Automatic -ErrorAction Continue; Start-Service sshd -ErrorAction Continue; netsh advfirewall firewall add rule name='OpenSSH Server' dir=in action=allow protocol=TCP localport=22"</CommandLine>
        </SynchronousCommand>
        <!-- END_SERVER2022_ONLY -->

        <!--
          Deploy SSH authorized keys for passwordless login.
          Windows OpenSSH uses a special file for admin users instead
          of the usual ~/.ssh/authorized_keys. The ACL must restrict
          access to SYSTEM and Administrators only, or sshd rejects it.
        -->
        <SynchronousCommand wcm:action="add">
          <Order>8</Order>
          <CommandLine>powershell -Command "$f = 'C:\ProgramData\ssh\administrators_authorized_keys'; foreach ($d in 'D','E','F','G','H','I') { $p = \"${d}:\authorized_keys\"; if (Test-Path $p) { Copy-Item $p $f -Force; break } }; if (Test-Path $f) { icacls $f /inheritance:r /grant 'SYSTEM:(F)' /grant 'Administrators:(F)' }"</CommandLine>
        </SynchronousCommand>

        <SynchronousCommand wcm:action="add">
          <Order>9</Order>
          <CommandLine>cmd /c "echo [OOBE] Removing bloatware &gt; COM1 || exit /b 0"</CommandLine>
        </SynchronousCommand>

        <!--
          REMOVE BLOATWARE
          Remove all pre-installed Store apps EXCEPT the useful ones:
          Calculator, Photos, Terminal, Store, App Installer, Notepad.
          This gets rid of Clipchamp, LinkedIn, TikTok, Instagram,
          Xbox, Solitaire, etc. Using -AllUsers ensures new user
          profiles also won't get this junk.
        -->
        <SynchronousCommand wcm:action="add">
          <Order>10</Order>
          <CommandLine>powershell -Command "Get-AppxProvisionedPackage -Online | Where-Object { $_.DisplayName -notmatch 'Calculator|Photos|Terminal|Store|DesktopAppInstaller|WindowsNotepad' } | Remove-AppxProvisionedPackage -AllUsers -Online -ErrorAction Continue"</CommandLine>
        </SynchronousCommand>

        <!-- BEGIN_WIN11_ONLY: Install WinDbg via winget -->
        <SynchronousCommand wcm:action="add">
          <Order>11</Order>
          <CommandLine>cmd /c "echo [OOBE] Installing WinDbg &gt; COM1 || exit /b 0"</CommandLine>
        </SynchronousCommand>
        <SynchronousCommand wcm:action="add">
          <Order>12</Order>
          <CommandLine>cmd /c winget install Microsoft.WinDbg --accept-source-agreements --accept-package-agreements --silent</CommandLine>
        </SynchronousCommand>
        <!-- END_WIN11_ONLY -->

        <!--
          Write the completion marker to serial port BEFORE shutting down.
          The host script watches the serial log for this exact string
          to distinguish the final shutdown from intermediate shutdowns
          that happen during installation (e.g., after DISM features).
        -->
        <SynchronousCommand wcm:action="add">
          <Order>13</Order>
          <CommandLine>cmd /c "echo INSTALLATION_COMPLETE &gt; COM1 || exit /b 0"</CommandLine>
        </SynchronousCommand>

        <!--
          SHUT DOWN — signal to the host script that installation is done.
          Our bash script polls "virsh domstate" waiting for "shut off".
          30-second delay gives the previous commands time to finish.
        -->
        <SynchronousCommand wcm:action="add">
          <Order>14</Order>
          <CommandLine>shutdown /s /t 30 /c "Installation complete"</CommandLine>
        </SynchronousCommand>
      </FirstLogonCommands>
    </component>
  </settings>
</unattend>
XMLEOF

# Substitute configurable values into the XML template
sed -i "s/YOURUSER/${USER_NAME}/g; s/YOURPASSWORD/${USER_PASSWORD}/g; s/VIRTIO_DRIVER_DIR/${VIRTIO_DRIVER_DIR}/g; s/IMAGE_INDEX/${IMAGE_INDEX}/g" \
    "$WORK_DIR/autounattend.xml"

# Remove version-specific XML blocks (keep only the matching version)
for marker in WIN10 WIN11 SERVER2016 SERVER2022; do
    case "$WIN_VERSION" in
        10)          [[ "$marker" == "WIN10" ]] && continue ;;
        server2016)  [[ "$marker" == "SERVER2016" ]] && continue ;;
        server2022)  [[ "$marker" == "SERVER2022" ]] && continue ;;
        *)           [[ "$marker" == "WIN11" ]] && continue ;;
    esac
    sed -i "/<!-- BEGIN_${marker}_ONLY/,/<!-- END_${marker}_ONLY -->/d" "$WORK_DIR/autounattend.xml"
done

echo "Generated autounattend.xml (Windows $WIN_VERSION)"

# --- Generate setup.ps1 (runs during specialize pass) ---
#
# This PowerShell script handles settings that are too complex for
# single "reg add" commands in the XML. It runs during the specialize
# pass (as SYSTEM, before any user logs in).
#
# The trickiest part is the "DefaultUser" hive manipulation — this is
# how you set per-user registry defaults for ALL future user profiles.
# Instead of modifying each user's registry after they log in, you
# modify the template (NTUSER.DAT in C:\Users\Default) that Windows
# copies when creating new user profiles.
cat > "$WORK_DIR/setup.ps1" <<'PS1EOF'
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

# BEGIN_CLIENT_ONLY
# =====================================================================
# ENABLE WSL (Windows Subsystem for Linux)
# =====================================================================
# WSL lets you run Linux distributions inside Windows. Two features
# are needed:
#   1. Microsoft-Windows-Subsystem-Linux: the WSL core
#   2. VirtualMachinePlatform: required for WSL 2 (which runs a real
#      Linux kernel in a lightweight VM — much faster than WSL 1)
# After the VM boots, run "wsl --install" to pick a distro.
Log "[SETUP] Enabling WSL and VirtualMachinePlatform"
dism.exe /Online /Enable-Feature /FeatureName:Microsoft-Windows-Subsystem-Linux /All /NoRestart
dism.exe /Online /Enable-Feature /FeatureName:VirtualMachinePlatform /All /NoRestart
# END_CLIENT_ONLY
# BEGIN_SERVER_ONLY
Log "[SETUP] Suppressing Server Manager auto-launch"
reg.exe add "HKLM\SOFTWARE\Microsoft\ServerManager" /v DoNotOpenServerManagerAtLogon /t REG_DWORD /d 1 /f
# END_SERVER_ONLY

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
PS1EOF

# Remove version-specific blocks from setup.ps1
if [[ "$WIN_VERSION" == server* ]]; then
    sed -i '/# BEGIN_CLIENT_ONLY/,/# END_CLIENT_ONLY/d' "$WORK_DIR/setup.ps1"
else
    sed -i '/# BEGIN_SERVER_ONLY/,/# END_SERVER_ONLY/d' "$WORK_DIR/setup.ps1"
fi

echo "Generated setup.ps1"

# --- Collect SSH public keys ---
# Bundle the user's SSH public keys into the answer-file ISO so we can
# install them during FirstLogon. This enables passwordless SSH access.
SSH_KEY_FILE="$WORK_DIR/authorized_keys"
if ls ~/.ssh/id_*.pub &>/dev/null; then
    cat ~/.ssh/id_*.pub > "$SSH_KEY_FILE"
    echo "Bundled $(wc -l < "$SSH_KEY_FILE") SSH public key(s)"
fi

# --- Download Win32-OpenSSH (Win10 / Server 2016 only) ---
# These versions need a standalone OpenSSH binary — the built-in Windows
# capability is either broken (Win10 22H2) or absent (Server 2016).
# We download the ZIP on the host now and bundle it into the answer-file ISO
# so no internet access is needed during first boot.
if [[ "$WIN_VERSION" == "10" || "$WIN_VERSION" == "server2016" ]]; then
    OPENSSH_ZIP="$WORK_DIR/OpenSSH-Win64.zip"
    echo "Downloading Win32-OpenSSH..."
    curl -sL -o "$OPENSSH_ZIP" \
        "https://github.com/PowerShell/Win32-OpenSSH/releases/latest/download/OpenSSH-Win64.zip"
    if [[ ! -s "$OPENSSH_ZIP" ]]; then
        echo "Warning: failed to download Win32-OpenSSH, SSH may not work" >&2
    fi
fi

# --- Create answer-file ISO ---
# Package our autounattend.xml and setup.ps1 into a tiny ISO image
# that gets attached to the VM as a virtual CD-ROM. Windows scans all
# removable media for "autounattend.xml" at boot — this is cleaner
# than modifying the Windows ISO itself.
#   -J = Joliet extensions (Windows-friendly long filenames)
#   -r = Rock Ridge extensions (Unix permissions, but harmless here)
UNATTEND_ISO="$CACHE_DIR/${VM_NAME}-autounattend.iso"
ISO_FILES=("$WORK_DIR/autounattend.xml" "$WORK_DIR/setup.ps1")
[[ -f "$SSH_KEY_FILE" ]] && ISO_FILES+=("$SSH_KEY_FILE")
[[ -f "$OPENSSH_ZIP" ]] && ISO_FILES+=("$OPENSSH_ZIP")
genisoimage -quiet -o "$UNATTEND_ISO" -J -r "${ISO_FILES[@]}"
echo "Created answer-file ISO: $UNATTEND_ISO"

# --- Create disk image ---
# qcow2 = QEMU Copy-On-Write format. It's a sparse file — a "64G"
# image only takes a few KB on disk initially and grows as Windows
# writes data. This is much more efficient than a raw image.
DISK_PATH="$CACHE_DIR/${VM_NAME}.qcow2"
if [[ -f "$DISK_PATH" ]]; then
    if [[ "$FORCE" -eq 1 ]]; then
        rm -f "$DISK_PATH"
    else
        echo "Disk image already exists: $DISK_PATH"
        echo "Remove it first if you want a fresh install."
        exit 1
    fi
fi
qemu-img create -f qcow2 "$DISK_PATH" "${DISK_GB}G"
echo "Created disk image: $DISK_PATH (${DISK_GB} GiB)"

# --- Build virt-install command ---
#
# virt-install is a libvirt tool that creates and starts a new VM.
# Each flag configures a piece of virtual hardware. Here's what each does:
#
#   --name          Unique name for the VM (used by virsh, virt-viewer, etc.)
#   --memory        RAM in MiB (8192 = 8 GB — minimum for comfortable Win11)
#   --vcpus         Number of virtual CPU cores
#   --os-variant    Tells libvirt which Windows version this is (win10 or win11)
#                   so it picks good defaults (e.g., Hyper-V enlightenments)
#   --boot          Boot order: try CD-ROM first (for install), then hard disk.
#                   "uefi" tells libvirt to use OVMF firmware instead of legacy BIOS.
#   --tpm           Emulated TPM 2.0 — required by Windows 11, optional for Win10.
#   --disk (first)  The main virtual hard drive: our qcow2 image over virtio bus.
#                   cache=writeback improves write performance (safe for a dev VM).
#   --cdrom         The Windows ISO (first CD-ROM, typically drive D:)
#   --disk (sata)   Additional CD-ROMs: virtio-win drivers and our autounattend ISO.
#                   SATA bus because the virtio CD-ROM driver may not be loaded yet.
#   --network       bridge=virbr0 connects the VM to the host's NAT bridge.
#                   model=virtio uses the fast paravirtualized NIC.
#   --graphics      SPICE display protocol (better than VNC for Windows).
#                   listen=none = local socket only, no network listener.
#   --video         QXL video adapter (designed for SPICE, supports resizing)
#   --channel (1st) SPICE VMC channel (clipboard sharing, file transfer)
#   --channel (2nd) QEMU guest agent socket — lets virsh communicate with
#                   the guest (graceful shutdown, IP query, filesystem freeze)
#   --sound         Emulated sound card
#   --serial        Virtual serial port (COM1 in Windows), backed by a file on the
#                   host. Windows commands write progress to COM1, and we tail the
#                   file to show real-time installation status. Also used to detect
#                   the "INSTALLATION_COMPLETE" sentinel that signals we're done.
#   --controller    virtio-scsi controller (used by vioscsi driver)
#   --noautoconsole Don't open a viewer window — we'll handle boot keys via virsh.

# Serial port log — captures everything Windows writes to COM1.
# Used for real-time progress display and completion detection.
INSTALL_LOG="$CACHE_DIR/${VM_NAME}-install.log"
: > "$INSTALL_LOG"

echo ""
echo "Creating VM '$VM_NAME'..."
echo "  Windows: $WIN_VERSION"
echo "  vCPUs:   $VCPUS"
echo "  RAM:     $RAM_MB MiB"
echo "  Disk:    $DISK_GB GiB"
echo "  User:    $USER_NAME"
echo ""

virt-install \
    --name "$VM_NAME" \
    --memory "$RAM_MB" \
    --vcpus "$VCPUS" \
    --os-variant "$OS_VARIANT" \
    --boot uefi,cdrom,hd \
    --tpm backend.type=emulator,backend.version=2.0,model=tpm-crb \
    --disk path="$DISK_PATH",format=qcow2,bus=virtio,cache=writeback \
    --cdrom "$WIN_ISO" \
    --disk "$VIRTIO_ISO",device=cdrom,bus=sata \
    --disk "$UNATTEND_ISO",device=cdrom,bus=sata \
    --network bridge=virbr0,model=virtio \
    --graphics spice,listen=none \
    --video qxl \
    --channel spicevmc \
    --channel unix,target.type=virtio,target.name=org.qemu.guest_agent.0 \
    --sound default \
    --serial file,path="$INSTALL_LOG" \
    --controller type=scsi,model=virtio-scsi \
    --noautoconsole

# --- Press any key to boot from CD ---
# When booting from CD, the Windows EFI bootloader shows:
#   "Press any key to boot from CD or DVD..."
# If no key is pressed within ~5 seconds, it skips the CD and tries
# the hard drive (which is empty — so installation never starts).
#
# The tricky part: OVMF (the UEFI firmware) ALSO processes keyboard
# events during its own initialization. Keys sent too early get consumed
# by OVMF and never reach the Windows bootloader. So we watch the
# serial log for OVMF's "starting Boot" message — that means OVMF is
# about to transfer control to the CD boot code. THEN we send keys.
(
    # Wait for OVMF to hand off to the CD bootloader
    for _i in $(seq 30); do
        grep -q "starting Boot" "$INSTALL_LOG" 2>/dev/null && break
        sleep 1
    done
    sleep 2
    # Now send keys — they'll reach the Windows "Press any key" prompt
    for _i in $(seq 15); do
        virsh send-key "$VM_NAME" KEY_ENTER 2>/dev/null || break
        sleep 1
    done
) &

# --- Wait for installation to complete ---
#
# Windows installation involves multiple reboots and sometimes full
# shutdowns (e.g., after DISM enables WSL). libvirt treats reboots
# transparently (domain stays "running"), but a shutdown transitions
# the domain to "shut off".
#
# Our strategy:
#   1. Tail the serial log (COM1 output) to show real-time progress
#   2. When the VM shuts down, check the log for "INSTALLATION_COMPLETE"
#   3. If the marker is found → we're done
#   4. If not → restart the VM and keep waiting (intermediate shutdown)
#   5. Safety cap: give up after MAX_BOOTS restarts
#
# The INSTALLATION_COMPLETE marker is written to COM1 by the very last
# FirstLogonCommand, right before the final "shutdown /s".
if [[ "$NO_WAIT" -eq 0 ]]; then
    echo "Waiting for installation to complete (this may take 30-60 minutes)..."
    echo "Connect with: virt-viewer $VM_NAME"
    echo "Install log:  $INSTALL_LOG"
    echo ""

    # Show real-time installation progress from the serial port log.
    # tail -F (capital F) handles file truncation on VM restart.
    # sed -u is unbuffered so lines appear immediately.
    tail -F "$INSTALL_LOG" 2>/dev/null | sed -u 's/^/  [vm] /' &
    TAIL_PID=$!

    MAX_BOOTS=5
    boot_count=1
    while true; do
        state=$(virsh domstate "$VM_NAME" 2>/dev/null) || break
        if [[ "$state" == "shut off" ]]; then
            # Check if Windows wrote the completion marker before shutting down
            if grep -q "INSTALLATION_COMPLETE" "$INSTALL_LOG" 2>/dev/null; then
                break
            fi
            # No marker — this is an intermediate shutdown (e.g., after DISM).
            # Restart the VM so installation can continue.
            boot_count=$((boot_count + 1))
            if [[ $boot_count -gt $MAX_BOOTS ]]; then
                echo ""
                echo "Warning: VM shut down $((MAX_BOOTS)) times without completing."
                echo "Check the log: $INSTALL_LOG"
                echo "Start manually: virsh start $VM_NAME"
                break
            fi
            echo ""
            echo "  VM shut down mid-install (boot $boot_count/$MAX_BOOTS), restarting..."

            # Save current log before restart truncates it
            cat "$INSTALL_LOG" >> "$INSTALL_LOG.full" 2>/dev/null
            virsh start "$VM_NAME" >/dev/null
            sleep 10
        fi
        sleep 15
    done

    # Stop the log tail (wait returns non-zero for killed processes)
    kill "$TAIL_PID" 2>/dev/null
    wait "$TAIL_PID" 2>/dev/null || true
    # Save final log segment
    cat "$INSTALL_LOG" >> "$INSTALL_LOG.full" 2>/dev/null

    # Eject install media — no longer needed and avoids accidental
    # re-triggering of the Windows installer on next boot.
    for dev in $(virsh domblklist "$VM_NAME" 2>/dev/null | awk '/\.iso/{print $1}'); do
        virsh change-media "$VM_NAME" "$dev" --eject --config 2>/dev/null
    done
fi

# --- Success! Print connection instructions ---
# At this point, the VM is installed and shut off. Start it with
# "virsh start <name>" and connect with one of the methods below.
echo ""
echo "================================================================"
echo "  VM '$VM_NAME' created successfully!"
echo "================================================================"
echo ""
echo "Connect with:"
echo "  virt-viewer $VM_NAME"
echo "  (or: virsh domdisplay $VM_NAME)"
echo ""
echo "Get VM IP (requires guest agent):"
echo "  virsh domifaddr $VM_NAME --source agent"
echo ""
echo "SSH:"
echo "  ssh $USER_NAME@<IP>"
echo ""
echo "RDP:"
echo "  xfreerdp /v:<IP> /u:$USER_NAME /p:$USER_PASSWORD /dynamic-resolution"
if [[ "$WIN_VERSION" == server* ]]; then
    echo ""
    echo "RDP with USB redirection:"
    echo "  xfreerdp /v:<IP> /u:$USER_NAME /p:$USER_PASSWORD /dynamic-resolution /usb:auto"
fi
echo ""
echo "VM management:"
echo "  virsh start $VM_NAME"
echo "  virsh shutdown $VM_NAME"
echo "  virsh destroy $VM_NAME        # force stop"
echo "  virsh undefine $VM_NAME --nvram --tpm  # remove completely"
echo ""
echo "Install log:  $INSTALL_LOG.full"
echo ""
