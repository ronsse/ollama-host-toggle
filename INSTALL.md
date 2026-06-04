# Install ollama-host-toggle

Windows + Python 3.12. Run on the GPU machine that hosts Ollama.

## 1. Dependencies
```powershell
python -m pip install -r requirements.txt
```

## 2. Run
```powershell
pythonw -m ollama_host_toggle      # windowless (no console)
```
On **first run** it auto-creates `config.toml` with a generated `auth_token` and your
detected Tailscale IP, then shows a tray notification. A tray icon appears:
**green** = serving + model loaded, **amber** = serving but idle, **grey** = off.

For debugging, run with a console to see tracebacks:
```powershell
python -m ollama_host_toggle
```

## 3. Configure (optional)
Edit `config.toml` (created on first run; gitignored) to adjust `models`,
`default_preload`, `http_bind`, `hub_status_url`, etc. See `config.example.toml` for
every key. To rotate the token, change `auth_token` or set the
`OLLAMA_HOST_TOGGLE_TOKEN` env var (it overrides the file).

`http_bind` should be your **tailnet IP** (auto-detected on first run) so the API is
reachable only over Tailscale. Do **not** use `0.0.0.0` unless you mean to expose it.

## 4. Autostart at login
Right-click the tray icon → **Start at login** (toggle on). That creates a Startup
shortcut to a windowless launch; toggle off to remove it. No manual steps needed.

> Prefer to do it by hand? Drop a shortcut to `run.bat` in your Startup folder
> (`shell:startup`).

## 5. Verify the HTTP API (from another tailnet host)
```bash
TOKEN=<auth_token from config.toml>
IP=<this machine's tailnet IP>
curl -s -H "Authorization: Bearer $TOKEN" http://$IP:11435/state | jq

# start hosting + preload
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"preload":"qwen2.5:14b"}' http://$IP:11435/host/on

# stop hosting (free VRAM) — confirm nvidia-smi drops
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://$IP:11435/host/off
```
A request without a valid Bearer token returns `401`.

## (Optional) Build a standalone exe
```powershell
python -m pip install pyinstaller
pyinstaller ollama-host-toggle.spec
# dist/ollama-host-toggle.exe  — creates config.toml in its working dir on first run
```
