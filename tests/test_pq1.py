"""PQ1 monitoring and the boundaries of its provisional register map."""

import re
from collections.abc import Iterator
from collections.abc import Mapping
from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from custom_components.foxess_modbus.client.modbus_client import ModbusClient
from custom_components.foxess_modbus.common.entity_controller import ModbusControllerEntity
from custom_components.foxess_modbus.common.exceptions import AutoconnectFailedError
from custom_components.foxess_modbus.common.types import ConnectionType
from custom_components.foxess_modbus.common.types import Inv
from custom_components.foxess_modbus.common.types import InverterModel
from custom_components.foxess_modbus.common.types import RegisterType
from custom_components.foxess_modbus.const import ENTITY_ID_PREFIX
from custom_components.foxess_modbus.const import FRIENDLY_NAME
from custom_components.foxess_modbus.const import INVERTER_BASE
from custom_components.foxess_modbus.const import INVERTER_CONN
from custom_components.foxess_modbus.const import INVERTER_MODEL
from custom_components.foxess_modbus.const import MAX_READ
from custom_components.foxess_modbus.const import UNIQUE_ID_PREFIX
from custom_components.foxess_modbus.entities.entity_descriptions import ENTITIES
from custom_components.foxess_modbus.entities.modbus_enum_sensor import ModbusEnumSensorDescription
from custom_components.foxess_modbus.entities.modbus_sensor import ModbusSensor
from custom_components.foxess_modbus.inverter_profiles import INVERTER_PROFILES
from custom_components.foxess_modbus.inverter_profiles import inverter_connection_type_profile_from_config
from custom_components.foxess_modbus.modbus_controller import ModbusController


@pytest.fixture
def controller(hass: HomeAssistant) -> Iterator[ModbusController]:
    details = {
        INVERTER_BASE: InverterModel.PQ1,
        INVERTER_MODEL: "PQ1-8.0",
        INVERTER_CONN: ConnectionType.LAN,
        ENTITY_ID_PREFIX: "pq1",
        UNIQUE_ID_PREFIX: "pq1",
        FRIENDLY_NAME: "PQ1",
    }
    result = ModbusController(
        hass, AsyncMock(spec=ModbusClient), inverter_connection_type_profile_from_config(details), details, 247, 10, 20
    )
    yield result
    result.unload()


@pytest.fixture
def sensors(controller: ModbusController) -> dict[str, SensorEntity]:
    profile = inverter_connection_type_profile_from_config(controller.inverter_details)
    result = {}
    for entity in profile.create_entities(SensorEntity, controller, filter_depends_on_other_entites=False):
        sensor = cast(SensorEntity, entity)
        assert sensor.entity_description.key not in result
        result[sensor.entity_description.key] = sensor
        controller.register_modbus_entity(cast(ModbusControllerEntity, sensor))
    return result


def set_registers(controller: ModbusController, values: Mapping[int, int | None]) -> None:
    for address, value in values.items():
        controller._data[address].read_value = value  # noqa: SLF001


def numeric_value(sensor: SensorEntity) -> int | float | None:
    return cast(ModbusSensor, sensor)._calculate_native_value()  # noqa: SLF001


@pytest.mark.parametrize("packed", [False, True])
async def test_detect_pq1(packed: bool) -> None:
    client = AsyncMock(spec=ModbusClient)
    chars = list(b"PQ1-8.0 ")
    words = [(chars[i] << 8) | chars[i + 1] for i in range(0, len(chars), 2)] if packed else chars
    words += [0] * (15 - len(words))
    client.read_registers.side_effect = lambda start, count, *_: words[start - 30000 : start - 30000 + count]
    assert await ModbusController.autodetect(client, 247, {MAX_READ: 4}) == (InverterModel.PQ1, "PQ1-8.0")
    assert all(call.args[2:] == (RegisterType.HOLDING, 247) for call in client.read_registers.call_args_list)
    client.close.assert_awaited_once()
    client.write_registers.assert_not_awaited()


async def test_reject_unrecognised_pq1_suffix() -> None:
    client = AsyncMock(spec=ModbusClient)
    client.read_registers.return_value = list(b"PQ1-8.0-OTHER") + [0] * 3
    with pytest.raises(AutoconnectFailedError):
        await ModbusController.autodetect(client, 247, {MAX_READ: 20})
    client.close.assert_awaited_once()


def test_profile_and_read_only_entities(controller: ModbusController, sensors: dict[str, SensorEntity]) -> None:
    profile = inverter_connection_type_profile_from_config(controller.inverter_details)
    assert profile is INVERTER_PROFILES[InverterModel.PQ1].connection_types[ConnectionType.AUX]
    assert profile.register_type == RegisterType.HOLDING
    assert profile.get_inv_for_version(None) == Inv.PQ1
    assert controller.inverter_capacity == 8000
    assert re.match(profile.inverter_model_profile.model_pattern, "P1-8.0-E") is None
    assert controller.remote_control_manager is None
    assert controller.charge_periods == []
    assert profile.create_entities(NumberEntity, controller) == []
    assert profile.create_entities(SelectEntity, controller) == []
    assert not any(
        factory.depends_on_other_entities for factory in ENTITIES if factory.serialize(Inv.PQ1, RegisterType.HOLDING)
    )
    addresses = {a for entity in sensors.values() for a in cast(ModbusControllerEntity, entity).addresses}
    assert set(range(31020, 31029)) <= addresses
    assert set(range(32000, 32024)) <= addresses
    assert not addresses.intersection(range(41001, 41007))
    assert not addresses.intersection({39135, 44003, 46001, 37700, 38307, 38914, 39601})
    assert not addresses.intersection(range(48010, 48970))
    assert cast(ModbusControllerEntity, sensors["pv_power_now"]).addresses == [39118]
    assert "pv1_energy_total" not in sensors
    assert "pv5_power" not in sensors
    assert "work_mode" not in sensors
    for pv in range(1, 5):
        assert f"pv{pv}_voltage" in sensors
        assert f"pv{pv}_current" in sensors
        assert f"pv{pv}_power" in sensors


@pytest.mark.parametrize("max_read", [1, 8, 20, 125])
async def test_poll_ranges_avoid_invalid_block(
    controller: ModbusController, sensors: dict[str, SensorEntity], max_read: int
) -> None:
    assert sensors
    controller._max_read = max_read  # noqa: SLF001
    ranges = list(controller._create_read_ranges(max_read, is_initial_connection=True))  # noqa: SLF001
    polled = {a for start, count in ranges for a in range(start, start + count)}
    assert {41000, 41007, 41008, 41009, 41010, 41011} <= polled
    assert not polled.intersection(range(41001, 41007))
    assert all(1 <= count <= max_read for _, count in ranges)
    client = cast(AsyncMock, controller._client)  # noqa: SLF001
    client.read_registers.side_effect = lambda _start, count, *_: [0] * count
    await controller._read_all_registers()  # noqa: SLF001
    client.write_registers.assert_not_awaited()
    assert all(call.args[2:] == (RegisterType.HOLDING, 247) for call in client.read_registers.call_args_list)


@pytest.mark.parametrize(
    ("key", "values", "expected"),
    [
        ("pv3_voltage", {39074: 2561}, 256.1),
        ("pv3_current", {39075: 150}, 1.5),
        ("pv3_power", {39284: 395}, 0.395),
        ("pv_power_now", {39118: 1287}, 1.287),
        ("invbatvolt", {31020: 4000}, 400),
        ("invbatcurrent", {31021: 65521}, -1.5),
        ("invbatpower", {31022: 64492}, -1.044),
        ("battery_charge", {31022: 64492}, 1.044),
        ("battery_discharge", {31022: 64492}, 0),
        ("battery_charge", {31022: 1044}, 0),
        ("battery_discharge", {31022: 1044}, 1.044),
        ("battery_temp", {31023: 275}, 27.5),
        ("battery_soc", {31024: 97, 31028: 0, 37002: 2}, 97),
        ("bms_charge_rate", {31025: 500}, 50),
        ("bms_discharge_rate", {31026: 500}, 50),
        ("bms_kwh_remaining", {37632: 1920}, 19.2),
        ("rfreq", {39139: 4991}, 49.91),
        ("max_charge_current", {41007: 500}, 50),
        ("min_soc", {41009: 10}, 10),
        ("max_soc", {41010: 100}, 100),
        ("grid_ct", {31014: 64536}, -1),
        ("grid_consumption", {31014: 64536}, 1),
        ("feed_in", {31014: 1000}, 1),
        ("export_power_limit", {46616: 0, 46617: 15000}, 15000),
        ("export_power_limit", {46616: 1, 46617: 4464}, 70000),
        ("solar_energy_total", {32000: 1, 32001: 2}, 6553.8),
        ("pq1_register_44000", {44000: 12}, 12),
        ("pq1_register_31027", {31027: 65535}, 65535),
    ],
)
def test_decoding(
    controller: ModbusController, sensors: dict[str, SensorEntity], key: str, values: dict[int, int], expected: float
) -> None:
    set_registers(controller, values)
    assert numeric_value(sensors[key]) == pytest.approx(expected)


def test_experimental_metadata_and_missing_words(
    controller: ModbusController, sensors: dict[str, SensorEntity]
) -> None:
    energy = sensors["solar_energy_total"]
    set_registers(controller, {32000: None, 32001: 10})
    assert numeric_value(energy) is None
    assert energy.entity_description.name == "Solar Generation Total (Experimental)"
    assert energy.entity_description.entity_category == EntityCategory.DIAGNOSTIC
    assert energy.entity_description.entity_registry_enabled_default is False
    assert energy.entity_description.state_class is None
    assert energy.extra_state_attributes == {
        "mapping_status": "provisional",
        "raw_registers": {"32001": 10, "32000": None},
    }
    assert sensors["battery_temp"].entity_description.name == "Battery Temp (Experimental)"
    assert sensors["battery_soc"].entity_description.name == "Battery SoC"
    assert sensors["battery_soc"].extra_state_attributes is None
    assert sensors["pq1_register_44000"].entity_description.entity_registry_enabled_default is False


def test_battery_state_does_not_use_unverified_connection_flags(
    controller: ModbusController, sensors: dict[str, SensorEntity]
) -> None:
    set_registers(controller, {31024: 97, 31028: 0, 37002: 2})
    sensor = sensors["battery_soc"]
    with patch.object(sensor, "schedule_update_ha_state"):
        cast(ModbusControllerEntity, sensor).update_callback({31024})
    assert sensor.native_value == 97


def test_experimental_settings_do_not_leak_to_p1(
    controller: ModbusController, sensors: dict[str, SensorEntity]
) -> None:
    profile = INVERTER_PROFILES[InverterModel.P1].connection_types[ConnectionType.AUX]
    p1_sensors = {
        entity.entity_description.key: cast(SensorEntity, entity)
        for entity in profile.create_entities(SensorEntity, controller, filter_depends_on_other_entites=False)
    }
    for key in ("solar_energy_total", "invbatcurrent", "battery_temp", "pv1_power"):
        assert str(sensors[key].entity_description.name).endswith("(Experimental)")
        assert not str(p1_sensors[key].entity_description.name).endswith("(Experimental)")
        assert p1_sensors[key].entity_description.entity_registry_enabled_default
        assert p1_sensors[key].entity_description.state_class is not None


def test_enum_serialization_does_not_mutate_mode_map(
    controller: ModbusController, sensors: dict[str, SensorEntity]
) -> None:
    description = sensors["manual_work_mode"].entity_description
    assert isinstance(description, ModbusEnumSensorDescription)
    serialized = description.serialize(Inv.PQ1, RegisterType.HOLDING)
    assert serialized is not None
    serialized["options_map"]["0"] = serialized["options_map"].pop(0)
    set_registers(controller, {41000: 0})
    assert sensors["manual_work_mode"].native_value == "Self Use"


@pytest.mark.parametrize(("value", "label"), [(0, "Self Use"), (1, None), (6, None), (12, None), (None, None)])
def test_manual_mode_preserves_unknown_codes(
    controller: ModbusController, sensors: dict[str, SensorEntity], value: int | None, label: str | None
) -> None:
    set_registers(controller, {41000: value})
    assert sensors["manual_work_mode"].native_value == label
    assert sensors["manual_work_mode"].extra_state_attributes == {"raw_value": value}


@pytest.mark.parametrize(("value", "expected"), [(0, False), (1, True), (2, None), (12, None), (None, None)])
def test_scheduler_is_strict_boolean(controller: ModbusController, value: int | None, expected: bool | None) -> None:
    profile = inverter_connection_type_profile_from_config(controller.inverter_details)
    entities = profile.create_entities(BinarySensorEntity, controller)
    assert len(entities) == 1
    sensor = cast(BinarySensorEntity, entities[0])
    controller.register_modbus_entity(cast(ModbusControllerEntity, sensor))
    set_registers(controller, {48000: value})
    assert sensor.is_on is expected


@pytest.mark.parametrize(
    ("register", "raw", "decoded"), [(36001, 289, "1.21"), (36002, 257, "1.01"), (36003, 288, "1.20")]
)
def test_firmware(
    controller: ModbusController, sensors: dict[str, SensorEntity], register: int, raw: int, decoded: str
) -> None:
    key = {36001: "master_version", 36002: "slave_version", 36003: "manager_version"}[register]
    set_registers(controller, {register: raw})
    assert sensors[key].native_value == decoded
