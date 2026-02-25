# Home Assistant support for Tuya BLE devices

## Overview

This integration supports Tuya devices connected via BLE.

_Forked from [@PlusPlus-ua](https://github.com/PlusPlus-ua/ha_tuya_ble) and [@jbsky](https://github.com/jbsky/ha_tuya_ble)_

## Installation

Place the `custom_components` folder in your configuration directory (or add its contents to an existing `custom_components` folder). Alternatively install via [HACS](https://hacs.xyz/).

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=elrobertocarlos&repository=ha_tuya_ble&category=integration)

## Requirements

- Home Assistant 2024.1.0 or newer
- HACS (if installing via HACS)

## Usage

After adding to Home Assistant, the integration will automatically discover all supported Bluetooth devices, or you can add discoverable devices manually.

The integration works locally, but connection to Tuya BLE devices requires device credentials (device ID and encryption key) from the Tuya IoT cloud. These credentials are typically only needed once during setup.

### Getting Tuya Cloud Credentials

To obtain the required credentials, refer to the official Tuya integration [documentation](https://www.home-assistant.io/integrations/tuya/). You'll need:

- Tuya IoT Access ID
- Tuya IoT Access Secret
- Your Tuya account credentials
- Country code (to determine the correct API endpoint)

### Manual Credentials Entry

If cloud login fails (due to IP restrictions, account permissions, or other issues), you can manually enter device credentials. These can be obtained using:

- [tinytuya](https://github.com/jasonacox/tinytuya) - A Python module for local control of Tuya devices
- Extracting credentials from your Tuya mobile app

Required manual credentials:
- **UUID** (required)
- **Local Key** (required)
- Device ID (optional but recommended)
- Category (optional but recommended)
- Product ID (optional but recommended)
- Device Name (optional)
- Product Model (optional)
- Product Name (optional)

## Supported devices list

### Fingerbots (category_id 'szjqr' and 'kg')

- **Fingerbot** (product_ids: `ltak7e1p`, `y6kttvd6`, `yrnk7mnn`, `nvr2rocq`, `bnt7wajf`, `rvdceqjh`, `5xhbk964`)  
  Original device, powered by CR2 battery
  
- **Adaprox Fingerbot** (product_id: `y6kttvd6`)  
  Built-in battery with USB Type-C charging
  
- **Fingerbot Plus** (product_ids: `blliqpsj`, `ndvkgsrm`, `yiihr7zh`, `neq16kgd`, `mknd4lci`, `riecov42`)  
  Similar to original, includes sensor button for manual control
  
- **CubeTouch 1s** (product_id: `3yqdo5yt`)  
  Built-in battery with USB Type-C charging
  
- **CubeTouch II** (product_id: `xhf790if`)  
  Built-in battery with USB Type-C charging

**Features:**
All features available in Home Assistant. Programming (series of actions) is implemented for Fingerbot Plus.

**Programming entities:**
- `Program` (switch)
- `Repeat forever` (switch)
- `Repeats count` (number)
- `Idle position` (number)
- `Program` (text)

**Program format:** `position[/time];position[/time];...`
- `position` is in percent (0-100)
- `time` is optional, in seconds (defaults to 0 if missing)
- Example: `50/2;100/0;0/3` - Move to 50% (hold 2s), then 100% (instant), then 0% (hold 3s)

**Events:**
- `fingerbot_button_pressed` - Fired when the touch button is pressed on Fingerbot Plus models

### Temperature and Humidity Sensors (category_id 'wsdcg')

- **Soil moisture sensor** (product_id: `ojzlzzsw`)

### Plant Sensors (category_id 'zwjcy')

- **Smartlife Plant Sensor SGS01** (product_id: `gvygg3m8`)

### CO2 Sensors (category_id 'co2bj')

- **CO2 Detector** (product_id: `59s19z5m`)

### Smart Locks (category_id 'ms')

- **Smart Lock** (product_ids: `ludzroix`, `isk2p555`)

### Climate Devices (category_id 'wk')

- **Thermostatic Radiator Valve** (product_ids: `drlajpqc`, `nhj2j7su`)

### Smart Water Bottles (category_id 'znhsb')

- **Smart water bottle** (product_id: `cdlandip`)

### Irrigation Controllers (category_id 'ggq')

- **Irrigation computer** (product_ids: `6pahkcau`, `hfgdqhho`, `fnlw6npo`)

### Water Valves (category_id 'sfkzq')

- **Water valve controller** (product_id: `nxquc5lb`)

### Smart Curtains (category_id 'cl')

- **Smart Curtain Robot** (product_id: `kcy0x4pi`)

**Features:**
- Open/Close curtain
- Stop curtain movement
- Set curtain position (0-100%)
- Current position feedback

### Access Control (category_id 'jtmspro')

- **CentralAcesso** (product_id: `ebd5e0uauqx0vfsp`)

## Configuration

The integration can be configured through the Home Assistant UI. Debug logging is available for troubleshooting:

```yaml
logger:
  default: info
  logs:
    custom_components.tuya_ble: debug
    custom_components.tuya_ble.config_flow: debug
    custom_components.tuya_ble.cloud: debug
```

## Troubleshooting

### Connection Issues

- Ensure the device is in range and has sufficient battery
- Try unbinding the device from any Tuya Bluetooth gateway
- Check that Bluetooth is enabled on your Home Assistant host

### Cloud Login Failures

- Verify your Tuya IoT credentials are correct
- Check if your IP address is allowed in the Tuya IoT platform
- Ensure your account has the necessary permissions
- Try using manual credential entry if cloud login continues to fail

### Device Not Discovered

- Make sure the device is registered in the Tuya cloud using the mobile app
- Verify the device is broadcasting BLE advertisements
- Check that the device is not already paired with another integration

## Support project

I am working on this integration in Ukraine. Our country was subjected to brutal aggression by Russia. The war still continues. The capital of Ukraine - Kyiv, where I live, and many other cities and villages are constantly under threat of rocket attacks. Our air defense forces are doing wonders, but they also need support. So if you want to help the development of this integration, donate some money and I will spend it to support our air defense.

<p align="center">
  <a href="https://www.buymeacoffee.com/3PaK6lXr4l"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy me an air defense"></a>
</p>

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for detailed version history.
