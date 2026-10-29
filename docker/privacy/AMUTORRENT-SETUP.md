# aMuTorrent, Prowlarr and TRAWL: manual setup

**Purpose:** Configure the web interfaces **after** the Docker containers are running. Docker creates the services, but it does **not** create the aMuTorrent administrator, Prowlarr administrator, indexers, solver tags, API links or restricted user accounts.

**Start here:** [Docker service index](../README.md) · [Full VPN/Compose/DNS operations](AMUTORRENT-OPERATIONS.md)

This is a reproducible walkthrough for the inspected privacy stack. Substitute your own MagicDNS suffix, LAN IP and credentials. The application buttons may move between versions; use the application labels and connection values below. **Do not paste secrets into GitHub or chat.**

## Which steps are automatic?

| Component | Created by Docker | Must configure by hand |
| --- | --- | --- |
| Gluetun | VPN network namespace and firewall | Verify VPN egress and existing port settings |
| aMuTorrent | App on internal port 4000; persistent data/logs | First-run wizard, admin password, Transmission, Prowlarr, restricted users |
| Transmission | Existing RPC download engine on 9091 | Use existing RPC credentials in aMuTorrent |
| Prowlarr | Internal admin UI on 9696 | Forms login, indexer-proxy, 1337x indexer, API key |
| TRAWL | Optional browser solver on 8191 | Add a FlareSolverr-compatible proxy **in Prowlarr**; Docker alone cannot do this |
| Tailscale + Pi-hole/nginx | Remote HTTPS and local HTTPS, with host configuration | Register sidecar initially, verify login/DNS/TLS, schedule exported cert renewal |

## 1. Open the two web interfaces

**aMuTorrent (phone or computer):** Open `https://amutorrent.YOUR-TAILNET.ts.net`. On home Wi-Fi with Pi-hole DNS, the same hostname routes locally to nginx. Away from home, enable Tailscale and use the same URL. The aMuTorrent HTTPS endpoint is the user-facing application.

**Prowlarr (admin only):** Its host port must remain bound to `127.0.0.1:9696`, not the whole LAN. Choose **one** of these ways to administer it:

- **Phone, away from home:** Enable Tailscale, open your existing remote Mullvad Browser at `https://mullvad.YOUR-TAILNET.ts.net`, then in the **remote browser itself** visit `http://127.0.0.1:9696`. Mullvad Browser and Prowlarr share Gluetun's network namespace. That loopback address is **not** a URL for your phone's local Chrome browser.
- **Linux/desktop with SSH:** On your own computer run `ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:9696:127.0.0.1:9696 root@YOUR-SERVER-LAN-IP`, leave it running, and open `http://127.0.0.1:9696` on that computer. Requires the verified host loopback binding.

Never open Prowlarr directly to WAN or expose it as an unrestricted public web service.

## 2. In aMuTorrent: complete the first-run wizard

The aMuTorrent **Setup Wizard** is a manual application task, not a Docker installation step.

1. **Security:** Enable web authentication. Choose a strong administrator password. Passwords must have at least eight characters, including letters, digits and a special character. Finish setup and check an incognito/private window prompts for credentials before sharing access.
2. **Download Clients → Transmission:** Enable it and enter the values below. Use the username/password that already protect Transmission RPC. Click **Test**.

   | Field | Value in this Gluetun stack |
   | --- | --- |
   | Host | `127.0.0.1` |
   | Port | `9091` |
   | URL path | `/transmission/rpc` |
   | Username / password | Existing Transmission RPC credentials |
   | Use SSL | Off (internal HTTP on the shared network namespace) |

3. **Directories:** Keep data at `/usr/src/app/server/data` and logs at `/usr/src/app/server/logs`, matching the Compose bind mounts. Missing optional GeoIP data can be left disabled. Do not invent a directory outside the mounted paths.
4. **Integrations:** Prowlarr can be configured **after** completing section 3 below. Leave Sonarr and Radarr disabled unless actually in use; do not add dummy API keys.
5. **Review & Save:** Run available tests, save the wizard, and confirm aMuTorrent loads normally. Configuration is persisted to `/docker/privacy/amutorrent/data/config.json` on the inspected host.

**Host-specific permission note:** On the inspected OMV host, the data/log directory ACLs caused an `EACCES` when aMuTorrent ran as UID 1000. The verified fix was to run only aMuTorrent as `1001:1000`. Do not recursively loosen directory permissions or assume that UID applies to every server. See [operations](AMUTORRENT-OPERATIONS.md#why-uid-1001-is-intentional).

After initial setup, the same settings are editable in **aMuTorrent → Settings → BitTorrent Integration**.

## 3. In Prowlarr: secure its admin UI

1. Open Prowlarr using section 1.
2. In the initial authentication screen, select **Forms (Login Page)**.
3. Set **Authentication Required = Enabled**.
4. Leave **Allowed Hosts** blank unless you have a separately verified requirement to restrict it.
5. Set administrator username and a strong password; confirm and **Save**. Verify you can sign in again.

At this point Prowlarr is running, but it still has **zero search indexers** until you add them in the UI.

## 4. In Prowlarr: connect TRAWL for Cloudflare-protected sites

TRAWL implements a FlareSolverr-compatible API. On the inspected server the standalone trial uses `ghcr.io/germondai/trawl:1.9.3-baseline` with `--network container:gluetun`; it does not publish port 8191.

**First verify TRAWL's health locally on OMV:**

```bash
vpn_pid="$(docker inspect -f '{{.State.Pid}}' gluetun)"
nsenter -t "$vpn_pid" -n curl -fsS --max-time 10 http://127.0.0.1:8191/health
```

An OK response means the solver API is running, **not** that Prowlarr has saved its proxy or that 1337x works.

In **Prowlarr**, do the following manually:

1. Open **Settings → Indexer Proxies → + → FlareSolverr**. Enable Advanced settings if the timeout field is hidden.
2. Enter these values:

   | Prowlarr field | Value |
   | --- | --- |
   | Name | `TRAWL` |
   | Host | `http://127.0.0.1:8191` |
   | Tags | Create and **select** `cloudflare` |
   | Request Timeout | `180` seconds |

3. Click **Test**. A successful proxy test sends a request to `https://prowlarr.servarr.com/v1/ping` through TRAWL.
4. **Click Save.** Verify TRAWL now appears in the saved **Indexer Proxies** list. **A successful Test does not mean it was saved.**

The exact tag matters: Prowlarr uses a FlareSolverr-type proxy only when it detects Cloudflare **and** the indexer and proxy have a matching saved tag. An untagged proxy is disabled.

## 5. In Prowlarr: add the 1337x indexer

1. Open **Indexers → Add Indexer (+)**, search **1337x**, and select it.
2. Check its selected base URL (e.g. `https://1337x.to/`). Mirrors and site availability can change.
3. Under **Tags**, select the **same existing** `cloudflare` tag used by the saved TRAWL proxy. Do not merely type text without selecting/creating the tag.
4. Click **Test**, and if successful click **Save**.
5. Verify that **1337x is visible in the saved Indexers list**. An unsaved indexer is not active.

**Known failure:** `Unable to access 1337x.to, blocked by CloudFlare Protection.` This can mean an indexer or proxy wasn't saved, the tags do not match, Prowlarr isn't invoking TRAWL, the challenge could not be replayed, or the current VPN exit IP is rejected. Do not assume a Docker/VPN failure from that message alone.

**Live diagnostic failure (2026-10-29):** The Prowlarr API reported `1337x` enabled, with `Tags: []`, `Matching solver: False`, and one saved FlareSolverr-compatible proxy. Both `a christmas carol` and `ubuntu` returned **0** direct Prowlarr API search results. This can happen even when 1337x has a green indexer status check and aMuTorrent's Prowlarr API connection passes: the saved indexer **still has no matching proxy tag**.

**Fix using Prowlarr's web UI:** Go to **Indexers**, use the **wrench icon** on the far right of the **1337x** row, select the existing `cloudflare` tag in **Tags**, and **Save**. Then confirm **Settings → Indexers → Indexer Proxies → TRAWL** has that identical *selected and saved* tag. Re-test 1337x and run a search in Prowlarr itself before searching through aMuTorrent. Saving the tag on the indexer is separate from enabling the indexer. An indexer enabled with no tags is not linked to TRAWL.

**Check the distinction immediately after clicking Test:**

```bash
docker logs --since 5m trawl 2>&1 | grep -E 'request.start|request.success|request.failure|tier.complete' | tail -n 25
```

- **Only `prowlarr.servarr.com/v1/ping`**: Prowlarr tested the **proxy**, not 1337x.
- **A fresh request targeting 1337x**: Prowlarr invoked the solver. Check whether the subsequent indexer test saved successfully.
- **No new TRAWL request despite a fresh 1337x test**: Recheck that **both items are saved** and carry the same selected tag.
- **Solver returns 200 but Prowlarr still fails**: Could be a challenge-cookie or HTTP-client replay failure; keep the browser test and indexer test separate. Do not claim success until Prowlarr can search 1337x.

**Observed on OMV, 2026-10-29:** Direct TRAWL `/v1` testing solved a Cloudflare challenge, obtained a `cf_clearance` cookie and returned HTTP 200 for 1337x; Prowlarr's TRAWL proxy-ping succeeded. The user then showed 1337x **saved and enabled with a green status check**, and reported that the **aMuTorrent ↔ Prowlarr API integration is set up and working**. **Actual search results and a completed aMuTorrent → Transmission handoff remain unverified.**

## 6. In aMuTorrent: finish Prowlarr integration

After Prowlarr has at least one saved, working indexer:

1. In **Prowlarr → Settings → General**, reveal/copy its **API Key** privately. Do not share it in messages or source control.
2. Open **aMuTorrent → Settings → BitTorrent Integration → Prowlarr**.
3. Enable the integration, set **Prowlarr URL** to `http://127.0.0.1:9696`, and paste the API key.
4. Click **Test**, then **Save**. Keep Transmission enabled as the download client.
5. Search a legal redistributable torrent, such as a Linux ISO, and send it to Transmission. Verify the transfer exists in Transmission and behaves as expected.

aMuTorrent's general configuration documents both Transmission and Prowlarr, but the older Prowlarr-specific integration document refers to qBittorrent/rTorrent. Therefore **the Transmission search-to-download handoff remains a compatibility test**, not an assumed success.

## 7. In aMuTorrent: add a restricted user

Only after verifying the administrator login and search flow:

1. Open **aMuTorrent → Settings → User Management → Add User**.
2. Create a separate account and select **Custom** capabilities (not the **Read Only** preset, which includes viewing all downloads). Enable `search` and `add_downloads`; optionally `pause_resume`, `remove_downloads` and `view_history` depending on how much control you want that user to have.
3. **Do not grant admin, view-all, edit-all, manage-system-configuration or logs permissions** to the restricted account.
4. Test in a private session that the account can search/add but cannot change other users' downloads, global settings or Prowlarr administration.

Sharing a Tailscale service requires appropriate tailnet access rules. Application permissions do **not** create separate storage quotas or isolate the underlying Transmission downloads.

## 8. Final checks and remaining manual work

- [ ] aMuTorrent prompts for authentication in a private session
- [ ] Transmission RPC **Test** passes inside aMuTorrent
- [x] Prowlarr Forms authentication saved and TRAWL proxy ping responded successfully
- [ ] Confirm by reading the saved configuration that both TRAWL and 1337x have the selected `cloudflare` tag
- [x] 1337x saved/enabled with a green status check in Prowlarr
- [ ] Search 1337x from Prowlarr/aMuTorrent and verify actual results
- [x] aMuTorrent's Prowlarr API connection reported working by the user
- [ ] Send a legal test torrent from aMuTorrent to Transmission and verify it arrives
- [ ] Restricted account permissions are actually enforced
- [ ] Local Pi-hole HTTPS and remote Tailscale HTTPS are each verified
- [ ] Exported Tailscale certificate renewal has been dry-run checked/scheduled

**This GitHub branch is not a live-server deployment.** The current standalone TRAWL container is not Compose-managed; the optional `compose.trawl.yml` provides a future Compose version. Do **not** run it over an existing container named `trawl`. The migration must be planned after inspecting the live privacy project and all active overlays; do not remove the existing container just to make an example work.

Official references: [aMuTorrent configuration](https://got3nks.github.io/amutorrent/docs/configuration/), [Prowlarr proxy settings](https://wiki.servarr.com/prowlarr/settings), [TRAWL FlareSolverr-compatible API](https://github.com/germondai/trawl).
