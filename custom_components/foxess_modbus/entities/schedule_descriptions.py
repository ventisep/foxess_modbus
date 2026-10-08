"""Model/firmware specifications for read-only schedule support."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..common.types import Inv
from ..common.types import RegisterType
from .modbus_schedule_config import ModbusScheduleAddressConfig

if TYPE_CHECKING:
    from .entity_factory import EntityFactory


@dataclass(frozen=True)
class ScheduleAddressSpec:
    """Match a scheduler layout to the profile's firmware-specific Inv flag."""

    models: Inv
    config: ModbusScheduleAddressConfig


class ModbusScheduleFactory:
    """Use one capability specification for both the manager and its sensors."""

    def __init__(self, addresses: list[ScheduleAddressSpec]) -> None:
        self.address_specs = addresses

    def create_if_supported(
        self, inverter_model: Inv, register_type: RegisterType
    ) -> ModbusScheduleAddressConfig | None:
        matches = [
            spec.config
            for spec in self.address_specs
            if inverter_model in spec.models and register_type == spec.config.register_type
        ]
        assert len(matches) <= 1, "Multiple schedule configurations match this profile"
        return matches[0] if matches else None

    @property
    def entity_descriptions(self) -> list["EntityFactory"]:
        # Import here to keep the capability configuration independent of sensors.
        from .modbus_schedule_sensor import ModbusScheduleSensorDescription

        return [
            ModbusScheduleSensorDescription(
                key="schedule_entries", name="Schedule Entries", factory=self, icon="mdi:calendar-clock"
            ),
            ModbusScheduleSensorDescription(
                key="remaining_time", name="Remaining Time", factory=self, icon="mdi:calendar-clock"
            ),
        ]


SCHEDULE_DESCRIPTION = ModbusScheduleFactory(
    addresses=[
        ScheduleAddressSpec(
            models=Inv.PQ1,
            config=ModbusScheduleAddressConfig(
                register_type=RegisterType.HOLDING,
                first_record_address=48010,
                record_size=10,
                # PQ1 supports 95 explicit schedules plus Remaining Time, covering
                # 48010-48969. Other model/firmware specs can select another range.
                max_records=96,
                work_mode_map={
                    1: "Self Use",
                    2: "Feed-in Priority",
                    3: "Back-up",
                    6: "Force Charge",
                    7: "Force Discharge",
                },
            ),
        )
    ]
)
