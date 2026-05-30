# Remote access to the GX10 box

How to reach the demo box (**`gx10-4428`**, NVIDIA GB10 / ASUS Ascent GX10) from
anywhere — SSH for the team, a public HTTPS URL for judges. Works from **Windows,
macOS, and Linux** clients.

Access path is **Tailscale** (encrypted mesh VPN, no router/port-forward config):
- **Tailscale SSH** → you + teammates reach SSH + the demo from any network, authenticated by your tailnet identity.
- **Tailscale Funnel** → exposes *only* the read-only demo web app to the public internet.
- **SSH public-key** → a fallback that also works over the LAN if Tailscale is down.

SSH is **never** exposed to the public internet; Ollama stays bound to `localhost`.

> Values filled in once the box is on the tailnet (run `tailscale status` on the box):
> - Tailnet name: `<your-tailnet>.ts.net`  (e.g. `tail1234.ts.net`)
> - Box tailnet IP: `100.x.y.z`
> - MagicDNS name: `gx10-4428` (short) / `gx10-4428.<your-tailnet>.ts.net` (full)
> - Public demo URL (Funnel): `https://gx10-4428.<your-tailnet>.ts.net`

Box identity: user **`asus`**, hostname **`gx10-4428`**, LAN IP `10.10.52.82` (venue wifi; LAN-only).

---

## TL;DR — once setup is done

```bash
# From any device signed into the same tailnet:
ssh asus@gx10-4428                      # Tailscale SSH (or: ssh asus@100.x.y.z)

# Bring the demo up on the box, then open the public URL anywhere:
ssh asus@gx10-4428 'cd ~/dev/spark-hack-toronto && . .venv/bin/activate && make demo'
#   → https://gx10-4428.<your-tailnet>.ts.net   (public, read-only)
```

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

### 3. Expose the demo publicly
```bash
# Start the demo (binds 127.0.0.1:8000; Tailscale proxies it locally):
cd ~/dev/spark-hack-toronto && . .venv/bin/activate && make demo   # leave running

# In another shell — publish :8000 to the public internet over HTTPS:
tailscale funnel --bg 8000
tailscale funnel status            # shows the public https URL
```
- `tailscale serve --bg 8000` instead → serves it **privately** on the tailnet only (no public exposure).
- Turn it off: `tailscale funnel --bg off` (or `tailscale serve reset`).

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
curl -s https://gx10-4428.<your-tailnet>.ts.net/health  # → {"status":"ok",...}
```

## Security posture
- **SSH**: tailnet-only (Tailscale SSH) + key fallback. Never funneled to the public internet.
- **Funnel**: exposes only the **read-only** demo app (GET `/`, `/analyze`, `/digest`, `/addresses`, `/health`). No mutations, no secrets, no auth needed for the public demo.
- **Ollama** (`:11434`) and the **memory/db** stay bound to `localhost` — never exposed.
- Turn off the public URL the moment the demo's over: `tailscale funnel --bg off`.

## Troubleshooting
- `tailscale status` says *Logged out* → re-run `sudo tailscale up --ssh`.
- Funnel error *"Funnel not available"* → finish admin-console step 2 (HTTPS certs + `funnel` nodeAttr).
- Public URL 502 → the demo server isn't running; start `make demo` on the box.
- Can't SSH over tailnet → confirm the **client** is signed into the **same tailnet** (`tailscale status` on the client).
- LAN SSH only (no Tailscale): `ssh asus@10.10.52.82` — works only on the same wifi.
