# Energy Tariff Helper

A Home Assistant custom integration that publishes your **current electricity
tariff rates** as sensors, driven by time-of-use windows you configure in the UI.

It provides pricing information only. It does not multiply energy by price, does
not accumulate costs, and does not replace the Energy dashboard's own cost engine.

## Sensors

| Entity | Unit | Meaning |
| --- | --- | --- |
| `sensor.<meter>_import_rate` | `AUD/kWh` | Rate you pay to import right now. |
| `sensor.<meter>_export_rate` | `AUD/kWh` | Rate you are paid to export right now. |
| `sensor.<meter>_supply_charge` | `AUD/day` | Your fixed daily supply charge. |
| `sensor.<meter>_supply_charge_total` | `AUD` | Cumulative supply charge since setup. |
| `sensor.<meter>_supply_charge_energy` | `kWh` | Always `0`; exists to carry the supply charge in the Energy dashboard. |

Every sensor reports values **including tax** where you have enabled it, and
carries a `gst_multiplier` attribute (`1.0` when tax is off for that component).

The two rate sensors also expose attributes, each reflecting its own direction:

- `active_window`: `"HH:MM-HH:MM"` of the window currently in effect for that
  direction, or `null`.
- `windows`: that direction's full schedule, so templates and automations can read
  future windows without extra entities.

So `sensor.<meter>_import_rate` lists your import windows and
`sensor.<meter>_export_rate` lists your export windows.

If no window matches the current time, that direction's rate reads `0.0`.

## Install

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/funkmaster-dan/Home-Assistant-Tarrif-Helper` with
   category **Integration**.
3. Install **Energy Tariff Helper** and restart Home Assistant.

### Manual

Copy `custom_components/energy_tariff_helper/` into your HA `config/custom_components/`
directory and restart Home Assistant.

## Configure

1. **Settings → Devices & Services → Add Integration → Energy Tariff Helper**.
2. Give the meter a name (e.g. `Electricity`).
3. On the integration page you get two sections of windows:

   - **Import window** — the periods and rates you pay to import.
   - **Export window** — the periods and rates you are paid to export.

   Each section has an **Add** button, and every window row has edit and delete
   buttons. Add as many as you need; changes apply immediately.
4. **Configure** on the integration page sets:

   - **Daily supply charge** — a fixed amount billed per day in `AUD/day`.
   - **Tax rate** — the percentage to apply (default 10%, Australian GST).
   - **Add tax to import / export / supply charge** — three independent toggles.

### Tax (GST)

Enter your tariff rates **excluding tax**, then choose which components get tax
added. Each is independent:

- **Import** — normally taxed.
- **Export** — feed-in tariffs are often tax-free, so this is off by default.
- **Supply charge** — normally taxed.

The rate sensors, the supply charge sensor and the cumulative supply charge total
all report **tax-inclusive** values once enabled, so the Energy dashboard's cost
figures include tax. All toggles are **off by default**, so upgrading never
changes your reported rates.

Every sensor carries a `gst_multiplier` attribute (`1.0` when tax is off for that
component) explaining any difference from the rates you entered.

Import and export are separate schedules, so you can model a two-tier import
tariff and a flat feed-in tariff, or any other combination.

### How windows behave

- `start` is inclusive, `end` is exclusive.
- If the end time is earlier than the start time, the window spans midnight —
  so `23:00 → 07:00` covers 11pm through 7am the next morning.
- When windows overlap, the **earliest-listed** match wins.
- If no window matches the current time, that direction's rate reads `0.0`.

## Use it in the Energy dashboard

The Energy dashboard can compute costs directly from the rate sensors:

1. **Settings → Dashboards → Energy → Grid**.
2. Set **"entity tracking total costs"**… instead, set the grid source's *energy
   price* fields:
   - Import price → `sensor.<meter>_import_rate`
   - Export price → `sensor.<meter>_export_rate`

   The `AUD/kWh` unit is accepted natively; no helper is needed.

### Adding the fixed daily supply charge

Home Assistant's Energy dashboard has no built-in field for a fixed daily charge —
its cost engine only ever multiplies energy by price. The integration therefore
provides a matching pair of entities for a dedicated grid source:

| Entity | Role |
| --- | --- |
| `sensor.<meter>_supply_charge_energy` | always `0 kWh`, so it adds nothing to your energy totals |
| `sensor.<meter>_supply_charge_total` | the cumulative supply charge in `AUD` |

Wire them up in **Settings → Dashboards → Energy → Grid → Add grid source**:

- **Grid consumption** → `sensor.<meter>_supply_charge_energy`
- **"entity tracking the total costs"** → `sensor.<meter>_supply_charge_total`

The dashboard then adds your daily charge to its cost figures without touching
your energy totals.

The total applies the charge **from the start of each day**, so the current day is
included as soon as it begins and the charge for a given day is recorded on that
day. The setup day counts as day one. The value only ever increases, so restarts
are safe.

Note that the cost field only exists on **grid** sources — individual devices
cannot carry a cost entity.

## Notes

- Rates are stored as you enter them, **excluding tax**. Tax is applied only to
  the components you enable, as described above.
- The active window is re-evaluated once a minute, so a rate change at a window
  boundary appears within about a minute.
