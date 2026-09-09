r"""serial_send build_payload 行为钉 (F-102 最后一块: 让 serial_send 脱离
零覆盖清单)。纯函数, 覆盖 hex/文本模式 × 行尾 × 非法 hex。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import serial_send  # noqa: E402


class BuildPayloadTests(unittest.TestCase):

    def test_text_mode_appends_lf(self):
        self.assertEqual(serial_send.build_payload("hi", False, "lf"),
                         b"hi\n")

    def test_text_mode_cr_crlf_none(self):
        self.assertEqual(serial_send.build_payload("hi", False, "cr"),
                         b"hi\r")
        self.assertEqual(serial_send.build_payload("hi", False, "crlf"),
                         b"hi\r\n")
        self.assertEqual(serial_send.build_payload("hi", False, "none"),
                         b"hi")

    def test_hex_mode_parses_spaced_bytes(self):
        self.assertEqual(serial_send.build_payload("DE AD", True, "none"),
                         b"\xde\xad")
        self.assertEqual(serial_send.build_payload("0xDE,0xAD", True, "none"),
                         b"\xde\xad")

    def test_hex_mode_invalid_returns_none(self):
        self.assertIsNone(serial_send.build_payload("ZZ", True, "none"))


if __name__ == "__main__":
    unittest.main()
