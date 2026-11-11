from string import digits, ascii_letters
import re
import random


def get_password(m):
    # data = set(ascii_letters + digits) - {'0', '1', 'o', 'O', 'l', 'I'}
    # data = ''.join(data)
    data1 = ''.join(re.findall(r'[^01oOlI]', ascii_letters + digits))
    password = random.sample(data1, m)
    # pos = random.sample(range(m), 3)
    # password[pos[0]] = password[pos[0]].lower()
    # password[pos[1]] = password[pos[1]].upper()
    # password[pos[2]] = str(random.randint(2, 9))
    password = ''
    while (not re.search(r'[a-z]', password)
           or not re.search(r'[A-Z]', password)
           or not re.search(r'[2-9]', password)):
        password = ''.join(random.sample(data1, m))

    return password


def main(n, m):
    # res = set()
    # while len(res) < n:
    #     res.add(get_password(m))
    #
    # for p in res:
    #     print(p)


    while len(res) < n:
        res.add(get_password(m))

    for p in res:
        print(p)
    with open('passwords.txt', 'w') as f:
        for i, p in enumerate(res, 1):
            f.write(f'{i:2}. {p}\n')


main(10, 12)