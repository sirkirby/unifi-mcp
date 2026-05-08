# DPI Category Reference

Deep Packet Inspection (DPI) allows the UniFi controller to identify and classify traffic by application or service, independent of port number. Firewall rules can target DPI categories to block or shape specific applications.

> **Important:** DPI category IDs are controller-specific and may vary across firmware versions. This document lists common category and application names. Call `unifi_get_dpi_stats` to discover the exact category IDs available on the user's controller before creating DPI-based rules.

---

## How DPI Rules Work

DPI rules inspect the traffic payload (Layer 7) to identify the application. This is more reliable than port-based blocking because many applications use non-standard ports or switch ports to evade rules.

**Important:** The V2 zone-based firewall surface (`unifi_create_firewall_policy`) does **not** accept a `dpi_category_id` field — its source/destination are strictly zone- + IP/network/object-based. For DPI-category-based filtering, use the content-filter or traffic-rule tooling that supports DPI:

1. Call `unifi_get_dpi_stats` to get the list of available categories and their IDs on this controller.
2. Find the category ID for the application you want to block.
3. Apply the category via `unifi_update_content_filter` (DPI-aware content filtering profile) or the appropriate traffic-rule tool.

For a coarse "block this network from reaching the internet" rule (no DPI), use `unifi_create_firewall_policy` with a zone-based `source` (the target network's zone) and `destination` zone set to External.

---

## Common Application Categories

### Social Media

| Application | Category | Notes |
|-------------|----------|-------|
| TikTok | Social Media / Short Video | High bandwidth; popular parental control target |
| Instagram | Social Media | Owned by Meta; shares infrastructure with Facebook |
| Facebook | Social Media | Includes Messenger traffic |
| Twitter / X | Social Media | Formerly Twitter |
| Snapchat | Social Media | Heavy use of ephemeral media uploads |
| Pinterest | Social Media | Image-heavy; significant bandwidth |
| Reddit | Social Media / Forums | |

### Video Streaming

| Application | Category | Notes |
|-------------|----------|-------|
| YouTube | Video Streaming | Also used by YouTube Music |
| Netflix | Video Streaming | High bandwidth; streams on port 443 |
| Disney+ | Video Streaming | Includes Hulu on some controllers |
| Twitch | Video Streaming / Gaming | Live streaming; very high bandwidth |
| Spotify | Audio Streaming | Uses both TCP 443 and UDP |
| Apple TV+ | Video Streaming | |
| Amazon Prime Video | Video Streaming | |

### Gaming

| Application | Category | Notes |
|-------------|----------|-------|
| Steam | Gaming | Large file downloads; game traffic |
| Xbox Live | Gaming | Microsoft gaming network |
| PlayStation Network | Gaming | Sony PSN; also handles PS Store downloads |
| Epic Games | Gaming | Includes Fortnite traffic |
| Battle.net | Gaming | Blizzard games (WoW, Overwatch, Diablo) |
| Roblox | Gaming | Popular with younger audiences |
| Minecraft | Gaming | Uses non-standard ports |

### Messaging and Communication

| Application | Category | Notes |
|-------------|----------|-------|
| WhatsApp | Messaging / VoIP | Includes voice and video calls |
| Telegram | Messaging | Includes file sharing via Telegram |
| Discord | Messaging / VoIP | Gaming-adjacent; voice channels use significant bandwidth |
| Signal | Messaging | Privacy-focused; may appear as generic HTTPS |
| Skype | VoIP / Messaging | Microsoft-owned |
| Zoom | Video Conferencing | Prioritize rather than block in work environments |
| Microsoft Teams | Video Conferencing | |

### File Sharing and P2P

| Application | Category | Notes |
|-------------|----------|-------|
| BitTorrent | P2P / File Sharing | Protocol-level detection; covers all BitTorrent clients |
| uTorrent | P2P / File Sharing | BitTorrent client; covered by BitTorrent category |
| qBittorrent | P2P / File Sharing | BitTorrent client; covered by BitTorrent category |
| eMule | P2P / File Sharing | eDonkey/Kademlia protocol |
| Usenet | Usenet / File Sharing | NZB binary downloads |

### VPN and Proxy Services

| Application | Category | Notes |
|-------------|----------|-------|
| NordVPN | VPN | May also be detected under generic VPN category |
| ExpressVPN | VPN | |
| Mullvad | VPN | Privacy-focused; WireGuard/OpenVPN |
| Cloudflare WARP | VPN / Proxy | Uses WireGuard protocol |
| OpenVPN | VPN | Protocol-level detection |
| WireGuard | VPN | Protocol-level detection |
| Tor | Anonymizer / Proxy | Onion routing; often listed under Anonymizers |

---

## Category Groups (Higher-Level Blocking)

Some controllers expose top-level category groups that block entire families of applications in a single rule:

| Group | What It Covers |
|-------|---------------|
| Social Media | All social networking applications |
| Video Streaming | All video and audio streaming services |
| Gaming | Online gaming platforms and stores |
| P2P / File Sharing | BitTorrent, eDonkey, and similar protocols |
| VPN / Proxy | Commercial VPN services and proxy tools |
| Anonymizers | Tor, proxy services that obscure identity |

Using a group is preferred over listing individual applications — it catches new services in the same category without requiring rule updates.

---

## Checking Available Categories on a Controller

Controller firmware determines which DPI signatures are available. Always confirm before building rules:

```
Tool: unifi_get_dpi_stats
```

The response includes:
- `category_id` — the numeric ID to use in rules
- `name` — human-readable category name
- `app_id` — (if supported) application-level ID for finer control
- `bytes` / `tx_bytes` / `rx_bytes` — current traffic stats per category

If a specific application is not listed, block by category group or consider port-based rules as a fallback.

---

## DPI Limitations

- DPI inspection requires the controller to have active DPI enabled (Settings > Traffic Management > DPI)
- Encrypted traffic (HTTPS, QUIC) is identified by TLS SNI and certificate metadata, not payload content
- Applications that use IP pinning or CDNs (e.g., Netflix) may require IP group rules in addition to DPI rules
- DPI may not detect applications tunneled inside VPNs — block VPN protocols first if needed
