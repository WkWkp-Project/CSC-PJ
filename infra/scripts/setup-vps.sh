#!/usr/bin/env bash
# One-time VPS preparation for Ubuntu 24.04 / 22.04 (also works on Debian 12).
# Run as root on a FRESH server:  bash setup-vps.sh <your-ssh-username>
#
# It does: system update, firewall (22/80/443 only), Docker, and a non-root user
# with sudo + docker. It does NOT touch your apps, does NOT open the database
# port, and does NOT disable password login - do that yourself only after you
# have confirmed key-based login works, otherwise you can lock yourself out.
set -euo pipefail

USERNAME="${1:-deploy}"
if [[ $EUID -ne 0 ]]; then echo "run as root: sudo bash $0 $USERNAME" >&2; exit 1; fi
if ! [[ "$USERNAME" =~ ^[a-z_][a-z0-9_-]{1,30}$ ]]; then echo "bad username: $USERNAME" >&2; exit 2; fi
. /etc/os-release
echo "== preparing $PRETTY_NAME for user '$USERNAME'"

echo "== 1/5 system update"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get -y -qq upgrade
apt-get -y -qq install ufw git curl ca-certificates

echo "== 2/5 firewall (SSH allowed first, so this session is not cut off)"
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose

echo "== 3/5 Docker"
if command -v docker >/dev/null 2>&1; then
  echo "docker already installed: $(docker --version)"
else
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/${ID}/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
    "$(dpkg --print-architecture)" "$ID" "$VERSION_CODENAME" > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get -y -qq install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

echo "== 4/5 user '$USERNAME'"
if id "$USERNAME" >/dev/null 2>&1; then
  echo "user already exists, leaving its password alone"
else
  adduser --disabled-password --gecos "" "$USERNAME"
  echo "set a password for '$USERNAME' (or press Ctrl-C to use an SSH key only):"
  passwd "$USERNAME" || true
fi
usermod -aG sudo,docker "$USERNAME"
# Copy root's authorised SSH keys so key-based login keeps working for the new user.
if [[ -f /root/.ssh/authorized_keys ]]; then
  install -d -m 700 -o "$USERNAME" -g "$USERNAME" "/home/$USERNAME/.ssh"
  install -m 600 -o "$USERNAME" -g "$USERNAME" /root/.ssh/authorized_keys "/home/$USERNAME/.ssh/authorized_keys"
  echo "copied root's SSH keys to $USERNAME"
fi

echo "== 5/5 /opt/platform"
mkdir -p /opt/platform
chown "$USERNAME" /opt/platform

cat <<DONE

Done.
Docker:  $(docker --version 2>/dev/null || echo 'not reporting')
Compose: $(docker compose version 2>/dev/null | head -1 || echo 'not reporting')

Next:
  1. From your PC, open a NEW terminal and check you can log in:
       ssh $USERNAME@<this server's IP>
     Keep this root session open until that works.
  2. Then follow infra/README.md from step 2 (clone the repo into /opt/platform).
  3. Only after key-based login is confirmed, disable password login in
     /etc/ssh/sshd_config (PasswordAuthentication no) and run: systemctl restart ssh
DONE
