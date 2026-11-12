"""Задание 6. Окно котировок криптовалют к USD на основе публичного Kraken API.

Запуск: python "Задание 6.py"
Зависимости: python -m pip install -r requirements_task6.txt
"""

from datetime import timedelta, timezone
from decimal import Decimal
from queue import Empty, Queue
from threading import Thread
import time
import tkinter as tk
from tkinter import ttk

from crypto_api_task6 import COINS, KrakenClient, QuoteError


AUTO_REFRESH_SECONDS = 60
MIN_REQUEST_INTERVAL = 5
MOSCOW_TIME = timezone(timedelta(hours=3))


def format_price(value: Decimal):
    """Для небольших цен сохраняем шесть значащих цифр вместо нуля."""
    if value >= 1:
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
        self.provider = provider if provider is not None else KrakenClient()
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
        self.source = tk.StringVar(value='Источник: Kraken  •  Валюта котировки: доллар США (USD)')
        self.price_note = tk.StringVar(
            value='Цена — последняя сделка на Kraken. Время получения не является временем сделки.'
        )
        self.root.title('Задание 6 — Курсы криптовалют')
        self.root.geometry('920x560')
        self.root.minsize(880, 560)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self._build_interface()
        self.start_id = self.root.after(100, self.refresh)
        self.timer_id = self.root.after(100, self._poll)

    def _build_interface(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10))
        style.configure('Title.TLabel', font=('Segoe UI', 20, 'bold'))
        style.configure('Treeview', rowheight=42, font=('Segoe UI', 11))
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

        columns = ('name', 'symbol', 'price', 'low', 'high')
        self.table = ttk.Treeview(frame, columns=columns, show='headings', height=5)
        for column, title, width, anchor in (
            ('name', 'Криптовалюта', 175, 'w'),
            ('symbol', 'Тикер', 75, 'center'),
            ('price', 'Цена, USD', 170, 'e'),
            ('low', 'Мин. за 24 ч, USD', 175, 'e'),
            ('high', 'Макс. за 24 ч, USD', 175, 'e'),
        ):
            self.table.heading(column, text=title, anchor=anchor)
            self.table.column(column, width=width, minwidth=width, anchor=anchor)
        self.table.tag_configure('stripe', background='#EEF3F8')
        for index, coin in enumerate(COINS):
            tags = ('stripe',) if index % 2 == 0 else ()
            self.table.insert(
                '', 'end', iid=coin.symbol,
                values=(coin.name, coin.symbol, '—', '—', '—'), tags=tags,
            )
        self.table.pack(fill='x')

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
                self.status.set(f'Обновление не выполнено; показаны устаревшие данные. {error}')
            return

        self.snapshot = snapshot
        self.source.set(f'Источник: {snapshot.source}  •  Валюта котировки: доллар США (USD)')
        self.price_note.set(
            f'Цена — последняя сделка на {snapshot.source}. Время получения не является временем сделки.'
        )
        for quote in snapshot.quotes:
            self.table.item(quote.symbol, values=(
                quote.name, quote.symbol, format_price(quote.price),
                format_price(quote.low_24h), format_price(quote.high_24h),
            ))
        received = snapshot.received_at.astimezone(MOSCOW_TIME).strftime('%d.%m.%Y %H:%M:%S')
        self.received.set(f'Данные получены: {received} МСК')
        self.status.set('Все пять котировок обновлены.')

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
