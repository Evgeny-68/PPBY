# n = int(input())
# l = []
# for i in range(n):
#     day, month = map(int, input().split())
#     l.append(day)
# cnt = 0
# for i in range(n):
#     day, month = l(i)
#     if day == 3 and month == 9:
#         break
#     else:
#         l.append((day, month))
#         cnt += 1
#         print(cnt)
#         for i in range(len(l[cnt:])):
#             print(*l[cnt:][i])
n = int(input())
l = []
for _ in range(n):
    day, month = map(int, input().split())
    l.append((day, month))
cnt = 0
while l[0] != (3, 9):
    l.append(l.pop(0))   # первая карточка — в конец, это и есть одно перелистывание
    cnt += 1
print(cnt)
for day, month in l:
    print(day, month)