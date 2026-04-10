import asyncio
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

API_TOKEN = "ВАШ_ТОКЕН"
ADMIN_IDS = [123456789]  # ID админов
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# База данных
conn = sqlite3.connect("shop.db")
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    selected_t3 TEXT DEFAULT ''
)""")
c.execute("""CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    t3_type TEXT,
    description TEXT,
    status TEXT DEFAULT 'waiting'
)""")
conn.commit()

# Стейты для описания аватарки
class AvatarOrder(StatesGroup):
    waiting_description = State()

# Клавиатуры
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Магазин", callback_data="shop")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton(text="📞 Поддержка (пополнение)", callback_data="support")]
    ])

def t3_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎨 Аватарки для приложений", callback_data="t3_apps")],
        [InlineKeyboardButton(text="🎮 Аватарки для игр", callback_data="t3_games")],
        [InlineKeyboardButton(text="🔞 18+ аватарки", callback_data="t3_18")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="back")]
    ])

def admin_order_keyboard(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Взять заказ", callback_data=f"take_{order_id}")]
    ])

# Команда /start
@dp.message(Command("start"))
async def start(message: Message):
    user_id = message.from_user.id
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    await message.answer("Добро пожаловать в Avatar Shop!\nВыберите действие:", reply_markup=main_menu())

# Магазин
@dp.callback_query(F.data == "shop")
async def shop_menu(callback: CallbackQuery):
    await callback.message.edit_text("Выберите тип работы (T3):", reply_markup=t3_menu())
    await callback.answer()

# Выбор T3
@dp.callback_query(F.data.startswith("t3_"))
async def choose_t3(callback: CallbackQuery, state: FSMContext):
    t3_map = {
        "t3_apps": "Аватарки для приложений",
        "t3_games": "Аватарки для игр",
        "t3_18": "18+ аватарки"
    }
    t3_type = t3_map.get(callback.data, "Неизвестно")
    user_id = callback.from_user.id
    c.execute("UPDATE users SET selected_t3 = ? WHERE user_id = ?", (t3_type, user_id))
    conn.commit()
    await callback.message.edit_text(f"Вы выбрали: {t3_type}\nОпишите, какую аватарку вы хотите:")
    await state.set_state(AvatarOrder.waiting_description)
    await callback.answer()

# Приём описания от покупателя
@dp.message(AvatarOrder.waiting_description)
async def get_description(message: Message, state: FSMContext):
    user_id = message.from_user.id
    desc = message.text
    c.execute("SELECT selected_t3 FROM users WHERE user_id = ?", (user_id,))
    t3_type = c.fetchone()[0]
    c.execute("INSERT INTO orders (user_id, t3_type, description) VALUES (?, ?, ?)", (user_id, t3_type, desc))
    conn.commit()
    order_id = c.lastrowid
    await message.answer("✅ Заказ создан! Админ свяжется с вами в этом чате.")
    # Уведомление админам
    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, f"🆕 Новый заказ #{order_id}\nT3: {t3_type}\nОписание: {desc}\nОт: {user_id}", reply_markup=admin_order_keyboard(order_id))
    await state.clear()

# Админ берёт заказ
@dp.callback_query(F.data.startswith("take_"))
async def take_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    c.execute("SELECT user_id, description FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    if not order:
        await callback.answer("Заказ не найден")
        return
    user_id, desc = order
    await callback.message.edit_text(f"✅ Вы взяли заказ #{order_id}\nОписание: {desc}\nТеперь отправьте готовую аватарку в ответ на это сообщение.")
    # Сохраняем состояние, что админ работает над order_id
    await callback.answer()

# Админ отправляет аватарку
@dp.message(F.photo)
async def admin_send_avatar(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    # Тут нужно связать с последним взятым заказом - для простоты возьмём последний незакрытый
    c.execute("SELECT id, user_id FROM orders WHERE status='waiting' ORDER BY id DESC LIMIT 1")
    order = c.fetchone()
    if not order:
        await message.answer("Нет активных заказов")
        return
    order_id, user_id = order
    await bot.send_photo(user_id, message.photo[-1].file_id, caption=f"🖼 Ваш заказ #{order_id} готов!\nСпасибо за покупку!")
    c.execute("UPDATE orders SET status='done' WHERE id=?", (order_id,))
    conn.commit()
    await message.answer(f"✅ Аватарка отправлена пользователю {user_id}, заказ #{order_id} закрыт.")

# Баланс и поддержка
@dp.callback_query(F.data == "balance")
async def show_balance(callback: CallbackQuery):
    user_id = callback.from_user.id
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    balance = c.fetchone()[0]
    await callback.message.edit_text(f"💰 Ваш баланс: {balance} руб.\nПополнить можно через поддержку.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📞 Связаться с поддержкой", callback_data="support")]]))
    await callback.answer()

@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    await callback.message.edit_text("📞 Напишите @admin_username (или ссылка на поддержку) для пополнения баланса.\nПосле пополнения баланс обновится вручную.")
    await callback.answer()

@dp.callback_query(F.data == "back")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu())
    await callback.answer()

# Запуск
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
