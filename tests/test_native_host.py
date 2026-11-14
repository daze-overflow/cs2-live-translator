import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from native.host import read_message, write_message, start_backend, valid_request, health


class NativeHostTests(unittest.TestCase):
    def test_utf8_protocol_round_trip_has_a_binary_length_prefix(self):
        stream = io.BytesIO()
        write_message(stream, {"type": "progress", "message": "正在加载模型"})
        raw = stream.getvalue()
        self.assertEqual(struct.unpack("<I", raw[:4])[0], len(raw) - 4)
        stream.seek(0)
        self.assertEqual(read_message(stream)["message"], "正在加载模型")
        self.assertIsNone(read_message(stream))

    def test_partial_and_oversized_protocol_messages_are_rejected(self):
        for raw in (b'\x01', struct.pack('<I', 6000), struct.pack('<I', 8) + b'{}'):
            with self.subTest(raw=raw[:4]), self.assertRaises(ValueError):
                read_message(io.BytesIO(raw))

    def test_only_a_fixed_start_command_is_accepted(self):
        self.assertTrue(valid_request({"type": "start"}))
        for message in ({"type": "run", "command": "anything"},
                        {"type": "start", "command": "anything"}, [], None):
            self.assertFalse(valid_request(message))

    def test_an_unrelated_health_endpoint_is_not_a_translation_service(self):
        with patch('native.host.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(b'{"app_id":"other","ready":true}')
            with self.assertRaisesRegex(RuntimeError, '其他程序'):
                health(8765)

    def root(self, directory):
        root = Path(directory)
        (root / 'local-config.json').write_text(json.dumps({"port": 8765}), encoding='utf-8')
        (root / '.venv/Scripts').mkdir(parents=True)
        (root / '.venv/Scripts/python.exe').touch()
        return root

    def test_a_ready_manual_backend_is_reused_without_becoming_owned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.root(directory)
            with patch('native.host.health', return_value={"ready": True, "version": "0.6.0"}), \
                 patch('native.host.subprocess.Popen') as spawn, patch('native.host.attach_job') as job:
                result = start_backend(root, lambda _message: None)
            self.assertFalse(result['started'])
            spawn.assert_not_called()
            job.assert_not_called()

    def test_cold_start_waits_for_ready_and_launches_only_the_fixed_local_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.root(directory)
            progress = []
            process = Mock(pid=1234)
            process.poll.return_value = None
            with patch('native.host.health', side_effect=[None, None, {"ready": True, "version": "0.6.0"}]), \
                 patch('native.host.startup_lock', return_value=nullcontext()), patch('native.host.attach_job'), \
                 patch('native.host.subprocess.Popen', return_value=process) as spawn:
                result = start_backend(root, progress.append)
            self.assertEqual(progress[0]['type'], 'progress')
            self.assertTrue(result['started'])
            self.assertEqual(spawn.call_args.args[0][1:], ['-X', 'utf8', '-m', 'backend.app'])
            self.assertEqual(spawn.call_args.kwargs['cwd'], root)
            self.assertNotIn('shell', spawn.call_args.kwargs)

    def test_model_startup_exit_returns_a_failure_instead_of_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.root(directory)
            process = Mock()
            process.poll.return_value = 1
            with patch('native.host.health', return_value=None), \
                 patch('native.host.startup_lock', return_value=nullcontext()), patch('native.host.attach_job'), \
                 patch('native.host.subprocess.Popen', return_value=process), self.assertRaisesRegex(RuntimeError, '启动失败'):
                start_backend(root, lambda _message: None)

    def test_a_process_that_never_becomes_ready_times_out(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.root(directory)
            with patch('native.host.health', return_value=None), \
                 patch('native.host.startup_lock', return_value=nullcontext()), patch('native.host.attach_job'), \
                 patch('native.host.subprocess.Popen'), self.assertRaisesRegex(RuntimeError, '超时'):
                start_backend(root, lambda _message: None, timeout=0)
