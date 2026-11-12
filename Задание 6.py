"""Задание 6. Прямые котировки Bybit отдельно к USD и USDT.

Запуск: python "Задание 6.py"
Зависимость: python -m pip install requests
Для запуска достаточно этого файла; иконка встроена в код.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from queue import Empty, Queue
from tempfile import TemporaryDirectory
from threading import Thread
import base64
import time
import tkinter as tk
from tkinter import ttk

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


AUTO_REFRESH_SECONDS = 60
MIN_REQUEST_INTERVAL = 5
MOSCOW_TIME = timezone(timedelta(hours=3))
COIN_LABELS = {coin.symbol: f'{coin.symbol} — {coin.name}' for coin in COINS}
CURRENCY_LABELS = {'USD': 'USD — доллар США', 'USDT': 'USDT — Tether'}


def format_price(value: Decimal):
    """До 10 единиц валюты сохраняем шесть значащих цифр, включая USDT/USD."""
    if value >= 10:
        return f'{value:,.2f}'.replace(',', ' ')
    return format(value, '.6g')


def fetch_in_worker(provider, results):
    """Поток работает только с сетью и очередью, не обращается к Tkinter."""
    try:
        results.put((provider.fetch_quotes(), None))
    except QuoteError as error:
        results.put((None, str(error)))
    except Exception:
        # Даже неожиданная ошибка должна снять состояние «Загрузка» в GUI.
        results.put((None, 'Не удалось обработать ответ сервиса. Повторите попытку.'))


class CryptoApp:
    def __init__(self, root, provider=None):
        self.root = root
        self.provider = provider if provider is not None else BybitClient()
        self.results = Queue()
        self.busy = False
        self.closed = False
        self.last_request_started = None
        self.snapshot = None
        self.stale = False
        self.last_error = ''
        self.displayed_currency = None
        self.timer_id = None
        self.start_id = None

        self.auto_refresh = tk.BooleanVar(value=False)
        self.coin_selection = tk.StringVar(value=COIN_LABELS['BTC'])
        self.currency_selection = tk.StringVar(value=CURRENCY_LABELS['USD'])
        self.status = tk.StringVar(value='Ожидание первого запроса…')
        self.received = tk.StringVar(value='Данные ещё не получены')
        self.source = tk.StringVar(value='Источник: Bybit  •  Прямые спотовые пары')
        self.price_note = tk.StringVar(
            value='Прямые спотовые пары Bybit. USD и USDT не приравниваются друг к другу.'
        )
        self.pair_title = tk.StringVar()
        self.price_text = tk.StringVar()
        self.low_text = tk.StringVar(value='—')
        self.high_text = tk.StringVar(value='—')
        self.selection_hint = tk.StringVar()
        self.card_state = tk.StringVar(value='Ожидание данных')
        self.market_title = tk.StringVar()
        self.root.title('Задание 6 — Курсы криптовалют')
        set_window_icon(self.root)
        self.root.geometry('1000x760')
        self.root.minsize(920, 700)
        self.root.configure(background='#F3F6FA')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self._build_interface()
        self._render_view()
        self.start_id = self.root.after(100, self.refresh)
        self.timer_id = self.root.after(100, self._poll)

    def _build_interface(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background='#F3F6FA', foreground='#172F49')
        style.configure('App.TFrame', background='#F3F6FA')
        style.configure('Title.TLabel', font=('Segoe UI', 23, 'bold'), foreground='#132C46')
        style.configure('Note.TLabel', foreground='#617286', font=('Segoe UI', 9))
        style.configure('Field.TLabel', foreground='#425971', font=('Segoe UI', 9, 'bold'))
        style.configure('Section.TLabel', font=('Segoe UI', 12, 'bold'))
        style.configure('Accent.TButton', background='#087F8C', foreground='white',
                        font=('Segoe UI', 10, 'bold'), padding=(18, 8))
        style.map('Accent.TButton', background=[('active', '#096D78'), ('disabled', '#B9CAD0')],
                  foreground=[('disabled', '#F5FAFC')])
        style.configure('TCombobox', padding=7, fieldbackground='white')
        style.map('TCombobox', fieldbackground=[('readonly', 'white')],
                  foreground=[('readonly', '#172F49')])
        style.configure('Card.TFrame', background='white')
        style.configure('CardNote.TLabel', background='white', foreground='#60748A', font=('Segoe UI', 9))
        style.configure('Pair.TLabel', background='white', foreground='#416076', font=('Segoe UI', 11, 'bold'))
        style.configure('Price.TLabel', background='white', foreground='#132C46', font=('Segoe UI', 27, 'bold'))
        style.configure('Metric.TLabel', background='white', foreground='#172F49', font=('Segoe UI', 15, 'bold'))
        style.configure('CardState.TLabel', background='white', foreground='#087F8C', font=('Segoe UI', 9, 'bold'))
        style.configure('CardWarning.TLabel', background='white', foreground='#9A5A16', font=('Segoe UI', 9, 'bold'))
        style.configure('Status.TLabel', foreground='#36566F', font=('Segoe UI', 9))
        style.configure('Warning.TLabel', foreground='#9A5A16', font=('Segoe UI', 9))
        style.configure('Treeview', rowheight=29, background='white', fieldbackground='white',
                        foreground='#233E55', font=('Segoe UI', 10), borderwidth=0)
        style.configure('Treeview.Heading', background='#E7EEF5', foreground='#34516B',
                        font=('Segoe UI', 9, 'bold'), padding=(8, 7))
        style.map('Treeview', background=[('selected', '#D9ECEF')], foreground=[('selected', '#123E49')])

        frame = ttk.Frame(self.root, style='App.TFrame', padding=(24, 18))
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)
        header = ttk.Frame(frame, style='App.TFrame')
        header.grid(row=0, column=0, sticky='ew', pady=(0, 15))
        ttk.Label(header, text='Курсы криптовалют', style='Title.TLabel').pack(anchor='w')
        ttk.Label(header, textvariable=self.source, style='Note.TLabel').pack(anchor='w', pady=(2, 0))

        controls = ttk.Frame(frame, style='App.TFrame')
        controls.grid(row=1, column=0, sticky='ew', pady=(0, 16))
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text='Криптовалюта', style='Field.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 5))
        ttk.Label(controls, text='Валюта котировки', style='Field.TLabel').grid(row=0, column=1, sticky='w', padx=(16, 0), pady=(0, 5))
        self.coin_combobox = ttk.Combobox(
            controls, textvariable=self.coin_selection, values=list(COIN_LABELS.values()),
            state='readonly', width=27, takefocus=True,
        )
        self.coin_combobox.grid(row=1, column=0, sticky='ew')
        self.currency_combobox = ttk.Combobox(
            controls, textvariable=self.currency_selection, values=list(CURRENCY_LABELS.values()),
            state='readonly', width=26, takefocus=True,
        )
        self.currency_combobox.grid(row=1, column=1, sticky='ew', padx=(16, 16))
        self.refresh_button = ttk.Button(controls, text='Обновить', style='Accent.TButton', command=self.refresh)
        self.refresh_button.grid(row=1, column=2, sticky='e')
        ttk.Checkbutton(
            controls, text='Обновлять каждые 60 секунд', variable=self.auto_refresh,
        ).grid(row=2, column=0, columnspan=2, sticky='w', pady=(8, 0))
        ttk.Label(controls, text='Ctrl+R — обновить', style='Note.TLabel').grid(row=2, column=2, sticky='e', pady=(8, 0))
        self.coin_combobox.bind('<<ComboboxSelected>>', self._on_coin_selected)
        self.currency_combobox.bind('<<ComboboxSelected>>', self._on_currency_selected)
        self.root.bind('<Control-r>', lambda event: self.refresh())

        card_border = tk.Frame(frame, background='#DDE6EE', padx=1, pady=1)
        card_border.grid(row=2, column=0, sticky='ew')
        card = ttk.Frame(card_border, style='Card.TFrame', padding=(20, 14))
        card.pack(fill='both', expand=True)
        card.columnconfigure(0, weight=1)
        ttk.Label(card, textvariable=self.pair_title, style='Pair.TLabel').grid(row=0, column=0, sticky='w')
        self.state_label = ttk.Label(card, textvariable=self.card_state, style='CardState.TLabel')
        self.state_label.grid(row=0, column=1, columnspan=2, sticky='e')
        self.price_label = ttk.Label(card, textvariable=self.price_text, style='Price.TLabel')
        self.price_label.grid(row=1, column=0, sticky='w', pady=(7, 3), padx=(0, 14))
        for column, title, variable in (
            (1, 'Минимум за 24 ч', self.low_text), (2, 'Максимум за 24 ч', self.high_text),
        ):
            metric = ttk.Frame(card, style='Card.TFrame', padding=(10, 0))
            metric.grid(row=1, column=column, sticky='e')
            ttk.Label(metric, text=title, style='CardNote.TLabel').pack(anchor='e')
            ttk.Label(metric, textvariable=variable, style='Metric.TLabel').pack(anchor='e', pady=(4, 0))
        self.hint_label = ttk.Label(card, textvariable=self.selection_hint, style='CardNote.TLabel', wraplength=820)
        self.hint_label.grid(row=2, column=0, columnspan=3, sticky='w', pady=(4, 0))

        table_header = ttk.Frame(frame, style='App.TFrame')
        table_header.grid(row=3, column=0, sticky='ew', pady=(17, 8))
        ttk.Label(table_header, textvariable=self.market_title, style='Section.TLabel').pack(side='left')
        ttk.Label(table_header, text='Выберите строку для просмотра пары', style='Note.TLabel').pack(side='right')
        table_frame = ttk.Frame(frame, style='App.TFrame')
        table_frame.grid(row=4, column=0, sticky='nsew')
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        columns = ('name', 'symbol', 'price', 'low', 'high', 'availability')
        self.table = ttk.Treeview(table_frame, columns=columns, show='headings', height=8,
                                  selectmode='browse', takefocus=True)
        for column, title, width, minimum, anchor in (
            ('name', 'Криптовалюта', 174, 160, 'w'),
            ('symbol', 'Тикер', 70, 60, 'center'),
            ('price', 'Цена, USD', 140, 108, 'e'),
            ('low', 'Мин. 24 ч, USD', 140, 115, 'e'),
            ('high', 'Макс. 24 ч, USD', 140, 115, 'e'),
            ('availability', 'Доступность', 166, 150, 'w'),
        ):
            self.table.heading(column, text=title, anchor=anchor)
            self.table.column(column, width=width, minwidth=minimum, anchor=anchor)
        self.table.tag_configure('stripe', background='#F4F8FB')
        self.table.grid(row=0, column=0, sticky='nsew')
        self.scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        self.scrollbar.grid(row=0, column=1, sticky='ns')
        self.table.configure(yscrollcommand=self.scrollbar.set)
        self.table.bind('<<TreeviewSelect>>', self._on_table_selected)

        footer = ttk.Frame(frame, style='App.TFrame')
        footer.grid(row=5, column=0, sticky='ew', pady=(11, 0))
        self.status_label = ttk.Label(footer, textvariable=self.status, style='Status.TLabel', wraplength=850)
        self.status_label.pack(anchor='w')
        ttk.Label(footer, textvariable=self.received, style='Note.TLabel').pack(anchor='w', pady=(3, 0))
        ttk.Label(footer, textvariable=self.price_note, style='Note.TLabel', wraplength=850).pack(anchor='w', pady=(3, 0))
        self.coin_combobox.focus_set()

    def _selected_codes(self):
        return (self.coin_selection.get().split(' — ', 1)[0],
                self.currency_selection.get().split(' — ', 1)[0])

    def _quote_for(self, symbol, currency):
        if self.snapshot is None:
            return None
        return next((quote for quote in self.snapshot.quotes
                     if quote.symbol == symbol and quote.currency == currency), None)

    def _render_card(self):
        symbol, currency = self._selected_codes()
        coin = next(coin for coin in COINS if coin.symbol == symbol)
        quote = self._quote_for(symbol, currency)
        self.pair_title.set(f'{coin.name}  ·  {symbol} / {currency}')
        self.low_text.set('—')
        self.high_text.set('—')
        if symbol == currency:
            self.price_text.set('Валюта котировки')
            self.selection_hint.set(f'{symbol} выбран как валюта котировки. Рыночная цена пары {symbol}/{currency} не выводится.')
        elif quote is not None and quote.status == 'available':
            self.price_text.set(f'1 {symbol} = {format_price(quote.price)} {currency}')
            self.low_text.set(f'{format_price(quote.low_24h)} {currency}')
            self.high_text.set(f'{format_price(quote.high_24h)} {currency}')
            self.selection_hint.set('Цена последней сделки и диапазон за 24 часа. Время получения указано ниже.')
        elif self.snapshot is None:
            self.price_text.set(f'1 {symbol} = — {currency}')
            self.selection_hint.set('Котировка появится после получения данных от биржи.')
        else:
            self.price_text.set('Нет данных по паре')
            alternative = next((unit for unit in QUOTE_CURRENCIES if unit != currency
                                and (other := self._quote_for(symbol, unit)) is not None
                                and other.status == 'available'), None)
            if alternative:
                self.selection_hint.set(f'В полученном ответе есть пара {symbol}/{alternative}. Выберите {alternative} в поле валюты котировки; пересчёт не выполняется.')
            else:
                self.selection_hint.set('В полученном ответе нет прямой котировки этой пары. Пересчёт через другую валюту не выполняется.')
        if self.stale and self.snapshot is not None:
            self.card_state.set('Данные устарели')
        elif self.busy:
            self.card_state.set('Обновление · прежние данные' if self.snapshot is not None else 'Загрузка…')
        elif self.last_error:
            self.card_state.set('Данные не получены')
        else:
            self.card_state.set('Получено от биржи' if self.snapshot is not None else 'Ожидание данных')
        self.state_label.configure(style='CardWarning.TLabel' if self.stale or self.last_error else 'CardState.TLabel')

    def _select_table_row(self):
        symbol, currency = self._selected_codes()
        row_id = f'{symbol}:{currency}'
        if row_id in self.table.get_children():
            if self.table.selection() != (row_id,):
                self.table.selection_set(row_id)
            self.table.focus(row_id)
            self.table.see(row_id)

    def _render_table(self):
        _, currency = self._selected_codes()
        if self.displayed_currency != currency:
            children = self.table.get_children()
            if children:
                self.table.delete(*children)
            self.displayed_currency = currency
        for column, label in (('price', 'Цена'), ('low', 'Мин. 24 ч'), ('high', 'Макс. 24 ч')):
            self.table.heading(column, text=f'{label}, {currency}')
        for index, coin in enumerate(COINS):
            quote = self._quote_for(coin.symbol, currency)
            price = low = high = '—'
            if coin.symbol == currency:
                availability = 'Валюта котировки'
            elif quote is not None and quote.status == 'available':
                price, low, high = (format_price(quote.price), format_price(quote.low_24h), format_price(quote.high_24h))
                availability = 'Есть котировка'
            else:
                availability = 'Ожидание' if self.snapshot is None else 'Нет данных'
            values = (coin.name, coin.symbol, price, low, high, availability)
            row_id = f'{coin.symbol}:{currency}'
            if row_id in self.table.get_children():
                self.table.item(row_id, values=values)
            else:
                self.table.insert('', 'end', iid=row_id, values=values,
                                  tags=('stripe',) if index % 2 == 0 else ())
        self.market_title.set(f'Все криптовалюты · {currency}')
        self._select_table_row()

    def _update_status(self):
        if self.busy:
            if self.stale:
                message = 'Обновление… пока показаны устаревшие данные.'
            elif self.snapshot is not None:
                message = 'Обновление… пока показаны данные предыдущего получения.'
            else:
                message = 'Получаем котировки от биржи…'
        elif self.last_error:
            prefix = 'Обновление не выполнено; данные устарели.' if self.snapshot is not None else 'Данные не получены.'
            message = f'{prefix} {self.last_error}'
        elif self.snapshot is not None:
            _, currency = self._selected_codes()
            available = sum(quote.status == 'available' and quote.currency == currency
                            for quote in self.snapshot.quotes)
            message = f'Доступно прямых котировок к {currency}: {available}.'
        else:
            message = 'Ожидание первого запроса…'
        self.status.set(message)
        self.status_label.configure(style='Warning.TLabel' if self.stale or self.last_error else 'Status.TLabel')

    def _render_view(self):
        self._render_table()
        self._render_card()
        self._update_status()

    def _on_coin_selected(self, event=None):
        self._render_card()
        self._select_table_row()
        self._update_status()

    def _on_currency_selected(self, event=None):
        self._render_view()

    def _on_table_selected(self, event=None):
        selection = self.table.selection()
        if not selection:
            return
        symbol, currency = selection[0].split(':', 1)
        _, selected_currency = self._selected_codes()
        if currency != selected_currency or symbol not in COIN_LABELS:
            return
        if self.coin_selection.get() != COIN_LABELS[symbol]:
            self.coin_selection.set(COIN_LABELS[symbol])
            self._render_card()
            self._update_status()

    def refresh(self):
        if self.closed or self.busy:
            return
        now = time.monotonic()
        if self.last_request_started is not None:
            if now - self.last_request_started < MIN_REQUEST_INTERVAL:
                return
        self.busy = True
        self.last_request_started = now
        self.refresh_button.configure(state='disabled')
        self._update_status()
        self._render_card()
        Thread(
            target=fetch_in_worker, args=(self.provider, self.results), daemon=True,
        ).start()

    def _show_result(self, snapshot, error):
        self.busy = False
        if error:
            self.last_error = error
            self.stale = self.snapshot is not None
            self._render_card()
            self._update_status()
            return

        self.snapshot = snapshot
        self.stale = False
        self.last_error = ''
        self.source.set(f'Источник: {snapshot.source}  •  Прямые спотовые пары')
        self.price_note.set(
            f'Прямые спотовые пары {snapshot.source}. USD и USDT не приравниваются друг к другу.'
        )
        received = snapshot.received_at.astimezone(MOSCOW_TIME).strftime('%d.%m.%Y %H:%M:%S')
        self.received.set(f'Данные получены: {received} МСК')
        self._render_view()

    def _poll(self):
        if self.closed:
            return
        try:
            snapshot, error = self.results.get_nowait()
        except Empty:
            pass
        else:
            self._show_result(snapshot, error)

        now = time.monotonic()
        elapsed = None if self.last_request_started is None else now - self.last_request_started
        if not self.busy and (elapsed is None or elapsed >= MIN_REQUEST_INTERVAL):
            self.refresh_button.configure(state='normal')
        if self.auto_refresh.get() and not self.busy and elapsed is not None:
            if elapsed >= AUTO_REFRESH_SECONDS:
                self.refresh()
        self.timer_id = self.root.after(100, self._poll)

    def close(self):
        self.closed = True
        for timer_id in (self.start_id, self.timer_id):
            if timer_id is not None:
                self.root.after_cancel(timer_id)
        self.root.destroy()


# Исходная иконка ICO встроена без изменения байтов; внешний assets/crypto.ico не нужен.
WINDOW_ICON_BASE64 = """
AAABAAEAICAAAAEAIACoEAAAFgAAACgAAAAgAAAAQAAAAAEAIAAAAAAAABAAAMMOAADDDgAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
/nWjAP6AkwD+eZ0G/nuaEf5+lRL+gZES/oSMEv6GhxL+iYQP/oqCAf6KggAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAD+ol0A/qFeAf6kWgn+pVgR/qdVD/6pUwT+qVMA/qNZAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP53oQD+dqIH
/nifVP55nZL+fJmW/n+Ulf6Bj5X+hIuV/oeGl/6Jg3z+i4EN/oqBAAAAAAAAAAAAAAAAAAAAAAD+oF8A/qBgBv6h
Xjr+o1x3/qRakP6mV5T+qFSW/qpQjv6tTV/+r0oX/qxNAP6vSQAAAAAAAAAAAAAAAAD+d6EA/naiA/53oHL+eJ+K
/nqcLP58lxL+f5MR/oKOEf6FihH+iIUR/oqCDv6LgAH+i4EAAAAAAAAAAAD+nWQA/qBgAP6gYB7+oV+C/qFeg/6j
XEb+plcz/qhTNP6qUTL+q085/q1Mbv6wSJz+skVJ/rVAAv6zQwAAAAAAAAAAAP54nwD+eJ84/nielf55ng3+eZ4A
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/p5jAP6gYAD+oGAl/qBgmv6hX1P+pVg+/qdWg/6o
VJL+qlGL/qxOkP6uSo/+sEdY/rFFNf6zQ5n+tEFc/r4yAf61PwAAAAAA/nqbAP56nG3+eptY/nqbAP5/kwAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD+oGAA/qBgD/6gYJj+oV9P/qVYYf6mV5v+p1ZB/qhUD/6p
UwT+q08H/q9JKf6xRYD+s0ON/rRBL/62P57+tz09/rc9AP63PQD+fpYA/n2Xev59l0X+fZcAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/qFfAP6hXgD+oV9h/qFef/6lWE3+pViX/qZXFf6sTj/+rE1y/q9KeP6x
Rjj+skQK/rFGA/60QWr+tj+C/rg8Qf64O5b+ujgJ/ro5AP6AkQD+f5N6/oCSRP6AkgAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAD+ol0A/qJdC/6iXZv+o1s7/qZXlv6mVi3+qVMA/qxNff6uS8L+r0iP/rFFlP6z
Q4X+tEEK/rY/CP63PJH+uDs//ro4iv67Nzb+uzcA/oOMAP6Cjnr+g41F/oONAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAP6jWwD+o1sn/qRblv6nVj7+p1WG/qhUAv6vSgD+r0lF/q9IeP6vSQD+skQF/rVAkv61
QDH+uDwA/rk6UP66OW7+vDVd/rw1YP68NQD+hogA/oWJev6GiUT+hokAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAA/qVYAP6lWDr+pViD/qlSUv6pUmv+qVIA/rFGAP6xRl/+skWa/rRCOv61P07+tj+d/rY+Hf65
OgD+uzcu/rs3hv69M0r+vjNy/r0zAP6GiCT+iIWR/omDZf6OfBX+ioIA/o57AAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAD+p1UA/qdVO/6nVYD+q09U/qtPb/6rTwD9p1UB/rJFe/6zQ73+tEF8/rY/tP63PXX+tj4A/rw1AP68
NTH+vDSJ/r8xSv6/MW/+vzEA/oeGwP6Jg6z+jH7A/o58cv6NfQD+j3sAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAP6pUgD+qVIm/qpRj/6tTT3+rkuM/rFGA/60QgD+tEJG/rRBef62PgD+uDtK/rg7gv63PAD+vTMA/r4zVv6+
M3H+vzBe/r8wV/6/MAD+ioJn/ox/kv6Pep3+j3op/o96AP+XcQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
/qtQAP6rUAr+rE2T/q1LNf6wR5T+sUYv/rFGAP61QID+tj/G/rg8mf65OqH+uTpA/ro4AP6+Mgr+vjKT/r4xPf7A
L4b+wC8s/sAvAP6Mfw7+j3qj/pB5b/6PewD+kHgAAAAAAP6gYAD+n2EB/qJeCP6jWwz+pVkG/qZZAP6lWQD+rU0A
/q9JAP6uSln+sEh3/rJFRP6zQ5L+tUEX/rY/Nv63PWT+uDtq/rk6Iv60PwD+vjIE/r4xa/6/MXf+wC5C/sAuiP7B
LgX+wC4A/pF3AP6ReBX+kXcM/pF3AP6fYQD+nmMR/p9hUf6gX4P+ol2P/qRakP6mV4/+qFN3/qtQOP6tTQX+r0kA
/rBIDf6yRZD+s0NO/rRBU/62P5f+uDxJ/ro4Ff68NQj+vTQO/r4yMv6+MYP+vzF+/sAvLf7BLZr+wS0y/sEtAP7C
LAAAAAAAAAAAAP6cZgD/jHwA/p1kPf6eY5r+n2F+/qJeVf6kWlL+plZU/qhUUv6pUl/+rE6P/q5Kg/6wRxz+skUA
/rNDIf60QZj+tj5X/rc9Nv64O33+ujiY/rs2l/69NJn+vjKN/r4xT/7ALjv+wS2e/sEtUv7ALwD+wS0AAAAAAAAA
AAD+nGYA/p5iAP6dZUr+nmSf/qBhVv6jXHv+pFqU/qVYgf6nVXf+qlGI/qxNk/6uSmT+sEhj/rJFmf6zQyL+tEEA
/rY/HP63PYP+uTqL/rs3Tf68Njb+vTQ4/r4yOf6/MEj+wC+A/sEuof7BLUT+wSwB/sEtAAAAAAAAAAAA/ZppAP6e
ZAD+nWQs/p5kn/6gYFf+ol2f/qNcXv6jWw7+q1AG/qtPGf6oVQL+rUwj/rBIhP6yRYb+s0Nd/rRBkv62Pw3+tj4A
/rg7Bv66OTn+uzd5/r00kv6+MpX+vzGV/sAviP7ALlX+wS4T/sAvAP7FJgD+xSYM/sUmFf7FJwD+nmMA/p5jBP6e
Yof+n2Ff/qJdm/6iXEL+qVIH/qlSOv6rT2D+rE6j/q9JQ/6wRxL+sUYF/rNDef60QXT+tj5+/rc9W/62PgD+uDsA
/r0zAP68MwD+vTMG/r4xDP6/MAj+wC4B/sAvAAAAAAD+xSYA/sYlAP7FJm7+xiWk/sYlDv6fYQD+n2Er/qBhjv6j
XGn+o1tz/qVYAP6oUw/+qVJr/qxOkf6uS8P+sEiQ/rFFgPvJJgD+tUAS/rY/mP63PFL+uDuT/ro5Cf65OQAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/8YiAP7GJQD+xiUo/sYlnf7GJZP+xyRo/qFfAP6hX1j+oV5r/qRZiv6k
WSv+pFkAAAAAAP6vSQD+r0ko/rBIi/6yRCj+s0OR/rNCBv64PAD+uDxm/rg7ZP66OI/+uzck/rs3AAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAD+xiQA/sYlAP7GJXH+xiW//sckq/7HJMH+o1wA/qNccf6jW1r+pleR/qZWEf6n
VQD+rkwB/q9JMf6xRnH+skWy/rRCdf60QY3+tUAD/rk6AP65OUP+ujl4/rw2g/68NTj+vDUAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAP7GJAD+xiUA/sYlFP7HJGT+xySR/sckJv6lWAD+pVl0/qVYWf6oVJX+qVMS/q1MAP6w
SB/+sEii/rFFhf6zQ77+tEJq/rVAJ/60QQD+uzcA/rs3RP67N3z+vTOD/r0zOv69MwAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAD+xyMA/scjQ/7HI3n+xyMA/qdVAP6nVmP+p1Vk/qpQkf6rTyr+rkoA/rFGLf6x
Ron+tEIq/rRBj/61QAT+tUAA/rw1AP68NQD+vDVm/rw1av6+Mo/+vjEo/r4xAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAP7IIwD+yCND/sgjef7HIwD+qVMA/qlTOP6qUYn+rE1q/q5LbP6uSgD+skQe/rNDov61
QIr+tj/A/rg8c/65Okb+vjUA/r00Df69NJX+vjJR/r8xlf6/MAv+vzEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAA/sgjAP7II0P+yCJ6/sgjAP6rUAD+qlEK/qxNlP6uS1H+sEiV/rJFNf6vSgD+tEEu/rY/bP63
Paz+uDtV/rk6Mv68NAP+vTNq/r4zdP6/MHb+vzBh/r8wAP6/LwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAD+yCIA/sgiRP7IInn+yCIA/q5LAP6vSgD+rko8/rBImv6yRUv+s0OY/rVAT/63PQr+tzwI/rg8IP66
NwH+vTQY/r0zdP6+M4T+vzBW/sAvlf7ALxH+wC8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
/skiAP7IIgD+ySJW/skibf7IIgAAAAAA/rBHAP6fYQD+skVZ/rNDlP60QUr+tj+A/rc8lv65OoD+ujd2/rw2iP69
NJf+vjNp/r8wX/7AL5r+wC8n/sAvAP7BLwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD+ySEA
/skhDf7JIZT+ySE4/skhAAAAAAAAAAAA/rNDAP6xRgL+tEFJ/rY/mv64PHD+uTpT/ro5W/67N2H+vTRb/r4yX/6/
MIv+wC+I/sAvIP7ALwD+wC8AAAAAAAAAAAD+xiQA/sYkAf7HJA7+xyQR/scjEf7IIxH+yCMR/sgiEv7JIiz+ySGJ
/skhcv7JIQP+ySEAAAAAAAAAAAAAAAAA/rY+AP65OwD+tz0Z/rg7YP66OI3+uzaV/r00lf6+MpP+vzF8/r8wPv7A
Lwf+wC8AAAAAAAAAAAAAAAAAAAAAAP7HJAD+xyQN/sckff7HJJf+xyOW/sgjlv7IIpb+yCKX/skik/7JIVb+ySEI
/skhAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP6+MwD+uzcA/rs3BP68NQ/+vTMS/r4yCf7AMAH+vzAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAA/sckAP7HJAH+xyQP/sckE/7HIxL+yCMS/sgiEv7IIhH+ySEH/sgnAP7JHwAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
//////AP8H/AD8AfgA+AB4//AAOf/gADn/4AAZ/8EAGf/BIhn/wwIQ/8IGEP/BJhD/wQQR4OAAGYAgAD4AEAB+AA
gAfAAEAZgABweIQAP/CHBD/whAQ/8IQMP/mEHD/5hAg/+YIAf/nAAH/5wAD/8eAB8AH4A/AD/g/wD/////8=
"""


def set_window_icon(root):
    """Windows загружает ICO в память; временный файл удаляется сразу после назначения."""
    try:
        with TemporaryDirectory(prefix='crypto-rates-icon-') as directory:
            icon_path = Path(directory) / 'crypto.ico'
            icon_path.write_bytes(base64.b64decode(WINDOW_ICON_BASE64))
            root.iconbitmap(str(icon_path))
    except (OSError, tk.TclError):
        # Без доступа к temp или поддержки ICO остаётся стандартная иконка Tk.
        pass


def main():
    root = tk.Tk()
    CryptoApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
