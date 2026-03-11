"""The Tuya BLE integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
)
from homeassistant.components.climate.const import (
    PRESET_AWAY,
    PRESET_NONE,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .devices import (
    TuyaBLEData,
    TuyaBLEEntity,
    TuyaBLEPassiveCoordinator,
    TuyaBLEProductInfo,
)
from .tuya_ble import TuyaBLEDataPoint, TuyaBLEDataPointType, TuyaBLEDevice

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)


@dataclass
class TuyaBLEClimateMapping:
    """
    Mapping configuration for Tuya BLE climate devices.

    Attributes:
        description: Description of the climate entity.
        hvac_mode_dp_id: Data point ID for HVAC mode.
        hvac_modes: List of supported HVAC modes.
        hvac_switch_dp_id: Data point ID for HVAC switch.
        hvac_switch_mode: HVAC mode for the switch.
        preset_mode_dp_ids: Dictionary mapping preset modes to data point IDs.
        temperature_unit: Unit of temperature.
        current_temperature_dp_id: Data point ID for current temperature.
        current_temperature_coefficient: Coefficient for current temperature value.
        target_temperature_dp_id: Data point ID for target temperature.
        target_temperature_coefficient: Coefficient for target temperature value.
        target_temperature_max: Maximum target temperature.
        target_temperature_min: Minimum target temperature.
        target_temperature_step: Step size for target temperature.
        current_humidity_dp_id: Data point ID for current humidity.
        current_humidity_coefficient: Coefficient for current humidity value.
        target_humidity_dp_id: Data point ID for target humidity.
        target_humidity_coefficient: Coefficient for target humidity value.
        target_humidity_max: Maximum target humidity.
        target_humidity_min: Minimum target humidity.

    """

    description: ClimateEntityDescription

    hvac_mode_dp_id: int = 0
    hvac_modes: list[HVACMode] | None = None

    hvac_switch_dp_id: int = 0
    hvac_switch_mode: HVACMode | None = None

    preset_mode_dp_ids: dict[str, int] | None = None

    temperature_unit: str = UnitOfTemperature.CELSIUS
    current_temperature_dp_id: int = 0
    current_temperature_coefficient: float = 1.0
    target_temperature_dp_id: int = 0
    target_temperature_coefficient: float = 1.0
    target_temperature_max: float = 30.0
    target_temperature_min: float = 5
    target_temperature_step: float = 1.0

    current_humidity_dp_id: int = 0
    current_humidity_coefficient: float = 1.0
    target_humidity_dp_id: int = 0
    target_humidity_coefficient: float = 1.0
    target_humidity_max: float = 100.0
    target_humidity_min: float = 0.0


@dataclass
class TuyaBLECategoryClimateMapping:
    """
    Category mapping for Tuya BLE climate devices.

    Attributes:
        products: Optional dictionary mapping product IDs to lists of climate mappings.
        mapping: Optional list of climate mappings for the category.

    """

    products: dict[str, list[TuyaBLEClimateMapping]] | None = None
    mapping: list[TuyaBLEClimateMapping] | None = None


mapping: dict[str, TuyaBLECategoryClimateMapping] = {
    "wk": TuyaBLECategoryClimateMapping(
        products={
            **{
                key: [
                    # Thermostatic Radiator Valve
                    # - [x] 8   - Window
                    # - [x] 10  - Antifreeze
                    # - [x] 27  - Calibration
                    # - [x] 40  - Lock
                    # - [x] 101 - Switch
                    # - [x] 102 - Current
                    # - [x] 103 - Target
                    # - [ ] 104 - Heating time
                    # - [x] 105 - Battery power alarm
                    # - [x] 106 - Away
                    # - [x] 107 - Programming mode
                    # - [x] 108 - Programming switch
                    # - [ ] 109 - Programming data (deprecated - do not delete)
                    # - [ ] 110 - Historical data protocol (Day-Target temperature)
                    # - [ ] 111 - System Time Synchronization
                    # - [ ] 112 - Historical data (Week-Target temperature)
                    # - [ ] 113 - Historical data (Month-Target temperature)
                    # - [ ] 114 - Historical data (Year-Target temperature)
                    # - [ ] 115 - Historical data (Day-Current temperature)
                    # - [ ] 116 - Historical data (Week-Current temperature)
                    # - [ ] 117 - Historical data (Month-Current temperature)
                    # - [ ] 118 - Historical data (Year-Current temperature)
                    # - [ ] 119 - Historical data (Day-motor opening degree)
                    # - [ ] 120 - Historical data (Week-motor opening degree)
                    # - [ ] 121 - Historical data (Month-motor opening degree)
                    # - [ ] 122 - Historical data (Year-motor opening degree)
                    # - [ ] 123 - Programming data (Monday)
                    # - [ ] 124 - Programming data (Tuseday)
                    # - [ ] 125 - Programming data (Wednesday)
                    # - [ ] 126 - Programming data (Thursday)
                    # - [ ] 127 - Programming data (Friday)
                    # - [ ] 128 - Programming data (Saturday)
                    # - [ ] 129 - Programming data (Sunday)
                    # - [x] 130 - Water scale
                    TuyaBLEClimateMapping(
                        description=ClimateEntityDescription(
                            key="thermostatic_radiator_valve"
                        ),
                        hvac_switch_dp_id=101,
                        hvac_switch_mode=HVACMode.HEAT,
                        hvac_modes=[HVACMode.OFF, HVACMode.HEAT],
                        preset_mode_dp_ids={PRESET_AWAY: 106, PRESET_NONE: 106},
                        current_temperature_dp_id=102,
                        current_temperature_coefficient=10.0,
                        target_temperature_coefficient=10.0,
                        target_temperature_step=0.5,
                        target_temperature_dp_id=103,
                        target_temperature_min=5.0,
                        target_temperature_max=30.0,
                    )
                ]
                for key in ["drlajpqc", "nhj2j7su"]
            },
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLEClimateMapping]:
    """
    Retrieve the list of climate mappings for a given Tuya BLE device.

    Args:
        device (TuyaBLEDevice): The Tuya BLE device to get mappings for.

    Returns:
        list[TuyaBLECategoryClimateMapping]:
            A list of climate mappings associated with the device.

    """
    category = mapping.get(device.category)
    if category is not None and category.products is not None:
        product_mapping = category.products.get(device.product_id)
        if product_mapping is not None:
            return product_mapping
        if category.mapping is not None:
            return category.mapping
        return []
    return []


class TuyaBLEClimate(TuyaBLEEntity, ClimateEntity):
    """
    Representation of a Tuya BLE climate (thermostat) entity.

    This class integrates Tuya BLE climate devices with Home Assistant,
    providing support for temperature, humidity, HVAC modes, and preset modes.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLEPassiveCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLEClimateMapping,
    ) -> None:
        """
        Initialize a Tuya BLE climate entity.

        Args:
            hass (HomeAssistant): The Home Assistant instance.
            coordinator (TuyaBLEPassiveCoordinator): The coordinator for BLE updates.
            device (TuyaBLEDevice): The Tuya BLE device.
            product (TuyaBLEProductInfo): Product information.
            mapping (TuyaBLEClimateMapping): Mapping configuration for the device.

        """
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_preset_mode = PRESET_NONE
        self._attr_hvac_action = HVACAction.HEATING

        if mapping.hvac_mode_dp_id and mapping.hvac_modes:
            self._attr_hvac_modes = mapping.hvac_modes
        elif mapping.hvac_switch_dp_id and mapping.hvac_switch_mode:
            self._attr_hvac_modes = [HVACMode.OFF, mapping.hvac_switch_mode]

        if mapping.preset_mode_dp_ids:
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE
            self._attr_preset_modes = list(mapping.preset_mode_dp_ids.keys())

        if mapping.target_temperature_dp_id != 0:
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE
            self._attr_temperature_unit = mapping.temperature_unit
            self._attr_max_temp = mapping.target_temperature_max
            self._attr_min_temp = mapping.target_temperature_min
            self._attr_target_temperature_step = mapping.target_temperature_step

        if mapping.target_humidity_dp_id != 0:
            self._attr_supported_features |= ClimateEntityFeature.TARGET_HUMIDITY
            self._attr_max_humidity = mapping.target_humidity_max
            self._attr_min_humidity = mapping.target_humidity_min

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_current_temperature()
        self._update_target_temperature()
        self._update_current_humidity()
        self._update_target_humidity()
        self._update_hvac_mode()
        self._update_preset_mode()
        self._update_hvac_action()
        self.async_write_ha_state()

    def _update_current_temperature(self) -> None:
        dp_id = self._mapping.current_temperature_dp_id
        if dp_id == 0:
            return
        datapoint = self._device.datapoints[dp_id]
        if datapoint is None:
            return
        try:
            value = float(datapoint.value)
            self._attr_current_temperature = (
                value / self._mapping.current_temperature_coefficient
            )
        except Exception:
            _LOGGER.exception("Failed to parse current temperature datapoint value")

    def _update_target_temperature(self) -> None:
        dp_id = self._mapping.target_temperature_dp_id
        if dp_id == 0:
            return
        datapoint = self._device.datapoints[dp_id]
        if datapoint is None:
            return
        try:
            value = float(datapoint.value)
            self._attr_target_temperature = (
                value / self._mapping.target_temperature_coefficient
            )
        except Exception:
            _LOGGER.exception("Failed to parse target temperature datapoint value")

    def _update_current_humidity(self) -> None:
        dp_id = self._mapping.current_humidity_dp_id
        if dp_id == 0:
            return
        datapoint = self._device.datapoints[dp_id]
        if datapoint is None:
            return
        try:
            value = int(datapoint.value)
            self._attr_current_humidity = int(
                value / self._mapping.current_humidity_coefficient
            )
        except Exception:
            _LOGGER.exception("Failed to parse current humidity datapoint value")

    def _update_target_humidity(self) -> None:
        dp_id = self._mapping.target_humidity_dp_id
        if dp_id == 0:
            return
        datapoint = self._device.datapoints[dp_id]
        if datapoint is None:
            return
        try:
            value = float(datapoint.value)
            self._attr_target_humidity = (
                value / self._mapping.target_humidity_coefficient
            )
        except Exception:
            _LOGGER.exception("Failed to parse target humidity datapoint value")

    def _update_hvac_mode(self) -> None:
        if self._mapping.hvac_mode_dp_id != 0 and self._mapping.hvac_modes:
            datapoint = self._device.datapoints[self._mapping.hvac_mode_dp_id]
            if datapoint is None:
                return
            try:
                value = int(datapoint.value)
                self._attr_hvac_mode = (
                    self._mapping.hvac_modes[value]
                    if 0 <= value < len(self._mapping.hvac_modes)
                    else None
                )
            except Exception:
                _LOGGER.exception("Failed to parse HVAC mode datapoint value")
        elif self._mapping.hvac_switch_dp_id != 0 and self._mapping.hvac_switch_mode:
            datapoint = self._device.datapoints[self._mapping.hvac_switch_dp_id]
            if datapoint is None:
                return
            self._attr_hvac_mode = (
                self._mapping.hvac_switch_mode if datapoint.value else HVACMode.OFF
            )

    def _update_preset_mode(self) -> None:
        if not self._mapping.preset_mode_dp_ids:
            return
        current_preset_mode = PRESET_NONE
        for preset_mode, dp_id in self._mapping.preset_mode_dp_ids.items():
            datapoint = self._device.datapoints[dp_id]
            if datapoint and datapoint.value:
                current_preset_mode = preset_mode
                break
        self._attr_preset_mode = current_preset_mode

    def _update_hvac_action(self) -> None:
        try:
            if (
                self._attr_preset_mode == PRESET_AWAY
                or self._attr_hvac_mode == HVACMode.OFF
                or (
                    self._attr_target_temperature is not None
                    and self._attr_current_temperature is not None
                    and self._attr_target_temperature <= self._attr_current_temperature
                )
            ):
                self._attr_hvac_action = HVACAction.IDLE
            else:
                self._attr_hvac_action = HVACAction.HEATING
        except Exception:
            _LOGGER.exception("Exception occurred while determining HVAC action")

    async def async_set_temperature(self, **kwargs: object) -> None:
        """Set new target temperature."""
        if self._mapping.target_temperature_dp_id != 0:
            temperature_value = kwargs.get("temperature")
            if temperature_value is None:
                return
            if isinstance(temperature_value, (int, float, str)):
                try:
                    temperature = float(temperature_value)
                except (TypeError, ValueError):
                    _LOGGER.exception(
                        "Invalid temperature value: %s",
                        temperature_value,
                    )
                    return
            else:
                msg = f"Unsupported type for temperature: {type(temperature_value)}"
                raise TypeError(msg)
            int_value = int(temperature * self._mapping.target_temperature_coefficient)
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.target_temperature_dp_id,
                TuyaBLEDataPointType.DT_VALUE,
                int_value,
            )
            if datapoint:
                self._hass.create_task(datapoint.set_value(int_value))

    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        if self._mapping.target_humidity_dp_id != 0:
            int_value = int(humidity * self._mapping.target_humidity_coefficient)
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.target_humidity_dp_id,
                TuyaBLEDataPointType.DT_VALUE,
                int_value,
            )
            if datapoint:
                self._hass.create_task(datapoint.set_value(int_value))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if (
            self._mapping.hvac_mode_dp_id != 0
            and self._mapping.hvac_modes
            and hvac_mode in self._mapping.hvac_modes
        ):
            int_value = self._mapping.hvac_modes.index(hvac_mode)
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.target_humidity_dp_id,
                TuyaBLEDataPointType.DT_VALUE,
                int_value,
            )
            if datapoint:
                self._hass.create_task(datapoint.set_value(int_value))
        elif self._mapping.hvac_switch_dp_id != 0 and self._mapping.hvac_switch_mode:
            bool_value = hvac_mode == self._mapping.hvac_switch_mode
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.hvac_switch_dp_id,
                TuyaBLEDataPointType.DT_BOOL,
                bool_value,
            )
            if datapoint:
                self._hass.create_task(datapoint.set_value(bool_value))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if self._mapping.preset_mode_dp_ids:
            datapoint: TuyaBLEDataPoint | None = None
            bool_value = False

            keys = list(self._mapping.preset_mode_dp_ids.keys())
            values = list(self._mapping.preset_mode_dp_ids.values())  # Get all DP IDs
            # TRVs with only Away and None modes can be set with a single datapoint
            # and use a single DP ID
            if all(values[0] == elem for elem in values) and keys[0] == PRESET_AWAY:
                for dp_id in values:
                    bool_value = preset_mode == PRESET_AWAY
                    datapoint = self._device.datapoints.get_or_create(
                        dp_id,
                        TuyaBLEDataPointType.DT_BOOL,
                        bool_value,
                    )
                    break
            elif self._mapping.preset_mode_dp_ids:
                for (
                    dp_preset_mode,
                    dp_id,
                ) in self._mapping.preset_mode_dp_ids.items():
                    bool_value = dp_preset_mode == preset_mode
                    datapoint = self._device.datapoints.get_or_create(
                        dp_id,
                        TuyaBLEDataPointType.DT_BOOL,
                        bool_value,
                    )
            if datapoint:
                self._hass.create_task(datapoint.set_value(bool_value))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE sensors."""
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)

    entities: list[TuyaBLEClimate] = [
        TuyaBLEClimate(
            hass,
            data.coordinator,
            data.device,
            data.product,
            mapping,
        )
        for mapping in mappings
    ]
    async_add_entities(entities)
