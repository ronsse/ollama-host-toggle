# Driving the agent from another host

`ollama-host-toggle` exposes a token-gated HTTP API on your tailnet, so any
always-on machine (a hub, a home server, a cron box) can turn GPU hosting on/off
and check status remotely.

## Direct calls
```bash
AGENT="http://<gpu-box-tailnet-ip>:11435"
TOKEN="<auth_token from the agent's config.toml>"
AUTH="Authorization: Bearer $TOKEN"

curl -s -H "$AUTH" "$AGENT/state"
curl -s -X POST -H "$AUTH" -H 'Content-Type: application/json' \
     -d '{"preload":"qwen2.5:14b"}' "$AGENT/host/on"
curl -s -X POST -H "$AUTH" "$AGENT/host/off"
```

If the agent is unreachable (box asleep/off), treat that as **hosting = off** and
fall back to whatever your default tier is.

## Example: a small reverse-proxy (Node/Express)
Wrap the agent behind your own hub so internal callers don't need the token. The
hub holds the token; clients just hit the hub.

```js
const AGENT = process.env.AGENT_URL  || 'http://<gpu-box-tailnet-ip>:11435';
const TOKEN = process.env.AGENT_TOKEN || '';

async function agent(path, { method = 'GET', body } = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), method === 'GET' ? 5000 : 130000);
  try {
    const res = await fetch(AGENT.replace(/\/$/, '') + path, {
      method,
      headers: { Authorization: `Bearer ${TOKEN}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    return { status: res.status, data: await res.json().catch(() => ({})) };
  } finally { clearTimeout(t); }
}

// GET /gpu/state — report 'off' instead of erroring when the box is unreachable
app.get('/gpu/state', async (_q, res) => {
  try { const r = await agent('/state'); res.status(r.status).json(r.data); }
  catch { res.json({ reachable: false, serving: false }); }
});

// POST /gpu/host  {on:true|false, preload?:'model'}
app.post('/gpu/host', async (req, res) => {
  const on = req.body?.on === true || req.body?.action === 'on';
  try {
    const r = on
      ? await agent('/host/on', { method: 'POST', body: req.body?.preload ? { preload: req.body.preload } : {} })
      : await agent('/host/off', { method: 'POST' });
    res.status(r.status).json(r.data);
  } catch (e) { res.status(502).json({ error: 'agent unreachable', detail: String(e) }); }
});
```

## Networking note (Docker)
If your hub runs in a **bridge-networked container**, the tailnet hostname won't
resolve inside it (no MagicDNS) — use the **tailnet IP**. Traffic to `100.64.0.0/10`
is NAT'd through the host's `tailscale0`, so the IP works without host networking.

## Cold power-on
The HTTP API only answers when the box is awake. To wake it from sleep/off, pair
this with **Wake-on-LAN** (send a magic packet from the same LAN, then poll
`/state` until it answers). WoL is the only fallback the agent can't cover itself.
