from tkinter import Tk, Label, Button
from tkinter import messagebox as mb
from tkinter import ttk
import requests


def update_currency_label(event):
    code = target_combobox.get()
    # code = combobox.get()
    name = currencies[code]
    target_label.config(text=name)


def update_base_label(event):
    code = base_combobox.get()
    name = currencies[code]
    base_label.config(text=name)


def update_second_base_label(event):
    code = second_base_combobox.get()
    name = currencies[code]
    second_base_label.config(text=name)


def exchange():
    target_code = target_combobox.get().strip()
    base_code = base_combobox.get().strip()
    # code = entry.get().upper().strip()
    # code = combobox.get()
    if target_code and base_code:
        try:

            response = requests.get(f'https://open.er-api.com/v6/latest/{base_code}')
            response.raise_for_status()
            data = response.json()
            if target_code in data['rates']:
                exchange_rate = data['rates'][target_code]
                base = currencies[base_code]
                target = currencies[target_code]
                # currency_name = currencies[code]
                mb.showinfo('Курс обмена',
                            f'Курс: {exchange_rate:.1f} {target} за 1 {base}')
            else:
                mb.showerror('Ошибка',
                            f'Валюта {target_code} не найдена')
        except Exception as er:
            mb.showerror('Ошибка', er)

    else:
        mb.showwarning('Внимание', 'Введите код валюты')


currencies = {
    'EUR': 'Евро',
    'USD': 'Доллар США',
    'JPY': 'Японская йена',
    'GBP': 'Фунт стерлингов',
    'AUD': 'Австралийский доллар',
    'CAD': 'Канадский доллар',
    'CHF': 'Швейцарский франк',
    'CNY': 'Китайский юань',
    'RUB': 'Российский рубль',
    'KZT': 'Казахстанский тенге',
    'UZS': 'Узбекский сум'

}

def main():
    global root, base_combobox, second_base_combobox, target_combobox
    global base_label, second_base_label, target_label

    root = Tk()
    root.title('Курсы обмена валют')
    root.geometry('360x450')
    root.minsize(360, 450)

    Label(root, text='Базовая валюта').pack(pady=(15, 10))
    base_combobox = ttk.Combobox(
        root, values=list(currencies), state='readonly'
    )
    base_combobox.set('EUR')
    base_combobox.pack(pady=10)
    base_combobox.bind('<<ComboboxSelected>>', update_base_label)
    base_label = ttk.Label(root, text=currencies['EUR'])
    base_label.pack(pady=10)

    Label(root, text='Вторая базовая валюта').pack(pady=10)
    second_base_combobox = ttk.Combobox(
        root, values=list(currencies), state='readonly'
    )
    second_base_combobox.set('USD')
    second_base_combobox.pack(pady=10)
    second_base_combobox.bind(
        '<<ComboboxSelected>>', update_second_base_label
    )
    second_base_label = ttk.Label(root, text=currencies['USD'])
    second_base_label.pack(pady=10)

    Label(root, text='Целевая валюта').pack(pady=10)
    target_combobox = ttk.Combobox(
        root, values=list(currencies), state='readonly'
    )
    target_combobox.set('RUB')
    target_combobox.pack(pady=10)
    target_combobox.bind('<<ComboboxSelected>>', update_currency_label)
    target_label = ttk.Label(root, text=currencies['RUB'])
    target_label.pack(pady=10)

    Button(root, text='Получить курсы обмена', command=exchange).pack(
        pady=15, padx=10
    )
    root.mainloop()


if __name__ == '__main__':
    main()
