"""Задание 6. Прямые котировки Bybit отдельно к USD и USDT.

Запуск: python "Задание 6.py"
Зависимости: python -m pip install -r requirements_task6.txt
"""

from datetime import timedelta, timezone
from decimal import Decimal
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
import time
import tkinter as tk
from tkinter import ttk

from crypto_api_task6 import COINS, QUOTE_CURRENCIES, BybitClient, QuoteError


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
        icon_path = Path(__file__).resolve().parent / 'assets' / 'crypto.ico'
        if icon_path.is_file():
            try:
                self.root.iconbitmap(str(icon_path))
            except tk.TclError:
                # Некоторые платформы Tk не поддерживают значки в формате ICO.
                pass
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


def main():
    root = tk.Tk()
    CryptoApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
