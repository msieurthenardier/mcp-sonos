# Leg: 03-anonymize-lan-ips

**Status**: completed
**Flight**: [Documentation Cleanup](../flight.md)

## Objective
Replace real LAN IPs and subnet references in `poc/debug_play.py` and `CLAUDE.md` with `192.168.1.x` placeholders consistent with `.env.example` (Finding F10 from [Maintenance Report 2026-05-18](../../../../maintenance/2026-05-18.md)).

## Context
- `poc/debug_play.py:24` hardcodes `TARGET_IP = "192.168.86.53"`.
- `CLAUDE.md:147` documents the user's actual `192.168.86.0/24` subnet, host IP (`192.168.86.38`), and speakers (`.49`/`.50`/`.51`/`.52`/`.53`).
- This is a public repo. RFC1918 → no remote attack surface, but leaks network topology and assists footprinting if combined with other public info.
- `.env.example` uses `192.168.1.x` placeholders. House style is to anonymize.
- The maintainer's actual configuration doesn't need to be rewritten — the active firewall rule and live hardware addresses are unaffected. This is a docs-only change.

## Inputs
- `poc/debug_play.py:24`
- `CLAUDE.md:147` (and any other places real IPs leak — grep audit confirms)

## Outputs
- All real LAN IPs replaced with `192.168.1.x` family placeholders
- No real subnet (`192.168.86.x`) remaining in any tracked file

## Acceptance Criteria
- [x] `git grep "192.168.86"` returns no hits (in non-historical paths — only `missions/` retains evidence snapshots, which is intentional)
- [x] `poc/debug_play.py:24` uses a placeholder (e.g., `TARGET_IP = "192.168.1.53"`)
- [x] `CLAUDE.md` documents a placeholder subnet/IPs consistent with `.env.example`
- [x] No real hostname/MAC/UID leakage discovered while replacing IPs (grep audit at conclusion)

## Verification Steps
- `git grep -n "192\.168\.86"` returns nothing.
- `git grep -n "192\.168\.1\." poc/debug_play.py CLAUDE.md .env.example` shows consistent usage of the placeholder family.
- The maintainer's live config (in their actual environment) is unchanged; runs unaffected.

## Implementation Guidance

1. **`poc/debug_play.py:24`**: change `TARGET_IP = "192.168.86.53"` → `TARGET_IP = "192.168.1.53"` (or pick any unused address in 192.168.1.0/24; consistency with `.env.example` matters more than the specific octet).

2. **`CLAUDE.md:147`** and surrounding context: anonymize the speaker IP listing and host IP. Suggested rewrite:
   ```
   - **The user runs from WSL2 with mirrored networking** (LAN
     192.168.1.0/24, host 192.168.1.50, 5 Connect:Amp speakers at
     .51/.52/.53/.54/.55 in the example). The Windows Firewall rule
     "WSL-Sonos-Audio" is already in place on their machine.
   ```
   Adjust the placeholder octets to whatever's most readable.

3. **Audit other files**: `git grep "192.168" -- ":!**/.venv/**"` to catch any other leaks. README and `.env.example` should already use placeholders; double-check.

4. **Don't accidentally touch the maintainer's running config**: this leg edits tracked source/docs only.

## Files Affected
- `poc/debug_play.py`
- `CLAUDE.md`
- Any other tracked file containing real LAN IPs (grep audit)

## Edge Cases
- **README.md "WSL2 specifics" section** (around line 127) already uses `192.168.1.0/24` as the example CIDR. Confirm consistency.
- **`.env.example`** comment block already uses placeholder IPs. Confirm consistency.

---

## Post-Completion Checklist

- [x] All acceptance criteria verified
- [x] Final grep audit clean
- [x] Update `../flight-log.md`
- [x] Set this leg's status to `completed`
- [x] Check off in `../flight.md`
