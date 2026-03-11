"""The Tuya BLE integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityDescription,
)

from .const import DOMAIN
from .devices import (
    TuyaBLEData,
    TuyaBLEEntity,
    TuyaBLEPassiveCoordinator,
    TuyaBLEProductInfo,
)
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

TuyaBLECoverIsAvailable = Callable[["TuyaBLECover", TuyaBLEProductInfo], bool] | None


@dataclass
class TuyaBLECoverMapping:
    """
    Mapping configuration for a Tuya BLE cover entity.

    Attributes
    ----------
    dp_id : int
        The primary datapoint ID for the cover (typically current position).
    description : CoverEntityDescription
        The entity description including device class and key.
    force_add : bool
        Whether to force add the entity even if datapoint is not available.
    dp_type : TuyaBLEDataPointType | None
        The expected datapoint type.
    is_available : TuyaBLECoverIsAvailable
        Optional callback to determine if the cover is available.
    position_dp_id : int | None
        The datapoint ID for setting cover position.
    control_dp_id : int | None
        The datapoint ID for control commands (open/close/stop).

    """

    dp_id: int
    description: CoverEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    is_available: TuyaBLECoverIsAvailable = None
    # Data point IDs for position and control
    position_dp_id: int | None = None
    control_dp_id: int | None = None


@dataclass
class TuyaBLECategoryCoverMapping:
    """
    Category-level mapping configuration for Tuya BLE cover entities.

    Attributes
    ----------
    products : dict[str, list[TuyaBLECoverMapping]] | None
        Product-specific mappings keyed by product ID.
    mapping : list[TuyaBLECoverMapping] | None
        Category-level mappings applied to all products in the category.

    """

    products: dict[str, list[TuyaBLECoverMapping]] | None = None
    mapping: list[TuyaBLECoverMapping] | None = None


mapping: dict[str, TuyaBLECategoryCoverMapping] = {
    "cl": TuyaBLECategoryCoverMapping(
        products={
            "kcy0x4pi": [  # Smart Curtain Robot
                TuyaBLECoverMapping(
                    dp_id=3,  # percent_state - current position
                    description=CoverEntityDescription(
                        key="curtain",
                        device_class=CoverDeviceClass.CURTAIN,
                    ),
                    position_dp_id=2,  # percent_control - for setting position
                    control_dp_id=1,  # control - for open/close/stop commands
                ),
            ],
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLECoverMapping]:
    """
    Get cover mappings for a Tuya BLE device.

    Parameters
    ----------
    device : TuyaBLEDevice
        The Tuya BLE device to get mappings for.

    Returns
    -------
    list[TuyaBLECoverMapping]
        List of cover mappings for the device, or empty list if none found.

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


class TuyaBLECover(TuyaBLEEntity, CoverEntity):
    """Representation of a Tuya BLE Cover."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLEPassiveCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLECoverMapping,
    ) -> None:
        """Initialize a Tuya BLE cover entity."""
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping

    @property
    def current_cover_position(self) -> int | None:
        """Return current position of cover."""
        datapoint = self._device.datapoints.get_or_create(
            self._mapping.dp_id,
            self._mapping.dp_type or TuyaBLEDataPointType.DT_VALUE,
            0,
        )
        if datapoint:
            # Device uses inverted position: 0=open, 100=closed
            # Home Assistant standard: 0=closed, 100=open
            # So we invert the value
            raw_position = int(datapoint.value) if datapoint.value is not None else None
            return (100 - raw_position) if raw_position is not None else None
        return None

    @property
    def is_closed(self) -> bool | None:
        """Return if cover is closed."""
        position = self.current_cover_position
        if position is None:
            return None
        return position == 0

    @property
    def is_opening(self) -> bool:
        """Return if cover is opening."""
        # We don't have direct feedback on whether it's opening,
        # so return False for now
        return False

    @property
    def is_closing(self) -> bool:
        """Return if cover is closing."""
        # We don't have direct feedback on whether it's closing,
        # so return False for now
        return False

    def open_cover(self, **_kwargs: Any) -> None:
        """Open the cover."""
        if self._mapping.control_dp_id:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.control_dp_id,
                TuyaBLEDataPointType.DT_ENUM,
                0,
            )
            if datapoint:
                self._hass.create_task(datapoint.set_value(0))

    def close_cover(self, **_kwargs: Any) -> None:
        """Close the cover."""
        if self._mapping.control_dp_id:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.control_dp_id,
                TuyaBLEDataPointType.DT_ENUM,
                2,
            )
            if datapoint:
                self._hass.create_task(datapoint.set_value(2))

    def stop_cover(self, **_kwargs: Any) -> None:
        """Stop the cover."""
        if self._mapping.control_dp_id:
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.control_dp_id,
                TuyaBLEDataPointType.DT_ENUM,
                1,
            )
            if datapoint:
                self._hass.create_task(datapoint.set_value(1))

    def set_cover_position(self, **kwargs: Any) -> None:
        """Set cover position."""
        if ATTR_POSITION in kwargs and self._mapping.position_dp_id:
            position = kwargs[ATTR_POSITION]
            # Device uses inverted position, so invert the value
            inverted_position = 100 - int(position)
            datapoint = self._device.datapoints.get_or_create(
                self._mapping.position_dp_id,
                TuyaBLEDataPointType.DT_VALUE,
                0,
            )
            if datapoint:
                self._hass.create_task(datapoint.set_value(inverted_position))

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        result = super().available
        if result and self._mapping.is_available is not None:
            result = self._mapping.is_available(self, self._product)
        return result

    @property
    def supported_features(self) -> int:
        """Return the supported features."""
        features = 0
        # Support opening/closing via commands
        if self._mapping.control_dp_id:
            features |= (
                0x1  # OPEN
                | 0x2  # CLOSE
                | 0x4  # STOP
            )
        # Support position setting
        if self._mapping.position_dp_id:
            features |= 0x8  # SET_POSITION
        return features


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE covers."""
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)

    entities: list[TuyaBLECover] = [
        TuyaBLECover(
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
