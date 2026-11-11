import requests
from bs4 import BeautifulSoup

'''http://hse.ru/staff/allat'''
response = requests.get('http://hse.ru/staff/allat')
soup = BeautifulSoup(response.text, 'html.parser')
name = soup.find_all('h1', class_='name')
print(response)
print(response.text)
