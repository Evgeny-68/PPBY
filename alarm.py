from pathlib import Path
from tkinter import *
from tkinter import messagebox as mb
import time
import pygame as pg

pg.mixer.init()
# pg.mixer.music.load('electronic-alarm-signal.mp3')
sound_path = Path(__file__).resolve().parent / 'electronic-alarm-signal.mp3'
pg.mixer.music.load(str(sound_path))

time_alarm = ''


def tick():
    global time_alarm

    current_time = time.strftime("%H:%M:%S")
    screen_time.config(text=current_time)

    if time_alarm == current_time:
        time_alarm = ''
        pg.mixer.music.play()

    root.after(1000, tick)


def on_click():
    global time_alarm

    try:
        hours = int(hours_var.get())
        minutes = int(minutes_var.get())
        seconds = int(seconds_var.get())

        if not (0 <= hours <= 23
                and 0 <= minutes <= 59
                and 0 <= seconds <= 59):
            raise ValueError

    except ValueError:
        mb.showerror(
            'Ошибка',
            'Введите часы от 00 до 23, '
            'минуты и секунды от 00 до 59.'
        )
        return

    time_alarm = f'{hours:02d}:{minutes:02d}:{seconds:02d}'

    hours_var.set(f'{hours:02d}')
    minutes_var.set(f'{minutes:02d}')
    seconds_var.set(f'{seconds:02d}')

    mb.showinfo(
        'Включение будильника',
        f'Будильник включен на {time_alarm}'
    )


def off_click():
    global time_alarm

    time_alarm = ''
    pg.mixer.music.stop()

    hours_var.set('00')
    minutes_var.set('00')
    seconds_var.set('00')

    mb.showwarning(
        'Выключение будильника',
        'Будильник выключен'
    )


root = Tk()
root.title('Будильник')
root.config(background='black')

WIDTH = root.winfo_screenwidth()
HEIGHT = root.winfo_screenheight()
X, Y = 400, 260

root.geometry(
    f'{X}x{Y}+{WIDTH // 2 - X // 2}'
    f'+{HEIGHT // 2 - Y // 2 - 25}'
)

screen_time = Label(
    root,
    text='00:00:00',
    font=('Arial', 50),
    bg='black',
    fg='lime'
)
screen_time.pack()

Label(
    root,
    text='Часы : Минуты : Секунды',
    font=('Arial', 12),
    bg='black',
    fg='white'
).pack(pady=5)

time_frame = Frame(root, bg='black')
time_frame.pack()

hours_var = StringVar(value='00')
minutes_var = StringVar(value='00')
seconds_var = StringVar(value='00')

for index, (variable, maximum) in enumerate([
    (hours_var, 23),
    (minutes_var, 59),
    (seconds_var, 59),
]):
    if index > 0:
        Label(
            time_frame,
            text=':',
            font=('Arial', 20),
            bg='black',
            fg='white'
        ).pack(side=LEFT)

    Spinbox(
        time_frame,
        from_=0,
        to=maximum,
        format='%02.0f',
        wrap=True,
        textvariable=variable,
        width=3,
        font=('Arial', 20),
        justify=CENTER
    ).pack(side=LEFT)

Button(
    root,
    text='Включить',
    font=('Arial', 10),
    command=on_click
).pack(pady=10)

Button(
    root,
    text='Выключить',
    font=('Arial', 10),
    command=off_click
).pack()

tick()
root.mainloop()