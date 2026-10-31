# Proxmox VE host: recommended Linux VM approach

**[Installation hub](../README.md) | [Linux Docker](docker-linux.md) | [Unraid](unraid.md) | [AI setup](../guides/ai-setup.md)**

**Status: Guidance only; no Proxmox template or full install test completed.**

## Recommended deployment

1. Create a dedicated Ubuntu/Debian **virtual machine** on Proxmox VE.
2. Give it stable LAN networking, sufficient RAM/CPU for dashboard + optional paper/live processes and an appropriately backed-up virtual disk for state.
3. Install Docker Engine + Compose plugin, Git, Python 3 and OpenSSL in the guest.
4. Follow [Linux Docker](docker-linux.md): `sudo sh install.sh --platform docker`.
5. Keep the guest firewall restricted to trusted LAN clients. If running Ollama or forecasting elsewhere, allow guest access to those private LAN endpoints only.

Using a VM keeps Docker's kernel/storage expectations within a normal guest OS. Advanced users can experiment with nested containers/LXC, but **nested Docker in an LXC is not tested or recommended as the default Auto Trader deployment**. An LXC is **not** the same isolation boundary as a fully virtualized Linux guest.

## Backups and upgrades

Use the Proxmox guest backup facility for the VM, and independently back up the Auto Trader data directory and broker tokens securely. Take a consistent, stopped-container backup before updating application code.

## Compatibility

- No prebuilt Proxmox image, cloud-init template, or Terraform automation is published.
- No validation of Proxmox host network bridging/PCI GPU pass-through for the AI workstation has been completed.
- Live trading remains disabled after first install; review the [Schwab authorization guide](../guides/schwab.md).
