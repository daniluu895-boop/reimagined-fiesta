from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from database.database import async_session_maker
from database.models import User, Category, Product, ProductVariant, CartItem, Order, OrderItem
from config import ADMIN_ID
from utils.logger import logger
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime
import time


# Импортируем клавиатуры и состояния из соседних файлов
from bot.keyboards.keyboards import (
    main_menu_kb, admin_menu_kb, categories_kb, variants_kb, 
    product_actions_kb, cart_kb, admin_cancel_kb, admin_confirm_kb
)
from bot.states import AddProductState, OrderState, ProfileState

router = Router()

# --- 1. СТАРТ И РОЛИ ---
@router.message(CommandStart())
async def cmd_start(message: types.Message):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        
        if not user:
            # Если пользователя нет - создаем
            new_user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                language_code=message.from_user.language_code, # Сохраняем язык
                is_admin=(message.from_user.id == ADMIN_ID),
                interaction_count=1 # Первое посещение
            )
            session.add(new_user)
            await session.commit()
            logger.info(f"New user: {message.from_user.id}")
        else:
            # Если пользователь есть - обновляем данные и увеличиваем счетчик
            user.username = message.from_user.username
            user.first_name = message.from_user.first_name
            user.last_name = message.from_user.last_name
            user.language_code = message.from_user.language_code
            user.interaction_count += 1 # Увеличиваем счетчик заходов
            user.last_seen = datetime.utcnow() # Обновляем время последнего визита
            await session.commit()

    if message.from_user.id == ADMIN_ID:
        await message.answer("👋 Здравствуй, Админ!", reply_markup=admin_menu_kb())
    else:
        await message.answer("👋 Добро пожаловать в магазин!", reply_markup=main_menu_kb())

# --- 2. КАТАЛОГ ---
@router.message(F.text == "📦 Каталог")
async def show_catalog(message: types.Message):
    async with async_session_maker() as session:
        cats = await session.scalars(select(Category).where(Category.is_active == True))
        await message.answer("Выберите категорию:", reply_markup=categories_kb(cats.all()))

@router.callback_query(F.data.startswith("cat_"))
async def show_products(callback: types.CallbackQuery):
    cat_id = int(callback.data.split("_")[1])
    async with async_session_maker() as session:
        prods = await session.scalars(select(Product).where(Product.category_id == cat_id))
        builder = InlineKeyboardBuilder()
        for p in prods:
            builder.button(text=p.name, callback_data=f"prod_{p.id}")
        builder.button(text="🔙 Назад", callback_data="back_to_cats")
        builder.adjust(1)
        
        # Оборачиваем в try, чтобы не было ошибки "message is not modified"
        try:
            await callback.message.edit_text("Товары:", reply_markup=builder.as_markup())
        except TelegramBadRequest:
            pass # Если сообщение такое же - просто игнорируем

@router.callback_query(F.data == "back_to_cats")
async def back_to_cats(callback: types.CallbackQuery):
    async with async_session_maker() as session:
        cats = await session.scalars(select(Category))
        await callback.message.edit_text("Категории:", reply_markup=categories_kb(cats.all()))

@router.callback_query(F.data.startswith("prod_"))
async def show_product(callback: types.CallbackQuery):
    prod_id = int(callback.data.split("_")[1])
    async with async_session_maker() as session:
        product = await session.get(Product, prod_id)
        if not product:
            await callback.answer("Товар не найден")
            return
            
        text = f"<b>{product.name}</b>\n{product.description}"
        if product.main_photo_id:
            await callback.message.answer_photo(photo=product.main_photo_id, caption=text, parse_mode="HTML", reply_markup=product_actions_kb(prod_id))
            await callback.message.delete()
        else:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=product_actions_kb(prod_id))

# --- 3. КОРЗИНА ---
@router.callback_query(F.data.startswith("add_cart_"))
async def select_variant(callback: types.CallbackQuery):
    prod_id = int(callback.data.split("_")[2])
    async with async_session_maker() as session:
        variants = await session.scalars(select(ProductVariant).where(ProductVariant.product_id == prod_id))
        variants_list = variants.all()
        
        if not variants_list:
            await callback.answer("Нет доступных вариантов")
            return

        kb = variants_kb(variants_list, prod_id)
        
        # Проверяем, есть ли у сообщения фото
        if callback.message.photo:
            # Если фото есть, редактируем подпись (caption)
            await callback.message.edit_caption(caption="Выберите вариант:", reply_markup=kb)
        elif callback.message.text:
            # Если только текст, редактируем текст
            await callback.message.edit_text("Выберите вариант:", reply_markup=kb)
        else:
            # Если совсем ничего (на всякий случай), отправляем новое
            await callback.message.answer("Выберите вариант:", reply_markup=kb)
            
    await callback.answer()

@router.callback_query(F.data.startswith("var_"))
async def add_to_cart(callback: types.CallbackQuery):
    var_id = int(callback.data.split("_")[1])
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        variant = await session.get(ProductVariant, var_id)
        
        existing = await session.scalar(select(CartItem).where(CartItem.user_id == user.id, CartItem.variant_id == var_id))
        if existing:
            existing.quantity += 1
        else:
            session.add(CartItem(user_id=user.id, variant_id=var_id))
        await session.commit()
    await callback.answer("✅ Добавлено в корзину!")

@router.message(F.text == "🛒 Корзина")
async def view_cart(message: types.Message):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        
        # --- ИСПРАВЛЕННЫЙ ЗАПРОС ---
        # Мы говорим: выбери CartItem, И ПОДГРУЗИ (options) связанные variant и product
        items = await session.scalars(
            select(CartItem)
            .where(CartItem.user_id == user.id)
            .options(
                selectinload(CartItem.variant).selectinload(ProductVariant.product)
            )
        )
        # ---------------------------
        
        items_list = items.all()
        
        if not items_list:
            await message.answer("Корзина пуста")
            return

        # Подгружать данные здесь больше не нужно, они уже загружены!
        text = "<b>Корзина:</b>\n"
        total = 0
        for item in items_list:
            # Теперь доступ к item.variant.product не вызывает ошибку
            subtotal = item.variant.price * item.quantity
            total += subtotal
            text += f"- {item.variant.product.name} ({item.variant.size}) x{item.quantity} = {subtotal}₽\n"
        
        text += f"\n<b>Итого: {total}₽</b>"
        await message.answer(text, parse_mode="HTML", reply_markup=cart_kb(items_list))

# --- 4. АДМИНКА: ДОБАВЛЕНИЕ ТОВАРА ---
@router.message(F.text == "➕ Добавить товар")
async def admin_add_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(AddProductState.name)
    await message.answer("Введите название товара:", reply_markup=admin_cancel_kb())

@router.message(AddProductState.name)
async def admin_add_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddProductState.description)
    await message.answer("Описание:")

@router.message(AddProductState.description)
async def admin_add_desc(message: types.Message, state: FSMContext):
    await state.update_data(desc=message.text)
    await state.set_state(AddProductState.category)
    # Выведем список категорий для выбора
    async with async_session_maker() as session:
        cats = await session.scalars(select(Category))
        builder = InlineKeyboardBuilder()
        for c in cats:
            builder.button(text=c.name, callback_data=f"setcat_{c.id}")
    await message.answer("Выберите категорию:", reply_markup=builder.as_markup())

@router.callback_query(AddProductState.category, F.data.startswith("setcat_"))
async def admin_set_cat(callback: types.CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split("_")[1])
    await state.update_data(cat_id=cat_id)
    await state.set_state(AddProductState.photo)
    await callback.message.answer("Отправьте фото товара:")

@router.message(AddProductState.photo, F.photo)
async def admin_add_photo(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(photo=file_id)
    await state.set_state(AddProductState.variants)
    await state.update_data(variants_list=[]) # Инициализация списка вариантов
    await message.answer("Фото принято. Теперь введите варианты в формате:\n`Размер,Цвет,Цена,Остаток`\nНапример: `M,Черный,1500,10`", parse_mode="Markdown")

@router.message(AddProductState.variants)
async def admin_add_variant(message: types.Message, state: FSMContext):
    if message.text.lower() == "готово":
        data = await state.get_data()
        text = f"Создаем товар: {data['name']}?\nВариантов: {len(data['variants_list'])}"
        await state.set_state(AddProductState.confirm)
        await message.answer(text, reply_markup=admin_confirm_kb())
        return

    try:
        parts = message.text.split(',')
        if len(parts) != 4: raise ValueError
        size, color, price, qty = [p.strip() for p in parts]
        
        data = await state.get_data()
        variants = data.get("variants_list", [])
        variants.append({"size": size, "color": color, "price": int(price), "stock": int(qty)})
        await state.update_data(variants_list=variants)
        await message.answer("Вариант добавлен. Введите следующий или напишите 'Готово'.")
    except:
        await message.answer("Ошибка формата. Попробуйте: `M,Черный,1500,10`")

@router.callback_query(AddProductState.confirm, F.data == "admin_save_product")
async def admin_save(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    async with async_session_maker() as session:
        product = Product(
            name=data['name'],
            description=data['desc'],
            category_id=data['cat_id'],
            main_photo_id=data['photo']
        )
        session.add(product)
        await session.flush() # Чтобы получить ID продукта
        
        for var_data in data['variants_list']:
            variant = ProductVariant(
                product_id=product.id,
                size=var_data['size'],
                color=var_data['color'],
                price=var_data['price'],
                stock_quantity=var_data['stock']
            )
            session.add(variant)
        await session.commit()
    
    await state.clear()
    await callback.message.answer("✅ Товар сохранен!", reply_markup=admin_menu_kb())

# --- Отмена админа ---
@router.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Действие отменено.")

from aiogram.types import ReplyKeyboardRemove # Убедись, что это импортировано вверху файла

# --- 5. ОФОРМЛЕНИЕ ЗАКАЗА (CHECKOUT) ---

# Шаг 1: Начало
@router.callback_query(F.data == "checkout")
async def start_checkout(callback: types.CallbackQuery, state: FSMContext):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        items = await session.scalars(select(CartItem).where(CartItem.user_id == user.id))
        
        if not items.all():
            await callback.answer("Корзина пуста!")
            return

        # Сохраняем телефон в переменную, пока сессия открыта
        saved_phone = user.phone

    await state.set_state(OrderState.phone)
    
    # Строим клавиатуру
    builder = ReplyKeyboardBuilder()
    if saved_phone:
        builder.add(KeyboardButton(text=f"Использовать {saved_phone}"))
    builder.add(KeyboardButton(text="📲 Отправить другой номер", request_contact=True))
    builder.add(KeyboardButton(text="❌ Отмена"))
    builder.adjust(1)
    
    await callback.message.answer("Введите номер телефона:", reply_markup=builder.as_markup())
    await callback.answer()

# Шаг 2: Телефон
@router.message(OrderState.phone, F.contact | F.text)
async def process_phone(message: types.Message, state: FSMContext):
    phone = ""
    
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
        return

    if message.contact:
        phone = message.contact.phone_number
    elif message.text and message.text.startswith("Использовать"):
        # Если выбрали сохраненный, загружаем из базы
        async with async_session_maker() as session:
            u = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
            phone = u.phone
    else:
        phone = message.text

    await state.update_data(phone=phone)
    await state.set_state(OrderState.address)
    
    # Спрашиваем адрес
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        saved_address = user.shipping_address
        
        builder = ReplyKeyboardBuilder()
        if saved_address:
            # Обрезаем адрес для отображения на кнопке
            btn_text = f"Использовать {saved_address[:15]}..."
            builder.add(KeyboardButton(text=btn_text))
        builder.add(KeyboardButton(text="Ввести новый адрес"))
        builder.adjust(1)
        
        await message.answer("Отлично! Теперь адрес доставки:", reply_markup=builder.as_markup())

# Шаг 3: Адрес
@router.message(OrderState.address)
async def process_address(message: types.Message, state: FSMContext):
    address = ""
    # Если нажали "Использовать..."
    if message.text and message.text.startswith("Использовать"):
        async with async_session_maker() as session:
            u = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
            address = u.shipping_address
    # Если нажали "Ввести новый" - ждем следующее сообщение? 
    # Нет, кнопка "Ввести новый" просто позволяет напечатать текст.
    # Но если пользователь нажал кнопку "Ввести новый адрес", это текст, мы его не примем как адрес.
    elif message.text == "Ввести новый адрес":
        await message.answer("Хорошо, напишите адрес текстом:")
        # Не меняем состояние и не выходим, ждем следующее сообщение с адресом
        return 
    else:
        address = message.text

    # Сохраняем адрес в профиль, если его там не было
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if not user.shipping_address and address:
            user.shipping_address = address
            await session.commit()

    await state.update_data(address=address)
    
    # Переходим к подтверждению (Шаг 4)
    await show_confirmation(message, state)

# Шаг 4: Показ чека и подтверждение
async def show_confirmation(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    
    # Считаем итог
    total = 0
    text_list = []
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        items = await session.scalars(select(CartItem).where(CartItem.user_id == user.id))
        
        for item in items.all():
            var = await session.get(ProductVariant, item.variant_id)
            prod = await session.get(Product, var.product_id)
            subtotal = var.price * item.quantity
            total += subtotal
            text_list.append(f"• {prod.name} ({var.size}) x{item.quantity} = {subtotal}₽")

    text = (
        f"<b>Подтвердите заказ:</b>\n\n"
        f"📞 Телефон: {data['phone']}\n"
        f"🏠 Адрес: {data['address']}\n\n"
        f"Товары:\n" + "\n".join(text_list) + 
        f"\n\n💰 <b>Итого: {total}₽</b>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm_order_final")
    builder.button(text="❌ Отмена", callback_data="cancel_order_final")
    builder.adjust(2)
    
    # Убираем Reply клавиатуру и присылаем чек
    await message.answer(text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await message.answer("Все верно?", reply_markup=builder.as_markup())

# Шаг 5: Финал (Сохранение в БД)
@router.callback_query(F.data == "confirm_order_final")
async def finish_order(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        items = await session.scalars(select(CartItem).where(CartItem.user_id == user.id))
        items_list = items.all()
        
        if not items_list:
            await callback.message.edit_text("Корзина пуста.")
            return

        # 1. Считаем общую сумму
        total_amount = 0
        receipt_lines = []
        for item in items_list:
            var = await session.get(ProductVariant, item.variant_id)
            prod = await session.get(Product, var.product_id)
            subtotal = var.price * item.quantity
            total_amount += subtotal
            receipt_lines.append(f"• {prod.name} ({var.size}) x{item.quantity} = {subtotal}₽")

        # 2. Создаем заказ с ВРЕМЕННЫМ номером
        import time
        temp_number = f"TEMP-{int(time.time())}" 
        
        order = Order(
            order_number=temp_number,
            user_id=user.id,
            total_amount=total_amount,
            status="new",
            customer_phone=data['phone'],
            shipping_address=data['address'],
            customer_name=user.first_name
        )
        session.add(order)
        await session.flush() # Получаем ID
        
        # 3. Генерируем правильный номер
        year = datetime.now().year
        real_order_number = f"ORD-{year}-{order.id}"
        order.order_number = real_order_number

        # 4. Переносим товары
        for item in items_list:
            var = await session.get(ProductVariant, item.variant_id)
            prod = await session.get(Product, var.product_id)
            
            order_item = OrderItem(
                order_id=order.id,
                variant_id=var.id,
                product_name=prod.name,
                size=var.size,
                color=var.color,
                quantity=item.quantity,
                price_at_purchase=var.price,
                subtotal=var.price * item.quantity
            )
            session.add(order_item)
            await session.delete(item) # Удаляем из корзины

        # 5. Статистика
        user.orders_count += 1
        user.total_spent += total_amount

        await session.commit()

    # 6. Чек пользователю
    receipt_text = (
        f"🎉 <b>Заказ успешно оформлен!</b>\n\n"
        f"📝 <b>Номер заказа:</b> <code>{real_order_number}</code>\n"
        f"📞 <b>Телефон:</b> {data['phone']}\n"
        f"📍 <b>Адрес:</b> {data['address']}\n\n"
        f"<b>Ваш чек:</b>\n" + "\n".join(receipt_lines) + 
        f"\n\n💰 <b>Итого к оплате:</b> {total_amount}₽\n\n"
        f"Ожидайте звонка менеджера!"
    )
    
    try:
        # Пытаемся отредактировать сообщение "Все верно?"
        await callback.message.delete() # Удаляем "Все верно?"
        await callback.message.answer(receipt_text, parse_mode="HTML") # Шлем чек
        # Или редактируем предыдущее, но там кнопки. Проще удалить и послать новое.
    except:
        await callback.message.answer(receipt_text, parse_mode="HTML")

    # 7. Уведомление админа
    admin_text = (
        f"🛍 <b>Новый заказ!</b>\n"
        f"Номер: {real_order_number}\n"
        f"Клиент: {user.first_name} (@{user.username})\n"
        f"Сумма: {total_amount}₽"
    )
    try:
        await callback.bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Не удалось уведомить админа: {e}")

    await callback.answer()

# Отмена заказа
@router.callback_query(F.data == "cancel_order_final")
async def cancel_checkout(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    # Удаляем сообщение с кнопками подтверждения
    await callback.message.delete()
    await callback.message.answer("❌ Оформление отменено.")

# --- ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ---

@router.message(F.text == "👤 Профиль")
async def show_profile(message: types.Message):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        
        if not user:
            await message.answer("Ошибка: пользователь не найден.")
            return

        # Формируем текст профиля
        text = (
            f"👤 <b>Личный кабинет</b>\n\n"
            f"🆔 <b>ID:</b> <code>{user.telegram_id}</code>\n"
            f"👤 <b>Имя:</b> {user.first_name or 'Не указано'}\n"
            f"📞 <b>Телефон:</b> {user.phone or 'Не указан'}\n"
            f"📍 <b>Адрес:</b> {user.shipping_address or 'Не указан'}\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"📦 Заказов: {user.orders_count}\n"
            f"💰 Потрачено: {user.total_spent}₽"
        )

        # Клавиатура профиля (инлайн)
        builder = InlineKeyboardBuilder()
        builder.button(text="📦 Мои заказы", callback_data="profile_orders")
        builder.button(text="✏️ Изменить данные", callback_data="profile_edit_data")
        builder.adjust(1)

        await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

# --- ИСТОРИЯ ЗАКАЗОВ ---

@router.callback_query(F.data == "profile_orders")
async def profile_orders(callback: types.CallbackQuery):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        
        # Подгружаем заказы (нужен selectinload для items, если хотим сразу видеть детали, но пока список)
        orders = await session.scalars(
            select(Order)
            .where(Order.user_id == user.id)
            .order_by(Order.created_at.desc()) # Сначала новые
        )
        orders_list = orders.all()

        if not orders_list:
            await callback.answer("У вас пока нет заказов.", show_alert=True)
            return

        builder = InlineKeyboardBuilder()
        text = "<b>📦 Ваши заказы:</b>\n\n"
        
        for order in orders_list:
            # Определяем эмодзи статуса
            status_emoji = "🟢" if order.status == "new" else "🟡" if order.status == "processing" else "🔵"
            text += (
                f"{status_emoji} <b>Заказ #{order.order_number}</b>\n"
                f"   Сумма: {order.total_amount}₽ | Статус: {order.status}\n\n"
            )
            builder.button(text=f"Чек #{order.order_number}", callback_data=f"order_detail_{order.id}")
        
        builder.button(text="🔙 Назад", callback_data="back_to_profile")
        builder.adjust(1)
        
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

# --- ПРОСМОТР ЧЕКА ---

@router.callback_query(F.data.startswith("order_detail_"))
async def order_detail(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    async with async_session_maker() as session:
        # Подгружаем заказ И товары в нем (selectinload)
        order = await session.scalar(
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.items)) # Важно! Не забудь импортировать selectinload
        )
        
        if not order:
            await callback.answer("Заказ не найден")
            return

        text = f"🧾 <b>Чек по заказу #{order.order_number}</b>\n\n"
        total = 0
        for item in order.items:
            # item - это OrderItem, у него уже есть все данные
            subtotal = item.price_at_purchase * item.quantity
            total += subtotal
            text += f"• {item.product_name} ({item.size}) x{item.quantity} = {subtotal}₽\n"
        
        text += (
            f"\n💵 <b>Итого:</b> {total}₽\n"
            f"📍 Адрес: {order.shipping_address}\n"
            f"📞 Телефон: {order.customer_phone}\n"
            f"📅 Дата: {order.created_at.strftime('%d.%m.%Y %H:%M')}"
        )
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад к списку", callback_data="profile_orders")
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

# --- НАВИГАЦИЯ ---

@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: types.CallbackQuery):
    # Просто перезапускаем показ профиля (эмулируем команду, но меняем сообщение)
    # Чтобы не дублировать код, лучше вынести логику профиля в отдельную функцию, но для простоты:
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        text = (
            f"👤 <b>Личный кабинет</b>\n\n"
            f"🆔 <b>ID:</b> <code>{user.telegram_id}</code>\n"
            f"👤 <b>Имя:</b> {user.first_name or 'Не указано'}\n"
            f"📞 <b>Телефон:</b> {user.phone or 'Не указан'}\n"
            f"📍 <b>Адрес:</b> {user.shipping_address or 'Не указан'}\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"📦 Заказов: {user.orders_count}\n"
            f"💰 Потрачено: {user.total_spent}₽"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="📦 Мои заказы", callback_data="profile_orders")
        builder.button(text="✏️ Изменить данные", callback_data="profile_edit_data")
        builder.adjust(1)
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

# --- РЕДАКТИРОВАНИЕ ДАННЫХ ПРОФИЛЯ ---

# 1. Меню редактирования
@router.callback_query(F.data == "profile_edit_data")
async def profile_edit_start(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📞 Изменить телефон", callback_data="edit_phone_start")
    builder.button(text="📍 Изменить адрес", callback_data="edit_address_start")
    builder.button(text="🔙 Назад", callback_data="back_to_profile")
    builder.adjust(1)
    
    await callback.message.edit_text("Что вы хотите изменить?", reply_markup=builder.as_markup())
    await callback.answer()

# 2. Изменение телефона (Запуск)
@router.callback_query(F.data == "edit_phone_start")
async def edit_phone_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileState.phone)
    
    # Клавиатура с кнопкой "Отправить контакт"
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📲 Отправить свой номер", request_contact=True)],
        [KeyboardButton(text="❌ Отмена")]
    ], resize_keyboard=True)
    
    await callback.message.answer("Отправьте номер телефона или введите вручную:", reply_markup=kb)
    await callback.answer()

# 3. Ловим новый телефон
@router.message(ProfileState.phone, F.contact | F.text)
async def save_profile_phone(message: types.Message, state: FSMContext):
    phone = ""
    if message.contact:
        phone = message.contact.phone_number
    elif message.text != "❌ Отмена":
        phone = message.text
    else:
        await state.clear()
        await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())
        return

    # Сохраняем в БД
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        user.phone = phone
        await session.commit()
    
    await state.clear()
    await message.answer(f"✅ Телефон обновлен: {phone}", reply_markup=ReplyKeyboardRemove())

# 4. Изменение адреса (Запуск)
@router.callback_query(F.data == "edit_address_start")
async def edit_address_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileState.address)
    await callback.message.answer("Введите новый адрес доставки:")
    await callback.answer()

# 5. Ловим новый адрес
@router.message(ProfileState.address)
async def save_profile_address(message: types.Message, state: FSMContext):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        user.shipping_address = message.text # Убедись, что поле shipping_address есть в models.py!
        await session.commit()
    
    await state.clear()
    await message.answer(f"✅ Адрес обновлен: {message.text}")