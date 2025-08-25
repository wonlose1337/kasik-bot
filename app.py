import logging
import re
import json
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
import asyncio
import datetime
from PIL import Image, ImageDraw, ImageFont
import os
import pathlib

def safe_print(text: str):
    try:
        print(text)
    except UnicodeEncodeError:
        try:
            print(text.encode('ascii', 'ignore').decode('ascii'))
        except Exception:
            pass

def is_admin(user_id: int) -> bool:
    """проверяет, является ли пользователь админом"""
    return user_id in ADMIN_IDS

async def check_channel_subscription(user_id: int) -> bool:
    """проверяет, подписан ли пользователь на канал @daisicx"""
    try:
        # Проверяем подписку на канал @daisicx
        member = await bot.get_chat_member(chat_id='@daisicx', user_id=user_id)
        return member.status not in ['left', 'kicked']
    except Exception as e:
        print(f"ошибка проверки подписки: {e}")
        return False

def update_roulette_history(user_id: str, amount: int, bet_type: str):
    """
    Обновляет историю ставок игрока для анализа паттернов
    """
    current_time = datetime.datetime.now().timestamp()
    
    # Инициализируем историю для нового пользователя
    if user_id not in roulette_bet_history:
        roulette_bet_history[user_id] = []
    
    # Очищаем старые записи (старше BET_HISTORY_WINDOW секунд)
    roulette_bet_history[user_id] = [
        bet for bet in roulette_bet_history[user_id] 
        if current_time - bet['time'] < BET_HISTORY_WINDOW
    ]
    
    # Добавляем новую ставку в историю
    roulette_bet_history[user_id].append({
        'time': current_time,
        'amount': amount,
        'bet_type': bet_type
    })

# Получаем токен из переменных окружения или из config.py
API_TOKEN = os.getenv('BOT_TOKEN')
if not API_TOKEN:
    try:
        from config import BOT_TOKEN
        API_TOKEN = BOT_TOKEN
        safe_print("✅ Токен загружен из config.py")
    except ImportError:
        safe_print("❌ ОШИБКА: Не удалось загрузить токен из config.py!")
        safe_print("🔐 Убедитесь, что файл config.py существует и содержит BOT_TOKEN")
        exit(1)

if not API_TOKEN:
    safe_print("❌ ОШИБКА: BOT_TOKEN не найден!")
    safe_print("🔐 Проверьте переменную окружения BOT_TOKEN или файл config.py")
    exit(1)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# База данных
DB_FILE = 'users_db.json'
CHATS_FILE = 'bot_chats.json'
# основной чат, который надо исключать при массовых рассылках по чатам
# укажи явный ID, если известен, иначе бот попробует разрешить по юзернейму
MAIN_CHAT_USERNAME = 'Daisicxchat'
MAIN_CHAT_ID: int | None = None

# Система отслеживания ставок для анализа паттернов игры
roulette_bet_history = {}  # {user_id: [{'time': timestamp, 'amount': amount, 'bet_type': bet_type}, ...]}
BET_HISTORY_WINDOW = 300  # окно в 5 минут для анализа паттернов
# Счётчик подряд одинаковых ставок для точечного занижения шансов только при спаме одним и тем же
roulette_bet_streaks = {}  # {user_id: {'bet_type': str, 'streak': int}}
# Флаг обработки ставки, чтобы не обрабатывать несколько ставок одновременно
roulette_in_progress = set()  # set[user_id]



# Админы (ID пользователей)
ADMIN_IDS = {
    
    6076432444,  # выавы
    6190327518,  # хуйня  
    737300328,  # сосо
}

# Процент налога на богатство (по умолчанию 5%)
WEALTH_TAX_PERCENT = 5

# Файл для сохранения настроек налога
TAX_SETTINGS_FILE = 'tax_settings.json'

# Комиссия на переводы для топ-20 игроков (20%)
TRANSFER_COMMISSION_TOP20 = 20

# Максимально допустимая сумма вклада (1кккк)
BANK_MAX_DEPOSIT = 1_000_000_000_000_000_000_000_000

# Система промокодов
promo_codes = {}  # {code: {'reward': amount, 'activations': max_activations, 'current_activations': 0, 'expiry': timestamp, 'created_by': admin_id}}

# Система работы грузчика
loader_jobs = {}  # {user_id: {'start_time': timestamp, 'total_earnings': 0, 'cargo_count': 0}}
cargo_types = [
    # обычные грузы (80% шанс)
    {'name': 'коробки с одеждой', 'weight': 'легкий', 'time': 5, 'payment': 150000000, 'emoji': '📦'},
    {'name': 'мешки с мукой', 'weight': 'средний', 'time': 15, 'payment': 250000000, 'emoji': '🛍️'},
    {'name': 'ящики с овощами', 'weight': 'средний', 'time': 20, 'payment': 300000000, 'emoji': '🥬'},
    {'name': 'бочки с водой', 'weight': 'тяжелый', 'time': 30, 'payment': 400000000, 'emoji': '🛢️'},
    {'name': 'мебель', 'weight': 'очень тяжелый', 'time': 45, 'payment': 500000000, 'emoji': '🪑'},
    {'name': 'строительные материалы', 'weight': 'очень тяжелый', 'time': 60, 'payment': 600000000, 'emoji': '🧱'},
    
    # ценные грузы (15% шанс)
    {'name': 'электроника', 'weight': 'средний', 'time': 25, 'payment': 800000000, 'emoji': '💻', 'rare': True},
    {'name': 'медицинское оборудование', 'weight': 'тяжелый', 'time': 40, 'payment': 1000000000, 'emoji': '🏥', 'rare': True},
    {'name': 'холодильники', 'weight': 'очень тяжелый', 'time': 55, 'payment': 1200000000, 'emoji': '❄️', 'rare': True},
    
    # супер редкие грузы (5% шанс)
    {'name': 'алмазы', 'weight': 'легкий', 'time': 10, 'payment': 2000000000, 'emoji': '💎', 'super_rare': True},
    {'name': 'ювелирные изделия', 'weight': 'легкий', 'time': 8, 'payment': 2500000000, 'emoji': '💍', 'super_rare': True},
    {'name': 'золотые слитки', 'weight': 'средний', 'time': 20, 'payment': 3000000000, 'emoji': '🥇', 'super_rare': True},
    {'name': 'антиквариат', 'weight': 'средний', 'time': 35, 'payment': 3500000000, 'emoji': '🏺', 'super_rare': True},
]

def load_users():
    """Загружает пользователей из JSON файла"""
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            # Исправляем базу данных: убираем дубликаты и неправильные записи
            fixed_data = {}
            
            for user_id, user_data in data.items():
                # Конвертируем user_id в строку для единообразия
                user_id_str = str(user_id)
    
    # Пропускаем записи с неправильными никами
                if 'nick' in user_data and user_data['nick'].startswith('/'):
                    continue
                
                # Если пользователь уже есть, оставляем более полную запись
                if user_id_str in fixed_data:
                    # Сравниваем записи и оставляем ту, у которой больше полей
                    if len(user_data) > len(fixed_data[user_id_str]):
                        fixed_data[user_id_str] = user_data
                else:
                    fixed_data[user_id_str] = user_data
            
            # Убеждаемся что все пользователи имеют все необходимые поля
            for user_id, user_data in fixed_data.items():
                if 'warns' not in user_data:
                    user_data['warns'] = 0
                if 'banned' not in user_data:
                    user_data['banned'] = False
                if 'referral_earnings' not in user_data:
                    user_data['referral_earnings'] = 0
                if 'referrals' not in user_data:
                    user_data['referrals'] = 0
                if 'balance' not in user_data:
                    user_data['balance'] = 0  # 0 по умолчанию
            
            print(f"Загружено {len(fixed_data)} пользователей из БД")
            return fixed_data
    except FileNotFoundError:
        print(f"Файл {DB_FILE} не найден, создаём новую базу данных")
        return {}
    except json.JSONDecodeError as e:
        print(f"Ошибка чтения JSON файла: {e}")
        print("Создаём новую базу данных")
        return {}
    except Exception as e:
        print(f"Неожиданная ошибка при загрузке базы данных: {e}")
        return {}

def save_users():
    """сохраняет пользователей в json файл"""
    try:
        # убеждаемся что все пользователи имеют все необходимые поля перед сохранением
        for user_id, user_data in users.items():
            if 'warns' not in user_data:
                user_data['warns'] = 0
            if 'banned' not in user_data:
                user_data['banned'] = False
            if 'referral_earnings' not in user_data:
                user_data['referral_earnings'] = 0
        
        # проверяем и автоматически расширяем лимит сокращений
        auto_extend_k_limit()
        
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"ошибка сохранения базы данных: {e}")

def save_promo_codes():
    """сохраняет промокоды в JSON файл"""
    try:
        with open('promo_codes.json', 'w', encoding='utf-8') as f:
            json.dump(promo_codes, f, ensure_ascii=False, indent=2)
        print(f"✅ Промокоды сохранены: {len(promo_codes)} шт.")
    except Exception as e:
        print(f"❌ Ошибка сохранения промокодов: {e}")

def load_promo_codes():
    """загружает промокоды из JSON файла"""
    global promo_codes
    try:
        with open('promo_codes.json', 'r', encoding='utf-8') as f:
            promo_codes = json.load(f)
        print(f"✅ Промокоды загружены: {len(promo_codes)} шт.")
    except FileNotFoundError:
        print("📁 Файл promo_codes.json не найден, создаём новую базу промокодов")
        promo_codes = {}
    except Exception as e:
        print(f"❌ Ошибка загрузки промокодов: {e}, создаём новую базу")
        promo_codes = {}

def generate_random_promo():
    """генерирует случайный промокод"""
    import string
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(8))

def is_promo_valid(promo_code: str) -> bool:
    """проверяет валидность промокода"""
    if promo_code not in promo_codes:
        return False
    
    promo = promo_codes[promo_code]
    
    # проверяем количество активаций (если не бесконечно)
    if promo['activations'] != -1 and promo['current_activations'] >= promo['activations']:
        return False
    
    # проверяем срок действия
    if promo['expiry'] and datetime.datetime.now().timestamp() > promo['expiry']:
        return False
    
    return True

def activate_promo(promo_code: str, user_id: str) -> tuple[bool, str, int]:
    """активирует промокод для пользователя"""
    if not is_promo_valid(promo_code):
        return False, "промокод недействителен", 0
    
    promo = promo_codes[promo_code]
    
    # проверяем, не активировал ли пользователь уже этот промокод
    if 'used_by' not in promo:
        promo['used_by'] = []
    
    if user_id in promo['used_by']:
        return False, "ты уже использовал этот промокод", 0
    
    # активируем промокод
    promo['current_activations'] += 1
    promo['used_by'].append(user_id)
    
    # сохраняем промокоды
    save_promo_codes()
    
    return True, "промокод активирован!", promo['reward']

async def activate_promo_from_link(message: types.Message, user_id_str: str, promo_code: str):
    """активирует промокод по ссылке и показывает результат"""
    # Активируем промокод
    success, message_text, reward = activate_promo(promo_code, user_id_str)
    
    if success:
        # начисляем награду
        users[user_id_str]['balance'] += reward
        save_users()
        
        # показываем успешное сообщение
        success_text = f"🎉 <b>промокод активирован по ссылке!</b>\n\n"
        success_text += f"🎫 <b>промокод:</b> {promo_code}\n"
        success_text += f"💰 <b>награда:</b> ${format_money(reward)}\n"
        success_text += f"💳 <b>новый баланс:</b> ${format_money(users[user_id_str]['balance'])}\n\n"
        success_text += "✅ <b>награда успешно начислена на баланс!</b>"
        
        await message.answer(success_text, parse_mode='HTML')
    else:
        # показываем ошибку
        error_text = f"❌ <b>ошибка активации промокода</b>\n\n"
        error_text += f"🎫 <b>промокод:</b> {promo_code}\n"
        error_text += f"⚠️ <b>причина:</b> {message_text}\n\n"
        error_text += "💡 <b>возможные причины:</b>\n"
        error_text += "• промокод не существует\n"
        error_text += "• промокод уже использован\n"
        error_text += "• истек срок действия\n"
        error_text += "• превышен лимит активаций"
        
        await message.answer(error_text, parse_mode='HTML')
    
    # Показываем главное меню
    await show_menu(message, int(user_id_str))

def load_tax_settings():
    """Загружает настройки налога из JSON файла"""
    global WEALTH_TAX_PERCENT
    global TRANSFER_COMMISSION_TOP20
    try:
        with open(TAX_SETTINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            WEALTH_TAX_PERCENT = data.get('wealth_tax_percent', 5)
            TRANSFER_COMMISSION_TOP20 = data.get('transfer_commission_top20', TRANSFER_COMMISSION_TOP20)
            print(f"✅ Настройки налога загружены: {WEALTH_TAX_PERCENT}%")
    except FileNotFoundError:
        print(f"📁 Файл {TAX_SETTINGS_FILE} не найден, используем значение по умолчанию: 5%")
        WEALTH_TAX_PERCENT = 5
        # комиссия оставляется по умолчанию, заданному в коде
    
    except Exception as e:
        print(f"❌ Ошибка загрузки настроек налога: {e}, используем значение по умолчанию: 5%")
        WEALTH_TAX_PERCENT = 5

def save_tax_settings():
    
    """Сохраняет настройки налога в JSON файл"""
    try:
        data = {
            'wealth_tax_percent': WEALTH_TAX_PERCENT,
            'transfer_commission_top20': TRANSFER_COMMISSION_TOP20,
            'last_updated': datetime.datetime.now().isoformat()
        }
        with open(TAX_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ Настройки налога сохранены: {WEALTH_TAX_PERCENT}%")
    except Exception as e:
        print(f"❌ Ошибка сохранения настроек налога: {e}")

def create_backup():
    """Создает резервную копию базы данных"""
    try:
        # Создаем папку backup если её нет
        if not os.path.exists('backup'):
            os.makedirs('backup')
        
        # Генерируем имя файла с текущей датой и временем
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'backup/users_backup_{timestamp}.json'
        
        # Копируем текущую базу данных
        with open(DB_FILE, 'r', encoding='utf-8') as source:
            data = json.load(source)
        
        with open(backup_filename, 'w', encoding='utf-8') as target:
            json.dump(data, target, ensure_ascii=False, indent=2)
        
        print(f"✅ Резервная копия создана: {backup_filename}")
        
        # Удаляем старые резервные копии (оставляем только последние 10)
        cleanup_old_backups()
        
        return True
    except Exception as e:
        print(f"❌ Ошибка создания резервной копии: {e}")
        return False

def cleanup_old_backups():
    """Удаляет старые резервные копии, оставляя только последние 10"""
    try:
        if not os.path.exists('backup'):
            return
        
        # Получаем список всех файлов резервных копий
        backup_files = []
        for filename in os.listdir('backup'):
            if filename.startswith('users_backup_') and filename.endswith('.json'):
                file_path = os.path.join('backup', filename)
                backup_files.append((file_path, os.path.getmtime(file_path)))
        
        # Сортируем по времени создания (новые первыми)
        backup_files.sort(key=lambda x: x[1], reverse=True)
        # Удаляем старые файлы, оставляя только последние 10
        if len(backup_files) > 10:
            for file_path, _ in backup_files[10:]:
                try:
                    os.remove(file_path)
                    print(f"🗑️ Удалена старая резервная копия: {file_path}")
                except Exception as e:
                    print(f"❌ Ошибка удаления файла {file_path}: {e}")
                    
    except Exception as e:
        print(f"❌ Ошибка очистки старых резервных копий: {e}")

async def start_backup_scheduler():
    """Запускает планировщик резервного копирования каждые 30 минут"""
    print("💾 Запускаем планировщик резервного копирования...")
    
    # Флаг для предотвращения повторного запуска
    if hasattr(start_backup_scheduler, '_running'):
        print("⚠️ Планировщик резервного копирования уже запущен!")
        return
    
    start_backup_scheduler._running = True
    
    try:
        while True:
            try:
                # Создаем резервную копию
                success = create_backup()
                
                if success:
                    print(f"💾 Резервная копия создана в {datetime.datetime.now().strftime('%H:%M:%S')}")
                else:
                    print(f"❌ Ошибка создания резервной копии в {datetime.datetime.now().strftime('%H:%M:%S')}")
                
                # Ждем 30 минут (1800 секунд)
                await asyncio.sleep(1800)
                
            except Exception as e:
                print(f"❌ Ошибка в планировщике резервного копирования: {e}")
                await asyncio.sleep(60)  # ждем 1 минуту при ошибке
    finally:
        # Снимаем флаг при завершении
        start_backup_scheduler._running = False

def is_top20_player(user_id: str) -> bool:
    
    """Проверяет, является ли игрок топ-20"""
    try:
        top_20_players = get_top_players()[:20]
        return user_id in [str(uid) for uid, _ in top_20_players]
    except Exception as e:
        print(f"❌ Ошибка при проверке топ-20 игрока {user_id}: {e}")
        return False

def migrate_existing_users():
    """Мигрирует существующих пользователей, добавляя новые поля"""
    migrated_count = 0
    
    for user_id, user_data in users.items():
        # Добавляем недостающие поля
        if 'registration_date' not in user_data:
            user_data['registration_date'] = str(datetime.datetime.now())
            migrated_count += 1
        
        if 'last_activity' not in user_data:
            user_data['last_activity'] = str(datetime.datetime.now())
            migrated_count += 1
        
        if 'total_messages' not in user_data:
            user_data['total_messages'] = 0
            migrated_count += 1
        
        if 'phone_number' not in user_data:
            user_data['phone_number'] = None
            migrated_count += 1
        
        if 'email' not in user_data:
            user_data['email'] = None
            migrated_count += 1
        
        if 'age' not in user_data:
            user_data['age'] = None
            migrated_count += 1
        
        if 'city' not in user_data:
            user_data['city'] = None
            migrated_count += 1
        
        if 'country' not in user_data:
            user_data['country'] = None
            migrated_count += 1
        
        if 'language' not in user_data:
            user_data['language'] = 'ru'
            migrated_count += 1
        
        if 'device_info' not in user_data:
            user_data['device_info'] = None
            migrated_count += 1
        
        if 'ip_address' not in user_data:
            user_data['ip_address'] = None
            migrated_count += 1
        
        if 'referral_source' not in user_data:
            user_data['referral_source'] = 'direct'
            migrated_count += 1
        
        if 'account_type' not in user_data:
            user_data['account_type'] = 'regular'
            migrated_count += 1
        
        if 'verification_status' not in user_data:
            user_data['verification_status'] = 'unverified'
            migrated_count += 1
        
        if 'security_level' not in user_data:
            user_data['security_level'] = 'basic'
            migrated_count += 1
        
        if 'premium_features' not in user_data:
            user_data['premium_features'] = False
            migrated_count += 1
        
        if 'last_login' not in user_data:
            user_data['last_login'] = str(datetime.datetime.now())
            migrated_count += 1
        
        if 'login_count' not in user_data:
            user_data['login_count'] = 1
            migrated_count += 1
        
        if 'session_duration' not in user_data:
            user_data['session_duration'] = 0
            migrated_count += 1
        
        if 'last_bonus_time' not in user_data:
            user_data['last_bonus_time'] = 0
            migrated_count += 1
        
        if 'preferences' not in user_data:
            user_data['preferences'] = {
                'notifications': True,
                'privacy_mode': False,
                'auto_save': True
            }
            migrated_count += 1
        
        if 'bank_deposit' not in user_data:
            user_data['bank_deposit'] = 0
            migrated_count += 1
        
        if 'bank_deposit_time' not in user_data:
            user_data['bank_deposit_time'] = 0
            migrated_count += 1
    
    if migrated_count > 0:
        print(f"Мигрировано {migrated_count} полей для существующих пользователей")
        save_users()
    
    return migrated_count

# Загружаем пользователей при запуске
users = load_users()
safe_print("загружены пользователи")



# чаты бота (для рассылок в чаты)
def load_bot_chats() -> list[int]:
    
    try:
        with open(CHATS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return [int(x) for x in data]
    except FileNotFoundError:
        pass
    except Exception as e:
        safe_print(f"не удалось загрузить список чатов: {e}")
    return []

def save_bot_chats(chats: list[int]):
    try:
        with open(CHATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(chats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        safe_print(f"не удалось сохранить список чатов: {e}")

bot_chats: list[int] = load_bot_chats()
@dp.callback_query(lambda c: c.data in ['bc_target_dm','bc_target_chats','bc_target_chats_ex_main','bc_cancel'])
async def broadcast_target_choice(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer()
        return
    if callback.data == 'bc_cancel':
        await state.clear()
        await callback.message.edit_text('рассылку отменил')
        await callback.answer()
        return
    await state.update_data(broadcast_target=callback.data)
    
    # после выбора цели показываем инструкцию и просим текст/фото
    await callback.message.edit_text(
        '📢 рассылка\n\n'
        'отправь сообщение для рассылки всем пользователям\n\n'
        '💡 поддерживаемые HTML-теги:\n'
        '• <b>жирный текст</b> - <code>&lt;b&gt;текст&lt;/b&gt;</code>\n'
        '• <i>курсив</i> - <code>&lt;i&gt;текст&lt;/i&gt;</code>\n'
        '• <u>подчеркнутый</u> - <code>&lt;u&gt;текст&lt;/u&gt;</code>\n'
        '•  зачеркнутый ridiculous  - <code>&lt;s&gt;текст&lt;/s&gt;</code>\n'
        '• <code>моноширинный</code> - <code>&lt;code&gt;текст&lt;/code&gt;</code>\n'
        '• <a href="https://t.me/Daisicxchat">ссылка</a> - <code>&lt;a href="ссылка"&gt;текст&lt;/a&gt;</code>\n'
    
    '• <blockquote>цитата</blockquote> - <code>&lt;blockquote&gt;текст&lt;/blockquote&gt;</code>\n\n'
        '📷 для отправки с фото:\n'
        'отправь фото с подписью или просто текст\n\n'
        '❌ для отмены: напиши "отмена"\n\n'
        'а потом ещё спрошу — нужна инлайн кнопка с ссылкой или нет',
        parse_mode='HTML'
    
    )
    await state.set_state(AdminState.waiting_for_broadcast_text)
    await callback.answer()

# фиксируем чаты при событиях my_chat_member (бот добавлен/удалён)
@dp.my_chat_member()
async def on_my_chat_member(update: types.ChatMemberUpdated):
    try:
        chat_id = update.chat.id
        status = update.new_chat_member.status
        if status in ('member', 'administrator'):  # бот добавлен/есть доступ
            if chat_id not in bot_chats:
                bot_chats.append(chat_id)
                save_bot_chats(bot_chats)
        elif status in ('left', 'kicked'):  # бота выгнали/вышел
            if chat_id in bot_chats:
                bot_chats.remove(chat_id)
                save_bot_chats(bot_chats)
    except Exception as e:
        safe_print(f"ошибка обновления списка чатов: {e}")

# Мигрируем существующих пользователей
migrate_existing_users()

class RegisterState(StatesGroup):
    waiting_for_nick = State()
class AdminState(StatesGroup):
    
    waiting_for_target = State()
    waiting_for_warn_reason = State()
    
    waiting_for_warn_duration = State()
    waiting_for_ban_reason = State()
    
    waiting_for_ban_duration = State()
    waiting_for_unwarn_count = State()
    
    waiting_for_balance_amount = State()
    waiting_for_warn_date = State() # Добавляем новое состояние для даты варна
    
    waiting_for_ban_date = State() # Добавляем новое состояние для даты бана
    waiting_for_probe_target = State()
    
    waiting_for_unwarn_reason = State()
    waiting_for_unban_reason = State()
    
    waiting_for_annul_reason = State()
    waiting_for_give_amount = State()
    
    waiting_for_give_reason = State()
    waiting_for_broadcast_text = State()
    
    waiting_for_broadcast_button_decision = State()
    waiting_for_broadcast_button_data = State()
    
    waiting_for_broadcast_target = State()
    waiting_for_reset_all_balance_confirm = State()
    
    waiting_for_tax_percent = State()
    waiting_for_commission_percent = State()
    
    waiting_for_add_admin_username = State()
    waiting_for_annul_deposit_target = State()
    
    # Состояния для промокодов
    waiting_for_promo_code = State()
    waiting_for_promo_reward = State()
    waiting_for_promo_activations = State()
    waiting_for_promo_expiry_date = State()
    waiting_for_promo_expiry_time = State()

class TransferState(StatesGroup):
    waiting_for_confirmation = State()

class SettingsState(StatesGroup):
    waiting_for_new_nick = State()

class PromoState(StatesGroup):
    waiting_for_promo_input = State()

class LoaderState(StatesGroup):
    working = State()

def format_money(amount: int) -> str:
    
    # всегда пишем деньги с точками в числе
    return f"{int(amount):,}".replace(",", ".")

def update_user_activity(user_id: str):
    """Обновляет активность пользователя"""
    if user_id in users:
        users[user_id]['last_activity'] = str(datetime.datetime.now())
        users[user_id]['total_messages'] = users[user_id].get('total_messages', 0) + 1
        users[user_id]['login_count'] = users[user_id].get('login_count', 0) + 1
        users[user_id]['last_login'] = str(datetime.datetime.now())

def collect_user_info(message: types.Message, user_id: str):
    """Собирает дополнительную информацию о пользователе"""
    if user_id in users:
        user_data = users[user_id]
    
    # Обновляем время последней активности
        user_data['last_activity'] = str(datetime.datetime.now())
        
        # Собираем информацию об устройстве (если доступно)
        if hasattr(message.from_user, 'language_code'):
            user_data['language'] = message.from_user.language_code or 'ru'
        
        # Обновляем счетчик сообщений
        user_data['total_messages'] = user_data.get('total_messages', 0) + 1
        
        # Если это первое сообщение за сессию, увеличиваем счетчик входов
        last_login = user_data.get('last_login', '')
        try:
            needs_new_login = False
            if not last_login:
                needs_new_login = True
            else:
                last_dt = datetime.datetime.fromisoformat(last_login.replace('Z', '+00:00'))
                needs_new_login = (datetime.datetime.now() - last_dt).total_seconds() > 3600
            if needs_new_login:
                user_data['login_count'] = user_data.get('login_count', 0) + 1
                user_data['last_login'] = str(datetime.datetime.now())
        except Exception:
            # В случае неверного формата даты просто обновляем last_login и инкрементируем
            user_data['login_count'] = user_data.get('login_count', 0) + 1
            user_data['last_login'] = str(datetime.datetime.now())

def parse_amount(text):
    """парсит сумму из текста, поддерживает сокращения"""
    import re
    
    # проверяем специальные случаи
    if text.lower().strip() == 'все':
        return -1
    
    # убираем все кроме цифр, латиницы, кириллицы, точки и пробелов
    # (символ "k" также допустим для кратности)
    text = re.sub(r'[^0-9a-zа-я\s.]', '', text.lower())
    
    # сначала ищем обычные числа без сокращений
    simple_match = re.search(r'^(\d+(?:\.\d+)?)$', text)
    
    if simple_match:
        return int(float(simple_match.group(1)))
    
    # ищем сокращения с буквами "к" или "k" (от больших к маленьким)
    # каждая буква (к или k) умножает на 1000
    k_match = re.search(r'^(\d+(?:\.\d+)?)([кk]+)$', text)
    
    if k_match:
        number = float(k_match.group(1))
        k_count = len(k_match.group(2))
        multiplier = 1000 ** k_count
        return int(number * multiplier)
    
    # ищем другие сокращения
    patterns = [
    
    (r'(\d+(?:\.\d+)?)\s*млн', lambda m: int(float(m.group(1)) * 10**6)),                  # 100млн = 100 миллионов
        (r'(\d+(?:\.\d+)?)\s*т', lambda m: int(float(m.group(1)) * 10**3)),                    # 100т = 100 тысяч
    
    ]
    
    for pattern, converter in patterns:
        match = re.search(pattern, text)
        if match:
            return converter(match)
    
    # если ничего не найдено, пробуем обычное число
    number_match = re.search(r'(\d+(?:\.\d+)?)', text)
    
    if number_match:
        return int(float(number_match.group(1)))
    
    raise ValueError('не удалось распарсить сумму')

def auto_extend_k_limit():
    """автоматически расширяет лимит сокращений на основе максимального баланса игроков"""
    max_balance = 0
    
    # находим максимальный баланс среди всех игроков
    for user_data in users.values():
        balance = user_data.get('balance', 0)
        if balance > max_balance:
            max_balance = balance
    
    # если максимальный баланс больше 10^15 (1кккк), добавляем еще одну "к"
    if max_balance > 10**15:
        return True
    
    return False

def get_max_k_count():
    """возвращает максимальное количество букв "к" для сокращений"""
    if auto_extend_k_limit():
        return 20  # увеличиваем лимит до 20 букв "к"
    return 15  # стандартный лимит 15 букв "к"

def extract_username(text: str) -> str:
    t = text.strip()
    
    if 't.me/' in t:
        t = t.split('t.me/')[-1]
    
    if t.startswith('@'):
        t = t[1:]
    
    t = re.sub(r'[^\w_]', '', t)
    return t.lower()

async def generate_referral_link(user_id: int) -> str:
    """Генерирует реферальную ссылку"""
    bot_info = await bot.get_me()
    
    bot_username = bot_info.username
    return f"https://t.me/{bot_username}?start=ref{user_id}"

def get_random_referral_bonus() -> int:
    
    """Генерирует рандомный приз от 50кк до 150кк"""
    min_bonus = 50_000_000  # 50кк = 50 миллионов
    
    max_bonus = 150_000_000  # 150кк = 150 миллионов
    return random.randint(min_bonus, max_bonus)

def get_milestone_bonus(referral_count: int) -> int:
    """Возвращает бонус за достижение определённого количества рефералов"""
    if referral_count == 10:
        return 10_000_000_000  # 10ккк = 10 миллиардов
    
    elif referral_count == 25:
        return 10_000_000_000  # 10ккк = 10 миллиардов
    
    elif referral_count == 50:
        return 30_000_000_000  # 30ккк = 30 миллиардов
    
    return 0

async def show_menu(message: types.Message, user_id: int, state: FSMContext = None):
    """показывает меню пользователя"""
    user_id_str = str(user_id)  # конвертируем в строку для сравнения
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # очищаем работу грузчика при выходе в меню
    if user_id_str in loader_jobs:
        del loader_jobs[user_id_str]
        print(f"🔄 Пользователь {user_id_str} вышел из работы грузчика")
    
    # очищаем состояние FSM если передано
    if state:
        try:
            await state.clear()
            print(f"🔄 Очищено состояние FSM для пользователя {user_id_str}")
        except:
            pass
    
    # проверяем, существует ли пользователь в базе данных
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    user_data = users[user_id_str]
    
    # проверяем, есть ли у пользователя ник (зарегистрирован ли он)
    if 'nick' not in user_data:
        await show_not_registered_message(message)
        return
    
    # проверяем, не забанен ли пользователь
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_date = user_data.get('ban_date', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n"
            f"📅 <b>дата блокировки:</b> {ban_date}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
    
    reply_markup=markup
        )
        return
    
    balance = user_data.get('balance', 0)
    
    nick = user_data.get('nick', 'неизвестно')
    
    menu_text = f"привет, <a href=\"tg://user?id={user_id}\"><b>{nick}</b></a>\nу тебя на счету — <b>${format_money(balance)}</b>"
    
    # показываем кнопки только в личных сообщениях
    if message.chat.type == 'private':
        markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
            [KeyboardButton(text='💼 работа'), KeyboardButton(text='💰 бонус')],
            [KeyboardButton(text='🏦 банк'), KeyboardButton(text='🎮 игры')],
            [KeyboardButton(text='🏆'), KeyboardButton(text='🎫 промокоды')],
            [KeyboardButton(text='⚙️ настройки')]
        ])
        
        # пробуем отправить картинку с приветствием
        try:
            image_paths = [
    
    'img/plyer_default.jpg',
                './img/plyer_default.jpg',
                'C:/Users/User/Desktop/dodeper bot/img/plyer_default.jpg'
            ]
            
            image_sent = False
            
            for image_path in image_paths:
                try:
                    if os.path.exists(image_path):
                        await bot.send_photo(
                            message.chat.id,
                            types.FSInputFile(image_path),
                            caption=menu_text,
                            parse_mode='HTML',
                            reply_markup=markup
                        )
                        image_sent = True
                        break
                except Exception as e:
                    continue
            
            if not image_sent:
                await message.answer(menu_text, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            await message.answer(menu_text, parse_mode='HTML', reply_markup=markup)
    
    else:
        # в чатах тоже пробуем картинку
        try:
            image_paths = [
    
    'img/plyer_default.jpg',
                './img/plyer_default.jpg',
                'C:/Users/User/Desktop/dodeper bot/img/plyer_default.jpg'
            ]
            
            print(f"🔍 Пытаюсь отправить картинку в чат для пользователя {user_id}")
            image_sent = False
            
            for image_path in image_paths:
                try:
                    print(f"📁 Проверяю путь в чате: {image_path}")
                    if os.path.exists(image_path):
                        print(f"✅ Файл найден в чате: {image_path}")
                        await bot.send_photo(
                            message.chat.id,
                            types.FSInputFile(image_path),
                            caption=menu_text,
                            parse_mode='HTML'
                        )
                        print(f"📸 Картинка в чате отправлена успешно!")
                        image_sent = True
                        break
                    else:
                        print(f"❌ Файл не найден в чате: {image_path}")
                except Exception as e:
                    print(f"⚠️ Ошибка при отправке картинки в чате {image_path}: {e}")
                    continue
            
            if not image_sent:
                print(f"📝 Картинка в чате не отправлена, отправляю только текст")
                await message.answer(menu_text, parse_mode='HTML')
        except Exception as e:
            print(f"💥 Общая ошибка при отправке картинки в чате: {e}")
            await message.answer(menu_text, parse_mode='HTML')

async def show_work_menu(message: types.Message, user_id: int):
    
    """показывает меню работы"""
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    menu_text = '💼 <b>раздел работа</b>\n\nздесь ты можешь заработать деньги разными способами'
    
    # показываем кнопки только в личных сообщениях
    if message.chat.type == 'private':
        markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
            [KeyboardButton(text='рефералы 👥')],
            [KeyboardButton(text='📦 работа грузчика')],
            [KeyboardButton(text='назад ⬅️')]
        ])
        
        await message.answer(menu_text, parse_mode='HTML', reply_markup=markup)
    
    else:
        await message.answer(menu_text, parse_mode='HTML')

async def show_bonus_menu(message: types.Message, user_id: int):
    
    """показывает меню бонусов"""
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    user_data = users[user_id_str]
    
    nick = user_data.get('nick', 'игрок')
    
    # проверяем время последнего бонуса
    last_bonus_time = user_data.get('last_bonus_time', 0)
    
    current_time = datetime.datetime.now().timestamp()
    time_diff = current_time - last_bonus_time
    
    # 5 минут = 300 секунд
    if time_diff >= 300:
        # можно забрать бонус
        markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='✅ забрать бонус', callback_data='claim_bonus')]
        ])
        
        await message.answer(
            f'<b>{nick}</b>, здесь ты можешь забирать бонус каждые <b>5 минут</b>\n\nсумма бонуса может быть от <b>1ккк</b> до <b>10ккк</b>',
            parse_mode='HTML',
    
    reply_markup=markup
        )
    else:
        # еще рано
        remaining_time = 300 - time_diff
        
        minutes = int(remaining_time // 60)
        seconds = int(remaining_time % 60)
        
        time_text = f'<b>{minutes}:{seconds:02d}</b>'
        
        await message.answer(
            f'❌ ты не можешь забрать бонус! осталось времени <b>{time_text}</b> до бонуса',
            parse_mode='HTML'
        )

async def show_referrals_menu(message: types.Message, user_id: int):
    """показывает меню рефералов"""
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    user_data = users[user_id_str]
    
    referral_count = user_data.get('referrals', 0)
    total_earned = user_data.get('referral_earnings', 0)
    
    referral_link = await generate_referral_link(user_id)
    
    # показываем кнопки только в личных сообщениях
    if message.chat.type == 'private':
        markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='назад ⬅️')]
        ])
        await message.answer(
            f'👥 <b>реферальная система</b>\n\n📊 твоя статистика:\n• приглашено людей: <b>{referral_count}</b>\n• заработано: <b>${format_money(total_earned)}</b>\n\n💰 <b>как работает:</b>\n1. скопируй свою реферальную ссылку\n2. отправь её в чат\n3. когда человек перейдёт по ссылке и зарегистрируется\n4. ты получишь рандомный приз от <b>$50.000.000</b> до <b>$150.000.000</b>\n\n🏆 <b>бонусы за достижения:</b>\n• 10 рефералов: <b>$10.000.000.000</b> (10ккк)\n• 25 рефералов: <b>$10.000.000.000</b> (10ккк)\n• 50 рефералов: <b>$30.000.000.000</b> (30ккк)\n\n🔗 <b>твоя ссылка:</b>\n<code>{referral_link}</code>',
            parse_mode='HTML',
    
    reply_markup=markup
        )
    else:
        await message.answer(
            f'👥 <b>реферальная система</b>\n\n'
            f'📊 твоя статистика:\n'
            f'• приглашено людей: <b>{referral_count}</b>\n'
            f'• заработано: <b>${format_money(total_earned)}</b>\n\n'
            f'💰 <b>как работает:</b>\n'
            f'1. скопируй свою реферальную ссылку\n'
            f'2. отправь её в чат\n'
            f'3. когда человек перейдёт по ссылке и зарегистрируется\n'
            f'4. ты получишь рандомный приз от <b>$50.000.000</b> до <b>$150.000.000</b>\n\n'
            f'🏆 <b>бонусы за достижения:</b>\n'
            f'• 10 рефералов: <b>$10.000.000.000</b> (10ккк)\n'
            f'• 25 рефералов: <b>$10.000.000.000</b> (10ккк)\n'
            f'• 50 рефералов: <b>$30.000.000.000</b> (30ккк)\n\n'
            f'🔗 <b>твоя ссылка:</b>\n<code>{referral_link}</code>',
            parse_mode='HTML'
    
    )

async def show_games_menu(message: types.Message, user_id: int):
    """показывает меню игр"""
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # показываем кнопки только в личных сообщениях
    if message.chat.type == 'private':
        markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='рулетка 🎰'), KeyboardButton(text='кости 🎲')],
            [KeyboardButton(text='баскетбол 🏀')],
    
    [KeyboardButton(text='назад ⬅️')]
        ])
        await message.answer(
            '🎮 <b>раздел игры</b>\n\nздесь ты можешь играть в разные игры и выигрывать деньги\n\n⚠️ <b>важно:</b> игры работают только в чатах!\n\n💡 <b>подсказка:</b> нажми на любую игру, чтобы узнать подробности и команды',
            parse_mode='HTML',
    
    reply_markup=markup
        )
    else:
        await message.answer(
            '🎮 <b>раздел игры</b>\n\nздесь ты можешь играть в разные игры и выигрывать деньги\n\n⚠️ <b>важно:</b> игры работают только в чатах!\n\n💡 <b>подсказка:</b> нажми на любую игру, чтобы узнать подробности и команды',
            parse_mode='HTML'
    
    )

async def show_bank_menu(message: types.Message, user_id: int):
    """показывает меню банка"""
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    user_data = users[user_id_str]
    
    balance = user_data.get('balance', 0)
    deposit = user_data.get('bank_deposit', 0)
    
    deposit_time = user_data.get('bank_deposit_time', 0)
    
    # рассчитываем проценты
    current_time = datetime.datetime.now().timestamp()
    
    hours_passed = 0
    total_interest = 0
    
    can_withdraw = False
    
    if deposit > 0 and deposit_time > 0:
        hours_passed = (current_time - deposit_time) / 3600  # часы
    
    # максимум 24 часа для 10%
        hours_passed = min(hours_passed, 24)
    
    # 10% за 24 часа = 0.4167% за час
        total_interest = int(deposit * 0.004167 * hours_passed)
    
    # можно снять только через 24 часа
        can_withdraw = (current_time - deposit_time) >= 86400  # 24 часа в секундах
    
    # показываем кнопки только в личных сообщениях
    if message.chat.type == 'private':
        markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='💰 положить деньги', callback_data='bank_deposit')],
            [InlineKeyboardButton(text='💸 забрать деньги', callback_data='bank_withdraw')],
    
    [InlineKeyboardButton(text='📊 информация о вкладе', callback_data='bank_info')]
        ])
        
        bank_text = f'🏦 <b>банк</b>\n\n'
    
        bank_text += f'💳 <b>твой баланс:</b> <b>${format_money(balance)}</b>\n'
        
        if deposit > 0:
            hours_passed_int = int(hours_passed)
            minutes_passed_int = int((hours_passed - hours_passed_int) * 60)
            bank_text += f'💰 <b>вклад:</b> <b>${format_money(deposit)}</b>\n'
            bank_text += f'⏰ <b>время вклада:</b> <b>{hours_passed_int}ч {minutes_passed_int}м</b>\n'
            bank_text += f'💎 <b>накопленные проценты:</b> <b>${format_money(total_interest)}</b>\n'
            if can_withdraw:
                bank_text += f'✅ <b>можно забрать деньги</b>\n\n'
            else:
                remaining_time = 86400 - (current_time - deposit_time)
                
                remaining_hours = int(remaining_time // 3600)
                remaining_minutes = int((remaining_time % 3600) // 60)
                
                bank_text += f'⏳ <b>до снятия:</b> <b>{remaining_hours}ч {remaining_minutes}м</b>\n\n'
        else:
            bank_text += f'💰 <b>вклад:</b> <b>нет активного вклада</b>\n\n'
        
        bank_text += '💡 <b>как работает:</b>\n'
        bank_text += '• положи деньги во вклад\n'
        bank_text += '• проценты начисляются 24 часа (10%)\n'
        bank_text += '• снять деньги можно только через сутки\n'
        bank_text += '• при досрочном снятии - штраф без процентов\n\n'
        bank_text += '⚠️ <b>важно:</b> вклад заблокирован на 24 часа!'
        
        await message.answer(bank_text, parse_mode='HTML', reply_markup=markup)
    
    else:
        bank_text = f'🏦 <b>банк</b>\n\n'
    
        bank_text += f'💳 <b>твой баланс:</b> <b>${format_money(balance)}</b>\n'
        
        if deposit > 0:
            hours_passed_int = int(hours_passed)
    
            minutes_passed_int = int((hours_passed - hours_passed_int) * 60)
            bank_text += f'💰 <b>вклад:</b> <b>${format_money(deposit)}</b>\n'
            bank_text += f'⏰ <b>время вклада:</b> <b>{hours_passed_int}ч {minutes_passed_int}м</b>\n'
            bank_text += f'💎 <b>накопленные проценты:</b> <b>${format_money(total_interest)}</b>\n'
            if can_withdraw:
                bank_text += f'✅ <b>можно забрать деньги</b>\n\n'
            else:
                remaining_time = 86400 - (current_time - deposit_time)
                
                remaining_hours = int(remaining_time // 3600)
                remaining_minutes = int((remaining_time % 3600) // 60)
    
                bank_text += f'⏳ <b>до снятия:</b> <b>{remaining_hours}ч {remaining_minutes}м</b>\n\n'
        else:
            bank_text += f'💰 <b>вклад:</b> <b>нет активного вклада</b>\n\n'
        
        bank_text += '💡 <b>как работает:</b>\n'
        bank_text += '• положи деньги во вклад\n'
        bank_text += '• проценты начисляются 24 часа (10%)\n'
        bank_text += '• снять деньги можно только через сутки\n'
        bank_text += '• при досрочном снятии - штраф без процентов\n\n'
        bank_text += '⚠️ <b>важно:</b> вклад заблокирован на 24 часа!'
        
        await message.answer(bank_text, parse_mode='HTML')

# === ФУНКЦИИ РАБОТЫ ГРУЗЧИКА ===

async def start_loader_work(message: types.Message, user_id_str: str, state: FSMContext):
    """начинает работу грузчика"""
    # проверяем, не начал ли уже работу
    if user_id_str in loader_jobs:
        await message.answer('⚠️ ты уже работаешь грузчиком! сначала закончи текущую смену')
        return
    
    # инициализируем работу
    loader_jobs[user_id_str] = {
        'start_time': datetime.datetime.now().timestamp(),
        'total_earnings': 0,
        'cargo_count': 0,
        'current_cargo': None,
        'cargo_accepted': False,
        'cargo_rejected': False
    }
    
    # устанавливаем состояние
    await state.set_state(LoaderState.working)
    
    # отправляем первое сообщение о работе
    await send_cargo_message(message, user_id_str)
async def send_cargo_message(message: types.Message, user_id_str: str):
    """отправляет сообщение о новом грузе"""
    if user_id_str not in loader_jobs:
        return
    
    # проверяем, не отправляется ли уже груз
    if loader_jobs[user_id_str].get('sending_cargo', False):
        print(f"⚠️ Груз уже отправляется для {user_id_str}, пропускаем")
        return
    
    # помечаем, что отправляем груз
    loader_jobs[user_id_str]['sending_cargo'] = True
    
    try:
        # показываем поиск груза
        search_text = "🔍 ищу новый груз..."
        search_msg = await message.answer(search_text, parse_mode='HTML')
        
        # рандомное время поиска (1-3 секунды)
        import random
        search_time = random.uniform(1, 3)
        await asyncio.sleep(search_time)
        
        # удаляем сообщение о поиске
        try:
            await search_msg.delete()
        except:
            pass
        
        # выбираем случайный груз
        cargo = select_random_cargo()
        
        # сохраняем текущий груз и очищаем флаги
        loader_jobs[user_id_str]['current_cargo'] = cargo
        loader_jobs[user_id_str]['cargo_accepted'] = False
        loader_jobs[user_id_str]['cargo_rejected'] = False
        
        # создаем текст сообщения
        cargo_text = f"📦 <b>найден груз!</b>\n\n"
        cargo_text += f"🎯 <b>груз:</b> {cargo['emoji']} {cargo['name']}\n"
        cargo_text += f"⚖️ <b>вес:</b> {cargo['weight']}\n"
        cargo_text += f"⏱️ <b>время переноса:</b> {cargo['time']} сек\n"
        cargo_text += f"💰 <b>оплата:</b> ${format_money(cargo['payment'])}\n\n"
        
        if cargo.get('super_rare'):
            cargo_text += "💎 <b>СУПЕР РЕДКИЙ ГРУЗ!</b>\n"
        elif cargo.get('rare'):
            cargo_text += "⭐ <b>редкий груз!</b>\n"
        
        cargo_text += "\n🤔 будешь брать этот груз?"
        
        # создаем инлайн клавиатуру
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✅ принять', callback_data='cargo_accept'), 
             InlineKeyboardButton(text='❌ отказаться', callback_data='cargo_reject')]
        ])
        
        # отправляем сообщение
        cargo_msg = await message.answer(cargo_text, parse_mode='HTML', reply_markup=markup)
        
        # сохраняем ID сообщения для удаления и удалим предыдущее при наличии
        try:
            prev_msg_id = loader_jobs[user_id_str].get('current_message_id')
            if prev_msg_id:
                await bot.delete_message(message.chat.id, prev_msg_id)
        except:
            pass
        loader_jobs[user_id_str]['current_message_id'] = cargo_msg.message_id
        
    except Exception as e:
        print(f"❌ Ошибка при отправке груза для {user_id_str}: {e}")
    finally:
        # сбрасываем флаг отправки груза
        if user_id_str in loader_jobs:
            loader_jobs[user_id_str]['sending_cargo'] = False

def select_random_cargo():
    """выбирает случайный груз с учетом редкости"""
    import random
    
    # определяем тип груза по вероятности
    rand = random.random()
    
    if rand < 0.008:  # 0.8% - супер редкие (было 5%)
        rare_cargos = [c for c in cargo_types if c.get('super_rare')]
        return random.choice(rare_cargos) if rare_cargos else cargo_types[0]
    elif rand < 0.035:  # 2.7% - редкие (было 15%)
        rare_cargos = [c for c in cargo_types if c.get('rare')]
        return random.choice(rare_cargos) if rare_cargos else cargo_types[0]
    else:  # 96.5% - обычные (было 80%)
        normal_cargos = [c for c in cargo_types if not c.get('rare') and not c.get('super_rare')]
        return random.choice(normal_cargos) if normal_cargos else cargo_types[0]

async def cargo_timer(chat_id: int, user_id_str: str, time_seconds: int):
    """таймер для завершения переноса груза"""
    await asyncio.sleep(time_seconds)
    
    if user_id_str not in loader_jobs:
        return
    
    # завершаем перенос груза
    await complete_cargo_delivery(chat_id, user_id_str)

async def complete_cargo_delivery(chat_id: int, user_id_str: str):
    """завершает доставку груза и начисляет оплату"""
    if user_id_str not in loader_jobs:
        return
    
    job = loader_jobs[user_id_str]
    cargo = job.get('current_cargo')
    
    if not cargo:
        return
    
    # начисляем оплату
    payment = cargo['payment']
    job['total_earnings'] += payment
    job['cargo_count'] += 1
    
    # обновляем баланс пользователя
    if user_id_str in users:
        users[user_id_str]['balance'] += payment
        save_users()
    
    # удаляем сообщение о переносе
    try:
        await bot.delete_message(chat_id, job.get('delivery_message_id', 0))
    except:
        pass
    
    # создаем сообщение о доставке груза
    delivery_text = f"✅ <b>груз доставлен!</b>\n\n"
    delivery_text += f"📦 {cargo['emoji']} {cargo['name']}\n"
    delivery_text += f"💰 <b>получено:</b> ${format_money(payment)}\n\n"
    
    if cargo.get('super_rare'):
        delivery_text += "💎 <b>СУПЕР РЕДКИЙ ГРУЗ ДОСТАВЛЕН!</b>\n"
    elif cargo.get('rare'):
        delivery_text += "⭐ <b>редкий груз доставлен!</b>\n"
    
    # удаляем предыдущее сообщение с грузом/статусом и отправляем новое
    try:
        prev_msg_id = job.get('current_message_id')
        if prev_msg_id:
            await bot.delete_message(chat_id, prev_msg_id)
    except:
        pass
    try:
        delivery_msg = await bot.send_message(chat_id, delivery_text, parse_mode='HTML')
        job['current_message_id'] = delivery_msg.message_id
    except:
        pass
    
    # создаем отдельное сообщение со статистикой
    stats_text = f"📊 <b>статистика смены:</b>\n"
    stats_text += f"• грузов доставлено: {job['cargo_count']}\n"
    stats_text += f"• общий заработок: ${format_money(job['total_earnings'])}\n\n"
    stats_text += "🔄 ищем новый груз..."
    
    # отправляем сообщение со статистикой, предварительно удаляя предыдущее
    try:
        prev_msg_id = job.get('current_message_id')
        if prev_msg_id:
            await bot.delete_message(chat_id, prev_msg_id)
    except:
        pass
    try:
        stats_msg = await bot.send_message(chat_id, stats_text, parse_mode='HTML')
        job['current_message_id'] = stats_msg.message_id
    except:
        pass
    
    # очищаем текущий груз и флаги
    job['current_cargo'] = None
    job['cargo_accepted'] = False
    job['cargo_rejected'] = False
    
    # отправляем новый груз через 2 секунды
    await asyncio.sleep(2)
    if user_id_str in loader_jobs:
        await send_cargo_message_via_bot(chat_id, user_id_str)

async def send_cargo_message_via_bot(chat_id: int, user_id_str: str):
    """отправляет сообщение о новом грузе через бота"""
    if user_id_str not in loader_jobs:
        return
    
    # проверяем, не отправляется ли уже груз
    if loader_jobs[user_id_str].get('sending_cargo', False):
        print(f"⚠️ Груз уже отправляется для {user_id_str}, пропускаем")
        return
    
    # помечаем, что отправляем груз
    loader_jobs[user_id_str]['sending_cargo'] = True
    
    try:
        # показываем поиск груза
        search_text = "🔍 ищу новый груз..."
        search_msg = await bot.send_message(chat_id, search_text, parse_mode='HTML')
        
        # рандомное время поиска (1-3 секунды)
        import random
        search_time = random.uniform(1, 3)
        await asyncio.sleep(search_time)
        
        # удаляем сообщение о поиске
        try:
            await bot.delete_message(chat_id, search_msg.message_id)
        except:
            pass
        
        # выбираем случайный груз
        cargo = select_random_cargo()
        
        # сохраняем текущий груз и очищаем флаги
        loader_jobs[user_id_str]['current_cargo'] = cargo
        loader_jobs[user_id_str]['cargo_accepted'] = False
        loader_jobs[user_id_str]['cargo_rejected'] = False
        
        # создаем текст сообщения
        cargo_text = f"📦 <b>найден груз!</b>\n\n"
        cargo_text += f"🎯 <b>груз:</b> {cargo['emoji']} {cargo['name']}\n"
        cargo_text += f"⚖️ <b>вес:</b> {cargo['weight']}\n"
        cargo_text += f"⏱️ <b>время переноса:</b> {cargo['time']} сек\n"
        cargo_text += f"💰 <b>оплата:</b> ${format_money(cargo['payment'])}\n\n"
        
        if cargo.get('super_rare'):
            cargo_text += "💎 <b>СУПЕР РЕДКИЙ ГРУЗ!</b>\n"
        elif cargo.get('rare'):
            cargo_text += "⭐ <b>редкий груз!</b>\n"
        
        # рандомное время на принятие груза (5-30 секунд)
        accept_time = random.randint(5, 30)
        
        cargo_text += "\n🤔 будешь брать этот груз?"
        
        # создаем инлайн клавиатуру
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✅ принять', callback_data='cargo_accept'), 
             InlineKeyboardButton(text='❌ отказаться', callback_data='cargo_reject')]
        ])
        
        # отправляем сообщение
        cargo_msg = await bot.send_message(chat_id, cargo_text, parse_mode='HTML', reply_markup=markup)
        
        # сохраняем ID сообщения для удаления и удалим предыдущее при наличии
        try:
            prev_msg_id = loader_jobs[user_id_str].get('current_message_id')
            if prev_msg_id:
                await bot.delete_message(chat_id, prev_msg_id)
        except:
            pass
        loader_jobs[user_id_str]['current_message_id'] = cargo_msg.message_id
        
        # сохраняем время принятия груза
        loader_jobs[user_id_str]['cargo_accept_time'] = accept_time
        loader_jobs[user_id_str]['cargo_available_until'] = datetime.datetime.now().timestamp() + accept_time
        
        # запускаем таймер на принятие груза
        asyncio.create_task(cargo_accept_timer(chat_id, user_id_str, accept_time))
        
    except Exception as e:
        print(f"❌ Ошибка при отправке груза для {user_id_str}: {e}")
    finally:
        # сбрасываем флаг отправки груза
        if user_id_str in loader_jobs:
            loader_jobs[user_id_str]['sending_cargo'] = False

async def cargo_accept_timer(chat_id: int, user_id_str: str, accept_time: int):
    """таймер для принятия груза"""
    print(f"🚀 Таймер запущен для {user_id_str}, время: {accept_time} сек")
    
    await asyncio.sleep(accept_time)
    
    print(f"⏰ Таймер истек для {user_id_str}")
    
    if user_id_str not in loader_jobs:
        print(f"❌ Пользователь {user_id_str} не найден в loader_jobs")
        return
    
    job = loader_jobs[user_id_str]
    
    # проверяем, не был ли груз уже принят или отклонен
    if ('cargo_accepted' in job and job['cargo_accepted']) or ('cargo_rejected' in job and job['cargo_rejected']):
        print(f"✅ Груз уже обработан пользователем {user_id_str}")
        return
    
    print(f"❌ Груз не был принят пользователем {user_id_str}")
    
    # груз не был принят вовремя
    cargo = job.get('current_cargo')
    if not cargo:
        print(f"❌ Груз не найден для пользователя {user_id_str}")
        return
    
    print(f"📦 Отправляем сообщение о том, что груз взял другой игрок для {user_id_str}")
    
    # удаляем сообщение с грузом
    try:
        await bot.delete_message(chat_id, job.get('current_message_id', 0))
        print(f"🗑️ Сообщение с грузом удалено для {user_id_str}")
    except Exception as e:
        print(f"❌ Ошибка при удалении сообщения: {e}")
    
    # отправляем сообщение о том, что груз взял другой игрок
    timeout_text = f"❌ <b>ты не успел!</b>\n\n"
    timeout_text += f"📦 {cargo['emoji']} {cargo['name']}\n"
    timeout_text += f"💰 <b>оплата:</b> ${format_money(cargo['payment'])}\n\n"
    timeout_text += "😔 <b>груз взял другой игрок</b>"
    
    try:
        # удаляем предыдущее сообщение
        try:
            prev_msg_id = job.get('current_message_id')
            if prev_msg_id:
                await bot.delete_message(chat_id, prev_msg_id)
        except:
            pass
        timeout_msg = await bot.send_message(chat_id, timeout_text, parse_mode='HTML')
        job['current_message_id'] = timeout_msg.message_id
        print(f"✅ Сообщение о том, что груз взял другой игрок отправлено для {user_id_str}")
    except Exception as e:
        print(f"❌ Ошибка при отправке сообщения: {e}")
    
    # очищаем текущий груз и флаги
    job['current_cargo'] = None
    job['cargo_accepted'] = False
    job['cargo_rejected'] = False
    
    # ищем новый груз через 2 секунды
    await asyncio.sleep(2)
    if user_id_str in loader_jobs:
        print(f"🔄 Ищем новый груз для {user_id_str}")
        await send_cargo_message_via_bot(chat_id, user_id_str)

async def finish_loader_work(chat_id: int, user_id_str: str):
    """завершает работу грузчика и выдает итоговую оплату"""
    if user_id_str not in loader_jobs:
        return
    
    job = loader_jobs[user_id_str]
    
    # рассчитываем время работы
    work_time = datetime.datetime.now().timestamp() - job['start_time']
    hours = int(work_time // 3600)
    minutes = int((work_time % 3600) // 60)
    seconds = int(work_time % 60)
    
    # создаем итоговое сообщение
    final_text = f"🏁 <b>смена завершена!</b>\n\n"
    final_text += f"⏱️ <b>время работы:</b> {hours:02d}:{minutes:02d}:{seconds:02d}\n"
    final_text += f"📦 <b>грузов доставлено:</b> {job['cargo_count']}\n"
    final_text += f"💰 <b>общий заработок:</b> ${format_money(job['total_earnings'])}\n\n"
    
    if job['cargo_count'] > 0:
        avg_per_cargo = job['total_earnings'] // job['cargo_count']
        final_text += f"📊 <b>средняя оплата за груз:</b> ${format_money(avg_per_cargo)}\n\n"
    
    final_text += "✅ <b>все деньги начислены на баланс!</b>"
    
    # отправляем итоговое сообщение
    await bot.send_message(chat_id, final_text, parse_mode='HTML')
    
    # очищаем работу
    del loader_jobs[user_id_str]

# === КОЛЛБЭКИ ДЛЯ РАБОТЫ ГРУЗЧИКА ===

@dp.callback_query(lambda c: c.data == 'cargo_accept')
async def cargo_accept_callback(callback: types.CallbackQuery):
    """обработчик принятия груза"""
    user_id = callback.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in loader_jobs:
        await callback.answer("ты не работаешь грузчиком", show_alert=True)
        return
    
    job = loader_jobs[user_id_str]
    cargo = job.get('current_cargo')
    
    if not cargo:
        await callback.answer("груз не найден", show_alert=True)
        return
    
    # проверяем, не принят ли уже груз
    if job.get('cargo_accepted', False):
        await callback.answer("груз уже принят!", show_alert=True)
        return
    
    # проверяем, не отклонен ли груз
    if job.get('cargo_rejected', False):
        await callback.answer("груз уже отклонен!", show_alert=True)
        return
    
    # проверяем, не истекло ли время
    current_time = datetime.datetime.now().timestamp()
    if 'cargo_available_until' in job and current_time > job['cargo_available_until']:
        print(f"⏰ Время истекло для {user_id_str}, груз уже недоступен")
        await callback.answer("время истекло! груз взял другой игрок", show_alert=True)
        return
    
    print(f"✅ Груз принят пользователем {user_id_str}")
    # помечаем груз как принятый
    job['cargo_accepted'] = True
    
    # удаляем сообщение с выбором груза
    try:
        await callback.message.delete()
    except:
        pass
    
    # создаем сообщение о начале переноса
    delivery_text = f"📦 <b>начинаю перенос груза!</b>\n\n"
    delivery_text += f"🎯 <b>груз:</b> {cargo['emoji']} {cargo['name']}\n"
    delivery_text += f"⏱️ <b>время переноса:</b> {cargo['time']} сек\n"
    delivery_text += f"💰 <b>оплата:</b> ${format_money(cargo['payment'])}\n\n"
    delivery_text += "⏳ переносим груз..."
    
    # создаем клавиатуру с кнопкой закончить работу
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='🏁 закончить работу')]
    ])
    
    # отправляем сообщение о переносе
    delivery_msg = await callback.message.answer(delivery_text, parse_mode='HTML', reply_markup=markup)
    
    # сохраняем ID сообщения о переносе
    loader_jobs[user_id_str]['delivery_message_id'] = delivery_msg.message_id
    
    # запускаем таймер
    asyncio.create_task(cargo_timer(callback.message.chat.id, user_id_str, cargo['time']))
    
    await callback.answer("груз принят!")

@dp.callback_query(lambda c: c.data == 'cargo_reject')
async def cargo_reject_callback(callback: types.CallbackQuery):
    """обработчик отказа от груза"""
    user_id = callback.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in loader_jobs:
        await callback.answer("ты не работаешь грузчиком", show_alert=True)
        return
    
    job = loader_jobs[user_id_str]
    
    # проверяем, не принят ли уже груз
    if job.get('cargo_accepted', False):
        await callback.answer("груз уже принят!", show_alert=True)
        return
    
    # проверяем, не отклонен ли груз
    if job.get('cargo_rejected', False):
        await callback.answer("груз уже отклонен!", show_alert=True)
        return
    
    # проверяем, не истекло ли время
    current_time = datetime.datetime.now().timestamp()
    if 'cargo_available_until' in job and current_time > job['cargo_available_until']:
        await callback.answer("время истекло! груз взял другой игрок", show_alert=True)
        return
    
    # помечаем груз как отклоненный (чтобы таймер не сработал)
    job['cargo_rejected'] = True
    
    # удаляем сообщение с отказом
    try:
        await callback.message.delete()
    except:
        pass
    
    # ищем новый груз
    await send_cargo_message_via_bot(callback.message.chat.id, user_id_str)
    
    await callback.answer("ищу новый груз...")

async def show_not_registered_message(message: types.Message):
    
    """показывает сообщение для незарегистрированных пользователей в групповых чатах"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    keyboard = InlineKeyboardBuilder()
    
    keyboard.button(text="создать человечка", callback_data="create_human")
    await message.answer(
        'ты не зарегистрирован в боте',
        reply_markup=keyboard.as_markup()
    
    )

@dp.message(Command('start'))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Парсим аргументы команды для реферальной системы и промокодов
    args = message.text.split()
    
    referral_id = None
    promo_code = None
    
    if len(args) > 1:
        for arg in args[1:]:
            # Ищем реферальный ID в формате ref<id>
            if arg.startswith('ref'):
                try:
                    referral_id = int(arg[3:])
                except ValueError:
                    continue
            # Ищем промокод в формате promo_<code>
            elif arg.startswith('promo_'):
                promo_code = arg[6:]  # убираем 'promo_' префикс
    
    # Проверяем, зарегистрирован ли пользователь
    is_registered = user_id_str in users and 'nick' in users.get(user_id_str, {})
    
    if is_registered:
        # Пользователь уже зарегистрирован
        user_data = users[user_id_str]
        
        # Если пользователь пришёл по реферальной ссылке, сохраняем реферера
        if referral_id and str(referral_id) in users:
            users[user_id_str]['temp_referrer'] = referral_id
            users[user_id_str]['temp_referral_date'] = str(datetime.datetime.now())
            save_users()
        
        # Если пользователь пришёл по ссылке с промокодом, активируем его
        if promo_code:
            await activate_promo_from_link(message, user_id_str, promo_code)
        else:
            await show_menu(message, user_id)
        return
    
    # Пользователь не зарегистрирован - показываем регистрацию
    # сохраняем реферала временно
    if referral_id and str(referral_id) in users:
        if user_id_str not in users:
            users[user_id_str] = {}
        users[user_id_str]['temp_referrer'] = referral_id
        users[user_id_str]['temp_referral_date'] = str(datetime.datetime.now())
        save_users()
    
    if message.chat.type == 'private':
        markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[[KeyboardButton(text='зарегистрироваться ✅')]])
        try:
            # пробуем разные пути к картинке
            image_paths = [
                'img/plyer_default.jpg',
                './img/plyer_default.jpg',
                'img/player_default.jpg',
                './img/player_default.jpg',
                'C:/Users/User/Desktop/dodeper bot/img/plyer_default.jpg',
                'C:/Users/User/Desktop/dodeper bot/img/player_default.jpg'
            ]
            image_sent = False
            for image_path in image_paths:
                try:
                    if os.path.exists(image_path):
                        await bot.send_photo(
                            message.chat.id,
                            types.FSInputFile(image_path),
                            caption='<b>привет</b>\nвижу, что у тебя нету аккаунта в боте, давай зарегистрируемся',
                            parse_mode='HTML',
                            reply_markup=markup
                        )
                        image_sent = True
                        break
                except Exception:
                    continue
            if not image_sent:
                await message.answer(
                    '<b>привет</b>\nвижу, что у тебя нету аккаунта в боте, давай зарегистрируемся',
                    parse_mode='HTML',
                    reply_markup=markup
                )
        except Exception:
            await message.answer(
                '<b>привет</b>\nвижу, что у тебя нету аккаунта в боте, давай зарегистрируемся',
                parse_mode='HTML',
                reply_markup=markup
            )
    else:
        await message.answer('напиши боту в личные сообщения, чтобы зарегистрироваться')

# Текстовые алиасы для старта без слеша
@dp.message(F.text.lower() == 'старт')
async def cmd_start_rus_text(message: types.Message, state: FSMContext):
    await cmd_start(message, state)
@dp.message(F.text.lower() == 'start')
async def cmd_start_eng_text(message: types.Message, state: FSMContext):
    await cmd_start(message, state)

@dp.message(Command('clear_db'))
async def clear_database(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    global users
    users = {}
    
    save_users()
    await message.answer('база данных очищена')

@dp.message(Command('fix_db'))
async def fix_database(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    # Создаём новую базу без дубликатов
    fixed_users = {}
    
    for user_id, user_data in users.items():
        if user_id not in fixed_users:
            # Убеждаемся что все поля есть
            if 'warns' not in user_data:
                user_data['warns'] = 0
            if 'banned' not in user_data:
                user_data['banned'] = False
            if 'referral_earnings' not in user_data:
                user_data['referral_earnings'] = 0
            fixed_users[user_id] = user_data
    
    users = fixed_users
    
    save_users()
    await message.answer(f'база данных исправлена. осталось {len(users)} пользователей')

@dp.message(F.text.lower() == 'меню')
async def on_menu_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # Проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    await show_menu(message, user_id)

@dp.message(F.text.lower() == 'я')
async def on_ya_button(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # Проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    await show_menu(message, user_id)

@dp.message(F.text.lower() == 'mn')
async def on_mn_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # Проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    await show_menu(message, user_id)

@dp.message(F.text.lower() == 'm')
async def on_m_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # Проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    await show_menu(message, user_id)

@dp.message(Command('menu'))
async def cmd_menu_en(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # Проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    await show_menu(message, user_id)

# Команды без слеша
@dp.message(F.text.lower() == 'меню')
async def text_menu(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # Проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    await show_menu(message, user_id)

@dp.message(F.text.lower() == 'я')
async def text_ya(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # Проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    await show_menu(message, user_id)

@dp.message(F.text.lower() == 'mn')
async def text_mn(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # Проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    await show_menu(message, user_id)

@dp.message(F.text.lower() == 'm')
async def text_m(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # Проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    await show_menu(message, user_id)

@dp.message(F.text.lower() == 'menu')
async def text_menu_en(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # Проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    await show_menu(message, user_id)





# Обработчики обычных кнопок
@dp.message(F.text.lower() == '💼 работа')
async def on_work_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    await show_work_menu(message, user_id)
@dp.message(F.text.lower() == '📦 работа грузчика')
async def on_loader_work_button(message: types.Message, state: FSMContext):
    """обработчик кнопки работы грузчика"""
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    if user_data.get('banned', False):
        await message.answer('🚫 ты заблокирован и не можешь работать')
        return
    
    # показываем информацию о работе грузчика
    info_text = "📦 <b>работа грузчика</b>\n\n"
    info_text += "💼 <b>описание работы:</b>\n"
    info_text += "• таскаешь разные грузы на складе\n"
    info_text += "• время переноса зависит от веса (5-60 сек)\n"
    info_text += "• чем тяжелее груз, тем больше оплата\n"
    info_text += "• можно уйти с работы в любой момент\n\n"
    
    info_text += "💰 <b>типы грузов:</b>\n"
    info_text += "• обычные грузы (80%): коробки, мешки, ящики\n"
    info_text += "• редкие грузы (15%): электроника, оборудование\n"
    info_text += "• супер редкие (5%): алмазы, ювелирка, золото\n\n"
    
    info_text += "💵 <b>средняя оплата:</b> ~250кк за груз\n"
    info_text += "⏱️ <b>время работы:</b> по желанию\n\n"
    
    info_text += "🎯 <b>как работает:</b>\n"
    info_text += "1. нажимаешь 'начать работу'\n"
    info_text += "2. бот дает груз и таймер\n"
    info_text += "3. после завершения получаешь оплату\n"
    info_text += "4. автоматически дается новый груз\n"
    info_text += "5. можешь уйти в любой момент"
    
    # создаем клавиатуру с кнопками
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='🚀 начать работу грузчиком')],
        [KeyboardButton(text='назад ⬅️')]
    ])
    
    await message.answer(info_text, parse_mode='HTML', reply_markup=markup)

@dp.message(F.text.lower() == '🚀 начать работу грузчиком')
async def on_start_loader_work_button(message: types.Message, state: FSMContext):
    """обработчик кнопки начала работы грузчика"""
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    if user_data.get('banned', False):
        await message.answer('🚫 ты заблокирован и не можешь работать')
        return
    
    # проверяем, не работает ли уже грузчиком
    if user_id_str in loader_jobs:
        await message.answer('⚠️ ты уже работаешь грузчиком! сначала закончи текущую смену')
        return
    
    # начинаем работу грузчика
    await start_loader_work(message, user_id_str, state)

@dp.message(F.text.lower() == '🎫 промокоды')
async def on_promo_button(message: types.Message, state: FSMContext):
    """обработчик кнопки промокодов"""
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    

    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    if user_data.get('banned', False):
        await message.answer('🚫 ты заблокирован и не можешь использовать промокоды')
        return
    
    # показываем меню промокодов
    promo_text = "🎫 <b>промокоды</b>\n\n"
    promo_text += "💡 <b>как использовать:</b>\n"
    promo_text += "• введи промокод в поле ниже\n"
    promo_text += "• получишь награду на баланс\n"
    promo_text += "• каждый промокод можно использовать только один раз\n\n"
    
    promo_text += "💰 <b>награды:</b>\n"
    promo_text += "• валюта на баланс\n"
    promo_text += "• размер награды зависит от промокода\n\n"
    
    promo_text += "⚠️ <b>внимание:</b>\n"
    promo_text += "• промокоды могут иметь ограничения по времени\n"
    promo_text += "• промокоды могут иметь лимит активаций\n"
    promo_text += "• используй промокоды вовремя!"
    
    # создаем клавиатуру
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='🔑 ввести промокод')],
        [KeyboardButton(text='назад ⬅️')]
    ])
    
    await message.answer(promo_text, parse_mode='HTML', reply_markup=markup)

@dp.message(F.text.lower() == '🔑 ввести промокод')
async def on_enter_promo_button(message: types.Message, state: FSMContext):
    """обработчик кнопки ввода промокода"""
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    if user_data.get('banned', False):
        await message.answer('🚫 ты заблокирован и не можешь использовать промокоды')
        return
    
    # устанавливаем состояние ожидания промокода
    await state.set_state(PromoState.waiting_for_promo_input)
    
    # создаем клавиатуру для возврата
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='назад ⬅️')]
    ])
    
    await message.answer(
        "🔑 <b>введи промокод:</b>\n\n"
        "📝 напиши промокод в чат\n"
        "💡 промокод должен состоять из букв и цифр\n"
        "❌ для отмены нажми 'назад'",
        parse_mode='HTML',
        reply_markup=markup
    )

@dp.message(PromoState.waiting_for_promo_input)
async def handle_promo_input(message: types.Message, state: FSMContext):
    """обработчик ввода промокода"""
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    if user_data.get('banned', False):
        await message.answer('🚫 ты заблокирован и не можешь использовать промокоды')
        await state.clear()
        await show_menu(message, user_id)
        return
    
    promo_code = message.text.strip().upper()
    
    # проверяем, что это не команда
    if promo_code.startswith('/'):
        await message.answer('❌ это команда, а не промокод!')
        return
    
    # активируем промокод
    success, message_text, reward = activate_promo(promo_code, user_id_str)
    
    if success:
        # начисляем награду
        users[user_id_str]['balance'] += reward
        save_users()
        
        # показываем успешное сообщение
        success_text = f"✅ <b>промокод активирован!</b>\n\n"
        success_text += f"🎫 <b>промокод:</b> {promo_code}\n"
        success_text += f"💰 <b>награда:</b> ${format_money(reward)}\n"
        success_text += f"💳 <b>новый баланс:</b> ${format_money(users[user_id_str]['balance'])}\n\n"
        success_text += "🎉 <b>поздравляем с получением награды!</b>"
        
        await message.answer(success_text, parse_mode='HTML')
    else:
        # показываем ошибку
        error_text = f"❌ <b>ошибка активации промокода</b>\n\n"
        error_text += f"🎫 <b>промокод:</b> {promo_code}\n"
        error_text += f"⚠️ <b>причина:</b> {message_text}\n\n"
        error_text += "💡 <b>возможные причины:</b>\n"
        error_text += "• промокод не существует\n"
        error_text += "• промокод уже использован\n"
        error_text += "• истек срок действия\n"
        error_text += "• превышен лимит активаций"
        
        await message.answer(error_text, parse_mode='HTML')
    
    # очищаем состояние и возвращаемся в главное меню
    await state.clear()
    await show_menu(message, user_id)

@dp.message(F.text.lower() == '❌ уйти с работы')
async def on_quit_loader_work_button(message: types.Message, state: FSMContext):
    """обработчик кнопки ухода с работы грузчика"""
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in loader_jobs:
        await message.answer('ты не работаешь грузчиком')
        return
    
    # получаем данные о работе
    job = loader_jobs[user_id_str]
    user_data = users[user_id_str]
    nick = user_data.get('nick', 'игрок')
    
    # рассчитываем время работы
    work_time = datetime.datetime.now().timestamp() - job['start_time']
    hours = int(work_time // 3600)
    minutes = int((work_time % 3600) // 60)
    seconds = int(work_time % 60)
    
    # создаем сообщение подтверждения
    confirm_text = f"🤔 <b>{nick}, ты точно хочешь уйти с работы?</b>\n\n"
    confirm_text += f"⏱️ <b>время работы:</b> {hours:02d}:{minutes:02d}:{seconds:02d}\n"
    confirm_text += f"📦 <b>грузов доставлено:</b> {job['cargo_count']}\n"
    confirm_text += f"💰 <b>ты заработал:</b> ${format_money(job['total_earnings'])}\n\n"
    confirm_text += "❓ подтверди уход с работы"
    
    # создаем клавиатуру подтверждения
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='✅ да, уйти с работы')],
        [KeyboardButton(text='❌ нет, продолжить работу')]
    ])
    
    await message.answer(confirm_text, parse_mode='HTML', reply_markup=markup)

@dp.message(F.text.lower() == '✅ да, уйти с работы')
async def on_confirm_quit_loader_work(message: types.Message, state: FSMContext):
    """обработчик подтверждения ухода с работы грузчика"""
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in loader_jobs:
        await message.answer('ты не работаешь грузчиком')
        return
    
    # завершаем работу
    await finish_loader_work(message.chat.id, user_id_str)
    
    # очищаем состояние
    await state.clear()
    
    # возвращаемся в главное меню
    await show_menu(message, user_id)

@dp.message(F.text.lower() == '❌ нет, продолжить работу')
async def on_cancel_quit_loader_work(message: types.Message):
    """обработчик отмены ухода с работы грузчика"""
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in loader_jobs:
        await message.answer('ты не работаешь грузчиком')
        return
    
    # возвращаемся к работе
    await message.answer('✅ продолжаем работу!', reply_markup=ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='🏁 закончить работу')]
    ]))

@dp.message(F.text.lower() == '🏁 закончить работу')
async def on_finish_loader_work_button(message: types.Message, state: FSMContext):
    """обработчик кнопки завершения работы грузчика"""
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in loader_jobs:
        await message.answer('ты не работаешь грузчиком')
        return
    
    # завершаем работу
    await finish_loader_work(message.chat.id, user_id_str)
    
    # очищаем состояние
    await state.clear()
    
    # возвращаемся в главное меню
    await show_menu(message, user_id)


@dp.message(F.text.lower() == '💰 бонус')
async def on_bonus_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    await show_bonus_menu(message, user_id)

@dp.message(F.text.lower() == '🎮 игры')
async def on_games_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    await show_games_menu(message, user_id)

@dp.message(F.text.lower() == '🏦 банк')
async def on_bank_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    await show_bank_menu(message, user_id)

@dp.message(F.text.lower() == 'рефералы 👥')
async def on_referrals_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    await show_referrals_menu(message, user_id)

@dp.message(F.text.lower() == 'рулетка 🎰')
async def on_roulette_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    await message.answer(
        '🎰 <b>рулетка</b>\n\n'
        'классическая игра в рулетку с возможностью выиграть большие деньги!\n\n'
        '🎯 <b>как играть:</b>\n'
        '• делай ставки на числа от 0 до 36\n'
        '• или ставь на цвета (красный/черный)\n'
        '• выигрыш зависит от типа ставки\n\n'
        '💰 <b>выигрыши:</b>\n'
        '• на число (35:1): <b>35x</b> от ставки\n'
        '• на цвет (1:1): <b>2x</b> от ставки\n'
        '• на четное/нечетное (1:1): <b>2x</b> от ставки\n\n'
        '⚖️ <b>система шансов:</b>\n'
        '• x2 ставки (цвета, чет/нечет): до 60%\n'
        '• x3 ставки (ряды, дюжины): до 40%\n'
        '• x36 ставки (числа, зеро): до 3%\n'
        '• топ-3 игроки получают анти-бонусы\n'
        '• богатые игроки имеют пониженные шансы\n'
        '• чем выше шанс, тем больше риск проигрыша\n\n'
        '⚠️ <b>важно:</b> игра работает только в чатах!\n\n'
        '📝 <b>команды:</b>\n'
        '• <code>/rul</code> - основная команда\n'
        '• <code>рул четное 1.5к</code> - на четное число\n'
        '• <code>рул кра 1.5к</code> - на красный цвет\n'
        '• <code>рул чер 1.5к</code> - на черный цвет\n'
        '• <code>рул 7 1.5к</code> - на конкретное число',
        parse_mode='HTML'
    
    )

@dp.message(F.text.lower() == 'кости 🎲')
async def on_dice_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    await message.answer(
        '🎲 <b>кости</b>\n\n'
        'увлекательная игра в кости между двумя игроками!\n\n'
        '🎯 <b>как играть:</b>\n'
        '• создай игру командой "кости сумма"\n'
        '• второй игрок принимает вызов\n'
        '• оба бросают кости по очереди\n'
        '• у кого больше очков - тот выигрывает ставку\n\n'
        '💰 <b>выигрыши:</b>\n'
        '• победитель забирает ставку обоих игроков\n'
        '• при ничье каждый получает свою ставку обратно\n'
        '• проигравший теряет свою ставку\n\n'
        '⚠️ <b>важно:</b> игра работает только в чатах!\n\n'
        '📝 <b>команды:</b>\n'
        '• <code>кости 1.5к</code> - создать игру со ставкой 1.5к\n'
        '• <code>кости все</code> - ставка всем балансом\n'
        '• <code>кости 500к</code> - ставка 500к',
        parse_mode='HTML'
    
    )

@dp.message(F.text.lower() == 'баскетбол 🏀')
async def on_basketball_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    await message.answer(
        '🏀 <b>баскетбол</b>\n\n'
        'спортивная игра в баскетбол между двумя игроками!\n\n'
        '🎯 <b>как играть:</b>\n'
        '• создай игру командой "баскет сумма"\n'
        '• второй игрок принимает вызов\n'
        '• оба бросают мяч по очереди\n'
        '• у кого больше очков - тот выигрывает\n\n'
        '💰 <b>выигрыши:</b>\n'
        '• победа: <b>2x</b> от ставки\n'
        '• при ничье каждый получает свою ставку обратно\n\n'
        '⚠️ <b>важно:</b> игра работает только в чатах!\n\n'
        '📝 <b>команды:</b>\n'
        '• <code>баскет 1.5к</code> - создать игру со ставкой 1.5к\n'
        '• <code>бск 1.5к</code> - короткая команда\n'
        '• <code>баскет все</code> - ставка всем балансом',
        parse_mode='HTML'
    
    )

@dp.message(F.text.lower() == 'назад ⬅️')
async def on_back_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    # проверяем, откуда пришел пользователь
    if message.chat.type == 'private':
        # если это личное сообщение, показываем главное меню
        await show_menu(message, user_id)
    else:
        # если это чат, показываем главное меню
        await show_menu(message, user_id)

@dp.message(F.text.lower() == 'зарегистрироваться ✅')
async def on_register_button(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Собираем информацию о пользователе
    collect_user_info(message, str(user_id))
    
    # Проверяем, не зарегистрирован ли уже пользователь (только по наличию nick)
    user_id_str = str(user_id)
    if user_id_str in users and 'nick' in users[user_id_str]:
        await message.answer('ты уже зарегистрирован!')
        return
    
    await message.answer('напиши свой ник', reply_markup=ReplyKeyboardRemove())
    
    await state.set_state(RegisterState.waiting_for_nick)

@dp.message(F.text.lower().contains('зарегистрироваться'))
async def register_start_fallback(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Проверяем, не зарегистрирован ли уже пользователь (только по наличию nick)
    user_id_str = str(user_id)
    if user_id_str in users and 'nick' in users[user_id_str]:
        await message.answer('ты уже зарегистрирован!')
        return
    
    await message.answer('напиши свой ник')
    await state.set_state(RegisterState.waiting_for_nick)
@dp.message(RegisterState.waiting_for_nick)
async def process_nick(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)  # Конвертируем в строку
    nick = message.text.strip()
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, не зарегистрирован ли уже пользователь
    if user_id_str in users and 'nick' in users[user_id_str]:
        await message.answer('ты уже зарегистрирован!')
        await state.clear()
        await show_menu(message, user_id)
        return
    
    # Проверяем длину ника
    if len(nick) < 2 or len(nick) > 20:
        await message.answer('ник должен быть от 2 до 20 символов')
        return
    
    # Проверяем, не занят ли ник
    for existing_user in users.values():
        if 'nick' in existing_user and existing_user['nick'].lower() == nick.lower():
            await message.answer('этот ник уже занят, выбери другой')
            return
    
    # Проверяем, есть ли реферер в базе данных
    temp_referrer = None
    
    if user_id_str in users and 'temp_referrer' in users[user_id_str]:
        temp_referrer = users[user_id_str]['temp_referrer']
    
    # Регистрируем пользователя
    users[user_id_str] = {
        'nick': nick,
        'tg_username': message.from_user.username or 'без_юз',
        'balance': 0,  # 0 начальный баланс
        'referrals': 0,
        'referral_earnings': 0,
        'warns': 0,
        'banned': False,
        'registration_date': str(datetime.datetime.now()),
        'last_activity': str(datetime.datetime.now()),
        'total_messages': 0,
        'phone_number': None,
        'email': None,
        'age': None,
        'city': None,
        'country': None,
        'language': message.from_user.language_code or 'ru',
        'device_info': None,
        'ip_address': None,
        'referral_source': 'direct' if not temp_referrer else 'referral',
        'account_type': 'regular',
        'verification_status': 'unverified',
        'security_level': 'basic',
        'premium_features': False,
        'last_login': str(datetime.datetime.now()),
        'login_count': 1,
        'session_duration': 0,
        'last_bonus_time': 0,
        'preferences': {
            'notifications': True,
            'privacy_mode': False,
            'auto_save': True
        },
        'bank_deposit': 0,
        'bank_deposit_time': 0
    }
    
    # Если пользователь пришёл по реферальной ссылке
    if temp_referrer and str(temp_referrer) in users:
        referrer_id_str = str(temp_referrer)
        referrer_data = users[referrer_id_str]
        
        # Увеличиваем количество рефералов
        referrer_data['referrals'] = referrer_data.get('referrals', 0) + 1
        
        # Выдаём случайный бонус
        bonus = get_random_referral_bonus()
        users[user_id_str]['balance'] += bonus
        referrer_data['referral_earnings'] = referrer_data.get('referral_earnings', 0) + bonus
        
        # Проверяем достижения
        milestone_bonus = get_milestone_bonus(referrer_data['referrals'])
        if milestone_bonus > 0:
            referrer_data['balance'] += milestone_bonus
            referrer_data['referral_earnings'] += milestone_bonus
        
        # Сохраняем изменения
        save_users()
        
        # Уведомляем реферера
        try:
            await bot.send_message(
                temp_referrer,
                f"🎉 ты заскамил мамонта!\n\n"
                f"👤 <b>новый игрок:</b> <a href=\"tg://user?id={user_id}\"><b>{nick}</b></a>\n"
                f"💰 <b>твой бонус:</b> <b>${format_money(bonus)}</b>\n"
                f"📊 <b>всего рефералов:</b> <b>{referrer_data['referrals']}</b>\n"
                f"💎 <b>общий заработок:</b> <b>${format_money(referrer_data['referral_earnings'])}</b>",
                parse_mode='HTML'
            )
            
            # Если есть milestone бонус
            if milestone_bonus > 0:
                await bot.send_message(
                    temp_referrer,
                    f"🏆 <b>достижение!</b>\n\n"
                    f"🎯 <b>{referrer_data['referrals']} рефералов</b>\n"
                    f"💰 <b>дополнительный бонус:</b> <b>${format_money(milestone_bonus)}</b>",
                    parse_mode='HTML'
                )
        except Exception as e:
            print(f"Ошибка отправки уведомления рефереру {temp_referrer}: {e}")
    
    # Сохраняем пользователей
    save_users()
    
    # Очищаем состояние
    await state.clear()
    
    # Показываем меню
    await show_menu(message, user_id)

async def process_transfer(message: types.Message, text: str, user_id: int):
    """Обрабатывает перевод денег"""
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    # Проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    # Парсим текст для поиска получателя и суммы
    text_lower = text.lower()
    
    # Ищем сумму в тексте - исправленный regex для поддержки любого количества "к"
    # Ищем сумму в конце строки или перед username
    amount_match = re.search(r'(\d+(?:[.,]\d+)?(?:к+)?|все)(?:\s*$|\s+(?:@|юз))', text_lower)
    
    if not amount_match:
        await message.answer('укажи сумму для перевода. например: кинуть юз 1к или кинуть юз 1000000')
        return
    
    amount_text = amount_match.group(1)
    
    amount = parse_amount(amount_text)
    
    # Обработка команды "все"
    if amount == -1:
        amount = users[user_id_str]['balance']
    
    if amount <= 0:
            await message.answer('у тебя нет денег для перевода')
            return
    
    # проверяем, что сумма больше 0
    if amount <= 0:
        await message.answer('сумма перевода должна быть больше 0')
        return
    
    # Ищем получателя (после "юз" или "@username"). Исключаем слово "все" как ник
    user_match = re.search(r'(?:юз\s+((?!все\b)[^\s]+)|@([^\s]+))', text_lower)
    
    if not user_match:
        await message.answer('укажи получателя. например: кинуть юз username сумма или кинуть @username сумма')
        return
    
    # Берем первый найденный username (из группы 1 или 2)
    target_username = user_match.group(1) if user_match.group(1) else user_match.group(2)
    
    # Извлекаем username из различных форматов
    username = extract_username(target_username)
    
    # Ищем пользователя по username или нику
    target_user_id = None
    
    for uid, user_data in users.items():
        if (user_data.get('tg_username', '').lower() == username.lower() or 
            user_data.get('nick', '').lower() == target_username.lower()):
            target_user_id = uid
            break
    
    if not target_user_id:
        await message.answer('пользователь не найден')
        return
    
    if target_user_id == user_id_str:
        await message.answer('нельзя переводить самому себе')
        return
    
    # Проверяем, является ли отправитель топ-20 игроком
    is_top20 = is_top20_player(user_id_str)
    
    # Вычисляем комиссию для топ-20 игроков
    commission_amount = 0
    
    amount_to_receiver = amount
    
    if is_top20:
        commission_amount = int(amount * TRANSFER_COMMISSION_TOP20 / 100)
    
    amount_to_receiver = amount - commission_amount
    
    # Проверяем баланс (комиссия берется с суммы перевода)
    if users[user_id_str]['balance'] < amount:
        await message.answer(f"у тебя недостаточно денег. на счету: <b>${format_money(users[user_id_str]['balance'])}</b>", parse_mode='HTML')
        return
    
    # Проверяем, не забанен ли получатель
    target_user_data = users[target_user_id]
    
    if target_user_data.get('banned', False):
        await message.answer('нельзя переводить забаненному пользователю')
        return
    
    # Проверяем настройку подтверждений перевода
    transfer_confirmations = user_data.get('transfer_confirmations', True)
    
    if transfer_confirmations:
        # Показываем подтверждение перевода
        sender_nick = users[user_id_str].get('nick', 'игрок')
        receiver_nick = users[target_user_id].get('nick', 'игрок')
        
        # Формируем сообщение подтверждения
        if is_top20:
            confirmation_message = (
                f"<a href='tg://user?id={user_id}'><b>{sender_nick}</b></a>, подтверди перевод игроку <b>{receiver_nick}</b> ${format_money(amount)}\n\n"
                f"комиссия составляет ${format_money(commission_amount)}"
            )
        else:
            confirmation_message = (
                f"<a href='tg://user?id={user_id}'><b>{sender_nick}</b></a>, подтверди перевод игроку <b>{receiver_nick}</b> ${format_money(amount)}"
            )
        
        # Создаем кнопку подтверждения
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✅ подтвердить перевод', callback_data=f'confirm_transfer_{user_id_str}_{target_user_id}_{amount}_{is_top20}')]
        ])
        
        await message.answer(confirmation_message, parse_mode='HTML', reply_markup=markup)
    else:
        # Выполняем перевод сразу без подтверждения
        await execute_transfer(user_id_str, target_user_id, amount, is_top20, message)

async def execute_transfer(sender_user_id: str, target_user_id: str, amount: int, is_top20: bool, message: types.Message):
    """выполняет перевод денег"""
    # Вычисляем комиссию для топ-20 игроков
    commission_amount = 0
    amount_to_receiver = amount
    
    if is_top20:
        commission_amount = int(amount * TRANSFER_COMMISSION_TOP20 / 100)
        amount_to_receiver = amount - commission_amount
    
    # Выполняем перевод
    users[sender_user_id]['balance'] -= amount
    users[target_user_id]['balance'] += amount_to_receiver
    
    # Сохраняем изменения в базу данных
    save_users()
    
    # Формируем сообщение об успешном переводе
    sender_nick = users[sender_user_id].get('nick', 'игрок')
    receiver_nick = users[target_user_id].get('nick', 'игрок')
    
    if is_top20:
        success_message = (
            f"✅ <b>{sender_nick}</b>, ты успешно перевел <b>${format_money(amount)}</b> игроку <b>{receiver_nick}</b>\n\n"
            f"💸 <b>комиссия составила:</b> <b>${format_money(commission_amount)}</b>\n"
            f"💳 <b>твой баланс:</b> <b>${format_money(users[sender_user_id]['balance'])}</b>"
        )
    else:
        success_message = (
            f"✅ <b>{sender_nick}</b>, ты успешно перевел <b>${format_money(amount)}</b> игроку <b>{receiver_nick}</b>\n\n"
            f"💳 <b>твой баланс:</b> <b>${format_money(users[sender_user_id]['balance'])}</b>"
        )
    
    await message.answer(success_message, parse_mode='HTML')

# Обработчик подтверждения перевода
@dp.callback_query(lambda c: c.data.startswith('confirm_transfer_'))
async def confirm_transfer_callback(callback: types.CallbackQuery):
    
    """Обрабатывает подтверждение перевода"""
    user_id = callback.from_user.id
    
    user_id_str = str(user_id)
    
    # Проверяем, зарегистрирован ли пользователь
    if user_id_str not in users:
        await callback.answer("ты не зарегистрирован в боте")
        return
    
    # Парсим данные из callback_data
    try:
        data_parts = callback.data.split('_')
        sender_user_id = data_parts[2]  # ID отправителя
        target_user_id = data_parts[3]  # ID получателя
        amount = int(data_parts[4])
        is_top20 = data_parts[5] == 'True'
    except (IndexError, ValueError):
        await callback.answer("Ошибка данных перевода")
        return
    
    # Проверяем, что нажавший кнопку - это тот, кто создал перевод
    if user_id_str != sender_user_id:
        await callback.answer("😡 только отправитель может подтвердить перевод")
        return
    
    # Проверяем, что перевод еще актуален
    if user_id_str not in users or target_user_id not in users:
        await callback.answer("Пользователь не найден")
        return
    
    # Проверяем баланс еще раз
    if users[user_id_str]['balance'] < amount:
        await callback.answer("Недостаточно средств")
        return
    
    # Выполняем перевод используя общую функцию
    await execute_transfer(user_id_str, target_user_id, amount, is_top20, callback.message)
    
    # Обновляем сообщение
    await callback.message.edit_text("✅ перевод выполнен!", parse_mode='HTML')
    
    await callback.answer("перевод выполнен!")
    
    # Отправляем уведомление получателю
    try:
        sender_nick = users[user_id_str].get('nick', 'игрок')
        commission_amount = int(amount * TRANSFER_COMMISSION_TOP20 / 100) if is_top20 else 0
        amount_to_receiver = amount - commission_amount
        
        await bot.send_message(
            target_user_id,
            f"💰 тебе перевели <b>${format_money(amount_to_receiver)}</b> от <a href='tg://user?id={user_id}'><b>{sender_nick}</b></a>\n"
            f"💳 теперь у тебя: <b>${format_money(users[target_user_id]['balance'])}</b>",
            parse_mode='HTML'
        )
    except Exception as e:
        print(f"ошибка отправки уведомления получателю: {e}")

# безопасный экранирующий хелпер для HTML
def html_escape(text: str) -> str:
    if text is None:
        return ''
    return (
        str(text)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#39;')
    )

@dp.message(F.text.regexp(r'(?i)\b(кинуть|передать|перевести|дать)\b'))
async def on_transfer(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, зарегистрирован ли пользователь
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    # Если это ответ на сообщение - обрабатываем перевод по ответу
    if message.reply_to_message:
        await handle_reply_transfer(message)
        return
    
    # Иначе обычный перевод
    await process_transfer(message, message.text, user_id)

async def handle_reply_transfer(message: types.Message):
    """Обрабатывает перевод по ответу на сообщение"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Проверяем, зарегистрирован ли пользователь
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    # Проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    text = message.text.lower()
    
    # Извлекаем сумму из текста - ищем любые числа (с сокращениями или без)
    # Ищем: число + опционально точка/запятая + опционально любое количество "к"
    amount_match = re.search(r'(\d+(?:[.,]\d+)?(?:к+)?|все)', text)
    
    if not amount_match:
        await message.answer('укажи сумму для перевода. например: кинуть 1к или кинуть 1000000')
        return
    
    try:
        amount_text = amount_match.group(1)
        amount = parse_amount(amount_text)
        
        # Обработка команды "все" для ответа
        if amount == -1:
            amount = users[user_id_str]['balance']
        if amount <= 0:
            await message.answer('у тебя нет денег для перевода')
            return
        
        # проверяем, что сумма больше 0
        if amount <= 0:
            await message.answer('сумма перевода должна быть больше 0')
            return
        
        # Получаем ID пользователя, на чье сообщение отвечаем
        target_user_id = str(message.reply_to_message.from_user.id)
        if target_user_id not in users:
            await message.answer('пользователь не зарегистрирован в боте')
            return
        
        if target_user_id == user_id_str:
            await message.answer('нельзя переводить самому себе')
            return
        
        # Проверяем, не забанен ли получатель
        target_user_data = users[target_user_id]
        if target_user_data.get('banned', False):
            await message.answer('нельзя переводить забаненному пользователю')
            return
        
        # Проверяем, является ли отправитель топ-20 игроком
        is_top20 = is_top20_player(user_id_str)
        
        # Вычисляем комиссию для топ-20 игроков
        commission_amount = 0
        amount_to_receiver = amount
        
        if is_top20:
            commission_amount = int(amount * TRANSFER_COMMISSION_TOP20 / 100)
            amount_to_receiver = amount - commission_amount
        
        if users[user_id_str]['balance'] < amount:
            await message.answer(f"у тебя недостаточно денег. на счету: <b>${format_money(users[user_id_str]['balance'])}</b>", parse_mode='HTML')
            return
        
        # Проверяем настройку подтверждений перевода
        transfer_confirmations = user_data.get('transfer_confirmations', True)
        
        if transfer_confirmations:
            # Показываем подтверждение перевода
            sender_nick = users[user_id_str].get('nick', 'игрок')
            receiver_nick = users[target_user_id].get('nick', 'игрок')
            
            # Формируем сообщение подтверждения
            if is_top20:
                confirmation_message = (
                    f"<a href='tg://user?id={user_id}'><b>{sender_nick}</b></a>, подтверди перевод игроку <b>{receiver_nick}</b> ${format_money(amount)}\n\n"
                    f"комиссия составляет ${format_money(commission_amount)}"
                )
            else:
                confirmation_message = (
                    f"<a href='tg://user?id={user_id}'><b>{sender_nick}</b></a>, подтверди перевод игроку <b>{receiver_nick}</b> ${format_money(amount)}"
                )
            
            # Создаем кнопку подтверждения
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='✅ подтвердить перевод', callback_data=f'confirm_transfer_{user_id_str}_{target_user_id}_{amount}_{is_top20}')]
            ])
            
            # Отправляем сообщение с подтверждением
            await message.answer(confirmation_message, parse_mode='HTML', reply_markup=markup)
        else:
            # Выполняем перевод сразу без подтверждения
            await execute_transfer(user_id_str, target_user_id, amount, is_top20, message)
    
    except Exception as e:
        await message.answer(f'ошибка при переводе: {str(e)}. используй формат: кинуть сумма')



# Админ команды
@dp.message(Command('admin'))
async def admin_panel(message: types.Message):
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к админ панели')
        return
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='⚠️ наказания'), KeyboardButton(text='💸 валюта')],
        [KeyboardButton(text='📋 база данных'), KeyboardButton(text='💰 налоги')],
    
    [KeyboardButton(text='🏦 вклады'), KeyboardButton(text='📣 рассылка')],
        [KeyboardButton(text='⚙️ управление промокодами'), KeyboardButton(text='добавить админ 👑')],
    
    [KeyboardButton(text='назад ⬅️')]
    ])
    
    await message.answer(
        '🔧 <b>админ панель</b>\n\nвыбери раздел:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.message(F.text.lower() == 'админ')
async def admin_panel_text(message: types.Message):
    """Обработчик текстовой команды 'админ'"""
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к админ панели')
        return
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='⚠️ наказания'), KeyboardButton(text='💸 валюта')],
        [KeyboardButton(text='📋 база данных'), KeyboardButton(text='💰 налоги')],
    
    [KeyboardButton(text='🏦 вклады'), KeyboardButton(text='📣 рассылка')],
        [KeyboardButton(text='⚙️ управление промокодами'), KeyboardButton(text='добавить админ 👑')],
    
    [KeyboardButton(text='назад ⬅️')]
    ])
    
    await message.answer(
        '🔧 <b>админ панель</b>\n\nвыбери раздел:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.message(F.text.lower() == 'админ')
async def admin_panel_text(message: types.Message):
    """Обработчик текстовой команды 'админ'"""
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к админ панели')
        return
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='⚠️ наказания'), KeyboardButton(text='💸 валюта')],
        [KeyboardButton(text='📋 база данных'), KeyboardButton(text='💰 налоги')],
    
    [KeyboardButton(text='🏦 вклады'), KeyboardButton(text='📣 рассылка')],
        [KeyboardButton(text='⚙️ управление промокодами'), KeyboardButton(text='добавить админ 👑')],
    
    [KeyboardButton(text='назад ⬅️')]
    ])
    
    await message.answer(
        '🔧 <b>админ панель</b>\n\nвыбери раздел:',
        parse_mode='HTML',
    
    reply_markup=markup
    )
# Обработчик для русской команды /админ
@dp.message(lambda message: message.text and message.text.lower() in ['/админ', '/admin'])
async def admin_panel_commands(message: types.Message):
    """Обработчик команд '/админ' и '/admin'"""
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к админ панели')
        return
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='⚠️ наказания'), KeyboardButton(text='💸 валюта')],
        [KeyboardButton(text='📋 база данных'), KeyboardButton(text='💰 налоги')],
    
    [KeyboardButton(text='🏦 вклады'), KeyboardButton(text='📣 рассылка')],
        [KeyboardButton(text='⚙️ управление промокодами'), KeyboardButton(text='добавить админ 👑')],
    
    [KeyboardButton(text='назад ⬅️')]
    ])
    
    await message.answer(
        '🔧 <b>админ панель</b>\n\nвыбери раздел:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.message(F.text == '⚙️ управление промокодами')
async def admin_promo_management(message: types.Message):
    """Обработчик кнопки управления промокодами в админ панели"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    # Показываем меню управления промокодами
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='➕ создать промокод'), KeyboardButton(text='📋 список промокодов')],
        [KeyboardButton(text='🗑️ удалить промокод'), KeyboardButton(text='📊 статистика промокодов')],
        [KeyboardButton(text='⬅️ назад в админ панель')]
    ])
    
    await message.answer(
        '⚙️ <b>управление промокодами</b>\n\nвыбери действие:',
        parse_mode='HTML',
        reply_markup=markup
    )

@dp.message(F.text.lower().contains('выдать') & F.text.lower().contains('варн'))
async def issue_warn_button(message: types.Message, state: FSMContext):
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    collect_user_info(message, user_id_str)
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    await state.update_data(current_action='warn')
    
    await message.answer('😡 напиши юз кому надо вставить варн в попачку))', reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminState.waiting_for_target)

@dp.message(AdminState.waiting_for_target)
async def admin_target_selected(message: types.Message, state: FSMContext):
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    target_text = message.text.strip()
    
    username = extract_username(target_text)
    target_user_id = None
    
    target_nick = None
    for uid, user_data in users.items():
        if (user_data.get('tg_username', '').lower() == username.lower() or 
            user_data.get('nick', '').lower() == target_text.lower()):
            target_user_id = uid
            target_nick = user_data.get('nick', 'неизвестно')
            break
    if not target_user_id:
        await message.answer('пользователь не найден или не зарегистрирован')
        await state.clear()
        await admin_panel(message)
        return
    data = await state.get_data()
    
    current_action = data.get('current_action')
    await state.update_data(target_user_id=target_user_id, target_nick=target_nick)
    
    if current_action == 'warn':
        await message.answer('🧾 напиши причину варна')
        await state.set_state(AdminState.waiting_for_warn_reason)
    elif current_action == 'ban':
        await message.answer('🧾 напиши причину бана')
        await state.set_state(AdminState.waiting_for_ban_reason)
    elif current_action == 'unwarn':
        await message.answer('🧾 напиши, сколько варнов снять (число или "все")')
        await state.set_state(AdminState.waiting_for_unwarn_count)
    elif current_action == 'unban':
        await message.answer('🧾 напиши причину разбана')
        await state.set_state(AdminState.waiting_for_unban_reason)
    elif current_action == 'annul_balance':
        await message.answer('🧾 напиши причину аннулирования')
        await state.set_state(AdminState.waiting_for_annul_reason)
    elif current_action == 'give_money':
        await message.answer('💵 напиши сумму для пополнения')
        await state.set_state(AdminState.waiting_for_give_amount)

@dp.message(F.text.lower().contains('выдать') & F.text.lower().contains('бан'))
async def issue_ban_button(message: types.Message, state: FSMContext):
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    await state.update_data(current_action='ban')
    
    await message.answer('😡 напиши юз кому надо вставить бан в попачку)', reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminState.waiting_for_target)

@dp.message(F.text.lower().contains('снять') & F.text.lower().contains('варн'))
async def remove_warn_button(message: types.Message, state: FSMContext):
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    await state.update_data(current_action='unwarn')
    
    await message.answer('🥰 напиши юз кому надо вытащить варн из попачки)', reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminState.waiting_for_target)

@dp.message(F.text.lower().contains('снять') & F.text.lower().contains('бан'))
async def remove_ban_button(message: types.Message, state: FSMContext):
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    await state.update_data(current_action='unban')
    
    await message.answer('🥰 напиши юз кому надо вытащить бан из попачки)', reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminState.waiting_for_target)

@dp.message(F.text.lower().contains('аннулировать') & F.text.lower().contains('баланс'))
async def reset_balance_button(message: types.Message, state: FSMContext):
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    await state.update_data(current_action='annul_balance')
    
    await message.answer('😡 напиши юз с кого надо собрать налог на жизнь)', reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminState.waiting_for_target)

@dp.message(F.text.lower().contains('просмотр') & F.text.lower().contains('бд'))
async def view_database(message: types.Message):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        return
    
    # показываем статистику базы данных
    total_users = len(users)
    
    total_balance = sum(user.get('balance', 0) for user in users.values())
    total_referrals = sum(user.get('referrals', 0) for user in users.values())
    
    max_balance = max((user.get('balance', 0) for user in users.values()), default=0)
    max_k_count = get_max_k_count()
    
    # дополнительная статистика
    active_users = sum(1 for user in users.values() if user.get('balance', 0) > 0)
    
    total_warns = sum(user.get('warns', 0) for user in users.values())
    banned_users = sum(1 for user in users.values() if user.get('banned', False))
    
    db_info = f'📊 <b>статистика базы данных:</b>\n\n'
    db_info += f'👥 <b>всего пользователей:</b> {total_users}\n'
    db_info += f'✅ <b>активных пользователей:</b> {active_users}\n'
    db_info += f'💰 <b>общий баланс:</b> ${format_money(total_balance)}\n'
    db_info += f'👥 <b>всего рефералов:</b> {total_referrals}\n'
    db_info += f'💎 <b>максимальный баланс:</b> ${format_money(max_balance)}\n'
    db_info += f'⚠️ <b>всего варнов:</b> {total_warns}\n'
    db_info += f'🚫 <b>забаненных:</b> {banned_users}\n'
    db_info += f'🔢 <b>лимит сокращений:</b> {max_k_count} букв "к"\n\n'
    
    if total_users == 0:
        db_info += '📝 база данных пуста'
    else:
        db_info += '💡 <b>подсказка:</b> для просмотра списка пользователей используй "экспорт БД"'
    
    await message.answer(db_info, parse_mode='HTML')

@dp.message(F.text.lower().contains('назад'))
async def admin_back_button(message: types.Message):
    
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    await admin_panel(message)

@dp.message(F.text.lower().contains('добавить') & F.text.lower().contains('админ'))
async def add_admin_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки добавления админа"""
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    await message.answer('👑 напиши username пользователя, которого хочешь сделать админом (без @):', reply_markup=ReplyKeyboardRemove())
    
    await state.set_state(AdminState.waiting_for_add_admin_username)

@dp.message(F.text.lower() == '📈 статистика вкладов')
async def admin_bank_stats_button(message: types.Message):
    """обработчик кнопки статистика вкладов в админ панели"""
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    # собираем статистику вкладов
    total_deposits = 0
    
    users_with_deposits = 0
    max_deposit = 0
    
    deposits_list = []
    
    for user_id_key, user_data in users.items():
        deposit = user_data.get('bank_deposit', 0)
    if deposit > 0:
            total_deposits += deposit
            users_with_deposits += 1
            deposits_list.append(deposit)
            if deposit > max_deposit:
                max_deposit = deposit
    
    total_users = len(users)
    percentage_with_deposits = (users_with_deposits / total_users * 100) if total_users > 0 else 0
    
    average_deposit = (total_deposits / users_with_deposits) if users_with_deposits > 0 else 0
    
    stats_text = f'💳 <b>статистика вкладов:</b>\n\n'
    
    stats_text += f'💰 <b>общая сумма вкладов:</b> <b>${format_money(total_deposits)}</b>\n'
    stats_text += f'👥 <b>пользователей с вкладами:</b> <b>{users_with_deposits}/{total_users}</b>\n'
    stats_text += f'📊 <b>процент с вкладами:</b> <b>{percentage_with_deposits:.1f}%</b>\n'
    stats_text += f'💎 <b>максимальный вклад:</b> <b>${format_money(max_deposit)}</b>\n'
    stats_text += f'📈 <b>средний вклад:</b> <b>${format_money(int(average_deposit))}</b>\n\n'
    stats_text += f'💡 <b>подсказка:</b> используй "🏆 топ вкладов" для просмотра лучших игроков'
    
    await message.answer(stats_text, parse_mode='HTML')

@dp.message(F.text.lower() == '🏆 топ вкладов')
async def admin_bank_top_button(message: types.Message):
    """обработчик кнопки топ вкладов в админ панели"""
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    # собираем данные о вкладах
    deposits_data = []
    
    total_deposits = 0
    users_with_deposits = 0
    
    for user_id_key, user_data in users.items():
        deposit = user_data.get('bank_deposit', 0)
    if deposit > 0:
            deposits_data.append({
                'user_id': user_id_key,
                'nick': user_data.get('nick', 'игрок'),
                'tg_username': user_data.get('tg_username', ''),
                'deposit': deposit
            })
            total_deposits += deposit
            users_with_deposits += 1
    
    # сортируем по размеру вклада (убывание)
    deposits_data.sort(key=lambda x: x['deposit'], reverse=True)
    
    top_text = f'🏆 <b>топ-10 по вкладам:</b>\n\n'
    
    medals = ['🥇', '🥈', '🥉']
    
    for i, data in enumerate(deposits_data[:10]):
        if i < 3:
            rank = medals[i]
        else:
            rank = f'{i+1}.'
        
        username = data['tg_username']
        if username:
            username = f'@{username}'
        else:
            username = data['nick']
        
        top_text += f'{rank} <b>{username}</b>\n'
        top_text += f'   💰 <b>${format_money(data["deposit"])}</b>\n\n'
    
    top_text += f'📊 <b>общая сумма вкладов:</b> <b>${format_money(total_deposits)}</b>\n'
    top_text += f'👥 <b>всего с вкладами:</b> <b>{users_with_deposits}</b>'
    
    await message.answer(top_text, parse_mode='HTML')

# Обработчики состояний админки

# === рассылка ===
@dp.message(F.text.lower() == 'рассылка 📣')
async def start_broadcast(message: types.Message, state: FSMContext):
    # только в личке и только админы
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    # сначала спрашиваем куда слать
    kb = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='всем в лс', callback_data='bc_target_dm')],
        [InlineKeyboardButton(text='во все чаты', callback_data='bc_target_chats')],
    
    [InlineKeyboardButton(text='во все чаты (кроме основного)', callback_data='bc_target_chats_ex_main')],
        [InlineKeyboardButton(text='отмена', callback_data='bc_cancel')]
    
    ])
    await message.answer('куда отправляем?', reply_markup=kb)
    
    await state.set_state(AdminState.waiting_for_broadcast_target)

@dp.message(AdminState.waiting_for_broadcast_text)
async def broadcast_text_received(message: types.Message, state: FSMContext):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    # отмена
    if (message.text or '').strip().lower() == 'отмена':
        await state.clear()
        await message.answer('рассылку отменил')
        return
    # поддержка текста и фото с подписью, учитываем разметку от клиента и сырые HTML-теги
    has_entities = bool(getattr(message, 'entities', None) or getattr(message, 'caption_entities', None))
    
    if has_entities:
        # есть форматирование от телеги — берём html-версию, которая уже соберёт теги
        text = (getattr(message, 'caption_html', None)
    
    or getattr(message, 'html_text', None)
                or (message.caption or message.text or ''))
    else:
        # нет entities — оставляем сырой ввод, чтобы работали вручную написанные теги <b> и т.д.
        text = (message.caption or message.text or '')
    
    # исправляем экранированные HTML-теги
    text = text.replace('&amp;lt;', '<').replace('&amp;gt;', '>')
    
    text = text.replace('&lt;', '<').replace('&gt;', '>')
    
    # проверяем и исправляем основные HTML-теги
    html_tags = {
    
    '&amp;lt;b&amp;gt;': '<b>', '&amp;lt;/b&amp;gt;': '</b>',
        '&amp;lt;i&amp;gt;': '<i>', '&amp;lt;/i&amp;gt;': '</i>',
        '&amp;lt;u&amp;gt;': '<u>', '&amp;lt;/u&amp;gt;': '</u>',
        '&amp;lt;s&amp;gt;': ' ', '&amp;lt;/s&amp;gt;': ' ',
        '&amp;lt;code&amp;gt;': '<code>', '&amp;lt;/code&amp;gt;': '</code>',
        '&amp;lt;a href=&amp;quot;': '<a href="', '&amp;lt;/a&amp;gt;': '</a>',
    
    '&amp;lt;blockquote&amp;gt;': '<blockquote>', '&amp;lt;/blockquote&amp;gt;': '</blockquote>',
        '&amp;quot;': '"', '&amp;amp;': '&'
    }
    
    for escaped, original in html_tags.items():
        text = text.replace(escaped, original)
    
    photo_id = None
    if getattr(message, 'photo', None):
        try:
            photo_id = message.photo[-1].file_id
        except Exception:
            photo_id = None
    
    await state.update_data(broadcast_text=text, broadcast_photo_id=photo_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='добавить кнопку', callback_data='bc_add_button')],
        [InlineKeyboardButton(text='без кнопки — отправляем', callback_data='bc_no_button')],
    
    [InlineKeyboardButton(text='отмена', callback_data='bc_cancel')]
    ])
    await message.answer('добавить кнопку?', reply_markup=kb)

@dp.callback_query(lambda c: c.data in ['bc_add_button','bc_no_button','bc_cancel'])
async def broadcast_button_choice(callback: types.CallbackQuery, state: FSMContext):
    
    user_id = callback.from_user.id
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
        return
    if callback.data == 'bc_cancel':
        await state.clear()
        await callback.message.edit_text('рассылку отменил')
        await callback.answer('рассылка отменена', show_alert=True)
        return
    if callback.data == 'bc_no_button':
        await callback.answer('кнопка не добавлена', show_alert=True)
        await start_broadcast_send(callback.message, state, add_button=False)
        return
    
    # add button
    await state.set_state(AdminState.waiting_for_broadcast_button_data)
    await callback.message.edit_text('пришли кнопку так:\nтекст | ссылка\nнапример:\nперейти | https://example.com')
    await callback.answer('введите данные кнопки', show_alert=True)

@dp.message(AdminState.waiting_for_broadcast_button_data)
async def broadcast_button_data_received(message: types.Message, state: FSMContext):
    if message.chat.type != 'private':
        return
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    raw = (message.text or '').strip()
    
    if '|' not in raw:
        await message.answer('нужен формат: текст | ссылка')
        return
    btn_text, btn_url = [p.strip() for p in raw.split('|', 1)]
    
    if not btn_text or not btn_url or not (btn_url.startswith('http://') or btn_url.startswith('https://')):
        await message.answer('ссылка должна начинаться с http(s)://')
        return
    await state.update_data(broadcast_button={'text': btn_text, 'url': btn_url})
    
    await start_broadcast_send(message, state, add_button=True)

async def start_broadcast_send(message_or_cb_msg, state: FSMContext, add_button: bool):
    data = await state.get_data()
    
    text = data.get('broadcast_text', '')
    
    # дополнительная проверка и исправление HTML-тегов
    if text:
        # исправляем экранированные HTML-теги
        text = text.replace('&amp;lt;', '<').replace('&amp;gt;', '>')
        text = text.replace('&lt;', '<').replace('&gt;', '>')
        
        # проверяем и исправляем основные HTML-теги
        html_tags = {
            '&amp;lt;b&amp;gt;': '<b>', '&amp;lt;/b&amp;gt;': '</b>',
            '&amp;lt;i&amp;gt;': '<i>', '&amp;lt;/i&amp;gt;': '</i>',
            '&amp;lt;u&amp;gt;': '<u>', '&amp;lt;/u&amp;gt;': '</u>',
            '&amp;lt;s&amp;gt;': ' ', '&amp;lt;/s&amp;gt;': ' ',
            '&amp;lt;code&amp;gt;': '<code>', '&amp;lt;/code&amp;gt;': '</code>',
            '&amp;lt;a href=&amp;quot;': '<a href="', '&amp;lt;/a&amp;gt;': '</a>',
            '&amp;lt;blockquote&amp;gt;': '<blockquote>', '&amp;lt;/blockquote&amp;gt;': '</blockquote>',
            '&amp;quot;': '"', '&amp;amp;': '&'
        }
        
        for escaped, original in html_tags.items():
            text = text.replace(escaped, original)
    
    button = data.get('broadcast_button') if add_button else None
    # подтверждение
    kb = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='да, отправляем', callback_data='bc_confirm')],
        [InlineKeyboardButton(text='отмена', callback_data='bc_cancel')]
    
    ])
    preview_kb = None
    
    if button:
        preview_kb = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text=button['text'], url=button['url'])]
        ])
    try:
        await message_or_cb_msg.answer('вот так это будет выглядеть. ок?', reply_markup=preview_kb if preview_kb else None, parse_mode='HTML', link_preview_options=types.LinkPreviewOptions(is_disabled=True))
        
        photo_id = data.get('broadcast_photo_id')
        if photo_id:
            await bot.send_photo(message_or_cb_msg.chat.id, photo_id, caption=text, parse_mode='HTML', reply_markup=preview_kb if preview_kb else None)
        else:
            await message_or_cb_msg.answer(text, reply_markup=preview_kb if preview_kb else None, parse_mode='HTML', link_preview_options=types.LinkPreviewOptions(is_disabled=True))
    
    except Exception:
        await message_or_cb_msg.answer('превью не отдалось, но рассылка отправится нормально.')
    await message_or_cb_msg.answer('подтверди отправку', reply_markup=kb)
    
    await state.update_data(broadcast_preview_has_button=bool(button))
@dp.callback_query(lambda c: c.data == 'bc_confirm')
async def broadcast_confirm(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer()
        return
    data = await state.get_data()
    
    text = data.get('broadcast_text', '')
    
    # дополнительная проверка и исправление HTML-тегов перед отправкой
    if text:
        # исправляем экранированные HTML-теги
        text = text.replace('&amp;lt;', '<').replace('&amp;gt;', '>')
        text = text.replace('&lt;', '<').replace('&gt;', '>')
        
        # проверяем и исправляем основные HTML-теги
        html_tags = {
            '&amp;lt;b&amp;gt;': '<b>', '&amp;lt;/b&amp;gt;': '</b>',
            '&amp;lt;i&amp;gt;': '<i>', '&amp;lt;/i&amp;gt;': '</i>',
            '&amp;lt;u&amp;gt;': '<u>', '&amp;lt;/u&amp;gt;': '</u>',
            '&amp;lt;s&amp;gt;': ' ', '&amp;lt;/s&amp;gt;': ' ',
            '&amp;lt;code&amp;gt;': '<code>', '&amp;lt;/code&amp;gt;': '</code>',
            '&amp;lt;a href=&amp;quot;': '<a href="', '&amp;lt;/a&amp;gt;': '</a>',
            '&amp;lt;blockquote&amp;gt;': '<blockquote>', '&amp;lt;/blockquote&amp;gt;': '</blockquote>',
            '&amp;quot;': '"', '&amp;amp;': '&'
        }
        
        for escaped, original in html_tags.items():
            text = text.replace(escaped, original)
    
    has_button = data.get('broadcast_preview_has_button', False)
    button = data.get('broadcast_button') if has_button else None
    
    chosen_target = data.get('broadcast_target')
    target_mode = 'dm' if chosen_target == 'bc_target_dm' else 'chats'
    await callback.message.edit_text('ок, отправляю всем. это может занять немного времени.')
    await callback.answer()
    
    # собираем список получателей
    if target_mode == 'dm':
        recipients = [int(uid) for uid in users.keys()]
    
    else:
        recipients = list(bot_chats)
    
    # исключаем основной чат, если выбрано "кроме основного"
        if chosen_target == 'bc_target_chats_ex_main':
            global MAIN_CHAT_ID
            try:
                if MAIN_CHAT_ID is None and MAIN_CHAT_USERNAME:
                    chat = await bot.get_chat(f"@{MAIN_CHAT_USERNAME}")
                    MAIN_CHAT_ID = int(chat.id)
            except Exception:
                pass
            if MAIN_CHAT_ID is not None:
                recipients = [cid for cid in recipients if int(cid) != int(MAIN_CHAT_ID)]
    total = len(recipients)
    
    sent = 0
    failed = 0
    
    kb = None
    if button:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button['text'], url=button['url'])]])
    
    # шлём пачками, чтобы не словить лимиты
    for idx, uid in enumerate(recipients):
        try:
            photo_id = data.get('broadcast_photo_id')
            if photo_id:
                await bot.send_photo(int(uid), photo_id, caption=text, parse_mode='HTML', reply_markup=kb)
            else:
                await bot.send_message(int(uid), text, parse_mode='HTML', reply_markup=kb, link_preview_options=types.LinkPreviewOptions(is_disabled=True))
            sent += 1
        except Exception:
            failed += 1
        # лёгкая пауза каждые 25 сообщений
        if (idx + 1) % 25 == 0:
            try:
                await callback.message.edit_text(f'отправляю... {sent}/{total}, ошибок: {failed}')
            except Exception:
                pass
            await asyncio.sleep(0.5)
    
    summary = f'готово. отправлено: {sent}/{total}, не доставлено: {failed}'
    
    try:
        await callback.message.edit_text(summary)
    except Exception:
        await bot.send_message(user_id, summary)
    await state.clear()
@dp.message(AdminState.waiting_for_warn_reason)
async def warn_reason_entered(message: types.Message, state: FSMContext):
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    reason = message.text.strip()
    
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    
    await message.answer('напиши срок варна (например: 1 день, 1 неделя, навсегда)')
    await state.update_data(warn_reason=reason)
    
    await state.set_state(AdminState.waiting_for_warn_duration)

@dp.message(AdminState.waiting_for_warn_duration)
async def warn_duration_entered(message: types.Message, state: FSMContext):
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id not in ADMIN_IDS:
        return
    
    duration = message.text.strip()
    
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    
    reason = data.get('warn_reason')
    
    # Выдаём варн
    success, message_text = await give_warn(target_user_id, reason, duration)
    
    await message.answer(message_text)
    
    # Возвращаем админ панель
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='выдать варн ⚠️'), KeyboardButton(text='выдать бан 🚫')],
        [KeyboardButton(text='снять варн ✅'), KeyboardButton(text='снять бан ✅')],
    
    [KeyboardButton(text='аннулировать баланс 💰'), KeyboardButton(text='выдать деньги 💵')],
        [KeyboardButton(text='пробить юз 🔍'), KeyboardButton(text='просмотр БД 📊')],
    
    [KeyboardButton(text='экспорт БД 📋'), KeyboardButton(text='очистить БД 🗑️')],
        [KeyboardButton(text='назад ⬅️')]
    
    ])
    await message.answer('🔧 админ панель', reply_markup=markup)
    
    await state.clear()

@dp.message(AdminState.waiting_for_ban_date)
async def ban_date_entered(message: types.Message, state: FSMContext):
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id not in ADMIN_IDS:
        return
    
    ban_date = message.text.strip()
    
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    
    # Выдаём бан
    success, message_text = await give_ban_simple(target_user_id, ban_date)
    
    await message.answer(message_text)
    
    # Возвращаем админ панель
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='выдать варн ⚠️'), KeyboardButton(text='выдать бан 🚫')],
        [KeyboardButton(text='снять варн ✅'), KeyboardButton(text='снять бан ✅')],
    
    [KeyboardButton(text='аннулировать баланс 💰'), KeyboardButton(text='выдать деньги 💵')],
        [KeyboardButton(text='пробить юз 🔍'), KeyboardButton(text='просмотр БД 📊')],
    
    [KeyboardButton(text='экспорт БД 📋'), KeyboardButton(text='очистить БД 🗑️')],
        [KeyboardButton(text='назад ⬅️')]
    
    ])
    await message.answer('🔧 админ панель', reply_markup=markup)
    
    await state.clear()

# Обработчик для кнопки "бан навсегда"
@dp.callback_query(lambda c: c.data == 'ban_forever')
async def ban_forever_callback(callback_query: types.CallbackQuery, state: FSMContext):
    # Проверяем, что это личное сообщение
    if callback_query.message.chat.type != 'private':
        return
    
    user_id = callback_query.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    data = await state.get_data()
    
    target_user_id = data.get('target_user_id')
    
    # Выдаём бан навсегда
    success, message_text = await give_ban_simple(target_user_id, 'навсегда')
    
    await callback_query.message.answer(message_text)
    
    # Возвращаем админ панель
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='выдать варн ⚠️'), KeyboardButton(text='выдать бан 🚫')],
        [KeyboardButton(text='снять варн ✅'), KeyboardButton(text='снять бан ✅')],
    
    [KeyboardButton(text='аннулировать баланс 💰'), KeyboardButton(text='выдать деньги 💵')],
        [KeyboardButton(text='пробить юз 🔍'), KeyboardButton(text='просмотр БД 📊')],
    
    [KeyboardButton(text='экспорт БД 📋'), KeyboardButton(text='очистить БД 🗑️')],
        [KeyboardButton(text='назад ⬅️')]
    
    ])
    await callback_query.message.answer('🔧 админ панель', reply_markup=markup)
    
    await state.clear()
    await callback_query.answer()

@dp.message(AdminState.waiting_for_ban_reason)
async def ban_reason_entered(message: types.Message, state: FSMContext):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id not in ADMIN_IDS:
        return
    
    reason = message.text.strip()
    
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    
    await message.answer('напиши срок бана (например: 1 день, 1 неделя, навсегда)', reply_markup=ReplyKeyboardRemove())
    await state.update_data(ban_reason=reason)
    
    await state.set_state(AdminState.waiting_for_ban_duration)

@dp.message(AdminState.waiting_for_ban_duration)
async def ban_duration_entered(message: types.Message, state: FSMContext):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id not in ADMIN_IDS:
        return
    
    duration = message.text.strip()
    
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    
    reason = data.get('ban_reason')
    
    # Выдаём бан
    success, message_text = await give_ban(target_user_id, reason, duration)
    
    await message.answer(message_text)
    
    # Возвращаем админ панель
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='выдать варн ⚠️'), KeyboardButton(text='выдать бан 🚫')],
        [KeyboardButton(text='снять варн ✅'), KeyboardButton(text='снять бан ✅')],
    
    [KeyboardButton(text='аннулировать баланс 💰'), KeyboardButton(text='выдать деньги 💵')],
        [KeyboardButton(text='пробить юз 🔍'), KeyboardButton(text='просмотр БД 📊')],
    
    [KeyboardButton(text='экспорт БД 📋'), KeyboardButton(text='очистить БД 🗑️')],
        [KeyboardButton(text='назад ⬅️')]
    
    ])
    await message.answer('🔧 админ панель', reply_markup=markup)
    
    await state.clear()

@dp.message(AdminState.waiting_for_unwarn_count)
async def unwarn_count_entered(message: types.Message, state: FSMContext):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id not in ADMIN_IDS:
        return
    
    count = message.text.strip()
    
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    
    # Снимаем варн(ы)
    success, message_text = await remove_warn(target_user_id, count)
    
    await message.answer(message_text)
    
    # Возвращаем админ панель
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='выдать варн ⚠️'), KeyboardButton(text='выдать бан 🚫')],
        [KeyboardButton(text='снять варн ✅'), KeyboardButton(text='снять бан ✅')],
    
    [KeyboardButton(text='аннулировать баланс 💰'), KeyboardButton(text='выдать деньги 💵')],
        [KeyboardButton(text='пробить юз 🔍'), KeyboardButton(text='просмотр БД 📊')],
    
    [KeyboardButton(text='экспорт БД 📋')],
        [KeyboardButton(text='назад ⬅️')]
    
    ])
    await message.answer('🔧 админ панель', reply_markup=markup)
    
    await state.clear()

@dp.message(AdminState.waiting_for_balance_amount)
async def balance_amount_entered(message: types.Message, state: FSMContext):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id not in ADMIN_IDS:
        return
    
    amount_text = message.text.strip()
    
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    
    # Парсим сумму
    if amount_text.lower() == 'все':
        amount = -1
    
    else:
        try:
            amount = parse_amount(amount_text)
        except:
            await message.answer('неверный формат суммы')
            await state.clear()
            return
    
    # проверяем, что сумма больше 0 (кроме команды "все")
    if amount != -1 and amount <= 0:
        await message.answer('сумма должна быть больше 0')
        await state.clear()
        return
    
    # Аннулируем баланс
    success, message_text = await annul_balance(target_user_id, amount)
    
    await message.answer(message_text)
    
    # Возвращаем админ панель
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='выдать варн ⚠️'), KeyboardButton(text='выдать бан 🚫')],
        [KeyboardButton(text='снять варн ✅'), KeyboardButton(text='снять бан ✅')],
    
    [KeyboardButton(text='аннулировать баланс 💰'), KeyboardButton(text='выдать деньги 💵')],
        [KeyboardButton(text='пробить юз 🔍'), KeyboardButton(text='просмотр БД 📊')],
    
    [KeyboardButton(text='экспорт БД 📋'), KeyboardButton(text='очистить БД 🗑️')],
        [KeyboardButton(text='назад ⬅️')]
    
    ])
    await message.answer('🔧 админ панель', reply_markup=markup)
    
    await state.clear()

# Функции для работы с варнами/банами
async def give_warn(target_user_id: int, reason: str, duration: str):
    """Выдаёт варн пользователю"""
    if target_user_id not in users:
        return False, "пользователь не найден"
    
    user_data = users[target_user_id]
    
    current_warns = user_data.get('warns', 0)
    user_data['warns'] = current_warns + 1
    user_data['warn_reason'] = reason
    user_data['warn_date'] = str(datetime.datetime.now())
    user_data['warn_duration'] = duration
    
    save_users()
    
    # Отправляем уведомление пользователю
    try:
        await bot.send_message(
            target_user_id,
            f"🚨 <b>твой аккаунт получил предупреждение!</b>\n\n"
            f"⚠️ <b>причина:</b> {reason}\n"
            f"⏰ <b>срок:</b> {duration}\n"
            f"📊 <b>всего варнов:</b> {user_data['warns']}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML'
    
    )
    except Exception as e:
        print(f"Ошибка отправки уведомления о варне: {e}")
    
    return True, f"варн выдан пользователю {user_data['nick']}"

async def give_ban(target_user_id: int, reason: str, duration: str):
    """Выдаёт бан пользователю"""
    if target_user_id not in users:
        return False, "пользователь не найден"
    
    user_data = users[target_user_id]
    
    user_data['banned'] = True
    user_data['ban_reason'] = reason
    user_data['ban_date'] = str(datetime.datetime.now())
    user_data['ban_duration'] = duration
    
    save_users()
    
    # Отправляем уведомление пользователю
    try:
        await bot.send_message(
            target_user_id,
            f"�� <b>твой аккаунт заблокирован администрацией!</b>\n\n"
            f"❌ <b>причина:</b> {reason}\n"
            f"⏰ <b>срок:</b> {duration}\n"
            f"📅 <b>дата блокировки:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML'
    
    )
    except Exception as e:
        print(f"Ошибка отправки уведомления о бане: {e}")
    
    return True, f"бан выдан пользователю {user_data['nick']}"

async def remove_warn(target_user_id: int, count: str):
    """Снимает варн(ы) с пользователя"""
    if target_user_id not in users:
        return False, "пользователь не найден"
    
    user_data = users[target_user_id]
    
    current_warns = user_data.get('warns', 0)
    
    if count == 'все':
        removed_count = current_warns
        user_data['warns'] = 0
    else:
        try:
            removed_count = int(count)
            user_data['warns'] = max(0, current_warns - removed_count)
        except ValueError:
            return False, "неверное количество варнов"
    
    save_users()
    
    # Отправляем уведомление пользователю
    try:
        await bot.send_message(
            target_user_id,
            f"✅ <b>с твоего аккаунта снято предупреждение!</b>\n\n"
            f"🎉 <b>снято варнов:</b> {count}\n"
            f"📊 <b>осталось варнов:</b> {user_data['warns']}\n"
            f"📅 <b>дата снятия:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"😊 теперь ты можешь спокойно играть!\n"
            f"🙏 извините за неудобство",
            parse_mode='HTML'
    
    )
    except Exception as e:
        print(f"Ошибка отправки уведомления о снятии варна: {e}")
    
    return True, f"снято {removed_count} варн(ов) с пользователя {user_data['nick']}"

async def remove_ban(target_user_id: int):
    """Снимает бан с пользователя"""
    if target_user_id not in users:
        return False, "пользователь не найден"
    
    user_data = users[target_user_id]
    
    if not user_data.get('banned', False):
        return False, "пользователь не забанен"
    
    user_data['banned'] = False
    user_data.pop('ban_reason', None)
    user_data.pop('ban_date', None)
    user_data.pop('ban_duration', None)
    
    save_users()
    
    # Отправляем уведомление пользователю
    try:
        await bot.send_message(
            target_user_id,
            f"✅ <b>с твоего аккаунта снята блокировка!</b>\n\n"
            f"🎉 <b>статус:</b> разблокирован\n"
            f"📅 <b>дата разблокировки:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"😊 теперь ты можешь спокойно играть!\n"
            f"🙏 извините за неудобство",
            parse_mode='HTML'
    
    )
    except Exception as e:
        print(f"Ошибка отправки уведомления о снятии бана: {e}")
    
    return True, f"бан снят с пользователя {user_data['nick']}"

async def annul_balance(target_user_id: int, amount: int):
    """Аннулирует баланс пользователя"""
    if target_user_id not in users:
        return False, "пользователь не найден"
    
    user_data = users[target_user_id]
    
    current_balance = user_data.get('balance', 0)
    
    if amount == -1:  # аннулировать весь баланс
        user_data['balance'] = 0
        annuled_amount = current_balance
    
    else:
        user_data['balance'] = max(0, current_balance - amount)
        annuled_amount = min(amount, current_balance)
    
    save_users()
    
    # Отправляем уведомление пользователю
    try:
        await bot.send_message(
            target_user_id,
            f"💰 <b>с твоего баланса сняты средства!</b>\n\n"
            f"❌ <b>снято:</b> ${format_money(annuled_amount)}\n"
            f"💳 <b>новый баланс:</b> ${format_money(user_data['balance'])}\n"
            f"📅 <b>дата операции:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"💬 по вопросам обращайтесь в поддержку\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML'
    
    )
    except Exception as e:
        print(f"Ошибка отправки уведомления об аннулировании баланса: {e}")
    
    return True, f"аннулировано ${format_money(annuled_amount)} у пользователя {user_data['nick']}"
# Новые функции для простых админских действий
async def give_warn_simple(target_user_id: int):
    """Выдаёт варн пользователю (простая версия)"""
    if target_user_id not in users:
        return False, "пользователь не найден"
    
    user_data = users[target_user_id]
    
    current_warns = user_data.get('warns', 0)
    
    # Проверяем лимит варнов
    if current_warns >= 3:
        # Если 3 варна - бан навсегда
        user_data['banned'] = True
        user_data['ban_reason'] = 'превышен лимит варнов (3/3)'
        user_data['ban_date'] = str(datetime.datetime.now())
        user_data['ban_duration'] = 'навсегда'
        
        save_users()
        
        # Уведомляем пользователя о бане
        try:
            markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
            ])
            await bot.send_message(
                target_user_id,
                f"🚫 <b>твой аккаунт заблокирован навсегда!</b>\n\n"
                f"❌ <b>причина:</b> превышен лимит варнов (3/3)\n"
                f"📅 <b>дата блокировки:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"💬 обжаловать наказание можно по кнопке ниже\n"
                f"🔗 <b>поддержка:</b> @daisicxTp_bot",
                parse_mode='HTML',
    
    reply_markup=markup
            )
        except Exception as e:
            print(f"Ошибка отправки уведомления о бане: {e}")
        
        return True, f"пользователь {user_data['nick']} забанен навсегда за превышение лимита варнов"
    
    # Выдаём варн
    user_data['warns'] = current_warns + 1
    user_data['warn_date'] = str(datetime.datetime.now())
    
    save_users()
    
    # Уведомляем пользователя
    try:
        markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        await bot.send_message(
            target_user_id,
            f"⚠️ <b>твой аккаунт получил предупреждение!</b>\n\n"
            f"📊 <b>всего варнов:</b> {user_data['warns']}/3\n"
            f"📅 <b>дата предупреждения:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"⚠️ <b>внимание:</b> при получении 3-го варна аккаунт будет заблокирован навсегда!\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
    
    reply_markup=markup
        )
    except Exception as e:
        print(f"Ошибка отправки уведомления о варне: {e}")
    
    return True, f"варн выдан пользователю {user_data['nick']} ({user_data['warns']}/3)"

async def give_ban_simple(target_user_id: int, ban_date: str):
    """Выдаёт бан пользователю (простая версия)"""
    if target_user_id not in users:
        return False, "пользователь не найден"
    
    user_data = users[target_user_id]
    
    user_data['banned'] = True
    user_data['ban_reason'] = 'блокировка администрацией'
    user_data['ban_date'] = str(datetime.datetime.now())
    user_data['ban_duration'] = ban_date
    
    save_users()
    
    # Уведомляем пользователя
    try:
        markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        await bot.send_message(
            target_user_id,
            f"🚫 <b>твой аккаунт заблокирован администрацией!</b>\n\n"
            f"⏰ <b>срок блокировки:</b> {ban_date}\n"
            f"📅 <b>дата блокировки:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
    
    reply_markup=markup
        )
    except Exception as e:
        print(f"Ошибка отправки уведомления о бане: {e}")
    
    return True, f"бан выдан пользователю {user_data['nick']} до {ban_date}"

async def remove_warn_simple(target_user_id: int):
    """Снимает варн с пользователя (простая версия)"""
    if target_user_id not in users:
        return False, "пользователь не найден"
    
    user_data = users[target_user_id]
    
    current_warns = user_data.get('warns', 0)
    
    if current_warns <= 0:
        return False, "у пользователя нет варнов"
    
    user_data['warns'] = current_warns - 1
    save_users()
    
    # Уведомляем пользователя
    try:
        await bot.send_message(
            target_user_id,
            f"✅ <b>с твоего аккаунта снято предупреждение!</b>\n\n"
            f"📊 <b>осталось варнов:</b> {user_data['warns']}/3\n"
            f"📅 <b>дата снятия:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"😊 теперь ты можешь спокойно играть!\n"
            f"🙏 извините за неудобство",
            parse_mode='HTML'
    
    )
    except Exception as e:
        print(f"Ошибка отправки уведомления о снятии варна: {e}")
    
    return True, f"снят 1 варн с пользователя {user_data['nick']} ({user_data['warns']}/3)"

async def remove_ban_simple(target_user_id: int):
    """Снимает бан с пользователя (простая версия)"""
    if target_user_id not in users:
        return False, "пользователь не найден"
    
    user_data = users[target_user_id]
    
    if not user_data.get('banned', False):
        return False, "пользователь не забанен"
    
    user_data['banned'] = False
    user_data.pop('ban_reason', None)
    user_data.pop('ban_date', None)
    user_data.pop('ban_duration', None)
    
    save_users()
    
    # Уведомляем пользователя
    try:
        await bot.send_message(
            target_user_id,
            f"✅ <b>с твоего аккаунта снята блокировка!</b>\n\n"
            f"🎉 <b>статус:</b> разблокирован\n"
            f"📅 <b>дата разблокировки:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"😊 теперь ты можешь спокойно играть!\n"
            f"🙏 извините за неудобство",
            parse_mode='HTML'
    
    )
    except Exception as e:
        print(f"Ошибка отправки уведомления о снятии бана: {e}")
    
    return True, f"бан снят с пользователя {user_data['nick']}"

async def annul_balance_simple(target_user_id: int):
    """Аннулирует баланс пользователя (простая версия)"""
    if target_user_id not in users:
        return False, "пользователь не найден"
    
    user_data = users[target_user_id]
    
    current_balance = user_data.get('balance', 0)
    
    user_data['balance'] = 0
    save_users()
    
    # Уведомляем пользователя
    try:
        markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='💬 обратиться в поддержку', url='https://t.me/daisicxTp_bot')]
        ])
        await bot.send_message(
            target_user_id,
            f"💰 <b>с твоего баланса сняты все средства!</b>\n\n"
            f"❌ <b>снято:</b> ${format_money(current_balance)}\n"
            f"💳 <b>новый баланс:</b> $0\n"
            f"📅 <b>дата операции:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"💬 по вопросам обращайтесь в поддержку\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
    
    reply_markup=markup
        )
    except Exception as e:
        print(f"Ошибка отправки уведомления об аннулировании баланса: {e}")
    
    return True, f"аннулирован баланс пользователя {user_data['nick']} (${format_money(current_balance)})"

# === тестовая команда для проверки изображений рулетки ===
@dp.message(Command('test_roulette'))
async def test_roulette_images(message: types.Message):
    """тестирует создание изображений рулетки"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    await message.answer('🧪 Тестирую создание изображений рулетки...')
    
    try:
        # Тестируем создание изображения для красного числа
        red_image = create_roulette_result_image(7, 'red', 'красное', 1000, True, 2, 2000)
        
        if red_image and os.path.exists(red_image):
            await bot.send_photo(
                message.chat.id,
                types.FSInputFile(red_image),
                caption="✅ Тест красного числа (7)"
            )
            os.remove(red_image)
        else:
            await message.answer('❌ Ошибка создания изображения для красного числа')
        
        # Тестируем создание изображения для черного числа
        black_image = create_roulette_result_image(8, 'black', 'черное', 1000, True, 2, 2000)
        
        if black_image and os.path.exists(black_image):
            await bot.send_photo(
                message.chat.id,
                types.FSInputFile(black_image),
                caption="✅ Тест черного числа (8)"
            )
            os.remove(black_image)
        else:
            await message.answer('❌ Ошибка создания изображения для черного числа')
        
        # Тестируем создание изображения для зеро
        zero_image = create_roulette_result_image(0, 'green', 'зеро', 1000, True, 36, 36000)
        
        if zero_image and os.path.exists(zero_image):
            await bot.send_photo(
                message.chat.id,
                types.FSInputFile(zero_image),
                caption="✅ Тест зеро (0)"
            )
            os.remove(zero_image)
        else:
            await message.answer('❌ Ошибка создания изображения для зеро')
        
        await message.answer('🎯 Тестирование завершено!')
        
    except Exception as e:
        await message.answer(f'❌ Ошибка при тестировании: {e}')

# === callback обработчики для налога и комиссий ===
@dp.callback_query(lambda c: c.data == 'wealth_tax_info')
async def wealth_tax_info_callback(callback: types.CallbackQuery):
    """Показывает информацию о налоге на богатство"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
        return
    
    await callback.message.edit_text(
        f'📊 <b>информация о налоге на богатство</b>\n\n'
        f'💰 <b>текущий процент:</b> {WEALTH_TAX_PERCENT}%\n'
        f'⏰ <b>периодичность:</b> каждый час\n'
        f'👥 <b>применяется к:</b> топ-15 игрокам\n'
        f'💸 <b>налог берется с:</b> текущего баланса\n\n'
        f'💡 <b>как работает:</b>\n'
        f'• каждый час автоматически списывается налог\n'
        f'• налог = {WEALTH_TAX_PERCENT}% от баланса\n'
    
    f'• уведомления отправляются игрокам\n'
        f'• отчет отправляется администраторам',
        parse_mode='HTML',
    
    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='⬅️ назад', callback_data='wealth_tax_back')]
    
    ])
    )

@dp.callback_query(lambda c: c.data == 'wealth_tax_write')
async def wealth_tax_write_callback(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает новый процент налога"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
        return
    
    await callback.message.edit_text(
        '📝 <b>изменение процента налога</b>\n\n'
        f'💰 <b>текущий процент:</b> {WEALTH_TAX_PERCENT}%\n\n'
        'напиши новый процент (от 1 до 50):',
        parse_mode='HTML',
    
    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='❌ отмена', callback_data='wealth_tax_cancel')]
    
    ])
    )
    
    await state.set_state(AdminState.waiting_for_tax_percent)
    await callback.answer('введите новый процент налога', show_alert=True)

@dp.callback_query(lambda c: c.data == 'wealth_tax_cancel')
async def wealth_tax_cancel_callback(callback: types.CallbackQuery):
    """Отменяет настройку налога"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
        return
    
    await callback.message.edit_text(
        '❌ <b>настройка налога отменена</b>\n\n'
        f'💰 <b>текущий процент:</b> {WEALTH_TAX_PERCENT}%',
        parse_mode='HTML'
    )
    await callback.answer('настройка налога отменена', show_alert=True)

@dp.callback_query(lambda c: c.data == 'transfer_commission_info')
async def transfer_commission_info_callback(callback: types.CallbackQuery):
    """Показывает информацию о комиссии переводов"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
        return
    
    await callback.message.edit_text(
        f'📊 <b>информация о комиссии переводов</b>\n\n'
        f'💰 <b>текущий процент:</b> {TRANSFER_COMMISSION_TOP20}%\n'
        f'👥 <b>применяется к:</b> топ-20 игрокам\n'
        f'💸 <b>комиссия берется с:</b> суммы перевода\n\n'
        f'💡 <b>как работает:</b>\n'
        f'• только топ-20 игроки платят комиссию\n'
        f'• комиссия = {TRANSFER_COMMISSION_TOP20}% от суммы перевода\n'
    
    f'• получатель получает сумму минус комиссия\n'
        f'• обычные игроки переводят без комиссии',
        parse_mode='HTML',
    
    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='⬅️ назад', callback_data='transfer_commission_back')]
    
    ])
    )

@dp.callback_query(lambda c: c.data == 'transfer_commission_write')
async def transfer_commission_write_callback(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает новый процент комиссии"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
        return
    
    await callback.message.edit_text(
        '📝 <b>изменение процента комиссии</b>\n\n'
        f'💰 <b>текущий процент:</b> {TRANSFER_COMMISSION_TOP20}%\n\n'
        'напиши новый процент (от 1 до 50):',
        parse_mode='HTML',
    
    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='❌ отмена', callback_data='transfer_commission_cancel')]
    
    ])
    )
    
    await state.set_state(AdminState.waiting_for_commission_percent)
    await callback.answer('введите новый процент комиссии', show_alert=True)

@dp.callback_query(lambda c: c.data == 'transfer_commission_cancel')
async def transfer_commission_cancel_callback(callback: types.CallbackQuery):
    """Отменяет настройку комиссии"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
        return
    
    await callback.message.edit_text(
        '❌ <b>настройка комиссии отменена</b>\n\n'
        f'💰 <b>текущий процент:</b> {TRANSFER_COMMISSION_TOP20}%',
        parse_mode='HTML'
    )
    await callback.answer('настройка комиссии отменена', show_alert=True)

@dp.callback_query(lambda c: c.data == 'wealth_tax_back')
async def wealth_tax_back_callback(callback: types.CallbackQuery):
    """Возврат к настройкам налога"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
        return
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text=f'📊 текущий процент: {WEALTH_TAX_PERCENT}%', callback_data='wealth_tax_info')],
        [InlineKeyboardButton(text='📝 написать процент', callback_data='wealth_tax_write')],
    
    [InlineKeyboardButton(text='❌ отмена', callback_data='wealth_tax_cancel')]
    ])
    
    await callback.message.edit_text(
        f'⚙️ <b>настройки налога на богатство</b>\n\n'
        f'💰 <b>текущий процент:</b> {WEALTH_TAX_PERCENT}%\n'
        f'⏰ <b>периодичность:</b> каждый час\n'
        f'👥 <b>применяется к:</b> топ-15 игрокам\n\n'
        f'выбери действие:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.callback_query(lambda c: c.data == 'transfer_commission_back')
async def transfer_commission_back_callback(callback: types.CallbackQuery):
    """Возврат к настройкам комиссии"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
        return
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text=f'📊 текущий процент: {TRANSFER_COMMISSION_TOP20}%', callback_data='transfer_commission_info')],
        [InlineKeyboardButton(text='📝 написать процент', callback_data='transfer_commission_write')],
    
    [InlineKeyboardButton(text='❌ отмена', callback_data='transfer_commission_cancel')]
    ])
    
    await callback.message.edit_text(
        f'⚙️ <b>настройки комиссии переводов</b>\n\n'
        f'💰 <b>текущий процент:</b> {TRANSFER_COMMISSION_TOP20}%\n'
        f'👥 <b>применяется к:</b> топ-20 игрокам\n'
        f'💸 <b>комиссия берется с:</b> суммы перевода\n\n'
        f'выбери действие:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

# === обработчики callback-кнопок настроек ===
@dp.callback_query(lambda c: c.data == 'settings_change_nick')
async def settings_change_nick_callback(callback: types.CallbackQuery, state: FSMContext):
    """обработчик кнопки изменения ника"""
    user_id = callback.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    await callback.message.edit_text(
        "✏️ <b>изменение ника</b>\n\n"
        "💡 напиши новый ник (от 3 до 20 символов):",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='❌ отмена', callback_data='settings_cancel_nick')]
        ])
    )
    
    await state.set_state(SettingsState.waiting_for_new_nick)
    await callback.answer()

@dp.callback_query(lambda c: c.data == 'settings_cancel_nick')
async def settings_cancel_nick_callback(callback: types.CallbackQuery, state: FSMContext):
    """обработчик кнопки отмены изменения ника"""
    user_id = callback.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    # очищаем состояние FSM
    await state.clear()
    
    # удаляем сообщение с запросом ника
    await callback.message.delete()
    
    # показываем меню настроек
    await show_settings_menu(callback.message, user_id_str)
    await callback.answer()

@dp.callback_query(lambda c: c.data == 'settings_toggle_top')
async def settings_toggle_top_callback(callback: types.CallbackQuery):
    """обработчик кнопки переключения видимости в топе"""
    user_id = callback.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    user_data = users[user_id_str]
    current_hide = user_data.get('hide_from_top', False)
    
    # переключаем настройку
    user_data['hide_from_top'] = not current_hide
    save_users()
    
    new_status = 'скрыта' if not current_hide else 'видна'
    await callback.answer(f"🏆 ссылка в топе изменена: {new_status}", show_alert=True)
    
    # возвращаемся к настройкам
    await show_settings_menu(callback.message, user_id_str)

@dp.callback_query(lambda c: c.data == 'settings_toggle_confirmations')
async def settings_toggle_confirmations_callback(callback: types.CallbackQuery):
    """обработчик кнопки переключения подтверждений перевода"""
    user_id = callback.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    user_data = users[user_id_str]
    current_confirmations = user_data.get('transfer_confirmations', True)
    
    # переключаем настройку
    user_data['transfer_confirmations'] = not current_confirmations
    save_users()
    
    if not current_confirmations:
        # включаем подтверждения
        await callback.answer("✅ подтверждения перевода включены", show_alert=True)
    else:
        # выключаем подтверждения
        await callback.answer("⚠️ подтверждения перевода выключены! теперь переводы будут выполняться сразу без подтверждения", show_alert=True)
    
    # возвращаемся к настройкам
    await show_settings_menu(callback.message, user_id_str)

@dp.callback_query(lambda c: c.data == 'settings_back')
async def settings_back_callback(callback: types.CallbackQuery, state: FSMContext):
    """обработчик кнопки возврата из настроек"""
    user_id = callback.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    # очищаем состояние FSM (важно для исправления бага)
    await state.clear()
    
    # возвращаемся в главное меню
    await show_menu(callback.message, user_id)
    await callback.answer()

async def show_settings_menu(message: types.Message, user_id_str: str):
    """показывает меню настроек"""
    user_data = users[user_id_str]
    nick = user_data.get('nick', 'игрок')
    
    # проверяем текущие настройки
    hide_from_top = user_data.get('hide_from_top', False)
    transfer_confirmations = user_data.get('transfer_confirmations', True)
    
    settings_text = f"⚙️ <b>настройки</b>\n\n"
    settings_text += f"👤 <b>текущий ник:</b> {nick}\n"
    settings_text += f"🏆 <b>ссылка в топе:</b> {'скрыта' if hide_from_top else 'видна'}\n"
    settings_text += f"✅ <b>подтверждения перевода:</b> {'выключены' if not transfer_confirmations else 'включены'}\n\n"
    settings_text += "💡 выбери что хочешь изменить:\n\n"
    settings_text += "⚠️ <b>внимание:</b> при отключении подтверждений переводы будут выполняться сразу без дополнительной проверки"
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✏️ изменить ник', callback_data='settings_change_nick')],
        [InlineKeyboardButton(text='🏆 скрыть ссылку' if not hide_from_top else '🏆 показать ссылку', callback_data='settings_toggle_top')],
        [InlineKeyboardButton(text='✅ выключить подтверждения' if transfer_confirmations else '✅ включить подтверждения', callback_data='settings_toggle_confirmations')],
        [InlineKeyboardButton(text='⬅️ назад', callback_data='settings_back')]
    ])
    
    await message.edit_text(settings_text, parse_mode='HTML', reply_markup=markup)

async def main():
    # Удаляем webhook перед запуском polling
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook удален, запускаем polling...")
    except Exception as e:
        print(f"⚠️ Ошибка при удалении webhook: {e}")
    
    # Загружаем настройки налога
    load_tax_settings()
    
    # Загружаем промокоды
    load_promo_codes()
    
    # Запускаем пинг в фоне
    ping_task = asyncio.create_task(start_ping())
    
    # Запускаем планировщик налога в фоне
    tax_task = asyncio.create_task(start_wealth_tax_scheduler())
    
    # Запускаем планировщик резервного копирования в фоне
    backup_task = asyncio.create_task(start_backup_scheduler())
    
    # Запускаем бота
    await dp.start_polling(bot)

# Добавляем команду для перезагрузки БД
@dp.message(Command('reload_db'))
async def reload_database(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    users = load_users()
    
    await message.answer(f'база данных перезагружена! загружено {len(users)} пользователей')
@dp.message(Command('collect_tax'))
async def collect_tax_command(message: types.Message):
    """Команда для ручного сбора налога на богатство"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратор
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    await message.answer('💰 запускаю ручной сбор налога на богатство...')
    
    try:
        await collect_wealth_tax()
        await message.answer('✅ налог на богатство успешно собран!')
    except Exception as e:
        await message.answer(f'❌ ошибка при сборе налога: {e}')

@dp.message(Command('backup'))
async def create_backup_command(message: types.Message):
    """Команда для ручного создания резервной копии базы данных"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратор
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    await message.answer('💾 создаю резервную копию базы данных...')
    
    try:
        success = create_backup()
        if success:
            await message.answer('✅ резервная копия базы данных успешно создана!')
        else:
            await message.answer('❌ ошибка при создании резервной копии')
    except Exception as e:
        await message.answer(f'❌ ошибка при создании резервной копии: {e}')

@dp.message(Command('roulette_status'))
async def roulette_status_command(message: types.Message):
    """Команда для проверки статуса рулетки"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратор
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    # Показываем статус рулетки
    status_text = (
    
    f"🎰 <b>Статус рулетки</b>\n\n"
        f"🔒 <b>Исправления:</b>\n"
        f"• Анализ паттернов: ❌ (отключен)\n"
        f"• Полностью случайная система: ✅\n"
        f"• Система против богатых игроков: ✅\n\n"
        f"📊 <b>Базовые шансы проигрыша по балансу:</b>\n"
        f"• До 1кк: 50%\n"
        f"• До 10кк: 55%\n"
        f"• До 100кк: 60%\n"
        f"• До 1ккк: 65%\n"
        f"• До 10ккк: 70%\n"
        f"• До 100ккк: 75%\n"
        f"• До 1кккк: 80%\n"
        f"• Больше 1кккк: 85%\n\n"
        f"📈 <b>Бонус за большие ставки:</b>\n"
        f"• До 5% от баланса: +0%\n"
        f"• До 15% от баланса: +5%\n"
        f"• До 30% от баланса: +10%\n"
        f"• До 50% от баланса: +15%\n"
        f"• До 80% от баланса: +20%\n"
        f"• Больше 80% от баланса: +25%\n\n"
        f"✅ <b>Баг исправлен - богатые игроки проигрывают чаще!</b>"
    )
    
    await message.answer(status_text, parse_mode='HTML')

@dp.message(F.text.lower() == 'мой id')
async def my_id_command(message: types.Message):
    """показывает ID пользователя"""
    user_id = message.from_user.id
    
    username = message.from_user.username or 'без username'
    
    await message.answer(
        f'🆔 <b>твоя информация</b>\n\n'
        f'📱 <b>ID:</b> <code>{user_id}</code>\n'
        f'👤 <b>Username:</b> @{username}\n'
        f'👑 <b>Админ:</b> {"да" if user_id in ADMIN_IDS else "нет"}\n\n'
        f'💡 <b>ADMIN_IDS в коде:</b>\n<code>{ADMIN_IDS}</code>',
        parse_mode='HTML'
    
    )

@dp.message(F.text.lower() == 'menu')
async def on_menu_en_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    await show_menu(message, user_id)

@dp.message(F.text.lower() == 'top')
async def on_top_command(message: types.Message):
    """обработчик команды top"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await message.answer('сначала зарегистрируйся командой /start')
        return
    
    # показываем первую страницу топа
    top_text, markup = await show_top_page(message, 0)
    
    await message.answer(top_text, parse_mode='HTML', reply_markup=markup)

@dp.message(F.text == '🏆')
async def on_trophy_button(message: types.Message):
    """обработчик кнопки 🏆"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await message.answer('сначала зарегистрируйся командой /start')
        return
    
    # показываем первую страницу топа
    top_text, markup = await show_top_page(message, 0)
    
    await message.answer(top_text, parse_mode='HTML', reply_markup=markup)

@dp.message(F.text == '⚙️ настройки')
async def on_settings_button(message: types.Message):
    """обработчик кнопки настройки"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await message.answer('сначала зарегистрируйся командой /start')
        return
    
    user_data = users[user_id_str]
    nick = user_data.get('nick', 'игрок')
    
    # проверяем текущие настройки
    hide_from_top = user_data.get('hide_from_top', False)
    transfer_confirmations = user_data.get('transfer_confirmations', True)
    
    settings_text = f"⚙️ <b>настройки</b>\n\n"
    settings_text += f"👤 <b>текущий ник:</b> {nick}\n"
    settings_text += f"🏆 <b>ссылка в топе:</b> {'скрыта' if hide_from_top else 'видна'}\n"
    settings_text += f"✅ <b>подтверждения перевода:</b> {'выключены' if not transfer_confirmations else 'включены'}\n\n"
    settings_text += "💡 выбери что хочешь изменить:\n\n"
    settings_text += "⚠️ <b>внимание:</b> при отключении подтверждений переводы будут выполняться сразу без дополнительной проверки"
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✏️ изменить ник', callback_data='settings_change_nick')],
        [InlineKeyboardButton(text='🏆 скрыть ссылку' if not hide_from_top else '🏆 показать ссылку', callback_data='settings_toggle_top')],
        [InlineKeyboardButton(text='✅ выключить подтверждения' if transfer_confirmations else '✅ включить подтверждения', callback_data='settings_toggle_confirmations')],
        [InlineKeyboardButton(text='⬅️ назад', callback_data='settings_back')]
    ])
    
    await message.answer(settings_text, parse_mode='HTML', reply_markup=markup)

@dp.message(F.text.lower() == 'м')
async def on_m_letter(message: types.Message):
    """обработчик буквы м"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id_str not in users:
        await show_not_registered_message(message)
        return
    
    if 'nick' not in users[user_id_str]:
        await show_not_registered_message(message)
        return
    
    # проверяем, не забанен ли пользователь
    user_data = users[user_id_str]
    
    if user_data.get('banned', False):
        ban_reason = user_data.get('ban_reason', 'неизвестно')
        ban_duration = user_data.get('ban_duration', 'неизвестно')
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💬 обжаловать наказание', url='https://t.me/daisicxTp_bot')]
        ])
        
        await message.answer(
            f"🚫 <b>твой аккаунт заблокирован!</b>\n\n"
            f"❌ <b>причина:</b> {ban_reason}\n"
            f"⏰ <b>срок:</b> {ban_duration}\n\n"
            f"💬 обжаловать наказание можно по кнопке ниже\n"
            f"🔗 <b>поддержка:</b> @daisicxTp_bot",
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    
    await show_menu(message, user_id)

@dp.message(F.text == 'выбрать цель 🎯')
async def select_target_button(message: types.Message):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return

@dp.message(AdminState.waiting_for_warn_date)
async def warn_date_entered(message: types.Message, state: FSMContext):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    if user_id not in ADMIN_IDS:
        return
    
    date_text = message.text.strip()
    
    # Парсим дату
    try:
        # Пробуем разные форматы даты
        date_formats = ['%d.%m.%Y', '%d.%m.%y', '%d/%m/%Y', '%d/%m/%y']
        parsed_date = None
        
        for fmt in date_formats:
            try:
                parsed_date = datetime.datetime.strptime(date_text, fmt)
                break
            except ValueError:
                continue
        
        if not parsed_date:
            await message.answer('неправильный формат даты. используй формат дд.мм.гггг')
            return
        
        # Сохраняем дату в состоянии
        await state.update_data(warn_date=date_text)
        
        # Запрашиваем причину варна
        await message.answer('напиши причину варна')
        await state.set_state(AdminState.waiting_for_warn_reason)
        
    except Exception as e:
        await message.answer(f'ошибка при парсинге даты: {e}')
        await state.clear()
        await admin_panel(message)

@dp.message(Command('user_info'))
async def show_user_info(message: types.Message):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    # Парсим аргументы команды
    args = message.text.split()
    
    if len(args) < 2:
        await message.answer('использование: /user_info <username или nick>')
        return
    
    target_text = args[1].strip()
    
    username = extract_username(target_text)
    
    # Ищем пользователя
    target_user_id = None
    target_user_data = None
    
    for uid, user_data in users.items():
        if (user_data.get('tg_username', '').lower() == username.lower() or 
            user_data.get('nick', '').lower() == target_text.lower()):
            target_user_id = uid
            target_user_data = user_data
            break
    
    if not target_user_data:
        await message.answer('пользователь не найден')
        return
    
    # Формируем детальную информацию
    info_text = f"🔍 <b>детальная информация о пользователе</b>\n\n"
    
    info_text += f"🆔 <b>ID:</b> {target_user_id}\n"
    info_text += f"👤 <b>ник:</b> {target_user_data.get('nick', 'неизвестно')}\n"
    info_text += f"📱 <b>username:</b> @{target_user_data.get('tg_username', 'без_юз')}\n"
    info_text += f"💰 <b>баланс:</b> ${format_money(target_user_data.get('balance', 0))}\n"
    info_text += f"⚠️ <b>варны:</b> {target_user_data.get('warns', 0)}\n"
    info_text += f"🚫 <b>забанен:</b> {'да' if target_user_data.get('banned', False) else 'нет'}\n"
    info_text += f"📅 <b>дата регистрации:</b> {target_user_data.get('registration_date', 'неизвестно')}\n"
    info_text += f"🕐 <b>последняя активность:</b> {target_user_data.get('last_activity', 'неизвестно')}\n"
    info_text += f"💬 <b>всего сообщений:</b> {target_user_data.get('total_messages', 0)}\n"
    info_text += f"🌍 <b>язык:</b> {target_user_data.get('language', 'неизвестно')}\n"
    info_text += f"🔗 <b>источник:</b> {target_user_data.get('referral_source', 'неизвестно')}\n"
    info_text += f"📊 <b>тип аккаунта:</b> {target_user_data.get('account_type', 'неизвестно')}\n"
    info_text += f"✅ <b>статус верификации:</b> {target_user_data.get('verification_status', 'неизвестно')}\n"
    info_text += f"🔒 <b>уровень безопасности:</b> {target_user_data.get('security_level', 'неизвестно')}\n"
    info_text += f"💎 <b>премиум функции:</b> {'да' if target_user_data.get('premium_features', False) else 'нет'}\n"
    info_text += f"🔢 <b>количество входов:</b> {target_user_data.get('login_count', 0)}\n"
    info_text += f"📱 <b>последний вход:</b> {target_user_data.get('last_login', 'неизвестно')}\n"
    info_text += f"👥 <b>рефералы:</b> {target_user_data.get('referrals', 0)}\n"
    info_text += f"💸 <b>заработок с рефералов:</b> ${format_money(target_user_data.get('referral_earnings', 0))}\n"
    
    # Дополнительная информация
    if target_user_data.get('phone_number'):
        info_text += f"📞 <b>телефон:</b> {target_user_data.get('phone_number')}\n"
    if target_user_data.get('email'):
        info_text += f"📧 <b>email:</b> {target_user_data.get('email')}\n"
    if target_user_data.get('age'):
        info_text += f"🎂 <b>возраст:</b> {target_user_data.get('age')}\n"
    if target_user_data.get('city'):
        info_text += f"🏙️ <b>город:</b> {target_user_data.get('city')}\n"
    if target_user_data.get('country'):
        info_text += f"🌍 <b>страна:</b> {target_user_data.get('country')}\n"
    
    # Настройки
    preferences = target_user_data.get('preferences', {})
    
    info_text += f"\n⚙️ <b>настройки:</b>\n"
    info_text += f"• уведомления: {'вкл' if preferences.get('notifications', True) else 'выкл'}\n"
    info_text += f"• приватный режим: {'вкл' if preferences.get('privacy_mode', False) else 'выкл'}\n"
    info_text += f"• автосохранение: {'вкл' if preferences.get('auto_save', True) else 'выкл'}\n"
    
    await message.answer(info_text, parse_mode='HTML')

@dp.message(Command('export_db'))
async def export_database(message: types.Message):
    
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    # создаём экспорт
    export_text = f"📊 <b>экспорт базы данных</b>\n"
    
    export_text += f"📅 <b>дата экспорта:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
    export_text += f"👥 <b>всего пользователей:</b> {len(users)}\n\n"
    
    for user_id, user_data in users.items():
        export_text += f"🆔 <b>ID:</b> {user_id}\n"
        export_text += f"👤 <b>ник:</b> {user_data.get('nick', 'неизвестно')}\n"
        export_text += f"📱 <b>username:</b> @{user_data.get('tg_username', 'без_юз')}\n"
        export_text += f"💰 <b>баланс:</b> ${format_money(user_data.get('balance', 0))}\n"
        export_text += f"⚠️ <b>варны:</b> {user_data.get('warns', 0)}\n"
        export_text += f"🚫 <b>забанен:</b> {'да' if user_data.get('banned', False) else 'нет'}\n"
        export_text += f"📅 <b>регистрация:</b> {user_data.get('registration_date', 'неизвестно')}\n"
        export_text += f"🕐 <b>активность:</b> {user_data.get('last_activity', 'неизвестно')}\n"
        export_text += f"💬 <b>сообщения:</b> {user_data.get('total_messages', 0)}\n"
        export_text += f"🌍 <b>язык:</b> {user_data.get('language', 'неизвестно')}\n"
        export_text += f"🔗 <b>источник:</b> {user_data.get('referral_source', 'неизвестно')}\n"
        export_text += f"🔢 <b>входы:</b> {user_data.get('login_count', 0)}\n"
        export_text += f"👥 <b>рефералы:</b> {user_data.get('referrals', 0)}\n"
        export_text += f"💸 <b>заработок:</b> ${format_money(user_data.get('referral_earnings', 0))}\n"
        
        # Дополнительная информация
        if user_data.get('phone_number'):
            export_text += f"📞 <b>телефон:</b> {user_data.get('phone_number')}\n"
        if user_data.get('email'):
            export_text += f"📧 <b>email:</b> {user_data.get('email')}\n"
        if user_data.get('age'):
            export_text += f"🎂 <b>возраст:</b> {user_data.get('age')}\n"
        if user_data.get('city'):
            export_text += f"🏙️ <b>город:</b> {user_data.get('city')}\n"
        if user_data.get('country'):
            export_text += f"🌍 <b>страна:</b> {user_data.get('country')}\n"
        
        export_text += "─" * 30 + "\n\n"
    
    # Разбиваем на части если слишком длинное
    if len(export_text) > 4000:
        parts = [export_text[i:i+4000] for i in range(0, len(export_text), 4000)]
    
    for i, part in enumerate(parts):
            await message.answer(f"{part}\n\n<i>часть {i+1} из {len(parts)}</i>", parse_mode='HTML')
    
    else:
        await message.answer(export_text, parse_mode='HTML')
    
    # Возвращаемся в админ-панель
    await admin_panel(message)

@dp.message(Command('extend_limit'))
async def extend_k_limit_command(message: types.Message):
    """команда для ручного расширения лимита сокращений"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    # проверяем текущий лимит
    current_max = get_max_k_count()
    
    max_balance = max((user.get('balance', 0) for user in users.values()), default=0)
    
    info_text = f"🔢 <b>информация о лимите сокращений:</b>\n\n"
    
    info_text += f"📊 текущий лимит: {current_max} букв \"к\"\n"
    info_text += f"💎 максимальный баланс: ${format_money(max_balance)}\n"
    info_text += f"⚡ автоматическое расширение: {'включено' if auto_extend_k_limit() else 'выключено'}\n\n"
    
    if auto_extend_k_limit():
        info_text += "✅ лимит автоматически расширен на основе максимального баланса игроков"
    else:
        info_text += "ℹ️ лимит будет автоматически расширен, когда максимальный баланс превысит 1кккк"
    
    await message.answer(info_text, parse_mode='HTML')

@dp.message(F.text.lower() == 'мой id')
async def my_id_command(message: types.Message):
    """показывает ID пользователя"""
    user_id = message.from_user.id
    
    username = message.from_user.username or 'без username'
    
    await message.answer(
        f'🆔 <b>твоя информация</b>\n\n'
        f'📱 <b>ID:</b> <code>{user_id}</code>\n'
        f'👤 <b>Username:</b> @{username}\n'
        f'👑 <b>Админ:</b> {"да" if user_id in ADMIN_IDS else "нет"}\n\n'
        f'💡 <b>ADMIN_IDS в коде:</b>\n<code>{ADMIN_IDS}</code>',
        parse_mode='HTML'
    
    )

@dp.message(F.text.lower().contains('очистить') & F.text.lower().contains('бд'))
async def clear_db_button(message: types.Message):
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    # создаем клавиатуру для подтверждения
    markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='✅ да, очистить', callback_data='confirm_clear_db')],
        [InlineKeyboardButton(text='❌ отмена', callback_data='cancel_clear_db')]
    
    ])
    
    await message.answer(
        f'🗑️ <b>очистка базы данных</b>\n\n'
        f'⚠️ <b>внимание!</b> это действие необратимо!\n\n'
        f'📊 <b>текущая статистика:</b>\n'
        f'• пользователей: <b>{len(users)}</b>\n'
        f'• общий баланс: <b>${format_money(sum(user.get("balance", 0) for user in users.values()))}</b>\n\n'
        f'🔴 <b>после очистки:</b>\n'
        f'• все пользователи будут удалены\n'
        f'• все данные будут потеряны\n'
        f'• база данных станет пустой\n\n'
        f'ты уверен, что хочешь очистить базу данных?',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.message(F.text.lower().contains('экспорт') & F.text.lower().contains('бд'))
async def export_db_button(message: types.Message):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    # показываем меню выбора экспорта
    markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='📱 посмотреть в Telegram', callback_data='export_view_telegram')],
        [InlineKeyboardButton(text='📁 скачать файл', callback_data='export_download_file')],
    
    [InlineKeyboardButton(text='❌ отмена', callback_data='export_cancel')]
    ])
    
    await message.answer(
        f'📊 <b>экспорт базы данных</b>\n\n'
        f'👥 <b>всего пользователей:</b> {len(users)}\n'
        f'📅 <b>дата:</b> {datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")}\n\n'
        f'выбери способ экспорта:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

# === обработчики экспорта БД ===
@dp.callback_query(lambda c: c.data == 'export_view_telegram')
async def export_view_telegram_callback(callback: types.CallbackQuery):
    """просмотр экспорта в Telegram с пагинацией"""
    user_id = callback.from_user.id
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
    
    return
    await callback.answer('создаю экспорт для просмотра...', show_alert=False)
    
    # показываем первую страницу
    await show_users_page(callback.message, 0, user_id)
async def show_users_page(message: types.Message, page: int, user_id: int = None):
    
    """показывает страницу пользователей с пагинацией"""
    if user_id is None:
        user_id = message.from_user.id
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        return
    
    # настройки пагинации
    users_per_page = 5  # количество пользователей на странице
    
    total_users = len(users)
    total_pages = (total_users + users_per_page - 1) // users_per_page
    
    if page >= total_pages:
        page = total_pages - 1
    
    if page < 0:
        page = 0
    
    # создаем заголовок
    header = f"📊 <b>экспорт базы данных</b>\n"
    
    header += f"📅 <b>дата:</b> {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
    header += f"👥 <b>всего пользователей:</b> {total_users}\n"
    header += f"📄 <b>страница:</b> {page + 1} из {total_pages}\n\n"
    
    # получаем пользователей для текущей страницы
    user_items = list(users.items())
    
    start_idx = page * users_per_page
    end_idx = min(start_idx + users_per_page, total_users)
    
    page_content = header
    
    for i in range(start_idx, end_idx):
        user_id, user_data = user_items[i]
        
        page_content += f"🆔 <b>ID:</b> {user_id}\n"
        page_content += f"👤 <b>ник:</b> {user_data.get('nick', 'неизвестно')}\n"
        page_content += f"📱 <b>username:</b> @{user_data.get('tg_username', 'без_юз')}\n"
        page_content += f"💰 <b>баланс:</b> ${format_money(user_data.get('balance', 0))}\n"
        page_content += f"⚠️ <b>варны:</b> {user_data.get('warns', 0)}\n"
        page_content += f"🚫 <b>забанен:</b> {'да' if user_data.get('banned', False) else 'нет'}\n"
        page_content += f"📅 <b>регистрация:</b> {user_data.get('registration_date', 'неизвестно')}\n"
        page_content += f"🕐 <b>активность:</b> {user_data.get('last_activity', 'неизвестно')}\n"
        page_content += f"💬 <b>сообщения:</b> {user_data.get('total_messages', 0)}\n"
        page_content += f"🌍 <b>язык:</b> {user_data.get('language', 'неизвестно')}\n"
        page_content += f"🔗 <b>источник:</b> {user_data.get('referral_source', 'неизвестно')}\n"
        page_content += f"🔢 <b>входы:</b> {user_data.get('login_count', 0)}\n"
        page_content += f"👥 <b>рефералы:</b> {user_data.get('referrals', 0)}\n"
        page_content += f"💸 <b>заработок:</b> ${format_money(user_data.get('referral_earnings', 0))}\n"
        
        # дополнительная информация
        if user_data.get('phone_number'):
            page_content += f"📞 <b>телефон:</b> {user_data.get('phone_number')}\n"
        if user_data.get('email'):
            page_content += f"📧 <b>email:</b> {user_data.get('email')}\n"
        if user_data.get('age'):
            page_content += f"🎂 <b>возраст:</b> {user_data.get('age')}\n"
        if user_data.get('city'):
            page_content += f"🏙️ <b>город:</b> {user_data.get('city')}\n"
        if user_data.get('country'):
            page_content += f"🌍 <b>страна:</b> {user_data.get('country')}\n"
        
        page_content += "─" * 30 + "\n\n"
    
    # создаем кнопки навигации
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    
    # кнопки навигации
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text='⬅️', callback_data=f'users_page_{page-1}'))
    
    nav_buttons.append(InlineKeyboardButton(text=f'{page+1}/{total_pages}', callback_data='no_action'))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text='➡️', callback_data=f'users_page_{page+1}'))
    
    if nav_buttons:
        markup.inline_keyboard.append(nav_buttons)
    
    # кнопка возврата
    markup.inline_keyboard.append([InlineKeyboardButton(text='🔙 назад в админ-панель', callback_data='back_to_admin')])
    
    # отправляем или редактируем сообщение
    try:
        await message.edit_text(page_content, parse_mode='HTML', reply_markup=markup)
    
    except:
        await message.answer(page_content, parse_mode='HTML', reply_markup=markup)

@dp.callback_query(lambda c: c.data == 'export_download_file')
async def export_download_file_callback(callback: types.CallbackQuery):
    """скачивание экспорта в виде файла"""
    user_id = callback.from_user.id
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
    
    return
    
    await callback.answer('создаю файл для скачивания...', show_alert=False)
    
    # создаем содержимое файла
    file_content = f"ЭКСПОРТ БАЗЫ ДАННЫХ\n"
    
    file_content += f"Дата экспорта: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
    file_content += f"Всего пользователей: {len(users)}\n\n"
    
    for user_id, user_data in users.items():
        file_content += f"ID: {user_id}\n"
        file_content += f"Ник: {user_data.get('nick', 'неизвестно')}\n"
        file_content += f"Username: @{user_data.get('tg_username', 'без_юз')}\n"
        file_content += f"Баланс: ${format_money(user_data.get('balance', 0))}\n"
        file_content += f"Варны: {user_data.get('warns', 0)}\n"
        file_content += f"Забанен: {'да' if user_data.get('banned', False) else 'нет'}\n"
        file_content += f"Регистрация: {user_data.get('registration_date', 'неизвестно')}\n"
        file_content += f"Активность: {user_data.get('last_activity', 'неизвестно')}\n"
        file_content += f"Сообщения: {user_data.get('total_messages', 0)}\n"
        file_content += f"Язык: {user_data.get('language', 'неизвестно')}\n"
        file_content += f"Источник: {user_data.get('referral_source', 'неизвестно')}\n"
        file_content += f"Входы: {user_data.get('login_count', 0)}\n"
        file_content += f"Рефералы: {user_data.get('referrals', 0)}\n"
        file_content += f"Заработок: ${format_money(user_data.get('referral_earnings', 0))}\n"
        
        # дополнительная информация
        if user_data.get('phone_number'):
            file_content += f"Телефон: {user_data.get('phone_number')}\n"
        if user_data.get('email'):
            file_content += f"Email: {user_data.get('email')}\n"
        if user_data.get('age'):
            file_content += f"Возраст: {user_data.get('age')}\n"
        if user_data.get('city'):
            file_content += f"Город: {user_data.get('city')}\n"
        if user_data.get('country'):
            file_content += f"Страна: {user_data.get('country')}\n"
        
        file_content += "─" * 30 + "\n\n"
    
    # создаем временный файл
    filename = f"db_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    file_path = f"temp/{filename}"
    
    # создаем папку temp если её нет
    os.makedirs("temp", exist_ok=True)
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(file_content)
        
        # отправляем файл
        with open(file_path, 'rb') as f:
            await callback.message.answer_document(
                document=types.BufferedInputFile(f.read(), filename=filename),
                caption=f'📁 <b>экспорт базы данных</b>\n\n📅 <b>дата:</b> {datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")}\n👥 <b>пользователей:</b> {len(users)}',
                parse_mode='HTML'
            )
        
        # удаляем временный файл
        os.remove(file_path)
        
    except Exception as e:
        await callback.message.answer(f'❌ ошибка при создании файла: {e}')
    
    # возвращаемся в админ-панель
    await admin_panel(callback.message)

@dp.callback_query(lambda c: c.data == 'export_cancel')
async def export_cancel_callback(callback: types.CallbackQuery):
    """отмена экспорта"""
    user_id = callback.from_user.id
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
    
    return
    
    await callback.answer('экспорт отменен', show_alert=False)
    
    # возвращаемся в админ-панель
    await admin_panel(callback.message)

# === обработчики пагинации пользователей ===
@dp.callback_query(lambda c: c.data.startswith('users_page_'))
async def users_page_callback(callback: types.CallbackQuery):
    """обработчик кнопок пагинации пользователей"""
    user_id = callback.from_user.id
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
    
    return
    
    # извлекаем номер страницы
    page = int(callback.data.split('_')[2])
    
    await callback.answer(f'страница {page + 1}', show_alert=False)
    
    # показываем страницу
    await show_users_page(callback.message, page, user_id)

@dp.callback_query(lambda c: c.data == 'back_to_admin')
async def back_to_admin_callback(callback: types.CallbackQuery):
    """возврат в админ-панель"""
    user_id = callback.from_user.id
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
    
    return
    
    await callback.answer('возвращаемся в админ-панель...', show_alert=False)
    
    # возвращаемся в админ-панель
    await admin_panel(callback.message)

@dp.callback_query(lambda c: c.data == 'no_action')
async def no_action_callback(callback: types.CallbackQuery):
    """пустой обработчик для кнопок без действия"""
    try:
        await callback.answer()
    except:
        pass

# === конец обработчиков пагинации ===

# === конец обработчиков экспорта БД ===

@dp.message(F.text.lower().contains('пробить') | F.text.lower().contains('пробив'))
async def probe_user_button(message: types.Message, state: FSMContext):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    await message.answer('🔍 напиши юз кого хочешь пробить))', reply_markup=ReplyKeyboardRemove())
    
    await state.set_state(AdminState.waiting_for_probe_target)

@dp.message(AdminState.waiting_for_probe_target)
async def probe_target_selected(message: types.Message, state: FSMContext):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        return
    
    target_text = message.text.strip()
    
    username = extract_username(target_text)
    
    # Ищем пользователя
    target_user_id = None
    
    target_user_data = None
    
    for uid, user_data in users.items():
        if (user_data.get('tg_username', '').lower() == username.lower() or 
            user_data.get('nick', '').lower() == target_text.lower()):
            target_user_id = uid
            target_user_data = user_data
            break
    
    if not target_user_data:
        await message.answer('пользователь не найден')
        await state.clear()
        await admin_panel(message)
        return
    
    # Формируем детальную информацию в том же стиле
    info_text = f"🔍 <b>пробив пользователя</b>\n\n"
    
    info_text += f"🆔 <b>ID:</b> {target_user_id}\n"
    info_text += f"👤 <b>ник:</b> {target_user_data.get('nick', 'неизвестно')}\n"
    info_text += f"📱 <b>username:</b> @{target_user_data.get('tg_username', 'без_юз')}\n"
    info_text += f"💰 <b>баланс:</b> ${format_money(target_user_data.get('balance', 0))}\n"
    info_text += f"⚠️ <b>варны:</b> {target_user_data.get('warns', 0)}\n"
    info_text += f"🚫 <b>забанен:</b> {'да' if target_user_data.get('banned', False) else 'нет'}\n"
    info_text += f"📅 <b>дата регистрации:</b> {target_user_data.get('registration_date', 'неизвестно')}\n"
    info_text += f"🕐 <b>последняя активность:</b> {target_user_data.get('last_activity', 'неизвестно')}\n"
    info_text += f"💬 <b>всего сообщений:</b> {target_user_data.get('total_messages', 0)}\n"
    info_text += f"🌍 <b>язык:</b> {target_user_data.get('language', 'неизвестно')}\n"
    info_text += f"🔗 <b>источник:</b> {target_user_data.get('referral_source', 'неизвестно')}\n"
    info_text += f"📊 <b>тип аккаунта:</b> {target_user_data.get('account_type', 'неизвестно')}\n"
    info_text += f"✅ <b>статус верификации:</b> {target_user_data.get('verification_status', 'неизвестно')}\n"
    info_text += f"🔒 <b>уровень безопасности:</b> {target_user_data.get('security_level', 'неизвестно')}\n"
    info_text += f"💎 <b>премиум функции:</b> {'да' if target_user_data.get('premium_features', False) else 'нет'}\n"
    info_text += f"🔢 <b>количество входов:</b> {target_user_data.get('login_count', 0)}\n"
    info_text += f"📱 <b>последний вход:</b> {target_user_data.get('last_login', 'неизвестно')}\n"
    info_text += f"👥 <b>рефералы:</b> {target_user_data.get('referrals', 0)}\n"
    info_text += f"💸 <b>заработок с рефералов:</b> ${format_money(target_user_data.get('referral_earnings', 0))}\n"
    
    # Дополнительная информация
    if target_user_data.get('phone_number'):
        info_text += f"📞 <b>телефон:</b> {target_user_data.get('phone_number')}\n"
    if target_user_data.get('email'):
        info_text += f"📧 <b>email:</b> {target_user_data.get('email')}\n"
    if target_user_data.get('age'):
        info_text += f"🎂 <b>возраст:</b> {target_user_data.get('age')}\n"
    if target_user_data.get('city'):
        info_text += f"🏙️ <b>город:</b> {target_user_data.get('city')}\n"
    if target_user_data.get('country'):
        info_text += f"🌍 <b>страна:</b> {target_user_data.get('country')}\n"
    
    # Настройки
    preferences = target_user_data.get('preferences', {})
    
    info_text += f"\n⚙️ <b>настройки:</b>\n"
    info_text += f"• уведомления: {'вкл' if preferences.get('notifications', True) else 'выкл'}\n"
    info_text += f"• приватный режим: {'вкл' if preferences.get('privacy_mode', False) else 'выкл'}\n"
    info_text += f"• автосохранение: {'вкл' if preferences.get('auto_save', True) else 'выкл'}\n"
    
    await message.answer(info_text, parse_mode='HTML')
    
    # Очищаем состояние и возвращаемся в админ-панель
    await state.clear()
    await admin_panel(message)

 

@dp.message(F.text.lower().contains('выдать') & (F.text.lower().contains('деньги') | F.text.lower().contains('баланс')))
async def give_money_button(message: types.Message, state: FSMContext):
    # Проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    await message.answer('🧾 напиши юз кому выдать деньги', reply_markup=ReplyKeyboardRemove())
    
    await state.update_data(current_action='give_money')
    await state.set_state(AdminState.waiting_for_target)

@dp.message(AdminState.waiting_for_give_amount)
async def give_amount_entered(message: types.Message, state: FSMContext):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    amount_text = message.text.strip()
    
    try:
        amount = parse_amount(amount_text)
    
    except:
        await message.answer('неверный формат суммы')
        await state.clear()
        return
    
    # проверяем, что сумма больше 0
    if amount <= 0:
        await message.answer('сумма должна быть больше 0')
        await state.clear()
        return
    
    await state.update_data(give_amount=amount)
    
    await message.answer('🧾 напиши причину пополнения')
    await state.set_state(AdminState.waiting_for_give_reason)

@dp.message(AdminState.waiting_for_give_reason)
async def give_reason_entered(message: types.Message, state: FSMContext):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    reason = message.text.strip()
    
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    
    amount = data.get('give_amount')
    if not target_user_id or amount is None:
        await message.answer('ошибка состояния, начни заново')
        await state.clear()
        return
    # выполняем зачисление
    if target_user_id in users:
        users[target_user_id]['balance'] = users[target_user_id].get('balance', 0) + int(amount)
        save_users()
        try:
            await bot.send_message(
                int(target_user_id),
                f"💵 <b>твой баланс был пополнен администратором</b>\n\n"
                f"➕ <b>сумма:</b> ${format_money(amount)}\n"
                f"💳 <b>новый баланс:</b> ${format_money(users[target_user_id]['balance'])}\n"
                f"🧾 <b>причина:</b> {reason}",
                parse_mode='HTML'
    
    )
        except Exception as e:
            print(f'не удалось отправить уведомление о пополнении: {e}')
        await message.answer(f"пополнен баланс пользователя {users[target_user_id].get('nick','?')} на ${format_money(amount)}")
    else:
        await message.answer('пользователь не найден')
    await state.clear()
    await admin_panel(message)

@dp.message(AdminState.waiting_for_tax_percent)
async def tax_percent_entered(message: types.Message, state: FSMContext):
    """Обрабатывает ввод нового процента налога"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    try:
        new_percent = int(message.text.strip())
        
        if new_percent < 1 or new_percent > 50:
            await message.answer('❌ процент должен быть от 1 до 50. попробуй еще раз:')
            return
        
        # Обновляем глобальную переменную
        global WEALTH_TAX_PERCENT
        WEALTH_TAX_PERCENT = new_percent
        
        # Сохраняем настройки
        save_tax_settings()
        
        await message.answer(
            f'✅ <b>процент налога изменен!</b>\n\n'
            f'💰 <b>новый процент:</b> {WEALTH_TAX_PERCENT}%\n'
            f'⏰ <b>изменения вступят в силу:</b> при следующем сборе налога',
            parse_mode='HTML'
        )
        
        print(f"✅ Админ {user_id} изменил процент налога на {WEALTH_TAX_PERCENT}%")
        
    except ValueError:
        await message.answer('❌ введи число от 1 до 50:')
        return
    
    await state.clear()
    await admin_panel(message)

@dp.message(AdminState.waiting_for_commission_percent)
async def commission_percent_entered(message: types.Message, state: FSMContext):
    """Обрабатывает ввод нового процента комиссии"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    try:
        new_percent = int(message.text.strip())
        
        if new_percent < 1 or new_percent > 50:
            await message.answer('❌ процент должен быть от 1 до 50. попробуй еще раз:')
            return
        
        # Обновляем глобальную переменную
        global TRANSFER_COMMISSION_TOP20
        TRANSFER_COMMISSION_TOP20 = new_percent
        
        # Сохраняем настройки
        save_tax_settings()
        
        await message.answer(
            f'✅ <b>процент комиссии изменен!</b>\n\n'
            f'💰 <b>новый процент:</b> {TRANSFER_COMMISSION_TOP20}%\n'
            f'⏰ <b>изменения вступят в силу:</b> при следующем переводе',
            parse_mode='HTML'
        )
        
        print(f"✅ Админ {user_id} изменил процент комиссии на {TRANSFER_COMMISSION_TOP20}%")
        
    except ValueError:
        await message.answer('❌ введи число от 1 до 50:')
        return
    
    await state.clear()
    await admin_panel(message)

@dp.message(AdminState.waiting_for_unban_reason)
async def unban_reason_entered(message: types.Message, state: FSMContext):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    reason = message.text.strip()
    
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    
    success, message_text = await remove_ban(target_user_id)
    await message.answer(message_text + f"\n🧾 причина: {reason}")
    await state.clear()
    await admin_panel(message)

@dp.message(AdminState.waiting_for_annul_reason)
async def annul_reason_entered(message: types.Message, state: FSMContext):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    reason = message.text.strip()
    
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    
    await message.answer('напиши сумму для аннулирования (число или "все")')
    await state.update_data(annul_reason=reason)
    
    await state.set_state(AdminState.waiting_for_balance_amount)

@dp.message(F.text.lower().contains('обнулить') & F.text.lower().contains('баланс') & F.text.lower().contains('всем'))
async def reset_all_balance_button(message: types.Message, state: FSMContext):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    collect_user_info(message, user_id_str)
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    await message.answer(
        '⚠️ <b>внимание!</b>\n\n'
        'ты собираешься обнулить баланс <b>ВСЕМ</b> игрокам!\n\n'
        'это действие нельзя отменить!\n\n'
        'напиши "да" для подтверждения или "нет" для отмены:',
        parse_mode='HTML',
    
    reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AdminState.waiting_for_reset_all_balance_confirm)

@dp.message(AdminState.waiting_for_reset_all_balance_confirm)
async def reset_all_balance_confirm(message: types.Message, state: FSMContext):
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    confirm_text = message.text.strip().lower()
    
    if confirm_text == 'да':
        # обнуляем баланс всем игрокам
        reset_count = 0
        
        for user_id_str, user_data in users.items():
            if 'balance' in user_data:
                user_data['balance'] = 0
                reset_count += 1
        
        # сохраняем изменения в базу данных
        save_users()
        
        await message.answer(
            f'✅ <b>баланс обнулен всем игрокам!</b>\n\n'
            f'📊 <b>обнулено игроков:</b> {reset_count}\n'
            f'💰 <b>все балансы установлены в:</b> $0',
            parse_mode='HTML'
        )
        
        safe_print(f"админ {user_id} обнулил баланс всем игрокам ({reset_count} игроков)")
        
    elif confirm_text == 'нет':
        await message.answer('❌ операция отменена')
    else:
        await message.answer('напиши "да" для подтверждения или "нет" для отмены')
        return
    
    await state.clear()
    await admin_panel(message)
@dp.message(AdminState.waiting_for_add_admin_username)
async def add_admin_username_handler(message: types.Message, state: FSMContext):
    """Обработчик username для добавления админа"""
    # проверяем, что это личное сообщение
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    username = message.text.strip().lower()
    
    # Убираем @ если пользователь его написал
    if username.startswith('@'):
        username = username[1:]
    
    # Ищем пользователя в базе данных
    target_user_id = None
    
    target_nick = None
    
    for uid, user_data in users.items():
        if user_data.get('tg_username', '').lower() == username:
            target_user_id = uid
            target_nick = user_data.get('nick', 'неизвестно')
            break
    
    if not target_user_id:
        await message.answer(f'❌ Пользователь @{username} не найден в базе данных')
        await state.clear()
        await admin_panel(message)
        return
    
    # Проверяем, не является ли пользователь уже админом
    if int(target_user_id) in ADMIN_IDS:
        await message.answer(f'❌ Пользователь @{username} уже является администратором')
        await state.clear()
        await admin_panel(message)
        return
    
    # Добавляем пользователя в админы
    ADMIN_IDS.add(int(target_user_id))
    
    # Сохраняем изменения в файл (если нужно)
    # Можно создать функцию для сохранения ADMIN_IDS в файл
    
    await message.answer(
        f'✅ <b>Пользователь @{username} ({target_nick}) успешно добавлен в администраторы!</b>\n\n'
        f'👑 <b>ID:</b> {target_user_id}\n'
        f'📝 <b>Nick:</b> {target_nick}\n'
        f'🔐 <b>Username:</b> @{username}',
        parse_mode='HTML'
    
    )
    
    safe_print(f"админ {user_id} добавил пользователя {target_user_id} (@{username}) в администраторы")
    
    await state.clear()
    await admin_panel(message)

# === ОБРАБОТЧИКИ СОСТОЯНИЙ ДЛЯ ПРОМОКОДОВ ===

@dp.message(AdminState.waiting_for_promo_code)
async def promo_code_handler(message: types.Message, state: FSMContext):
    """Обработчик ввода промокода"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    promo_code = message.text.strip().upper()
    
    # Проверяем, что промокод состоит только из букв и цифр
    if not promo_code.isalnum():
        await message.answer('❌ промокод должен состоять только из букв и цифр')
        return
    
    # Проверяем, что промокод не слишком короткий
    if len(promo_code) < 3:
        await message.answer('❌ промокод должен содержать минимум 3 символа')
        return
    
    # Проверяем, что промокод не слишком длинный
    if len(promo_code) > 20:
        await message.answer('❌ промокод не должен превышать 20 символов')
        return
    
    # Проверяем, что промокод не существует
    if promo_code in promo_codes:
        await message.answer('❌ такой промокод уже существует')
        return
    
    # Сохраняем промокод в состоянии
    await state.update_data(promo_code=promo_code)
    
    # Устанавливаем состояние ожидания награды
    await state.set_state(AdminState.waiting_for_promo_reward)
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='⬅️ отмена')]
    ])
    
    await message.answer(
        f'✅ <b>промокод принят!</b>\n\n'
        f'🎫 <b>промокод:</b> {promo_code}\n\n'
        f'💰 <b>теперь укажи награду:</b>\n'
        f'📝 напиши сумму валюты (например: 1000000000)',
        parse_mode='HTML',
        reply_markup=markup
    )

@dp.message(AdminState.waiting_for_promo_reward)
async def promo_reward_handler(message: types.Message, state: FSMContext):
    """Обработчик ввода награды промокода"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    reward_text = message.text.strip()
    
    # Парсим сумму
    try:
        reward = parse_amount(reward_text)
        if reward <= 0:
            await message.answer('❌ награда должна быть больше 0')
            return
    except:
        await message.answer('❌ неверный формат суммы. напиши число (например: 1000000000)')
        return
    
    # Получаем данные из состояния
    data = await state.get_data()
    promo_code = data.get('promo_code')
    
    if not promo_code:
        await message.answer('❌ ошибка: промокод не найден в состоянии')
        await state.clear()
        await promo_codes_section(message)
        return
    
    # Сохраняем награду в состоянии
    await state.update_data(reward=reward)
    
    # Устанавливаем состояние ожидания количества активаций
    await state.set_state(AdminState.waiting_for_promo_activations)
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='⬅️ отмена')]
    ])
    
    await message.answer(
        f'💰 <b>награда принята!</b>\n\n'
        f'🎫 <b>промокод:</b> {promo_code}\n'
        f'💰 <b>награда:</b> ${format_money(reward)}\n\n'
        f'📊 <b>теперь укажи лимит активаций:</b>\n'
        f'📝 напиши число (например: 10) или "бесконечно"',
        parse_mode='HTML',
        reply_markup=markup
    )

@dp.message(AdminState.waiting_for_promo_activations)
async def promo_activations_handler(message: types.Message, state: FSMContext):
    """Обработчик ввода лимита активаций промокода"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    activations_text = message.text.strip().lower()
    
    # Парсим количество активаций
    if activations_text == 'бесконечно':
        activations = -1  # -1 означает бесконечно
    else:
        try:
            activations = int(activations_text)
            if activations <= 0:
                await message.answer('❌ количество активаций должно быть больше 0')
                return
        except:
            await message.answer('❌ неверный формат. напиши число или "бесконечно"')
            return
    
    # Получаем данные из состояния
    data = await state.get_data()
    promo_code = data.get('promo_code')
    reward = data.get('reward')
    
    if not promo_code or not reward:
        await message.answer('❌ ошибка: данные промокода не найдены в состоянии')
        await state.clear()
        await promo_codes_section(message)
        return
    
    # Сохраняем количество активаций в состоянии
    await state.update_data(activations=activations)
    
    # Устанавливаем состояние ожидания даты истечения
    await state.set_state(AdminState.waiting_for_promo_expiry_date)
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='⏰ указать срок действия'), KeyboardButton(text='♾️ бессрочно')],
        [KeyboardButton(text='⬅️ отмена')]
    ])
    
    expiry_text = "бесконечно" if activations == -1 else f"{activations} раз"
    
    await message.answer(
        f'📊 <b>лимит активаций принят!</b>\n\n'
        f'🎫 <b>промокод:</b> {promo_code}\n'
        f'💰 <b>награда:</b> ${format_money(reward)}\n'
        f'📊 <b>активации:</b> {expiry_text}\n\n'
        f'⏰ <b>теперь укажи срок действия:</b>\n'
        f'📅 выбери опцию ниже',
        parse_mode='HTML',
        reply_markup=markup
    )

@dp.message(AdminState.waiting_for_promo_expiry_date)
async def promo_expiry_date_handler(message: types.Message, state: FSMContext):
    """Обработчик выбора срока действия промокода"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    choice = message.text.strip()
    
    if choice == '♾️ бессрочно':
        # Создаем промокод без срока действия
        await create_promo_final(message, state, expiry=None)
        return
    elif choice == '⏰ указать срок действия':
        # Устанавливаем состояние ожидания даты
        await state.set_state(AdminState.waiting_for_promo_expiry_time)
        
        markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
            [KeyboardButton(text='⬅️ отмена')]
        ])
        
        await message.answer(
            '📅 <b>указание срока действия</b>\n\n'
            '📝 напиши дату в формате ДД.ММ.ГГГГ ЧЧ:ММ\n'
            '💡 например: 01.09.2025 15:00\n'
            '❌ для отмены нажми "отмена"',
            parse_mode='HTML',
            reply_markup=markup
        )
        return
    else:
        await message.answer('❌ выбери одну из опций')
        return

@dp.message(AdminState.waiting_for_promo_expiry_time)
async def promo_expiry_time_handler(message: types.Message, state: FSMContext):
    """Обработчик ввода времени истечения промокода"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    expiry_text = message.text.strip()
    
    # Парсим дату и время
    try:
        expiry_date = datetime.datetime.strptime(expiry_text, '%d.%m.%Y %H:%M')
        expiry_timestamp = expiry_date.timestamp()
        
        # Проверяем, что дата в будущем
        if expiry_timestamp <= datetime.datetime.now().timestamp():
            await message.answer('❌ дата должна быть в будущем')
            return
    except:
        await message.answer('❌ неверный формат даты. используй формат ДД.ММ.ГГГГ ЧЧ:ММ')
        return
    
    # Создаем промокод с указанным сроком действия
    await create_promo_final(message, state, expiry=expiry_timestamp)

async def create_promo_final(message: types.Message, state: FSMContext, expiry=None):
    """Финальное создание промокода"""
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    # Получаем данные из состояния
    data = await state.get_data()
    promo_code = data.get('promo_code')
    reward = data.get('reward')
    activations = data.get('activations')
    
    if not all([promo_code, reward, activations is not None]):
        await message.answer('❌ ошибка: не все данные промокода найдены')
        await state.clear()
        await promo_codes_section(message)
        return
    
    # Создаем промокод
    promo_codes[promo_code] = {
        'reward': reward,
        'activations': activations,
        'current_activations': 0,
        'expiry': expiry,
        'created_by': user_id_str,
        'created_at': datetime.datetime.now().timestamp(),
        'used_by': []
    }
    
    # Сохраняем промокоды
    save_promo_codes()
    
    # Формируем сообщение об успехе
    expiry_text = "бессрочно" if expiry is None else datetime.datetime.fromtimestamp(expiry).strftime('%d.%m.%Y %H:%M')
    activations_text = "бесконечно" if activations == -1 else f"{activations} раз"
    
    # Создаем ссылку на промокод
    bot_username = (await bot.me()).username
    promo_link = f"https://t.me/{bot_username}?start=promo_{promo_code}"
    
    success_text = f"✅ <b>промокод успешно создан!</b>\n\n"
    success_text += f"🎫 <b>промокод:</b> {promo_code}\n"
    success_text += f"💰 <b>награда:</b> ${format_money(reward)}\n"
    success_text += f"📊 <b>активации:</b> {activations_text}\n"
    success_text += f"⏰ <b>срок действия:</b> {expiry_text}\n"
    success_text += f"👑 <b>создал:</b> {user_id_str}\n\n"
    success_text += "🔗 <b>ссылка для активации:</b>\n"
    success_text += f"<code>{promo_link}</code>\n\n"
    success_text += "💡 <b>игроки могут перейти по ссылке и автоматически активировать промокод!</b>\n\n"
    success_text += "🎉 <b>промокод готов к использованию!</b>"
    
    # Очищаем состояние
    await state.clear()
    
    # Возвращаемся в раздел промокодов
    await promo_codes_section(message)

# === ОБРАБОТЧИКИ КНОПОК ОТМЕНЫ И КОЛБЭКОВ ===

@dp.message(F.text == '⬅️ отмена')
async def cancel_promo_creation(message: types.Message, state: FSMContext):
    """Обработчик кнопки отмены создания промокода"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    # Очищаем состояние
    await state.clear()
    
    # Возвращаемся в раздел промокодов
    await promo_codes_section(message)

@dp.callback_query(lambda c: c.data.startswith('delete_promo_'))
async def delete_promo_callback(callback: types.CallbackQuery):
    """Обработчик колбэка удаления промокода"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
        return
    
    # Извлекаем код промокода из callback_data
    promo_code = callback.data.replace('delete_promo_', '')
    
    if promo_code not in promo_codes:
        await callback.answer('промокод не найден', show_alert=True)
        return
    
    # Удаляем промокод
    del promo_codes[promo_code]
    
    # Сохраняем промокоды
    save_promo_codes()
    
    await callback.answer(f'✅ промокод {promo_code} удален!', show_alert=True)
    
    # Обновляем сообщение
    await callback.message.edit_text(
        f'🗑️ <b>промокод удален!</b>\n\n'
        f'🎫 <b>промокод:</b> {promo_code}\n'
        f'✅ <b>статус:</b> успешно удален\n\n'
        f'🔄 <b>обновляю список промокодов...</b>',
        parse_mode='HTML'
    )
    
    # Возвращаемся в раздел промокодов
    await callback.message.answer('🔄 список промокодов обновлен')
    await promo_codes_section(callback.message)

@dp.callback_query(lambda c: c.data == 'cancel_delete_promo')
async def cancel_delete_promo_callback(callback: types.CallbackQuery):
    """Обработчик колбэка отмены удаления промокода"""
    user_id = callback.from_user.id
    
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
        return
    
    await callback.answer('❌ удаление отменено', show_alert=True)
    
    # Возвращаемся в раздел промокодов
    await promo_codes_section(callback.message)

@dp.message(SettingsState.waiting_for_new_nick)
async def new_nick_handler(message: types.Message, state: FSMContext):
    """обработчик ввода нового ника"""
    user_id = message.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await message.answer('сначала зарегистрируйся командой /start')
        await state.clear()
        return
    
    user_data = users[user_id_str]
    new_nick = message.text.strip()
    
    # проверяем длину ника
    if len(new_nick) < 3:
        await message.answer('❌ ник должен содержать минимум 3 символа')
        return
    
    if len(new_nick) > 20:
        await message.answer('❌ ник не должен превышать 20 символов')
        return
    
    # сохраняем старый ник для истории
    old_nick = user_data.get('nick', 'неизвестно')
    
    # обновляем ник
    user_data['nick'] = new_nick
    save_users()
    
    await message.answer(
        f'✅ <b>ник успешно изменен!</b>\n\n'
        f'👤 <b>старый ник:</b> {old_nick}\n'
        f'👤 <b>новый ник:</b> {new_nick}',
        parse_mode='HTML'
    )
    
    await state.clear()
    
    # возвращаемся к настройкам
    await show_settings_menu(message, user_id_str)

@dp.message(F.text == '⚠️ наказания')
async def punishments_section(message: types.Message):
    """Обработчик раздела наказаний"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='выдать варн ⚠️'), KeyboardButton(text='выдать бан 🚫')],
        [KeyboardButton(text='снять варн ✅'), KeyboardButton(text='снять бан ✅')],
    
    [KeyboardButton(text='⬅️ назад в админ панель')]
    ])
    
    await message.answer(
        '⚠️ <b>раздел наказаний</b>\n\nвыбери действие:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.message(F.text == '💸 валюта')
async def currency_section(message: types.Message):
    """Обработчик раздела валюты"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='аннулировать баланс 💰'), KeyboardButton(text='выдать деньги 💵')],
        [KeyboardButton(text='обнулить баланс всем 💸')],
    
    [KeyboardButton(text='⬅️ назад в админ панель')]
    ])
    
    await message.answer(
        '💸 <b>раздел валюты</b>\n\nвыбери действие:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.message(F.text == '📋 база данных')
async def database_section(message: types.Message):
    """Обработчик раздела базы данных"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='пробить юз 🔍'), KeyboardButton(text='просмотр БД 📊')],
        [KeyboardButton(text='экспорт БД 📋')],
    
    [KeyboardButton(text='⬅️ назад в админ панель')]
    ])
    
    await message.answer(
        '📋 <b>раздел базы данных</b>\n\nвыбери действие:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.message(F.text == '💰 налоги')
async def taxes_section(message: types.Message):
    """Обработчик раздела налогов"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='собрать налог 💰'), KeyboardButton(text='налог на богатство ⚙️')],
        [KeyboardButton(text='комиссия переводов ⚙️')],
    
    [KeyboardButton(text='⬅️ назад в админ панель')]
    ])
    
    await message.answer(
        '💰 <b>раздел налогов</b>\n\nвыбери действие:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

async def promo_codes_section(message: types.Message):
    """Обработчик раздела промокодов"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='➕ создать промокод'), KeyboardButton(text='📋 список промокодов')],
        [KeyboardButton(text='🗑️ удалить промокод'), KeyboardButton(text='📊 статистика промокодов')],
        [KeyboardButton(text='⬅️ назад в админ панель')]
    ])
    
    await message.answer(
        '🎫 <b>раздел промокодов</b>\n\nвыбери действие:',
        parse_mode='HTML',
        reply_markup=markup
    )

@dp.message(F.text == '➕ создать промокод')
async def create_promo_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки создания промокода"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    # Показываем меню создания промокода
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='✏️ написать самому'), KeyboardButton(text='🎲 сгенерировать случайный')],
        [KeyboardButton(text='⬅️ назад в промокоды')]
    ])
    
    await message.answer(
        '➕ <b>создание промокода</b>\n\n'
        'выбери способ создания промокода:',
        parse_mode='HTML',
        reply_markup=markup
    )
@dp.message(F.text == '✏️ написать самому')
async def write_promo_manually(message: types.Message, state: FSMContext):
    """Обработчик кнопки написания промокода вручную"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    # Устанавливаем состояние ожидания промокода
    await state.set_state(AdminState.waiting_for_promo_code)
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='⬅️ отмена')]
    ])
    
    await message.answer(
        '✏️ <b>написание промокода</b>\n\n'
        '📝 напиши промокод в чат\n'
        '💡 промокод должен состоять из букв и цифр\n'
        '❌ для отмены нажми "отмена"',
        parse_mode='HTML',
        reply_markup=markup
    )

@dp.message(F.text == '🎲 сгенерировать случайный')
async def generate_promo_random(message: types.Message, state: FSMContext):
    """Обработчик кнопки генерации случайного промокода"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    # Генерируем случайный промокод
    promo_code = generate_random_promo()
    
    # Сохраняем промокод в состоянии
    await state.update_data(promo_code=promo_code)
    
    # Устанавливаем состояние ожидания награды
    await state.set_state(AdminState.waiting_for_promo_reward)
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='⬅️ отмена')]
    ])
    
    await message.answer(
        f'🎲 <b>промокод сгенерирован!</b>\n\n'
        f'🎫 <b>промокод:</b> {promo_code}\n\n'
        f'💰 <b>теперь укажи награду:</b>\n'
        f'📝 напиши сумму валюты (например: 1000000000)',
        parse_mode='HTML',
        reply_markup=markup
    )

@dp.message(F.text == '📋 список промокодов')
async def list_promo_codes(message: types.Message):
    """Обработчик кнопки списка промокодов"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    if not promo_codes:
        await message.answer('📋 <b>список промокодов</b>\n\n❌ промокоды не найдены', parse_mode='HTML')
        return
    
    # Формируем список промокодов
    promo_list = "📋 <b>список промокодов:</b>\n\n"
    
    for code, data in promo_codes.items():
        expiry_date = "бессрочно"
        if data.get('expiry'):
            expiry_date = datetime.datetime.fromtimestamp(data['expiry']).strftime('%d.%m.%Y %H:%M')
        
        # Создаем ссылку на промокод
        bot_username = (await bot.me()).username
        promo_link = f"https://t.me/{bot_username}?start=promo_{code}"
        
        promo_list += f"🎫 <b>{code}</b>\n"
        promo_list += f"💰 награда: ${format_money(data['reward'])}\n"
        promo_list += f"📊 активации: {data['current_activations']}/{data['activations']}\n"
        promo_list += f"⏰ срок действия: {expiry_date}\n"
        promo_list += f"👑 создал: {data['created_by']}\n"
        promo_list += f"🔗 <code>{promo_link}</code>\n\n"
    
    # Добавляем кнопку возврата
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='⬅️ назад в промокоды')]
    ])
    
    await message.answer(promo_list, parse_mode='HTML', reply_markup=markup)

@dp.message(F.text == '🗑️ удалить промокод')
async def delete_promo_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки удаления промокода"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    if not promo_codes:
        await message.answer('🗑️ <b>удаление промокода</b>\n\n❌ промокоды не найдены', parse_mode='HTML')
        return
    
    # Формируем список промокодов для удаления
    promo_list = "🗑️ <b>выбери промокод для удаления:</b>\n\n"
    
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    
    for code in promo_codes.keys():
        markup.inline_keyboard.append([InlineKeyboardButton(text=code, callback_data=f'delete_promo_{code}')])
    
    markup.inline_keyboard.append([InlineKeyboardButton(text='⬅️ отмена', callback_data='cancel_delete_promo')])
    
    await message.answer(promo_list, parse_mode='HTML', reply_markup=markup)

@dp.message(F.text == '📊 статистика промокодов')
async def promo_statistics(message: types.Message):
    """Обработчик кнопки статистики промокодов"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    if not promo_codes:
        await message.answer('📊 <b>статистика промокодов</b>\n\n❌ промокоды не найдены', parse_mode='HTML')
        return
    
    # Подсчитываем статистику
    total_promos = len(promo_codes)
    total_activations = sum(data['current_activations'] for data in promo_codes.values())
    total_rewards = sum(data['reward'] * data['current_activations'] for data in promo_codes.values())
    
    active_promos = sum(1 for code in promo_codes.keys() if is_promo_valid(code))
    expired_promos = total_promos - active_promos
    
    stats_text = f"📊 <b>статистика промокодов</b>\n\n"
    stats_text += f"🎫 <b>всего промокодов:</b> {total_promos}\n"
    stats_text += f"✅ <b>активных:</b> {active_promos}\n"
    stats_text += f"❌ <b>истекших:</b> {expired_promos}\n"
    stats_text += f"🔢 <b>всего активаций:</b> {total_activations}\n"
    stats_text += f"💰 <b>выдано наград:</b> ${format_money(total_rewards)}\n\n"
    
    # Добавляем список активных промокодов с ссылками
    if active_promos > 0:
        stats_text += "🔗 <b>активные промокоды:</b>\n\n"
        
        for code, data in promo_codes.items():
            if is_promo_valid(code):
                # Создаем ссылку на промокод
                bot_username = (await bot.me()).username
                promo_link = f"https://t.me/{bot_username}?start=promo_{code}"
                
                stats_text += f"🎫 <b>{code}</b>\n"
                stats_text += f"💰 ${format_money(data['reward'])}\n"
                stats_text += f"🔗 <code>{promo_link}</code>\n\n"
    
    # Добавляем кнопку возврата
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton(text='⬅️ назад в промокоды')]
    ])
    
    await message.answer(stats_text, parse_mode='HTML', reply_markup=markup)

@dp.message(F.text == '⬅️ назад в промокоды')
async def back_to_promo_section(message: types.Message):
    """Возврат в раздел промокодов"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    await promo_codes_section(message)

@dp.message(F.text == '🏦 вклады')
async def deposits_section(message: types.Message):
    """Обработчик раздела вкладов"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='📈 статистика вкладов'), KeyboardButton(text='🏆 топ вкладов')],
        [KeyboardButton(text='🧹 аннулировать вклад игроку')],
    [KeyboardButton(text='🗑️ аннулировать вклады всем')],
        [KeyboardButton(text='⬅️ назад в админ панель')]
    
    ])
    
    await message.answer(
        '🏦 <b>раздел вкладов</b>\n\nвыбери действие:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.message(F.text == '🧹 аннулировать вклад игроку')
async def annul_deposit_user_prompt(message: types.Message, state: FSMContext):
    """Запрашивает у админа @username или ID игрока для аннулирования вклада"""
    if message.chat.type != 'private':
        return
    if message.from_user.id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    await state.set_state(AdminState.waiting_for_annul_deposit_target)
    await message.answer('пришли @username или ID игрока для аннулирования вклада')

@dp.message(AdminState.waiting_for_annul_deposit_target)
async def annul_deposit_user_execute(message: types.Message, state: FSMContext):
    if message.chat.type != 'private':
        return
    if message.from_user.id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    raw = (message.text or '').strip()
    target_id = None
    # поддержка ID
    if raw.isdigit():
        target_id = raw
    else:
        # поддержка @username
        uname = raw.lstrip('@').lower()
        for uid, data in users.items():
            if str(data.get('tg_username', '')).lower() == uname:
                target_id = uid
                break
    if not target_id or target_id not in users:
        await message.answer('пользователь не найден')
        await state.clear()
        return
    if users[target_id].get('bank_deposit', 0) <= 0:
        await message.answer('у пользователя нет активного вклада')
        await state.clear()
        return
    amount = users[target_id].get('bank_deposit', 0)
    users[target_id]['bank_deposit'] = 0
    users[target_id]['bank_deposit_time'] = 0
    save_users()
    await state.clear()
    await message.answer(f'✅ вклад игрока аннулирован на сумму ${format_money(amount)}')
    # Возврат в раздел вкладов
    await deposits_section(message)

@dp.message(F.text == '🗑️ аннулировать вклады всем')
async def annul_all_deposits(message: types.Message):
    """аннулирует вклады всех игроков"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    # подсчитываем статистику
    total_deposits = 0
    affected_users = 0
    
    for user_data in users.values():
        if user_data.get('bank_deposit', 0) > 0:
            total_deposits += user_data['bank_deposit']
            affected_users += 1
    
    if affected_users == 0:
        await message.answer('📊 у игроков нет активных вкладов для аннулирования')
        return
    
    # создаем клавиатуру подтверждения
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='✅ подтвердить', callback_data='confirm_annul_deposits')],
        [InlineKeyboardButton(text='❌ отмена', callback_data='cancel_annul_deposits')]
    ])
    
    await message.answer(
        f'🗑️ <b>аннулирование вкладов</b>\n\n'
        f'📊 <b>статистика:</b>\n'
        f'• затронуто игроков: <b>{affected_users}</b>\n'
        f'• общая сумма вкладов: <b>${format_money(total_deposits)}</b>\n\n'
        f'⚠️ <b>внимание:</b> это действие нельзя отменить!\n'
        f'все активные вклады будут обнулены.',
        parse_mode='HTML',
        reply_markup=markup
    )

@dp.callback_query(lambda c: c.data == 'confirm_annul_deposits')
async def confirm_annul_deposits_callback(callback: types.CallbackQuery):
    """подтверждение аннулирования вкладов"""
    user_id = callback.from_user.id
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
        return
    
    # аннулируем вклады
    total_deposits = 0
    affected_users = 0
    
    for user_data in users.values():
        if user_data.get('bank_deposit', 0) > 0:
            total_deposits += user_data['bank_deposit']
            user_data['bank_deposit'] = 0
            user_data['bank_deposit_time'] = 0
            affected_users += 1
    
    # сохраняем изменения
    save_users()
    
    await callback.answer('✅ вклады аннулированы!', show_alert=True)
    await callback.message.edit_text(
        f'✅ <b>вклады аннулированы!</b>\n\n'
        f'📊 <b>результат:</b>\n'
        f'• затронуто игроков: <b>{affected_users}</b>\n'
        f'• обнулено вкладов: <b>${format_money(total_deposits)}</b>\n\n'
        f'📅 <b>дата:</b> {datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")}',
        parse_mode='HTML'
    )

@dp.callback_query(lambda c: c.data == 'cancel_annul_deposits')
async def cancel_annul_deposits_callback(callback: types.CallbackQuery):
    """отмена аннулирования вкладов"""
    user_id = callback.from_user.id
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой функции', show_alert=True)
        return
    
    await callback.answer('❌ аннулирование отменено', show_alert=True)
    await callback.message.edit_text(
        '❌ <b>аннулирование отменено</b>\n\n'
        'вклады остались без изменений',
        parse_mode='HTML'
    )

@dp.message(F.text == '📣 рассылка')
async def broadcast_section(message: types.Message):
    """Обработчик раздела рассылки"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    
    [KeyboardButton(text='рассылка 📣')],
        [KeyboardButton(text='⬅️ назад в админ панель')]
    
    ])
    
    await message.answer(
        '📣 <b>раздел рассылки</b>\n\nвыбери действие:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.message(F.text == '⬅️ назад в админ панель')
async def back_to_admin_panel(message: types.Message):
    """Возврат в главную админ панель"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой функции')
        return
    
    await admin_panel(message)

@dp.message(F.text.lower() == 'собрать налог 💰')
async def collect_tax_button(message: types.Message):
    """Обработчик кнопки сбора налога в админ-панели"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    await message.answer('💰 запускаю сбор налога на богатство...')
    
    try:
        await collect_wealth_tax()
        await message.answer('✅ налог на богатство успешно собран!')
    except Exception as e:
        await message.answer(f'❌ ошибка при сборе налога: {e}')

@dp.message(F.text == 'налог на богатство ⚙️')
async def wealth_tax_settings_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки настройки налога на богатство"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    # Показываем текущие настройки и кнопки для изменения
    markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text=f'📊 текущий процент: {WEALTH_TAX_PERCENT}%', callback_data='wealth_tax_info')],
        [InlineKeyboardButton(text='📝 написать процент', callback_data='wealth_tax_write')],
    
    [InlineKeyboardButton(text='❌ отмена', callback_data='wealth_tax_cancel')]
    ])
    
    await message.answer(
        f'⚙️ <b>настройки налога на богатство</b>\n\n'
        f'💰 <b>текущий процент:</b> {WEALTH_TAX_PERCENT}%\n'
        f'⏰ <b>периодичность:</b> каждый час\n'
        f'👥 <b>применяется к:</b> топ-15 игрокам\n\n'
        f'выбери действие:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.message(F.text == 'комиссия переводов ⚙️')
async def transfer_commission_settings_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки настройки комиссии переводов"""
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    # Собираем информацию о пользователе
    collect_user_info(message, user_id_str)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer('у тебя нет доступа к этой команде')
        return
    
    # Показываем текущие настройки и кнопки для изменения
    markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text=f'📊 текущий процент: {TRANSFER_COMMISSION_TOP20}%', callback_data='transfer_commission_info')],
        [InlineKeyboardButton(text='📝 написать процент', callback_data='transfer_commission_write')],
    
    [InlineKeyboardButton(text='❌ отмена', callback_data='transfer_commission_cancel')]
    ])
    
    await message.answer(
        f'⚙️ <b>настройки комиссии переводов</b>\n\n'
        f'💰 <b>текущий процент:</b> {TRANSFER_COMMISSION_TOP20}%\n'
        f'👥 <b>применяется к:</b> топ-20 игрокам\n'
        f'💸 <b>комиссия берется с:</b> суммы перевода\n\n'
        f'выбери действие:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

# === мини-игра баскетбол ===
# активные игры по чатам
basket_games = {}

BASKET_IMAGE_PATH = 'img/basket.jpg'

@dp.message(F.text.lower().contains('баскет') | F.text.lower().contains('бск'))
async def basket_create(message: types.Message):
    
    # Проверяем, что это не личное сообщение
    if message.chat.type == 'private':
        markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='➕ добавить бота в чат', url='https://t.me/Dodeperplaybot?startgroup')]
        ])
        await message.answer(
            '🏀 игра в баскетбол доступна только в чатах с другими игроками\n\n'
            'добавь бота в чат, чтобы играть!',
            reply_markup=markup
    
    )
        return
    
    user_id = message.from_user.id
    
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    user_id_str = str(user_id)
    
    if user_id_str not in users or 'nick' not in users[user_id_str]:
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="создать человечка", callback_data="create_human")
        await message.answer("ты не зарегистрирован в боте", reply_markup=keyboard.as_markup())
        return
    # если уже есть игра, удаляем старую и уведомляем только в этом случае
    had_old = chat_id in basket_games
    if had_old:
        old_game = basket_games.get(chat_id) or {}
        try:
            old_msg_id = old_game.get('message_id')
            if old_msg_id:
                await bot.delete_message(chat_id, old_msg_id)
        except:
            pass
        basket_games.pop(chat_id, None)
        try:
            await message.answer('🔄 старая игра в баскетбол отменена, создается новая')
        except Exception:
            pass
    
    text_lower = (message.text or '').lower()
    
    amount_match = re.search(r'(?:баскет|бск)\s+(.+)$', text_lower)
    if not amount_match:
        await message.answer('укажи сумму после слова баскет или бск. пример: баскет 1кк или бск 1кк или баскет все')
        return
    amount_text = amount_match.group(1).strip()
    
    try:
        if amount_text in ['все', 'всё', 'алл']:
            amount = users[user_id_str].get('balance', 0)
        else:
            amount = parse_amount(amount_text)
    except Exception:
        await message.answer('не понял сумму. пример: баскет 1к, баскет 1кк, баскет все')
        return
    if amount <= 0:
        await message.answer('ставка должна быть положительной')
        return
    if users[user_id_str].get('balance', 0) < amount:
        await message.answer(f"у тебя недостаточно денег. на счету: <b>${format_money(users[user_id_str].get('balance',0))}</b>", parse_mode='HTML')
        return
    
    basket_games[chat_id] = {
        'initiator_id': user_id_str,
        'amount': amount,
        'status': 'pending',
        'message_id': None
    }
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='✅ играть', callback_data='basket_accept')],
        [InlineKeyboardButton(text='❌ отмена', callback_data='basket_cancel')]
    
    ])
    nick = users[user_id_str].get('nick','игрок')
    
    link = f"<a href=\"tg://user?id={user_id}\"><b>{nick}</b></a>"
    caption = (
    
    f"🏀 {link} хочет сыграть в баскетбол\n\n"
        f"ставка — <b>${format_money(amount)}</b>\n\n"
        f"жми играть, если готов"
    )
    # превью-картинка как часть карточки (одно сообщение)
    import os
    try:
        # пытаемся отправить фото, если файл существует
        if os.path.exists(BASKET_IMAGE_PATH):
            try:
                msg = await bot.send_photo(chat_id, types.FSInputFile(BASKET_IMAGE_PATH), caption=caption, parse_mode='HTML', reply_markup=kb)
            except Exception as e:
                # обработка flood control с единичным ретраем
                try:
                    from aiogram.exceptions import TelegramRetryAfter
                except Exception:
                    TelegramRetryAfter = None
                if TelegramRetryAfter and isinstance(e, TelegramRetryAfter):
                    try:
                        await asyncio.sleep(getattr(e, 'retry_after', 3) + 1)
                        msg = await bot.send_photo(chat_id, types.FSInputFile(BASKET_IMAGE_PATH), caption=caption, parse_mode='HTML', reply_markup=kb)
                    except Exception as e2:
                        print(f'не удалось отправить картинку баскета после ретрая: {e2}')
                        msg = await message.answer(caption, parse_mode='HTML', reply_markup=kb)
                else:
                    print(f'не удалось отправить картинку баскета: {e}')
                    msg = await message.answer(caption, parse_mode='HTML', reply_markup=kb)
        else:
            msg = await message.answer(caption, parse_mode='HTML', reply_markup=kb)
    except Exception as e:
        # обработка flood control для текстового сообщения
        print(f'fallback на текст и он тоже упал: {e}')
        try:
            from aiogram.exceptions import TelegramRetryAfter
        except Exception:
            TelegramRetryAfter = None
        if TelegramRetryAfter and isinstance(e, TelegramRetryAfter):
            try:
                await asyncio.sleep(getattr(e, 'retry_after', 3) + 1)
                msg = await message.answer(caption, parse_mode='HTML', reply_markup=kb)
            except Exception as e2:
                print(f'не удалось отправить карточку баскета после ретрая: {e2}')
                # на крайний случай — немой провал без спама
                msg = None
        else:
            # иные ошибки — не спамим повторно
            msg = None
    
    if msg is not None:
        basket_games[chat_id]['message_id'] = msg.message_id
@dp.callback_query(lambda c: c.data == 'basket_cancel')
async def basket_cancel(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    
    game = basket_games.get(chat_id)
    if not game:
        await callback.answer('игра не найдена', show_alert=False)
        return
    if str(callback.from_user.id) != game['initiator_id']:
        await callback.answer('отменить может только создатель', show_alert=True)
        return
    # удаляем сообщение с карточкой
    try:
        await bot.delete_message(chat_id, game.get('message_id'))
    except:
        pass
    basket_games.pop(chat_id, None)
    await callback.answer('отменено')

@dp.callback_query(lambda c: c.data == 'basket_accept')
async def basket_accept(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    
    accepter_id = str(callback.from_user.id)
    game = basket_games.get(chat_id)
    
    if not game or game.get('status') != 'pending':
        await callback.answer('игра не найдена', show_alert=False)
        return
    if accepter_id == game['initiator_id']:
        await callback.answer('нужен второй игрок', show_alert=True)
        return
    amount = game['amount']
    
    if users.get(game['initiator_id'], {}).get('balance', 0) < amount:
        try:
            await bot.delete_message(chat_id, game.get('message_id'))
        except:
            pass
        basket_games.pop(chat_id, None)
        await callback.message.answer('игра отменена — у создателя недостаточно денег')
        try:
            await callback.answer()
        except:
            pass
        return
    if users.get(accepter_id, {}).get('balance', 0) < amount:
        await callback.answer('у тебя недостаточно денег для ставки', show_alert=True)
        return
    
    # списываем
    users[game['initiator_id']]['balance'] -= amount
    users[accepter_id]['balance'] -= amount
    save_users()
    game['status'] = 'started'
    game['opponent_id'] = accepter_id
    try:
        await bot.delete_message(chat_id, game.get('message_id'))
    except:
        pass
    await callback.message.answer('начинаем игру')
    try:
        await callback.answer()
    except:
        pass
    
    # броски: сначала текст «кто кидает», потом кидаем
    initiator_nick = users[game['initiator_id']].get('nick','игрок')
    
    opponent_nick = users[accepter_id].get('nick','игрок')
    initiator_link = f"<a href=\"tg://user?id={int(game['initiator_id'])}\"><b>{initiator_nick}</b></a>"
    
    opponent_link = f"<a href=\"tg://user?id={int(accepter_id)}\"><b>{opponent_nick}</b></a>"

    await callback.message.answer(f"кидает {initiator_link}", parse_mode='HTML')
    
    await asyncio.sleep(0.4)
    throw1 = await bot.send_dice(chat_id, emoji='🏀')
    
    await asyncio.sleep(3)
    
    await callback.message.answer(f"кидает {opponent_link}", parse_mode='HTML')
    
    await asyncio.sleep(0.4)
    throw2 = await bot.send_dice(chat_id, emoji='🏀')
    
    await asyncio.sleep(3)
    
    val1 = throw1.dice.value
    
    val2 = throw2.dice.value
    
    if val1 == val2:
        users[game['initiator_id']]['balance'] += amount
        users[accepter_id]['balance'] += amount
        save_users()
        await callback.message.answer(
            'ничья\n\n'
            f"баланс {initiator_link} — <b>${format_money(users[game['initiator_id']]['balance'])}</b>\n"
            f"баланс {opponent_link} — <b>${format_money(users[accepter_id]['balance'])}</b>",
            parse_mode='HTML'
    
    )
        basket_games.pop(chat_id, None)
        return
    
    # проверяем идеальные броски и забивание
    initiator_perfect = val1 == 5
    opponent_perfect = val2 == 5
    # забитым считаем только 4-5; 1-3 — промахи/застревание/«почти»
    initiator_scored = val1 >= 4
    opponent_scored = val2 >= 4
    
    # если оба забили идеально - ничья
    if initiator_perfect and opponent_perfect:
        users[game['initiator_id']]['balance'] += amount
        users[accepter_id]['balance'] += amount
        save_users()
        await callback.message.answer(
            'ничья - оба забили идеально!\n\n'
            f"баланс {initiator_link} — <b>${format_money(users[game['initiator_id']]['balance'])}</b>\n"
            f"баланс {opponent_link} — <b>${format_money(users[accepter_id]['balance'])}</b>",
            parse_mode='HTML'
    
    )
        basket_games.pop(chat_id, None)
        return
    
    # если оба не забили - ничья
    if not initiator_scored and not opponent_scored:
        users[game['initiator_id']]['balance'] += amount
        users[accepter_id]['balance'] += amount
        save_users()
        await callback.message.answer(
            'ничья - оба не забили\n\n'
            f"баланс {initiator_link} — <b>${format_money(users[game['initiator_id']]['balance'])}</b>\n"
            f"баланс {opponent_link} — <b>${format_money(users[accepter_id]['balance'])}</b>",
            parse_mode='HTML'
    
    )
        basket_games.pop(chat_id, None)
        return
    
    # если один забил идеально, другой обычный - приз x2 тому, кто идеально
    if initiator_perfect and opponent_scored and not opponent_perfect:
        users[game['initiator_id']]['balance'] += amount * 2
        save_users()
        winner_link = f"<a href=\"tg://user?id={int(game['initiator_id'])}\"><b>{initiator_nick}</b></a>"
        loser_link = f"<a href=\"tg://user?id={int(accepter_id)}\"><b>{opponent_nick}</b></a>"
        await callback.message.answer(
            f"🏆 победил {winner_link} (2x - идеальный бросок!)\n"
            f"💀 {loser_link} проиграл (x0)\n\n"
            f"баланс {winner_link} — <b>${format_money(users[game['initiator_id']]['balance'])}</b>\n"
            f"баланс {loser_link} — <b>${format_money(users[accepter_id]['balance'])}</b>",
            parse_mode='HTML'
    
    )
        basket_games.pop(chat_id, None)
        return
    
    if opponent_perfect and initiator_scored and not initiator_perfect:
        users[accepter_id]['balance'] += amount * 2
        # первый игрок проигрывает (x0)
        save_users()
        winner_link = f"<a href=\"tg://user?id={int(accepter_id)}\"><b>{opponent_nick}</b></a>"
        loser_link = f"<a href=\"tg://user?id={int(game['initiator_id'])}\"><b>{initiator_nick}</b></a>"
        await callback.message.answer(
            f"🏆 победил {winner_link} (2x - идеальный бросок!)\n"
            f"💀 {loser_link} проиграл (x0)\n\n"
            f"баланс {winner_link} — <b>${format_money(users[accepter_id]['balance'])}</b>\n"
            f"баланс {loser_link} — <b>${format_money(users[game['initiator_id']]['balance'])}</b>",
            parse_mode='HTML'
    
    )
        basket_games.pop(chat_id, None)
        return
    
    # если один забил, другой нет - приз x2 тому, кто забил
    print(f"DEBUG: initiator_scored={initiator_scored}, opponent_scored={opponent_scored}")
    print(f"DEBUG: val1={val1}, val2={val2}")
    if initiator_scored and not opponent_scored:
        users[game['initiator_id']]['balance'] += amount * 2
        save_users()
        winner_link = f"<a href=\"tg://user?id={int(game['initiator_id'])}\"><b>{initiator_nick}</b></a>"
        loser_link = f"<a href=\"tg://user?id={int(accepter_id)}\"><b>{opponent_nick}</b></a>"
        await callback.message.answer(
            f"🏆 победил {winner_link} (2x - забил!)\n"
            f"💀 {loser_link} проиграл (x0)\n\n"
            f"баланс {winner_link} — <b>${format_money(users[game['initiator_id']]['balance'])}</b>\n"
            f"баланс {loser_link} — <b>${format_money(users[accepter_id]['balance'])}</b>",
            parse_mode='HTML'
    
    )
        basket_games.pop(chat_id, None)
        return
    
    print(f"DEBUG: opponent_scored={opponent_scored}, initiator_scored={initiator_scored}")
    if opponent_scored and not initiator_scored:
        users[accepter_id]['balance'] += amount * 2
        save_users()
        winner_link = f"<a href=\"tg://user?id={int(accepter_id)}\"><b>{opponent_nick}</b></a>"
        loser_link = f"<a href=\"tg://user?id={int(game['initiator_id'])}\"><b>{initiator_nick}</b></a>"
        await callback.message.answer(
            f"🏆 победил {winner_link} (2x - забил!)\n"
            f"💀 {loser_link} проиграл (x0)\n\n"
            f"баланс {winner_link} — <b>${format_money(users[accepter_id]['balance'])}</b>\n"
            f"баланс {loser_link} — <b>${format_money(users[game['initiator_id']]['balance'])}</b>",
            parse_mode='HTML'
    
    )
        basket_games.pop(chat_id, None)
        return
    
    # далее предполагается, что хотя бы один забил (не идеально) — сравниваем очки
    
    # оба забили (но не идеально) - определяем победителя по очкам
    if val1 > val2:
        winner_id = game['initiator_id']
        winner_val = val1
        loser_id = accepter_id
        loser_val = val2
    else:
        winner_id = accepter_id
        winner_val = val2
        loser_id = game['initiator_id']
        loser_val = val1
    
    # определяем множитель выигрыша
    # всегда 2x за победу
    win_amount = amount * 2
    multiplier_text = "2x"
    
    users[winner_id]['balance'] += win_amount
    save_users()
    
    winner_link = f"<a href=\"tg://user?id={int(winner_id)}\"><b>{users[winner_id].get('nick','игрок')}</b></a>"
    
    loser_link = f"<a href=\"tg://user?id={int(loser_id)}\"><b>{users[loser_id].get('nick','игрок')}</b></a>"
    
    await callback.message.answer(
        f"🏆 победил {winner_link} ({multiplier_text})\n\n"
        f"баланс {winner_link} — <b>${format_money(users[winner_id]['balance'])}</b>\n"
        f"баланс {loser_link} — <b>${format_money(users[loser_id]['balance'])}</b>",
        parse_mode='HTML'
    
    )
    
    basket_games.pop(chat_id, None)
# === конец мини-игры баскетбол ===

# глобальные переменные для игр
dice_games = {}

# глобальные переменные для топа
top_cache = {}
TOP_UPDATE_INTERVAL = 300  # 5 минут в секундах
TOP_PAGE_SIZE = 5  # игроков на страницу

# === мини-игра кости ===
@dp.message(F.text.lower().startswith('кости'))
async def dice_game(message: types.Message):
    """игра в кости"""
    # Проверяем, что это не личное сообщение
    if message.chat.type == 'private':
        markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='➕ добавить бота в чат', url='https://t.me/Dodeperplaybot?startgroup')]
        ])
        await message.answer(
            '🎲 игра в кости доступна только в чатах с другими игроками\n\n'
            'добавь бота в чат, чтобы играть!',
            reply_markup=markup
    
    )
        return
    
    user_id = str(message.from_user.id)
    
    # Убираем блокировку обычных пользователей - они должны иметь доступ к играм
    
    if user_id not in users:
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="создать человечка", callback_data="create_human")
        await message.answer("ты не зарегистрирован в боте", reply_markup=keyboard.as_markup())
        try:
            roulette_in_progress.discard(user_id)
        except Exception:
            pass
        return
    
    # парсим ставку
    text = message.text.lower()
    
    if any(tok in text for tok in ['все', 'всё', 'алл']):
        amount = users[user_id]['balance']
    else:
        try:
            # извлекаем сумму после слова "кости"
            amount_text = text.replace('кости', '').strip()
            amount = parse_amount(amount_text)
        except:
            await message.answer('напиши: кости <сумма> или кости все/всё/алл')
            return
    
    if amount <= 0:
        await message.answer('ставка должна быть больше 0')
        return
    
    if amount > users[user_id]['balance']:
        await message.answer('у тебя недостаточно денег для такой ставки')
        return
    
    chat_id = str(message.chat.id)
    
    # если уже есть игра, удаляем старую
    if chat_id in dice_games:
        old_game = dice_games[chat_id]
    
    try:
        pass
    except:
        pass
    
    # удаляем старую игру и уведомляем только если она была
    had_old_dice = chat_id in dice_games
    if had_old_dice:
        old_dice = dice_games.get(chat_id) or {}
        try:
            old_msg_id = old_dice.get('message_id')
            if old_msg_id:
                await bot.delete_message(chat_id, old_msg_id)
        except:
            pass
        dice_games.pop(chat_id, None)
        try:
            await message.answer('🔄 старая игра в кости отменена, создается новая')
        except Exception:
            pass
    
    # создаем игру
    dice_games[chat_id] = {
        'initiator_id': user_id,
        'initiator_nick': users[user_id]['nick'],
        'amount': amount,
        'message_id': None
    }
    
    # создаем клавиатуру
    kb = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='✅ принять', callback_data='dice_accept')],
        [InlineKeyboardButton(text='❌ отмена', callback_data='dice_cancel')]
    
    ])
    
    nick = users[user_id].get('nick','игрок')
    
    link = f"<a href=\"tg://user?id={int(user_id)}\"><b>{nick}</b></a>"
    caption = (
    
    f"🎲 {link} хочет сыграть в кости\n\n"
        f"ставка — <b>${format_money(amount)}</b>\n\n"
        f"жми принять, если готов"
    )
    
    msg = await message.answer(caption, parse_mode='HTML', reply_markup=kb)
    
    dice_games[chat_id]['message_id'] = msg.message_id

@dp.callback_query(lambda c: c.data == 'dice_cancel')
async def dice_cancel(callback: types.CallbackQuery):
    """отмена игры в кости"""
    chat_id = str(callback.message.chat.id)
    
    game = dice_games.get(chat_id)
    if not game:
        await callback.answer('игра не найдена', show_alert=False)
        return
    if str(callback.from_user.id) != game['initiator_id']:
        await callback.answer('отменить может только создатель', show_alert=True)
        return
    # удаляем сообщение с карточкой
    try:
        await bot.delete_message(chat_id, game.get('message_id'))
    except:
        pass
    dice_games.pop(chat_id, None)
    await callback.answer('отменено')

@dp.callback_query(lambda c: c.data == 'dice_accept')
async def dice_accept(callback: types.CallbackQuery):
    """принятие игры в кости"""
    chat_id = str(callback.message.chat.id)
    
    accepter_id = str(callback.from_user.id)
    game = dice_games.get(chat_id)
    
    if not game:
        await callback.answer('игра не найдена', show_alert=True)
        return
    
    if accepter_id == game['initiator_id']:
        await callback.answer('нужен второй игрок', show_alert=True)
        return
    
    if accepter_id not in users:
        await callback.answer('сначала зарегистрируйся', show_alert=True)
        return
    
    if users[accepter_id]['balance'] < game['amount']:
        await callback.answer('у тебя недостаточно денег для ставки', show_alert=True)
        return
    
    # проверяем баланс создателя
    if users.get(game['initiator_id'], {}).get('balance', 0) < game['amount']:
        try:
            await bot.delete_message(chat_id, game.get('message_id'))
        except:
            pass
        dice_games.pop(chat_id, None)
        await callback.message.answer('игра отменена — у создателя недостаточно денег')
        await callback.answer('игра отменена', show_alert=True)
        return
    
    # снимаем деньги с обоих игроков
    users[game['initiator_id']]['balance'] -= game['amount']
    users[accepter_id]['balance'] -= game['amount']
    save_users()
    
    # удаляем исходное сообщение
    try:
        await bot.delete_message(chat_id, game.get('message_id'))
    except:
        pass
    
    await callback.message.answer('начинаем игру')
    await callback.answer('игра началась!', show_alert=True)
    
    # броски: сначала текст «кто кидает», потом кидаем
    initiator_nick = users[game['initiator_id']].get('nick','игрок')
    
    opponent_nick = users[accepter_id].get('nick','игрок')
    initiator_link = f"<a href=\"tg://user?id={int(game['initiator_id'])}\"><b>{initiator_nick}</b></a>"
    
    opponent_link = f"<a href=\"tg://user?id={int(accepter_id)}\"><b>{opponent_nick}</b></a>"

    await callback.message.answer(f"кидает {opponent_link}", parse_mode='HTML')
    
    await asyncio.sleep(0.4)
    throw1 = await bot.send_dice(chat_id, emoji='🎲')
    
    await asyncio.sleep(3)
    
    await callback.message.answer(f"кидает {initiator_link}", parse_mode='HTML')
    
    await asyncio.sleep(0.4)
    throw2 = await bot.send_dice(chat_id, emoji='🎲')
    
    await asyncio.sleep(3)
    
    val1 = throw1.dice.value
    
    val2 = throw2.dice.value
    
    if val1 == val2:
        users[game['initiator_id']]['balance'] += game['amount']
        users[accepter_id]['balance'] += game['amount']
        save_users()
        await callback.message.answer(
            'ничья\n\n'
            f"баланс {initiator_link} — <b>${format_money(users[game['initiator_id']]['balance'])}</b>\n"
            f"баланс {opponent_link} — <b>${format_money(users[accepter_id]['balance'])}</b>",
            parse_mode='HTML'
        )
        dice_games.pop(chat_id, None)
        return
    
    if val1 > val2:
        winner_id = accepter_id
        winner_val = val1
        loser_id = game['initiator_id']
        loser_val = val2
    else:
        winner_id = game['initiator_id']
        winner_val = val2
        loser_id = accepter_id
        loser_val = val1
    
    # начисляем выигрыш
    win_amount = game['amount'] * 2  # всегда x2 ставки
    
    users[winner_id]['balance'] += win_amount
    save_users()
    
    winner_link = f"<a href=\"tg://user?id={int(winner_id)}\"><b>{users[winner_id].get('nick','игрок')}</b></a>"
    
    loser_link = f"<a href=\"tg://user?id={int(loser_id)}\"><b>{users[loser_id].get('nick','игрок')}</b></a>"
    
    await callback.message.answer(
        f"🎲 {loser_link} проиграл игроку {winner_link} <b>${format_money(game['amount'])}</b>.\n\n"
        f"• результат игры — <b>{loser_val}:{winner_val}</b>\n"
        f"• баланс {loser_link} — <b>${format_money(users[loser_id]['balance'])}</b>\n"
        f"• баланс {winner_link} — <b>${format_money(users[winner_id]['balance'])}</b>",
        parse_mode='HTML'
    
    )
    
    dice_games.pop(chat_id, None)
# === конец мини-игры кости ===

# === команда топ ===
def get_top_players():
    """получает топ игроков по балансу (только топ 100)"""
    # сортируем пользователей по балансу (по убыванию)
    sorted_users = sorted(users.items(), key=lambda x: x[1].get('balance', 0), reverse=True)
    
    # НЕ фильтруем скрытых игроков - они остаются в топе, но без ссылок
    # visible_users = [(uid, user_data) for uid, user_data in sorted_users if not user_data.get('hide_from_top', False)]
    
    # возвращаем только топ 100
    return sorted_users[:100]

def get_user_position(user_id: str) -> int:
    """получает позицию пользователя в топе"""
    sorted_users = get_top_players()
    
    for i, (uid, _) in enumerate(sorted_users):
        if uid == user_id:
            return i + 1
    return len(sorted_users) + 1

async def show_top_page(message: types.Message, page: int = 0):
    
    """показывает страницу топа"""
    user_id = str(message.from_user.id)
    
    # получаем топ игроков
    top_players = get_top_players()
    
    total_players = len(top_players)
    
    # вычисляем позицию пользователя
    user_position = get_user_position(user_id)
    
    # вычисляем границы страницы
    start_idx = page * TOP_PAGE_SIZE
    
    end_idx = min(start_idx + TOP_PAGE_SIZE, total_players)
    
    if start_idx >= total_players:
        page = 0
        start_idx = 0
        end_idx = min(TOP_PAGE_SIZE, total_players)
    
    # формируем текст топа
    top_text = f"💰 <b>топ 100 самых богатых игроков</b>\n"
    
    if user_id in users:
        top_text += f"<i>(ты на {user_position}-м месте):</i>\n\n"
    else:
        top_text += "\n"
    
    # добавляем игроков на страницу
    for i in range(start_idx, end_idx):
        rank = i + 1
        uid, user_data = top_players[i]
        nick = user_data.get('nick', 'неизвестно')
        balance = user_data.get('balance', 0)
        
        # добавляем эмодзи для топ-3
        if rank == 1:
            rank_text = "🥇"
        elif rank == 2:
            rank_text = "🥈"
        elif rank == 3:
            rank_text = "🥉"
        else:
            rank_text = f"{rank}."
        
        # создаем ссылку на пользователя (если не скрыт из топа)
        hide_from_top = user_data.get('hide_from_top', False)
        if hide_from_top:
            user_link = f"<b>{nick}</b>"
        else:
            user_link = f"<a href=\"tg://user?id={int(uid)}\"><b>{nick}</b></a>"
        
        balance_text = f"<b>${format_money(balance)}</b>"
        
        top_text += f"{rank_text} {user_link} — {balance_text}\n"
    
    # добавляем информацию об обновлении
    top_text += f"\n<i>топ обновляется раз в 5 минут</i>"
    
    # создаем клавиатуру для пагинации
    keyboard = []
    
    # кнопка "назад" если не первая страница
    if page > 0:
        keyboard.append([InlineKeyboardButton(text='⬅️ назад', callback_data=f'top_page_{page-1}')])
    
    # кнопка "вперед" если есть следующая страница и мы не достигли 100 игроков
    if end_idx < total_players and end_idx < 100:
        keyboard.append([InlineKeyboardButton(text='след ➡️', callback_data=f'top_page_{page+1}')])
    
    # если нет кнопок, добавляем пустую строку
    if not keyboard:
        keyboard.append([InlineKeyboardButton(text='📊 топ обновлен', callback_data='top_refresh')])
    
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    return top_text, markup

@dp.message(F.text.lower() == 'топ')
async def show_top(message: types.Message):
    """показывает топ игроков"""
    user_id = str(message.from_user.id)
    
    # Убираем блокировку обычных пользователей - они должны иметь доступ к топу
    
    # проверяем, зарегистрирован ли пользователь
    if user_id not in users:
        await message.answer('сначала зарегистрируйся командой /start')
        return
    
    # показываем первую страницу топа
    top_text, markup = await show_top_page(message, 0)
    
    await message.answer(top_text, parse_mode='HTML', reply_markup=markup)

@dp.callback_query(lambda c: c.data.startswith('top_page_'))
async def top_page_callback(callback: types.CallbackQuery):
    """обработчик пагинации топа"""
    
    # Убираем блокировку обычных пользователей - они должны иметь доступ к топу
    
    try:
        page = int(callback.data.split('_')[2])
        top_text, markup = await show_top_page(callback.message, page)
        
        # редактируем сообщение
        await callback.message.edit_text(top_text, parse_mode='HTML', reply_markup=markup)
        await callback.answer()
    except Exception as e:
        try:
            await callback.answer('ошибка при загрузке страницы', show_alert=True)
        except:
            pass

@dp.callback_query(lambda c: c.data == 'top_refresh')
async def top_refresh_callback(callback: types.CallbackQuery):
    """обновляет топ"""
    
    # Убираем блокировку обычных пользователей - они должны иметь доступ к топу
    
    await callback.answer('топ обновляется каждые 5 минут')
# === конец команды топ ===
# === рулетка ===
def create_roulette_result_image(number, color, bet_type, amount, won, multiplier, win_amount):
    """создает изображение рулетки с результатом игры
    
    Логика работы:
    - Для числа 0 (зеро): использует rul__zero.jpg (зеленая картинка, ноль уже есть)
    - Для красных чисел: использует rul_red.jpg, пишет число на красной полоске внизу
    - Для черных чисел: использует rul_black.jpg, пишет число на черной полоске внизу
    
    Числа пишутся белым цветом на полоске внизу изображения
    """
    try:
        # открываем базовое изображение рулетки в зависимости от цвета выпавшего числа
        if number == 0:
            # зеро - зеленая картинка (используем rul__zero.jpg)
            base_image = Image.open('img/rul__zero.jpg')
        elif color == 'red':
            # красное число - красная картинка
            base_image = Image.open('img/rul_red.jpg')
        else:
            # черное число - черная картинка
            base_image = Image.open('img/rul_black.jpg')
        
        # создаем копию для рисования
        img = base_image.copy()
        draw = ImageDraw.Draw(img)
        
        # пытаемся загрузить шрифт, если не получается - используем стандартный
        try:
            # Уменьшаем размер шрифта для лучшего размещения
            font = ImageFont.truetype("arial.ttf", 50)
        except:
            try:
                # Пробуем другие шрифты если arial не найден
                font = ImageFont.truetype("DejaVuSans-Bold.ttf", 70)
            except:
                try:
                    font = ImageFont.truetype("LiberationSans-Bold.ttf", 70)
                except:
                    # Если ничего не найдено, используем стандартный
                    font = ImageFont.load_default()
        
        # получаем размеры изображения
        width, height = img.size
        
        # рисуем выпавшее число на соответствующей полоске (кроме зеро)
        if number != 0:  # не рисуем число для зеро, так как оно уже есть на картинке
            number_text = str(number)
            text_bbox = draw.textbbox((0, 0), number_text, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            
            # позиция для текста - по горизонтали по центру, по вертикали на полоске внизу
            x = (width - text_width) // 2
            
            if color == 'red':
                # для красных чисел - на красной полоске внизу, чуть пониже
                y = height - 120  # на красной полоске внизу, чуть пониже
                text_color = (255, 255, 255)  # белый текст на красном фоне
            else:
                # для черных чисел - на черной полоске внизу, чуть пониже
                y = height - 120  # на черной полоске внизу, чуть пониже
                text_color = (255, 255, 255)  # белый текст на черном фоне
            
            # рисуем тень для текста (черная тень для лучшей читаемости)
            shadow_color = (0, 0, 0)  # черная тень
            draw.text((x+2, y+2), number_text, fill=shadow_color, font=font)
            
            # рисуем основной текст на полоске внизу
            draw.text((x, y), number_text, fill=text_color, font=font)
        
        # сохраняем временное изображение в папку img
        temp_path = f'img/temp_roulette_{random.randint(1000, 9999)}.png'
        img.save(temp_path, 'PNG')
        
        return temp_path
        
    except Exception as e:
        print(f"Ошибка создания изображения рулетки: {e}")
        return None

def get_roulette_number_color(number):
    """определяет цвет числа в рулетке"""
    if number == 0:
        return 'green'
    
    # красные числа
    red_numbers = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
    
    if number in red_numbers:
        return 'red'
    else:
        return 'black'



# Убираем лишние защиты - оставляем только исправление бага

@dp.message(F.text.lower().startswith('рул'))
async def roulette_handler(message: types.Message):
    """обработчик рулетки - информация или игра"""
    user_id = str(message.from_user.id)

    # Блокировка параллельной обработки ставок одного игрока: молча игнорируем вторую ставку
    if user_id in roulette_in_progress:
        return
    roulette_in_progress.add(user_id)
    
    # Убираем защиту от флуда - не нужна
    
    # проверяем, зарегистрирован ли пользователь
    if user_id not in users:
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text="создать человечка", callback_data="create_human")
        await message.answer("ты не зарегистрирован в боте", reply_markup=keyboard.as_markup())
        return
    
    # парсим сообщение
    parts = message.text.lower().split()
    
    # если только "рул" - показываем информацию
    if len(parts) == 1:
        try:
            # добавляем небольшую задержку для предотвращения flood control
            await asyncio.sleep(0.5)
            await bot.send_photo(
                message.chat.id,
                types.FSInputFile('img/rul_info.jpg'),
                caption="🃏 <b>используй:</b>\n"
    
    "<code>рул ставка сумма</code>\n\n"
                        "<b>ставить можно на:</b>\n"
                        "• чёрное/черное/чер (x2)\n"
                        "• красное/крас/кра (x2)\n"
                        "• зеро/ноль/з (x36)\n"
                        "• чёт/четное/чет (x2)\n"
                        "• нечёт/нечетное/нч (x2)\n"
                        "• ряд1, ряд2, ряд3 (x3)\n"
                        "• 1-12, 13-24, 25-36 (x3)\n"
                        "• 1-18, 19-36 (x2)\n"
                        "• числа 0-36 (x36)\n\n"
                        "💡 <b>примеры:</b>\n"
                        "<code>рул чёрное 1000</code>\n"
                        "<code>рул красное 500к</code>\n"
                        "<code>рул зеро 100</code>\n"
                        "<code>рул 13-24 1к</code>",
                parse_mode='HTML'
            )
        except Exception as e:
            await message.answer(f"ошибка отправки информации о рулетке: {e}")
        try:
            roulette_in_progress.discard(user_id)
        except Exception:
            pass
        return
    
    # если есть аргументы - играем в рулетку
    if len(parts) < 3:
        await message.answer('используй: рул ставка сумма\nнапример: рул чёрное 1000')
        try:
            roulette_in_progress.discard(user_id)
        except Exception:
            pass
        return
    if len(parts) > 3:
        await message.answer('нельзя указывать несколько ставок сразу. используй формат: рул <ставка> <сумма>\nнапример: рул 13-24 1к или рул нечёт 1к')
        try:
            roulette_in_progress.discard(user_id)
        except Exception:
            pass
        return
    
    bet_type = parts[1]
    # Нормализуем тип ставки: приводим разные тире к дефису и убираем лишние пробелы
    bet_type = bet_type.replace('–', '-').replace('—', '-').replace('−', '-').strip()
    
    # запрет на вторую ставку вместо суммы (например: "рул неч 13-24 20ккк")
    amount_token = parts[2]
    
    conflicting_bet_tokens = {
        'чёрное','чер','черное','черн','чёрн','ч','чёр',
        'красное','крас','кр','красн','крас','к',
        'зеро','з','ноль','нуль','зер','зе','0',
        'чёт','чет','четное','четн','чётное','чётн',
        'нечёт','нечет','нч','нечетное','нечетн','нечётное','нечётн','неч',
        'ряд1','ряд 1','1ряд','1 ряд','р1','1р',
        'ряд2','ряд 2','2ряд','2 ряд','р2','2р',
        'ряд3','ряд 3','3ряд','3 ряд','р3','3р',
        '1-12','13-24','25-36','1-18','19-36',
        'малые','малый','м','мал','большие','большой','б','бол'
    }
    if '-' in amount_token or amount_token in conflicting_bet_tokens:
        await message.answer('нельзя указывать несколько ставок сразу. используй формат: рул <ставка> <сумма>\nнапример: рул 13-24 1к или рул нечёт 1к')
        try:
            roulette_in_progress.discard(user_id)
        except Exception:
            pass
        return
    
    # Ранняя проверка валидности типа ставки, чтобы не списывать деньги при неверной ставке
    recognized_types = [
        'чёрное', 'чер', 'черное', 'черн', 'чёрн', 'ч', 'чёр',
        'красное', 'кра', 'кр', 'красн', 'крас', 'к', 'красн',
        'зеро', 'з', 'ноль', 'нуль', '0', 'зер', 'зе',
        'чёт', 'чет', 'ч', 'четное', 'четн', 'чётное', 'чётн', 'чётн', 'четн',
        'нечёт', 'нечет', 'нч', 'нечетное', 'нечетн', 'нечётное', 'нечётн', 'нечётн', 'нечетн', 'неч',
        'ряд1', 'ряд 1', '1ряд', '1 ряд', 'р1', '1р',
        'ряд2', 'ряд 2', '2ряд', '2 ряд', 'р2', '2р',
        'ряд3', 'ряд 3', '3ряд', '3 ряд', 'р3', '3р',
        '1-12', 'первая дюжина', '1дюжина', '1 дюжина', '1д', 'д1',
        '13-24', 'вторая дюжина', '2дюжина', '2 дюжина', '2д', 'д2',
        '25-36', 'третья дюжина', '3дюжина', '3 дюжина', '3д', 'д3',
        '1-18', 'малые', 'малый', 'м', 'мал',
        '19-36', 'большие', 'большой', 'б', 'бол'
    ]
    import re
    if bet_type not in recognized_types and not (bet_type.isdigit() and 0 <= int(bet_type) <= 36) and not re.match(r'^(\d{1,2})-(\d{1,2})$', bet_type):
        await message.answer(f'неизвестный тип ставки "{bet_type}". используй: рул чёрное 1000 или рул 13-24 1к')
        try:
            roulette_in_progress.discard(user_id)
        except Exception:
            pass
        return
    
    # обработка сокращений и специальных ставок
    if len(parts) >= 3 and parts[2] in ['вб', 'все', 'всё', 'алл', 'вабанк', 'вс', 'в', 'ваб', 'вабан', 'вседеньги', 'всёденьги']:
        amount = users[user_id]['balance']  # ставка всеми деньгами
    else:
        try:
            amount = parse_amount(parts[2])
        except Exception as e:
            await message.answer('неверная сумма. используй: рул чёрное 1000')
            try:
                roulette_in_progress.discard(user_id)
            except Exception:
                pass
            return
    
    # проверяем, что ставка больше 0
    if amount <= 0:
        await message.answer('ставка должна быть больше 0')
        try:
            roulette_in_progress.discard(user_id)
        except Exception:
            pass
        return
    
    # проверяем баланс (кроме ставки всеми деньгами)
    if len(parts) < 3 or parts[2] not in ['вб', 'все', 'всё', 'алл', 'вабанк', 'вс', 'в', 'ваб', 'вабан', 'вседеньги', 'всёденьги']:
        if users[user_id]['balance'] < amount:
            await message.answer(f"у тебя недостаточно денег. на счету: <b>${format_money(users[user_id]['balance'])}</b>", parse_mode='HTML')
            try:
                roulette_in_progress.discard(user_id)
            except Exception:
                pass
            return
    
    # Списываем ставку СРАЗУ после проверки баланса
    users[user_id]['balance'] -= amount
    
    # Для занижения шансов только при многократном повторе одной ставки ведём минимальный стрик
    user_streak = roulette_bet_streaks.get(user_id, {'bet_type': None, 'streak': 0})

    # Доп. валидация типа ставки до генерации исхода
    recognized_types = [
        'чёрное', 'чер', 'черное', 'черн', 'чёрн', 'ч', 'чёр',
        'красное', 'кра', 'кр', 'красн', 'крас', 'к', 'красн',
        'зеро', 'з', 'ноль', 'нуль', '0', 'зер', 'зе',
        'чёт', 'чет', 'ч', 'четное', 'четн', 'чётное', 'чётн', 'чётн', 'четн',
        'нечёт', 'нечет', 'нч', 'нечетное', 'нечетн', 'нечётное', 'нечётн', 'нечётн', 'нечетн', 'неч',
        'ряд1', 'ряд 1', '1ряд', '1 ряд', 'р1', '1р',
        'ряд2', 'ряд 2', '2ряд', '2 ряд', 'р2', '2р',
        'ряд3', 'ряд 3', '3ряд', '3 ряд', 'р3', '3р',
        '1-12', 'первая дюжина', '1дюжина', '1 дюжина', '1д', 'д1',
        '13-24', 'вторая дюжина', '2дюжина', '2 дюжина', '2д', 'д2',
        '25-36', 'третья дюжина', '3дюжина', '3 дюжина', '3д', 'д3',
        '1-18', 'малые', 'малый', 'м', 'мал',
        '19-36', 'большие', 'большой', 'б', 'бол'
    ]
    import re
    if bet_type not in recognized_types and not (bet_type.isdigit() and 0 <= int(bet_type) <= 36) and not re.match(r'^(\d{1,2})-(\d{1,2})$', bet_type):
        await message.answer(f'неизвестный тип ставки "{bet_type}". используй: рул чёрное 1000 или рул 13-24 1к')
        try:
            roulette_in_progress.discard(user_id)
        except Exception:
            pass
        return

    # Сформируем множество выигрышных чисел для ставки
    win_numbers = set()
    # Цвета
    if bet_type in ['чёрное', 'чер', 'черное', 'черн', 'чёрн', 'ч', 'чёр']:
        win_numbers = {n for n in range(1, 37) if get_roulette_number_color(n) == 'black'}
    elif bet_type in ['красное', 'кра', 'кр', 'красн', 'крас', 'к', 'красн']:
        win_numbers = {n for n in range(1, 37) if get_roulette_number_color(n) == 'red'}
    # Ноль
    elif bet_type in ['зеро', 'з', 'ноль', 'нуль', '0', 'зер', 'зе']:
        win_numbers = {0}
    # Чет / Нечет (0 всегда проигрыш)
    elif bet_type in ['чёт', 'чет', 'ч', 'четное', 'четн', 'чётное', 'чётн', 'чётн', 'четн']:
        win_numbers = {n for n in range(1, 37) if n % 2 == 0}
    elif bet_type in ['нечёт', 'нечет', 'нч', 'нечетное', 'нечетн', 'нечётное', 'нечётн', 'нечётн', 'нечетн', 'неч']:
        win_numbers = {n for n in range(1, 37) if n % 2 == 1}
    # Ряды
    elif bet_type in ['ряд1', 'ряд 1', '1ряд', '1 ряд', 'р1', '1р']:
        win_numbers = {1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34}
    elif bet_type in ['ряд2', 'ряд 2', '2ряд', '2 ряд', 'р2', '2р']:
        win_numbers = {2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35}
    elif bet_type in ['ряд3', 'ряд 3', '3ряд', '3 ряд', 'р3', '3р']:
        win_numbers = {3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36}
    # Дюжины
    elif bet_type in ['1-12', 'первая дюжина', '1дюжина', '1 дюжина', '1д', 'д1']:
        win_numbers = set(range(1, 13))
    elif bet_type in ['13-24', 'вторая дюжина', '2дюжина', '2 дюжина', '2д', 'д2']:
        win_numbers = set(range(13, 25))
    elif bet_type in ['25-36', 'третья дюжина', '3дюжина', '3 дюжина', '3д', 'д3']:
        win_numbers = set(range(25, 37))
    # Поля 1-18 / 19-36
    elif bet_type in ['1-18', 'малые', 'малый', 'м', 'мал']:
        win_numbers = set(range(1, 19))
    elif bet_type in ['19-36', 'большие', 'большой', 'б', 'бол']:
        win_numbers = set(range(19, 37))
    # Диапазон формата a-b
    elif re.match(r'^(\d{1,2})-(\d{1,2})$', bet_type):
        a, b = map(int, bet_type.split('-'))
        if 1 <= a <= b <= 36:
            win_numbers = set(range(a, b + 1))
        else:
            await message.answer('некорректный диапазон. используй, например: 13-24')
            try:
                roulette_in_progress.discard(user_id)
            except Exception:
                pass
            return
    # Конкретное число
    elif bet_type.isdigit() and 0 <= int(bet_type) <= 36:
        win_numbers = {int(bet_type)}

    # Система в пользу казино — аккуратно влияет только на выбор числа, но не ломает правила
    player_balance = users[user_id]['balance']
    bet_percentage = (amount / player_balance) * 100 if player_balance > 0 else 0

    # Базовый шанс проигрыша по балансу (улучшен для более честной игры)
    if player_balance <= 1_000_000:
        base_lose_chance = 0.20  # было 0.50 - улучшили на 5%
    elif player_balance <= 10_000_000:
        base_lose_chance = 0.20  # было 0.52 - улучшили на 5%
    elif player_balance <= 100_000_000:
        base_lose_chance = 0.20  # было 0.55 - улучшили на 6%
    elif player_balance <= 1_000_000_000:
        base_lose_chance = 0.20  # было 0.58 - улучшили на 7%
    elif player_balance <= 10_000_000_000:
        base_lose_chance = 0.20  # было 0.60 - улучшили на 7%
    elif player_balance <= 100_000_000_000:
        base_lose_chance = 0.20  # было 0.63 - улучшили на 8%
    elif player_balance <= 1_000_000_000_000:
        base_lose_chance = 0.20  # было 0.66 - улучшили на 9%
    else:
        base_lose_chance = 0.20  # было 0.68 - улучшили на 9%

    # Бонус к шансу проигрыша по размеру ставки (значительно улучшен)
    if bet_percentage <= 5:
        bet_bonus = 0.00  # маленькие ставки - без штрафа
    elif bet_percentage <= 15:
        bet_bonus = 0.00  # было 0.01 - улучшили в 2 раза
    elif bet_percentage <= 30:
        bet_bonus = 0.00  # было 0.015 - улучшили почти в 2 раза
    elif bet_percentage <= 50:
        bet_bonus = 0.0   # было 0.02 - улучшили в 2 раза
    elif bet_percentage <= 80:
        bet_bonus = 0.0  # было 0.02 - улучшили почти в 2 раза
    else:
        bet_bonus = 0.0  # было 0.025 - улучшили почти в 2 раза

    # общий шанс проигрыша ограничиваем 50% для более комфортной игры
    # но для x2 ставок (18 чисел) максимальный шанс выигрыша 50%
    # для x3 ставок (12 чисел) максимальный шанс выигрыша 33.33%
    lose_chance = min(base_lose_chance + bet_bonus, 0.50)

    # Генерируем исход с учётом систем: шанс проигрыша зависит от баланса и процента ставки
    all_numbers = set(range(37))
    lose_numbers = list(all_numbers - win_numbers)
    win_numbers_list = list(win_numbers)
    # Защита от пустых множеств (на всякий случай)
    if not win_numbers_list:
        number = random.randint(0, 36)
    else:
        # Базовая вероятность выигрыша
        win_probability = max(0.0, min(1.0, 1 - lose_chance))

        # Потолки вероятности выигрыша по типу ставки (улучшены)
        # x2 ставки (цвета, чет/нечет, 1-18/19-36) - 60% шанс (было 55%)
        # x3 ставки (ряды, дюжины) - 40% шанс (было 38%)
        # x36 ставки (конкретные числа, зеро) - 3% шанс (было 2%)
        type_cap_win_prob = 0.35  # было 0.28 - улучшили на 25%
        if len(win_numbers) <= 1:
            # одиночное число или зеро (x36)
            type_cap_win_prob = 0.03   # было 0.02 - улучшили на 50%
        elif len(win_numbers) in (12,):
            # дюжины и ряды (x3)
            type_cap_win_prob = 0.65   # было 0.38 - улучшили до 40%
        elif len(win_numbers) in (18,):
            # цвет, чёт/нечёт, 1-18/19-36 (x2)
            type_cap_win_prob = 0.60   # было 0.55 - улучшили до 60%
        elif 2 <= len(win_numbers) <= 6:
            # узкие пользовательские диапазоны (2-6 чисел)
            type_cap_win_prob = 0.65   # было 0.22 - улучшили на 27%
        else:
            # остальные случаи (включая произвольные диапазоны)
            type_cap_win_prob = 0.65   # было 0.28 - улучшили на 25%

        # Применяем только глобальные потолки
        win_probability = min(win_probability, type_cap_win_prob)

        # Буст за серию проигрышей: игроку, который часто проигрывал, поднимаем шанс (улучшено)
        # Храним в users[user]['roulette_loss_streak']
        loss_streak = int(users[user_id].get('roulette_loss_streak', 0))
        if loss_streak >= 2:  # было 3 - снизили порог
            # Улучшенные бусты: 2 — +8п.п., 4 — +15п.п., 6 — +22п.п., 8 — +30п.п.
            boost = 0.0
            if loss_streak >= 8:
                boost = 0.30  # было 0.15 - удвоили
            elif loss_streak >= 6:
                boost = 0.22  # было 0.10 - удвоили
            elif loss_streak >= 4:
                boost = 0.15  # было 0.10 - улучшили на 50%
            else:
                boost = 0.08  # было 0.05 - улучшили на 60%
            win_probability = min(type_cap_win_prob, win_probability + boost)
            
        # Для числа/зеро: после бустов ограничиваем максимумом 3% (улучшили с 2%)
        if len(win_numbers) <= 1:
            win_probability = min(0.03, win_probability)  # было 0.02 - улучшили на 50%

        # === АНТИ-БОНУСЫ ДЛЯ ТОП-3 ИГРОКОВ ===
        # Скрытое «проклятие» топ-3: снижаем шанс победы (усилено)
        try:
            position = get_user_position(user_id)
            if position <= 3:
                # Усиленное занижение для топ-3
                win_probability *= 0.99  # -25% для топ-3
                # Доп. ослабление для 1-го места
                if position == 1:
                    win_probability *= 0.99  # ещё -20% для 1-го места
                elif position == 2:
                    win_probability *= 0.99  # ещё -15% для 2-го места
                elif position == 3:
                    win_probability *= 0.99  # ещё -10% для 3-го места
        except Exception:
            pass

        # === СИСТЕМА "ЧЕМ БОЛЬШЕ ШАНС, ТЕМ БОЛЬШЕ РИСК" ===
        # Чем выше шанс выигрыша, тем больше вероятность проигрыша (но не очень сильно)
        if win_probability > 0.5:  # Если шанс больше 50%
            risk_multiplier = 1.0 + (win_probability - 0.5) * 0.1  # Максимум +15% к проигрышу
            win_probability /= risk_multiplier
            print(f"🎰 Риск-множитель для {user_id}: x{risk_multiplier:.2f} (шанс: {win_probability*100:.1f}%)")
        elif win_probability > 0.3:  # Если шанс больше 30%
            risk_multiplier = 1.0 + (win_probability - 0.3) * 0.1  # Максимум +4% к проигрышу
            win_probability /= risk_multiplier
            print(f"🎰 Риск-множитель для {user_id}: x{risk_multiplier:.2f} (шанс: {win_probability*100:.1f}%)")

        # Если игрок ставит один и тот же тип ставки подряд 8+ раз, вводим мягкое занижение шанса (улучшено)
        if user_streak['bet_type'] == bet_type:
            current_streak = user_streak.get('streak', 0) + 1
        else:
            current_streak = 1

        if current_streak >= 8:  # было 6 - увеличили порог
            # Более мягкое занижение: -10% вместо -15%, и не ниже 40% от потолка
            win_probability *= 0.99  # было 0.85 - улучшили с -15% до -10%
            min_floor = max(0.001, type_cap_win_prob * 0.40)  # было 0.30 - улучшили до 40%
            win_probability = max(min_floor, win_probability)

        # === АНТИ-БОНУСЫ ДЛЯ БОГАТЫХ ИГРОКОВ ===
        # Понижение шансов для больших ставок (>= 70ккк) - усилено
        if amount >= 300_000_000_000:
            win_probability *= 0.99  # -35% для очень больших ставок
        elif amount >= 70_000_000_000:
            win_probability *= 0.99  # -20% для больших ставок

        # Дополнительные анти-бонусы по абсолютному балансу игрока
        player_balance = users[user_id]['balance']
        if player_balance >= 1_000_000_000_000:  # 1кккк+
            balance_penalty = 0.99  # -15% для очень богатых
            win_probability *= balance_penalty
            print(f"🎰 Анти-бонус по балансу для {user_id}: x{balance_penalty} (баланс: ${format_money(player_balance)})")
        elif player_balance >= 100_000_000_000:  # 100ккк+
            balance_penalty = 0.99  # -10% для богатых
            win_probability *= balance_penalty
            print(f"🎰 Анти-бонус по балансу для {user_id}: x{balance_penalty} (баланс: ${format_money(player_balance)})")

        # === ПРОКЛЯТИЕ УДАЧИ ===
        # Если у игрока очень высокий шанс выигрыша, добавляем скрытое проклятие
        if win_probability > 0.4:  # Если шанс больше 40%
            curse_strength = min(0.15, (win_probability - 0.4) * 0.5)  # Максимум -15%
            curse_multiplier = 1.0 - curse_strength
            win_probability *= curse_multiplier
            print(f"🎰 Проклятие удачи для {user_id}: -{curse_strength*100:.1f}% (финальный шанс: {win_probability*100:.1f}%)")

        # === ФИНАЛЬНАЯ ЗАЩИТА ОТ СЛИШКОМ НИЗКИХ ШАНСОВ ===
        # Убеждаемся, что шанс не стал слишком низким после всех анти-бонусов
        min_safe_probability = type_cap_win_prob * 0.3  # Минимум 30% от потолка типа ставки
        if win_probability < min_safe_probability:
            old_probability = win_probability
            win_probability = min_safe_probability
            print(f"🎰 Защита от слишком низких шансов для {user_id}: {old_probability*100:.1f}% → {win_probability*100:.1f}%")

        # Обновим локальную переменную стрика (запишем после завершения игры)
        user_streak_next = {'bet_type': bet_type, 'streak': current_streak}



        if random.random() < win_probability and win_numbers_list:
            number = random.choice(win_numbers_list)
        else:
            # если по какой-то причине lose_numbers пуст, выберем из всех
            if lose_numbers:
                number = random.choice(lose_numbers)
            else:
                number = random.randint(0, 36)
    
    color = get_roulette_number_color(number)
    
    # определяем выигрыш с учетом размера ставки
    won = False
    
    multiplier = 0
    
    # определяем, выиграл ли игрок по правилам рулетки
    should_win_by_rules = False
    
    bet_multiplier = 0
    
    # обработка сокращений для типов ставок
    # определяем базовый множитель выплаты по типу ставки (независимо от результата)
    import re
    type_multiplier = 0
    range_match = re.match(r'^(\d{1,2})-(\d{1,2})$', bet_type)
    if bet_type.isdigit() and 0 <= int(bet_type) <= 36:
        type_multiplier = 36
    elif bet_type in ['зеро', 'з', 'ноль', 'нуль', '0', 'зер', 'зе']:
        type_multiplier = 36
    elif range_match:
        a = int(range_match.group(1))
        b = int(range_match.group(2))
        if (a, b) in [(1, 18), (19, 36)]:
            type_multiplier = 2
        elif 1 <= a <= b <= 36 and (b - a + 1) == 12:
            type_multiplier = 3
        else:
            type_multiplier = 0
    elif bet_type in ['ряд1', 'ряд 1', '1ряд', '1 ряд', 'р1', '1р',
                      'ряд2', 'ряд 2', '2ряд', '2 ряд', 'р2', '2р',
                      'ряд3', 'ряд 3', '3ряд', '3 ряд', 'р3', '3р',
                      '1-12', '13-24', '25-36']:
        type_multiplier = 3
    elif bet_type in ['1-18', '19-36', 'малые', 'малый', 'м', 'мал', 'большие', 'большой', 'б', 'бол',
                      'чёт', 'чет', 'ч', 'четное', 'четн', 'чётное', 'чётн',
                      'нечёт', 'нечет', 'нч', 'нечетное', 'нечетн', 'нечётное', 'нечётн', 'неч']:
        type_multiplier = 2
    if bet_type in ['чёрное', 'чер', 'черное', 'черн', 'чёрн', 'ч', 'чёр'] and color == 'black':
        should_win_by_rules = True
        bet_multiplier = 2
    elif bet_type in ['красное', 'кра', 'кр', 'красн', 'крас', 'к', 'красн'] and color == 'red':
        should_win_by_rules = True
        bet_multiplier = 2
    elif bet_type in ['зеро', 'з', 'ноль', 'нуль', '0', 'зер', 'зе'] and number == 0:
        should_win_by_rules = True
        bet_multiplier = 36
    elif bet_type in ['чёт', 'чет', 'ч', 'четное', 'четн', 'чётное', 'чётн', 'чётн', 'четн'] and number != 0 and number % 2 == 0:
        should_win_by_rules = True
        bet_multiplier = 2
    elif bet_type in ['нечёт', 'нечет', 'нч', 'нечетное', 'нечетн', 'нечётное', 'нечётн', 'нечётн', 'нечетн', 'неч'] and number % 2 == 1:
        should_win_by_rules = True
        bet_multiplier = 2
    
    # ставки на ряды
    if bet_type in ['ряд1', 'ряд 1', '1ряд', '1 ряд', 'р1', '1р', 'ряд1', 'ряд1'] and number in [1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34]:
        should_win_by_rules = True
        bet_multiplier = 3
    if bet_type in ['ряд2', 'ряд 2', '2ряд', '2 ряд', 'р2', '2р', 'ряд2', 'ряд2'] and number in [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35]:
        should_win_by_rules = True
        bet_multiplier = 3
    if bet_type in ['ряд3', 'ряд 3', '3ряд', '3 ряд', 'р3', '3р', 'ряд3', 'ряд3'] and number in [3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36]:
        should_win_by_rules = True
        bet_multiplier = 3
    # ставки на дюжины
    if bet_type in ['1-12', 'первая дюжина', '1дюжина', '1 дюжина', '1д', 'д1'] and 1 <= number <= 12:
        should_win_by_rules = True
        bet_multiplier = 3
    if bet_type in ['13-24', 'вторая дюжина', '2дюжина', '2 дюжина', '2д', 'д2'] and 13 <= number <= 24:
        should_win_by_rules = True
        bet_multiplier = 3
    if bet_type in ['25-36', 'третья дюжина', '3дюжина', '3 дюжина', '3д', 'д3'] and 25 <= number <= 36:
        should_win_by_rules = True
        bet_multiplier = 3
    # универсальная проверка диапазона вида a-b
    if range_match:
        a = int(range_match.group(1))
        b = int(range_match.group(2))
        if 1 <= a <= b <= 36 and a <= number <= b:
            # определить множитель по правилам: 1-18/19-36 = x2, дюжины = x3
            if (a, b) in [(1, 18), (19, 36)]:
                should_win_by_rules = True
                bet_multiplier = 2
            elif (b - a + 1) == 12:
                should_win_by_rules = True
                bet_multiplier = 3
    # ставки на сектора
    if bet_type in ['1-18', '1-18', 'малые', 'малый', 'м', 'мал', '1-18', '1-18'] and 1 <= number <= 18:
        should_win_by_rules = True
        bet_multiplier = 2
    if bet_type in ['19-36', '19-36', 'большие', 'большой', 'б', 'бол', '19-36', '19-36'] and 19 <= number <= 36:
        should_win_by_rules = True
        bet_multiplier = 2
    # ставки на конкретные числа
    if bet_type.isdigit() and 0 <= int(bet_type) <= 36:
        bet_number = int(bet_type)
        if number == bet_number:
            should_win_by_rules = True
            bet_multiplier = 36
    
    # Итог по правилам рулетки без случайных побед для проигрышных ставок
    won = should_win_by_rules
    multiplier = bet_multiplier if won else 0
    
    
    # проверяем, был ли тип ставки распознан
    recognized_types = [
    
    'чёрное', 'чер', 'черное', 'черн', 'чёрн', 'ч', 'чёр',
        'красное', 'кра', 'кр', 'красн', 'крас', 'к', 'красн',
        'зеро', 'з', 'ноль', 'нуль', '0', 'зер', 'зе',
        'чёт', 'чет', 'ч', 'четное', 'четн', 'чётное', 'чётн', 'чётн', 'четн',
        'нечёт', 'нечет', 'нч', 'нечетное', 'нечетн', 'нечётное', 'нечётн', 'нечётн', 'нечетн', 'неч',
        'ряд1', 'ряд 1', '1ряд', '1 ряд', 'р1', '1р',
        'ряд2', 'ряд 2', '2ряд', '2 ряд', 'р2', '2р',
        'ряд3', 'ряд 3', '3ряд', '3 ряд', 'р3', '3р',
        '1-12', 'первая дюжина', '1дюжина', '1 дюжина', '1д', 'д1',
        '13-24', 'вторая дюжина', '2дюжина', '2 дюжина', '2д', 'д2',
        '25-36', 'третья дюжина', '3дюжина', '3 дюжина', '3д', 'д3',
        '1-18', 'малые', 'малый', 'м', 'мал',
        '19-36', 'большие', 'большой', 'б', 'бол'
    ]
    
    # проверяем, был ли тип ставки распознан
    if bet_type not in recognized_types and not (bet_type.isdigit() and 0 <= int(bet_type) <= 36) and not re.match(r'^(\d{1,2})-(\d{1,2})$', bet_type):
        # если тип ставки не распознан, показываем ошибку
        await message.answer(f'неизвестный тип ставки "{bet_type}". используй: рул чёрное 1000 или рул 13-24 1к')
        try:
            roulette_in_progress.discard(user_id)
        except Exception:
            pass
        return
    
    # получаем имя пользователя
    # формируем безопасное упоминание (экранируем ник/username от HTML)
    raw_name = message.from_user.first_name or message.from_user.username or "игрок"
    
    user_name = html_escape(raw_name)
    user_mention = f"<a href='tg://user?id={message.from_user.id}'><b>{user_name}</b></a>"
    
    # обрабатываем результат
    if won:
        # Начисляем ПОЛНЫЙ выигрыш (ставка * множитель), т.к. ставка была списана раньше
        # Для текста и изображения отображаем чистую прибыль
        profit_amount = amount * (multiplier - 1)
        payout_amount = amount * multiplier
        
        # Начисляем выигрыш
        users[user_id]['balance'] += payout_amount
        
        # Проверяем, была ли это ставка "все"
        was_all_in = len(parts) >= 3 and parts[2] in ['вб', 'все', 'всё', 'алл', 'вабанк', 'вс', 'в', 'ваб', 'вабан', 'вседеньги', 'всёденьги']
        
        if was_all_in:
            result_text = f"{user_mention}, поздравляю! ты выиграл <b>${format_money(payout_amount)}</b> (x{multiplier}).\n\n"
            result_text += f"баланс — <b>${format_money(users[user_id]['balance'])}</b>."
        else:
            result_text = f"{user_mention}, поздравляю! ты выиграл <b>${format_money(profit_amount)}</b> (x{multiplier}).\n\n"
            result_text += f"баланс — <b>${format_money(users[user_id]['balance'])}</b>."
    else:
        # Ставка уже списана, показываем проигрыш
        result_text = f"{user_mention}, к сожалению ты проиграл <b>${format_money(amount)}</b>.\n\n"
        result_text += f"баланс — <b>${format_money(users[user_id]['balance'])}</b>."
    
    # Обновляем серию проигрышей: при выигрыше сбрасываем, при проигрыше увеличиваем
    try:
        if won:
            users[user_id]['roulette_loss_streak'] = 0
        else:
            users[user_id]['roulette_loss_streak'] = int(users[user_id].get('roulette_loss_streak', 0)) + 1
    except Exception:
        pass
    
    # сохраняем изменения
    save_users()
    
    # отправляем результат с фотографией рулетки
    try:
        # создаем изображение с результатом
        # Передаем в изображение сумму чистого выигрыша (или 0 при проигрыше)
        image_path = create_roulette_result_image(number, color, bet_type, amount, won, multiplier, profit_amount if won else 0)
        
        if image_path and os.path.exists(image_path):
            # добавляем небольшую задержку для предотвращения flood control
            await asyncio.sleep(0.5)
            # отправляем созданное изображение
            await bot.send_photo(
                message.chat.id,
                types.FSInputFile(image_path),
                caption=result_text,
                parse_mode='HTML'
            )
            
            # удаляем временный файл
            try:
                os.remove(image_path)
            except:
                pass
        else:
            # если не удалось создать изображение, отправляем только текст
            await message.answer(result_text, parse_mode='HTML')
    
    except Exception as e:
        # если не удалось отправить фото, отправляем только текст
        try:
            await message.answer(result_text, parse_mode='HTML')
        except Exception as e2:
            # если и с HTML не получилось, отправляем без HTML
            plain_text = result_text.replace('<b>', '').replace('</b>', '').replace('<a href="tg://user?id=', '').replace('</a>', '')
            await message.answer(plain_text)

    # Обновим стрик одинаковых ставок
    try:
        roulette_bet_streaks[user_id] = user_streak_next
    except Exception:
        pass
    finally:
        # Снимаем блокировку независимо от исхода
        try:
            roulette_in_progress.discard(user_id)
        except Exception:
            pass

# === общий обработчик сообщений с защитой от спама ===
@dp.message()
async def handle_all_messages(message: types.Message):
    """Общий обработчик всех сообщений с защитой от спама"""
    
    # Убираем блокировку обычных пользователей - они должны иметь доступ к боту
    
    # Проверяем на спам
    if message.text and is_spam_message(message.text):
        print(f"🚫 Спам заблокирован от пользователя {message.from_user.id}: {message.text[:50]}...")
        return  # Игнорируем спам
    
    # Если это не спам, обрабатываем как обычно
    # (остальные обработчики будут работать)

# === команда рулетки ===
@dp.message(Command('rul'))
async def roulette_command_handler(message: types.Message):
    """обработчик команды /rul"""
    
    # Убираем блокировку обычных пользователей - они должны иметь доступ к рулетке
    # просто вызываем основную функцию рулетки
    await roulette_handler(message)

# === конец рулетки ===
# === обработчик кнопки "создать человечка" ===
@dp.callback_query(lambda c: c.data == 'confirm_clear_db')
async def confirm_clear_db_callback(callback: types.CallbackQuery):
    """подтверждение очистки базы данных"""
    user_id = callback.from_user.id
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой команде', show_alert=True)
        return
    
    # очищаем базу данных
    global users
    users = {}
    
    save_users()
    
    await callback.answer('база данных очищена!', show_alert=True)
    
    await callback.message.edit_text(
        '🗑️ <b>база данных очищена!</b>\n\n'
        '✅ все пользователи удалены\n'
        '✅ все данные сброшены\n'
        '✅ база данных пуста\n\n'
        '📅 <b>дата очистки:</b> ' + datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S'),
        parse_mode='HTML'
    )

@dp.callback_query(lambda c: c.data == 'cancel_clear_db')
async def cancel_clear_db_callback(callback: types.CallbackQuery):
    """отмена очистки базы данных"""
    user_id = callback.from_user.id
    
    # проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await callback.answer('у тебя нет доступа к этой команде', show_alert=True)
        return
    
    await callback.answer('очистка отменена', show_alert=True)
    
    await callback.message.edit_text(
        '❌ <b>очистка отменена</b>\n\n'
        'база данных осталась без изменений',
        parse_mode='HTML'
    )

@dp.callback_query(lambda c: c.data == 'claim_bonus')
async def claim_bonus_callback(callback: types.CallbackQuery):
    """обработчик кнопки получения бонуса"""
    user_id = callback.from_user.id
    
    user_id_str = str(user_id)
    
    # Убираем блокировку обычных пользователей - они должны иметь доступ к бонусам
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    # проверяем подписку на канал
    is_subscribed = await check_channel_subscription(user_id)
    
    if not is_subscribed:
        # создаем клавиатуру с кнопкой для получения бонуса
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✅ забрать бонус', callback_data='claim_bonus')]
        ])
        
        await callback.message.edit_text(
            '<b>❌ для получения бонуса необходимо подписаться на наш канал — https://t.me/daisicx</b>',
            parse_mode='HTML',
            reply_markup=markup,
            disable_web_page_preview=True
        )
        await callback.answer()
        return
    
    user_data = users[user_id_str]
    
    nick = user_data.get('nick', 'игрок')
    
    # проверяем время последнего бонуса
    last_bonus_time = user_data.get('last_bonus_time', 0)
    
    current_time = datetime.datetime.now().timestamp()
    time_diff = current_time - last_bonus_time
    
    # 5 минут = 300 секунд
    if time_diff >= 300:
        # генерируем бонус от 1 до 10ккк
        min_bonus = 1_000_000_000  # 1ккк
        max_bonus = 10_000_000_000  # 10ккк
        bonus_amount = random.randint(min_bonus, max_bonus)
        
        # выдаем бонус
        user_data['balance'] += bonus_amount
        user_data['last_bonus_time'] = current_time
        save_users()
        
        await callback.answer(f"бонус получен! +${format_money(bonus_amount)}", show_alert=True)
        await callback.message.edit_text(
            f'<b>{nick}</b>, ты успешно забрал бонус! ты получил <b>${format_money(bonus_amount)}</b>',
            parse_mode='HTML'
        )
    else:
        # еще рано
        remaining_time = 300 - time_diff
        minutes = int(remaining_time // 60)
        seconds = int(remaining_time % 60)
        time_text = f'<b>{minutes}:{seconds:02d}</b>'
        
        await callback.answer(f"❌ осталось времени {time_text} до бонуса", show_alert=True)

@dp.callback_query(lambda c: c.data == 'create_human')
async def create_human_callback(callback: types.CallbackQuery):
    """обработчик кнопки создания человечка"""
    try:
        # отправляем команду /start в личку
        await callback.answer("переходим в личку для регистрации...")
        
        # создаем ссылку на бота
        bot_info = await bot.get_me()
        bot_username = bot_info.username
        
        # отправляем сообщение с ссылкой
        await callback.message.answer(
            f"нажми на ссылку ниже, чтобы перейти к боту и зарегистрироваться:\n\n"
            f"https://t.me/{bot_username}?start=ref{callback.from_user.id}"
        )
        
    except Exception as e:
        print(f"ошибка в create_human_callback: {e}")
        await callback.answer("произошла ошибка")

# === банковские callback обработчики ===
@dp.callback_query(lambda c: c.data == 'bank_deposit')
async def bank_deposit_callback(callback: types.CallbackQuery):
    """обработчик кнопки положить деньги в банк"""
    user_id = callback.from_user.id
    
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    user_data = users[user_id_str]
    
    balance = user_data.get('balance', 0)
    current_deposit = user_data.get('bank_deposit', 0)
    
    if current_deposit > 0:
        await callback.answer("у тебя уже есть активный вклад! сначала забери деньги", show_alert=True)
        return
    
    if balance <= 0:
        await callback.answer("у тебя нет денег для вклада", show_alert=True)
        return
    
    # создаем inline кнопки для выбора суммы
    markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='💰 10% от баланса', callback_data='deposit_10')],
        [InlineKeyboardButton(text='💰 25% от баланса', callback_data='deposit_25')],
    
    [InlineKeyboardButton(text='💰 50% от баланса', callback_data='deposit_50')],
        [InlineKeyboardButton(text='💰 75% от баланса', callback_data='deposit_75')],
    
    [InlineKeyboardButton(text='💰 все деньги', callback_data='deposit_all')],
        [InlineKeyboardButton(text='❌ отмена', callback_data='bank_cancel')]
    
    ])
    
    await callback.message.edit_text(
        f'💰 <b>положить деньги в банк</b>\n\n'
        f'💳 <b>твой баланс:</b> <b>${format_money(balance)}</b>\n\n'
        f'выбери сумму для вклада:',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.callback_query(lambda c: c.data.startswith('deposit_'))
async def deposit_amount_callback(callback: types.CallbackQuery):
    """обработчик выбора суммы вклада"""
    user_id = callback.from_user.id
    
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    user_data = users[user_id_str]
    
    balance = user_data.get('balance', 0)
    current_deposit = user_data.get('bank_deposit', 0)
    
    # проверяем, есть ли уже активный вклад
    if current_deposit > 0:
        await callback.answer("у тебя уже есть активный вклад! сначала забери деньги", show_alert=True)
        return
    
    # определяем процент
    percent = callback.data.split('_')[1]
    
    if percent == 'all':
        deposit_amount = balance
    else:
        percent_int = int(percent)
        deposit_amount = int(balance * percent_int / 100)
    
    if deposit_amount <= 0:
        await callback.answer("сумма должна быть больше нуля", show_alert=True)
        return
    
    if deposit_amount > balance:
        await callback.answer("у тебя недостаточно денег", show_alert=True)
        return

    # Ограничиваем максимальный вклад
    if deposit_amount > BANK_MAX_DEPOSIT:
        deposit_amount = BANK_MAX_DEPOSIT
    
    # создаем вклад
    user_data['bank_deposit'] = deposit_amount
    user_data['bank_deposit_time'] = datetime.datetime.now().timestamp()
    user_data['balance'] -= deposit_amount
    save_users()
    
    # обновляем баланс после списания
    new_balance = user_data['balance']
    
    await callback.answer(f"вклад создан! ${format_money(deposit_amount)}", show_alert=True)
    
    # создаем кнопки для возврата в банк
    markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='💰 положить деньги', callback_data='bank_deposit')],
        [InlineKeyboardButton(text='💸 забрать деньги', callback_data='bank_withdraw')],
    
    [InlineKeyboardButton(text='📊 информация о вкладе', callback_data='bank_info')]
    ])
    
    await callback.message.edit_text(
        f'✅ <b>вклад создан!</b>\n\n'
        f'💰 <b>сумма вклада:</b> <b>${format_money(deposit_amount)}</b>\n'
        f'💳 <b>новый баланс:</b> <b>${format_money(new_balance)}</b>\n'
        f'⏰ <b>время создания:</b> <b>{datetime.datetime.now().strftime("%H:%M")}</b>\n\n'
        f'💡 проценты начисляются 24 часа (10%)\n'
        f'💎 <b>за 24 часа получишь:</b> <b>${format_money(int(deposit_amount * 0.10))}</b> (максимум 10%)\n\n'
        f'⚠️ <b>внимание:</b> снять деньги можно только через 24 часа!\n'
        f'🔒 <b>макс. вклад:</b> <b>${format_money(BANK_MAX_DEPOSIT)}</b>',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.callback_query(lambda c: c.data == 'bank_withdraw')
async def bank_withdraw_callback(callback: types.CallbackQuery):
    """обработчик кнопки забрать деньги из банка"""
    user_id = callback.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    user_data = users[user_id_str]
    deposit = user_data.get('bank_deposit', 0)
    deposit_time = user_data.get('bank_deposit_time', 0)
    
    if deposit <= 0:
        await callback.answer("у тебя нет активного вклада", show_alert=True)
        return
    
    # рассчитываем проценты и проверяем время
    current_time = datetime.datetime.now().timestamp()
    time_passed = current_time - deposit_time
    can_withdraw = time_passed >= 86400  # 24 часа в секундах
    
    if can_withdraw:
        # можно снять - начисляем проценты
        hours_passed = time_passed / 3600
        hours_passed = min(hours_passed, 24)  # максимум 24 часа
        total_interest = int(deposit * 0.004167 * hours_passed)  # 10% за 24 часа
        total_withdraw = deposit + total_interest
        
        # забираем деньги с процентами
        user_data['balance'] += total_withdraw
        user_data['bank_deposit'] = 0
        user_data['bank_deposit_time'] = 0
        save_users()
        
        # обновляем баланс после начисления
        new_balance = user_data['balance']
        
        await callback.answer(f"деньги забраны! +${format_money(total_withdraw)}", show_alert=True)
        
        # создаем кнопки для возврата в банк
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='💰 положить деньги', callback_data='bank_deposit')],
            [InlineKeyboardButton(text='💸 забрать деньги', callback_data='bank_withdraw')],
            [InlineKeyboardButton(text='📊 информация о вкладе', callback_data='bank_info')]
        ])
        
        hours_passed_int = int(hours_passed)
        minutes_passed_int = int((hours_passed - hours_passed_int) * 60)
        
        await callback.message.edit_text(
            f'💸 <b>деньги забраны!</b>\n\n'
            f'💰 <b>сумма вклада:</b> <b>${format_money(deposit)}</b>\n'
            f'⏰ <b>время вклада:</b> <b>{hours_passed_int}ч {minutes_passed_int}м</b>\n'
            f'💎 <b>накопленные проценты:</b> <b>${format_money(total_interest)}</b>\n'
            f'💳 <b>всего получено:</b> <b>${format_money(total_withdraw)}</b>\n'
            f'💳 <b>новый баланс:</b> <b>${format_money(new_balance)}</b>\n\n'
            f'✅ деньги с процентами добавлены на твой баланс!',
            parse_mode='HTML',
            reply_markup=markup
        )
    else:
        # досрочное снятие - показываем предупреждение
        penalty = int(deposit * 0.05)  # 5% штраф
        total_withdraw = deposit - penalty
        remaining_time = 86400 - time_passed
        remaining_hours = int(remaining_time // 3600)
        remaining_minutes = int((remaining_time % 3600) // 60)
        
        # создаем кнопки для подтверждения досрочного снятия
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='✅ да, забрать со штрафом', callback_data='withdraw_early_confirm')],
            [InlineKeyboardButton(text='❌ отмена', callback_data='bank_cancel')]
        ])
        
        await callback.message.edit_text(
            f'⚠️ <b>внимание! досрочное снятие вклада</b>\n\n'
            f'💰 <b>сумма вклада:</b> <b>${format_money(deposit)}</b>\n'
            f'⏳ <b>до снятия без штрафа осталось:</b> <b>{remaining_hours}ч {remaining_minutes}м</b>\n\n'
            f'💸 <b>при досрочном снятии:</b>\n'
            f'• штраф <b>5%</b> = <b>${format_money(penalty)}</b>\n'
            f'• проценты <b>не начисляются</b>\n'
            f'• получишь <b>${format_money(total_withdraw)}</b>\n\n'
            f'❓ <b>точно хочешь забрать вклад досрочно?</b>',
            parse_mode='HTML',
            reply_markup=markup
        )
        await callback.answer()

@dp.callback_query(lambda c: c.data == 'bank_info')
async def bank_info_callback(callback: types.CallbackQuery):
    """обработчик кнопки информация о вкладе"""
    user_id = callback.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    user_data = users[user_id_str]
    balance = user_data.get('balance', 0)
    deposit = user_data.get('bank_deposit', 0)
    deposit_time = user_data.get('bank_deposit_time', 0)
    
    # рассчитываем проценты
    current_time = datetime.datetime.now().timestamp()
    hours_passed = 0
    total_interest = 0
    can_withdraw = False
    
    if deposit > 0 and deposit_time > 0:
        hours_passed = (current_time - deposit_time) / 3600  # часы
        # максимум 24 часа для 10%
        hours_passed = min(hours_passed, 24)
        # 10% за 24 часа = 0.4167% за час
        total_interest = int(deposit * 0.004167 * hours_passed)
        # можно снять только через 24 часа
        can_withdraw = (current_time - deposit_time) >= 86400  # 24 часа в секундах
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💰 положить деньги', callback_data='bank_deposit')],
        [InlineKeyboardButton(text='💸 забрать деньги', callback_data='bank_withdraw')],
        [InlineKeyboardButton(text='📊 информация о вкладе', callback_data='bank_info')]
    ])
    
    bank_text = f'📊 <b>подробная информация о вкладе</b>\n\n'
    bank_text += f'💳 <b>твой баланс:</b> <b>${format_money(balance)}</b>\n'
    
    if deposit > 0:
        # рассчитываем дополнительную информацию
        hours_passed_int = int(hours_passed)
        minutes_passed_int = int((hours_passed - hours_passed_int) * 60)
        percent_earned = (total_interest / deposit) * 100 if deposit > 0 else 0
        hours_to_max = max(0, 24 - hours_passed)
        potential_interest = int(deposit * 0.004167 * hours_to_max)
        
        bank_text += f'💰 <b>сумма вклада:</b> <b>${format_money(deposit)}</b>\n'
        bank_text += f'⏰ <b>время вклада:</b> <b>{hours_passed_int}ч {minutes_passed_int}м</b>\n'
        bank_text += f'💎 <b>накопленные проценты:</b> <b>${format_money(total_interest)}</b>\n'
        bank_text += f'📈 <b>процент дохода:</b> <b>{percent_earned:.2f}%</b>\n'
        
        if can_withdraw:
            bank_text += f'✅ <b>можно забрать деньги</b>\n\n'
        else:
            remaining_time = 86400 - (current_time - deposit_time)
            remaining_hours = int(remaining_time // 3600)
            remaining_minutes = int((remaining_time % 3600) // 60)
            bank_text += f'⏳ <b>до снятия:</b> <b>{remaining_hours}ч {remaining_minutes}м</b>\n\n'
    else:
        bank_text += f'💰 <b>вклад:</b> <b>нет активного вклада</b>\n\n'
    
    bank_text += '💡 <b>как работает система:</b>\n'
    bank_text += '• проценты начисляются 24 часа (10%)\n'
    bank_text += '• снять деньги можно только через сутки\n'
    bank_text += '• при досрочном снятии - штраф 5% без процентов\n'
    bank_text += '• проценты начисляются каждый час\n\n'
    bank_text += '📊 <b>примеры доходности:</b>\n'
    bank_text += '• вклад 1ккк → за 24 часа: 100кк (10%)\n'
    bank_text += '• вклад 10ккк → за 24 часа: 1ккк (10%)\n'
    bank_text += '• вклад 100ккк → за 24 часа: 10ккк (10%)'
    
    await callback.message.edit_text(bank_text, parse_mode='HTML', reply_markup=markup)

@dp.callback_query(lambda c: c.data == 'bank_cancel')
async def bank_cancel_callback(callback: types.CallbackQuery):
    """обработчик кнопки отмены в банке"""
    user_id = callback.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    # возвращаемся к основному меню банка
    user_data = users[user_id_str]
    balance = user_data.get('balance', 0)
    deposit = user_data.get('bank_deposit', 0)
    deposit_time = user_data.get('bank_deposit_time', 0)
    
    # рассчитываем проценты
    current_time = datetime.datetime.now().timestamp()
    hours_passed = 0
    total_interest = 0
    can_withdraw = False
    
    if deposit > 0 and deposit_time > 0:
        hours_passed = (current_time - deposit_time) / 3600  # часы
        # максимум 24 часа для 10%
        hours_passed = min(hours_passed, 24)
        # 10% за 24 часа = 0.4167% за час
        total_interest = int(deposit * 0.004167 * hours_passed)
        # можно снять только через 24 часа
        can_withdraw = (current_time - deposit_time) >= 86400  # 24 часа в секундах
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='💰 положить деньги', callback_data='bank_deposit')],
        [InlineKeyboardButton(text='💸 забрать деньги', callback_data='bank_withdraw')],
        [InlineKeyboardButton(text='📊 информация о вкладе', callback_data='bank_info')]
    ])
    
    bank_text = f'🏦 <b>банк</b>\n\n'
    bank_text += f'💳 <b>твой баланс:</b> <b>${format_money(balance)}</b>\n'
    
    if deposit > 0:
        hours_passed_int = int(hours_passed)
        minutes_passed_int = int((hours_passed - hours_passed_int) * 60)
        bank_text += f'💰 <b>вклад:</b> <b>${format_money(deposit)}</b>\n'
        bank_text += f'⏰ <b>время вклада:</b> <b>{hours_passed_int}ч {minutes_passed_int}м</b>\n'
        bank_text += f'💎 <b>накопленные проценты:</b> <b>${format_money(total_interest)}</b>\n'
        
        if can_withdraw:
            bank_text += f'✅ <b>можно забрать деньги</b>\n\n'
        else:
            remaining_time = 86400 - (current_time - deposit_time)
            remaining_hours = int(remaining_time // 3600)
            remaining_minutes = int((remaining_time % 3600) // 60)
            bank_text += f'⏳ <b>до снятия:</b> <b>{remaining_hours}ч {remaining_minutes}м</b>\n\n'
    else:
        bank_text += f'💰 <b>вклад:</b> <b>нет активного вклада</b>\n\n'
    
    bank_text += '💡 <b>как работает:</b>\n'
    bank_text += '• положи деньги во вклад\n'
    bank_text += '• проценты начисляются 24 часа (10%)\n'
    bank_text += '• снять деньги можно только через сутки\n'
    bank_text += '• при досрочном снятии - штраф без процентов\n\n'
    bank_text += '⚠️ <b>важно:</b> вклад заблокирован на 24 часа!'
    
    await callback.message.edit_text(bank_text, parse_mode='HTML', reply_markup=markup)
    await callback.answer()

@dp.callback_query(lambda c: c.data == 'withdraw_early_confirm')
async def withdraw_early_confirm_callback(callback: types.CallbackQuery):
    """обработчик подтверждения досрочного снятия вклада"""
    user_id = callback.from_user.id
    
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    user_data = users[user_id_str]
    
    deposit = user_data.get('bank_deposit', 0)
    deposit_time = user_data.get('bank_deposit_time', 0)
    
    if deposit <= 0:
        await callback.answer("у тебя нет активного вклада", show_alert=True)
        return
    
    # рассчитываем штраф
    penalty = int(deposit * 0.05)  # 5% штраф
    
    total_withdraw = deposit - penalty
    
    # забираем деньги со штрафом
    user_data['balance'] += total_withdraw
    user_data['bank_deposit'] = 0
    user_data['bank_deposit_time'] = 0
    save_users()
    
    # обновляем баланс после начисления
    new_balance = user_data['balance']
    
    await callback.answer(f"⚠️ досрочное снятие! штраф ${format_money(penalty)} (5%) за то что забрал вклад раньше 24 часов", show_alert=True)
    
    # создаем кнопки для возврата в банк
    markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='💰 положить деньги', callback_data='bank_deposit')],
        [InlineKeyboardButton(text='💸 забрать деньги', callback_data='bank_withdraw')],
    
    [InlineKeyboardButton(text='📊 информация о вкладе', callback_data='bank_info')]
    ])
    
    await callback.message.edit_text(
        f'⚠️ <b>досрочное снятие вклада!</b>\n\n'
        f'💰 <b>сумма вклада:</b> <b>${format_money(deposit)}</b>\n'
        f'💸 <b>штраф 5% за досрочное снятие:</b> <b>${format_money(penalty)}</b>\n'
        f'💳 <b>получено на баланс:</b> <b>${format_money(total_withdraw)}</b>\n'
        f'💳 <b>новый баланс:</b> <b>${format_money(new_balance)}</b>\n\n'
        f'❌ <b>проценты не начислены!</b> вклад должен лежать 24 часа для получения 10%',
        parse_mode='HTML',
    
    reply_markup=markup
    )

@dp.callback_query(lambda c: c.data == 'bank_stats')
async def bank_stats_callback(callback: types.CallbackQuery):
    """обработчик кнопки статистика вкладов"""
    user_id = callback.from_user.id
    
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    # собираем статистику вкладов
    total_deposits = 0
    
    users_with_deposits = 0
    max_deposit = 0
    
    deposits_list = []
    
    for user_id_key, user_data in users.items():
        deposit = user_data.get('bank_deposit', 0)
        if deposit > 0:
            total_deposits += deposit
            users_with_deposits += 1
            deposits_list.append(deposit)
            if deposit > max_deposit:
                max_deposit = deposit
    
    total_users = len(users)
    percentage_with_deposits = (users_with_deposits / total_users * 100) if total_users > 0 else 0
    
    average_deposit = (total_deposits / users_with_deposits) if users_with_deposits > 0 else 0
    
    # создаем кнопки для возврата
    markup = InlineKeyboardMarkup(inline_keyboard=[
    
    [InlineKeyboardButton(text='🏆 топ вкладов', callback_data='bank_top')],
        [InlineKeyboardButton(text='⬅️ назад', callback_data='bank_cancel')]
    
    ])
    
    stats_text = f'💳 <b>статистика вкладов:</b>\n\n'
    
    stats_text += f'💰 <b>общая сумма вкладов:</b> <b>${format_money(total_deposits)}</b>\n'
    stats_text += f'👥 <b>пользователей с вкладами:</b> <b>{users_with_deposits}/{total_users}</b>\n'
    stats_text += f'📊 <b>процент с вкладами:</b> <b>{percentage_with_deposits:.1f}%</b>\n'
    stats_text += f'💎 <b>максимальный вклад:</b> <b>${format_money(max_deposit)}</b>\n'
    stats_text += f'📈 <b>средний вклад:</b> <b>${format_money(int(average_deposit))}</b>\n\n'
    stats_text += f'💡 <b>подсказка:</b> используй "топ вкладов 🏆" для просмотра лучших игроков'
    
    await callback.message.edit_text(stats_text, parse_mode='HTML', reply_markup=markup)
    
    await callback.answer()
@dp.callback_query(lambda c: c.data == 'bank_top')
async def bank_top_callback(callback: types.CallbackQuery):
    """обработчик кнопки топ вкладов"""
    user_id = callback.from_user.id
    user_id_str = str(user_id)
    
    if user_id_str not in users:
        await callback.answer("сначала зарегистрируйся", show_alert=True)
        return
    
    # собираем данные о вкладах
    deposits_data = []
    total_deposits = 0
    users_with_deposits = 0
    
    for user_id_key, user_data in users.items():
        deposit = user_data.get('bank_deposit', 0)
        if deposit > 0:
            deposits_data.append({
                'user_id': user_id_key,
                'nick': user_data.get('nick', 'игрок'),
                'tg_username': user_data.get('tg_username', ''),
                'deposit': deposit
            })
            total_deposits += deposit
            users_with_deposits += 1
    
    # сортируем по размеру вклада (убывание)
    deposits_data.sort(key=lambda x: x['deposit'], reverse=True)
    
    # создаем кнопки для возврата
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📈 статистика вкладов', callback_data='bank_stats')],
        [InlineKeyboardButton(text='⬅️ назад', callback_data='bank_cancel')]
    ])
    
    top_text = f'🏆 <b>топ-10 по вкладам:</b>\n\n'
    medals = ['🥇', '🥈', '🥉']
    
    for i, data in enumerate(deposits_data[:10]):
        if i < 3:
            rank = medals[i]
        else:
            rank = f'{i+1}.'
        
        username = data['tg_username']
        if username:
            username = f'@{username}'
        else:
            username = data['nick']
        
        top_text += f'{rank} <b>{username}</b>\n'
        top_text += f'   💰 <b>${format_money(data["deposit"])}</b>\n\n'
    
    top_text += f'📊 <b>общая сумма вкладов:</b> <b>${format_money(total_deposits)}</b>\n'
    top_text += f'👥 <b>всего с вкладами:</b> <b>{users_with_deposits}</b>'
    
    await callback.message.edit_text(top_text, parse_mode='HTML', reply_markup=markup)
    await callback.answer()

# === конец банковских callback обработчиков ===

# === функции налога на богатство ===
async def send_tax_notification(user_id: int, text: str):
    """Отправляет уведомление о налоге пользователю"""
    try:
        await bot.send_message(
            chat_id=user_id,
    
    text=text,
            parse_mode='HTML'
    
    )
    except Exception as e:
        print(f"❌ Ошибка отправки уведомления о налоге пользователю {user_id}: {e}")

async def collect_wealth_tax():
    """Списывает налог на богатство (настраиваемый процент) у топ-15 игроков каждый час"""
    try:
        print("💰 Начинаем сбор налога на богатство...")
        
        # Получаем топ-15 игроков
        top_players = get_top_players()[:15]
        
        if not top_players:
            print("⚠️ Нет игроков для сбора налога")
            return
        
        total_tax_collected = 0
        
        for rank, (user_id, user_data) in enumerate(top_players, 1):
            current_balance = user_data.get('balance', 0)
            
            if current_balance <= 0:
                continue
            
            # Вычисляем налог (используем настраиваемый процент)
            tax_amount = int(current_balance * WEALTH_TAX_PERCENT / 100)
            
            if tax_amount <= 0:
                continue
            
            # Списываем налог
            users[user_id]['balance'] -= tax_amount
            total_tax_collected += tax_amount
            
            # Отправляем уведомление пользователю
            try:
                nick = user_data.get('nick', 'игрок')
                new_balance = users[user_id]['balance']
                
                notification_text = (
                    f"💰 <b>налог на богатство</b>\n\n"
                    f"👤 <b>{nick}</b>, с твоего баланса был снят налог на богатство в размере <b>${format_money(tax_amount)}</b>\n"
                    f"💳 <b>текущий баланс — ${format_money(new_balance)}</b>\n\n"
                    f"📊 <i>ты топ #{rank} игрок</i>"
                )
                
                await send_tax_notification(int(user_id), notification_text)
                
                print(f"✅ Налог собран с {nick} (ID: {user_id}): ${format_money(tax_amount)}")
                
            except Exception as e:
                print(f"❌ Ошибка отправки уведомления пользователю {user_id}: {e}")
        
        # Сохраняем изменения в базе данных
        save_users()
        
        print(f"💰 Налог на богатство собран! Всего: ${format_money(total_tax_collected)}")
        
        # Отправляем отчет администраторам
        now = datetime.datetime.now()
        admin_report = (
            f"📊 <b>Отчет о сборе налога на богатство</b>\n\n"
            f"💰 <b>Общая сумма налога:</b> ${format_money(total_tax_collected)}\n"
            f"👥 <b>Количество игроков:</b> {len(top_players)}\n"
            f"📊 <b>Процент налога:</b> {WEALTH_TAX_PERCENT}%\n"
            f"⏰ <b>Время сбора:</b> {now.strftime('%d.%m.%Y %H:%M')}"
        )
        
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=admin_report,
                    parse_mode='HTML'
                )
            except Exception as e:
                print(f"❌ Ошибка отправки отчета админу {admin_id}: {e}")
                
    except Exception as e:
        print(f"❌ Ошибка при сборе налога на богатство: {e}")

async def start_wealth_tax_scheduler():
    """Запускает планировщик сбора налога на богатство каждый час с настраиваемым процентом у топ-15 игроков"""
    print("⏰ Запускаем планировщик налога на богатство...")
    
    # Флаг для предотвращения повторного запуска
    if hasattr(start_wealth_tax_scheduler, '_running'):
        print("⚠️ Планировщик налога уже запущен!")
        return
    
    start_wealth_tax_scheduler._running = True
    
    try:
        # Получаем текущее время
        now = datetime.datetime.now()
        
        # Вычисляем время до следующего часа (простое решение)
        next_hour = now.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
        delay_seconds = (next_hour - now).total_seconds()
        
        print(f"⏰ Первый сбор налога в {next_hour.strftime('%H:%M')} (через {int(delay_seconds/60)} минут)")
        
        # Ждем до следующего часа
        await asyncio.sleep(delay_seconds)
        
        while True:
            try:
                # Собираем налог
                await collect_wealth_tax()
                
                # Ждем час до следующего сбора
                await asyncio.sleep(3600)  # 1 час
                
            except Exception as e:
                print(f"❌ Ошибка в планировщике налога: {e}")
                await asyncio.sleep(300)  # ждем 5 минут при ошибке
    finally:
        # Снимаем флаг при завершении
        start_wealth_tax_scheduler._running = False

# === простой пинг для Render ===
async def ping_render():
    """Простой пинг для предотвращения засыпания на Render"""
    try:
        print("Ping sent to keep Render alive")
    except Exception as e:
        print(f"Ping error: {e}")

# Запускаем пинг каждые 10 минут
async def start_ping():
    while True:
        await asyncio.sleep(600)  # 10 минут
        await ping_render()

# === защита от спама ===
def is_spam_message(text: str) -> bool:
    """Проверяет, является ли сообщение спамом"""
    spam_keywords = [
    
    'jetacas', 'casino', 'bonus', 'promo code', 'welcome1k',
        '🟢', '💰', '🔑', '📥', '🔒', '⚡️', '🎮', '🕐', '💵', '✅', '💳', '🔗'
    ]
    
    text_lower = text.lower()
    
    for keyword in spam_keywords:
        if keyword.lower() in text_lower:
            return True
    return False





def cleanup_temp_files():
    """очищает временные файлы рулетки"""
    try:
        for filename in os.listdir('.'):
            if filename.startswith('temp_roulette_') and filename.endswith('.png'):
                try:
                    os.remove(filename)
                except:
                    pass
    except:
        pass

if __name__ == '__main__':
    try:
        # очищаем временные файлы при запуске
        cleanup_temp_files()
        asyncio.run(main())
    except KeyboardInterrupt:
        # очищаем временные файлы при завершении
        cleanup_temp_files()
        pass
    finally:
        # очищаем временные файлы в любом случае
        cleanup_temp_files()
