"""Получение публичных цен Kraken и преобразование JSON в данные приложения."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import requests


@dataclass(frozen=True)
class Coin:
    symbol: str
    name: str
    pair: str
    response_key: str


COINS = (
    Coin('BTC', 'Bitcoin', 'XBTUSD', 'XXBTZUSD'),
    Coin('ETH', 'Ethereum', 'ETHUSD', 'XETHZUSD'),
    Coin('SOL', 'Solana', 'SOLUSD', 'SOLUSD'),
    Coin('XRP', 'XRP', 'XRPUSD', 'XXRPZUSD'),
    Coin('DOGE', 'Dogecoin', 'DOGEUSD', 'XDGUSD'),
)


@dataclass(frozen=True)
class Quote:
    symbol: str
    name: str
    price: Decimal
    low_24h: Decimal
    high_24h: Decimal


@dataclass(frozen=True)
class Snapshot:
    quotes: tuple[Quote, ...]
    received_at: datetime
    source: str = 'Kraken'


class QuoteError(Exception):
    """Понятная пользователю ошибка получения котировок."""


def positive_decimal(value):
    """Не пропускаем пустые, бесконечные, нулевые и отрицательные цены."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise QuoteError('Сервис вернул некорректную цену.') from None
    if not number.is_finite() or number <= 0:
        raise QuoteError('Сервис вернул некорректную цену.')
    return number


def parse_quotes(data):
    """Названия полей Kraken остаются внутри адаптера, вне интерфейса."""
    if not isinstance(data, dict) or not isinstance(data.get('error'), list):
        raise QuoteError('Сервис вернул неверный формат данных.')
    if data['error']:
        if any('Rate limit' in str(error) for error in data['error']):
            raise QuoteError('Слишком много запросов. Повторите попытку позднее.')
        raise QuoteError('Kraken сообщил об ошибке. Повторите попытку позднее.')
    result = data.get('result')
    if not isinstance(result, dict):
        raise QuoteError('В ответе сервиса отсутствуют котировки.')

    quotes = []
    for coin in COINS:
        item = result.get(coin.response_key)
        if not isinstance(item, dict):
            raise QuoteError(f'В ответе сервиса отсутствует курс {coin.symbol}.')
        try:
            # c[0] — последняя сделка; l[1] и h[1] — минимум/максимум за 24 ч.
            fields = (item['c'], item['l'], item['h'])
            if any(not isinstance(field, list) for field in fields):
                raise TypeError
            price = positive_decimal(item['c'][0])
            low = positive_decimal(item['l'][1])
            high = positive_decimal(item['h'][1])
        except (KeyError, IndexError, TypeError):
            raise QuoteError(f'Некорректные данные для {coin.symbol}.') from None
        if low > high:
            raise QuoteError(f'Некорректный диапазон цен для {coin.symbol}.')
        quotes.append(Quote(coin.symbol, coin.name, price, low, high))
    return tuple(quotes)


class KrakenClient:
    """Адаптер источника: другой API может реализовать тот же fetch_quotes()."""

    url = 'https://api.kraken.com/0/public/Ticker'

    def fetch_quotes(self):
        try:
            response = requests.get(
                self.url,
                params={'pair': ','.join(coin.pair for coin in COINS)},
                headers={'Accept': 'application/json'},
                timeout=(5, 10),
            )
            response.raise_for_status()
        except requests.Timeout:
            raise QuoteError('Сервис не ответил вовремя. Повторите попытку.') from None
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 429:
                raise QuoteError('Слишком много запросов. Повторите попытку позднее.') from None
            raise QuoteError('Сервис временно недоступен. Повторите попытку позднее.') from None
        except requests.RequestException:
            raise QuoteError('Не удалось подключиться. Проверьте интернет.') from None

        try:
            data = response.json()
        except ValueError:
            raise QuoteError('Сервис вернул некорректный JSON.') from None
        quotes = parse_quotes(data)
        # Это время получения ответа, а не время последней сделки на бирже.
        return Snapshot(quotes, datetime.now(timezone.utc))
