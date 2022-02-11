#!/bin/sh

# set -x

# TODO: lookup the default system bridge name
BRIDGE=virbr0
VMNAME=windev

if [ ! -f windev_VM_vmware ]; then
  echo "- Downloading VMWare windev image"
  wget https://aka.ms/windev_VM_vmware
fi

echo "- Importing $VMNAME VM to libvirt qemu:///session"
virt-v2v -on $VMNAME -oc qemu:///session -i ova windev_VM_vmware -of qcow2 --bridge nat:$BRIDGE

# for nested-virtualization WSL&docker, unfortunately it doesn't work for me
virt-xml $VMNAME --edit --cpu host-passthrough
virt-xml $VMNAME --edit --memory 8192
virt-xml $VMNAME --edit --vcpu 8
virt-xml $VMNAME --edit --graphics spice
virt-xml $VMNAME --add-device --sound ich9
virt-xml $VMNAME --add-device --channel unix,target.type=virtio,target.name=org.qemu.guest_agent.0
virt-xml $VMNAME --add-device --channel spicevmc
virt-xml $VMNAME --add-device --redirdev usb,type=spicevmc
virt-xml $VMNAME --add-device --redirdev usb,type=spicevmc

INSTALL_PS1=$(mktemp /tmp/virt-install-windev-XXXX.ps1)

cat <<EOF >$INSTALL_PS1
# firstboot script from virt-install-windev.sh

# for some reason name resolution is a bit buggy, pre-fetch some URLs...
(New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org') >\$null
(New-Object System.Net.WebClient).DownloadString('https://packages.chocolatey.org') >\$null

Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

choco install spice-agent -y
choco install git -y
choco install -y python3
choco install -y cmake
choco install msys2 -y --params '/NoPath /NoUpdate /InstallDir:C:\\msys64'

pip3 install meson

c:\msys64\usr\bin\bash -lc 'pacman -S --noconfirm base-devel vim mingw-w64-ucrt-x86_64-toolchain meson cmake'

Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
EOF

virt-customize -d $VMNAME \
  --upload $INSTALL_PS1:/firstboot.ps1 \
  --firstboot-command 'net user user pass' \
  --firstboot-command 'powershell -noprofile -executionpolicy bypass -file C:\firstboot.ps1'

echo "- Starting $VMNAME VM, setting up dev & SSH"

virsh start $VMNAME

while ! virsh domifaddr $VMNAME --source agent >/dev/null 2>&1 ; do sleep 1 ; done
IP=$(virsh domifaddr $VMNAME --interface "Ethernet Instance 0" --source agent | tail -2  | awk '{print $4}'| cut -d/ -f1)

echo "- VM IP is $IP, waiting for SSH to show up"

while ! nc -z $IP 22 ; do sleep 1 ; done

echo "- Your $VMNAME VM is ready, start hacking!"
echo "ssh user@$IP (pass: pass)"
