"""Проверки адаптера Kraken без интернета; все цены в примерах условные."""

import copy
import importlib.util
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from queue import Queue
import unittest
from unittest.mock import Mock, patch

import requests

from crypto_api_task6 import KrakenClient, QuoteError, Snapshot, parse_quotes

spec = importlib.util.spec_from_file_location(
    'crypto_window_task6', Path(__file__).with_name('Задание 6.py')
)
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


def ticker_payload():
    """Названия полей и ключи соответствуют публичному Kraken Ticker."""
    values = {
        'XXBTZUSD': ('60000.10', '59000.01', '61000.02'),
        'XETHZUSD': ('3000.25', '2900.03', '3100.04'),
        'SOLUSD': ('140.05', '135.06', '145.07'),
        'XXRPZUSD': ('0.52', '0.50', '0.55'),
        'XDGUSD': ('0.000000123456789', '0.0000001', '0.0000002'),
    }
    return {
        'error': [],
        'result': {
            key: {
                'c': [price, '98765'],
                # Индекс 0 относится к текущему дню, индекс 1 — к 24 часам.
                'l': ['99999', low],
                'h': ['999999', high],
            }
            for key, (price, low, high) in values.items()
        },
    }


class ParseQuotesTests(unittest.TestCase):
    def test_maps_all_five_pairs_to_user_facing_symbols(self):
        quotes = parse_quotes(ticker_payload())
        self.assertEqual(
            [(quote.symbol, quote.name) for quote in quotes],
            [('BTC', 'Bitcoin'), ('ETH', 'Ethereum'), ('SOL', 'Solana'),
             ('XRP', 'XRP'), ('DOGE', 'Dogecoin')],
        )

    def test_uses_last_trade_and_24_hour_range(self):
        quote = parse_quotes(ticker_payload())[0]
        self.assertEqual(quote.price, Decimal('60000.10'))
        self.assertEqual(quote.low_24h, Decimal('59000.01'))
        self.assertEqual(quote.high_24h, Decimal('61000.02'))

    def test_preserves_small_prices_without_float_rounding(self):
        quote = parse_quotes(ticker_payload())[-1]
        self.assertIsInstance(quote.price, Decimal)
        self.assertEqual(quote.price, Decimal('0.000000123456789'))

    def test_ignores_unrequested_markets(self):
        payload = ticker_payload()
        payload['result']['UNREQUESTED'] = {'not': 'a ticker'}
        self.assertEqual(len(parse_quotes(payload)), 5)

    def test_rejects_missing_coin_instead_of_returning_partial_result(self):
        payload = ticker_payload()
        del payload['result']['XXRPZUSD']
        with self.assertRaisesRegex(QuoteError, 'отсутствует курс XRP'):
            parse_quotes(payload)

    def test_rejects_malformed_top_level_data(self):
        for payload in (None, [], {}, {'error': None}, {'error': 'failure'}):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(QuoteError, 'формат данных'):
                    parse_quotes(payload)

    def test_rejects_missing_result(self):
        for payload in ({'error': []}, {'error': [], 'result': []}):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(QuoteError, 'отсутствуют котировки'):
                    parse_quotes(payload)

    def test_reports_api_error_even_when_result_is_present(self):
        payload = ticker_payload()
        payload['error'] = ['EGeneral:Internal error']
        with self.assertRaisesRegex(QuoteError, 'Kraken сообщил об ошибке'):
            parse_quotes(payload)

    def test_reports_api_rate_limit(self):
        with self.assertRaisesRegex(QuoteError, 'Слишком много запросов'):
            parse_quotes({'error': ['EAPI:Rate limit exceeded']})

    def test_rejects_missing_or_malformed_price_arrays(self):
        invalid_items = [
            {},
            {'c': [], 'l': ['1', '2'], 'h': ['3', '4']},
            {'c': ['2'], 'l': ['1'], 'h': ['3', '4']},
            {'c': ['2'], 'l': ['1', '1'], 'h': None},
            {'c': '123', 'l': ['1', '1'], 'h': ['3', '4']},
        ]
        for item in invalid_items:
            with self.subTest(item=item):
                payload = ticker_payload()
                payload['result']['XXBTZUSD'] = item
                with self.assertRaisesRegex(QuoteError, 'Некорректные данные'):
                    parse_quotes(payload)

    def test_rejects_invalid_numbers_in_each_price_field(self):
        for field, index in (('c', 0), ('l', 1), ('h', 1)):
            for value in ('0', '-1', 'NaN', 'Infinity', '-Infinity', '', None, True):
                with self.subTest(field=field, value=value):
                    payload = ticker_payload()
                    payload['result']['XXBTZUSD'][field][index] = value
                    with self.assertRaisesRegex(QuoteError, 'некорректную цену'):
                        parse_quotes(payload)

    def test_rejects_reversed_daily_range(self):
        payload = ticker_payload()
        payload['result']['XXBTZUSD']['l'][1] = '62000'
        with self.assertRaisesRegex(QuoteError, 'диапазон цен'):
            parse_quotes(payload)

    def test_parsing_does_not_modify_server_payload(self):
        payload = ticker_payload()
        before = copy.deepcopy(payload)
        parse_quotes(payload)
        self.assertEqual(payload, before)


class KrakenClientTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('crypto_api_task6.requests.get')
        self.get = patcher.start()
        self.addCleanup(patcher.stop)
        self.response = Mock()
        self.response.json.return_value = ticker_payload()
        self.get.return_value = self.response

    def test_one_request_fetches_all_pairs_with_timeout(self):
        KrakenClient().fetch_quotes()
        self.get.assert_called_once_with(
            'https://api.kraken.com/0/public/Ticker',
            params={'pair': 'XBTUSD,ETHUSD,SOLUSD,XRPUSD,DOGEUSD'},
            headers={'Accept': 'application/json'},
            timeout=(5, 10),
        )
        self.response.raise_for_status.assert_called_once()
        self.response.json.assert_called_once()

    def test_returns_snapshot_with_aware_receipt_time(self):
        before = datetime.now(timezone.utc)
        snapshot = KrakenClient().fetch_quotes()
        after = datetime.now(timezone.utc)
        self.assertIsInstance(snapshot, Snapshot)
        self.assertEqual(snapshot.source, 'Kraken')
        self.assertEqual(len(snapshot.quotes), 5)
        self.assertIsNotNone(snapshot.received_at.utcoffset())
        self.assertLessEqual(before, snapshot.received_at)
        self.assertLessEqual(snapshot.received_at, after)

    def test_timeout_has_readable_message(self):
        self.get.side_effect = requests.Timeout()
        with self.assertRaisesRegex(QuoteError, 'не ответил вовремя'):
            KrakenClient().fetch_quotes()

    def test_connection_failure_has_readable_message(self):
        self.get.side_effect = requests.ConnectionError()
        with self.assertRaisesRegex(QuoteError, 'Проверьте интернет'):
            KrakenClient().fetch_quotes()

    def test_http_429_has_rate_limit_message(self):
        http_response = requests.Response()
        http_response.status_code = 429
        self.response.raise_for_status.side_effect = requests.HTTPError(
            response=http_response
        )
        with self.assertRaisesRegex(QuoteError, 'Слишком много запросов'):
            KrakenClient().fetch_quotes()
        self.response.json.assert_not_called()

    def test_http_503_has_service_unavailable_message(self):
        http_response = requests.Response()
        http_response.status_code = 503
        self.response.raise_for_status.side_effect = requests.HTTPError(
            response=http_response
        )
        with self.assertRaisesRegex(QuoteError, 'временно недоступен'):
            KrakenClient().fetch_quotes()
        self.response.json.assert_not_called()

    def test_http_500_has_service_unavailable_message(self):
        http_response = requests.Response()
        http_response.status_code = 500
        self.response.raise_for_status.side_effect = requests.HTTPError(
            response=http_response
        )
        with self.assertRaisesRegex(QuoteError, 'временно недоступен'):
            KrakenClient().fetch_quotes()
        self.response.json.assert_not_called()

    def test_invalid_json_has_readable_message(self):
        self.response.json.side_effect = requests.exceptions.JSONDecodeError(
            'invalid', '<html>', 0
        )
        with self.assertRaisesRegex(QuoteError, 'некорректный JSON'):
            KrakenClient().fetch_quotes()


class WorkerAndWindowTests(unittest.TestCase):
    def test_worker_delivers_success_to_queue(self):
        provider, results = Mock(), Queue()
        snapshot = Snapshot(parse_quotes(ticker_payload()), datetime.now(timezone.utc))
        provider.fetch_quotes.return_value = snapshot
        gui.fetch_in_worker(provider, results)
        self.assertEqual(results.get_nowait(), (snapshot, None))

    def test_worker_delivers_expected_error_to_queue(self):
        provider, results = Mock(), Queue()
        provider.fetch_quotes.side_effect = QuoteError('Нет соединения')
        gui.fetch_in_worker(provider, results)
        self.assertEqual(results.get_nowait(), (None, 'Нет соединения'))

    def test_unexpected_error_does_not_leave_window_waiting(self):
        provider, results = Mock(), Queue()
        provider.fetch_quotes.side_effect = RuntimeError('unexpected internal detail')
        gui.fetch_in_worker(provider, results)
        snapshot, error = results.get_nowait()
        self.assertIsNone(snapshot)
        self.assertIn('Не удалось обработать', error)
        self.assertNotIn('internal detail', error)

    def test_failed_refresh_keeps_previous_values_and_timestamp(self):
        window = object.__new__(gui.CryptoApp)
        previous = Snapshot(parse_quotes(ticker_payload()), datetime.now(timezone.utc))
        window.snapshot, window.busy = previous, True
        window.status, window.received, window.table = Mock(), Mock(), Mock()
        window._show_result(None, 'Нет сети')
        self.assertIs(window.snapshot, previous)
        self.assertFalse(window.busy)
        self.assertIn('устаревшие данные', window.status.set.call_args.args[0])
        window.table.item.assert_not_called()
        window.received.set.assert_not_called()

    def test_no_previous_values_are_fabricated_on_failure(self):
        window = object.__new__(gui.CryptoApp)
        window.snapshot, window.busy = None, True
        window.status, window.received, window.table = Mock(), Mock(), Mock()
        window._show_result(None, 'Нет сети')
        self.assertIn('Данные не получены', window.status.set.call_args.args[0])
        window.table.item.assert_not_called()
        self.assertIsNone(window.snapshot)

    def test_success_updates_five_rows_and_receipt_time(self):
        window = object.__new__(gui.CryptoApp)
        window.snapshot, window.busy = None, True
        window.status, window.received, window.table = Mock(), Mock(), Mock()
        window.source, window.price_note = Mock(), Mock()
        snapshot = Snapshot(
            parse_quotes(ticker_payload()), datetime(2026, 1, 1, tzinfo=timezone.utc),
            source='Test Exchange',
        )
        window._show_result(snapshot, None)
        self.assertEqual(window.table.item.call_count, 5)
        self.assertIs(window.snapshot, snapshot)
        window.received.set.assert_called_once_with('Данные получены: 01.01.2026 03:00:00 МСК')
        window.source.set.assert_called_once_with(
            'Источник: Test Exchange  •  Валюта котировки: доллар США (USD)'
        )
        self.assertIn('Test Exchange', window.price_note.set.call_args.args[0])

    def test_busy_and_rate_limit_prevent_duplicate_requests(self):
        window = object.__new__(gui.CryptoApp)
        window.closed, window.busy = False, True
        window.last_request_started = 100.0
        window.provider, window.results = Mock(), Queue()
        window.refresh_button, window.status = Mock(), Mock()
        with patch.object(gui.time, 'monotonic', return_value=104.9), patch.object(gui, 'Thread') as thread:
            window.refresh()
            window.busy = False
            window.refresh()
            thread.assert_not_called()
        with patch.object(gui.time, 'monotonic', return_value=105.0), patch.object(gui, 'Thread') as thread:
            window.refresh()
            thread.assert_called_once()
            thread.return_value.start.assert_called_once()
            self.assertTrue(window.busy)

    def test_small_displayed_price_stays_nonzero(self):
        text = gui.format_price(Decimal('0.000000123456789'))
        self.assertGreater(Decimal(text), 0)
        self.assertEqual(Decimal(text), Decimal('0.000000123457'))

    def test_poll_refreshes_only_when_enabled_due_and_idle(self):
        scenarios = (
            (True, 159.9, False, 0),
            (True, 160.0, False, 1),
            (False, 200.0, False, 0),
            (True, 200.0, True, 0),
        )
        for enabled, now, busy, expected_calls in scenarios:
            with self.subTest(enabled=enabled, now=now, busy=busy):
                window = object.__new__(gui.CryptoApp)
                window.closed, window.busy = False, busy
                window.results, window.last_request_started = Queue(), 100.0
                window.root, window.refresh_button = Mock(), Mock()
                window.auto_refresh, window.refresh = Mock(), Mock()
                window.auto_refresh.get.return_value = enabled
                with patch.object(gui.time, 'monotonic', return_value=now):
                    window._poll()
                self.assertEqual(window.refresh.call_count, expected_calls)
                window.root.after.assert_called_once_with(100, window._poll)

    def test_close_cancels_timers_and_prevents_further_work(self):
        window = object.__new__(gui.CryptoApp)
        window.root = Mock()
        window.closed = False
        window.start_id, window.timer_id = 'startup_timer', 'poll_timer'
        window.close()
        self.assertTrue(window.closed)
        self.assertEqual(
            [item.args for item in window.root.after_cancel.call_args_list],
            [('startup_timer',), ('poll_timer',)],
        )
        window.root.destroy.assert_called_once()
        with patch.object(gui, 'Thread') as thread:
            window.refresh()
            window._poll()
            thread.assert_not_called()
        window.root.after.assert_not_called()


if __name__ == '__main__':
    unittest.main()
