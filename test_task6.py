"""Проверки Bybit и интерфейса без интернета; цены в примерах условные."""

import copy
import importlib.util
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from queue import Queue
import unittest
from unittest.mock import Mock, patch

import requests

from crypto_api_task6 import BybitClient, QuoteError, Snapshot, parse_quotes

spec = importlib.util.spec_from_file_location(
    'crypto_window_task6', Path(__file__).with_name('Задание 6.py')
)
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)


def ticker_payload():
    """Поля Bybit spot ticker; разные USD и USDT цены проверяют разделение."""
    values = {
        'BTCUSD': ('60000.10', '59000.01', '61000.02'),
        'ETHUSD': ('3000.25', '2900.03', '3100.04'),
        'USDTUSD': ('1.0003', '0.9991', '1.0012'),
        'BTCUSDT': ('60010.20', '59010.01', '61010.02'),
        'ETHUSDT': ('3001.25', '2901.03', '3101.04'),
        'GRAMUSDT': ('0.00234878', '0.00220', '0.00250'),
        'BNBUSDT': ('605.45', '600.10', '610.80'),
        'SOLUSDT': ('140.05', '135.06', '145.07'),
        'XRPUSDT': ('0.52', '0.50', '0.55'),
        'DOGEUSDT': ('0.000000123456789', '0.0000001', '0.0000002'),
    }
    return {'retCode': 0, 'result': {'category': 'spot', 'list': [
        {'symbol': symbol, 'lastPrice': price, 'lowPrice24h': low, 'highPrice24h': high}
        for symbol, (price, low, high) in values.items()
    ]}}


def by_id(payload=None):
    return {quote.row_id: quote for quote in parse_quotes(
        ticker_payload() if payload is None else payload
    )}


def market(payload, symbol):
    return next(item for item in payload['result']['list'] if item['symbol'] == symbol)


class ParseQuotesTests(unittest.TestCase):
    def test_returns_eight_currencies_in_both_quote_units(self):
        quotes = parse_quotes(ticker_payload())
        expected = {
            'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'USDT': 'Tether',
            'GRAM': 'Gram (Toncoin)', 'BNB': 'BNB', 'SOL': 'Solana',
            'XRP': 'XRP', 'DOGE': 'Dogecoin',
        }
        self.assertEqual(len(quotes), 16)
        self.assertEqual(len({quote.row_id for quote in quotes}), 16)
        for currency in ('USD', 'USDT'):
            self.assertEqual(
                {quote.symbol: quote.name for quote in quotes if quote.currency == currency},
                expected,
            )

    def test_separates_usd_and_usdt_without_conversion(self):
        quotes = by_id()
        self.assertEqual(quotes['BTC:USD'].price, Decimal('60000.10'))
        self.assertEqual(quotes['BTC:USDT'].price, Decimal('60010.20'))
        self.assertEqual(quotes['ETH:USD'].price, Decimal('3000.25'))
        self.assertEqual(quotes['ETH:USDT'].price, Decimal('3001.25'))

    def test_gram_and_bnb_use_exact_usdt_pairs(self):
        quotes = by_id()
        self.assertEqual(quotes['GRAM:USDT'].price, Decimal('0.00234878'))
        self.assertEqual(quotes['BNB:USDT'].price, Decimal('605.45'))
        self.assertEqual(quotes['GRAM:USD'].status, 'missing')
        self.assertIsNone(quotes['GRAM:USD'].price)

    def test_uses_last_trade_and_24_hour_range(self):
        quote = by_id()['BTC:USD']
        self.assertEqual(quote.price, Decimal('60000.10'))
        self.assertEqual(quote.low_24h, Decimal('59000.01'))
        self.assertEqual(quote.high_24h, Decimal('61000.02'))

    def test_preserves_small_prices_without_float_rounding(self):
        quote = by_id()['DOGE:USDT']
        self.assertIsInstance(quote.price, Decimal)
        self.assertEqual(quote.price, Decimal('0.000000123456789'))

    def test_partial_response_marks_missing_pairs_without_fabricating_prices(self):
        payload = ticker_payload()
        payload['result']['list'] = [market(payload, 'BTCUSDT')]
        quotes = by_id(payload)
        self.assertEqual(len(quotes), 16)
        self.assertEqual(quotes['BTC:USDT'].status, 'available')
        self.assertEqual(quotes['BTC:USD'].status, 'missing')
        for quote in quotes.values():
            if quote.status != 'available':
                self.assertIsNone(quote.price)
                self.assertIsNone(quote.low_24h)
                self.assertIsNone(quote.high_24h)

    def test_usdt_usdt_is_quote_currency_not_fabricated_market(self):
        payload = ticker_payload()
        payload['result']['list'].append({
            'symbol': 'USDTUSDT', 'lastPrice': '1',
            'lowPrice24h': '1', 'highPrice24h': '1',
        })
        quote = by_id(payload)['USDT:USDT']
        self.assertEqual(quote.status, 'quote_currency')
        self.assertIsNone(quote.price)

    def test_unknown_and_similarly_named_pairs_do_not_match(self):
        payload = ticker_payload()
        for symbol in ('BTCUSDTBTC', 'BTCCUSD', 'TONUSDT', 'USDTUSDT', 'UNREQUESTED'):
            payload['result']['list'].append({'symbol': symbol, 'invalid': True})
        self.assertEqual(by_id(payload), by_id())

    def test_future_supported_usd_pair_is_used_when_returned(self):
        payload = ticker_payload()
        payload['result']['list'].append({
            'symbol': 'BNBUSD', 'lastPrice': '604.9',
            'lowPrice24h': '600.0', 'highPrice24h': '609.0',
        })
        quote = by_id(payload)['BNB:USD']
        self.assertEqual(quote.status, 'available')
        self.assertEqual(quote.price, Decimal('604.9'))

    def test_empty_or_unusable_ticker_list_is_an_error(self):
        for items in ([], None, {}, [{'symbol': 'UNKNOWN'}]):
            with self.subTest(items=items):
                with self.assertRaises(QuoteError):
                    parse_quotes({'retCode': 0, 'result': {'category': 'spot', 'list': items}})

    def test_rejects_malformed_top_level_data_and_return_code(self):
        for payload in (None, [], {}, {'retCode': None}, {'retCode': False},
                        {'retCode': '0'}, {'retCode': 0.0}):
            with self.subTest(payload=payload):
                with self.assertRaises(QuoteError):
                    parse_quotes(payload)

    def test_rejects_missing_result_or_wrong_market_category(self):
        for payload in (
            {'retCode': 0}, {'retCode': 0, 'result': []},
            {'retCode': 0, 'result': {'list': []}},
            {'retCode': 0, 'result': {'category': 'linear', 'list': []}},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(QuoteError):
                    parse_quotes(payload)

    def test_reports_api_error_even_when_result_is_present(self):
        payload = ticker_payload()
        payload['retCode'] = 10001
        with self.assertRaises(QuoteError):
            parse_quotes(payload)

    def test_reports_both_api_rate_limit_codes(self):
        for code in (10006, 10018):
            with self.subTest(code=code):
                with self.assertRaisesRegex(QuoteError, 'Слишком много запросов'):
                    parse_quotes({'retCode': code})

    def test_rejects_duplicate_selected_market(self):
        payload = ticker_payload()
        payload['result']['list'].append(copy.deepcopy(market(payload, 'BTCUSDT')))
        with self.assertRaises(QuoteError):
            parse_quotes(payload)

    def test_rejects_missing_price_fields(self):
        for field in ('lastPrice', 'lowPrice24h', 'highPrice24h'):
            with self.subTest(field=field):
                payload = ticker_payload()
                del market(payload, 'BTCUSD')[field]
                with self.assertRaises(QuoteError):
                    parse_quotes(payload)

    def test_rejects_invalid_numbers_in_each_price_field(self):
        for field in ('lastPrice', 'lowPrice24h', 'highPrice24h'):
            for value in ('0', '-1', 'NaN', 'Infinity', '-Infinity', '', None, True):
                with self.subTest(field=field, value=value):
                    payload = ticker_payload()
                    market(payload, 'BTCUSD')[field] = value
                    with self.assertRaises(QuoteError):
                        parse_quotes(payload)

    def test_rejects_reversed_daily_range(self):
        payload = ticker_payload()
        market(payload, 'BTCUSD')['lowPrice24h'] = '62000'
        with self.assertRaises(QuoteError):
            parse_quotes(payload)

    def test_parsing_does_not_modify_server_payload(self):
        payload = ticker_payload()
        before = copy.deepcopy(payload)
        parse_quotes(payload)
        self.assertEqual(payload, before)


class BybitClientTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('crypto_api_task6.requests.get')
        self.get = patcher.start()
        self.addCleanup(patcher.stop)
        self.response = Mock()
        self.response.json.return_value = ticker_payload()
        self.get.return_value = self.response

    def test_one_request_fetches_spot_markets_with_timeout(self):
        BybitClient().fetch_quotes()
        self.get.assert_called_once_with(
            'https://api.bybit.com/v5/market/tickers',
            params={'category': 'spot'}, headers={'Accept': 'application/json'}, timeout=(5, 10),
        )
        self.response.raise_for_status.assert_called_once()
        self.response.json.assert_called_once()

    def test_usdt_uses_real_usd_market_value_instead_of_constant_one(self):
        for market_price in ('1.0003', '0.9998'):
            with self.subTest(market_price=market_price):
                payload = ticker_payload()
                market(payload, 'USDTUSD')['lastPrice'] = market_price
                self.response.json.return_value = payload
                snapshot = BybitClient().fetch_quotes()
                quote = next(quote for quote in snapshot.quotes if quote.row_id == 'USDT:USD')
                self.assertEqual(quote.price, Decimal(market_price))

    def test_returns_snapshot_with_aware_receipt_time(self):
        before = datetime.now(timezone.utc)
        snapshot = BybitClient().fetch_quotes()
        after = datetime.now(timezone.utc)
        self.assertIsInstance(snapshot, Snapshot)
        self.assertEqual(snapshot.source, 'Bybit')
        self.assertEqual(len(snapshot.quotes), 16)
        self.assertIsNotNone(snapshot.received_at.utcoffset())
        self.assertLessEqual(before, snapshot.received_at)
        self.assertLessEqual(snapshot.received_at, after)

    def test_timeout_has_readable_message(self):
        self.get.side_effect = requests.Timeout()
        with self.assertRaisesRegex(QuoteError, 'не ответил вовремя'):
            BybitClient().fetch_quotes()

    def test_connection_failure_has_readable_message(self):
        self.get.side_effect = requests.ConnectionError()
        with self.assertRaisesRegex(QuoteError, 'Проверьте интернет'):
            BybitClient().fetch_quotes()

    def test_http_429_has_rate_limit_message(self):
        http_response = requests.Response()
        http_response.status_code = 429
        self.response.raise_for_status.side_effect = requests.HTTPError(response=http_response)
        with self.assertRaisesRegex(QuoteError, 'Слишком много запросов'):
            BybitClient().fetch_quotes()
        self.response.json.assert_not_called()

    def test_http_500_and_503_have_service_unavailable_message(self):
        for status in (500, 503):
            with self.subTest(status=status):
                http_response = requests.Response()
                http_response.status_code = status
                self.response.raise_for_status.side_effect = requests.HTTPError(response=http_response)
                with self.assertRaisesRegex(QuoteError, 'временно недоступен'):
                    BybitClient().fetch_quotes()
        self.response.json.assert_not_called()

    def test_invalid_json_has_readable_message(self):
        self.response.json.side_effect = requests.exceptions.JSONDecodeError('invalid', '<html>', 0)
        with self.assertRaisesRegex(QuoteError, 'некорректный JSON'):
            BybitClient().fetch_quotes()


class WorkerAndWindowTests(unittest.TestCase):
    def window(self, snapshot=None):
        window = object.__new__(gui.CryptoApp)
        window.snapshot, window.busy = snapshot, True
        window.status, window.received = Mock(), Mock()
        window.tables = {'USD': Mock(), 'USDT': Mock()}
        window.source, window.price_note = Mock(), Mock()
        return window

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

    def test_failed_refresh_keeps_both_tables_and_timestamp(self):
        previous = Snapshot(parse_quotes(ticker_payload()), datetime.now(timezone.utc))
        window = self.window(previous)
        window._show_result(None, 'Нет сети')
        self.assertIs(window.snapshot, previous)
        self.assertFalse(window.busy)
        self.assertIn('устаревшие данные', window.status.set.call_args.args[0])
        for table in window.tables.values():
            table.item.assert_not_called()
        window.received.set.assert_not_called()

    def test_no_previous_values_are_fabricated_on_failure(self):
        window = self.window()
        window._show_result(None, 'Нет сети')
        self.assertIn('Данные не получены', window.status.set.call_args.args[0])
        for table in window.tables.values():
            table.item.assert_not_called()
        self.assertIsNone(window.snapshot)

    def test_success_updates_each_table_and_receipt_time(self):
        window = self.window()
        snapshot = Snapshot(
            parse_quotes(ticker_payload()), datetime(2026, 1, 1, tzinfo=timezone.utc),
            source='Test Exchange',
        )
        window._show_result(snapshot, None)
        for currency, table in window.tables.items():
            self.assertEqual(table.item.call_count, 8)
            self.assertEqual(
                {call.args[0] for call in table.item.call_args_list},
                {quote.row_id for quote in snapshot.quotes if quote.currency == currency},
            )
        self.assertIs(window.snapshot, snapshot)
        window.received.set.assert_called_once_with('Данные получены: 01.01.2026 03:00:00 МСК')
        self.assertIn('Test Exchange', window.source.set.call_args.args[0])
        self.assertIn('Test Exchange', window.price_note.set.call_args.args[0])
        self.assertIn('10', window.status.set.call_args.args[0])

    def test_missing_pairs_clear_old_prices_in_both_tables_after_successful_refresh(self):
        previous = Snapshot(parse_quotes(ticker_payload()), datetime.now(timezone.utc))
        window = self.window(previous)
        payload = ticker_payload()
        payload['result']['list'] = [
            item for item in payload['result']['list']
            if item['symbol'] not in ('BTCUSD', 'ETHUSDT')
        ]
        new_snapshot = Snapshot(parse_quotes(payload), datetime.now(timezone.utc))
        window._show_result(new_snapshot, None)
        for currency, row_id, old_price in (
            ('USD', 'BTC:USD', '60 000.10'),
            ('USDT', 'ETH:USDT', '3 001.25'),
        ):
            with self.subTest(currency=currency):
                row_call = next(
                    call for call in window.tables[currency].item.call_args_list
                    if call.args[0] == row_id
                )
                displayed_values = row_call.kwargs['values']
                self.assertIn('Нет данных по паре', displayed_values)
                self.assertIn('—', displayed_values)
                self.assertNotIn(old_price, displayed_values)
        self.assertIs(window.snapshot, new_snapshot)

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

    def test_display_preserves_usdt_deviation_and_prices_below_ten(self):
        self.assertEqual(gui.format_price(Decimal('1.0003')), '1.0003')
        self.assertEqual(gui.format_price(Decimal('0.9998')), '0.9998')
        self.assertEqual(gui.format_price(Decimal('2.34878')), '2.34878')
        self.assertEqual(gui.format_price(Decimal('10.123456')), '10.12')

    def test_poll_refreshes_only_when_enabled_due_and_idle(self):
        scenarios = (
            (True, 159.9, False, 0), (True, 160.0, False, 1),
            (False, 200.0, False, 0), (True, 200.0, True, 0),
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
