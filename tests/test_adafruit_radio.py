# SPDX-FileCopyrightText: 2021 ladyada for Adafruit Industries
#
# SPDX-License-Identifier: Unlicense

"""
Simple unit tests for the adafruit_ble_radio module. Uses experimental mocking
found in the testconf.py file. See comments therein for explanation of how it
works.
"""
import struct
import time
from unittest import mock
import pytest
import adafruit_ble_radio


@pytest.fixture
def radio():
    """
    A fixture to recreate a new Radio instance for each test that needs it.
    """
    return adafruit_ble_radio.Radio()


def test_radio_init_default():
    """
    Ensure a Radio object is initialised in the expected way:

    * It has a BLERadio instance.
    * The self.uid counter is set to 0.
    * The self.msg_pool is initialised as an empty set.
    * The channel is set to the default 42.
    """
    r = adafruit_ble_radio.Radio()
    assert r.ble == adafruit_ble_radio.BLERadio()
    assert r.uid == 0
    assert r.msg_pool == set()
    assert r._channel == 42  # pylint: disable=protected-access


def test_radio_init_channel():
    """
    If a channel argument is passed to initialisation, this is correctly set.
    """
    r = adafruit_ble_radio.Radio(channel=7)
    assert r._channel == 7  # pylint: disable=protected-access


def test_radio_configure_channel(radio_obj):
    """
    If a valid channel argument is passed to the configure method, the Radio
    instance's channel is updated to reflect this.
    """
    assert radio_obj._channel == 42  # pylint: disable=protected-access
    radio_obj.configure(channel=7)
    assert radio_obj._channel == 7  # pylint: disable=protected-access


def test_radio_configure_channel_out_of_bounds(
    radio_obj,
):  # pylint: disable=invalid-name
    """
    If a channel not in the range 0-255 is passed into the configure method,
    then a ValueError exception is raised.
    """
    with pytest.raises(ValueError):
        radio_obj.configure(channel=-1)
    with pytest.raises(ValueError):
        radio_obj.configure(channel=256)
    # Add just-in-bounds checks too.
    radio_obj.configure(channel=0)
    assert radio_obj._channel == 0  # pylint: disable=protected-access
    radio_obj.configure(channel=255)
    assert radio_obj._channel == 255  # pylint: disable=protected-access


def test_radio_send(radio_obj):
    """
    The send method merely encodes to bytes and calls send_bytes.
    """
    radio_obj.send_bytes = mock.MagicMock()
    msg = "Testing 1, 2, 3..."
    radio_obj.send(msg)
    radio_obj.send_bytes.assert_called_once_with(msg.encode("utf-8"))


def test_radio_send_bytes_too_long(radio_obj):
    """
    A ValueError is raised if the message to be sent is too long (defined by
    MAX_LENGTH).
    """
    msg = bytes(adafruit_ble_radio.MAX_LENGTH + 1)
    with pytest.raises(ValueError):
        radio_obj.send_bytes(msg)


def test_radio_send_bytes(radio_obj):
    """
    Ensure the expected message is set on an instance of AdafruitRadio, and
    broadcast for AD_DURATION period of time.
    """
    radio_obj.uid = 255  # set up for cycle back to 0.
    msg = b"Hello"
    with mock.patch("adafruit_ble_radio.time.sleep") as mock_sleep:
        radio_obj.send_bytes(msg)
        mock_sleep.assert_called_once_with(adafruit_ble_radio.AD_DURATION)
    spy_advertisement = (
        adafruit_ble_radio._RadioAdvertisement()  # pylint: disable=protected-access
    )  # pylint: disable=protected-access
    chan = struct.pack("<B", radio_obj._channel)  # pylint: disable=protected-access
    uid = struct.pack("<B", 255)
    assert spy_advertisement.msg == chan + uid + msg
    radio_obj.ble.start_advertising.assert_called_once_with(spy_advertisement)
    radio_obj.ble.stop_advertising.assert_called_once_with()
    assert radio_obj.uid == 0


def test_radio_receive_no_message(radio_obj):
    """
    If no message is received from the receive_bytes method, then None is
    returned.
    """
    radio_obj.receive_full = mock.MagicMock(return_value=None)
    assert radio_obj.receive() is None
    radio_obj.receive_full.assert_called_once_with()


def test_radio_receive(radio_obj):
    """
    If bytes are received from the receive_bytes method, these are decoded
    using utf-8 and returned as a string with null characters stripped from the
    end.
    """
    # Return value contains message bytes, RSSI (signal strength), timestamp.
    msg = b"testing 1, 2, 3\x00\x00\x00\x00\x00\x00"
    radio_obj.receive_full = mock.MagicMock(return_value=(msg, -20, 1.2))
    assert radio_obj.receive() == "testing 1, 2, 3"


def test_radio_receive_full_no_messages(radio_obj):  # pylint: disable=invalid-name
    """
    If no messages are detected by receive_full then it returns None.
    """
    radio_obj.ble.start_scan.return_value = []
    assert radio_obj.receive_full() is None
    radio_obj.ble.start_scan.assert_called_once_with(
        adafruit_ble_radio._RadioAdvertisement,  # pylint: disable=protected-access
        minimum_rssi=-255,
        timeout=1,
        extended=True,
    )
    radio_obj.ble.stop_scan.assert_called_once_with()


def test_radio_receive_full_duplicate_message(
    radio_obj,
):  # pylint: disable=invalid-name
    """
    If a duplicate message is detected, then receive_full returns None
    (indicating no *new* messages received).
    """
    mock_entry = mock.MagicMock()
    mock_entry.msg = b"*\x00Hello"
    mock_entry.address.address_bytes = b"addr"
    mock_entry.rssi = -40
    radio_obj.ble.start_scan.return_value = [mock_entry]
    radio_obj.msg_pool.add((time.monotonic(), 42, 0, b"addr"))
    assert radio_obj.receive_full() is None


def test_radio_receive_full_and_remove_expired_message_metadata(
    radio_obj,
):  # pylint: disable=invalid-name
    """
    Return the non-duplicate message.

    Ensure that expired message metadata (used to detect duplicate messages
    within a short time window) is purged from the self.msg_pool cache.

    Ensure the metadata from the new message is now in the self.msg_pool cache.
    """
    mock_entry = mock.MagicMock()
    mock_entry.msg = b"*\x01Hello"
    mock_entry.address.address_bytes = b"adr2"
    mock_entry.rssi = -40
    radio_obj.ble.start_scan.return_value = [mock_entry]
    radio_obj.msg_pool.add(
        (time.monotonic() - adafruit_ble_radio.AD_DURATION - 1, 42, 0, b"addr")
    )
    result = radio_obj.receive_full()
    assert result[0] == b"Hello"
    assert result[1] == -40
    assert len(radio_obj.msg_pool) == 1
    metadata = radio_obj.msg_pool.pop()
    assert metadata[1] == 42
    assert metadata[2] == 1
    assert metadata[3] == b"adr2"
