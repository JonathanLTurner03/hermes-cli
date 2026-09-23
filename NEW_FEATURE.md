# Hecate Reverse Proxy (Traefik + DMZ Bastion)

## What this is

Hecate is a dual-NIC minipc sitting between the internet-facing side of the
network and the SERVERS VLAN. One NIC (enp4s0) is on a dedicated DMZ VLAN
that only the router can reach from WAN; the other (enp2s0) is on SERVERS.
Traefik runs on Hecate and is the only thing allowed to bridge the two —
nothing on SERVERS has a port open to the DMZ or to WAN directly.

Traefik uses the **file provider**, not the Docker labels provider. It never
mounts a Docker socket, on Hecate or anywhere else. Route config
(`route.yml`) lives in the `hermes` registry next to the service it points
to, and gets synced onto Hecate's watched directory. This means:

- Hecate has no way to enumerate or control containers on any other host —
  a compromised Traefik only has network access to the ports it's been
  told to route to.
- Enabling/disabling a route is a file in git (`hermes`), not a label baked
  into a compose file — auditable, and doesn't require touching the
  backend service's own config.
- Adding a backend host never requires giving Traefik new credentials or
  API access to that host.

## Network layout

| Host | Interface | IP | VLAN | Role |
|---|---|---|---|---|
| Hecate | enp4s0 | `10.0.21.10` | DMZ (21) | WAN-facing, TLS termination |
| Hecate | enp2s0 | `10.0.20.10` | SERVERS (20) | Internal-only entrypoint |
| Atlantis | — | `10.0.20.20` | SERVERS (20) | Backend host (Jellyfin, arr stack, etc.) |
| Omada controller | — | `10.0.10.x` *(unconfirmed)* | MGMT (10) | Router/switch/AP management |

```
                 WAN
                  │
                  ▼
          router (80/443 → Hecate DMZ)
                  │
     ┌────────────┴────────────┐
     │           Hecate         │
     │  enp4s0  10.0.21.10 (DMZ)│──▶ Traefik: web / websecure entrypoints
     │  enp2s0  10.0.20.10 (SRV)│──▶ Traefik: internal entrypoint (:8443)
     └────────────┬────────────┘
                  │  SERVERS VLAN (20)
                  ▼
     Atlantis 10.0.20.20 ── published ports, bound to this IP only
     (Jellyfin, Jellyseerr, Sonarr, Radarr, Prowlarr, qBittorrent, ...)
```

The DMZ entrypoints (`web`/`websecure`) are for anything that should be
reachable from the internet. The `internal` entrypoint on the SERVERS IP is
for things that want Traefik's features (hostname, TLS, auth) but should
never cross the DMZ boundary — the Omada controller UI is the current
example.

## Traffic rules (recap)

- **SERVERS ↔ SERVERS** (e.g. Jellyseerr → Sonarr on Atlantis, or a
  cross-host case): direct, VLAN IP to VLAN IP, never through Hecate.
  Same-host calls between containers should use Docker networks and
  container names instead of IPs at all — see the arr-stack example below.
- **TRUSTED → SERVERS**: direct at the router firewall (allow specific
  ports), not through Hecate. Only route through Traefik's `internal`
  entrypoint if you specifically want the proxy's features on that hop.
- **WAN → SERVERS**: always through Hecate's DMZ entrypoints. Nothing on
  SERVERS should have a port reachable from WAN or from the DMZ VLAN
  directly.
- **SERVERS → MGMT**: denied by the router ACLs by default. The Omada
  route below needs a one-off permit rule — see "Known gaps."

## Registry layout (hermes)

```
hermes/
└── hecate/
    ├── traefik/
    │   ├── docker-compose.yml
    │   ├── .env
    │   └── .env.secrets        (gitignored, not committed)
    └── routes/
        └── <name>/
            ├── route.yml
            └── enabled          (empty marker file)
```

`route.yml` files for services that *do* live under `hc` (Jellyfin,
Jellyseerr, etc.) belong next to that service's own `docker-compose.yml` on
its host's directory in the registry, not under `hecate/routes/`.
`hecate/routes/` is only for routes to things `hc` doesn't manage — the
Omada controller being the first case, since it's not deployed via
compose/hc at all.

The `enabled` marker is what's supposed to control whether a route file
gets symlinked into Traefik's live `dynamic-enabled/` directory on Hecate.

## Known gaps (as of this writing)

- **`hc sync` doesn't exist yet.** The roadmap only has
  `init/pull/where/services/up/down/restart/logs/status`. Until it's
  built, get a route live by hand:
  ```bash
  hc pull   # on hecate
  ln -s /opt/infra/hermes/hecate/routes/omada/route.yml \
        /opt/infra/hermes/hecate/traefik/dynamic-enabled/omada.yml
  ```
  When `hc sync` is built, it should walk the registry for
  `route.yml` + `enabled` pairs and make this same symlink.
- **Omada controller's MGMT IP is unconfirmed.** The Pi5 VLAN
  subinterface work (`eth0.10`) was still in progress last we touched it.
  Confirm the final address before wiring the route.
- **SERVERS → MGMT is denied** by the router ACLs. The Omada route needs
  an explicit router-level permit for Hecate's SERVERS IP
  (`10.0.20.10`) → the controller's MGMT IP on `8043/tcp`. That's a
  scoped, one-off exception — not a general SERVERS→MGMT opening.

## Implementation

### 1. Traefik on Hecate

`hecate/traefik/docker-compose.yml`:

```yaml
services:
  traefik:
    image: traefik:v3.1
    container_name: traefik
    restart: unless-stopped
    env_file:
      - .env
      - .env.secrets
    command:
      - --providers.file.directory=/dynamic
      - --providers.file.watch=true
      - --entrypoints.web.address=:80
      - --entrypoints.websecure.address=:443
      - --entrypoints.web.http.redirections.entrypoint.to=websecure
      - --entrypoints.internal.address=:8443
      - --certificatesresolvers.cf.acme.dnschallenge=true
      - --certificatesresolvers.cf.acme.dnschallenge.provider=cloudflare
      - --certificatesresolvers.cf.acme.email=${ACME_EMAIL}
      - --certificatesresolvers.cf.acme.storage=/letsencrypt/acme.json
      - --api.dashboard=true       # only bound to `internal` below
    ports:
      - "10.0.21.10:80:80"         # DMZ
      - "10.0.21.10:443:443"       # DMZ
      - "10.0.20.10:8443:8443"     # SERVERS-facing, internal-only
    volumes:
      - ./dynamic-enabled:/dynamic:ro
      - ./letsencrypt:/letsencrypt
    # no docker.sock mount
```

`.env` (tracked): `ACME_EMAIL=you@atlantissrv.com`
`.env.secrets` (gitignored): `CF_DNS_API_TOKEN=...`

### 2. Backend services (example: arr stack on Atlantis)

Same-host services talk to each other by container name over a shared
Docker network, with no published ports. Only what Hecate needs to reach
gets a `ports:` entry, bound to Atlantis's VLAN IP:

```yaml
services:
  jellyfin:
    image: jellyfin/jellyfin
    networks: [request-net]
    ports:
      - "10.0.20.20:8096:8096"

  jellyseerr:
    image: fallenbagel/jellyseerr
    networks: [request-net]
    ports:
      - "10.0.20.20:5055:5055"

  sonarr:
    image: lscr.io/linuxserver/sonarr
    networks: [request-net, arr-net]   # no ports:

  radarr:
    image: lscr.io/linuxserver/radarr
    networks: [request-net, arr-net]

  prowlarr:
    image: lscr.io/linuxserver/prowlarr
    networks: [arr-net]

  qbittorrent:
    image: lscr.io/linuxserver/qbittorrent
    networks: [arr-net]

networks:
  request-net:
  arr-net:
```

Jellyseerr is configured with `http://sonarr:8989`, `http://radarr:7878`,
`http://jellyfin:8096`. It's never on `arr-net`, so it has no route to
qBittorrent even if compromised.

Lock the two published ports down to Hecate's SERVERS IP on Atlantis:

```bash
ufw route allow proto tcp from 10.0.20.10 to any port 5055
ufw route allow proto tcp from 10.0.20.10 to any port 8096
```

(Remember plain `ufw` rules don't apply to Docker's published ports —
Docker's iptables rules bypass ufw's INPUT chain. Use `ufw route` /
`DOCKER-USER` or the `ufw-docker` wrapper.)

### 3. Route files

`jellyseerr/route.yml` (lives next to Jellyseerr's own compose file in the
registry, under Atlantis's directory):

```yaml
http:
  routers:
    jellyseerr:
      rule: Host(`requests.atlantissrv.com`)
      entryPoints: [websecure]
      service: jellyseerr
      tls: { certResolver: cf }
  services:
    jellyseerr:
      loadBalancer:
        servers:
          - url: http://10.0.20.20:5055
```

`jellyfin/route.yml` is the same shape, pointed at `10.0.20.20:8096`.

`hecate/routes/omada/route.yml` (internal-only, see "Known gaps" above for
what's still outstanding on this one):

```yaml
http:
  routers:
    omada:
      rule: Host(`omada.atlantissrv.com`)
      entryPoints: [internal]
      service: omada
      tls: { certResolver: cf }
  services:
    omada:
      loadBalancer:
        servers:
          - url: https://10.0.10.x:8043   # confirm real MGMT IP
        serversTransport: omada-transport
  serversTransports:
    omada-transport:
      insecureSkipVerify: true   # controller uses its own self-signed cert
```

### 4. DNS

Split-horizon via Technitium: `jellyfin.atlantissrv.com` resolves to
`10.0.20.20` for internal clients (SERVERS/TRUSTED), and to Hecate's DMZ
address for anything resolving from outside. No fallback logic needed —
each client gets the right answer for its own network from the start.

### 5. Verifying it end to end

```bash
# From a container, confirm same-network resolution works and
# cross-network resolution doesn't:
docker exec jellyseerr getent hosts sonarr        # should return an IP
docker exec jellyseerr getent hosts qbittorrent   # should return nothing

# From Hecate, confirm the route reaches the backend:
curl -v https://requests.atlantissrv.com
```