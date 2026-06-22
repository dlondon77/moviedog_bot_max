# core/payment.py — модуль для работы с Тинькофф Кассой
import hashlib
import logging
import requests
import sqlite3
import configparser
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# Путь к конфигу (используем тот же, что и в боте)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'config.ini')

def load_payment_config():
    config = configparser.ConfigParser(interpolation=None)
    config.read(CONFIG_PATH, encoding='utf-8')
    return config

def generate_token(method: str, params: dict, config) -> str:
    """
    Генерация токена для Tinkoff API согласно документации.
    method: 'Init' или 'GetState'
    params: параметры запроса
    config: объект configparser
    """
    try:
        # Читаем пароль с отключенной интерполяцией
        temp_config = configparser.ConfigParser(interpolation=None)
        temp_config.read(CONFIG_PATH, encoding='utf-8')
        password = temp_config['Tinkoff']['password']
        
        sign_params = {
            'TerminalKey': config['Tinkoff']['terminal_key'],
            'Password': password
        }
        
        if method == 'Init':
            sign_params.update({
                'Amount': str(params['Amount']),
                'OrderId': params['OrderId'],
                'Description': params.get('Description', '')
            })
        elif method == 'GetState':
            sign_params.update({
                'PaymentId': params['PaymentId']
            })
        else:
            raise ValueError(f"Неизвестный метод: {method}")
        
        # Сортируем параметры по алфавиту
        sorted_params = sorted(sign_params.items(), key=lambda x: x[0])
        
        # Объединяем значения в одну строку
        token_str = ''.join(str(v) for _, v in sorted_params)
        
        logger.debug(f"Генерация токена для {method}")
        return hashlib.sha256(token_str.encode('utf-8')).hexdigest()
        
    except Exception as e:
        logger.error(f"Ошибка генерации токена: {e}")
        raise


def init_payment(
    user_id: int,
    amount: int,
    description: str,
    user_email: str = None,
    user_phone: str = None,
    tariff_id: int = None,
    payments_db_path: str = None
) -> dict:
    """
    Инициализация платежа через Tinkoff API.
    
    Args:
        user_id: ID пользователя
        amount: Сумма в рублях (целое число)
        description: Описание платежа
        user_email: Email пользователя (опционально)
        user_phone: Телефон пользователя (опционально)
        tariff_id: ID тарифа (если это подписка)
        payments_db_path: Путь к БД платежей (если None, берётся из конфига)
    
    Returns:
        dict: Ответ от Tinkoff API или None при ошибке
    """
    config = load_payment_config()
    
    try:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        order_id = f"sub_{user_id}_{int(datetime.now().timestamp())}"
        amount_kop = amount * 100
        
        # Формируем чек
        receipt = {
            "Email": user_email or "test@example.com",
            "Phone": user_phone or "+79000000000",
            "Taxation": "usn_income",
            "Items": [{
                "Name": description,
                "Price": amount_kop,
                "Quantity": 1,
                "Amount": amount_kop,
                "Tax": "none"
            }]
        }
        
        params = {
            "TerminalKey": config['Tinkoff']['terminal_key'],
            "Amount": amount_kop,
            "OrderId": order_id,
            "Description": description,
            "Receipt": receipt,
            "Token": generate_token('Init', {
                "Amount": amount_kop,
                "OrderId": order_id,
                "Description": description
            }, config)
        }
        
        logger.info(f"💰 Инициализация платежа для пользователя {user_id}, сумма: {amount} руб")
        
        response = requests.post(
            config['Tinkoff']['init_url'],
            json=params,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get('Success'):
            # Сохраняем платеж в БД
            if payments_db_path is None:
                payments_db_path = config['Data'].get('payments_db_path')
                if not payments_db_path:
                    payments_db_path = os.path.join(BASE_DIR, 'data', 'payments.db')
            
            conn = sqlite3.connect(payments_db_path)
            cursor = conn.cursor()
            
            # Создаём таблицу, если её нет
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    payment_id TEXT,
                    order_id TEXT,
                    amount INTEGER,
                    status TEXT,
                    description TEXT,
                    user_email TEXT,
                    user_phone TEXT,
                    tariff_id INTEGER,
                    payment_url TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            ''')
            
            cursor.execute('''
                INSERT INTO payments 
                (user_id, payment_id, order_id, amount, status, description, 
                 user_email, user_phone, tariff_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                data['PaymentId'],
                order_id,
                amount,
                'NEW',
                description,
                user_email,
                user_phone,
                tariff_id,
                current_time,
                current_time
            ))
            
            # Обновляем payment_url
            if 'PaymentURL' in data:
                cursor.execute('''
                    UPDATE payments SET payment_url = ? WHERE payment_id = ?
                ''', (data['PaymentURL'], data['PaymentId']))
            
            conn.commit()
            conn.close()
            
            logger.info(f"✅ Платёж создан. PaymentId: {data['PaymentId']}")
            return data
        
        logger.error(f"❌ Ошибка создания платежа: {data}")
        return None
        
    except Exception as e:
        logger.error(f"Ошибка при инициализации платежа: {e}")
        return None


def check_payment_status(payment_id: str, payments_db_path: str = None) -> dict:
    """
    Проверка статуса платежа через Tinkoff API.
    
    Args:
        payment_id: ID платежа в Tinkoff
        payments_db_path: Путь к БД платежей
    
    Returns:
        dict: Статус платежа или None при ошибке
    """
    config = load_payment_config()
    
    try:
        params = {
            "TerminalKey": config['Tinkoff']['terminal_key'],
            "PaymentId": payment_id,
            "Token": generate_token('GetState', {"PaymentId": payment_id}, config)
        }
        
        response = requests.post(
            config['Tinkoff']['state_url'],
            json=params,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get('Success'):
            # Обновляем статус в БД
            new_status = data.get('Status', '').upper()
            
            if payments_db_path is None:
                payments_db_path = config['Data'].get('payments_db_path')
                if not payments_db_path:
                    payments_db_path = os.path.join(BASE_DIR, 'data', 'payments.db')
            
            conn = sqlite3.connect(payments_db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE payments 
                SET status = ?, updated_at = ?
                WHERE payment_id = ?
            ''', (new_status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), payment_id))
            conn.commit()
            conn.close()
            
            return data
        
        return None
        
    except Exception as e:
        logger.error(f"Ошибка проверки статуса платежа: {e}")
        return None


def get_payment_info(payment_id: str, payments_db_path: str = None) -> dict:
    """
    Получение информации о платеже из БД.
    
    Args:
        payment_id: ID платежа в Tinkoff
        payments_db_path: Путь к БД платежей
    
    Returns:
        dict: Информация о платеже или None
    """
    config = load_payment_config()
    
    if payments_db_path is None:
        payments_db_path = config['Data'].get('payments_db_path')
        if not payments_db_path:
            payments_db_path = os.path.join(BASE_DIR, 'data', 'payments.db')
    
    conn = sqlite3.connect(payments_db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, payment_id, order_id, amount, status, description, 
               user_email, user_phone, tariff_id, payment_url, created_at, updated_at
        FROM payments 
        WHERE payment_id = ?
    ''', (payment_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'user_id': row[0],
            'payment_id': row[1],
            'order_id': row[2],
            'amount': row[3],
            'status': row[4],
            'description': row[5],
            'user_email': row[6],
            'user_phone': row[7],
            'tariff_id': row[8],
            'payment_url': row[9],
            'created_at': row[10],
            'updated_at': row[11]
        }
    return None


def get_payments_by_user(user_id: int, limit: int = 10, payments_db_path: str = None) -> list:
    """
    Получение списка платежей пользователя.
    
    Args:
        user_id: ID пользователя
        limit: Количество записей
        payments_db_path: Путь к БД платежей
    
    Returns:
        list: Список платежей
    """
    config = load_payment_config()
    
    if payments_db_path is None:
        payments_db_path = config['Data'].get('payments_db_path')
        if not payments_db_path:
            payments_db_path = os.path.join(BASE_DIR, 'data', 'payments.db')
    
    conn = sqlite3.connect(payments_db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT payment_id, amount, status, description, created_at, updated_at
        FROM payments 
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    ''', (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            'payment_id': row[0],
            'amount': row[1],
            'status': row[2],
            'description': row[3],
            'created_at': row[4],
            'updated_at': row[5]
        }
        for row in rows
    ]
