# Clash Verge IP Checker Auto

[English](README.md) | [简体中文](README.zh-CN.md)

A local node checking and cleanup tool for Clash Verge Rev. It reads local profiles, checks exit-IP quality, filters results, and exports a new checked YAML.

> Use it only on your own computer or a trusted LAN. Do not expose it to the public internet.

## Preview

![Node checking and export interface](docs/assets/screenshots/overview.png)

![Network-impact confirmation before checking](docs/assets/screenshots/network-impact-confirmation.png)

The screenshots use demo profiles, demo nodes, and documentation-reserved IP addresses.

## Features

- Discovers the Clash Verge Rev data directory, profiles, and External Controller settings.
- Supports Remote and Local main profiles while listing other fragments separately.
- Uses IPPure fast checks by default, with an optional browser mode for additional data.
- Reuses successful results for the same exit IP for up to 14 days and deduplicates by exit IP.
- Selects completed nodes with risk scores at or below 30% by default.
- Exports a new `*_checked.yaml` and provides an import entry for Clash Verge.

## Safety

- The UI verifies External Controller and explains the host-wide network impact before checking.
- Checks temporarily change Clash mode and proxy selection. Downloads, sync jobs, SSH sessions, browsers, and API clients may change IP or briefly disconnect.
- Completion, stop, and error paths restore the previous proxy selections and mode.
- Non-current profiles can be loaded temporarily; the Clash Verge runtime configuration is restored afterward.
- Exports do not overwrite the source profile, edit `profiles.yaml`, or automatically activate the imported profile.

## Requirements

- Python 3.10 or newer.
- Clash Verge Rev installed and running.
- Clash Verge Rev External Controller enabled.
- A local YAML-backed Remote or Local main profile.

Keep the Controller bound to localhost when possible, for example `127.0.0.1:9097`. If it uses a secret, keep the secret local; the tool can read it without displaying it in the UI.

## Quick Start

### macOS

```bash
./run_mac.command
```

### Windows

```bat
run_windows.bat
```

The launchers create or repair the project-local `.venv` and install dependencies when needed. The Web UI uses port 8080 by default; if it is occupied, the launcher selects and reuses an available port in `18080-18120`. Open the actual URL printed in the terminal.

### Manual Start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python web.py
```

Browser mode also requires Chromium:

```bash
.venv/bin/python -m playwright install chromium
```

Use `CLASH_CHECKER_PORT` to require a fixed port and `CLASH_VERGE_HOME` to select the Clash Verge Rev data directory. Startup fails safely when an explicit port is already occupied.

## Workflow

1. Start Clash Verge Rev and confirm that External Controller is available.
2. Start this tool and select a Remote or Local main profile.
3. Keep the proxy group as `auto`, or enter the actual selector name.
4. Select `Switch and check`, then confirm or cancel after reviewing the network-impact warning.
5. Review the node results and default selection.
6. Select `Export selected`.
7. Import the checked profile on the first export; refresh the existing checked profile after later exports.
8. Review and enable the imported profile manually in Clash Verge.

`Refresh and switch check` reads the latest Remote profile content without writing back to the source file. Advanced settings can bypass the 14-day IP cache for a fresh check.

## LAN Access

On macOS:

```bash
./run_lan_mac.command
```

On Windows:

```bat
run_lan_windows.bat
```

Use LAN mode only on a trusted network. The page controls Clash Verge on the computer running this service, not Clash Verge on the browser device. The service has no login layer and must not be exposed to the public internet.

For a fixed LAN address, set both `CLASH_CHECKER_PORT` and `CLASH_CHECKER_PUBLIC_BASE_URL` with matching ports.

## Local Data and Privacy

| Path | Contents | Git state |
| --- | --- | --- |
| `exports/` | Exported checked YAML files | Ignored |
| `data/results.sqlite3` | Local profile and node results | Ignored |
| `sync/ip_reputation_cache.json` | Exit-IP reputation cache | Ignored |
| `sync/ip_reputation_cache.example.json` | Empty cache template | Tracked |
| `.runtime/` | Port, log, and temporary configuration files | Ignored |

Do not commit real subscription YAML, `profiles.yaml`, exported files, API secrets, provider URLs, tokens, or screenshots containing real profile information.

Adding an ignore rule does not remove a real IP cache from existing commits. Clean the related history or publish from an audited new history before making the repository public.

## Troubleshooting

### No profiles found

Confirm that Clash Verge Rev has been opened at least once. Enter a custom data directory in the UI or set `CLASH_VERGE_HOME`.

### Cannot connect to External Controller

Confirm that Clash Verge Rev is running, External Controller is enabled, and the Controller address and secret are correct.

### Proxy group cannot be detected

Enter a selector that can switch to the nodes being checked, such as `GLOBAL`, `Proxy`, or the proxy-group name used by the profile.

### Imported profile is not active

Importing creates the checked profile but does not activate it. Review, refresh, and enable it manually in Clash Verge.

## License and Attribution

This project is licensed under [GPL-3.0](LICENSE) and is adapted from [tombcato/clash-ip-checker](https://github.com/tombcato/clash-ip-checker). It is not an official upstream release. See [NOTICE](NOTICE) for attribution.
