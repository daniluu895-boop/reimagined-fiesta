from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import async_session_maker
from database.models import Order, User
from config import ADMIN_ID
from utils.logger import logger
from bot.keyboards.keyboards import (
    admin_orders_kb, admin_order_detail_kb, admin_menu_kb, 
    ORDER_STATUSES, admin_support_kb, support_menu_kb, faq_kb
)
from bot.states import SupportState 
admin_router = Router()


# ============================================================
# АДМИНКА: УПРАВЛЕНИЕ ЗАКАЗАМИ
# ============================================================

# Добавим кнопку "📦 Заказы" в админ-меню
# Для этого обновим admin_menu_kb в keyboards.py (см. ниже)


@admin_router.message(F.text == "📦 Заказы")
async def admin_orders_menu(message: types.Message):
    """Меню заказов для админа"""
    if message.from_user.id != ADMIN_ID:
        return
    
    async with async_session_maker() as session:
        orders = await session.scalars(
            select(Order)
            .order_by(Order.created_at.desc())
            .options(selectinload(Order.user))
        )
        orders_list = orders.all()
    
    if not orders_list:
        await message.answer("📭 Заказов пока нет.")
        return
    
    # Считаем новые
    new_count = sum(1 for o in orders_list if o.status == "new")
    
    text = f"📦 <b>Управление заказами</b>\n\n🟢 Новых: {new_count}\n📋 Всего: {len(orders_list)}"
    
    await message.answer(text, parse_mode="HTML", reply_markup=admin_orders_kb(orders_list))


@admin_router.callback_query(F.data == "admin_orders")
async def admin_orders_list(callback: types.CallbackQuery):
    """Список заказов (из callback)"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа")
        return
    
    async with async_session_maker() as session:
        orders = await session.scalars(
            select(Order)
            .order_by(Order.created_at.desc())
            .options(selectinload(Order.user))
        )
        orders_list = orders.all()
    
    if not orders_list:
        await callback.answer("Заказов нет")
        return
    
    new_count = sum(1 for o in orders_list if o.status == "new")
    text = f"📦 <b>Управление заказами</b>\n\n🟢 Новых: {new_count}\n📋 Всего: {len(orders_list)}"
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_orders_kb(orders_list))
    except TelegramBadRequest:
        pass
    
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_orders_page_"))
async def admin_orders_page(callback: types.CallbackQuery):
    """Пагинация заказов"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа")
        return
    
    page = int(callback.data.split("_")[3])
    
    async with async_session_maker() as session:
        orders = await session.scalars(
            select(Order)
            .order_by(Order.created_at.desc())
            .options(selectinload(Order.user))
        )
        orders_list = orders.all()
    
    new_count = sum(1 for o in orders_list if o.status == "new")
    text = f"📦 <b>Управление заказами</b>\n\n🟢 Новых: {new_count}\n📋 Всего: {len(orders_list)}"
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_orders_kb(orders_list, page))
    except TelegramBadRequest:
        pass
    
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_orders_filter_"))
async def admin_orders_filter(callback: types.CallbackQuery):
    """Фильтрация заказов по статусу"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа")
        return
    
    filter_status = callback.data.split("_")[3]
    
    async with async_session_maker() as session:
        if filter_status == "all":
            orders = await session.scalars(
                select(Order)
                .order_by(Order.created_at.desc())
                .options(selectinload(Order.user))
            )
        else:
            orders = await session.scalars(
                select(Order)
                .where(Order.status == filter_status)
                .order_by(Order.created_at.desc())
                .options(selectinload(Order.user))
            )
        orders_list = orders.all()
    
    status_text = "все" if filter_status == "all" else "новые"
    text = f"📦 <b>Заказы ({status_text})</b>\n\nНайдено: {len(orders_list)}"
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_orders_kb(orders_list))
    except TelegramBadRequest:
        pass
    
    await callback.answer()


@admin_router.callback_query(
    F.data.startswith("admin_order_") & 
    ~F.data.contains("page") & 
    ~F.data.contains("filter") & 
    ~F.data.contains("next") & 
    ~F.data.contains("status")
)
async def admin_order_detail(callback: types.CallbackQuery):
    """Детали заказа"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа")
        return
    
    order_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        order = await session.scalar(
            select(Order)
            .where(Order.id == order_id)
            .options(
                selectinload(Order.items),
                selectinload(Order.user)
            )
        )
        
        if not order:
            await callback.answer("Заказ не найден")
            return
        
        # Формируем текст
        status_name, _ = ORDER_STATUSES.get(order.status, ("❓ Неизвестно", None))
        
        text = (
            f"📦 <b>Заказ #{order.order_number}</b>\n\n"
            f"📊 <b>Статус:</b> {status_name}\n"
            f"👤 <b>Клиент:</b> {order.customer_name or 'Не указан'} (@{order.user.username or 'нет'})\n"
            f"📞 <b>Телефон:</b> {order.customer_phone or 'Не указан'}\n"
            f"📍 <b>Адрес:</b> {order.shipping_address or 'Не указан'}\n"
            f"📅 <b>Дата:</b> {order.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"<b>Товары:</b>\n"
        )
        
        subtotal = 0
        for item in order.items:
            item_total = item.price_at_purchase * item.quantity
            subtotal += item_total
            text += f"• {item.product_name} ({item.size}) x{item.quantity} = {item_total}₽\n"
        
        discount = subtotal - order.total_amount
        if discount < 0:
            discount = 0
        
        text += f"\n💰 Сумма: {subtotal}₽"
        if discount > 0:
            text += f"\n📉 Скидка: -{discount}₽"
        text += f"\n💳 <b>Итого:</b> {order.total_amount}₽"
    
    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=admin_order_detail_kb(order_id, order.status)
        )
    except TelegramBadRequest:
        pass
    
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_order_next_"))
async def admin_order_next_status(callback: types.CallbackQuery):
    """Перевести заказ в следующий статус"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа")
        return
    
    parts = callback.data.split("_")
    order_id = int(parts[3])
    new_status = parts[4]
    
    await change_order_status(order_id, new_status, callback)


@admin_router.callback_query(F.data.startswith("admin_order_status_"))
async def admin_order_set_status(callback: types.CallbackQuery):
    """Установить конкретный статус заказу"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа")
        return
    
    parts = callback.data.split("_")
    order_id = int(parts[3])
    new_status = parts[4]
    
    await change_order_status(order_id, new_status, callback)


async def change_order_status(order_id: int, new_status: str, callback: types.CallbackQuery):
    """Общая логика смены статуса + уведомление клиента"""
    async with async_session_maker() as session:
        order = await session.scalar(
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.user), selectinload(Order.items))
        )
        
        if not order:
            await callback.answer("Заказ не найден")
            return
        
        old_status = order.status
        order.status = new_status
        await session.commit()
        
        status_name, _ = ORDER_STATUSES.get(new_status, (new_status, None))
        
        # Уведомляем клиента
        try:
            notification_text = (
                f"📦 <b>Статус заказа обновлён!</b>\n\n"
                f"📝 Заказ: <code>{order.order_number}</code>\n"
                f"📊 Новый статус: <b>{status_name}</b>"
            )
            
            # Добавляем детали для определённых статусов
            if new_status == "shipped":
                notification_text += f"\n\n🚚 Ваш заказ отправлен по адресу:\n{order.shipping_address}"
            elif new_status == "completed":
                notification_text += "\n\n🎉 Спасибо за покупку! Ждём вас снова!"
            elif new_status == "cancelled":
                notification_text += "\n\n😔 Заказ отменён. Свяжитесь с нами, если есть вопросы."
            
            await callback.bot.send_message(
                order.user.telegram_id,
                notification_text,
                parse_mode="HTML"
            )
            client_notified = True
        except Exception as e:
            logger.error(f"Не удалось уведомить клиента: {e}")
            client_notified = False
        
        # Ответ админу
        notify_text = "✅ Клиент уведомлён" if client_notified else "⚠️ Не удалось уведомить клиента"
        await callback.answer(f"Статус: {status_name}. {notify_text}", show_alert=True)
        
        # Обновляем сообщение
        status_name_old, _ = ORDER_STATUSES.get(old_status, (old_status, None))
        
        text = callback.message.text
        text = text.replace(
            f"📊 Статус: {status_name_old}",
            f"📊 Статус: {status_name}"
        )
        
        try:
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=admin_order_detail_kb(order_id, new_status)
            )
        except TelegramBadRequest:
            # Если текст не изменился, обновляем только клавиатуру
            pass


@admin_router.callback_query(F.data == "admin_back_menu")
async def admin_back_menu(callback: types.CallbackQuery):
    """Возврат в админ-меню"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа")
        return
    
    try:
        await callback.message.edit_text(
            "👔 <b>Админ-панель</b>",
            parse_mode="HTML",
            reply_markup=None
        )
    except TelegramBadRequest:
        pass
    
    await callback.message.answer("Выберите действие:", reply_markup=admin_menu_kb())
    await callback.answer()


@admin_router.callback_query(F.data == "admin_orders_info")
async def admin_orders_info(callback: types.CallbackQuery):
    """Заглушка для кнопки с номером страницы"""
    await callback.answer()

# ============================================================
# ТЕХПОДДЕРЖКА
# ============================================================

# Константы FAQ
FAQ_TEXTS = {
    "delivery": (
        "🚚 <b>Доставка</b>\n\n"
        "📍 <b>Способы доставки:</b>\n"
        "• Курьером до двери — от 300₽\n"
        "• Самовывоз из пункта выдачи — от 150₽\n"
        "• Почта России — от 200₽\n\n"
        "⏰ <b>Сроки:</b>\n"
        "• Москва и СПб — 1-2 дня\n"
        "• Регионы — 3-7 дней\n\n"
        "📦 Заказы отправляем в день оплаты (до 17:00)"
    ),
    "payment": (
        "💳 <b>Оплата</b>\n\n"
        "Доступные способы оплаты:\n\n"
        "• 💳 Банковская карта (Visa, MasterCard, МИР)\n"
        "• 📱 СБП (Система быстрых платежей)\n"
        "• 💰 Наличными курьеру при получении\n\n"
        "🔒 Все платежи защищены и безопасны."
    ),
    "return": (
        "🔄 <b>Возврат и обмен</b>\n\n"
        "✅ <b>Условия возврата:</b>\n"
        "• 14 дней на возврат\n"
        "• Товар должен быть в оригинальной упаковке\n"
        "• Сохранены все бирки и ярлыки\n\n"
        "📋 <b>Как оформить возврат:</b>\n"
        "1. Напишите в поддержку\n"
        "2. Укажите номер заказа\n"
        "3. Опишите причину возврата\n\n"
        "💰 Возврат средств в течение 5-7 дней"
    ),
    "sizes": (
        "📏 <b>Размерная сетка</b>\n\n"
        "<pre>"
        "Размер  | Обхват груди | Обхват талии\n"
        "─────────────────────────────────\n"
        "   XS    |    84-88     |    64-68\n"
        "   S     |    88-92     |    68-72\n"
        "   M     |    92-96     |    76-80\n"
        "   L     |    96-100    |    84-88\n"
        "   XL    |   100-104    |    92-96\n"
        "</pre>\n\n"
        "💡 Если сомневаетесь с размером — напишите нам, поможем!"
    ),
    "contacts": (
        "📞 <b>Контакты</b>\n\n"
        "📱 Telegram: @your_support_bot\n"
        "📧 Email: support@yoursite.com\n"
        "⏰ Режим работы: Пн-Вс, 10:00-22:00\n\n"
        "💬 Быстрее всего отвечаем здесь в боте!"
    )
}


@admin_router.message(F.text == "🆘 Поддержка")
async def show_support_menu(message: types.Message):
    """Вход в меню поддержки из главного меню"""
    text = (
        "🆘 <b>Служба поддержки</b>\n\n"
        "Выберите действие или напишите нам:\n\n"
        "⏰ Среднее время ответа: 15 минут"
    )
    
    await message.answer(text, parse_mode="HTML", reply_markup=support_menu_kb())


# Оставьте callback-версию для навигации внутри поддержки:
@admin_router.callback_query(F.data == "support_back")
async def support_back(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в меню поддержки"""
    await state.clear()
    
    text = (
        "🆘 <b>Служба поддержки</b>\n\n"
        "Выберите действие или напишите нам:\n\n"
        "⏰ Среднее время ответа: 15 минут"
    )
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=support_menu_kb())
    except TelegramBadRequest:
        pass
    
    await callback.answer()


# --- Новое обращение ---
@admin_router.callback_query(F.data == "support_new")
async def support_new(callback: types.CallbackQuery, state: FSMContext):
    """Начало нового обращения"""
    await state.clear()
    await state.set_state(SupportState.user_message)
    
    text = (
        "✍️ <b>Напишите ваш вопрос</b>\n\n"
        "Опишите проблему как можно подробнее.\n"
        "Вы можете прикрепить фото или файл.\n\n"
        "Для отмены нажмите кнопку ниже."
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="support_cancel")
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    except TelegramBadRequest:
        pass
    
    await callback.answer()


@admin_router.message(SupportState.user_message)
async def support_send_message(message: types.Message, state: FSMContext):
    """Отправка сообщения в поддержку"""
    # Проверка на бан
    async with async_session_maker() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        if user and user.is_banned:
            await message.answer("⛔ Вы заблокированы и не можете писать в поддержку.")
            await state.clear()
            return
    
    # Формируем сообщение для админа
    admin_text = (
        f"📩 <b>Новое обращение в поддержку</b>\n\n"
        f"👤 <b>От:</b> {message.from_user.full_name}\n"
        f"🆔 <b>ID:</b> <code>{message.from_user.id}</code>\n"
        f"📧 <b>Username:</b> @{message.from_user.username or 'не указан'}\n\n"
        f"<b>Сообщение:</b>"
    )
    
    # Отправляем админу с клавиатурой для ответа
    try:
        if message.photo:
            # Если есть фото
            admin_msg = await message.bot.send_photo(
                ADMIN_ID,
                photo=message.photo[-1].file_id,
                caption=admin_text + f"\n\n{message.caption or ''}",
                parse_mode="HTML",
                reply_markup=admin_support_kb(message.from_user.id, message.message_id)
            )
        elif message.document:
            # Если есть документ
            admin_msg = await message.bot.send_document(
                ADMIN_ID,
                document=message.document.file_id,
                caption=admin_text + f"\n\n{message.caption or ''}",
                parse_mode="HTML",
                reply_markup=admin_support_kb(message.from_user.id, message.message_id)
            )
        else:
            # Текстовое сообщение
            admin_msg = await message.bot.send_message(
                ADMIN_ID,
                admin_text + f"\n\n{message.text}",
                parse_mode="HTML",
                reply_markup=admin_support_kb(message.from_user.id, message.message_id)
            )
        
        # Сохраняем ID сообщения админа для контекста
        await state.update_data(
            support_user_id=message.from_user.id,
            last_admin_msg_id=admin_msg.message_id
        )
        
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения админу: {e}")
        await message.answer("❌ Не удалось отправить сообщение. Попробуйте позже.")
        await state.clear()
        return
    
    await state.clear()
    
    # Подтверждение пользователю
    await message.answer(
        "✅ <b>Сообщение отправлено!</b>\n\n"
        "Мы ответим в ближайшее время.\n"
        "Обычно отвечаем в течение 15 минут.",
        parse_mode="HTML"
    )


# --- Отмена ---
@admin_router.callback_query(F.data == "support_cancel")
async def support_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Отмена написания сообщения"""
    await state.clear()
    
    text = (
        "🆘 <b>Служба поддержки</b>\n\n"
        "Выберите действие или напишите нам:\n\n"
        "⏰ Среднее время ответа: 15 минут"
    )
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=support_menu_kb())
    except TelegramBadRequest:
        pass
    
    await callback.answer("Отменено")


# --- Назад в поддержку ---
@admin_router.callback_query(F.data == "support_back")
async def support_back(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в меню поддержки"""
    await state.clear()
    
    text = (
        "🆘 <b>Служба поддержки</b>\n\n"
        "Выберите действие или напишите нам:\n\n"
        "⏰ Среднее время ответа: 15 минут"
    )
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=support_menu_kb())
    except TelegramBadRequest:
        pass
    
    await callback.answer()


# --- FAQ ---
@admin_router.callback_query(F.data == "support_faq")
async def support_faq(callback: types.CallbackQuery):
    """Меню FAQ"""
    text = "❓ <b>Частые вопросы</b>\n\nВыберите тему:"
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=faq_kb())
    except TelegramBadRequest:
        pass
    
    await callback.answer()


@admin_router.callback_query(F.data.startswith("faq_"))
async def faq_show(callback: types.CallbackQuery):
    """Показ ответа FAQ"""
    faq_key = callback.data.split("_")[1]
    
    text = FAQ_TEXTS.get(faq_key, "❓ Информация не найдена")
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 К списку вопросов", callback_data="support_faq")
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    except TelegramBadRequest:
        pass
    
    await callback.answer()


# ============================================================
# АДМИН: ОТВЕТЫ НА СООБЩЕНИЯ ПОДДЕРЖКИ
# ============================================================

@admin_router.callback_query(F.data.startswith("admin_reply_"))
async def admin_reply_start(callback: types.CallbackQuery, state: FSMContext):
    """Админ начинает отвечать пользователю"""
    parts = callback.data.split("_")
    user_id = int(parts[2])
    message_id = int(parts[3])
    
    # Сохраняем в состояние
    await state.update_data(
        reply_to_user_id=user_id,
        reply_to_msg_id=message_id
    )
    await state.set_state(SupportState.admin_reply)
    
    # Запрашиваем ответ
    await callback.message.answer(
        f"✍️ <b>Введите ответ для пользователя</b>\n\n"
        f"ID: <code>{user_id}</code>\n\n"
        f"Для отмены напишите /cancel",
        parse_mode="HTML"
    )
    await callback.answer()


@admin_router.message(SupportState.admin_reply)
async def admin_reply_send(message: types.Message, state: FSMContext):
    """Отправка ответа админа пользователю"""
    data = await state.get_data()
    user_id = data.get("reply_to_user_id")
    
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Ответ отменён")
        return
    
    if not user_id:
        await state.clear()
        await message.answer("❌ Ошибка: пользователь не найден")
        return
    
    # Формируем сообщение для пользователя
    user_text = (
        f"💬 <b>Ответ поддержки</b>\n\n"
        f"{message.text}\n\n"
        f"───────────────\n"
        f"Если у вас остались вопросы, напишите нам снова."
    )
    
    try:
        await message.bot.send_message(user_id, user_text, parse_mode="HTML")
        
        # Успех
        await message.answer(
            f"✅ <b>Ответ отправлен!</b>\n\n"
            f"Получатель: <code>{user_id}</code>",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Не удалось отправить ответ пользователю {user_id}: {e}")
        await message.answer(
            f"❌ <b>Не удалось отправить ответ</b>\n\n"
            f"Возможно, пользователь заблокировал бота.\n"
            f"Ошибка: {e}",
            parse_mode="HTML"
        )
    
    await state.clear()


@admin_router.callback_query(F.data.startswith("admin_ban_"))
async def admin_ban_user(callback: types.CallbackQuery):
    """Блокировка пользователя админом"""
    user_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        user = await session.scalar(
            select(User).where(User.telegram_id == user_id)
        )
        
        if not user:
            await callback.answer("Пользователь не найден")
            return
        
        user.is_banned = True
        await session.commit()
    
    await callback.answer(f"⛔ Пользователь {user_id} заблокирован", show_alert=True)


# --- Добавим кнопку "Поддержка" в профиль ---

# Найдите функцию show_profile и добавьте кнопку в клавиатуру:
# builder.button(text="🆘 Поддержка", callback_data="profile_support")