"""Публичные спотовые цены Bybit с раздельными валютами котировки USD и USDT."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import requests


@dataclass(frozen=True)
class Coin:
    symbol: str
    name: str


COINS = (
    Coin('BTC', 'Bitcoin'),
    Coin('ETH', 'Ethereum'),
    Coin('USDT', 'Tether'),
    Coin('GRAM', 'Gram (Toncoin)'),
    Coin('BNB', 'BNB'),
    Coin('SOL', 'Solana'),
    Coin('XRP', 'XRP'),
    Coin('DOGE', 'Dogecoin'),
)
QUOTE_CURRENCIES = ('USD', 'USDT')


@dataclass(frozen=True)
class Quote:
    symbol: str
    name: str
    currency: str
    price: Decimal | None = None
    low_24h: Decimal | None = None
    high_24h: Decimal | None = None
    status: str = 'available'

    @property
    def row_id(self):
        return f'{self.symbol}:{self.currency}'


@dataclass(frozen=True)
class Snapshot:
    quotes: tuple[Quote, ...]
    received_at: datetime
    source: str = 'Bybit'


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
    """Нормализуем только точные пары; отсутствующие пары не пересчитываем."""
    if not isinstance(data, dict) or type(data.get('retCode')) is not int:
        raise QuoteError('Сервис вернул неверный формат данных.')
    if data['retCode'] != 0:
        if data['retCode'] in (10006, 10018):
            raise QuoteError('Слишком много запросов. Повторите попытку позднее.')
        raise QuoteError('Bybit сообщил об ошибке. Повторите попытку позднее.')
    result = data.get('result')
    if not isinstance(result, dict) or result.get('category') != 'spot':
        raise QuoteError('Сервис вернул неверный формат спотовых котировок.')
    items = result.get('list')
    if not isinstance(items, list) or not items:
        raise QuoteError('Сервис вернул пустой или неверный список котировок.')

    allowed_pairs = {
        coin.symbol + currency
        for currency in QUOTE_CURRENCIES
        for coin in COINS
        if coin.symbol != currency
    }
    prices = {}
    for item in items:
        if not isinstance(item, dict):
            raise QuoteError('Сервис вернул неверную запись котировки.')
        symbol = item.get('symbol')
        if not isinstance(symbol, str) or not symbol:
            raise QuoteError('Сервис не указал символ торговой пары.')
        # Например, BTCUSDT и BTCUSD — разные рынки. Совпадения по суффиксу нет.
        if symbol not in allowed_pairs:
            continue
        if symbol in prices:
            raise QuoteError(f'Сервис вернул повторяющиеся данные пары {symbol}.')
        try:
            price = positive_decimal(item['lastPrice'])
            low = positive_decimal(item['lowPrice24h'])
            high = positive_decimal(item['highPrice24h'])
        except KeyError:
            raise QuoteError(f'Некорректные данные пары {symbol}.') from None
        if low > high:
            raise QuoteError(f'Некорректный диапазон цен пары {symbol}.')
        prices[symbol] = (price, low, high)

    if not prices:
        raise QuoteError('В ответе сервиса нет данных выбранных торговых пар.')

    quotes = []
    for currency in QUOTE_CURRENCIES:
        for coin in COINS:
            pair = coin.symbol + currency
            if coin.symbol == currency:
                # USDT/USDT не является рыночным курсом и не показывается как 1.
                quote = Quote(coin.symbol, coin.name, currency, status='quote_currency')
            elif pair not in prices:
                quote = Quote(coin.symbol, coin.name, currency, status='missing')
            else:
                quote = Quote(coin.symbol, coin.name, currency, *prices[pair])
            quotes.append(quote)
    return tuple(quotes)


class BybitClient:
    """Адаптер источника: другой API может реализовать тот же fetch_quotes()."""

    url = 'https://api.bybit.com/v5/market/tickers'

    def fetch_quotes(self):
        try:
            response = requests.get(
                self.url,
                params={'category': 'spot'},
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
