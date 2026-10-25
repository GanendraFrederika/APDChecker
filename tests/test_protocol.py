import sys
import unittest
from unittest.mock import Mock, patch
from apd_runtime.protocol import ActuatorLink, crc8, encode_frame, decode_frame


class ProtocolTests(unittest.TestCase):
    def test_crc_known_vector(self):
        self.assertEqual(crc8(b'123456789'), 0xf4)

    def test_roundtrip(self):
        for sequence in (1, 255, 65535):
            frame = encode_frame(sequence, 'ACK', 'A', 'ALARM')
            self.assertEqual(decode_frame(frame), (sequence, ['ACK', 'A', 'ALARM']))

    def test_corruption_rejected(self):
        frame = encode_frame(1, 'HELLO').replace(b'HELLO', b'JELLO')
        with self.assertRaises(ValueError):
            decode_frame(frame)

    def test_invalid_frame(self):
        for raw in (b'A', b'@0,HELLO*00\n', b'x'*101, b'@1,hello*00\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                decode_frame(raw)

    def test_invalid_encoder(self):
        for seq, fields in ((0, ['H']), (65536, ['H']), (1, []), (1, ['a'])):
            with self.assertRaises(ValueError):
                encode_frame(seq, *fields)

    def test_default_does_not_open_serial(self):
        fake = Mock()
        with patch.dict(sys.modules, {'serial': fake}):
            link = ActuatorLink(port='COM3')
            link.start()
            link.stop()
        fake.Serial.assert_not_called()

    def test_unknown_firmware_never_probed(self):
        fake = Mock()
        with patch.dict(sys.modules, {'serial': fake}):
            link = ActuatorLink(port='COM3', enabled=True)
            link.start()
            link.stop()
        fake.Serial.assert_not_called()
        self.assertIn('BLOCKED', link.status()['error'])

    def test_cannot_arm_disabled_link(self):
        with self.assertRaises(RuntimeError):
            ActuatorLink().arm()

    def test_ack(self):
        link = ActuatorLink()
        link._serial = Mock()
        link._serial.readline.return_value = encode_frame(1, 'ACK', 'HELLO', 'IDLE')
        link._request('HELLO')
        self.assertEqual(link.status()['last_ack'], 'IDLE')

    def test_fault_ack(self):
        link = ActuatorLink()
        link._serial = Mock()
        link._serial.readline.return_value = encode_frame(1, 'ACK', 'A', 'FAULT')
        with self.assertRaises(RuntimeError):
            link._request('A')

    def test_wrong_output_state_rejected(self):
        link = ActuatorLink()
        link._serial = Mock()
        link._serial.readline.return_value = encode_frame(1, 'ACK', 'A', 'IDLE')
        with self.assertRaises(RuntimeError):
            link._request('A')
