# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog],
and this project adheres to [Semantic Versioning].

## [0.2.6] - 2026-03-17

### Added

- Added motor fault diagnostic binary sensor for Smart Curtain Robot (DP 12).
- Added device registry metadata refresh to populate firmware/protocol/hardware versions after connect.

### Changed

- Improved Tuya BLE packet reassembly tolerance for devices that include fixed packet header padding bytes.
- Improved datapoint synchronization reliability by scheduling staged refresh requests after connect.
- Removed Smart Curtain Robot moving/work state/end-position sensors to reduce noisy/less-useful entities for cover devices.

### Fixed

- Fixed FUN_SENDER_DEVICE_STATUS handling to use fire-and-forget request flow.
- Fixed pairing response parsing to accept variable-length payloads returned by some devices.

## [0.2.5] - 2026-02-23

### Added

- Added cover platform support for Smart Curtain Robot (product_id: kcy0x4pi)
- Added manual device credentials entry in config flow
- Added enhanced error handling for Tuya API login failures

### Changed

- Updated README with comprehensive documentation
- Improved device support documentation with detailed feature lists
- Added manual credentials entry documentation
- Enhanced troubleshooting section
- Updated codeowner to @elrobertocarlos
- Updated repository references

### Fixed

- Fixed TypeError in config flow when adding integration manually (async_step_user and async_step_init now properly accept user_input parameter)
- Fixed KeyError in build_cache when config entries lack required Tuya login credentials (added validation before attempting login)

## [0.1.0] - 2023-04-22

- Initial release


## [0.1.1] - 2023-04-26

### Added

- Added new product_id for Fingerbot Plus (#1)

### Fixed

- Fixed problem in options flow.

### Changed

- Updated strings.json


## [0.1.2] - 2023-04-26

### Changed

- Changed a way to obtain device credentials from Tuya IOT cloud, possible fix to (#2)

## [0.1.4] - 2023-04-30

### Added

- Added support of CUBETOUCH 1s, thanks @damiano75
- Added new product_ids for Fingerbot.
- Added new product_ids for Fingerbot Plus.
- First attempt to support Smart Lock device.

### Fixed

- Fixed possible disconnect of BLE device.

## [0.1.5] - 2023-06-01

### Added

- Added new product_ids for Fingerbot.
- Added event "fingerbot_button_pressed" which is fired on Fingerbot Plus touch button press.
- First attempt to add support of climate entity.

## [0.1.6] - 2023-06-01

### Added

- Added new product_ids for Fingerbot and Fingerbot Plus.

### Changed

- Updated sources to conform Python 3.11

## [0.1.7] - 2023-06-01

### Added

- Added new product_ids.
- Added full support of BLE TRV provided by @forabi
- Added support of programming mode for Fingerbot Plus, thanks @redphx for information.

### Changed

- Improved connection stability.

## [0.1.8] - 2023-07-09

### Added

- Added support of 'Irrigation computer', thanks to @SanMiggel.
- Added new product_ids for Smart locks, thanks to @drewpo28.

### Changed

- Connection to the device is postponed now. Previously some out of range device might prevents HA from fully booting.
- Improved connection stability.


## [0.2.0] - 2024-03-21

### Added

- Add sfkzq/nxquc5lb device

### Changed

- Update readme (forked from)

### Fixed

- fix: Compatibility with HA 2024.1
- Fix deprecated

## [0.2.1] - 2025-03-26

### Added

- Add ggq/hfgdqhho device

### Fixed

- fix: Compatibility with HA 2025.3
- Fix deprecated

## [0.2.2] - 2025-04-16

### Fixed

- Fix deprecated with Home assistant 2025.4.2

### Update

- Update README about device support

## [0.2.3] - 2025-04-25

### Added

- Add ggq/fnlw6npo device
- Add jtmspro/ebd5e0uauqx0vfsp device

## [0.2.4] - 2025-12-29

### Added

- drop CONF_APP_TYPE
- Add mknd4lci
- Add riecov42
- fix SyntaxWarning: invalid escape sequence '\d'
