# FoxESS - Modbus

[![GitHub Release][releases-shield]][releases]
[![BuyMeCoffee][buymecoffeebadge]][buymecoffee]
[![Community Forum][forum-shield]][forum]

\*\* **This project is not endorsed by, directly affiliated with, maintained, authorized, or sponsored by FoxESS** \*\*

## Introduction

A Home Assistant custom component which communicates with FoxESS H-series inverters and derivatives without using FoxESS's cloud.

This means that you're not reliant on FoxESS's cloud infrastructure, so HA keeps working when the cloud goes down.
You can also read solar production etc in real-time, rather than once every 5 minutes.

Depending on your inverter model, you can also set charge periods, work mode, min/max SoC.
See [Supported Features](https://github.com/nathanmarlor/foxess_modbus/wiki/Supported-Features).

Supported models:

- FoxESS H1 (including AC1, AIO-H1 and G2)
- FoxESS H3 (including AC3 and AOI-H3)
- FoxESS H3 PRO
- FoxESS P1
- FoxESS PQ1 (read-only monitoring and experimental diagnostics)
- FoxESS KH
- Kuara H3
- Sonnenkraft SK-HWR
- STAR
- Solavita SP
- a-TroniX AX
- Enpal
- 1KOMMA5°

PQ1 support is based on register observations from a PQ1-8.0 using native LAN
Modbus TCP (port 502, device ID 247), with readings compared against the Fox app.
Grid CT, Feed-in and Grid Consumption reuse the confirmed `31049–31050` pair.
Raw watts are positive for import and negative for export; Grid CT follows the
integration's positive-export convention in kW, with positive directional
Feed-in and Grid Consumption readings. Feed-in power remains experimental,
disabled by default, along with BMS Charge Rate and BMS Discharge Rate.
PV Power sums the four verified string readings. Load Power uses the confirmed
`39225–39226` pair; alternative load and battery-power pairs are available as
disabled diagnostic sensors. `39237–39238` is a battery-power comparison;
`39248–39249` is an experimental net inverter AC output candidate. The unresolved
`39256–39257` has an experimental reactive-power interpretation using the shared
newer-model map, with raw words retained. `39270–39271` remains raw-only.
Solar Generation Total/Today use the verified
`39601–39604` pairs at 0.01 kWh per count. Verified solar, battery charge/discharge, feed-in,
purchased-energy and load-energy counters are enabled with energy statistics.
Battery Voltage is also confirmed and uses the shared normal sensor description.
Battery charge/discharge energy can differ from the app; measurement boundaries
remain unresolved, and the inverter-reported values are preserved unchanged.
Product support remains read-only.

PQ1 readings with provisional register interpretations have an **Experimental**
suffix and are disabled by default, along with raw register diagnostics. Enable
these individually to compare values; experimental sensors include raw register
attributes and do not produce long-term statistics or Energy dashboard inputs.
Manual Work Mode reads `41000`: `0` Self Use, `1` Feed-in Priority, `2` Backup,
`3` Peak Shaving. A diagnostic enum reads the parallel `49203` codes `1–4`.
Unknown codes retain a `raw_value` attribute. The always-zero `31014` and the
capacity-like `37632` are raw diagnostics rather than grid-power or remaining-
energy sensors. Scheduler records can
be inspected with the existing `foxess_modbus.read_registers` action in small
holding-register reads. The generic register-write action remains available,
but PQ1 write semantics have not been established.

You will need a direct connection to your inverter.
In most cases, this means buying a modbus to ethernet/USB adapter and wiring this to a port on your inverter.
See the documentation for details.

**[See the wiki](https://github.com/nathanmarlor/foxess_modbus/wiki) for how-to articles and FAQs.**

## Installation

[![Quick installation link](https://my.home-assistant.io/badges/hacs_repository.svg)][my-hacs]

Migrating from StealthChesnut's HA-FoxESS-Modbus? [Read this](https://github.com/nathanmarlor/foxess_modbus/wiki/Migrating-from-HA-FoxESS-Modbus).

Recommended installation is through [HACS][hacs]:

1. Either [use this link][my-hacs], or navigate to HACS integration and:
   - 'Explore & Download Repositories'
   - Search for 'FoxESS - Modbus'
   - Download
2. Restart Home Assistant
3. Go to Settings > Devices and Services > Add Integration
4. Search for and select 'FoxESS - Modbus' (If the integration is not found, empty your browser cache and reload the page)
5. Proceed with the configuration

## Usage

1. Navigate to Settings -> Devices & Services to find:

![Usage](images/usage.png)

2. Select '1 device' to find all Modbus readings:

![Example](images/example.png)

## Charge Periods

If your inverter supports setting charge periods, you can use install the [Charge Periods lovelace card](https://github.com/nathanmarlor/foxess_modbus_charge_period_card):

![Charge Periods](images/charge-periods.png)

## Services

### Write Service

A service to write any modbus address is available, similar to the native Home Assistant service. To use a service, navigate to Developer Tools -> Services and select it from the drop-down.

![Service](images/svc-write.png)

### Update Charge Periods

Updates one of the two charge periods (if supported by your inverter).

![Service](images/svc-charge-1.png)

### Update All Charge Periods

Sets all charge periods in one service call. The service "Update Charge Period" is easier for end-users to use.

![Service](images/svc-charge-2.png)

---

[buymecoffee]: https://www.buymeacoffee.com/nathanmarlor
[buymecoffeebadge]: https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow.svg?style=for-the-badge
[hacs]: https://hacs.xyz
[my-hacs]: https://my.home-assistant.io/redirect/hacs_repository/?owner=nathanmarlor&repository=foxess_modbus&category=integration
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[releases-shield]: https://img.shields.io/github/release/nathanmarlor/foxess_modbus.svg?style=for-the-badge
[releases]: https://github.com/nathanmarlor/foxess_modbus/releases
