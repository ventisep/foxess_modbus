# FoxESS PQ1 Development Notes

## Purpose

Engineering context for adding FoxESS PQ1 support to
`nathanmarlor/foxess_modbus`. Treat controlled PQ1 evidence as stronger
than cross-model inference. GitHub user **`ventisep` is the
tester/author of this work**, so those posts are not independent
corroboration.

## Four-PR roadmap

### Scope amendment agreed on 2026-10-01

The user expanded PR1 to support testing of the full readable
`31020–31028` block and other registers recorded as legal/readable on
PQ1 that are used on another Fox product. This supersedes the earlier
exclusion of experimental telemetry from PR1, without changing the
recorded evidence or asserting that cross-model meanings are confirmed.

Maintain the register plan in `docs/PQ1_REGISTER_MAPPING.csv` and the
test catalogue in `docs/PQ1_TEST_PLAN.csv`. The original Excel workbook
is an archival reference and is no longer synchronised with CSV edits.

- Use P1 interpretations provisionally for `31020` battery voltage,
  `31021` current, `31023` temperature, `31025–31026` BMS charge/discharge
  rates and `31028` BMS connection state. Existing power/SOC readings
  remain at `31022` and `31024`. The current P1 profile does not decode
  `31027` as inverter state; expose it raw for comparison.
- Include readable alternatives, duplicates, state words and control
  registers as explicitly experimental read-only diagnostics where
  necessary. Keep unknown words raw, preserve candidate meanings in
  descriptions, and retain raw values when testing decoded candidates.
  The CSV implementation columns identify implemented entities separately from
  deferred readings; implementation does not constitute hardware validation.
- Do not gate otherwise useful battery sensors on an unverified BMS
  connection-state interpretation. Compare `31023` and `37611` through
  distinct entities rather than assigning the same entity key twice.
- Registers without recorded PQ1 readability remain pending legality
  checks. Do not infer an entire pair or range is readable from a
  neighbouring readable word. Overlapping mapping rows must share
  diagnostic entities rather than create duplicates.
- Inspect the readable scheduler block using the existing
  `foxess_modbus.read_registers` action, with `type: holding` and bounded
  counts no larger than the configured adapter maximum. Start at `48010`
  for records. No dedicated snapshot sensor or 970 regularly polled
  entities are added. Dynamic interpretation and controls remain later-PR
  work. This reuses the existing register-read service as agreed in the
  implementation plan.
- All additions remain read-only. Never poll `41001–41006`, expose
  `44000` as Boolean Remote Enable, or infer physical battery/CT topology
  from register availability. Experimental readings must not silently
  become trusted inputs to energy accounting or control automations.

The roadmap below remains applicable except for this expanded read-only
test coverage in PR1.

### PR1 implementation decisions

- PQ1 has its own `InverterModel` and `Inv` flag. The common holding map
  uses the repository's AUX profile convention with LAN fallback. Only
  native LAN has supplied hardware evidence; RS485 is not claimed tested.
- Existing descriptions supply core readings, P1-style battery readings
  and candidate `320xx` counters. Provisional decoded sensors are marked
  Experimental, disabled by default, provide raw-word attributes and omit
  statistics eligibility. Raw diagnostics are also disabled by default.
  Enable the desired entities in Home Assistant when testing.
- PV string power initially uses the observed single words `39280`,
  `39282`, `39284`, `39286`, following the existing P1 single-word pattern.
  These readings remain experimental. Their preceding high words are not
  subscribed to until PQ1 readability and width are established. Total PV
  comes from `39118`; no per-string energy integrators are created from
  provisional power values.
- Manual Work Mode uses a read-only enum with `0: Self Use`. Unknown
  values retain `raw_value` and report unknown state. Scheduler Enabled
  accepts only 0 and 1. Neither entity can write.
- BMS readings are not gated by unverified `31028` or `37002` semantics.
- No PQ1 number/select entities, remote-control manager or charge periods
  are created. The existing generic write service is unchanged; this is
  read-only product support, not a new global write-service prohibition.
- Automated tests use recorded examples and synthetic boundary values.
  The implemented integration still requires on-device validation.

1.  **PR1 --- Core monitoring:** model/firmware, PV1--PV4,
    grid/import/export, load, battery power/SOC, established BMS, useful
    daily/total energy, verified limits, Manual Work Mode and Scheduler
    Enabled. Read-only.
2.  **PR2 --- Manual work-mode control:** only after PQ1 write transport
    and write encoding are established. Read and write mode maps may
    differ.
3.  **PR3 --- Scheduler reading + extended telemetry:** dynamic
    schedules, Remaining Time, Effective Work Mode, BMS2/battery
    channels, CT2/Meter2 and other confirmed extended telemetry.
4.  **PR4 --- Scheduler control:** enable/disable and record editing
    only after the write protocol, unknown fields and any shadow/commit
    behaviour are understood.

Forecasting, tariffs and optimisation logic belong elsewhere in Home
Assistant; `foxess_modbus` should provide reliable sensor/actuator data.

## Tested hardware / transport

- FoxESS **PQ1-8.0**, native LAN Modbus TCP port 502, slave/device ID
  **247**.
- Before PR1, native LAN reached model detection but the integration rejected
  `PQ1-8.0` as unsupported.
- Four EQ5000 battery modules installed. Do not equate physical
  modules with inverter/BMS "channels".
- Four PV inputs exist; PV1--PV3 tested connected, PV4 observed
  unused.

## Evidence levels

**Unknown** = readable/legal only. **Candidate** = meaning known on
another model. **Strong candidate** = cross-model meaning plus plausible
PQ1 correlation. **Strong** = substantial PQ1 correlation plus
cross-model evidence. **Confirmed** = controlled PQ1 change gives the
predicted change (or equivalent direct evidence).

## Confirmed / high-confidence core map

### Firmware

`36001` Master, `36002` Slave, `36003` Manager firmware.

### PV

| Register | Meaning                 | Scale/notes |
| -------- | ----------------------- | ----------- |
| 39070    | PV1 voltage             | 0.1 V       |
| 39071    | PV1 current             | 0.01 A      |
| 39072    | PV2 voltage             | 0.1 V       |
| 39073    | PV2 current             | 0.01 A      |
| 39074    | PV3 voltage             | 0.1 V       |
| 39075    | PV3 current             | 0.01 A      |
| 39076    | PV4 voltage             | 0.1 V       |
| 39077    | PV4 current             | 0.01 A      |
| 39280    | PV1 power observed word | W           |
| 39282    | PV2 power observed word | W           |
| 39284    | PV3 power observed word | W           |
| 39286    | PV4 power observed word | W           |

Newer Fox profiles treat PV power as 32-bit pairs `[39280,39279]`,
`[39282,39281]`, `[39284,39283]`, `[39286,39285]`; test whether PQ1
genuinely needs the full pairs. `39118` has correlated with total PV
power.

### Other core telemetry

Examples already correlated on PQ1: `31006` grid voltage, `31024`
battery SOC, `39139` grid frequency, `39141` inverter temperature.
`31022` has shown signed battery-related power. Reuse existing entity
definitions only where PQ1 evidence supports them.

### Battery constraints

Confirmed readable: `41007=500` max charge current (50.0 A), `41008=500`
max discharge current, `41009=10` min SOC, `41010=100` max SOC,
`41011=10` grid/corresponding min SOC. Newer block duplicates these at
`46607–46611`.

### BMS / energy

`376xx` provides established BMS data; `37632=1920` correlated with
19.20 kWh remaining. `32000–32023` is readable and strongly matches the
existing Fox energy-counter architecture; use this as PR1's starting
energy map.

## Manual Work Mode

`41000` is **Manual Work Mode**, not necessarily Current/Effective Work
Mode. PQ1 reads `0` in manual Self Use and it does not follow scheduled
modes while Scheduler is active. Existing H1-G2/P1 read semantics
suggest 0 Self Use, 1 Feed-in Priority, 2 Backup, 4 Peak Shaving; only
claim PQ1 values to the level actually tested.

A LAN FC06 write `41000: 0 -> 1` was acknowledged while the inverter
remained Self Use and readback remained 0. This is **inconclusive**, not
proof writes fail: newer Fox/EVO work demonstrates asymmetric read/write
maps, so write value 1 could conceivably mean Self Use.

## Do not poll legacy charge periods

`41001–41006` repeatedly fail on PQ1 while the surrounding compatible
map works. Explicitly exclude PQ1 from legacy two-charge-period
infrastructure. KH/newer profiles also skip this block.

## Limits / newer configuration

`46616=0`, `46617=15000`; installer global export limit is 15 kW and
other current Fox models use this pair as 32-bit Export Power Limit.
Treat as **Strong**, pending a controlled PQ1 limit change.

Candidates: `46501–02` Import Power Limit, `46503` Threshold SOC,
`46504–05` Export Power Limit. Do not conflate these with the global
installer limit until tested.

## Scheduler knowledge (primarily PR3)

`48000` is confirmed Scheduler Enabled: 1 ON, 0 OFF. Turning it off
retains records.

Records begin at `48010`, stride 10. `+0` is populated/valid. Iterate
while populated. Records sort dynamically by start time; they are not
stable IDs. The **last populated record is Remaining Time**; preceding
records are schedules.

| Offset | Meaning                     | Status                                                             |
| ------ | --------------------------- | ------------------------------------------------------------------ |
| +0     | populated/valid             | Confirmed                                                          |
| +1     | start time                  | Confirmed                                                          |
| +2     | end time                    | Confirmed                                                          |
| +3     | scheduler work mode         | Confirmed                                                          |
| +4     | packed Max/Min SOC          | Confirmed                                                          |
| +5     | mode-specific SOC parameter | Confirmed                                                          |
| +6     | mode-specific power         | Confirmed                                                          |
| +7     | scheduler field             | structure confirmed; semantic unknown                              |
| +8     | scheduler field             | structure confirmed; semantic unknown; controlled changes observed |
| +9     | scheduler field             | structure confirmed; semantic unknown                              |

Time encoding: `(hour << 8) | minute`. SOC examples: `0x640A` =
max100/min10; 99/11 gave `0x630B`.

Confirmed scheduler mode values: 1 Self Use, 2 Feed-in Priority, 3
Backup, 6 Forced Charge, 7 Forced Discharge. **Keep this enum separate
from Manual Work Mode.**

Do not hard-code Remaining Time to a fixed address. Do not zero
unknown/unused fields.

Native-LAN writes to scheduler enable using FC06 and FC16 did not change
`48000`; do not infer that COM/RS485 behaves identically.

Repeated scheduler banks at +80 exist; purpose unknown. Do not expose
them or assume per-phase semantics.

## Extended telemetry candidates (PR3 unless clearly proven useful earlier)

- BMS2 on newer models: `37700`, `38307–38310`, `38315–38318`,
  `38322`, `38330`.
- Battery channels: `39227–39231` channel 1, `39232–39236` channel 2,
  `39237–39238` aggregate.
- Load: `39219–39224` R/S/T, `39225–39226` total.
- CT2/Meter2: `38914–38921`. Interesting for the separate EV consumer
  unit, but **register existence does not prove a physical PQ1 CT2
  input**; verify hardware/manual before wiring.
- Newer grid CT: `38814–38821`.
- Alternative newer energy map: `39601–39632`; compare with
  established PQ1 `320xx`, do not replace speculatively.

## Remote-control maps

Observed PQ1: `44000=12 (0x000C)`, `44001=60`, `44002=0`. - `44000`:
semantics unresolved; possible bitfield/enum. Never expose as Boolean
Remote Enable. - `44001`: strong timeout/watchdog candidate. - `44002`:
strong active-power command/state candidate. Legacy H3 may use
`[44003,44002]` as 32-bit active power; width on PQ1 unresolved.

Newer candidates: `46001` enable, `46002` timeout, `46003–04` active
power, `46018–19` battery power limit, `49203` newer/EVO Work Mode.
Correlate before assigning PQ1 semantics.

## LAN vs COM/RS485

Separate transport from model semantics. Native LAN reads do not prove
identical write permissions/encoding over physical COM/RS485. Before COM
testing verify A/B pins, electrical standard, baud/parity/data/stop
settings and slave ID. Read known registers first, compare LAN, then
perform bounded writes. Never expose port 502 to the Internet.

## PR1 implementation rules

1.  PQ1 is a distinct first-class profile; do not wholesale alias to
    P1/H1-G2.
2.  Follow current upstream `main` abstractions and selectively reuse
    proven entities.
3.  Recognise `PQ1-*` if consistent with upstream matching conventions.
4.  Add PV3/PV4.
5.  Explicitly exclude `41001–41006`.
6.  Manual Work Mode read-only.
7.  Scheduler Enabled (`48000`) may be exposed as state; full parsing
    waits for PR3.
8.  Do not expose unresolved `44000` semantics.
9.  Avoid speculative entities merely to maximise entity count.
10. Add PQ1 fixtures/snapshots/tests and run the full regression suite.

## PR1 definition of done

PQ1-8.0 is recognised and, without writes, provides useful
model/firmware, PV1--4/production, grid/import/export, load, battery
power/SOC, established BMS, useful energy totals, verified battery
constraints, Manual Work Mode and Scheduler Enabled; known-invalid
legacy charge-period registers are not polled; uncertain semantics are
not presented as facts; existing-model tests remain green.

## Hard "do not assume" list

Do not assume: - readable address = same semantics as another Fox
model; - `41000` = effective mode with scheduler on; - manual and
scheduler mode enums match; - `41001–41006` exist; - `44000=12` is
Boolean; - BMS/battery channel = physical module; - CT2 registers imply
a physical PQ1 CT2 input; - LAN read support implies LAN write
support; - write acknowledgement proves semantic change; - FC06/FC16 are
interchangeable; - repeated +80 scheduler banks are per-phase; -
`ventisep` GitHub posts are independent evidence.

## Git / upstream

Base on current `nathanmarlor/foxess_modbus` `main`. Keep fork `main`
close to upstream and develop PR1 on a feature branch such as
`pq1-core`. Before coding, inspect current upstream and relevant open
PRs (especially work-mode/EVO/newer-model work) so PQ1 uses current
abstractions rather than duplicating likely merges. Prefer small
reviewable commits and no unrelated refactors.

The purpose of PR1 is **not to finish reverse-engineering PQ1**. It is a
conservative, useful, maintainable core profile backed by PQ1 evidence.
