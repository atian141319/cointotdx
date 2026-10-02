import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from chart_refresh import reload_active
from history_guard import HistoryGuard, fixed_cursor_visible
from settings import adapted_pair, default_settings, validate
from test_chart_refresh import bitmap


class CompletionTests(unittest.TestCase):
    def refresh_fixture(self, foreground_pid):
        raw = bitmap()
        for x in range(100, 132):
            point = 54 + ((525 - 37) * 1024 + x) * 4
            raw[point:point + 4] = bytes((255, 255, 0, 0))
        title = '通达信金融终端V7.73 - [分析图表-ETHUSDT试验]'
        user = SimpleNamespace(GetForegroundWindow=Mock(return_value=99),
                               GetLastInputInfo=Mock(side_effect=lambda pointer: setattr(pointer._obj, 'dwTime', 9950) or True),
                               GetGUIThreadInfo=Mock(return_value=True))
        def pid(handle, pointer):
            if pointer is not None:
                pointer._obj.value = foreground_pid
            return 1
        user.GetWindowThreadProcessId = pid
        client = SimpleNamespace(user=user, kernel=SimpleNamespace(GetTickCount=lambda:10000),
            windows=lambda:[(1,title,2)], capture=lambda path:{'title':title,'bitmap':raw},
            period=Mock(return_value={'operation':'public toolbar'}))
        guard = SimpleNamespace(watch=lambda *args:None, observe=lambda cursor:None)
        pairs = [{'enabled':True,'display_name':'ETHUSDT试验','symbol':'ETHUSDT','code':'397903'}]
        return client, guard, pairs

    def test_active_input_in_target_client_defers_reload(self):
        client, guard, pairs = self.refresh_fixture(2)
        self.assertFalse(reload_active(client, pairs, guard)['requested'])
        client.period.assert_not_called()

    def test_unrelated_app_input_does_not_stop_background_reload(self):
        client, guard, pairs = self.refresh_fixture(99)
        self.assertTrue(reload_active(client, pairs, guard)['requested'])
        client.period.assert_called_once_with('5m')

    def test_history_pause_outlasts_input_idle_and_latest_resumes(self):
        guard = HistoryGuard()
        self.assertIsNotNone(guard.observe(False))
        guard.navigation('latest')
        self.assertIsNone(guard.observe(False))
        guard.navigation('history')
        for _ in range(20):
            self.assertIsNotNone(guard.observe(False))
        guard.navigation('latest')
        self.assertIsNotNone(guard.observe(True))
        self.assertIsNone(guard.observe(False))

    def test_cursor_badge_detected_and_latched(self):
        raw = bitmap()
        self.assertFalse(fixed_cursor_visible(raw))
        for x in range(40, 110):
            point = 54 + ((525 - 457) * 1024 + x) * 4
            raw[point:point + 4] = bytes((128, 0, 0, 0))
        self.assertTrue(fixed_cursor_visible(raw))
        guard = HistoryGuard()
        guard.navigation('latest')
        guard.observe(False)
        guard.observe(True)
        self.assertIsNotNone(guard.observe(False))
        with self.assertRaises(ValueError):
            fixed_cursor_visible(raw[:-4])

    def test_new_pair_strategy_without_low_level_fields(self):
        pair = adapted_pair({'symbol': 'ADAUSDT', 'display_name': 'ADAUSDT试验',
                             'code': '397906', 'enabled': True,
                             'history_start': '2026-10-02T00:00:00Z'})
        self.assertEqual(pair['lc5_time_label'], 'last_minute')
        self.assertEqual(pair['display_context_start'], '2026-10-01T23:00:00+00:00')
        config = default_settings()
        config['pairs'] = [pair]
        self.assertEqual(validate(config, check_paths=False)['pairs'], [pair])
        self.assertEqual(default_settings()['pairs'][0]['lc5_time_label'], 'last_minute')

    def test_prefix_recomputed_from_history_not_existing_label(self):
        pair = adapted_pair({'history_start': '2026-10-02T23:30:00Z'})
        self.assertEqual(pair['display_context_start'], '2026-10-02T23:00:00+00:00')
        pair['history_start'] = '2026-10-03T00:00:00Z'
        self.assertEqual(adapted_pair(pair)['display_context_start'], '2026-10-02T23:00:00+00:00')
        with self.assertRaises(ValueError):
            adapted_pair({'history_start': '2026-10-03T00:00:00'})


if __name__ == '__main__':
    unittest.main()
