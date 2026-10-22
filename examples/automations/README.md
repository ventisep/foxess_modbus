# PQ1 remote-control automation examples

[PQ1_REMOTE_OVERRIDES.yaml](PQ1_REMOTE_OVERRIDES.yaml) is a Home Assistant
**package**, not a dashboard card or an individual automation. It supplies two
example automations, helpers and a short shared script. It uses existing remote
controls; it never writes scheduler records, scheduler enable or Basic Work Mode.
The optional watchdog number requires this version of the integration.

## Install

1. Update the integration and reload it. Confirm the PQ1 controls listed below exist.
2. Save the package as `/config/packages/foxess_remote_overrides.yaml`.
3. Enable packages in `configuration.yaml`, merging with your existing `homeassistant`
   section rather than creating a second one:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

4. Check configuration and restart HA. **Automatic charge and discharge start
   disabled and are disabled again on HA restart.** Configure and inspect the
   helpers before enabling either direction.
5. Add [the example card](../lovelace/PQ1_REMOTE_OVERRIDES_CARD.yaml) to a dashboard
   using **Edit → Add card → Manual**. It uses built-in cards only. You can instead
   put any of these helpers and sensors on your own cards.

The default integration prefix is `solar_inverter`. If yours differs, edit
`input_text.foxess_example_prefix` and the two direct integration entity IDs in
the card. For individually renamed entities, edit the package's entity-building
templates as well. Do not change the `foxess_example_` helper IDs independently.

Required integration entities, using that prefix:

- `select.solar_inverter_force_charge_mode`
- `select.solar_inverter_remote_control_target`
- `number.solar_inverter_force_charge_power`
- `number.solar_inverter_force_discharge_power`
- `number.solar_inverter_remote_control_watchdog_timeout`
- `sensor.solar_inverter_battery_soc`, `max_soc`, `min_soc`, `min_soc_on_grid`
- `sensor.solar_inverter_current_work_mode`
- For the schedule display: `binary_sensor.solar_inverter_scheduler_enabled`,
  `sensor.solar_inverter_schedule_entries`, `sensor.solar_inverter_remaining_time`,
  and `sensor.solar_inverter_manual_work_mode` (Basic Work Mode).

The YAML `initial` entries are editable example defaults: HA reapplies them at
startup. After your first setup, remove `initial` from time, number and source/prefix
helpers if you want their last UI-entered values restored instead. Keep the
explicit `initial: false` on enable switches for the documented opt-in startup
behaviour. Internal owner/completion helpers deliberately restore their states.

## Charging

Enable **Use Octopus off-peak signal** and **Enable automatic charging**.
The supplied cheap-electricity entity is:

```text
binary_sensor.octopus_energy_electricity_23p2005371_2600002633950_off_peak
```

Verify that entity exists and that `on` means the tariff opportunity you intend.
It is not necessarily an ad-hoc free-electricity or dispatch signal. Replace the
source helper if you want a different Octopus event.

Alternatively enable the charge time window, or enable both sources. They are
combined with **OR**: control remains eligible while either source is active.
Equal start/end times disable that window. Overnight windows are supported, using
HA local wall-clock time; the stop boundary is exclusive.

Set charge power and target SOC. Charging stops at the lower of the requested SOC
and the inverter's configured maximum SOC, or when all enabled charging sources
end. Reaching target latches completion until that opportunity ends; a subsequent
small SOC decrease does not repeatedly restart charging. Releasing remote control
allows the inverter's schedule/Basic mode to operate, which can change SOC again.

## Discharging

Enable a discharge time window, or supply an export-price entity in
`input_text.foxess_example_export_price_entity` and enable **Use export price
signal**. Price comparison uses **pence/kWh**, strictly above the threshold.
For a sensor in GBP/kWh, supply a template sensor multiplying by 100. No price
source is assumed or enabled automatically.

Set **Required SOC for rest of day**. Optionally put a forecast sensor entity ID
in `input_text.foxess_example_reserve_entity`; it must already represent **required
battery SOC as a percentage**, not kWh or a percentage of excess energy. A blank
source uses the manual helper; an unavailable or out-of-range forecast blocks
or releases discharge. This package does not calculate a forecast.

Discharge starts above reserve plus the start margin, and continues until reserve
is reached or the opportunity ends. The stop threshold also respects the higher
of the configured inverter minimum SOC and on-grid minimum SOC. Charge opportunities
have priority, including when their SOC target is already met; the example never
uses cheap periods to run a price-triggered discharge.

## Target measure, watchdog and operation

Power is a positive kW value; direction comes from the automation. **Target power
measure** determines whether that value refers to inverter AC power, battery power
or net CT export/import. It does not necessarily equal grid power. The control is
the existing integration selector, shared with manual remote-control use.

**Remote Control Watchdog Timeout** is a persisted integration preference:

- `0`: automatic, twice the configured polling interval.
- Positive seconds: at least twice the polling interval, up to 65,535 seconds
  (18 h 12 min 15 s representable maximum). PQ1's accepted upper limit is untested.
- It is applied when enabling control, or on the next manager poll if changed
  during a session. It does not enable control by itself.
- PQ1 saves the inverter's previous timeout and restores it after disabling;
  the preference itself is retained for subsequent sessions.

A short timeout releases stale commands sooner if connectivity fails. A long
one may continue the last command while disconnected. **HA cannot enforce the
example's SOC, price or time stops during that outage**, and a pending stop is
only retried when services/connectivity recover. Actual PQ1 watchdog expiry and
recovery still need on-device verification. Do not use this timeout as a session
stop timer, or use zero to mean unlimited operation.

Both automations call one queued script, recalculating current state rather than
replaying stored commands. Conditions are checked every 15 seconds and on relevant
helper/opportunity changes; actual SOC resolution also depends on inverter polling.
The example declines to take over an existing remote session visible through the
integration. Changing the remote direction selector manually relinquishes example
ownership and blocks restarting that opportunity. There is no atomic lock against
other integrations, the app or external Modbus writers: use one controlling system.

**Stop example overrides** disables both example enable switches and releases a
session owned by the example. It does not stop unrelated manual remote control.
On HA restart the enable switches are off; this package does not automatically
resume. An old physical command may remain until watchdog expiry because the
manager's in-memory ownership is lost. The card distinguishes requested operation
from telemetry-inferred remote operation; neither proves the requested watts
are physically achievable. Failed actions appear in HA automation/script traces.

Stored schedules are never changed. The card shows the underlying current period
or Basic mode, with uncertainty for unavailable/overlapping schedules and scheduled
SOC fallback. It highlights the **currently overridden** period, not a prediction
of future price-driven events. Test across a scheduled boundary before relying on
that priority with a new firmware version.

References: [HA packages](https://www.home-assistant.io/docs/configuration/packages/),
[automation triggers](https://www.home-assistant.io/docs/automation/trigger/),
[script syntax](https://www.home-assistant.io/docs/scripts/).
