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

The two rate sensors also expose attributes:

- `active_window`: `"HH:MM-HH:MM"` of the window currently in effect, or `null`.
- `windows`: the full configured schedule, so templates and automations can read
  future windows without extra entities.

If no window matches the current time, both rates read `0.0`.

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
3. Open the integration's **Options**. There you set:
   - **Daily supply charge** in `AUD/day`, and
   - **Tariff windows** as a JSON list.

### Tariff windows

Each window is a recurring daily period with an import and export rate in
`AUD/kWh`:

```json
[
  {"start": "07:00", "end": "23:00", "import_rate": 0.35, "export_rate": 0.05},
  {"start": "23:00", "end": "07:00", "import_rate": 0.18, "export_rate": 0.05}
]
```

- `start` is inclusive, `end` is exclusive.
- If `end` is earlier than `start`, the window spans midnight (the second
  window above covers 23:00 → 07:00 the next morning).
- When windows overlap, the **earliest-listed** match wins.
- If no window matches the current time, both rates read `0.0`.

The form rejects malformed JSON, missing fields, bad times, zero-length
windows and negative rates, with a message naming the problem.

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
its cost engine only ever multiplies energy by price. The supported workaround is to
hand the dashboard a cumulative monetary total:

1. **Settings → Dashboards → Energy → Grid**.
2. Add a grid source using a placeholder energy entity pinned to `0` kWh
   (`device_class: energy`, `state_class: total_increasing`, unit `kWh`). A utility
   meter with a non-empty tariff also works.
3. Set that source's **"entity tracking the total costs"** to
   `sensor.<meter>_supply_charge_total`.

The dashboard then folds your daily charge into its cost figures. The total counts
from the day the integration was set up and never decreases, so restarts are safe.

## Notes

- Rates are stored exactly as you enter them, inclusive of any tax. There is no tax
  logic.
- The active window is re-evaluated once a minute, so a rate change at a window
  boundary appears within about a minute.
