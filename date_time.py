from datetime import datetime, date, time, timedelta

# d = date(2024, 12, 31)
# t = time(12, 31, 16)
# print(d, type(d))
# print(t, type(t))
# dt = datetime.combine(d, t)
# print(dt, type(dt))
# d = date.today()
# print(d)
# dt = datetime.now().replace(microsecond=0)
# print(dt.time())
# dt = datetime.now().replace(microsecond=0)
# # dt = dt.replace(year=2020, month=10, day=30, hour=10, minute=30, second=30)
# print(dt)
# dtt = input('ВВедите дату (дд.мм.гггг): ')
# datte = datetime.strptime(dtt, '%d.%m.%Y')
# print(datte)
# print(datte.strftime('%A %d.%B.%Y %I:%M%p'))
# print(datte.strftime('%d.%m.%Y %X'))
# print(datte.strftime('%d.%m.%Y %H:%M'))
# print(datte.date())

birthday = input('Введите дату рождения ("дд.мм.гггг"): ')
birthday = datetime.strptime(birthday, '%d.%m/%Y').date()
dt_now = dt_now.year
res = birthday.replase(year=year_ +1)
if birthday < dt_now
    if res
print(birthday)
