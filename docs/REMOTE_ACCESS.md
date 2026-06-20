# Remote access to the GX10 box

How to reach the demo box (**`gx10-4428`**, NVIDIA GB10 / ASUS Ascent GX10) from
anywhere — SSH for the team, a public HTTPS URL for judges. Works from **Windows,
macOS, and Linux** clients.

Access path is **Tailscale** (encrypted mesh VPN, no router/port-forward config):
- **Tailscale SSH** → you + teammates reach SSH + the demo from any network, authenticated by your tailnet identity.
- **Tailscale Funnel** → exposes *only* the read-only demo web app to the public internet.
- **SSH public-key** → a fallback that also works over the LAN if Tailscale is down.

SSH is **never** exposed to the public internet; Ollama stays bound to `localhost`.

> **Live values** (this tailnet — none of these are secrets; the Funnel URLs are meant to be public,
> the `100.x` IP only resolves inside the tailnet):
> - Tailnet name: `taila9fe06.ts.net`
> - Box tailnet IP: `100.73.241.60`
> - MagicDNS name: `gx10-4428` (short) / `gx10-4428.taila9fe06.ts.net` (full)
> - **Public demo URLs (Funnel)** ← share with judges:
>   - **urbanos.risk (`:8000`): https://gx10-4428.taila9fe06.ts.net**
>   - **urbanos.kernel (`:8001`): https://gx10-4428.taila9fe06.ts.net:8443** (the flagship; Funnel maps `:8443`→`:8001`)
>
> Turn **both** public URLs off when the demo's done: `make funnel-off-all` (on the box).

Box identity: Linux user **`asus`**, hostname **`gx10-4428`**, LAN IP `10.10.52.82` (venue wifi; LAN-only).
The box is **tagged** (`tag:demo`) in the tailnet, so it shows as `tagged-devices` in `tailscale status`
(not owned by a personal account) — SSH access comes from the `tag:demo` grant, not personal ownership.

---

## TL;DR — once setup is done

```bash
# From any device signed into the same tailnet:
ssh asus@gx10-4428                      # Tailscale SSH (or: ssh asus@100.73.241.60)

# Both apps already run as systemd user services on the box (see §4) and both Funnels are on.
# After a `git pull` on the box, just restart the services so the live demo matches the repo:
ssh asus@gx10-4428 'systemctl --user restart civic-demo urbanos-demo'

# Public, read-only URLs (no setup needed if the services + Funnels are up):
#   urbanos.risk → https://gx10-4428.taila9fe06.ts.net
#   urbanos.kernel      → https://gx10-4428.taila9fe06.ts.net:8443

# Take BOTH public URLs back down when you're done:
ssh asus@gx10-4428 'cd ~/dev/spark-hack-toronto && make funnel-off-all'
```

**`make demo` = local only** (no public URL) · **`make demo-public` = local + public Funnel for `:8000`** ·
**`make funnel-off` = teardown of the `:8000`/`:443` Funnel only** ·
**`make funnel-off-all` = teardown of BOTH** (urbanos.risk `:443` + urbanos.kernel `:8443`).
The Ctrl-C trap in `make demo-public` is best-effort.

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

> **SSH is set up via the `tag:demo` grant** (the box is *tagged*, not owned by a personal
> account — it shows as `tagged-devices` in `tailscale status`). The team's SSH access to it
> comes from the `tag:demo` SSH grant in [`tailscale-policy.hujson`](./tailscale-policy.hujson),
> and the box was brought up with `sudo tailscale up --ssh --advertise-tags=tag:demo`.
> - This lets **teammates on their own Tailscale accounts** SSH into the box (a personal-ownership
>   rule like `autogroup:member` → `autogroup:self` would only cover devices *you* own).
> - If you use `check` mode it re-prompts for browser auth ~every 12h; switch to
>   `"action": "accept"` for a frictionless demo.

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

Under the hood (if you'd rather do it by hand). **Both apps are published** — urbanos.risk on the
default HTTPS port (`:443`) and urbanos.kernel on `:8443`:
```bash
make demo                              # local urbanos.risk on :8000 (no public URL)
tailscale funnel --bg 8000             # publish :8000 publicly on https://…  (→ :443)
tailscale funnel --bg --https=8443 8001  # publish urbanos.kernel :8001 publicly on https://…:8443
tailscale serve  --bg 8000             # ...or serve it PRIVATELY on the tailnet only
tailscale funnel --https=443 off       # turn the urbanos.risk public URL off
tailscale funnel --https=8443 off      # turn the urbanos.kernel public URL off
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
ExecStart=/home/asus/dev/spark-hack-toronto/.venv/bin/python -m uvicorn urbanos.risk.api.server:app --port 8000 --app-dir src
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now civic-demo.service     # start now + on every boot
```
The box runs **two** such user services (both `active`, with linger enabled):
- **`civic-demo.service`** — urbanos.risk, uvicorn on `:8000`.
- **`urbanos-demo.service`** — urbanos.kernel, uvicorn on `:8001` (local-only; reached via the `:8443` Funnel).

Manage / inspect them (act on both at once by listing both unit names):
```bash
systemctl --user status civic-demo urbanos-demo     # are they running?
systemctl --user restart civic-demo urbanos-demo    # e.g. after a `git pull` on the box
systemctl --user stop civic-demo                    # free :8000 to run `make demo` by hand
journalctl --user -u civic-demo -f                  # live logs (swap unit name for urbanos.kernel)
```
Notes:
- The units serve **local-only** (`:8000` / `:8001`); Funnel publishes them — so the
  `tailscale funnel … off` commands above are how you take the **public** URLs down. The
  services keep the local ports alive underneath.
- To run `make demo`/`make demo-public` by hand, `stop` the matching service first (avoids a port clash).
- These are CORE-demo safety nets, not CI-gated artifacts — they live on the box, not in the repo.

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
tailscale status                                          # box (tagged-devices) + your devices, online
ssh asus@gx10-4428 'hostname'                             # → gx10-4428
curl -s https://gx10-4428.taila9fe06.ts.net/health        # urbanos.risk → {"status":"ok",...}  (verified)
curl -s https://gx10-4428.taila9fe06.ts.net:8443/health   # urbanos.kernel      → {"status":"ok",...}  (verified)
```

## Security posture
- **SSH**: tailnet-only (Tailscale SSH via the `tag:demo` grant) + key fallback. Never funneled to the public internet.
- **Funnel**: exposes only the **read-only** demo apps — urbanos.risk on `:443` (GET `/`, `/analyze`, `/digest`, `/addresses`, `/health`) and urbanos.kernel on `:8443`. No mutations, no secrets, no auth needed for the public demo.
- **Ollama** (`:11434`) and the **memory/db** stay bound to `localhost` — never exposed.
- Turn off **both** public URLs the moment the demo's over: `make funnel-off-all`
  (or `tailscale funnel --https=443 off && tailscale funnel --https=8443 off`).

## Troubleshooting
- `tailscale status` says *Logged out* → re-run `sudo tailscale up --ssh`.
- Funnel error *"Funnel not available"* → finish admin-console step 2 (HTTPS certs + `funnel` nodeAttr).
- Public URL 502 → the matching demo server isn't running. Check the service for that URL
  (`systemctl --user status civic-demo urbanos-demo`; restart with
  `systemctl --user restart civic-demo urbanos-demo`); otherwise start `make demo` on the box.
  See *Keep the demo up across reboots* above.
- urbanos.kernel URL (`:8443`) unreachable but civic is fine → that Funnel is managed by hand, not by
  `make funnel-off`. Re-publish it: `tailscale funnel --bg --https=8443 8001`.
- Can't SSH over tailnet → confirm the **client** is signed into the **same tailnet** (`tailscale status` on the client).
- LAN SSH only (no Tailscale): `ssh asus@10.10.52.82` — works only on the same wifi.
