"""Tests for trusted phones, quick-action command checks and file names (no network, no real laptop)."""
import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path

from fasway import actions as A
from fasway.devices import EXPIRE_DAYS, DeviceStore
from fasway.files import FileShare, safe_name


class TrustedPhones(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_key_is_checked_and_only_its_hash_is_stored(self):
        s = DeviceStore(self.dir)
        s.add("phone-1234", "k" * 32, "Pixel")
        self.assertTrue(s.verify("phone-1234", "k" * 32))
        self.assertFalse(s.verify("phone-1234", "x" * 32))
        self.assertFalse(s.verify("phone-1234", ""))
        self.assertNotIn("k" * 32, (self.dir / "devices.json").read_text())

    def test_phone_not_seen_for_90_days_is_forgotten(self):
        s = DeviceStore(self.dir)
        s.add("old-phone", "k" * 32, "Old")
        s.add("new-phone", "n" * 32, "New")
        s.devices["old-phone"]["last_seen"] = time.time() - (EXPIRE_DAYS + 1) * 86400
        self.assertFalse(s.verify("old-phone", "k" * 32))
        self.assertNotIn("old-phone", s.devices)
        self.assertTrue(s.verify("new-phone", "n" * 32))

    def test_expired_phones_are_dropped_at_start(self):
        old = time.time() - (EXPIRE_DAYS + 5) * 86400
        (self.dir / "devices.json").write_text(json.dumps([
            {"id": "a", "name": "Lost phone", "key_hash": "x", "added": old, "last_seen": old},
            {"id": "b", "name": "My phone", "key_hash": "y", "added": time.time(), "last_seen": time.time()}]))
        s = DeviceStore(self.dir)
        self.assertEqual(s.forgotten, ["Lost phone"])
        self.assertEqual(list(s.devices), ["b"])
        self.assertEqual([d["id"] for d in json.loads((self.dir / "devices.json").read_text())], ["b"])


class CommandActions(unittest.TestCase):
    def setUp(self):
        self.qa = A.QuickActions(Path(tempfile.mkdtemp()))
        self.asked = []
        self.answer = True

        async def confirm(a):
            self.asked.append(a["value"])
            return self.answer
        self.qa.confirm = confirm

    def run_check(self, a):
        asyncio.run(self.qa.check(a))

    def test_which_actions_run_commands(self):
        self.assertTrue(A.runs_command({"type": "command", "value": "shutdown /h"}))
        self.assertTrue(A.runs_command({"type": "macro", "value": "key win+r\nCMD echo hi"}))
        self.assertTrue(A.runs_command({"type": "macro", "value": "run notepad"}))
        self.assertFalse(A.runs_command({"type": "macro", "value": "key win+r\ntype cmd\nkey enter"}))
        self.assertFalse(A.runs_command({"type": "open", "value": "cmd"}))
        self.assertFalse(A.runs_command({"type": "keys", "value": "ctrl+c"}))

    def test_new_command_is_asked_once_then_runs(self):
        a = self.qa.upsert({"name": "Hibernate", "type": "command", "value": "shutdown /h"})
        self.run_check(a)
        self.run_check(a)
        self.assertEqual(self.asked, ["shutdown /h"])

    def test_changed_command_is_asked_again(self):
        a = self.qa.upsert({"name": "Hibernate", "type": "command", "value": "shutdown /h"})
        self.run_check(a)
        a = self.qa.upsert({"id": a["id"], "name": "Hibernate", "type": "command", "value": "del /q C:\\x"})
        self.run_check(a)
        self.assertEqual(self.asked, ["shutdown /h", "del /q C:\\x"])

    def test_denied_command_does_not_run_and_is_asked_next_time(self):
        self.answer = False
        a = self.qa.upsert({"name": "X", "type": "command", "value": "calc"})
        with self.assertRaises(A.NotAllowed):
            self.run_check(a)
        with self.assertRaises(A.NotAllowed):
            self.run_check(a)
        self.assertEqual(len(self.asked), 2)

    def test_phone_cannot_mark_its_own_command_allowed(self):
        a = self.qa.upsert({"name": "X", "type": "command", "value": "calc", "ok": A._command_hash(
            {"type": "command", "value": "calc"})})
        self.assertNotIn("ok", a)
        self.assertFalse(self.qa.is_allowed(a))

    def test_other_actions_never_ask(self):
        a = self.qa.upsert({"name": "Docs", "type": "open", "value": "https://example.com"})
        self.run_check(a)
        self.assertEqual(self.asked, [])

    def test_allowed_command_survives_a_restart(self):
        a = self.qa.upsert({"name": "Hibernate", "type": "command", "value": "shutdown /h"})
        self.run_check(a)
        again = A.QuickActions(self.qa.path.parent)
        self.assertTrue(again.is_allowed(again.get(a["id"])))


class WakeOnLan(unittest.TestCase):
    def test_card_and_broadcast_for_the_address_phones_reach(self):
        import socket
        from collections import namedtuple
        from unittest import mock

        import psutil

        from fasway import wol
        A = namedtuple("A", "family address netmask")
        cards = {"Wi-Fi": [A(psutil.AF_LINK, "AA-BB-CC-DD-EE-FF", None),
                           A(socket.AF_INET, "192.168.1.24", "255.255.255.0")],
                 "vEthernet": [A(psutil.AF_LINK, "00-15-5D-00-00-01", None),
                               A(socket.AF_INET, "172.20.0.1", "255.255.240.0")]}
        with mock.patch.object(psutil, "net_if_addrs", return_value=cards):
            self.assertEqual(wol.adapter_for("192.168.1.24"), {"mac": "aa:bb:cc:dd:ee:ff", "bcast": "192.168.1.255"})
            self.assertEqual(wol.adapter_for("172.20.0.1")["bcast"], "172.20.15.255")
            self.assertIsNone(wol.adapter_for("10.0.0.9"))


class FileNames(unittest.TestCase):
    def test_names_from_the_phone_are_made_safe(self):
        self.assertEqual(safe_name("../../Windows/evil.exe"), "evil.exe")
        self.assertEqual(safe_name("..\\..\\boot.ini"), "boot.ini")
        self.assertEqual(safe_name("CON.txt"), "_CON.txt")
        self.assertEqual(safe_name('a<b>:c?.txt'), "a_b__c_.txt")
        self.assertEqual(safe_name("   "), "file")

    def test_same_name_twice_keeps_both(self):
        share = FileShare(Path(tempfile.mkdtemp()))
        first = share.finish_upload(self._part(share), "photo.jpg")
        second = share.finish_upload(self._part(share), "photo.jpg")
        self.assertEqual((first.name, second.name), ("photo.jpg", "photo (2).jpg"))

    def test_offered_file_ids_are_needed_to_download(self):
        folder = Path(tempfile.mkdtemp())
        f = folder / "a.txt"
        f.write_text("hi")
        share = FileShare(folder)
        [offer] = share.offer([f, folder])   # folders are skipped
        self.assertEqual(share.offered(offer["id"]), f)
        self.assertIsNone(share.offered("guess"))

    @staticmethod
    def _part(share):
        p = share.new_upload()
        p.write_bytes(b"x")
        return p


if __name__ == "__main__":
    unittest.main()
