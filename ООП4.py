from abc import ABC, abstractmethod

class Shape(ABC):
   def __init__(self, name):
       self.name = name

    @abstractmethod
    def get_shape(self):
        pass

   def display(self):
        print(self.name)
class Rectangle(Shape):
    def __init__(self, widht, height):
        super().__init__('Прямоугольник')
        self.width = widht
        self.height = height

    def
    def get_shape(self):

    def display(self):
        super().display()
        print(f'Высота: {self.height} ед.\n')

