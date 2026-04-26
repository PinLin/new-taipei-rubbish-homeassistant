# Repository Guidelines

## Project Structure & Module Organization
This repository contains a Home Assistant custom integration for New Taipei City rubbish collection data. Runtime code lives in `custom_components/ntpc_rubbish/`. Keep API clients in `api.py`, live polling and ETA/status logic in `coordinator.py`, config and options flow logic in `config_flow.py`, sensor entities in `sensor.py`, binary sensors in `binary_sensor.py`, and shared helpers/constants in `entity.py` and `const.py`. Metadata and user-facing text live in `manifest.json`, `services.yaml`, `strings.json`, and `translations/zh-Hant.json`. Tests live in `tests/`, currently `tests/test_coordinator.py` and `tests/test_config_flow.py`. Brand assets are under `custom_components/ntpc_rubbish/brand/`.

## Build, Test, and Development Commands
Run lightweight checks from the repo root:

```bash
python -m compileall custom_components/ntpc_rubbish tests
python -m pytest tests/ -v
```

`compileall` catches syntax issues quickly across the integration and tests. `pytest` runs the checked-in unit tests. For manual verification, copy `custom_components/ntpc_rubbish/` into Home Assistant’s `config/custom_components/`, restart HA, then add the integration from Settings > Devices & Services.

## Coding Style & Naming Conventions
Use 4-space indentation, module docstrings, and `snake_case` for functions, variables, config keys, and helpers. Keep constants uppercase in `const.py`. Follow Home Assistant async conventions such as `async_setup_entry` and `DataUpdateCoordinator`. Prefer stable ID-based entity naming; entity IDs should stay coordinate-based (for example `sensor.ntpc_rubbish_25_07987_121_48115_eta_minutes`) rather than name-derived pinyin.

## Testing Guidelines
Use `pytest` and name test files `test_*.py`. Add focused tests when changing route grouping, ETA/departure logic, config flow labels, or translation-backed entity behavior. Manual smoke tests should cover the map-only config flow, entity creation, ETA display, `垃圾車已離開`, and the `ntpc_rubbish.update` service.

## Commit & Pull Request Guidelines
Use short imperative commit messages such as `Fix zero-diff ETA fallback` or `Rename entity IDs to stable point IDs`. Keep commits focused. Pull requests should include a brief summary, manual test notes, linked issues when relevant, and screenshots for config flow or UI text changes.

## Security & Configuration Tips
Do not hardcode secrets, local paths, or environment-specific values. `api.py` intentionally relaxes SSL verification for the NTPC government host; document any networking change clearly. Treat `lineid`, `rank`, and config entry IDs as important debugging identifiers and preserve them in logs and diagnostics.
