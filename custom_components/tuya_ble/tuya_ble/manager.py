"""
Manager module for Tuya BLE device credentials and device manager.

This module provides:
- TuyaBLEDeviceCredentials: dataclass for storing Tuya BLE device credentials
- AbstaractTuyaBLEDeviceManager: abstract base class for managing device credentials
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TuyaBLEDeviceCredentials:
    """
    Credentials for a Tuya BLE device.

    Attributes
    ----------
    uuid : str
        The unique identifier of the device.
    local_key : str
        The local encryption key for the device.
    device_id : str
        The device identifier.
    category : str
        The device category.
    product_id : str
        The product identifier.
    device_name : str | None
        The name of the device.
    product_model : str | None
        The product model.
    product_name : str | None
        The product name.

    """

    uuid: str
    local_key: str
    device_id: str
    category: str
    product_id: str
    device_name: str | None
    product_model: str | None
    product_name: str | None

    def __str__(self) -> str:
        """Return a string representation of the device credentials."""
        return (
            "uuid: xxxxxxxxxxxxxxxx, "
            "local_key: xxxxxxxxxxxxxxxx, "
            "device_id: xxxxxxxxxxxxxxxx, "
            f"category: {self.category}, "
            f"product_id: {self.product_id}, "
            f"device_name: {self.device_name}, "
            f"product_model: {self.product_model}, "
            f"product_name: {self.product_name}"
        )

    @classmethod
    def create(  # noqa: PLR0913
        cls,
        uuid: str,
        local_key: str,
        device_id: str,
        category: str,
        product_id: str,
        device_name: str | None = None,
        product_model: str | None = None,
        product_name: str | None = None,
    ) -> TuyaBLEDeviceCredentials:
        """
        Create device credentials from individual fields.

        Parameters
        ----------
        uuid : str
            The unique identifier of the device.
        local_key : str
            The local encryption key for the device.
        device_id : str
            The device identifier.
        category : str
            The device category.
        product_id : str
            The product identifier.
        device_name : str | None, optional
            The name of the device, by default None.
        product_model : str | None, optional
            The product model, by default None.
        product_name : str | None, optional
            The product name, by default None.

        Returns
        -------
        TuyaBLEDeviceCredentials
            The credentials object with the provided fields.

        """
        return cls(
            uuid,
            local_key,
            device_id,
            category,
            product_id,
            device_name,
            product_model,
            product_name,
        )


class AbstaractTuyaBLEDeviceManager(ABC):
    """Abstaract manager of the Tuya BLE devices credentials."""

    @abstractmethod
    async def get_device_credentials(
        self,
        address: str,
        *,
        force_update: bool = False,
        save_data: bool = False,
    ) -> TuyaBLEDeviceCredentials | None:
        """Get credentials of the Tuya BLE device."""
