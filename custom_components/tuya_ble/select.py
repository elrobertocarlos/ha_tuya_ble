"""The Tuya BLE integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.components.select import (
    SelectEntity,
    SelectEntityDescription,
)
from homeassistant.const import EntityCategory, UnitOfTemperature

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    FINGERBOT_MODE_PROGRAM,
    FINGERBOT_MODE_PUSH,
    FINGERBOT_MODE_SWITCH,
)
from .devices import (
    TuyaBLEData,
    TuyaBLEEntity,
    TuyaBLEPassiveCoordinator,
    TuyaBLEProductInfo,
)
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)


@dataclass
class TuyaBLESelectMapping:
    """
    Mapping configuration for a Tuya BLE select entity.

    Attributes:
        dp_id: The datapoint ID associated with the select entity.
        description: The entity description for the select entity.
        force_add: Whether to force add the entity even if the datapoint is not present.
        dp_type: The type of the datapoint, if specified.

    """

    dp_id: int
    description: SelectEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None


@dataclass(frozen=True)
class TemperatureUnitDescription(SelectEntityDescription):
    """Entity description for temperature unit selection in Tuya BLE devices."""

    key: str = "temperature_unit"
    icon: str = "mdi:thermometer"
    entity_category: EntityCategory = EntityCategory.CONFIG


@dataclass
class TuyaBLEFingerbotModeMapping(TuyaBLESelectMapping):
    """Mapping for the fingerbot mode select entity in Tuya BLE devices."""

    description: SelectEntityDescription = field(
        default_factory=lambda: SelectEntityDescription(
            key="fingerbot_mode",
            entity_category=EntityCategory.CONFIG,
            options=[
                FINGERBOT_MODE_PUSH,
                FINGERBOT_MODE_SWITCH,
                FINGERBOT_MODE_PROGRAM,
            ],
        )
    )


@dataclass
class TuyaBLEWeatherDelayMapping(TuyaBLESelectMapping):
    """Mapping for the weather delay select entity in Tuya BLE devices."""

    description: SelectEntityDescription = field(
        default_factory=lambda: SelectEntityDescription(
            key="weather_delay",
            entity_category=EntityCategory.CONFIG,
            options=[
                "cancel",
                "24h",
                "48h",
                "72h",
                "96h",
                "120h",
                "144h",
                "168h",
            ],
        )
    )


@dataclass
class TuyaBLESmartWeatherMapping(TuyaBLESelectMapping):
    """Mapping for the smart weather select entity in Tuya BLE devices."""

    description: SelectEntityDescription = field(
        default_factory=lambda: SelectEntityDescription(
            key="smart_weather",
            entity_category=EntityCategory.CONFIG,
            options=[
                "sunny",
                "cloudy",
                "rainy",
            ],
        )
    )


@dataclass
class TuyaBLECategorySelectMapping:
    """
    Mapping for Tuya BLE select entities by category and product.

    Attributes:
        products: Optional dictionary mapping product IDs to lists
            of TuyaBLESelectMapping.
        mapping: Optional list of TuyaBLESelectMapping for the category.

    """

    products: dict[str, list[TuyaBLESelectMapping]] | None = None
    mapping: list[TuyaBLESelectMapping] | None = None


mapping: dict[str, TuyaBLECategorySelectMapping] = {
    "co2bj": TuyaBLECategorySelectMapping(
        products={
            "59s19z5m":  # CO2 Detector
            [
                TuyaBLESelectMapping(
                    dp_id=101,
                    description=TemperatureUnitDescription(
                        options=[
                            UnitOfTemperature.CELSIUS,
                            UnitOfTemperature.FAHRENHEIT,
                        ],
                    ),
                ),
            ],
        },
    ),
    "ms": TuyaBLECategorySelectMapping(
        products={
            **{
                k: [
                    TuyaBLESelectMapping(
                        dp_id=31,
                        description=SelectEntityDescription(
                            key="beep_volume",
                            options=[
                                "mute",
                                "low",
                                "normal",
                                "high",
                            ],
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                ]
                for k in ["ludzroix", "isk2p555"]  # Smart Lock
            },
        }
    ),
    "kg": TuyaBLECategorySelectMapping(
        products={
            **{
                k: [TuyaBLEFingerbotModeMapping(dp_id=101)] for k in ["mknd4lci"]
            },  # Fingerbot Plus
        },
    ),
    "szjqr": TuyaBLECategorySelectMapping(
        products={
            **{
                k: [TuyaBLEFingerbotModeMapping(dp_id=2)]
                for k in ["3yqdo5yt", "xhf790if"]
            },  # CubeTouch 1s and II
            **{
                k: [TuyaBLEFingerbotModeMapping(dp_id=8)]
                for k in ["blliqpsj", "ndvkgsrm", "yiihr7zh", "neq16kgd"]
            },  # Fingerbot Plus
            **{
                k: [TuyaBLEFingerbotModeMapping(dp_id=8)]
                for k in [
                    "ltak7e1p",
                    "y6kttvd6",
                    "yrnk7mnn",
                    "nvr2rocq",
                    "bnt7wajf",
                    "rvdceqjh",
                    "5xhbk964",
                ]
            },  # Fingerbot
        },
    ),
    "wsdcg": TuyaBLECategorySelectMapping(
        products={
            "ojzlzzsw":  # Soil moisture sensor
            [
                TuyaBLESelectMapping(
                    dp_id=9,
                    description=TemperatureUnitDescription(
                        options=[
                            UnitOfTemperature.CELSIUS,
                            UnitOfTemperature.FAHRENHEIT,
                        ],
                        entity_registry_enabled_default=False,
                    ),
                ),
            ],
        },
    ),
    "znhsb": TuyaBLECategorySelectMapping(
        products={
            "cdlandip":  # Smart water bottle
            [
                TuyaBLESelectMapping(
                    dp_id=106,
                    description=TemperatureUnitDescription(
                        options=[
                            UnitOfTemperature.CELSIUS,
                            UnitOfTemperature.FAHRENHEIT,
                        ],
                    ),
                ),
                TuyaBLESelectMapping(
                    dp_id=107,
                    description=SelectEntityDescription(
                        key="reminder_mode",
                        options=[
                            "interval_reminder",
                            "schedule_reminder",
                        ],
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
        },
    ),
    "sfkzq": TuyaBLECategorySelectMapping(
        products={
            "nxquc5lb": [  # Smart water timer - SOP10
                TuyaBLEWeatherDelayMapping(dp_id=10),
                TuyaBLESmartWeatherMapping(dp_id=13),
            ],
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLESelectMapping]:
    """
    Retrieve the list of TuyaBLESelectMapping objects for a given Tuya BLE device.

    Args:
        device: The TuyaBLEDevice instance to look up.

    Returns:
        A list of TuyaBLESelectMapping objects associated with the device's
        category and product_id.

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


class TuyaBLESelect(TuyaBLEEntity, SelectEntity):
    """Representation of a Tuya BLE select."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLEPassiveCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLESelectMapping,
    ) -> None:
        """
        Initialize a Tuya BLE select entity.

        Args:
            hass: The HomeAssistant instance.
            coordinator: The update coordinator for passive updates.
            device: The Tuya BLE device.
            product: The product information for the device.
            mapping: The select mapping configuration.

        """
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping
        self._attr_options = mapping.description.options or []

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        value = None
        result = None
        datapoint = self._device.datapoints[self._mapping.dp_id]
        if datapoint:
            value = datapoint.value
            try:
                idx = int(value)
                if 0 <= idx < len(self._attr_options):
                    result = self._attr_options[idx]
            except (ValueError, TypeError):
                if isinstance(value, str):
                    result = value
                elif isinstance(value, bytes):
                    try:
                        result = value.decode()
                    except UnicodeDecodeError:
                        result = str(value)
                elif isinstance(value, (int, bool)):
                    result = str(value)
        return result

    def select_option(self, value: str) -> None:
        """Change the selected option."""
        if value in self._attr_options:
            int_value = self._attr_options.index(value)
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.dp_id,
                TuyaBLEDataPointType.DT_ENUM,
                int_value,
            )
            if datapoint:
                self._hass.create_task(datapoint.set_value(int_value))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE sensors."""
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)
    entities: list[TuyaBLESelect] = [
        TuyaBLESelect(
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
    async_add_entities(entities)
