import logging
import requests
import psycopg2
from psycopg2 import sql
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from datetime import datetime

# Этапы разговора
SALARY, CITY, KEYWORDS = range(3)

# Настройки базы данных
DB_NAME = 'hhru'
DB_USER = 'postgres'
DB_PASSWORD = 'postgres'
DB_HOST = 'localhost'

# Функция для подключения к базе данных
def connect_db():
    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST)
    return conn

# Получение ID города
def get_city_id(city_name):
    url = "https://api.hh.ru/suggests/areas"
    params = {"text": city_name}
    response = requests.get(url, params=params)
    data = response.json()

    if data and "items" in data and len(data["items"]) > 0:
        return data["items"][0]["id"]
    else:
        return None

# Стартовая команда
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reply_markup = ReplyKeyboardRemove()
    
    await update.message.reply_text(
        'Добро пожаловать! Пожалуйста, введите минимальную зарплату:',
        reply_markup=reply_markup
    )
    return SALARY

# Обработка зарплаты
async def salary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['salary'] = update.message.text
    await update.message.reply_text('Спасибо! Теперь введите город для поиска вакансий:')
    return CITY

# Обработка города
async def city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['city'] = update.message.text
    await update.message.reply_text('Отлично! Теперь введите ключевые слова для поиска (например, "программист"):')
    return KEYWORDS

# Обработка ключевых слов и выполнение запроса к API
async def keywords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['keywords'] = update.message.text

    # Параметры запроса
    salary = context.user_data['salary']
    city_name = context.user_data['city']
    keywords = context.user_data['keywords']

    city_id = get_city_id(city_name)
    if city_id is None:
        await update.message.reply_text('Не удалось найти указанный город. Попробуйте еще раз.')
        return CITY
    
    url = "https://api.hh.ru/vacancies"
    params = {
        "text": keywords,
        "area": city_id,
        "salary": salary,
        "search_field": "name"
    }

    # Выполнение запроса к API
    response = requests.get(url, params=params)
    data = response.json()

    # Извлечение данных
    vacancies_count = data.get('found', 0)
    total_salary = 0
    salary_count = 0
    min_salary = None
    max_salary = None
    popular_vacancies = []

    for item in data.get('items', []):
        if 'salary' in item and item['salary']:
            if item['salary']['from']:
                if min_salary is None or item['salary']['from'] < min_salary:
                    min_salary = item['salary']['from']
            if item['salary']['to']:
                if max_salary is None or item['salary']['to'] > max_salary:
                    max_salary = item['salary']['to']
            if item['salary']['from'] and item['salary']['to']:
                total_salary += (item['salary']['from'] + item['salary']['to']) / 2
                salary_count += 1
            elif item['salary']['from']:
                total_salary += item['salary']['from']
                salary_count += 1
            elif item['salary']['to']:
                total_salary += item['salary']['to']
                salary_count += 1
        popular_vacancies.append(f"{item['name']} - {item['alternate_url']}")

    average_salary = int(total_salary / salary_count) if salary_count > 0 else 0

    # Сохранение данных в базу данных
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        sql.SQL("INSERT INTO requests (salary, city, keywords, vacancies_count, average_salary, min_salary, max_salary, request_time) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"),
        (salary, city_name, keywords, vacancies_count, average_salary, min_salary, max_salary, datetime.now())
    )
    conn.commit()
    cur.close()
    conn.close()

    # Формирование списка популярных вакансий
    popular_vacancies_message = "\n".join(popular_vacancies[:5])  # Ограничимся пятью ссылками

    # Отправка данных пользователю
    await update.message.reply_text(
        f'Найдено вакансий: {vacancies_count}\n'
        f'Средняя зарплата: {average_salary}\n'
        f'Минимальная зарплата: {min_salary}\n'
        f'Максимальная зарплата: {max_salary}\n\n'
        f'Популярные вакансии:\n{popular_vacancies_message}'
    )

    return ConversationHandler.END

# Завершение разговора
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Процесс отменен.')
    return ConversationHandler.END

def main() -> None:
    # Создание Application
    application = Application.builder().token("7068178617:AAGbbh1CAYTwHOzcEexgdiT7TmnBbyFXrC0").build()

    # Определение разговора
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SALARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, salary)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, city)],
            KEYWORDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, keywords)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)

    # Запуск бота
    application.run_polling()

if __name__ == '__main__':
    main()
