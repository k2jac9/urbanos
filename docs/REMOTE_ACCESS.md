# Remote access to the GX10 box

How to reach the demo box (**`gx10-4428`**, NVIDIA GB10 / ASUS Ascent GX10) from
anywhere — SSH for the team, a public HTTPS URL for judges. Works from **Windows,
macOS, and Linux** clients.

Access path is **Tailscale** (encrypted mesh VPN, no router/port-forward config):
- **Tailscale SSH** → you + teammates reach SSH + the demo from any network, authenticated by your tailnet identity.
- **Tailscale Funnel** → exposes *only* the read-only demo web app to the public internet.
- **SSH public-key** → a fallback that also works over the LAN if Tailscale is down.

SSH is **never** exposed to the public internet; Ollama stays bound to `localhost`.

> **Live values** (this tailnet — none of these are secrets; the Funnel URL is meant to be public,
> the `100.x` IP only resolves inside the tailnet):
> - Tailnet name: `taila9fe06.ts.net`
> - Box tailnet IP: `100.73.241.60`
> - MagicDNS name: `gx10-4428` (short) / `gx10-4428.taila9fe06.ts.net` (full)
> - **Public demo URL (Funnel): https://gx10-4428.taila9fe06.ts.net** ← share with judges
>
> Turn the public URL **off** when the demo's done: `tailscale funnel --https=443 off`.

Box identity: user **`asus`**, hostname **`gx10-4428`**, LAN IP `10.10.52.82` (venue wifi; LAN-only).

---

## TL;DR — once setup is done

```bash
# From any device signed into the same tailnet:
ssh asus@gx10-4428                      # Tailscale SSH (or: ssh asus@100.x.y.z)

# Bring the demo up AND flip the public URL on, in one command (on the box):
ssh asus@gx10-4428 'cd ~/dev/spark-hack-toronto && . .venv/bin/activate && make demo-public'
#   → https://gx10-4428.taila9fe06.ts.net   (public, read-only)

# Take the public URL back down when you're done:
ssh asus@gx10-4428 'cd ~/dev/spark-hack-toronto && make funnel-off'
```

**`make demo` = local only** (no public URL) · **`make demo-public` = local + public Funnel** ·
**`make funnel-off` = guaranteed teardown** (the Ctrl-C trap is best-effort).

---

## One-time setup on the box (`gx10-4428`)

These need `sudo` and a browser login, so a human runs them on the box.

### 1. Join the tailnet with SSH enabled
```bash
sudo tailscale up --ssh
```
Open the printed `https://login.tailscale.com/a/…` URL, sign in, approve `gx10-4428`.
Verify: `tailscale status` (should show the box `100.x` IP and `online`).

### 2. Enable Funnel (Tailscale admin console — https://login.tailscale.com)
Funnel = the public demo URL. One-time, browser-only:
1. **DNS** tab → enable **MagicDNS** and **HTTPS Certificates**.
2. **Access Controls** → use the policy in [`tailscale-policy.hujson`](./tailscale-policy.hujson)
   (this tailnet uses the new **grants** syntax). The key addition over the default is a
   top-level `nodeAttrs` block granting `funnel`:
   ```json
   "nodeAttrs": [
       { "target": ["autogroup:member"], "attr": ["funnel"] },
   ],
   ```
   Paste the whole file, or just add that block alongside your existing `grants` and `ssh`.
   (Newer tailnets also expose a per-machine **Funnel** toggle in the machine's `⋯` menu.)

> **SSH already works** with the default `ssh` rule (`autogroup:member` → `autogroup:self`,
> `check` mode) because the box is registered under your account — no change needed for SSH.
> - `check` mode re-prompts for browser auth ~every 12h; switch to `"action": "accept"` for a
>   frictionless demo.
> - That rule only allows SSH into devices **you own**. For teammates on their **own** Tailscale
>   accounts, tag the box (`tag:demo`) and grant the team SSH to it — see the commented
>   *OPTIONAL* block in [`tailscale-policy.hujson`](./tailscale-policy.hujson), then bring the box
>   up with `sudo tailscale up --ssh --advertise-tags=tag:demo`.

### 3. Expose the demo publicly — one command
```bash
cd ~/dev/spark-hack-toronto && . .venv/bin/activate
make demo-public          # serves :8000 AND flips Funnel on; prints the public URL
# ... demo ...
make funnel-off           # take the public URL back down (reliable teardown)
```
`make demo-public` is best-effort about Funnel: off-box, or without operator + the `funnel`
policy attr, it just serves locally. Requires `sudo tailscale set --operator=$USER` once so
the Makefile can manage Funnel without sudo.

Under the hood (if you'd rather do it by hand):
```bash
make demo                          # local server on :8000 (no public URL)
tailscale funnel --bg 8000         # publish :8000 publicly over HTTPS
tailscale serve  --bg 8000         # ...or serve it PRIVATELY on the tailnet only
tailscale funnel --https=443 off   # turn the public URL off
```

### 4. Keep the demo up across reboots (systemd user service)
Funnel config and `tailscaled` already survive a reboot, but `make demo` is a foreground
process — so after a reboot the public URL would proxy to a dead `:8000` (judges see a **502**).
A **systemd *user* service** closes that gap: it auto-starts the server on boot and restarts it
on crash. No `sudo` needed (user unit + linger), so the box's non-sudo `asus` account can manage it.

One-time, on the box:
```bash
loginctl enable-linger                       # run user services without an active login (no sudo)
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/civic-demo.service <<'UNIT'
[Unit]
Description=Civic Analyst demo (uvicorn :8000, real downtown data)
Documentation=https://gx10-4428.taila9fe06.ts.net

[Service]
WorkingDirectory=/home/asus/dev/spark-hack-toronto
Environment=DATA_DIR=demo_data
ExecStart=/home/asus/dev/spark-hack-toronto/.venv/bin/python -m uvicorn civic_analyst.api.server:app --port 8000 --app-dir src
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now civic-demo.service     # start now + on every boot
```
Manage / inspect it:
```bash
systemctl --user status civic-demo        # is it running?
systemctl --user restart civic-demo       # e.g. after a `git pull`
systemctl --user stop civic-demo          # free :8000 to run `make demo` by hand
journalctl --user -u civic-demo -f        # live logs
```
Notes:
- The unit serves **local-only** (`:8000`); Funnel still publishes it — so `make funnel-off`
  is still how you take the **public** URL down. The service keeps `:8000` alive underneath.
- To run `make demo`/`make demo-public` by hand, `stop` the service first (avoids a `:8000` clash).
- This is a CORE-demo safety net, not a CI-gated artifact — it lives on the box, not in the repo.

---

## SSH public-key fallback (works over LAN or tailnet)

Tailscale SSH needs no keys, but a key lets `ssh asus@…` work even if Tailscale is down.

### Get your client's public key
- **Windows** (PowerShell / Windows Terminal — OpenSSH is built in):
  ```powershell
  type $env:USERPROFILE\.ssh\id_ed25519.pub
  # If missing, generate first:  ssh-keygen -t ed25519
  ```
- **macOS / Linux**:
  ```bash
  cat ~/.ssh/id_ed25519.pub
  # If missing:  ssh-keygen -t ed25519
  ```
Copy the whole `ssh-ed25519 AAAA… you@host` line. **Never share the private key** (`id_ed25519`, no `.pub`).

### Add it on the box (append, don't overwrite)
```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'ssh-ed25519 AAAA…your-key… you@host' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

---

## Per-client setup

### Windows
1. Install Tailscale: https://tailscale.com/download/windows (GUI). Sign in with the **same account/tailnet** as the box.
2. SSH is built into Windows 10/11 — use `ssh asus@gx10-4428` in PowerShell/Windows Terminal.

### macOS / Linux
1. Install Tailscale: `https://tailscale.com/download` (or `curl -fsSL https://tailscale.com/install.sh | sh` on Linux), then `tailscale up`. Same tailnet as the box.
2. `ssh asus@gx10-4428`.

### Handy `~/.ssh/config` block (all client OSes)
```sshconfig
Host gx10
    HostName gx10-4428              # MagicDNS name; or the 100.x.y.z tailnet IP
    User asus
    ServerAliveInterval 30
```
Then just: `ssh gx10`.

---

## Verify
```bash
tailscale status                                        # box + your devices listed, online
ssh asus@gx10-4428 'hostname'                           # → gx10-4428
curl -s https://gx10-4428.taila9fe06.ts.net/health      # → {"status":"ok",...}  (verified working)
```

## Security posture
- **SSH**: tailnet-only (Tailscale SSH) + key fallback. Never funneled to the public internet.
- **Funnel**: exposes only the **read-only** demo app (GET `/`, `/analyze`, `/digest`, `/addresses`, `/health`). No mutations, no secrets, no auth needed for the public demo.
- **Ollama** (`:11434`) and the **memory/db** stay bound to `localhost` — never exposed.
- Turn off the public URL the moment the demo's over: `tailscale funnel --bg off`.

## Troubleshooting
- `tailscale status` says *Logged out* → re-run `sudo tailscale up --ssh`.
- Funnel error *"Funnel not available"* → finish admin-console step 2 (HTTPS certs + `funnel` nodeAttr).
- Public URL 502 → the demo server isn't running. If the `civic-demo` service is installed:
  `systemctl --user status civic-demo` (restart with `systemctl --user restart civic-demo`);
  otherwise start `make demo` on the box. See *Keep the demo up across reboots* above.
- Can't SSH over tailnet → confirm the **client** is signed into the **same tailnet** (`tailscale status` on the client).
- LAN SSH only (no Tailscale): `ssh asus@10.10.52.82` — works only on the same wifi.
