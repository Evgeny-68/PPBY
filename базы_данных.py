import sqlite3

conn = sqlite3.connect('test.db')
cursor = conn.cursor()

# cursor.execute('''INSERT  INTO Car (name, model,
# year, activ) VALUES (?, ?, ?, ?)''', ('VAZ', 2016, 1979, 1))

conn.commit()
# result = cursor.execute("""SELECT name, model,
# year FROM Car WHERE year BETWEEN 1979 and 1985;""")
# result = cursor.execute('''SELECT name, model,
# year FROM Car WHERE name LIKE "M%";''')
# result = cursor.execute('''SELECT name, model,
# year FROM Car WHERE name LIKE "M%" OR name LIKE "L%";''')
# result = cursor.execute('''SELECT DISTINCT
# year FROM Car;''')
# result = cursor.execute("""SELECT name, model,
# year FROM Car WHERE year BETWEEN 1979 and 1985 ORDER BY name DESC;""")
# result = cursor.execute("""SELECT name, model,
# year FROM Car WHERE year BETWEEN 1979 and 1985 ORDER BY name DESC LIMIT 3 OFFSET 1;""")
# result = cursor.execute("""SELECT name, model,
# year FROM Car WHERE year BETWEEN 1979 and 1985 ORDER BY name DESC LIMIT 1, 2;""")
result = cursor.execute("""SELECT name, model,
year FROM Car WHERE year BETWEEN 1979 and 1985 ORDER BY name DESC LIMIT 1, 2;""")
print(result)
for row in result.fetchall():
    print(row)

