import random
import string
import asyncio
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select

from database.database import async_session_maker
# ДОБАВЬ Order СЮДА:
from database.models import User, PromoCode, Order 
from config import ADMIN_ID
from utils.logger import logger
# Эти импорты подтянут готовые состояния из твоего states.py
from bot.states import AdminReplyState, PromoState, BroadcastState 

admin_users_router = Router()

# --- Пользователи Список ---
@admin_users_router.message(F.text == "👥 Пользователи")
async def admin_users_list(message: types.Message):
    await show_users_page(message.answer, 0)

async def show_users_page(send_func, page: int):
    async with async_session_maker() as session:
        users = await session.scalars(select(User).order_by(User.id.desc()))
        users_list = users.all()
        
        per_page = 8
        total_pages = (len(users_list) + per_page - 1) // per_page
        start = page * per_page
        current_users = users_list[start:start + per_page]
        
        builder = InlineKeyboardBuilder()
        for u in current_users:
            status = "🚫" if u.is_banned else "✅"
            builder.button(text=f"{status} {u.first_name or 'User'}", callback_data=f"user_info_{u.telegram_id}")
        
        nav = []
        if page > 0: nav.append(types.InlineKeyboardButton(text="⬅️", callback_data=f"user_page_{page-1}"))
        nav.append(types.InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="none"))
        if page < total_pages - 1: nav.append(types.InlineKeyboardButton(text="➡️", callback_data=f"user_page_{page+1}"))
        
        builder.row(*nav)
        builder.row(types.InlineKeyboardButton(text="🔙 В меню", callback_data="admin_back_menu"))
        builder.adjust(2)
        
        try:
            await send_func("👥 Список пользователей:", reply_markup=builder.as_markup())
        except TelegramBadRequest:
            pass

@admin_users_router.callback_query(F.data.startswith("user_page_"))
async def paginate_users(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[2])
    await show_users_page(callback.message.edit_text, page)
    await callback.answer()

@admin_users_router.callback_query(F.data.startswith("user_info_"))
async def user_info_detail(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[2])
    async with async_session_maker() as session:
        # Получаем юзера
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        
        # Получаем 3 последних заказа этого юзера
        recent_orders = await session.scalars(
            select(Order)
            .where(Order.user_id == user.id) # user.id - это ID в таблице БД
            .order_by(Order.created_at.desc())
            .limit(3)
        )
        orders_list = recent_orders.all()
        
        # Формируем список заказов
        orders_text = "\n".join([f"• #{o.order_number} ({o.total_amount}₽)" for o in orders_list]) or "Нет заказов"

        text = (
            f"👤 <b>Пользователь:</b> {user.first_name}\n"
            f"🆔 ID: <code>{user.telegram_id}</code>\n"
            f"🏷 Username: @{user.username or 'не указан'}\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"📦 Заказов: {user.orders_count}\n"
            f"💰 Потрачено: {user.total_spent}₽\n"
            f"📅 Дата рег: {user.created_at.strftime('%d.%m.%Y')}\n\n"
            f"📦 <b>Последние заказы:</b>\n{orders_text}"
        )
        
        builder = InlineKeyboardBuilder()
        builder.button(text="✉️ Написать в ЛС", callback_data=f"send_msg_{user_id}")
        builder.button(text="📦 Все заказы юзера", callback_data=f"user_orders_list_{user_id}")
        builder.button(text="🚫 Бан/Разабан", callback_data=f"ban_user_{user_id}")
        builder.button(text="🔙 К списку", callback_data="user_page_0")
        builder.button(text="🎁 Подарить промокод", callback_data=f"gen_promo_{user_id}")
        builder.adjust(1)
        
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@admin_users_router.callback_query(F.data.startswith("ban_user_"))
async def toggle_ban(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[2])
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        user.is_banned = not user.is_banned
        await session.commit()
    await callback.answer(f"Статус изменен на: {'Забанен' if user.is_banned else 'Активен'}")
    await user_info_detail(callback)

# --- Рассылка сообщения конкретному юзеру ---
@admin_users_router.callback_query(F.data.startswith("send_msg_"))
async def start_send_msg(callback: types.CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminReplyState.text)
    await callback.message.answer("Введите текст сообщения для пользователя:")

@admin_users_router.message(AdminReplyState.text)
async def process_send_msg(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_id = data['target_user_id']
    try:
        await message.bot.send_message(target_id, f"Сообщение от администрации:\n\n{message.text}")
        await message.answer("✅ Сообщение отправлено!")
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки: {e}")
    await state.clear()

@admin_users_router.callback_query(F.data.startswith("user_orders_list_"))
async def user_orders_list(callback: types.CallbackQuery):
    user_id = int(callback.data.split("_")[3])
    async with async_session_maker() as session:
        # Находим пользователя в БД по его telegram_id
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        
        # Получаем все заказы
        orders = await session.scalars(
            select(Order)
            .where(Order.user_id == user.id)
            .order_by(Order.created_at.desc())
        )
        orders_list = orders.all()

        if not orders_list:
            await callback.answer("У юзера нет заказов")
            return

        text = f"📦 <b>Заказы пользователя {user.first_name}:</b>\n\n"
        builder = InlineKeyboardBuilder()
        
        for o in orders_list:
            text += f"• #{o.order_number} | {o.total_amount}₽ | {o.status}\n"
            # Можно добавить кнопку перехода к конкретному заказу, если нужно
        
        builder.button(text="🔙 Назад к профилю", callback_data=f"user_info_{user_id}")
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

# --- МАССОВАЯ РАССЫЛКА ---

@admin_users_router.message(F.text == "📢 Рассылка")
async def broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BroadcastState.text)
    await message.answer("Введите текст сообщения для всех пользователей:")

@admin_users_router.message(BroadcastState.text)
async def broadcast_confirm(message: types.Message, state: FSMContext):
    await state.update_data(broadcast_text=message.text)
    await state.set_state(BroadcastState.confirm)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="bc_confirm")
    builder.button(text="❌ Отмена", callback_data="bc_cancel")
    
    await message.answer(f"Предпросмотр:\n\n{message.text}\n\nПодтверждаете?", reply_markup=builder.as_markup())

@admin_users_router.callback_query(F.data == "bc_cancel")
async def broadcast_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Рассылка отменена.")

@admin_users_router.callback_query(F.data == "bc_confirm")
async def broadcast_execute(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = data['broadcast_text']
    await state.clear()
    
    await callback.message.edit_text("⏳ Рассылка запущена...")
    
    async with async_session_maker() as session:
        users = await session.scalars(select(User))
        users_list = users.all()
        
    count = 0
    for u in users_list:
        try:
            await callback.bot.send_message(u.telegram_id, text, parse_mode="HTML")
            count += 1
            await asyncio.sleep(0.05) # Небольшая задержка, чтобы не словить спам-блок от Telegram
        except:
            continue
            
    await callback.message.answer(f"✅ Рассылка завершена! Получателей: {count}")

# --- ГЕНЕРАЦИЯ ПРОМОКОДА ДЛЯ ЮЗЕРА ---

# --- 1. Выбор типа ---
# --- 1. Выбор типа ---
@admin_users_router.callback_query(F.data.startswith("gen_promo_"))
async def gen_promo_type(callback: types.CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])
    await state.update_data(target_user=user_id)
    await state.set_state(PromoState.type)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📉 Скидка %", callback_data="p_type_percent")
    builder.button(text="💰 Скидка ₽", callback_data="p_type_rub")
    await callback.message.edit_text("Выберите тип скидки:", reply_markup=builder.as_markup())
    logger.info("Promo: Step 1 (Type selected)")

# --- 2. Ввод суммы/процентов ---
@admin_users_router.callback_query(PromoState.type, F.data.startswith("p_type_"))
async def gen_promo_value(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(p_type=callback.data.split("_")[2])
    await state.set_state(PromoState.value)
    await callback.message.edit_text("Введите число (чистое значение без букв):")
    logger.info("Promo: Step 2 (Value requested)")

# --- 3. Ввод описания ---
@admin_users_router.message(PromoState.value)
async def gen_promo_desc(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Ошибка! Введите только число.")
        return
    await state.update_data(p_value=int(message.text))
    await state.set_state(PromoState.description)
    await message.answer("Введите поясняющий текст для пользователя:")
    logger.info("Promo: Step 3 (Description requested)")

# --- 4. Финальное подтверждение ---
@admin_users_router.message(PromoState.description)
async def gen_promo_confirm(message: types.Message, state: FSMContext):
    await state.update_data(desc=message.text)
    data = await state.get_data()
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    await state.update_data(p_code=code)
    await state.set_state(PromoState.confirm)
    
    text = (f"✅ Готово к отправке:\nКод: <code>{code}</code>\n"
            f"Скидка: {data['p_value']}{'%' if data['p_type']=='percent' else '₽'}\n"
            f"Описание: {data['desc']}")
    
    builder = InlineKeyboardBuilder()
    builder.button(text="💾 Сохранить и отправить", callback_data="promo_save")
    await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    logger.info("Promo: Step 4 (Confirm button shown)")

# --- 5. Сохранение ---
@admin_users_router.callback_query(PromoState.confirm, F.data == "promo_save")
async def promo_save(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    async with async_session_maker() as session:
        # Убедись, что user найден
        user = await session.scalar(select(User).where(User.telegram_id == int(data['target_user'])))
        if not user:
            await callback.answer("Ошибка: юзер не найден в БД")
            return
        
        new_promo = PromoCode(
            code=data['p_code'],
            discount_amount=data['p_value'] if data['p_type'] == "rub" else 0,
            discount_percent=data['p_value'] if data['p_type'] == "percent" else 0,
            description=data['desc'],
            owner_id=user.id
        )
        session.add(new_promo)
        await session.commit()
    
    await callback.bot.send_message(data['target_user'], f"🎁 <b>Вам подарен промокод!</b>\n\n{data['desc']}\n\nКод: <code>{data['p_code']}</code>", parse_mode="HTML")
    await callback.message.edit_text("✅ Промокод сохранен и отправлен!")
    await state.clear()
    logger.info("Promo: Finished!")