import tkinter as tk
from tkinter import messagebox

class GraphicEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Графический редактор")
        self.root.geometry("600x500")
 # --- ВСТАВИТЬ ИКОНКУ ЗДЕСЬ ---
        try:
            # Пытаемся загрузить иконку формата .ico
            self.root.iconbitmap("redactor.ico") 
        except Exception as e:
            # Если файл не найден или формат неверный, просто выводим ошибку в консоль
            # Программа продолжит работу без иконки
            print(f"Не удалось загрузить иконку: {e}")

        # Переменные для хранения текущих настроек пера
        self.current_color = "black"
        self.pen_thickness = 2  # Значение по умолчанию
        self.start_x = None
        self.start_y = None

        # --- Создание холста ---
        self.canvas = tk.Canvas(self.root, bg="white")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # Привязка событий мыши для рисования
        self.canvas.bind("<Button-1>", self.start_draw)
        self.canvas.bind("<B1-Motion>", self.draw)

        # --- Нижняя панель управления ---
        self.bottom_frame = tk.Frame(self.root)
        self.bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)

        # 1. Палитра цветов
        colors = ["red", "green", "blue", "black"]
        for color in colors:
            btn = tk.Button(self.bottom_frame, bg=color, width=4, 
                            command=lambda c=color: self.set_color(c))
            btn.pack(side=tk.LEFT, padx=2, pady=5)

        # 2. Поле ввода для толщины линии
        tk.Label(self.bottom_frame, text="Толщина линии:").pack(side=tk.LEFT, padx=(10, 5))
        
        self.thickness_entry = tk.Entry(self.bottom_frame, width=5)
        self.thickness_entry.insert(0, str(self.pen_thickness)) # Вставляем значение по умолчанию
        self.thickness_entry.pack(side=tk.LEFT)

        # 3. Кнопка установки толщины
        self.set_thickness_btn = tk.Button(self.bottom_frame, text="Установить толщину", 
                                           command=self.set_thickness)
        self.set_thickness_btn.pack(side=tk.LEFT, padx=5)

    def set_color(self, color):
        """Устанавливает текущий цвет пера."""
        self.current_color = color

    def set_thickness(self):
        """
        Считывает значение из поля ввода и обновляет толщину пера.
        Обрабатывает исключение ValueError, если введено не целое число.
        """
        try:
            # Пытаемся преобразовать строку из Entry в целое число
            new_thickness = int(self.thickness_entry.get())
            
            # Проверка на отрицательное значение или ноль
            if new_thickness <= 0:
                raise ValueError("Толщина должна быть больше нуля")
                
            self.pen_thickness = new_thickness
            
        except ValueError:
            # Если введено не число (или число <= 0), показываем ошибку
            messagebox.showerror("Ошибка ввода", "Пожалуйста, введите корректное целое положительное число для толщины пера.")
            # Возвращаем старое значение в поле ввода
            self.thickness_entry.delete(0, tk.END)
            self.thickness_entry.insert(0, str(self.pen_thickness))

    def start_draw(self, event):
        """Запоминает начальные координаты при нажатии кнопки мыши."""
        self.start_x = event.x
        self.start_y = event.y

    def draw(self, event):
        """Рисует линию от предыдущей точки к текущей с учетом толщины."""
        if self.start_x and self.start_y:
            # Обновленная функция draw использует self.pen_thickness
            self.canvas.create_line(
                self.start_x, self.start_y, event.x, event.y,
                fill=self.current_color,
                width=self.pen_thickness,  # Использование заданной толщины
                capstyle=tk.ROUND,         # Скругленные концы линий для плавности
                smooth=True
            )
        # Обновляем координаты для следующего сегмента линии
        self.start_x = event.x
        self.start_y = event.y

if __name__ == "__main__":
    
    root = tk.Tk()
    app = GraphicEditor(root)
    root.mainloop()