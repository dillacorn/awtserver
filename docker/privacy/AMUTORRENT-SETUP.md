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

## 4. In Prowlarr: add the TRAWL Cloudflare proxy

TRAWL is a FlareSolverr-compatible service on `http://127.0.0.1:8191` inside Gluetun. Installing it **does not automatically configure Prowlarr**.

1. Go to **Settings → Indexers → Indexer Proxies → + → FlareSolverr**.
2. Set **Name:** `TRAWL`; **Host:** `http://127.0.0.1:8191`; **Request Timeout:** `180` seconds (Advanced).
3. Under **Tags**, create and **select** `cloudflare`.
4. Click **Test**, then **Save**. Confirm TRAWL appears in the saved proxy list.

## 5. In Prowlarr: add or fix 1337x

1. Go to **Indexers → Add Indexer (+) → 1337x**, or use the **wrench icon** on an existing 1337x row.
2. Under **Tags**, **select the same `cloudflare` tag** as TRAWL. The tag must appear as selected, not merely typed.
3. Click **Test → Save**, then try a search in **Prowlarr → Search** and in aMuTorrent.

**Important:** Both the **saved TRAWL proxy** and **saved 1337x indexer** must have the same `cloudflare` tag. A green/enabled 1337x indexer alone is insufficient. On the inspected OMV host, the indexer had no tags and returned zero results; selecting and saving the tag fixed searching (**user-confirmed, 2026-10-29**).

If search still fails, read recent TRAWL activity after a fresh 1337x test:

```bash
docker logs --since 5m trawl 2>&1 | grep -E 'request.start|request.success|request.failure' | tail -n 20
```

A request to `prowlarr.servarr.com/v1/ping` only verifies TRAWL's proxy test, not 1337x. See [operations](AMUTORRENT-OPERATIONS.md) for deeper VPN/Cloudflare troubleshooting.

**Other indexers:** Try Knaben or Torrent Downloads through **Add Indexer**. EXT.to is not included in the current native Prowlarr list; Generic Torznab works only with a compatible API or third-party gateway. Add the `cloudflare` tag to other indexers **only if** they require TRAWL.

## 6. In aMuTorrent: finish Prowlarr integration

After Prowlarr has at least one saved, working indexer:

1. In **Prowlarr → Settings → General**, reveal/copy its **API Key** privately. Do not share it in messages or source control.
2. Open **aMuTorrent → Settings → BitTorrent Integration → Prowlarr**.
3. Enable the integration, set **Prowlarr URL** to `http://127.0.0.1:9696`, and paste the API key.
4. Click **Test**, then **Save**. Keep Transmission enabled as the download client.
5. Search a legal redistributable torrent, such as a Linux ISO, and send it to Transmission. Verify the transfer exists in Transmission and behaves as expected.

aMuTorrent's general configuration documents both Transmission and Prowlarr, but the older Prowlarr-specific integration document refers to qBittorrent/rTorrent. Therefore **the Transmission search-to-download handoff remains a compatibility test**, not an assumed success.

## 7. In aMuTorrent: create a limited but usable account

**Goal:** A separate non-admin can search Prowlarr, add torrents through Transmission, organize their own downloads and pause/resume them, **without** managing other users or the server.

1. Sign in as an admin. Open **Settings → User Management → Add User** (or **Edit User** for an existing account).
2. Give the person their own username and password, keep **Admin** **off**, and choose **Custom** (not **Full** or **Read-only**).
3. Select the following checkboxes and **Save Changes**:

   | Enable | Leave disabled |
   | --- | --- |
   | **Search indexers** (`search`) | **Remove downloads** (`remove_downloads`), unless the user should delete their own |
   | **Add downloads** (`add_downloads`) | **Move files**, **Rename files** |
   | **Pause / resume** (`pause_resume`) | **Manage categories** |
   | **Assign categories** (`assign_categories`) | **Set rating & comment** (aMule-specific; unnecessary for BitTorrent) |
   | | **View history**, **Clear history**, **View logs** |
   | | **View shared files**, **View uploads**, **View statistics** |
   | | **Manage ED2K servers** |
   | | **View all users' downloads**, **Edit all users' downloads** |

4. Test the account in a **private browser session**: sign in, search via **Prowlarr**, add a legal test torrent, confirm it appears in **their** Downloads, and pause/resume it. Confirm that admin Settings and other users' downloads are not visible/editable.
5. Optionally allow **Remove downloads** to let them remove their **own** torrents. Check whether the removal dialog also deletes downloaded data before granting it.

**Important privacy detail (aMuTorrent v3.9.8):** The **View history** permission permits the history API, which does **not** filter entries by the logged-in owner's ID; leave it off if other users' history should be private. **Clear history** permits deletion of history entries. **Manage categories** edits global categories, while **Assign categories** only permits assigning an existing category to a download. The **Read-only** preset grants **View all users' downloads**, so do not use it for a private restricted account. See [upstream user permissions](https://github.com/got3nks/amutorrent/blob/v3.9.8/docs/USERS.md) and [history route](https://github.com/got3nks/amutorrent/blob/v3.9.8/server/modules/historyAPI.js).

**Limits:** aMuTorrent's user permissions do **not** create disk quotas, separate Transmission storage or enforce access controls on Transmission's own web UI. Protect Transmission credentials separately, and allow the person only the intended HTTPS service in your Tailscale policy.

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
