#!/bin/bash
set -euo pipefail

# --- Defaults ---
VM_NAME="windev"
VCPUS=4
RAM_MB=8192
DISK_GB=64
EVAL_URL="https://go.microsoft.com/fwlink/?linkid=2334167&clcid=0x409&culture=en-us&country=us"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/virt-install-windev"
VIRTIO_ISO="/usr/share/virtio-win/virtio-win.iso"
OVMF_CODE="/usr/share/OVMF/OVMF_CODE.secboot.fd"
OVMF_VARS="/usr/share/OVMF/OVMF_VARS.fd"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="Developer"
USER_PASSWORD="password"
COMPUTER_NAME="WinDev"
NO_WAIT=0
ISO_PATH=""
INSIDER=0

usage() {
    cat <<'EOF'
Usage: virt-install-windev.sh [OPTIONS]

Download a Windows 11 ISO and create a fully-unattended libvirt VM with
virtio drivers, UEFI, and TPM 2.0.

By default, downloads the Enterprise Evaluation ISO (no sign-in required).
Use --insider to download the latest Insider Preview build instead (requires
signing into your Microsoft account in a browser window).

Options:
  --name NAME         VM name (default: windev)
  --iso PATH          Use an existing Windows ISO instead of downloading
  --insider           Download Insider Preview ISO via browser automation
  --edition MATCH     Insider edition substring (default: 'Release Preview')
  --lang MATCH        Insider language substring (default: 'English (United States)')
  --vcpus N           Number of vCPUs (default: 4)
  --ram MB            RAM in MiB (default: 8192)
  --disk GB           Disk size in GiB (default: 64)
  --user NAME         Local admin username (default: Developer)
  --password PASS     Local admin password (default: password)
  --no-wait           Don't wait for installation to finish
  -h, --help          Show this help
EOF
}

INSIDER_EDITION="Release Preview"
INSIDER_LANG="English (United States)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name)     VM_NAME="$2"; shift 2 ;;
        --iso)      ISO_PATH="$2"; shift 2 ;;
        --insider)  INSIDER=1; shift ;;
        --edition)  INSIDER_EDITION="$2"; shift 2 ;;
        --lang)     INSIDER_LANG="$2"; shift 2 ;;
        --vcpus)    VCPUS="$2"; shift 2 ;;
        --ram)      RAM_MB="$2"; shift 2 ;;
        --disk)     DISK_GB="$2"; shift 2 ;;
        --user)     USER_NAME="$2"; shift 2 ;;
        --password) USER_PASSWORD="$2"; shift 2 ;;
        --no-wait)  NO_WAIT=1; shift ;;
        -h|--help)  usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

# --- Dependency checks ---
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
    echo "Error: VM '$VM_NAME' already exists." >&2
    echo "Remove it with: virsh destroy $VM_NAME; virsh undefine $VM_NAME --nvram --tpm" >&2
    exit 1
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

# --- Generate autounattend.xml ---
WORK_DIR=$(mktemp -d "${CACHE_DIR}/windev-setup.XXXXXX")
trap 'rm -rf "$WORK_DIR"' EXIT

cat > "$WORK_DIR/autounattend.xml" <<'XMLEOF'
<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">

  <!-- === Pass 1: windowsPE — partition disk, inject virtio drivers === -->
  <settings pass="windowsPE">
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

    <component name="Microsoft-Windows-PnpCustomizationsWinPE"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <DriverPaths>
        <PathAndCredentials wcm:action="add" wcm:keyValue="1">
          <Path>E:\NetKVM\w11\amd64</Path>
        </PathAndCredentials>
        <PathAndCredentials wcm:action="add" wcm:keyValue="2">
          <Path>E:\viostor\w11\amd64</Path>
        </PathAndCredentials>
        <PathAndCredentials wcm:action="add" wcm:keyValue="3">
          <Path>E:\qxldod\w11\amd64</Path>
        </PathAndCredentials>
        <PathAndCredentials wcm:action="add" wcm:keyValue="4">
          <Path>E:\vioscsi\w11\amd64</Path>
        </PathAndCredentials>
        <PathAndCredentials wcm:action="add" wcm:keyValue="5">
          <Path>E:\Balloon\w11\amd64</Path>
        </PathAndCredentials>
        <PathAndCredentials wcm:action="add" wcm:keyValue="6">
          <Path>E:\vioserial\w11\amd64</Path>
        </PathAndCredentials>
        <PathAndCredentials wcm:action="add" wcm:keyValue="7">
          <Path>E:\viorng\w11\amd64</Path>
        </PathAndCredentials>
      </DriverPaths>
    </component>

    <component name="Microsoft-Windows-Setup"
               processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35"
               language="neutral" versionScope="nonSxS"
               xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
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

      <ImageInstall>
        <OSImage>
          <InstallFrom>
            <MetaData wcm:action="add">
              <Key>/IMAGE/INDEX</Key>
              <Value>1</Value>
            </MetaData>
          </InstallFrom>
          <InstallTo>
            <DiskID>0</DiskID>
            <PartitionID>3</PartitionID>
          </InstallTo>
        </OSImage>
      </ImageInstall>

      <UserData>
        <AcceptEula>true</AcceptEula>
        <ProductKey>
          <Key>NPPR9-FWDCX-D2C8J-H872K-2YT43</Key>
          <WillShowUI>Never</WillShowUI>
        </ProductKey>
      </UserData>
    </component>
  </settings>

  <!-- === Pass 4: specialize — computer name, RDP, firewall === -->
  <settings pass="specialize">
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
  </settings>

  <!-- === Pass 7: oobeSystem — skip OOBE, create local user === -->
  <settings pass="oobeSystem">
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

      <TimeZone>UTC</TimeZone>
    </component>
  </settings>
</unattend>
XMLEOF

# Substitute configurable username/password
sed -i "s/YOURUSER/${USER_NAME}/g; s/YOURPASSWORD/${USER_PASSWORD}/g" \
    "$WORK_DIR/autounattend.xml"

echo "Generated autounattend.xml"

# --- Create answer-file ISO ---
UNATTEND_ISO="$CACHE_DIR/${VM_NAME}-autounattend.iso"
genisoimage -quiet -o "$UNATTEND_ISO" -J -r "$WORK_DIR/autounattend.xml"
echo "Created answer-file ISO: $UNATTEND_ISO"

# --- Create disk image ---
DISK_PATH="$CACHE_DIR/${VM_NAME}.qcow2"
if [[ -f "$DISK_PATH" ]]; then
    echo "Disk image already exists: $DISK_PATH"
    echo "Remove it first if you want a fresh install."
    exit 1
fi
qemu-img create -f qcow2 "$DISK_PATH" "${DISK_GB}G"
echo "Created disk image: $DISK_PATH (${DISK_GB} GiB)"

# --- Build virt-install command ---
echo ""
echo "Creating VM '$VM_NAME'..."
echo "  vCPUs:   $VCPUS"
echo "  RAM:     $RAM_MB MiB"
echo "  Disk:    $DISK_GB GiB"
echo "  User:    $USER_NAME"
echo ""

virt-install \
    --name "$VM_NAME" \
    --memory "$RAM_MB" \
    --vcpus "$VCPUS" \
    --os-variant win11 \
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
    --sound default \
    --controller type=scsi,model=virtio-scsi \
    --noautoconsole

# Windows ISO EFI bootloader shows "Press any key to boot from CD or DVD"
# and times out if no key is sent. Send keystrokes to cover the boot window.
for _i in 1 2 3; do
    sleep 3
    virsh send-key "$VM_NAME" KEY_ENTER 2>/dev/null || true
done

if [[ "$NO_WAIT" -eq 0 ]]; then
    echo "Waiting for installation to complete (this may take 30-60 minutes)..."
    echo "Connect with: virt-viewer $VM_NAME"
    while virsh domstate "$VM_NAME" 2>/dev/null | grep -q running; do
        sleep 30
    done
fi

echo ""
echo "================================================================"
echo "  VM '$VM_NAME' created successfully!"
echo "================================================================"
echo ""
echo "Connect with:"
echo "  virt-viewer $VM_NAME"
echo "  (or: virsh domdisplay $VM_NAME)"
echo ""
echo "RDP (after install completes):"
echo "  Get VM IP:  virsh domifaddr $VM_NAME"
echo "  Connect:    xfreerdp /v:<IP> /u:$USER_NAME /p:$USER_PASSWORD /dynamic-resolution"
echo ""
echo "VM management:"
echo "  virsh start $VM_NAME"
echo "  virsh shutdown $VM_NAME"
echo "  virsh destroy $VM_NAME        # force stop"
echo "  virsh undefine $VM_NAME --nvram --tpm  # remove completely"
echo ""
