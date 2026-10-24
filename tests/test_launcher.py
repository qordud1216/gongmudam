import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import launch_gongmudam as launch


class LauncherTests(unittest.TestCase):
    def test_only_isolated_public_gongmudam_health_is_reusable(self):
        valid = dict(status='ok', desktop_connected=True, public_demo=True,
                     private_data_isolated=True, requires_origin_pc=True)
        self.assertTrue(launch.ready(valid))
        for key in valid:
            self.assertFalse(launch.ready({**valid, key: None}), key)
        self.assertFalse(launch.ready({'status': 'ok'}))
        self.assertFalse(launch.ready([]))
        self.assertFalse(launch.ready({**valid, 'public_demo': 1}))

    @patch.object(launch, 'write_state')
    @patch.object(launch, 'probe', return_value=True)
    def test_repeated_launch_reuses_both_services_without_spawning(self, _probe, _state):
        instance = launch.Launcher()
        with patch.object(instance, 'spawn') as spawn:
            result = instance.run()
        self.assertEqual(result['status'], 'ready')
        self.assertFalse(result['server_started'])
        self.assertFalse(result['tunnel_started'])
        spawn.assert_not_called()

    @patch.object(launch, 'port_in_use', return_value=True)
    @patch.object(launch, 'probe', return_value=False)
    def test_busy_unrecognized_port_is_never_overwritten(self, _probe, _port):
        instance = launch.Launcher()
        with patch.object(instance, 'wait_ready', return_value=False), patch.object(instance, 'spawn') as spawn:
            with self.assertRaises(launch.LaunchError): instance.ensure_server()
        spawn.assert_not_called()

    @patch.object(launch, 'tunnel_processes', return_value=[1234])
    @patch.object(launch, 'probe', return_value=False)
    def test_connecting_tunnel_is_waited_for_instead_of_duplicated(self, _probe, _processes):
        instance = launch.Launcher()
        with patch.object(instance, 'wait_ready', return_value=True), patch.object(instance, 'spawn') as spawn:
            instance.ensure_tunnel()
        spawn.assert_not_called()
        self.assertFalse(instance.result['tunnel_started'])
        self.assertEqual(instance.result['tunnel_existing_pids'], [1234])

    @patch.object(launch, 'probe', return_value=False)
    def test_failed_started_process_is_not_reported_ready(self, _probe):
        instance = launch.Launcher()
        process = Mock(); process.poll.return_value = 1
        self.assertFalse(instance.wait_ready(launch.LOCAL_URL, 1, process))

    def test_server_and_tunnel_order_and_errors_are_recorded(self):
        instance = launch.Launcher(); order = []
        with patch.object(instance, 'ensure_server', side_effect=lambda: order.append('server')), \
             patch.object(instance, 'ensure_tunnel', side_effect=launch.LaunchError('network unavailable')), \
             patch.object(launch, 'write_state') as state:
            with self.assertRaises(launch.LaunchError): instance.run()
        self.assertEqual(order, ['server'])
        self.assertEqual(instance.result['status'], 'error')
        self.assertIn('network unavailable', state.call_args.args[0]['message'])

    def test_cold_server_uses_isolated_runtime_and_loopback_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python = root / 'service/.venv/Scripts/python.exe'
            python.parent.mkdir(parents=True); python.touch()
            state = root / 'launcher'
            with patch.object(launch, 'ROOT', root), patch.object(launch, 'STATE', state), \
                 patch.object(launch, 'probe', return_value=False), \
                 patch.object(launch, 'port_in_use', return_value=False), \
                 patch.object(launch.subprocess, 'run', return_value=Mock(returncode=0)):
                instance = launch.Launcher()
                with patch.object(instance, 'spawn', return_value=Mock()) as spawn, \
                     patch.object(instance, 'wait_ready', return_value=True):
                    instance.ensure_server()
                argv, component, env = spawn.call_args.args
                self.assertEqual(component, 'server')
                self.assertIn('127.0.0.1', argv)
                self.assertEqual(argv[-1], '8892')
                self.assertEqual(env['GONGMUDAM_PUBLIC'], '1')
                self.assertEqual(env['GONGMUDAM_SERVICE_ROOT'], str(root / '.local-runtime/service'))

    @unittest.skipUnless(os.name == 'nt', 'Windows named mutex')
    def test_concurrent_double_click_is_serialized(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(launch, 'ROOT', Path(tmp)):
            with launch.LaunchLock():
                with self.assertRaises(launch.AlreadyLaunching):
                    with launch.LaunchLock(): pass
            with launch.LaunchLock(): pass

    @patch.object(launch, 'write_state')
    @patch.object(launch.webbrowser, 'open', return_value=False)
    def test_browser_failure_keeps_service_success_and_reports_it(self, opened, state):
        result = {'status': 'ready'}
        self.assertFalse(launch.open_public(result))
        self.assertEqual(result, {'status': 'ready', 'browser_opened': False})
        opened.assert_called_once_with(launch.PUBLIC_URL)
        state.assert_called_once_with(result)


if __name__ == '__main__':
    unittest.main()
