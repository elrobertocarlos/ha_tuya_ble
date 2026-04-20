"""The Tuya BLE integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback

from .const import (
    BATTERY_CHARGED,
    BATTERY_CHARGING,
    BATTERY_NOT_CHARGING,
    BATTERY_STATE_HIGH,
    BATTERY_STATE_LOW,
    BATTERY_STATE_NORMAL,
    CO2_LEVEL_ALARM,
    CO2_LEVEL_NORMAL,
    DOMAIN,
)
from .devices import TuyaBLEData, TuyaBLEEntity, TuyaBLEProductInfo
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

if TYPE_CHECKING:
    from datetime import date, datetime
    from decimal import Decimal

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .devices import TuyaBLEPassiveCoordinator

_LOGGER = logging.getLogger(__name__)

SIGNAL_STRENGTH_DP_ID = -1


TuyaBLESensorIsAvailable = Callable[["TuyaBLESensor", TuyaBLEProductInfo], bool] | None


@dataclass
class TuyaBLESensorMapping:
    """
    Mapping for a Tuya BLE sensor.

    Attributes:
        dp_id (int): Data point ID for the sensor.
        description (SensorEntityDescription): Description of the sensor entity.
        force_add (bool): Whether to force add the sensor entity.
        dp_type (TuyaBLEDataPointType | None): Type of the data point.
        getter (
            Callable[[TuyaBLESensor], None] | None
        ): Custom getter function for the sensor value.
        coefficient (float): Coefficient for value conversion.
        icons (list[str] | None): List of icons for the sensor states.
        is_available (TuyaBLESensorIsAvailable):
            Function to determine sensor availability.

    """

    dp_id: int
    description: SensorEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    getter: Callable[[TuyaBLESensor], None] | None = None
    coefficient: float = 1.0
    icons: list[str] | None = None
    is_available: TuyaBLESensorIsAvailable = None


@dataclass
class TuyaBLEBatteryMapping(TuyaBLESensorMapping):
    """

    Mapping for a Tuya BLE battery sensor.

    Inherits from TuyaBLESensorMapping and provides a default battery sensor
    description.
    """

    description: SensorEntityDescription = field(
        default_factory=lambda: SensorEntityDescription(
            key="battery",
            device_class=SensorDeviceClass.BATTERY,
            native_unit_of_measurement=PERCENTAGE,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.MEASUREMENT,
        )
    )


@dataclass
class TuyaBLETemperatureMapping(TuyaBLESensorMapping):
    """
    Mapping for a Tuya BLE temperature sensor.

    Inherits from TuyaBLESensorMapping and provides a default temperature sensor
    description.
    """

    description: SensorEntityDescription = field(
        default_factory=lambda: SensorEntityDescription(
            key="temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
        )
    )


def is_co2_alarm_enabled(self: TuyaBLESensor, product: TuyaBLEProductInfo) -> bool:  # noqa: ARG001
    """
    Determine if the CO2 alarm is enabled for the given sensor and product.

    Parameters
    ----------
    self : TuyaBLESensor
        The sensor entity instance.
    product : TuyaBLEProductInfo
        The product information instance.

    Returns
    -------
    bool
        True if the CO2 alarm is enabled, False otherwise.

    """
    result: bool = True
    datapoint = self._device.datapoints[13]
    if datapoint:
        result = bool(datapoint.value)
    return result


def battery_enum_getter(self: TuyaBLESensor) -> None:
    """
    Set the battery percentage value for the sensor entity based on datapoint 104.

    Parameters
    ----------
    self : TuyaBLESensor
        The sensor entity instance.

    Returns
    -------
    None
        Sets the native value attribute for battery percentage.

    """
    datapoint = self._device.datapoints[104]
    if datapoint:
        self.set_native_value(int(datapoint.value) * 20.0)


@dataclass
class TuyaBLECategorySensorMapping:
    """
    Category sensor mapping for Tuya BLE devices.

    Attributes
    ----------
    products : dict[str, list[TuyaBLESensorMapping]] | None
        Mapping of product IDs to lists of sensor mappings.
    mapping : list[TuyaBLESensorMapping] | None
        Default sensor mapping for the category.

    """

    products: dict[str, list[TuyaBLESensorMapping]] | None = None
    mapping: list[TuyaBLESensorMapping] | None = None


@dataclass
class TuyaBLEWorkStateMapping(TuyaBLESensorMapping):
    """
    Mapping for a Tuya BLE work state sensor.

    Inherits from TuyaBLESensorMapping and provides a default work state sensor
    description.
    """

    description: SensorEntityDescription = field(
        default_factory=lambda: SensorEntityDescription(
            key="work_state",
            device_class=SensorDeviceClass.ENUM,
            options=[
                "auto",
                "manual",
                "idle",
            ],
        )
    )


mapping: dict[str, TuyaBLECategorySensorMapping] = {
    "cl": TuyaBLECategorySensorMapping(
        products={
            "kcy0x4pi": [  # Smart Curtain Robot 4
                TuyaBLEBatteryMapping(dp_id=13),  # battery_percentage
                TuyaBLESensorMapping(
                    dp_id=7,  # work_state
                    description=SensorEntityDescription(
                        key="work_state",
                        device_class=SensorDeviceClass.ENUM,
                        options=[
                            "standby",
                            "learning",
                            "success",
                            "fail",
                        ],
                    ),
                ),
                TuyaBLETemperatureMapping(
                    dp_id=103,  # temp_current
                    description=SensorEntityDescription(
                        key="temp_current",
                        device_class=SensorDeviceClass.TEMPERATURE,
                        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                        state_class=SensorStateClass.MEASUREMENT,
                        entity_registry_enabled_default=False,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=104,  # light_current
                    description=SensorEntityDescription(
                        key="light_current",
                        native_unit_of_measurement="%",
                        state_class=SensorStateClass.MEASUREMENT,
                        icon="mdi:brightness-percent",
                        entity_registry_enabled_default=False,
                    ),
                ),
            ],
            "ousymtkt": [  # Roller Blind Robot
                TuyaBLEBatteryMapping(dp_id=13),  # battery_percentage
                TuyaBLESensorMapping(
                    dp_id=3,  # work_state
                    description=SensorEntityDescription(
                        key="work_state",
                        device_class=SensorDeviceClass.ENUM,
                        options=[
                            "standby",
                            "opening",
                            "closing",
                        ],
                    ),
                ),
            ],
        },
    ),
    "co2bj": TuyaBLECategorySensorMapping(
        products={
            "59s19z5m": [  # CO2 Detector
                TuyaBLESensorMapping(
                    dp_id=1,
                    description=SensorEntityDescription(
                        key="carbon_dioxide_alarm",
                        icon="mdi:molecule-co2",
                        device_class=SensorDeviceClass.ENUM,
                        options=[
                            CO2_LEVEL_ALARM,
                            CO2_LEVEL_NORMAL,
                        ],
                    ),
                    is_available=is_co2_alarm_enabled,
                ),
                TuyaBLESensorMapping(
                    dp_id=2,
                    description=SensorEntityDescription(
                        key="carbon_dioxide",
                        device_class=SensorDeviceClass.CO2,
                        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLEBatteryMapping(dp_id=15),
                TuyaBLETemperatureMapping(dp_id=18),
                TuyaBLESensorMapping(
                    dp_id=19,
                    description=SensorEntityDescription(
                        key="humidity",
                        device_class=SensorDeviceClass.HUMIDITY,
                        native_unit_of_measurement=PERCENTAGE,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
            ]
        }
    ),
    "ms": TuyaBLECategorySensorMapping(
        products={
            **{
                key: [
                    TuyaBLESensorMapping(
                        dp_id=21,
                        description=SensorEntityDescription(
                            key="alarm_lock",
                            device_class=SensorDeviceClass.ENUM,
                            options=[
                                "wrong_finger",
                                "wrong_password",
                                "low_battery",
                            ],
                        ),
                    ),
                    TuyaBLEBatteryMapping(dp_id=8),
                ]
                for key in ["ludzroix", "isk2p555"]
            },
        }
    ),
    "szjqr": TuyaBLECategorySensorMapping(
        products={
            **{
                key: [
                    TuyaBLESensorMapping(
                        dp_id=7,
                        description=SensorEntityDescription(
                            key="battery_charging",
                            device_class=SensorDeviceClass.ENUM,
                            entity_category=EntityCategory.DIAGNOSTIC,
                            options=[
                                BATTERY_NOT_CHARGING,
                                BATTERY_CHARGING,
                                BATTERY_CHARGED,
                            ],
                        ),
                        icons=[
                            "mdi:battery",
                            "mdi:power-plug-battery",
                            "mdi:battery-check",
                        ],
                    ),
                    TuyaBLEBatteryMapping(dp_id=8),
                ]
                for key in ["3yqdo5yt", "xhf790if"]
            },
            **{
                key: [TuyaBLEBatteryMapping(dp_id=12)]
                for key in [
                    "blliqpsj",
                    "ndvkgsrm",
                    "yiihr7zh",
                    "neq16kgd",
                ]
            },
            **{
                key: [TuyaBLEBatteryMapping(dp_id=12)]
                for key in [
                    "ltak7e1p",
                    "y6kttvd6",
                    "yrnk7mnn",
                    "nvr2rocq",
                    "bnt7wajf",
                    "rvdceqjh",
                    "5xhbk964",
                ]
            },
        },
    ),
    "kg": TuyaBLECategorySensorMapping(
        products={
            **{
                key: [TuyaBLEBatteryMapping(dp_id=105)]
                for key in ["mknd4lci", "riecov42"]
            },
        },
    ),
    "wsdcg": TuyaBLECategorySensorMapping(
        products={
            "ojzlzzsw": [  # Soil moisture sensor
                TuyaBLETemperatureMapping(
                    dp_id=1,
                    coefficient=10.0,
                ),
                TuyaBLESensorMapping(
                    dp_id=2,
                    description=SensorEntityDescription(
                        key="moisture",
                        device_class=SensorDeviceClass.MOISTURE,
                        native_unit_of_measurement=PERCENTAGE,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=3,
                    description=SensorEntityDescription(
                        key="battery_state",
                        icon="mdi:battery",
                        device_class=SensorDeviceClass.ENUM,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        options=[
                            BATTERY_STATE_LOW,
                            BATTERY_STATE_NORMAL,
                            BATTERY_STATE_HIGH,
                        ],
                    ),
                    icons=[
                        "mdi:battery-alert",
                        "mdi:battery-50",
                        "mdi:battery-check",
                    ],
                ),
                TuyaBLEBatteryMapping(dp_id=4),
            ],
        },
    ),
    "zwjcy": TuyaBLECategorySensorMapping(
        products={
            "gvygg3m8": [  # Smartlife Plant Sensor SGS01
                TuyaBLETemperatureMapping(
                    dp_id=5,
                    coefficient=10.0,
                    description=SensorEntityDescription(
                        key="temp_current",
                        device_class=SensorDeviceClass.TEMPERATURE,
                        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=3,
                    description=SensorEntityDescription(
                        key="moisture",
                        device_class=SensorDeviceClass.MOISTURE,
                        native_unit_of_measurement=PERCENTAGE,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=14,
                    description=SensorEntityDescription(
                        key="battery_state",
                        icon="mdi:battery",
                        device_class=SensorDeviceClass.ENUM,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        options=[
                            BATTERY_STATE_LOW,
                            BATTERY_STATE_NORMAL,
                            BATTERY_STATE_HIGH,
                        ],
                    ),
                    icons=[
                        "mdi:battery-alert",
                        "mdi:battery-50",
                        "mdi:battery-check",
                    ],
                ),
                TuyaBLEBatteryMapping(
                    dp_id=15,
                    description=SensorEntityDescription(
                        key="battery_percentage",
                        device_class=SensorDeviceClass.BATTERY,
                        native_unit_of_measurement=PERCENTAGE,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
            ],
        },
    ),
    "znhsb": TuyaBLECategorySensorMapping(
        products={
            "cdlandip":  # Smart water bottle
            [
                TuyaBLETemperatureMapping(
                    dp_id=101,
                ),
                TuyaBLESensorMapping(
                    dp_id=102,
                    description=SensorEntityDescription(
                        key="water_intake",
                        device_class=SensorDeviceClass.WATER,
                        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=104,
                    description=SensorEntityDescription(
                        key="battery",
                        device_class=SensorDeviceClass.BATTERY,
                        native_unit_of_measurement=PERCENTAGE,
                        entity_category=EntityCategory.DIAGNOSTIC,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                    getter=battery_enum_getter,
                ),
            ],
        },
    ),
    "ggq": TuyaBLECategorySensorMapping(
        products={
            "6pahkcau": [  # Irrigation computer
                TuyaBLEBatteryMapping(dp_id=11),
                TuyaBLESensorMapping(
                    dp_id=6,
                    description=SensorEntityDescription(
                        key="time_left",
                        device_class=SensorDeviceClass.DURATION,
                        native_unit_of_measurement=UnitOfTime.MINUTES,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
            ],
            "hfgdqhho": [  # Irrigation computer - SGW02
                TuyaBLEBatteryMapping(dp_id=11),
                TuyaBLESensorMapping(
                    dp_id=111,
                    description=SensorEntityDescription(
                        key="use_time_z1",
                        device_class=SensorDeviceClass.DURATION,
                        native_unit_of_measurement=UnitOfTime.SECONDS,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=110,
                    description=SensorEntityDescription(
                        key="use_time_z2",
                        device_class=SensorDeviceClass.DURATION,
                        native_unit_of_measurement=UnitOfTime.SECONDS,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
            ],
            "fnlw6npo": [  # Irrigation computer - BWV-YC02S
                TuyaBLEBatteryMapping(dp_id=11),
                TuyaBLESensorMapping(
                    dp_id=111,
                    description=SensorEntityDescription(
                        key="use_time_z1",
                        device_class=SensorDeviceClass.DURATION,
                        native_unit_of_measurement=UnitOfTime.SECONDS,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=110,
                    description=SensorEntityDescription(
                        key="use_time_z2",
                        device_class=SensorDeviceClass.DURATION,
                        native_unit_of_measurement=UnitOfTime.SECONDS,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
            ],
        },
    ),
    "sfkzq": TuyaBLECategorySensorMapping(
        products={
            "nxquc5lb": [  # Smart water timer - SOP10
                TuyaBLEBatteryMapping(dp_id=7),
                TuyaBLEWorkStateMapping(dp_id=12),
                TuyaBLESensorMapping(
                    dp_id=15,
                    description=SensorEntityDescription(
                        key="use_time_one",
                        device_class=SensorDeviceClass.DURATION,
                        native_unit_of_measurement=UnitOfTime.SECONDS,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
                TuyaBLESensorMapping(
                    dp_id=9,
                    description=SensorEntityDescription(
                        key="use_time",
                        device_class=SensorDeviceClass.DURATION,
                        native_unit_of_measurement=UnitOfTime.SECONDS,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                ),
            ],
        },
    ),
}


def rssi_getter(sensor: TuyaBLESensor) -> None:
    """
    Set the signal strength value for the sensor entity.

    Parameters
    ----------
    sensor : TuyaBLESensor
        The sensor entity instance.

    Returns
    -------
    None
        Sets the native value attribute for signal strength.

    """
    sensor.set_native_value(sensor.device.rssi)


rssi_mapping = TuyaBLESensorMapping(
    dp_id=SIGNAL_STRENGTH_DP_ID,
    description=SensorEntityDescription(
        key="signal_strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    getter=rssi_getter,
)


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLESensorMapping]:
    """
    Retrieve the sensor mapping for a given Tuya BLE device.

    Parameters
    ----------
    device : TuyaBLEDevice
        The Tuya BLE device instance.

    Returns
    -------
    list[TuyaBLESensorMapping]
        List of sensor mappings for the device.

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


class TuyaBLESensor(TuyaBLEEntity, SensorEntity):
    """Representation of a Tuya BLE sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLEPassiveCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLESensorMapping,
    ) -> None:
        """
        Initialize a Tuya BLE sensor entity.

        Parameters
        ----------
        hass : HomeAssistant
            The Home Assistant instance.
        coordinator : TuyaBLEPassiveCoordinator
            The data update coordinator.
        device : TuyaBLEDevice
            The Tuya BLE device instance.
        product : TuyaBLEProductInfo
            The product information instance.
        mapping : TuyaBLESensorMapping
            The sensor mapping configuration.

        """
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping

    @property
    def device(self) -> TuyaBLEDevice:
        """Return the underlying Tuya BLE device."""
        return self._device

    def set_native_value(
        self,
        value: str | float | None | date | datetime | Decimal,
    ) -> None:
        """Set the native value for the sensor entity."""
        self._attr_native_value = value

    @callback
    def _handle_coordinator_update(self) -> None:
        def decode_value(value: object) -> str:
            if isinstance(value, (bytes, bytearray)):
                return value.decode("utf-8", errors="replace")
            if isinstance(value, memoryview):
                return str(value)
            return str(value)

        if self._mapping.getter is not None:
            self._mapping.getter(self)
        else:
            datapoint = self._device.datapoints[self._mapping.dp_id]
            if not datapoint:
                self.async_write_ha_state()
                return

            value = datapoint.value
            dp_type = datapoint.type

            if dp_type == TuyaBLEDataPointType.DT_ENUM:
                options = self.entity_description.options
                if options and isinstance(value, int) and 0 <= value < len(options):
                    self._attr_native_value = options[value]
                else:
                    self._attr_native_value = decode_value(value)
                if (
                    self._mapping.icons
                    and isinstance(value, int)
                    and 0 <= value < len(self._mapping.icons)
                ):
                    self._attr_icon = self._mapping.icons[value]
            elif dp_type == TuyaBLEDataPointType.DT_VALUE:
                if isinstance(value, (int, float)):
                    self._attr_native_value = value / self._mapping.coefficient
                else:
                    self._attr_native_value = decode_value(value)
            else:
                self._attr_native_value = decode_value(value)

        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        result = super().available
        if result and callable(self._mapping.is_available):
            result = self._mapping.is_available(self, self._product)
        return result


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Set up Tuya BLE sensor entities for a config entry.

    Parameters
    ----------
    hass : HomeAssistant
        The Home Assistant instance.
    entry : ConfigEntry
        The configuration entry.
    async_add_entities : AddEntitiesCallback
        Callback to add entities.

    Returns
    -------
    None
        Sets up sensor entities for the Tuya BLE integration.

    """
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)
    entities: list[TuyaBLESensor] = [
        TuyaBLESensor(
            hass,
            data.coordinator,
            data.device,
            data.product,
            rssi_mapping,
        )
    ]
    entities.extend(
        [
            TuyaBLESensor(
                hass,
                data.coordinator,
                data.device,
                data.product,
                mapping,
            )
            for mapping in mappings
            if mapping.force_add
            or data.device.datapoints.has_id(mapping.dp_id, mapping.dp_type)
        ]
    )
    async_add_entities(entities)
