# Devbox Restore Procedure

This procedure restores the devbox on an external libvirt/KVM host after a
disk loss. It rebuilds the OS with Ansible, then restores data with restic.

## 1. Rebuild the VM

1. Create a fresh VM from the Ubuntu 24.04 (Noble) cloud image with the
   NoCloud cloud-init seed. Give it 8 vCPUs, 20 GiB RAM, and a 200 GiB
   virtio root disk.
2. Make sure the VM gets the IP `192.168.1.51` (static netplan config or a
   DHCP reservation by MAC).
3. Wait for cloud-init to finish, then confirm SSH access:
   `ssh stian@192.168.1.51 true`.

## 2. Converge

Run from the lab repository on your workstation:

```bash
just devbox-converge
```

This installs all tools, the backup role, and mounts the NFS backup share at
`/mnt/backup`.

## 3. Restore data

All commands run as root inside the VM.

```bash
export RESTIC_REPOSITORY=/mnt/backup/restic
export RESTIC_PASSWORD_FILE=/etc/restic/devbox-backup.password
```

Note: a fresh converge generates a new password file. Replace
`/etc/restic/devbox-backup.password` with the saved copy of the old
password before you continue. Keep an off-VM copy of this password. Without
it, the repository is unreadable.

List snapshots and pick one:

```bash
restic snapshots
```

Restore the home directory in place:

```bash
restic restore latest --target / --include /home/stian
chown -R stian:stian /home/stian
```

Restore `/etc` into a staging directory. Do not restore it in place, because
the fresh OS and Ansible already own most of `/etc`:

```bash
restic restore latest --target /root/restore-etc --include /etc
```

Copy only the files you need from `/root/restore-etc/etc` (for example
manually added config that Ansible does not manage).

## 4. Verify

1. `systemctl status devbox-backup.timer` shows the timer active.
2. `restic snapshots` works with the restored password file.
3. SSH, devbox-html (port 80), opencode web (port 4096), and node-exporter
   (port 9100) respond.
4. Re-join Tailscale if needed: the tailnet identity lives in
   `/var/lib/tailscale`, which is not in the backup set.
