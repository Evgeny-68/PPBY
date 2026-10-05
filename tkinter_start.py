from tkinter import *
def answer(event):
    answ = num.get().strip()
    result.configure(text=answ)
root = Tk()
root.title('СТАРТ')
WIDHT = root.winfo_screenwidth()
HEIGHT = root.winfo_screenheight()
X = 300
Y = 140
root.geometry(f'{X}x{Y}+{WIDHT // 2 - X // 2}'
              f'+{HEIGHT // 2 - Y // 2 - 25}')
# root.geometry('300x300+300+200')
prompt = Label(text='Введите значение', font=('Arial 12'))
prompt.pack()
num = Entry(width=5, font=('Arial 12'))
num.pack()
result = Label(text='   ', font='Arial 10', bg='lightgray')
result.pack(pady=10)
btn = Button()
num.bind('<Return>', answer)
root.mainloop()