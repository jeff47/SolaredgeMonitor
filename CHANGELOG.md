# Changelog

## Unreleased
- Switched PAC/peer thresholds to percentages of AC capacity (default 1% PAC floor; low-light/peer skips as %).
- Added a single irradiance floor plus 100% cloud + precip suppression for PAC/low-output alerts.
- Updated config docs/examples to reflect percent thresholds and weather gates.
- Added weather-suppression tests covering irradiance, expected-power, and precip-based skips.
