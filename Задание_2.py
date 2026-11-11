def show_menu():
    """Функция для вывода меню на экран"""
    print("\nВыберите операцию:")
    print("1. Сложение")
    print("2. Вычитание")
    print("3. Умножение")
    print("4. Деление")
    print("5. Просмотр истории вычислений")

# Бесконечный цикл, чтобы калькулятор работал, пока мы его не закроем
while True:
    show_menu()
    choice = input("Введите номер операции (1/2/3/4/5): ")

    # Если выбрана история вычислений
    if choice == '5':
        print("История вычислений:")
        try:
            # Открываем файл для чтения (режим 'r')
            # encoding='utf-8' нужен для правильного чтения русских букв
            with open("calculations.txt", "r", encoding="utf-8") as file:
                for line in file:
                    print(line.strip()) # strip() убирает лишние переносы строк
        except FileNotFoundError:
            # Если файла еще нет (программа только запущена)
            print("История пока пуста. Вы еще не делали вычислений.")

    # Если выбрана одна из математических операций
    elif choice in ['1', '2', '3', '4']:
        # Запрашиваем числа. Используем float, чтобы можно было вводить дробные числа
        try:
            num1 = float(input("Введите первое число: "))
            num2 = float(input("Введите второе число: "))
        except ValueError:
            print("Ошибка! Нужно вводить только числа.")
            continue # Возвращаемся в начало цикла

        # Выполняем нужное действие и запоминаем знак операции
        if choice == '1':
            result = num1 + num2
            op = '+'
        elif choice == '2':
            result = num1 - num2
            op = '-'
        elif choice == '3':
            result = num1 * num2
            op = '*'
        elif choice == '4':
            if num2 == 0:
                print("Ошибка! На ноль делить нельзя.")
                continue
            result = num1 / num2
            op = '/'

        # Красиво форматируем числа для вывода (как на картинке)
        # Если число целое (например 4.0), делаем его просто 4
        n1 = int(num1) if num1.is_integer() else num1
        n2 = int(num2) if num2.is_integer() else num2

        if choice == '4':
            # Для деления оставляем 2 знака после запятой (как 1.00 на картинке)
            res_str = f"{result:.2f}"
        else:
            # Для остальных операций делаем красиво (без .0)
            res_str = int(result) if float(result).is_integer() else result

        # Формируем строку для вывода и записи в файл
        history_line = f"Результат: {n1} {op} {n2} = {res_str}"

        # Выводим результат на экран
        print(history_line)

        # Открываем файл в режиме 'a' (append - добавление в конец)
        with open("calculations.txt", "a", encoding="utf-8") as file:
            # Записываем строку и не забываем про \n (перенос на новую строку)
            file.write(history_line + "\n")

    else:
        print("Неверный ввод. Пожалуйста, выберите цифру от 1 до 5.")