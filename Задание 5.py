from tkinter import Tk, Label, Button
from tkinter import messagebox as mb
from tkinter import ttk
from math import isfinite
import webbrowser
import requests


def update_currency_label(event):
    code = target_combobox.get()
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
    second_base_code = second_base_combobox.get().strip()

    if any(code not in currencies for code in (
        base_code, second_base_code, target_code
    )):
        mb.showwarning('Внимание', 'Выберите обе базовые и целевую валюты.')
        return

    results = []
    success_count = 0

    # Для каждой базовой валюты получаем отдельный ответ в формате JSON.
    for code in (base_code, second_base_code):
        try:
            response = requests.get(
                f'https://open.er-api.com/v6/latest/{code}', timeout=10
            )
            response.raise_for_status()
            data = response.json()

            if data['result'] != 'success':
                error_type = data.get('error-type', 'неизвестная ошибка')
                raise ValueError(f'Ошибка сервиса: {error_type}')

            if target_code not in data['rates']:
                raise ValueError(f'Валюта {target_code} не найдена в ответе.')

            exchange_rate = float(data['rates'][target_code])
            if not isfinite(exchange_rate) or exchange_rate <= 0:
                raise ValueError('Сервис вернул некорректный курс.')

            # Шесть значащих цифр сохраняют точность и для небольших курсов.
            results.append(f'1 {code} = {exchange_rate:.6g} {target_code}')
            success_count += 1
        except requests.exceptions.JSONDecodeError:
            results.append(f'{code}: сервер вернул некорректный JSON.')
        except requests.RequestException:
            results.append(
                f'{code}: не удалось получить курс. '
                'Проверьте интернет и повторите попытку.'
            )
        except (KeyError, TypeError):
            results.append(f'{code}: неверный формат данных сервиса.')
        except ValueError as error:
            results.append(f'{code}: {error}')

    # Обе строки показываем одновременно, даже если один запрос не удался.
    message = '\n'.join(results)
    if success_count == 2:
        mb.showinfo('Курсы обмена', message)
    elif success_count == 1:
        mb.showwarning('Получен только один курс', message)
    else:
        mb.showerror('Ошибка получения курсов', message)


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
    root.geometry('360x490')
    root.minsize(360, 490)

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
    source_label = ttk.Label(
        root, text='Курсы: ExchangeRate-API', foreground='blue', cursor='hand2'
    )
    source_label.pack(pady=(0, 10))
    source_label.bind(
        '<Button-1>',
        lambda event: webbrowser.open('https://www.exchangerate-api.com')
    )
    root.mainloop()


if __name__ == '__main__':
    main()
