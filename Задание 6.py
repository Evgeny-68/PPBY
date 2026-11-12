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
        self.timer_id = None
        self.start_id = None

        self.auto_refresh = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Ожидание первого запроса…')
        self.received = tk.StringVar(value='Данные ещё не получены')
        self.source = tk.StringVar(value='Источник: Bybit  •  Прямые спотовые пары')
        self.price_note = tk.StringVar(
            value='Цена — последняя сделка на Bybit. Время получения не является временем сделки.'
        )
        self.root.title('Задание 6 — Курсы криптовалют')
        icon_path = Path(__file__).resolve().parent / 'assets' / 'crypto.ico'
        if icon_path.is_file():
            try:
                self.root.iconbitmap(str(icon_path))
            except tk.TclError:
                # Некоторые платформы Tk не поддерживают значки в формате ICO.
                pass
        self.root.geometry('920x700')
        self.root.minsize(880, 700)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self._build_interface()
        self.start_id = self.root.after(100, self.refresh)
        self.timer_id = self.root.after(100, self._poll)

    def _build_interface(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10))
        style.configure('Title.TLabel', font=('Segoe UI', 20, 'bold'))
        style.configure('Treeview', rowheight=34, font=('Segoe UI', 11))
        style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'))
        style.configure('Note.TLabel', foreground='#526174')
        style.configure('Status.TLabel', foreground='#234A70')

        frame = ttk.Frame(self.root, padding=22)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Курсы криптовалют', style='Title.TLabel').pack(anchor='w')
        ttk.Label(
            frame, textvariable=self.source,
            style='Note.TLabel',
        ).pack(anchor='w', pady=(5, 18))

        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=(0, 16))
        self.refresh_button = ttk.Button(controls, text='Обновить', command=self.refresh)
        self.refresh_button.pack(side='left')
        ttk.Checkbutton(
            controls, text='Автообновление каждые 60 секунд',
            variable=self.auto_refresh,
        ).pack(side='left', padx=20)

        self.notebook = ttk.Notebook(frame)
        self.tables = {}
        tab_names = {'USD': 'USD — доллар США', 'USDT': 'USDT — Tether'}
        for currency in QUOTE_CURRENCIES:
            tab = ttk.Frame(self.notebook, padding=4)
            self.notebook.add(tab, text=tab_names[currency])
            columns = ('name', 'symbol', 'price', 'low', 'high')
            table = ttk.Treeview(
                tab, columns=columns, show='headings', height=len(COINS),
            )
            for column, title, width, anchor in (
                ('name', 'Криптовалюта', 175, 'w'),
                ('symbol', 'Тикер', 75, 'center'),
                ('price', f'Цена, {currency}', 170, 'e'),
                ('low', f'Мин. 24 ч, {currency}', 175, 'e'),
                ('high', f'Макс. 24 ч, {currency}', 175, 'e'),
            ):
                table.heading(column, text=title, anchor=anchor)
                table.column(column, width=width, minwidth=width, anchor=anchor)
            table.tag_configure('stripe', background='#EEF3F8')
            for index, coin in enumerate(COINS):
                tags = ('stripe',) if index % 2 == 0 else ()
                price = 'Валюта котировки' if coin.symbol == currency else '—'
                table.insert(
                    '', 'end', iid=f'{coin.symbol}:{currency}',
                    values=(coin.name, coin.symbol, price, '—', '—'), tags=tags,
                )
            table.pack(fill='x')
            self.tables[currency] = table
        self.notebook.pack(fill='x')
        ttk.Label(
            frame, text='USD — доллар США; USDT — токен Tether. Пересчёт между ними не выполняется.',
            style='Note.TLabel', wraplength=820,
        ).pack(anchor='w', pady=(10, 0))

        self.status_label = ttk.Label(
            frame, textvariable=self.status, style='Status.TLabel', wraplength=820,
        )
        self.status_label.pack(anchor='w', pady=(16, 5))
        ttk.Label(frame, textvariable=self.received, style='Note.TLabel').pack(anchor='w')
        ttk.Label(
            frame, textvariable=self.price_note,
            style='Note.TLabel', wraplength=820,
        ).pack(anchor='w', pady=(10, 0))

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
        self.status.set('Загрузка котировок…')
        Thread(
            target=fetch_in_worker, args=(self.provider, self.results), daemon=True,
        ).start()

    def _show_result(self, snapshot, error):
        self.busy = False
        if error:
            if self.snapshot is None:
                self.status.set(f'Данные не получены. {error}')
            else:
                self.status.set(
                    f'Обновление не выполнено; показаны устаревшие данные в обеих вкладках. {error}'
                )
            return

        self.snapshot = snapshot
        self.source.set(f'Источник: {snapshot.source}  •  Прямые спотовые пары')
        self.price_note.set(
            f'Цена — последняя сделка на {snapshot.source}. Время получения не является временем сделки.'
        )
        for quote in snapshot.quotes:
            if quote.status == 'quote_currency':
                price, low, high = 'Валюта котировки', '—', '—'
            elif quote.status == 'missing':
                price, low, high = 'Нет данных по паре', '—', '—'
            else:
                price = format_price(quote.price)
                low, high = format_price(quote.low_24h), format_price(quote.high_24h)
            self.tables[quote.currency].item(quote.row_id, values=(
                quote.name, quote.symbol, price, low, high,
            ))
        received = snapshot.received_at.astimezone(MOSCOW_TIME).strftime('%d.%m.%Y %H:%M:%S')
        self.received.set(f'Данные получены: {received} МСК')
        available = sum(quote.status == 'available' for quote in snapshot.quotes)
        missing = sum(quote.status == 'missing' for quote in snapshot.quotes)
        self.status.set(f'Обновлены прямые пары: {available}. Нет данных по парам: {missing}.')

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
