import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
import aiosqlite

BOT_TOKEN = '8801854700:AAHNq53borL_AZBO19a60Gc6bgs4x_bCWJw'
admin_id = 8746165041

logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

DB_PATH = 'data.db'

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE,
                api_id INTEGER,
                api_hash TEXT,
                session_string TEXT,
                active INTEGER DEFAULT 1
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS contests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_channels TEXT,
                post_url TEXT,
                accounts_used INTEGER,
                status TEXT DEFAULT 'created'
            )
        ''')
        await db.commit()

async def add_account(phone: str, api_id: int, api_hash: str, session_string: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT OR REPLACE INTO accounts (phone, api_id, api_hash, session_string, active) VALUES (?, ?, ?, ?, 1)',
            (phone, api_id, api_hash, session_string)
        )
        await db.commit()

async def get_active_accounts():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT id, phone, session_string FROM accounts WHERE active=1')
        rows = await cursor.fetchall()
        return [{'id': r[0], 'phone': r[1], 'session': r[2]} for r in rows]

async def get_account(account_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT phone, api_id, api_hash, session_string FROM accounts WHERE id=?', (account_id,))
        row = await cursor.fetchone()
        if row:
            return {'phone': row[0], 'api_id': row[1], 'api_hash': row[2], 'session': row[3]}
        return None

async def create_contest(channels, post_url, count):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'INSERT INTO contests (target_channels, post_url, accounts_used, status) VALUES (?, ?, ?, ?)',
            (','.join(channels), post_url, count, 'created')
        )
        await db.commit()
        return cursor.lastrowid

async def update_contest_status(contest_id, status):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE contests SET status=? WHERE id=?', (status, contest_id))
        await db.commit()

class AddAccount(StatesGroup):
    waiting_phone = State()
    waiting_api_id = State()
    waiting_api_hash = State()
    waiting_code = State()
    waiting_password = State()

class NewContest(StatesGroup):
    waiting_post = State()
    waiting_channels = State()
    waiting_count = State()

def make_keyboard(buttons, row_width=2):
    rows = []
    for i in range(0, len(buttons), row_width):
        rows.append(buttons[i:i+row_width])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.message(Command('start'))
async def start_cmd(message: types.Message):
    buttons = [
        InlineKeyboardButton(text='➕ Добавить аккаунт', callback_data='add_account'),
        InlineKeyboardButton(text='📋 Мои аккаунты', callback_data='list_accounts'),
        InlineKeyboardButton(text='🏆 Новый конкурс', callback_data='new_contest'),
        InlineKeyboardButton(text='📊 Статус конкурсов', callback_data='list_contests')
    ]
    keyboard = make_keyboard(buttons, row_width=2)
    await message.answer('Добро пожаловать! Выберите действие:', reply_markup=keyboard)

@dp.callback_query(lambda c: c.data == 'add_account')
async def add_account_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer('Введите номер телефона в формате +7XXXXXXXXXX')
    await state.set_state(AddAccount.waiting_phone)
    await callback.answer()

@dp.callback_query(lambda c: c.data == 'list_accounts')
async def list_accounts(callback: types.CallbackQuery):
    accounts = await get_active_accounts()
    if not accounts:
        await callback.message.answer('Нет активных аккаунтов.')
    else:
        text = 'Ваши аккаунты:\n' + '\n'.join([f'{a["id"]}: {a["phone"]}' for a in accounts])
        await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(lambda c: c.data == 'new_contest')
async def new_contest_callback(callback: types.CallbackQuery, state: FSMContext):
    accounts = await get_active_accounts()
    if not accounts:
        await callback.message.answer('Сначала добавьте хотя бы один аккаунт.')
        await callback.answer()
        return
    await callback.message.answer(
        '📌 Инструкция:\n'
        '1. Зажмите кнопку "Участвовать" в конкурсе и скопируйте ссылку.\n'
        '2. Отправьте эту ссылку мне.\n'
        '3. Затем отправьте список каналов (юзернеймы через запятую), на которые нужно подписаться.\n'
        '4. После этого выберите, сколько аккаунтов задействовать.'
    )
    await callback.message.answer('Отправьте ссылку на пост (кнопку участия):')
    await state.set_state(NewContest.waiting_post)
    await callback.answer()

@dp.callback_query(lambda c: c.data == 'list_contests')
async def list_contests(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT id, target_channels, status FROM contests ORDER BY id DESC LIMIT 10')
        rows = await cursor.fetchall()
        if not rows:
            await callback.message.answer('Нет конкурсов.')
        else:
            text = 'Последние конкурсы:\n'
            for r in rows:
                text += f'#{r[0]}: каналы {r[1]} — статус {r[2]}\n'
            await callback.message.answer(text)
    await callback.answer()

@dp.message(AddAccount.waiting_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if not re.match(r'^\+?\d{10,15}$', phone):
        await message.answer('Неверный формат. Введите номер в формате +7XXXXXXXXXX')
        return
    await state.update_data(phone=phone)
    await message.answer('Введите API ID (целое число)')
    await state.set_state(AddAccount.waiting_api_id)

@dp.message(AddAccount.waiting_api_id)
async def process_api_id(message: types.Message, state: FSMContext):
    try:
        api_id = int(message.text.strip())
    except ValueError:
        await message.answer('API ID должно быть числом. Введите снова:')
        return
    await state.update_data(api_id=api_id)
    await message.answer('Введите API HASH (строка)')
    await state.set_state(AddAccount.waiting_api_hash)

@dp.message(AddAccount.waiting_api_hash)
async def process_api_hash(message: types.Message, state: FSMContext):
    api_hash = message.text.strip()
    if not api_hash:
        await message.answer('API HASH не может быть пустым. Введите снова:')
        return
    await state.update_data(api_hash=api_hash)
    data = await state.get_data()
    phone = data['phone']
    api_id = data['api_id']
    api_hash = data['api_hash']
    client = TelegramClient(f'session_{phone}', api_id, api_hash)
    await client.connect()
    try:
        await client.send_code_request(phone)
        await message.answer('Код подтверждения отправлен. Введите его:')
        await state.set_state(AddAccount.waiting_code)
        await state.update_data(client=client)
    except Exception as e:
        await message.answer(f'Ошибка при отправке кода: {str(e)}')
        await state.clear()

@dp.message(AddAccount.waiting_code)
async def process_code(message: types.Message, state: FSMContext):
    data = await state.get_data()
    client = data['client']
    phone = data['phone']
    api_id = data['api_id']
    api_hash = data['api_hash']
    code = message.text.strip()
    try:
        await client.sign_in(phone, code)
        session_string = client.session.save()
        await add_account(phone, api_id, api_hash, session_string)
        await message.answer(f'Аккаунт {phone} успешно добавлен!')
        await client.disconnect()
        await state.clear()
    except SessionPasswordNeededError:
        await message.answer('Введите пароль двухфакторной аутентификации:')
        await state.set_state(AddAccount.waiting_password)
        await state.update_data(need_password=True)
    except Exception as e:
        await message.answer(f'Ошибка: {str(e)}')
        await client.disconnect()
        await state.clear()

@dp.message(AddAccount.waiting_password)
async def process_password(message: types.Message, state: FSMContext):
    data = await state.get_data()
    client = data['client']
    phone = data['phone']
    api_id = data['api_id']
    api_hash = data['api_hash']
    password = message.text.strip()
    try:
        await client.sign_in(password=password)
        session_string = client.session.save()
        await add_account(phone, api_id, api_hash, session_string)
        await message.answer(f'Аккаунт {phone} успешно добавлен!')
        await client.disconnect()
    except Exception as e:
        await message.answer(f'Ошибка: {str(e)}')
        await client.disconnect()
    await state.clear()

@dp.message(NewContest.waiting_post)
async def process_post(message: types.Message, state: FSMContext):
    post_url = message.text.strip()
    if not post_url.startswith('https://t.me/'):
        await message.answer('Похоже, это не ссылка Telegram. Убедитесь, что вы копируете ссылку на пост (кнопку участия).')
        return
    await state.update_data(post_url=post_url)
    await message.answer('Теперь отправьте список каналов для подписки (юзернеймы через запятую, например @channel1, @channel2):')
    await state.set_state(NewContest.waiting_channels)

@dp.message(NewContest.waiting_channels)
async def process_channels(message: types.Message, state: FSMContext):
    channels = [ch.strip() for ch in message.text.split(',') if ch.strip()]
    if not channels:
        await message.answer('Введите хотя бы один канал.')
        return
    await state.update_data(channels=channels)
    accounts = await get_active_accounts()
    if not accounts:
        await message.answer('Нет активных аккаунтов. Добавьте их сначала.')
        await state.clear()
        return
    buttons = []
    for acc in accounts:
        buttons.append(InlineKeyboardButton(
            text=f'{acc["phone"]} (id {acc["id"]})',
            callback_data=f'select_acc_{acc["id"]}'
        ))
    buttons.append(InlineKeyboardButton(text='✅ Готово', callback_data='finish_contest'))
    keyboard = make_keyboard(buttons, row_width=3)
    await message.answer('Выберите аккаунты для участия (нажимайте для отметки/снятия). Когда закончите, нажмите "Готово".',
                         reply_markup=keyboard)
    await state.update_data(selected_accs=set())
    await state.set_state(NewContest.waiting_count)

@dp.callback_query(StateFilter(NewContest.waiting_count), lambda c: c.data.startswith('select_acc_'))
async def toggle_account(callback: types.CallbackQuery, state: FSMContext):
    acc_id = int(callback.data.split('_')[2])
    data = await state.get_data()
    selected = data.get('selected_accs', set())
    if acc_id in selected:
        selected.remove(acc_id)
    else:
        selected.add(acc_id)
    await state.update_data(selected_accs=selected)
    await callback.answer(f'Выбрано {len(selected)} аккаунтов.')

@dp.callback_query(StateFilter(NewContest.waiting_count), lambda c: c.data == 'finish_contest')
async def finish_contest(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get('selected_accs', set())
    if not selected:
        await callback.message.answer('Вы не выбрали ни одного аккаунта.')
        return
    channels = data['channels']
    post_url = data['post_url']
    contest_id = await create_contest(channels, post_url, len(selected))
    await update_contest_status(contest_id, 'running')
    await callback.message.answer(f'Конкурс #{contest_id} создан. Начинаем выполнение на {len(selected)} аккаунтах...')
    asyncio.create_task(run_contest_task(contest_id, list(selected), channels, post_url))
    await callback.answer()
    await state.clear()

async def run_contest_task(contest_id, account_ids, channels, post_url):
    for acc_id in account_ids:
        acc_data = await get_account(acc_id)
        if not acc_data:
            continue
        try:
            client = TelegramClient(acc_data['session'], acc_data['api_id'], acc_data['api_hash'])
            await client.connect()
            for ch in channels:
                try:
                    await client.join_channel(ch)
                except Exception as e:
                    logging.error(f'Ошибка подписки на {ch} для аккаунта {acc_id}: {e}')
            await client.send_message('me', f'Участие в конкурсе #{contest_id} выполнено для {acc_data["phone"]} по ссылке {post_url}')
            await client.disconnect()
        except Exception as e:
            logging.error(f'Ошибка для аккаунта {acc_id}: {e}')
    await update_contest_status(contest_id, 'completed')
    await bot.send_message(admin_id, f'Конкурс #{contest_id} завершён.')

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
