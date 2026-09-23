"""An ``rx`` record must mean we heard the packet on the air.

The repeater and its companions share one process and one radio, so a lot of
what reaches ``_publish_packet_to_mqtt`` was never received: packets this node
originated, and internal repeater<->companion traffic. Those records carry no
RF measurement, and the MC2MQTT schema has no way to say "not measured" -- so
they went out as ``RSSI: "0"``, which aggregators read as 0 dBm, the strongest
reading physically possible.

The visible damage is on the map rather than in the logs: whichever node the
packet came from appears to be sitting next to the observer, which is exactly
the evidence anyone uses to judge a link or site a repeater.

Own transmissions are still published, as ``direction: "tx"`` -- see
``test_mqtt_publish_own_tx.py``. This module only pins the ``rx`` side.
"""

from unittest.mock import MagicMock

from repeater.data_acquisition.storage_collector import StorageCollector

REQ_TYPE = 0
RAW_RX = "0141" + "be50" + "deadbeef"
RAW_TX = "0142" + "be506742" + "deadbeef"


def _collector(wants_tx: bool = False) -> tuple:
    """A StorageCollector with only the fields _publish_packet_to_mqtt touches."""
    collector = object.__new__(StorageCollector)
    collector.config = {"repeater": {"node_name": "test-node"}}
    collector.mqtt_handler = MagicMock()
    collector.mqtt_handler.public_key = "AB" * 32
    collector.mqtt_handler.wants_own_tx.return_value = wants_tx
    return collector, collector.mqtt_handler


def _record(rssi, snr, transmitted: bool = False) -> dict:
    return {
        "timestamp": 1700000000.0,
        "type": REQ_TYPE,
        "route": 1,
        "rssi": rssi,
        "snr": snr,
        "score": 0.5,
        "payload_length": 4,
        "packet_hash": "DEADBEEF" + "00" * 4,
        "raw_packet": RAW_RX,
        "raw_packet_tx": RAW_TX if transmitted else None,
        "transmitted": transmitted,
        "airtime_ms": 100.0,
    }


def _directions(handler) -> list:
    return [call.args[0]["direction"] for call in handler.publish_packet.call_args_list]


def test_measured_reception_still_publishes_rx():
    """The ordinary path is unchanged."""
    collector, handler = _collector()
    collector._publish_packet_to_mqtt(_record(rssi=-90, snr=7.5))

    assert _directions(handler) == ["rx"]
    assert handler.publish_packet.call_args.args[0]["RSSI"] == "-90"


def test_unmeasured_packet_publishes_no_rx_record():
    """Our own origination never went into a receiver, so it is not a reception."""
    collector, handler = _collector()
    collector._publish_packet_to_mqtt(_record(rssi=0, snr=0.0))

    assert _directions(handler) == []


def test_unmeasured_own_transmission_publishes_only_tx():
    """A relay we send is reported as what it is, and not also as a reception."""
    collector, handler = _collector(wants_tx=True)
    collector._publish_packet_to_mqtt(_record(rssi=0, snr=0.0, transmitted=True))

    assert _directions(handler) == ["tx"]


def test_relay_of_a_heard_packet_publishes_both_rx_and_tx():
    """A forwarding repeater did hear the packet, so both records are real."""
    collector, handler = _collector(wants_tx=True)
    collector._publish_packet_to_mqtt(_record(rssi=-101, snr=-7.0, transmitted=True))

    assert _directions(handler) == ["rx", "tx"]


def test_zero_snr_alone_is_a_real_measurement():
    """0.0 dB SNR happens on the air; 0 dBm RSSI with it does not."""
    collector, handler = _collector()
    collector._publish_packet_to_mqtt(_record(rssi=-95, snr=0.0))

    assert _directions(handler) == ["rx"]


def test_missing_rssi_and_snr_keys_are_treated_as_unmeasured():
    """An absent key is not a strong signal."""
    collector, handler = _collector()
    record = _record(rssi=0, snr=0.0)
    del record["rssi"]
    del record["snr"]
    collector._publish_packet_to_mqtt(record)

    assert _directions(handler) == []
