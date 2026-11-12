"""Проверки Bybit и интерфейса без интернета; цены в примерах условные."""

import copy
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from queue import Queue
import unittest
from unittest.mock import Mock, patch

import requests

spec = importlib.util.spec_from_file_location(
    'crypto_window_task6', Path(__file__).with_name('Задание 6.py')
)
gui = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gui
spec.loader.exec_module(gui)

BybitClient = gui.BybitClient
QuoteError = gui.QuoteError
Snapshot = gui.Snapshot
parse_quotes = gui.parse_quotes


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


def metrics_payload():
    """Оборот пары, количество монет и доля изменения заведомо различаются."""
    payload = ticker_payload()
    metrics = {
        'BTCUSD': ('1000', '0.5', '-0.0125'),
        'ETHUSD': ('2000', '8', '0.02'),
        'USDTUSD': ('9000000', '8997300', '0.003'),
        'BTCUSDT': ('888888', '12', '0.10'),
        'ETHUSDT': ('777777', '11', '-0.10'),
        'GRAMUSDT': ('6000', '9000', '-0.04'),
        'BNBUSDT': ('2000', '5', '0.10'),
        'SOLUSDT': ('3000', '6', '0'),
        'XRPUSDT': ('4000', '7', '-0.02'),
        'DOGEUSDT': ('5000', '8', '0.03'),
    }
    for item in payload['result']['list']:
        turnover, volume, change = metrics[item['symbol']]
        item.update(turnover24h=turnover, volume24h=volume, price24hPcnt=change)
    return payload


def by_id(payload=None):
    return {quote.row_id: quote for quote in parse_quotes(
        ticker_payload() if payload is None else payload
    )}


def market(payload, symbol):
    return next(item for item in payload['result']['list'] if item['symbol'] == symbol)


TEST_TIME = datetime(2026, 1, 1, 12, 7, tzinfo=timezone.utc)


def fx_payload(now=TEST_TIME):
    return {
        'result': 'success', 'base_code': 'USD',
        'time_last_update_unix': int((now - timedelta(hours=1)).timestamp()),
        'time_next_update_unix': int((now + timedelta(hours=23)).timestamp()),
        'rates': {'USD': 1, 'EUR': '0.9', 'JPY': '150', 'GBP': '0.8',
                  'AUD': '1.5', 'CAD': '1.4', 'CHF': '0.88', 'CNY': '7.2',
                  'RUB': '100', 'KZT': '500', 'UZS': '13000'},
    }


def example_fx(now=TEST_TIME):
    return gui.parse_fx(fx_payload(now), now)


def history_payload(symbol='BTCUSD', now=TEST_TIME, value='10'):
    candles = [
        [str(int((moment - timedelta(minutes=15)).timestamp()) * 1000),
         value, value, value, value, '0', '0']
        for moment in reversed(gui.history_moments(now))
    ]
    return {'retCode': 0, 'time': int(now.timestamp() * 1000),
            'result': {'category': 'spot', 'symbol': symbol, 'list': candles}}


def example_history(currency='USD', values=('100', '110', '105'), *,
                    symbol='BTC', now=TEST_TIME, calculated=False, fx_date=None):
    """Разные масштабы цен позволяют проверить сопоставление доходностей."""
    points = tuple(
        gui.HistoryPoint(now - timedelta(hours=len(values) - index - 1),
                         Decimal(value), index == len(values) - 1)
        for index, value in enumerate(values)
    )
    return gui.HistorySeries((symbol, currency), points, now, calculated, fx_date)


class ParseQuotesTests(unittest.TestCase):
    def test_returns_eight_assets_in_all_twelve_currencies(self):
        quotes = parse_quotes(ticker_payload())
        expected = {
            'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'USDT': 'Tether',
            'GRAM': 'Gram (Toncoin)', 'BNB': 'BNB', 'SOL': 'Solana',
            'XRP': 'XRP', 'DOGE': 'Dogecoin',
        }
        self.assertEqual(len(quotes), 96)
        self.assertEqual(len({quote.row_id for quote in quotes}), 96)
        for currency in gui.QUOTE_CURRENCIES:
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
        self.assertEqual(quotes['GRAM:USD'].provenance, 'calculated')
        self.assertEqual(quotes['GRAM:USD'].price, Decimal('0.00234878') * Decimal('1.0003'))

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
        self.assertEqual(len(quotes), 96)
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


class MarketMetricsTests(unittest.TestCase):
    def quotes(self, payload=None, fx=None):
        return {q.row_id: q for q in parse_quotes(
            metrics_payload() if payload is None else payload, fx,
        )}

    def test_direct_pair_uses_turnover_in_money_and_signed_percentage(self):
        quote = self.quotes()['BTC:USD']
        self.assertEqual(quote.turnover_24h, Decimal('1000'))
        self.assertNotEqual(quote.turnover_24h, Decimal('0.5'))
        self.assertEqual(quote.turnover_market, 'BTCUSD')
        self.assertEqual(quote.change_24h, Decimal('-1.25'))
        self.assertEqual(quote.price, Decimal('60000.10'))

    def test_each_asset_and_pair_keeps_its_own_turnover_without_summing_markets(self):
        quotes = self.quotes()
        self.assertEqual(quotes['BTC:USD'].turnover_24h, Decimal('1000'))
        self.assertEqual(quotes['ETH:USD'].turnover_24h, Decimal('2000'))
        self.assertEqual(quotes['BTC:USDT'].turnover_24h, Decimal('888888'))
        self.assertEqual(quotes['BTC:USDT'].turnover_market, 'BTCUSDT')
        self.assertEqual(quotes['ETH:USD'].turnover_market, 'ETHUSD')

    def test_zero_metrics_are_values_and_not_missing_data(self):
        payload = metrics_payload()
        market(payload, 'BTCUSD').update(turnover24h='0', price24hPcnt='0')
        quote = self.quotes(payload)['BTC:USD']
        self.assertEqual(quote.turnover_24h, Decimal('0'))
        self.assertEqual(quote.change_24h, Decimal('0'))
        self.assertIsNotNone(quote.turnover_24h)
        self.assertIsNotNone(quote.change_24h)
        self.assertEqual(gui.format_change(quote.change_24h), '0.00%')
        self.assertNotEqual(gui.format_turnover(quote.turnover_24h), '—')
        self.assertEqual(gui.format_change(None), '—')
        self.assertEqual(gui.format_turnover(None), '—')

    def test_missing_metrics_do_not_use_volume_as_turnover_or_remove_valid_price(self):
        payload = ticker_payload()
        market(payload, 'BTCUSD')['volume24h'] = '123456'
        quote = self.quotes(payload)['BTC:USD']
        self.assertIsNone(quote.turnover_24h)
        self.assertIsNone(quote.change_24h)
        self.assertEqual(quote.price, Decimal('60000.10'))

    def test_malformed_optional_metrics_are_isolated_from_each_other_and_prices(self):
        invalid_common = (None, '', 'NaN', 'Infinity', '-Infinity', True, {}, [])
        cases = (
            ('turnover24h', 'turnover_24h', invalid_common + ('-1',)),
            ('price24hPcnt', 'change_24h', invalid_common + ('-1', '-1.01')),
        )
        for field, attribute, invalid_values in cases:
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    payload = metrics_payload()
                    market(payload, 'BTCUSD')[field] = value
                    quote = self.quotes(payload)['BTC:USD']
                    self.assertIsNone(getattr(quote, attribute))
                    self.assertEqual(quote.price, Decimal('60000.10'))
                    self.assertEqual(quote.status, 'available')
                    if field == 'turnover24h':
                        self.assertEqual(quote.change_24h, Decimal('-1.25'))
                    else:
                        self.assertEqual(quote.turnover_24h, Decimal('1000'))

    def test_tether_conversion_uses_real_bridge_price_and_compounds_both_returns(self):
        quote = self.quotes()['BNB:USD']
        self.assertEqual(quote.turnover_24h, Decimal('2000') * Decimal('1.0003'))
        self.assertNotEqual(quote.turnover_24h, Decimal('9000000'))
        self.assertEqual(quote.turnover_market, 'BNBUSDT')
        self.assertEqual(quote.change_24h, Decimal('10.33'))
        self.assertNotEqual(quote.change_24h, Decimal('10.3'))
        self.assertEqual(quote.provenance, 'calculated')

    def test_fixed_fx_rescales_turnover_but_preserves_usd_percentage(self):
        quotes = self.quotes(fx=example_fx())
        usd, rub, eur = (quotes[f'BNB:{currency}'] for currency in ('USD', 'RUB', 'EUR'))
        self.assertEqual(rub.turnover_24h, usd.turnover_24h * Decimal('100'))
        self.assertEqual(eur.turnover_24h, usd.turnover_24h * Decimal('0.9'))
        self.assertEqual(rub.change_24h, usd.change_24h)
        self.assertEqual(eur.change_24h, usd.change_24h)
        self.assertEqual(rub.turnover_market, 'BNBUSDT')
        self.assertEqual(rub.fx_date, example_fx().updated_at)

    def test_direct_usd_metrics_take_priority_in_usd_and_fiat_calculations(self):
        quotes = self.quotes(fx=example_fx())
        self.assertEqual(quotes['BTC:USD'].turnover_24h, Decimal('1000'))
        self.assertEqual(quotes['BTC:RUB'].turnover_24h, Decimal('100000'))
        self.assertEqual(quotes['BTC:RUB'].turnover_market, 'BTCUSD')
        self.assertEqual(quotes['BTC:RUB'].change_24h, Decimal('-1.25'))
        payload = metrics_payload()
        del market(payload, 'BTCUSD')['turnover24h']
        del market(payload, 'BTCUSD')['price24hPcnt']
        quotes = self.quotes(payload, example_fx())
        self.assertIsNone(quotes['BTC:USD'].turnover_24h)
        self.assertIsNone(quotes['BTC:RUB'].change_24h)
        self.assertIsNone(quotes['BTC:RUB'].turnover_24h)

    def test_direct_eur_metrics_override_calculated_usd_and_fx_metrics(self):
        payload = metrics_payload()
        payload['result']['list'].append({
            'symbol': 'BTCEUR', 'lastPrice': '55000',
            'lowPrice24h': '54000', 'highPrice24h': '56000',
            'turnover24h': '700', 'volume24h': '0.123', 'price24hPcnt': '-0.02',
        })
        quote = self.quotes(payload, example_fx())['BTC:EUR']
        self.assertEqual(quote.turnover_24h, Decimal('700'))
        self.assertEqual(quote.change_24h, Decimal('-2'))
        self.assertEqual(quote.turnover_market, 'BTCEUR')
        self.assertEqual(quote.provenance, 'direct')
        self.assertIsNone(quote.fx_date)

    def test_missing_change_on_either_leg_does_not_fabricate_compound_return(self):
        for symbol in ('BNBUSDT', 'USDTUSD'):
            with self.subTest(symbol=symbol):
                payload = metrics_payload()
                del market(payload, symbol)['price24hPcnt']
                quote = self.quotes(payload)['BNB:USD']
                self.assertIsNone(quote.change_24h)
                self.assertEqual(quote.turnover_24h, Decimal('2000.6000'))
                self.assertIsNotNone(quote.price)

    def test_bridge_turnover_is_not_needed_but_source_turnover_is_required(self):
        payload = metrics_payload()
        del market(payload, 'USDTUSD')['turnover24h']
        quote = self.quotes(payload)['BNB:USD']
        self.assertEqual(quote.turnover_24h, Decimal('2000.6000'))
        self.assertEqual(quote.change_24h, Decimal('10.33'))
        del market(payload, 'BNBUSDT')['turnover24h']
        quote = self.quotes(payload)['BNB:USD']
        self.assertIsNone(quote.turnover_24h)
        self.assertEqual(quote.change_24h, Decimal('10.33'))

    def test_identity_and_missing_quotes_have_no_market_metrics(self):
        payload = metrics_payload()
        payload['result']['list'] = [market(payload, 'BTCUSDT')]
        quotes = self.quotes(payload)
        for row_id in ('USDT:USDT', 'BTC:USD', 'ETH:EUR'):
            with self.subTest(row_id=row_id):
                self.assertIsNone(quotes[row_id].turnover_24h)
                self.assertIsNone(quotes[row_id].change_24h)
                self.assertEqual(quotes[row_id].turnover_market, '')

    def test_change_format_distinguishes_increase_decrease_and_zero(self):
        self.assertEqual(gui.format_change(Decimal('0.68')), '▲ +0.68%')
        self.assertEqual(gui.format_change(Decimal('-1.2')), '▼ -1.20%')
        self.assertEqual(gui.format_change(Decimal('0')), '0.00%')
        self.assertEqual(gui.format_change(None), '—')


class BybitClientTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(gui.requests, 'get')
        self.get = patcher.start()
        self.addCleanup(patcher.stop)
        self.response = Mock()
        self.response.json.return_value = ticker_payload()
        self.get.return_value = self.response

    def test_one_ticker_request_with_cached_fx_uses_spot_and_timeout(self):
        client = BybitClient()
        client.fx_cache = example_fx(datetime.now(timezone.utc))
        client.fetch_quotes()
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
        self.assertEqual(len(snapshot.quotes), 96)
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


class FxAndCalculationTests(unittest.TestCase):
    def test_all_lesson_fiat_currencies_and_usdt_are_available(self):
        self.assertEqual(set(gui.QUOTE_CURRENCIES), {
            'USD', 'EUR', 'JPY', 'GBP', 'AUD', 'CAD', 'CHF', 'CNY', 'RUB', 'KZT', 'UZS', 'USDT',
        })
        self.assertEqual(gui.QUOTE_CURRENCIES[0], 'USD')

    def test_fiat_calculation_uses_direct_usd_and_actual_tether_usd_cross(self):
        quotes = {q.row_id: q for q in parse_quotes(ticker_payload(), example_fx())}
        btc, bnb = quotes['BTC:RUB'], quotes['BNB:RUB']
        self.assertEqual(btc.price, Decimal('60000.10') * 100)
        self.assertEqual(btc.markets, ('BTCUSD',))
        self.assertEqual(bnb.price, Decimal('605.45') * Decimal('1.0003') * 100)
        self.assertEqual(bnb.markets, ('BNBUSDT', 'USDTUSD'))
        for quote in (btc, bnb):
            self.assertEqual(quote.provenance, 'calculated')
            self.assertIsNone(quote.low_24h)
            self.assertIsNone(quote.high_24h)
            self.assertEqual(quote.fx_date, example_fx().updated_at)
            self.assertIn('USD/RUB', quote.source_path)

    def test_usdt_fiat_uses_real_usdt_usd_deviation(self):
        quotes = {q.row_id: q for q in parse_quotes(ticker_payload(), example_fx())}
        self.assertEqual(quotes['USDT:UZS'].price, Decimal('1.0003') * 13000)
        self.assertNotEqual(quotes['USDT:UZS'].price, Decimal('13000'))
        self.assertIsNone(quotes['USDT:USDT'].price)

    def test_direct_eur_or_future_fiat_pair_overrides_calculation(self):
        for symbol, currency in (('BTCEUR', 'EUR'), ('BNBRUB', 'RUB')):
            with self.subTest(symbol=symbol):
                payload = ticker_payload()
                payload['result']['list'].append({
                    'symbol': symbol, 'lastPrice': '123.45',
                    'lowPrice24h': '120', 'highPrice24h': '125',
                })
                quotes = {q.row_id: q for q in parse_quotes(payload, example_fx())}
                quote = quotes[f'{symbol[:-len(currency)]}:{currency}']
                self.assertEqual(quote.price, Decimal('123.45'))
                self.assertEqual(quote.provenance, 'direct')
                self.assertEqual(quote.low_24h, Decimal('120'))
                self.assertIsNone(quote.fx_date)

    def test_missing_fx_rate_only_disables_corresponding_calculations(self):
        payload = fx_payload()
        del payload['rates']['RUB']
        fx = gui.parse_fx(payload, TEST_TIME)
        quotes = {q.row_id: q for q in parse_quotes(ticker_payload(), fx)}
        self.assertEqual(quotes['BTC:RUB'].status, 'missing')
        self.assertEqual(quotes['BTC:EUR'].status, 'available')
        self.assertEqual(quotes['BTC:USD'].price, Decimal('60000.10'))
        self.assertEqual(quotes['BNB:USD'].provenance, 'calculated')

    def test_missing_usdt_usd_never_uses_a_constant_peg(self):
        payload = ticker_payload()
        payload['result']['list'] = [item for item in payload['result']['list']
                                     if item['symbol'] != 'USDTUSD']
        quotes = {q.row_id: q for q in parse_quotes(payload, example_fx())}
        self.assertEqual(quotes['BNB:USD'].status, 'missing')
        self.assertEqual(quotes['BNB:RUB'].status, 'missing')
        self.assertEqual(quotes['BTC:RUB'].price, Decimal('6000010.00'))

    def test_fx_rejects_wrong_base_or_non_unit_usd(self):
        for field, value in (('base_code', 'EUR'), ('result', 'error')):
            payload = fx_payload()
            payload[field] = value
            with self.subTest(field=field), self.assertRaises(QuoteError):
                gui.parse_fx(payload, TEST_TIME)
        for value in ('0.999', None, 'NaN', True):
            payload = fx_payload()
            payload['rates']['USD'] = value
            with self.subTest(usd=value), self.assertRaises(QuoteError):
                gui.parse_fx(payload, TEST_TIME)

    def test_fx_rejects_invalid_fiat_numbers(self):
        for value in ('0', '-1', 'Infinity', 'NaN', None, True):
            payload = fx_payload()
            payload['rates']['RUB'] = value
            with self.subTest(value=value), self.assertRaises(QuoteError):
                gui.parse_fx(payload, TEST_TIME)

    def test_fx_dates_are_aware_and_expired_data_is_marked_stale(self):
        payload = fx_payload(TEST_TIME - timedelta(days=2))
        fx = gui.parse_fx(payload, TEST_TIME)
        self.assertTrue(fx.stale)
        self.assertIsNotNone(fx.updated_at.utcoffset())
        quotes = {q.row_id: q for q in parse_quotes(ticker_payload(), fx)}
        self.assertTrue(quotes['BTC:RUB'].fx_stale)
        self.assertFalse(quotes['BTC:USD'].fx_stale)

    def test_fx_rejects_future_or_implausibly_long_cache_dates(self):
        scenarios = ((TEST_TIME + timedelta(minutes=6), TEST_TIME + timedelta(days=1)),
                     (TEST_TIME, TEST_TIME + timedelta(days=3)),
                     (TEST_TIME, TEST_TIME),
                     (datetime(2000, 1, 1, tzinfo=timezone.utc), TEST_TIME))
        for updated, next_update in scenarios:
            payload = fx_payload()
            payload['time_last_update_unix'] = updated.timestamp()
            payload['time_next_update_unix'] = next_update.timestamp()
            with self.subTest(updated=updated, next_update=next_update), self.assertRaises(QuoteError):
                gui.parse_fx(payload, TEST_TIME)

    def test_fx_cache_is_reused_until_daily_next_update(self):
        client = BybitClient()
        now = datetime.now(timezone.utc)
        with patch.object(client, '_request_json', return_value=fx_payload(now)) as request:
            first = client._get_fx()
            second = client._get_fx()
        self.assertEqual(first, second)
        request.assert_called_once_with(client.fx_url)
        self.assertFalse(second.stale)

    def test_failed_fx_has_retry_backoff_and_preserves_expired_cache_as_stale(self):
        client = BybitClient()
        now = datetime.now(timezone.utc)
        expired = gui.parse_fx(fx_payload(now - timedelta(days=2)), now)
        client.fx_cache = expired
        with patch.object(client, '_request_json', side_effect=QuoteError('Нет FX')) as request:
            with patch.object(gui.time, 'monotonic', return_value=100):
                first = client._get_fx()
            with patch.object(gui.time, 'monotonic', return_value=159.9):
                second = client._get_fx()
            self.assertEqual(request.call_count, 1)
            with patch.object(gui.time, 'monotonic', return_value=160):
                client._get_fx()
            self.assertEqual(request.call_count, 2)
        self.assertTrue(first.stale)
        self.assertEqual(first.updated_at, expired.updated_at)
        self.assertEqual(first, second)
        self.assertEqual(client.fx_error, 'Нет FX')

    def test_initial_fx_failure_keeps_available_bybit_prices(self):
        client = BybitClient()
        with patch.object(client, '_request_json', side_effect=[ticker_payload(), QuoteError('Нет FX')]):
            snapshot = client.fetch_quotes()
        quotes = {q.row_id: q for q in snapshot.quotes}
        self.assertIsNone(snapshot.fx)
        self.assertEqual(snapshot.fx_error, 'Нет FX')
        self.assertEqual(quotes['BTC:USD'].price, Decimal('60000.10'))
        self.assertEqual(quotes['BTC:RUB'].status, 'missing')

    def test_receipt_timestamp_is_taken_before_waiting_for_fx(self):
        fx = example_fx()
        class AdvancingClock(datetime):
            current = TEST_TIME

            @classmethod
            def now(cls, tz=None):
                return cls.current

        def slow_fx():
            AdvancingClock.current = TEST_TIME + timedelta(seconds=15)
            return fx

        client = BybitClient()
        with patch.object(client, '_request_json', return_value=ticker_payload()), \
                patch.object(client, '_get_fx', side_effect=slow_fx), \
                patch.object(gui, 'datetime', AdvancingClock):
            snapshot = client.fetch_quotes()
        self.assertEqual(snapshot.received_at, TEST_TIME)


class HistoryTests(unittest.TestCase):
    def test_reverse_candles_are_sorted_by_close_time(self):
        points = gui.parse_history(history_payload(), 'BTCUSD', TEST_TIME)
        self.assertEqual(tuple(p.timestamp for p in points), gui.history_moments(TEST_TIME))
        self.assertTrue(all(p.close == Decimal('10') and not p.is_current for p in points))

    def test_open_candle_and_points_later_than_server_time_are_excluded(self):
        payload = history_payload()
        boundary = gui.history_moments(TEST_TIME)[-1]
        payload['result']['list'].insert(0, [str(int(boundary.timestamp() * 1000)), '1', '1', '1', '999'])
        points = gui.parse_history(payload, 'BTCUSD', TEST_TIME)
        self.assertNotIn(Decimal('999'), [p.close for p in points])
        payload['time'] = int((boundary - timedelta(seconds=1)).timestamp() * 1000)
        points = gui.parse_history(payload, 'BTCUSD', TEST_TIME)
        self.assertTrue(all(p.timestamp < boundary for p in points))

    def test_history_rejects_wrong_market_duplicates_and_invalid_close(self):
        payloads = []
        wrong = history_payload('ETHUSD')
        payloads.append(wrong)
        duplicate = history_payload()
        duplicate['result']['list'].append(copy.deepcopy(duplicate['result']['list'][0]))
        payloads.append(duplicate)
        for value in ('NaN', 'Infinity', '0', '-1'):
            invalid = history_payload()
            invalid['result']['list'][0][4] = value
            payloads.append(invalid)
        for payload in payloads:
            with self.subTest(payload=payload['result']['symbol']), self.assertRaises(QuoteError):
                gui.parse_history(payload, 'BTCUSD', TEST_TIME)

    def test_history_rejects_malformed_timestamp_and_server_clock(self):
        for value in (True, '123', '1.5', None):
            payload = history_payload()
            payload['result']['list'][0][0] = value
            with self.subTest(value=value), self.assertRaises(QuoteError):
                gui.parse_history(payload, 'BTCUSD', TEST_TIME)
        for value in (0, True, '123', float('inf')):
            payload = history_payload()
            payload['time'] = value
            with self.subTest(server=value), self.assertRaises(QuoteError):
                gui.parse_history(payload, 'BTCUSD', TEST_TIME)

    def test_direct_history_has_closed_points_and_current_snapshot_endpoint(self):
        client = BybitClient()
        quote = by_id()['BTC:USD']
        with patch.object(client, '_request_json', return_value=history_payload()) as request:
            series = client.fetch_history(quote, TEST_TIME)
        self.assertEqual(len(series.points), 97)
        self.assertEqual(series.points[-1], gui.HistoryPoint(TEST_TIME, quote.price, True))
        self.assertFalse(series.calculated)
        params = request.call_args.args[1]
        self.assertEqual((params['category'], params['symbol'], params['interval']), ('spot', 'BTCUSD', '15'))
        self.assertLess(params['end'], int(gui.history_moments(TEST_TIME)[-1].timestamp() * 1000))

    def test_cross_history_aligns_timestamps_and_applies_one_fixed_fx_rate(self):
        client = BybitClient()
        quote = next(q for q in parse_quotes(ticker_payload(), example_fx()) if q.row_id == 'BNB:RUB')
        moments = gui.history_moments(TEST_TIME)
        left = tuple(gui.HistoryPoint(moment, Decimal(index + 1)) for index, moment in enumerate(moments))
        right = tuple(gui.HistoryPoint(moment, Decimal(index + 2)) for index, moment in reversed(list(enumerate(moments))))
        with patch.object(client, '_market_history', side_effect=[left, right]) as request:
            series = client.fetch_history(quote, TEST_TIME)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(series.points[0].close, Decimal('200'))
        self.assertEqual(series.points[10].close, Decimal(11 * 12 * 100))
        self.assertEqual(series.points[-1].close, quote.price)
        self.assertEqual(series.fx_date, quote.fx_date)
        self.assertTrue(series.calculated)

    def test_cross_history_refuses_shifted_or_missing_timestamps(self):
        client = BybitClient()
        quote = by_id()['BNB:USD']
        points = tuple(gui.HistoryPoint(moment, Decimal('10')) for moment in gui.history_moments(TEST_TIME))
        shifted = tuple(gui.HistoryPoint(p.timestamp + timedelta(minutes=15), p.close) for p in points)
        with patch.object(client, '_market_history', side_effect=[points, shifted]), \
                self.assertRaisesRegex(QuoteError, 'Неполные данные'):
            client.fetch_history(quote, TEST_TIME)

    def test_incomplete_history_is_not_cached_and_next_attempt_can_recover(self):
        client = BybitClient()
        partial = history_payload()
        partial['result']['list'].pop(5)
        with patch.object(client, '_request_json', side_effect=[partial, history_payload()]) as request:
            with self.assertRaisesRegex(QuoteError, 'Неполные данные'):
                client.fetch_history(by_id()['BTC:USD'], TEST_TIME)
            self.assertFalse(client.history_cache)
            series = client.fetch_history(by_id()['BTC:USD'], TEST_TIME)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(series.points), 97)

    def test_switching_fiat_reuses_market_history_until_cache_ttl(self):
        client = BybitClient()
        quotes = {q.row_id: q for q in parse_quotes(ticker_payload(), example_fx())}
        with patch.object(client, '_request_json', return_value=history_payload()) as request:
            with patch.object(gui.time, 'monotonic', return_value=100):
                rub = client.fetch_history(quotes['BTC:RUB'], TEST_TIME)
            with patch.object(gui.time, 'monotonic', return_value=159.9):
                uzs = client.fetch_history(quotes['BTC:UZS'], TEST_TIME)
            self.assertEqual(request.call_count, 1)
            with patch.object(gui.time, 'monotonic', return_value=160):
                client.fetch_history(quotes['BTC:RUB'], TEST_TIME)
            self.assertEqual(request.call_count, 2)
        self.assertEqual(uzs.points[0].close / rub.points[0].close, Decimal('130'))

    def test_missing_and_identity_quotes_have_no_history_request(self):
        client = BybitClient()
        with patch.object(client, '_request_json') as request:
            for row_id in ('BTC:RUB', 'USDT:USDT'):
                with self.subTest(row_id=row_id), self.assertRaises(QuoteError):
                    client.fetch_history(by_id()[row_id], TEST_TIME)
        request.assert_not_called()


class ComparisonTests(unittest.TestCase):
    def comparison(self, *histories, errors=()):
        return gui.ComparisonHistory('BTC', tuple(histories), TEST_TIME, errors)

    def quotes(self, with_fx=True, direct_eur=False):
        payload = ticker_payload()
        if direct_eur:
            payload['result']['list'].append({
                'symbol': 'BTCEUR', 'lastPrice': '54001',
                'lowPrice24h': '53000', 'highPrice24h': '55000',
            })
        all_quotes = parse_quotes(payload, example_fx() if with_fx else None)
        return tuple(q for currency in ('USD', 'EUR') for q in all_quotes
                     if q.symbol == 'BTC' and q.currency == currency)

    def test_normalization_compares_percentage_changes_not_absolute_prices(self):
        result = gui.normalize_comparison(self.comparison(
            example_history('USD'), example_history('EUR', ('200', '218', '208')),
        ))
        self.assertEqual(tuple(result), ('USD', 'EUR'))
        self.assertEqual([value for _, value in result['USD']], [0, 10, 5])
        self.assertEqual([value for _, value in result['EUR']], [0, 9, 4])
        self.assertEqual([moment for moment, _ in result['USD']],
                         [moment for moment, _ in result['EUR']])

    def test_both_lines_start_at_first_common_time_instead_of_zipping_rows(self):
        result = gui.normalize_comparison(self.comparison(
            example_history('USD', ('100', '110', '121')),
            example_history('EUR', ('200', '240')),
        ))
        expected_times = [TEST_TIME - timedelta(hours=1), TEST_TIME]
        self.assertEqual([moment for moment, _ in result['USD']], expected_times)
        self.assertEqual([moment for moment, _ in result['EUR']], expected_times)
        self.assertEqual([value for _, value in result['USD']], [0, 10])
        self.assertEqual([value for _, value in result['EUR']], [0, 20])

    def test_fewer_than_two_common_times_cannot_draw_a_comparison(self):
        left = example_history()
        right = example_history('EUR', now=TEST_TIME + timedelta(hours=2))
        with self.assertRaises(QuoteError):
            gui.normalize_comparison(self.comparison(left, right))

    def test_fixed_fx_conversion_has_identical_trend_without_artificial_offset(self):
        result = gui.normalize_comparison(self.comparison(
            example_history('USD', ('100', '110', '105')),
            example_history('EUR', ('90', '99', '94.5'),
                            calculated=True, fx_date=example_fx().updated_at),
        ))
        self.assertEqual(result['USD'], result['EUR'])

    def test_partial_comparison_normalizes_available_line_without_making_up_other(self):
        result = gui.normalize_comparison(self.comparison(
            example_history('USD'), errors=(('EUR', 'Нет истории'),),
        ))
        self.assertEqual(tuple(result), ('USD',))
        self.assertEqual([value for _, value in result['USD']], [0, 10, 5])

    def test_worker_loads_usd_and_direct_eur_with_one_snapshot_time(self):
        quotes = self.quotes(direct_eur=True)
        provider, results = Mock(), Queue()
        histories = (example_history('USD'), example_history('EUR'))
        provider.fetch_history.side_effect = histories
        token = ('BTC', 7)
        gui.fetch_comparison_in_worker(provider, quotes, TEST_TIME, results, token)
        result_token, comparison, error = results.get_nowait()
        self.assertEqual(result_token, token)
        self.assertIsNone(error)
        self.assertEqual(comparison.histories, histories)
        self.assertEqual(comparison.received_at, TEST_TIME)
        self.assertEqual(comparison.errors, ())
        self.assertEqual([call.args for call in provider.fetch_history.call_args_list],
                         [(quotes[0], TEST_TIME), (quotes[1], TEST_TIME)])
        self.assertEqual(quotes[1].markets, ('BTCEUR',))
        self.assertEqual(quotes[1].provenance, 'direct')

    def test_worker_preserves_usd_when_eur_history_fails(self):
        provider, results = Mock(), Queue()
        usd = example_history('USD')
        provider.fetch_history.side_effect = [usd, QuoteError('Нет истории EUR')]
        gui.fetch_comparison_in_worker(provider, self.quotes(), TEST_TIME, results, ('BTC', 1))
        _, comparison, error = results.get_nowait()
        self.assertIsNone(error)
        self.assertEqual(comparison.histories, (usd,))
        self.assertIn(('EUR', 'Нет истории EUR'), comparison.errors)

    def test_worker_does_not_request_missing_eur_price_or_assume_fx(self):
        provider, results = Mock(), Queue()
        quotes = self.quotes(with_fx=False)
        usd = example_history('USD')
        provider.fetch_history.return_value = usd
        gui.fetch_comparison_in_worker(provider, quotes, TEST_TIME, results, ('BTC', 1))
        _, comparison, error = results.get_nowait()
        provider.fetch_history.assert_called_once_with(quotes[0], TEST_TIME)
        self.assertIsNone(error)
        self.assertEqual(comparison.histories, (usd,))
        self.assertEqual([currency for currency, _ in comparison.errors], ['EUR'])

    def test_worker_rejects_other_pair_or_snapshot_without_losing_valid_line(self):
        usd = example_history('USD')
        invalid_series = (
            example_history('EUR', symbol='ETH'),
            example_history('EUR', now=TEST_TIME - timedelta(seconds=1)),
        )
        for wrong in invalid_series:
            with self.subTest(pair=wrong.pair_key, time=wrong.received_at):
                provider, results = Mock(), Queue()
                provider.fetch_history.side_effect = [usd, wrong]
                gui.fetch_comparison_in_worker(provider, self.quotes(), TEST_TIME, results, ('BTC', 1))
                _, comparison, error = results.get_nowait()
                self.assertIsNone(error)
                self.assertEqual(comparison.histories, (usd,))
                self.assertEqual([currency for currency, _ in comparison.errors], ['EUR'])

    def test_all_history_failures_deliver_error_without_internal_details(self):
        provider, results = Mock(), Queue()
        provider.fetch_history.side_effect = RuntimeError('private detail')
        token = ('BTC', 1)
        gui.fetch_comparison_in_worker(provider, self.quotes(), TEST_TIME, results, token)
        result_token, comparison, error = results.get_nowait()
        self.assertEqual(result_token, token)
        self.assertIsNone(comparison)
        self.assertTrue(error)
        self.assertNotIn('private detail', error)


class FakeVar:
    """Минимальная StringVar без создания окна Tk."""
    def __init__(self, value=''):
        self.value = value
        self.history = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        self.history.append(value)


class FakeTable:
    """Хранит видимые строки и выбор так же, как нужная тестам часть Treeview."""
    def __init__(self):
        self.rows = {}
        self.tags = {}
        self.selected = ()
        self.headings = {}
        self.updates = []

    def get_children(self, item=''):
        return tuple(self.rows)

    def exists(self, iid):
        return iid in self.rows

    def insert(self, parent, index, iid, values=(), **kwargs):
        self.rows[iid] = tuple(values)
        self.tags[iid] = tuple(kwargs.get('tags', ()))
        return iid

    def delete(self, *items):
        for iid in items:
            self.rows.pop(iid, None)
            self.tags.pop(iid, None)
        self.selected = tuple(iid for iid in self.selected if iid in self.rows)

    def item(self, iid, option=None, **kwargs):
        if 'values' in kwargs:
            self.rows[iid] = tuple(kwargs['values'])
            self.updates.append((iid, self.rows[iid]))
        if 'tags' in kwargs:
            self.tags[iid] = tuple(kwargs['tags'])
        if option == 'values':
            return self.rows[iid]
        if option == 'tags':
            return self.tags[iid]
        return {'values': self.rows[iid], 'tags': self.tags[iid]}

    def selection(self):
        return self.selected

    def selection_set(self, items):
        self.selected = (items,) if isinstance(items, str) else tuple(items)

    def selection_remove(self, *items):
        self.selected = tuple(iid for iid in self.selected if iid not in items)

    def focus(self, item=None):
        if item is not None:
            self.focused = item
        return getattr(self, 'focused', '')

    def see(self, item):
        self.visible_item = item

    def heading(self, column, **kwargs):
        self.headings[column] = kwargs


class WorkerAndWindowTests(unittest.TestCase):
    def window(self, snapshot=None):
        window = object.__new__(gui.CryptoApp)
        window.snapshot, window.busy = snapshot, False
        window.closed, window.stale, window.last_error = False, False, ''
        window.status = FakeVar()
        window.received = FakeVar('Данные ещё не получены')
        window.source, window.price_note = FakeVar(), FakeVar()
        window.coin_selection = FakeVar('BTC — Bitcoin')
        window.currency_selection = FakeVar('USD — доллар США')
        window.pair_title, window.price_text = FakeVar(), FakeVar()
        window.low_text, window.high_text = FakeVar(), FakeVar()
        window.change_text, window.turnover_text = FakeVar(), FakeVar()
        window.change_label = Mock()
        window.selection_hint, window.card_state = FakeVar(), FakeVar()
        window.market_title = FakeVar()
        window.displayed_currency = None
        window.state_label, window.status_label = Mock(), Mock()
        window.table = FakeTable()
        window.provider, window.refresh, window.refresh_button = Mock(), Mock(), Mock()
        window.root, window.results = Mock(), Queue()
        window.auto_refresh = FakeVar(False)
        window.last_request_started = None
        window.snapshot_version = 0
        window.chart_results = Queue()
        window.chart_busy = False
        window.chart_pending = window.chart_debounce_id = None
        window.chart_token = window.chart_active_token = None
        window.chart_series = None
        window.chart_message = ''
        window.chart_title, window.chart_caption = FakeVar(), FakeVar()
        window.chart_legend_usd, window.chart_legend_eur = FakeVar(), FakeVar()
        window._draw_chart, window._fit_card_price = Mock(), Mock()
        return window

    def snapshot(self, payload=None, received_at=None):
        return Snapshot(
            parse_quotes(ticker_payload() if payload is None else payload),
            received_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def metrics_snapshot(self, payload=None, fx=None):
        return Snapshot(parse_quotes(metrics_payload() if payload is None else payload, fx),
                        TEST_TIME, fx=fx)

    def assert_no_network_on_selection(self, window):
        window.refresh.assert_not_called()
        window.provider.fetch_quotes.assert_not_called()

    def test_worker_delivers_success_to_queue(self):
        provider, results = Mock(), Queue()
        snapshot = self.snapshot()
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

    def test_success_preserves_selection_and_updates_card_table_and_receipt(self):
        window = self.window()
        window.coin_selection.set('ETH — Ethereum')
        window.currency_selection.set('USDT — Tether')
        snapshot = Snapshot(self.snapshot().quotes, self.snapshot().received_at, source='Test Exchange')
        window._show_result(snapshot, None)
        self.assertEqual(window._selected_codes(), ('ETH', 'USDT'))
        self.assertEqual(len(window.table.rows), 8)
        self.assertEqual(set(window.table.rows), {
            quote.row_id for quote in snapshot.quotes if quote.currency == 'USDT'
        })
        self.assertEqual(window.table.selection(), ('ETH:USDT',))
        self.assertIn('3 001.25', window.price_text.get())
        self.assertIs(window.snapshot, snapshot)
        self.assertEqual(window.received.get(), 'Данные получены: 01.01.2026 03:00:00 МСК')
        self.assertIn('Test Exchange', window.source.get())
        self.assertIn('Расчётные цены', window.price_note.get())
        self.assertFalse(window.stale)
        self.assertEqual(window.last_error, '')

    def test_currency_selection_uses_saved_direct_prices_without_request(self):
        window = self.window()
        window._show_result(self.snapshot(), None)
        received_history = list(window.received.history)
        self.assertIn('60 000.10', window.price_text.get())
        window.currency_selection.set('USDT — Tether')
        window._on_currency_selected()
        self.assertIn('60 010.20', window.price_text.get())
        self.assertEqual(window._selected_codes(), ('BTC', 'USDT'))
        self.assertTrue(all(iid.endswith(':USDT') for iid in window.table.rows))
        self.assertNotIn('BTC:USD', window.table.rows)
        self.assertEqual(window.received.history, received_history)
        self.assert_no_network_on_selection(window)

    def test_coin_selection_updates_card_and_table_selection_without_request(self):
        window = self.window()
        window._show_result(self.snapshot(), None)
        received_history = list(window.received.history)
        window.coin_selection.set('ETH — Ethereum')
        window._on_coin_selected()
        self.assertEqual(window._selected_codes(), ('ETH', 'USD'))
        self.assertEqual(window.table.selection(), ('ETH:USD',))
        self.assertIn('3 000.25', window.price_text.get())
        self.assertEqual(window.received.history, received_history)
        self.assert_no_network_on_selection(window)

    def test_table_selection_updates_coin_combobox_and_card_without_request(self):
        window = self.window()
        window._show_result(self.snapshot(), None)
        received_history = list(window.received.history)
        window.table.selection_set('ETH:USD')
        window._on_table_selected()
        self.assertEqual(window.coin_selection.get(), 'ETH — Ethereum')
        self.assertIn('3 000.25', window.price_text.get())
        self.assertEqual(window._selected_codes(), ('ETH', 'USD'))
        self.assertEqual(window.received.history, received_history)
        self.assert_no_network_on_selection(window)

    def test_table_event_for_previous_currency_does_not_change_current_choice(self):
        window = self.window()
        window._show_result(self.snapshot(), None)
        window.table.selection_set('ETH:USDT')
        window._on_table_selected()
        self.assertEqual(window._selected_codes(), ('BTC', 'USD'))
        self.assertIn('60 000.10', window.price_text.get())
        self.assert_no_network_on_selection(window)

    def test_selection_before_first_load_clears_any_old_card_price(self):
        window = self.window()
        window.price_text.set('60 000.10')
        window.coin_selection.set('SOL — Solana')
        window._on_coin_selected()
        window.currency_selection.set('USDT — Tether')
        window._on_currency_selected()
        self.assertEqual(window._selected_codes(), ('SOL', 'USDT'))
        self.assertNotIn('60 000.10', window.price_text.get())
        self.assertIn('SOL', window.pair_title.get())
        self.assertIn('USDT', window.pair_title.get())
        self.assertTrue(all('140.05' not in values for values in window.table.rows.values()))
        self.assertEqual(window.received.history, [])
        self.assert_no_network_on_selection(window)

    def test_missing_pair_offers_alternative_without_substituting_its_price(self):
        window = self.window()
        window._show_result(self.snapshot(), None)
        window.coin_selection.set('GRAM — Gram (Toncoin)')
        window.currency_selection.set('RUB — Российский рубль')
        window._on_coin_selected()
        window._on_currency_selected()
        self.assertEqual(window._selected_codes(), ('GRAM', 'RUB'))
        self.assertNotIn('0.00234878', window.price_text.get())
        self.assertNotIn('0.00234878', window.table.rows['GRAM:RUB'])
        self.assertIn('USD', window.selection_hint.get())
        self.assert_no_network_on_selection(window)

    def test_identity_pair_shows_quote_currency_without_fake_one(self):
        window = self.window()
        window._show_result(self.snapshot(), None)
        window.coin_selection.set('USDT — Tether')
        window.currency_selection.set('USDT — Tether')
        window._on_currency_selected()
        self.assertEqual(window._selected_codes(), ('USDT', 'USDT'))
        self.assertNotIn(window.price_text.get(), ('1', '1.00', '1 USDT', '1.00 USDT'))
        self.assertEqual(window.price_text.get(), 'Валюта совпадает')
        self.assertEqual(window.table.rows['USDT:USDT'][2:5], ('—', '—', '—'))
        self.assert_no_network_on_selection(window)

    def test_failed_refresh_preserves_visible_values_and_receipt(self):
        window = self.window()
        previous = self.snapshot()
        window._show_result(previous, None)
        rows = copy.deepcopy(window.table.rows)
        received_history = list(window.received.history)
        window.busy = True
        window._show_result(None, 'Нет сети')
        self.assertIs(window.snapshot, previous)
        self.assertFalse(window.busy)
        self.assertTrue(window.stale)
        self.assertEqual(window.table.rows, rows)
        self.assertEqual(window.received.history, received_history)
        self.assertIn('устар', window.status.get().lower())
        self.assertIn('устар', window.card_state.get().lower())
        self.assertIn('Нет сети', window.status.get())

    def test_stale_state_survives_selection_and_clears_only_on_success(self):
        window = self.window()
        window._show_result(self.snapshot(), None)
        received_history = list(window.received.history)
        window._show_result(None, 'Нет сети')
        window.coin_selection.set('ETH — Ethereum')
        window._on_coin_selected()
        window.currency_selection.set('USDT — Tether')
        window._on_currency_selected()
        self.assertTrue(window.stale)
        self.assertIn('устар', window.card_state.get().lower())
        self.assertIn('устар', window.status.get().lower())
        self.assertIn('3 001.25', window.price_text.get())
        self.assertEqual(window.received.history, received_history)
        window._show_result(self.snapshot(received_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc)), None)
        self.assertFalse(window.stale)
        self.assertEqual(window.last_error, '')
        self.assertNotIn('устар', window.card_state.get().lower())
        self.assertEqual(window._selected_codes(), ('ETH', 'USDT'))
        self.assert_no_network_on_selection(window)

    def test_initial_failure_does_not_fabricate_prices(self):
        window = self.window()
        window._render_view()
        rows = copy.deepcopy(window.table.rows)
        window._show_result(None, 'Нет сети')
        self.assertIsNone(window.snapshot)
        self.assertEqual(window.table.rows, rows)
        self.assertIn('Данные не получены', window.status.get())
        self.assertEqual(window.received.history, [])
        self.assertNotIn('60 000.10', window.price_text.get())

    def test_missing_pairs_clear_previous_numbers_after_refresh_and_currency_switch(self):
        window = self.window()
        window._show_result(self.snapshot(), None)
        payload = ticker_payload()
        payload['result']['list'] = [
            item for item in payload['result']['list'] if item['symbol'] not in ('BTCUSD', 'BTCUSDT', 'ETHUSDT')
        ]
        snapshot = self.snapshot(payload)
        window._show_result(snapshot, None)
        self.assertNotIn('60 000.10', window.table.rows['BTC:USD'])
        self.assertNotIn('60 000.10', window.price_text.get())
        self.assertIn('Нет данных', ' '.join(window.table.rows['BTC:USD']))
        window.coin_selection.set('ETH — Ethereum')
        window.currency_selection.set('USDT — Tether')
        window._on_currency_selected()
        self.assertNotIn('3 001.25', window.table.rows['ETH:USDT'])
        self.assertNotIn('3 001.25', window.price_text.get())
        self.assertIn('Нет данных', ' '.join(window.table.rows['ETH:USDT']))
        self.assertIs(window.snapshot, snapshot)
        self.assert_no_network_on_selection(window)

    def test_busy_and_rate_limit_prevent_duplicate_requests(self):
        window = self.window()
        # В этом тесте вызываем настоящий refresh, не заглушку выбора валют.
        del window.refresh
        window.busy = True
        window.last_request_started = 100.0
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
                window = self.window()
                window.busy, window.last_request_started = busy, 100.0
                window.auto_refresh.set(enabled)
                with patch.object(gui.time, 'monotonic', return_value=now):
                    window._poll()
                self.assertEqual(window.refresh.call_count, expected_calls)
                window.root.after.assert_called_once_with(100, window._poll)

    def test_close_cancels_timers_and_prevents_further_work(self):
        window = self.window()
        del window.refresh
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

    def test_calculated_card_table_and_chart_explain_fixed_fx(self):
        window = self.window()
        window.currency_selection.set(gui.CURRENCY_LABELS['RUB'])
        window._show_result(Snapshot(parse_quotes(ticker_payload(), example_fx()), TEST_TIME,
                                    fx=example_fx()), None)
        self.assertIn('≈', window.price_text.get())
        self.assertEqual((window.low_text.get(), window.high_text.get()), ('—', '—'))
        self.assertEqual(window.table.rows['BTC:RUB'][3:5], ('—', '—'))
        self.assertIn('FX от', window.selection_hint.get())
        self.assertIn('не учитываются', window.selection_hint.get())
        comparison = gui.ComparisonHistory('BTC', (
            example_history('USD'),
            example_history('EUR', calculated=True, fx_date=example_fx().updated_at),
        ), TEST_TIME)
        window._show_chart_result(window.chart_token, comparison, None)
        self.assertIn('EUR', window.chart_caption.get())
        self.assertIn('FX', window.chart_caption.get())
        self.assertNotIn('RUB', window.chart_title.get())

    def test_direct_metrics_show_pair_units_and_separate_per_asset_turnover(self):
        window = self.window()
        window._show_result(self.metrics_snapshot(), None)
        self.assertEqual(window.change_text.get(), '24 ч: ▼ -1.25%')
        self.assertEqual(window.turnover_text.get(), 'Оборот 24 ч: 1.00 тыс. USD')
        self.assertIn('BTC/USD', window.selection_hint.get())
        window.change_label.configure.assert_called_with(style='ChangeDown.TLabel')
        self.assertEqual(window.table.rows['BTC:USD'][3:5], ('▼ -1.25%', '1.00 тыс.'))
        self.assertEqual(window.table.rows['ETH:USD'][3:5], ('▲ +2.00%', '2.00 тыс.'))
        self.assertIn('trend_down', window.table.tags['BTC:USD'])
        self.assertIn('trend_up', window.table.tags['ETH:USD'])
        self.assertEqual(window.table.headings['turnover']['text'], 'Оборот 24 ч, USD')
        self.assertEqual(window.table.headings['price']['text'], 'Цена, USD')

    def test_metric_selection_moves_between_up_zero_and_identity_without_old_values(self):
        window = self.window()
        window._show_result(self.metrics_snapshot(), None)
        window.coin_selection.set(gui.COIN_LABELS['ETH'])
        window._on_coin_selected()
        self.assertEqual(window.change_text.get(), '24 ч: ▲ +2.00%')
        window.change_label.configure.assert_called_with(style='ChangeUp.TLabel')
        self.assertEqual(window.turnover_text.get(), 'Оборот 24 ч: 2.00 тыс. USD')
        window.currency_selection.set(gui.CURRENCY_LABELS['USDT'])
        window.coin_selection.set(gui.COIN_LABELS['SOL'])
        window._on_currency_selected()
        self.assertEqual(window.change_text.get(), '24 ч: 0.00%')
        window.change_label.configure.assert_called_with(style='ChangeNeutral.TLabel')
        self.assertEqual(window.turnover_text.get(), 'Оборот 24 ч: 3.00 тыс. USDT')
        self.assertIn('trend_neutral', window.table.tags['SOL:USDT'])
        self.assertEqual(window.table.headings['turnover']['text'], 'Оборот 24 ч, USDT')
        window.coin_selection.set(gui.COIN_LABELS['USDT'])
        window._on_coin_selected()
        self.assertEqual(window.change_text.get(), '24 ч: —')
        self.assertEqual(window.turnover_text.get(), 'Оборот 24 ч: —')
        window.change_label.configure.assert_called_with(style='ChangeNeutral.TLabel')
        self.assertEqual(window.table.rows['USDT:USDT'][3:5], ('—', '—'))
        self.assert_no_network_on_selection(window)

    def test_calculated_metrics_use_selected_currency_approximation_and_actual_source_pair(self):
        window = self.window()
        window.currency_selection.set(gui.CURRENCY_LABELS['RUB'])
        window._show_result(self.metrics_snapshot(fx=example_fx()), None)
        self.assertEqual(window.change_text.get(), '24 ч: ≈ ▼ -1.25%')
        self.assertEqual(window.turnover_text.get(), 'Оборот 24 ч: ≈ 100.00 тыс. RUB')
        self.assertEqual(window.table.rows['BTC:RUB'][3:5], ('≈ ▼ -1.25%', '≈ 100.00 тыс.'))
        self.assertIn('BTC/USD', window.selection_hint.get())
        self.assertEqual(window.table.headings['turnover']['text'], 'Оборот 24 ч, RUB')
        window.coin_selection.set(gui.COIN_LABELS['BNB'])
        window._on_coin_selected()
        self.assertEqual(window.change_text.get(), '24 ч: ≈ ▲ +10.33%')
        self.assertEqual(window.turnover_text.get(), 'Оборот 24 ч: ≈ 200.06 тыс. RUB')
        self.assertIn('Оборот BNB/USDT', window.selection_hint.get())
        self.assertIn('текущему курсу', window.selection_hint.get())
        self.assertIn('приблиз', window.selection_hint.get().lower())

    def test_direct_eur_metrics_have_own_values_without_approximation(self):
        window = self.window()
        payload = metrics_payload()
        payload['result']['list'].append({
            'symbol': 'BTCEUR', 'lastPrice': '55000', 'lowPrice24h': '54000',
            'highPrice24h': '56000', 'price24hPcnt': '-0.02', 'turnover24h': '700',
        })
        window.currency_selection.set(gui.CURRENCY_LABELS['EUR'])
        window._show_result(self.metrics_snapshot(payload, example_fx()), None)
        self.assertEqual(window.change_text.get(), '24 ч: ▼ -2.00%')
        self.assertEqual(window.turnover_text.get(), 'Оборот 24 ч: 700.00 EUR')
        self.assertEqual(window.table.rows['BTC:EUR'][3:5], ('▼ -2.00%', '700.00'))
        self.assertIn('BTC/EUR', window.selection_hint.get())
        self.assertNotIn('≈', window.change_text.get() + window.turnover_text.get())

    def test_success_without_optional_metrics_clears_previous_numbers_and_direction(self):
        window = self.window()
        window._show_result(self.metrics_snapshot(), None)
        payload = metrics_payload()
        market(payload, 'BTCUSD').update(price24hPcnt='bad', turnover24h=None)
        window._show_result(self.metrics_snapshot(payload), None)
        self.assertEqual(window.change_text.get(), '24 ч: —')
        self.assertEqual(window.turnover_text.get(), 'Оборот 24 ч: —')
        self.assertEqual(window.table.rows['BTC:USD'][3:5], ('—', '—'))
        self.assertIn('trend_neutral', window.table.tags['BTC:USD'])
        self.assertNotIn('trend_down', window.table.tags['BTC:USD'])
        window.change_label.configure.assert_called_with(style='ChangeNeutral.TLabel')
        self.assertIn('60 000.10', window.price_text.get())
        self.assertFalse(window.stale)

    def test_metric_failure_preserves_last_snapshot_and_switches_to_selected_stale_values(self):
        window = self.window()
        window._show_result(self.metrics_snapshot(), None)
        original = (window.change_text.get(), window.turnover_text.get())
        window._show_result(None, 'Нет сети')
        self.assertEqual((window.change_text.get(), window.turnover_text.get()), original)
        self.assertIn('устар', window.card_state.get().lower())
        window.coin_selection.set(gui.COIN_LABELS['ETH'])
        window._on_coin_selected()
        self.assertEqual(window.change_text.get(), '24 ч: ▲ +2.00%')
        self.assertEqual(window.turnover_text.get(), 'Оборот 24 ч: 2.00 тыс. USD')
        self.assertIn('устар', window.card_state.get().lower())
        self.assertTrue(window.stale)

    def test_initial_failure_and_missing_pair_keep_metrics_empty(self):
        window = self.window()
        window._show_result(None, 'Нет сети')
        self.assertEqual(window.change_text.get(), '24 ч: —')
        self.assertEqual(window.turnover_text.get(), 'Оборот 24 ч: —')
        window._show_result(self.metrics_snapshot(), None)
        window.currency_selection.set(gui.CURRENCY_LABELS['RUB'])
        window._on_currency_selected()
        self.assertEqual(window.change_text.get(), '24 ч: —')
        self.assertEqual(window.turnover_text.get(), 'Оборот 24 ч: —')
        self.assertEqual(window.table.rows['BTC:RUB'][3:5], ('—', '—'))
        window.change_label.configure.assert_called_with(style='ChangeNeutral.TLabel')

    def test_refresh_updates_existing_row_trend_tags_and_keeps_zero_turnover_visible(self):
        window = self.window()
        window._show_result(self.metrics_snapshot(), None)
        payload = metrics_payload()
        market(payload, 'BTCUSD').update(price24hPcnt='0.04', turnover24h='0')
        market(payload, 'ETHUSD')['price24hPcnt'] = '0'
        window._show_result(self.metrics_snapshot(payload), None)
        self.assertEqual(window.table.rows['BTC:USD'][3], '▲ +4.00%')
        self.assertEqual(Decimal(window.table.rows['BTC:USD'][4]), Decimal('0'))
        self.assertIn('trend_up', window.table.tags['BTC:USD'])
        self.assertNotIn('trend_down', window.table.tags['BTC:USD'])
        self.assertEqual(window.table.rows['ETH:USD'][3], '0.00%')
        self.assertIn('trend_neutral', window.table.tags['ETH:USD'])
        self.assertNotIn('trend_up', window.table.tags['ETH:USD'])

    def test_initial_fx_failure_message_does_not_claim_a_cached_date(self):
        window = self.window()
        snapshot = Snapshot(parse_quotes(ticker_payload()), TEST_TIME, fx_error='Нет FX')
        window._show_result(snapshot, None)
        self.assertIn('Курсы FX недоступны', window.status.get())
        self.assertNotIn('дата', window.status.get())
        self.assertIn('60 000.10', window.price_text.get())

    def test_expired_fx_remains_marked_stale_when_currency_changes(self):
        window = self.window()
        fx = gui.parse_fx(fx_payload(TEST_TIME - timedelta(days=2)), TEST_TIME)
        window.currency_selection.set(gui.CURRENCY_LABELS['RUB'])
        window._show_result(Snapshot(parse_quotes(ticker_payload(), fx), TEST_TIME,
                                    fx=fx, fx_error='Нет FX'), None)
        self.assertIn('FX устарел', window.card_state.get())
        comparison = gui.ComparisonHistory('BTC', (
            example_history('USD'),
            gui.replace(example_history('EUR', calculated=True, fx_date=fx.updated_at), fx_stale=True),
        ), TEST_TIME)
        window._show_chart_result(window.chart_token, comparison, None)
        self.assertIn('устар', window.chart_caption.get())
        window.currency_selection.set(gui.CURRENCY_LABELS['UZS'])
        window._on_currency_selected()
        self.assertIn('FX устарел', window.card_state.get())
        self.assertIn('устаревший FX', window.status.get())
        self.assertIn('FX устарел', window.table.rows['BTC:UZS'][-1])

    def test_selection_clears_previous_chart_and_late_response_cannot_replace_it(self):
        window = self.window()
        window._show_result(self.snapshot(received_at=TEST_TIME), None)
        old_token = window.chart_token
        old_series = gui.ComparisonHistory('BTC', (example_history(),), TEST_TIME)
        window.chart_series = old_series
        window.coin_selection.set(gui.COIN_LABELS['ETH'])
        window._on_coin_selected()
        self.assertIsNone(window.chart_series)
        window._show_chart_result(old_token, old_series, None)
        self.assertIsNone(window.chart_series)
        self.assertEqual(window.chart_token, ('ETH', window.snapshot_version))

    def test_currency_selection_preserves_usd_eur_comparison_without_new_history_work(self):
        window = self.window()
        window._show_result(self.snapshot(received_at=TEST_TIME), None)
        comparison = gui.ComparisonHistory('BTC', (example_history(),), TEST_TIME)
        window._show_chart_result(window.chart_token, comparison, None)
        token, pending = window.chart_token, window.chart_pending
        title, caption = window.chart_title.get(), window.chart_caption.get()
        window.root.after.reset_mock()
        for currency in ('EUR', 'RUB', 'USDT'):
            window.currency_selection.set(gui.CURRENCY_LABELS[currency])
            window._on_currency_selected()
            self.assertEqual(window.chart_token, token)
            self.assertIs(window.chart_series, comparison)
            self.assertIs(window.chart_pending, pending)
            self.assertEqual(window.chart_title.get(), title)
            self.assertEqual(window.chart_caption.get(), caption)
        window.root.after.assert_not_called()
        self.assertIn('BTC / USD / EUR', title)

    def test_partial_comparison_keeps_available_line_and_marks_other_legend_unavailable(self):
        window = self.window()
        window._show_result(self.snapshot(received_at=TEST_TIME), None)
        price, rows = window.price_text.get(), copy.deepcopy(window.table.rows)
        comparison = gui.ComparisonHistory('BTC', (example_history(),), TEST_TIME,
                                           (('EUR', 'Нет истории EUR'),))
        window._show_chart_result(window.chart_token, comparison, None)
        self.assertIs(window.chart_series, comparison)
        self.assertEqual(window.chart_message, '')
        self.assertIn('USD', window.chart_legend_usd.get())
        self.assertIn('%', window.chart_legend_usd.get())
        self.assertIn('EUR', window.chart_legend_eur.get())
        self.assertNotIn('%', window.chart_legend_eur.get())
        self.assertIn('EUR', window.chart_caption.get())
        self.assertEqual(window.price_text.get(), price)
        self.assertEqual(window.table.rows, rows)

    def test_chart_rejects_other_pair_and_previous_snapshot_even_with_current_token(self):
        window = self.window()
        window._show_result(self.snapshot(received_at=TEST_TIME), None)
        token = window.chart_token
        for series in (gui.ComparisonHistory('ETH', (example_history(symbol='ETH'),), TEST_TIME),
                       gui.ComparisonHistory('BTC', (example_history(),), TEST_TIME - timedelta(seconds=60))):
            window._show_chart_result(token, series, None)
            self.assertIsNone(window.chart_series)
        window._show_result(self.snapshot(received_at=TEST_TIME + timedelta(seconds=60)), None)
        self.assertNotEqual(window.chart_token, token)
        window._show_chart_result(token, gui.ComparisonHistory('BTC', (example_history(),), TEST_TIME), None)
        self.assertIsNone(window.chart_series)

    def test_single_history_worker_keeps_only_latest_pending_selection(self):
        window = self.window()
        window._show_result(self.snapshot(received_at=TEST_TIME), None)
        with patch.object(gui, 'Thread') as thread:
            window._start_chart_request()
            old_token = window.chart_active_token
            self.assertEqual(thread.call_count, 1)
            window.coin_selection.set(gui.COIN_LABELS['ETH'])
            window._on_coin_selected()
            window._start_chart_request()
            window.coin_selection.set(gui.COIN_LABELS['BNB'])
            window._on_coin_selected()
            window._start_chart_request()
            self.assertEqual(thread.call_count, 1)
            self.assertEqual(window.chart_pending[0], ('BNB', window.snapshot_version))
            window.chart_results.put((old_token, None, 'Ошибка старой истории'))
            window._poll_chart_results()
            self.assertEqual(thread.call_count, 2)
            self.assertEqual(window.chart_active_token, ('BNB', window.snapshot_version))
            self.assertTrue(thread.call_args.kwargs['daemon'])

    def test_history_failure_changes_only_chart_not_quotes_or_receipt(self):
        window = self.window()
        window._show_result(self.snapshot(received_at=TEST_TIME), None)
        rows, price = copy.deepcopy(window.table.rows), window.price_text.get()
        receipt = list(window.received.history)
        window._show_chart_result(window.chart_token, None, 'Неполные данные истории')
        self.assertEqual(window.table.rows, rows)
        self.assertEqual(window.price_text.get(), price)
        self.assertEqual(window.received.history, receipt)
        self.assertIn('недоступ', window.chart_message.lower())
        self.assertFalse(window.stale)

    def test_history_worker_queues_unexpected_error_and_closing_rejects_response(self):
        provider, results = Mock(), Queue()
        provider.fetch_history.side_effect = RuntimeError('private detail')
        token = ('BTC', 1)
        gui.fetch_history_in_worker(provider, by_id()['BTC:USD'], TEST_TIME, results, token)
        result_token, series, error = results.get_nowait()
        self.assertEqual(result_token, token)
        self.assertIsNone(series)
        self.assertNotIn('private detail', error)
        window = self.window()
        window.start_id = window.timer_id = None
        window.chart_debounce_id = 'chart_timer'
        window.close()
        window.root.after_cancel.assert_called_once_with('chart_timer')
        window._show_chart_result(token, gui.HistorySeries(('BTC', 'USD'), (), TEST_TIME), None)
        with patch.object(gui, 'Thread') as thread:
            window._schedule_chart()
            window._start_chart_request()
            thread.assert_not_called()
        self.assertIsNone(window.chart_series)


if __name__ == '__main__':
    unittest.main()
