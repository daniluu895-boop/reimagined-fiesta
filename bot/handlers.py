from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from database.database import async_session_maker
from database.models import User, Category, Product, ProductVariant, CartItem, Order, OrderItem, PromoCode
from config import ADMIN_ID, BOT_NAME
from utils.logger import logger
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime
import time
import random
import string


# Импортируем клавиатуры и состояния из соседних файлов
from bot.keyboards.keyboards import (
    main_menu_kb, admin_menu_kb, categories_kb, variants_kb, 
    product_actions_kb, cart_kb, admin_cancel_kb, admin_confirm_kb
)
from bot.states import AddProductState, OrderState, ProfileState

router = Router()

# --- 1. СТАРТ И РОЛИ ---
@router.message(CommandStart())
async def cmd_start(message: types.Message, command: Command):
    # 1. Пытаемся получить ID того, кто пригласил (если есть)
    referrer_id = None
    if command.args:
        try:
            referrer_id = int(command.args)
            # Защита: нельзя пригласить самого себя
            if referrer_id == message.from_user.id:
                referrer_id = None
        except ValueError:
            pass

    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        
        if not user:
            # --- СЦЕНАРИЙ: НОВЫЙ ПОЛЬЗОВАТЕЛЬ ---
            
            # 2. Создаем пользователя (и сразу сохраняем реферера, если он есть)
            new_user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                language_code=message.from_user.language_code,
                is_admin=(message.from_user.id == ADMIN_ID),
                interaction_count=1,
                referrer_id=referrer_id # Запоминаем, кто пригласил
            )
            session.add(new_user)
            await session.flush() # Получаем ID нового юзера

            # 3. Генерируем Welcome-промокод (-200₽) для НОВОГО юзера
            import random, string
            promo_str = "WELCOME-" + ''.join(random.choices(string.digits, k=6))
            welcome_promo = PromoCode(
                code=promo_str,
                discount_amount=200, 
                discount_percent=0,  
                description="🎁 Подарок за регистрацию (-200₽)",
                owner_id=new_user.id
            )
            session.add(welcome_promo)
            
            # 4. Обрабатываем логику РЕФЕРАЛЬНОЙ СИСТЕМЫ (если он пришел по ссылке)
            if referrer_id:
                referrer_user = await session.scalar(select(User).where(User.telegram_id == referrer_id))
                if referrer_user:
                    referrer_user.referral_count += 1
                    
                    # Проверка награды для приглашающего (каждые 3 друга)
                    if referrer_user.referral_count % 3 == 0:
                        # Генерируем промокод для ПРИГЛАСИВШЕГО
                        ref_promo_str = "GIFT-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                        new_ref_promo = PromoCode(
                            code=ref_promo_str,
                            discount_percent=15,
                            discount_amount=0,
                            owner_id=referrer_user.id
                        )
                        session.add(new_ref_promo)
                        
                        # Уведомляем приглашающего
                        try:
                            await message.bot.send_message(
                                referrer_id, 
                                f"🎉 Ура! Вы пригласили 3 друзей!\n"
                                f"🎁 Ваш промокод на скидку 15%: <b><code>{ref_promo_str}</code></b>",
                                parse_mode="HTML"
                            )
                        except:
                            pass # Если бот не может написать приглашающему (заблокирован), игнорируем
                    else:
                        # Уведомление о прогрессе
                        try:
                            await message.bot.send_message(
                                referrer_id,
                                f"🤝 По вашей ссылке перешел друг! Прогресс: {referrer_user.referral_count}/3"
                            )
                        except:
                            pass

            await session.commit()
            logger.info(f"New user: {message.from_user.id}")

            # 5. Отправляем приветствие НОВОМУ юзеру
            welcome_text = (
                "👋 Добро пожаловать в магазин!\n\n"
                f"🎉 В честь знакомства дарим вам промокод: <code>{promo_str}</code>\n"
                "Он дает скидку 200₽ на первый заказ!\n\n"
                "Посмотреть ваши промокоды можно в Профиле (👤)."
            )

            if message.from_user.id == ADMIN_ID:
                await message.answer("👋 Здравствуй, Админ!", reply_markup=admin_menu_kb())
            else:
                await message.answer(welcome_text, parse_mode="HTML", reply_markup=main_menu_kb())

        else:
            # --- СЦЕНАРИЙ: СТАРЫЙ ПОЛЬЗОВАТЕЛЬ ---
            user.username = message.from_user.username
            user.first_name = message.from_user.first_name
            user.last_name = message.from_user.last_name
            user.language_code = message.from_user.language_code
            user.interaction_count += 1
            user.last_seen = datetime.utcnow()
            await session.commit()

            if message.from_user.id == ADMIN_ID:
                await message.answer("👋 Здравствуй, Админ!", reply_markup=admin_menu_kb())
            else:
                await message.answer("👋 С возвращением!", reply_markup=main_menu_kb())

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

    # --- НОВЫЙ ШАГ: Спрашиваем промокод ---
    await state.set_state(OrderState.promo)
    
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Пропустить"))
    builder.adjust(1)
    
    await message.answer("🎁 У вас есть промокод? Введите его или нажмите 'Пропустить'.", reply_markup=builder.as_markup())

# Шаг 4: Обработка промокода
@router.message(OrderState.promo)
async def process_promo(message: types.Message, state: FSMContext):
    promo_code_input = message.text
    
    # 1. Если нажали "Пропустить"
    if promo_code_input == "Пропустить":
        # Очищаем данные о скидке, если они были, и идем дальше
        await state.update_data(applied_promo_id=None, discount_val=0, discount_type=None)
        await show_confirmation(message, state)
        return # Важно выйти, чтобы код ниже не выполнялся

    # 2. Если ввели код
    async with async_session_maker() as session:
        # Ищем промокод в базе (активный, не использованный)
        promo_obj = await session.scalar(
            select(PromoCode).where(
                PromoCode.code == promo_code_input, 
                PromoCode.is_used == False
            )
        )
        
        if promo_obj:
            # Промокод найден
            discount_val = 0
            discount_type = ""
            
            # Проверяем тип скидки: Рубли или Проценты
            if promo_obj.discount_amount > 0:
                discount_val = promo_obj.discount_amount
                discount_type = "rub"
                await message.answer(f"✅ Промокод принят! Скидка: {discount_val}₽")
            
            elif promo_obj.discount_percent > 0:
                discount_val = promo_obj.discount_percent
                discount_type = "percent"
                await message.answer(f"✅ Промокод принят! Скидка: {discount_val}%")
            
            else:
                # На всякий случай, если в базе пусто и там, и там
                await message.answer("❌ Ошибка промокода.")
                return

            # Сохраняем данные в память машины состояний
            await state.update_data(
                applied_promo_id=promo_obj.id, 
                discount_val=discount_val, 
                discount_type=discount_type
            )
            
            # Переходим к подтверждению
            await show_confirmation(message, state)

        else:
            # Промокод не найден или использован
            await message.answer("❌ Промокод не найден или уже использован. Попробуйте еще раз или нажмите 'Пропустить'.")
            # Не меняем состояние, ждем повторного ввода

# Шаг 5: Показ чека и подтверждение
async def show_confirmation(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    
    # 1. Получаем данные о скидке
    discount_val = data.get('discount_val', 0)
    discount_type = data.get('discount_type') # 'rub' или 'percent'
    
    # 2. Считаем итоговую сумму корзины
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

    # 3. Вычисляем размер скидки
    discount_amount = 0
    if discount_type == 'percent':
        # Скидка в процентах
        discount_amount = int(total * (discount_val / 100))
    elif discount_type == 'rub':
        # Скидка в рублях
        discount_amount = discount_val
    
    # Защита: скидка не может быть больше суммы заказа
    if discount_amount > total:
        discount_amount = total
    
    # Итого к оплате
    final_total = total - discount_amount

    # 4. Формируем текст чека
    text = (
        f"<b>Подтвердите заказ:</b>\n\n"
        f"📞 Телефон: {data['phone']}\n"
        f"🏠 Адрес: {data['address']}\n\n"
        f"<b>Ваши товары:</b>\n" + "\n".join(text_list) + 
        f"\n\n💰 <b>Сумма товаров:</b> {total}₽"
    )
    
    # Если есть скидка, добавляем строку
    if discount_amount > 0:
        text += f"\n📉 <b>Скидка:</b> -{discount_amount}₽"
    
    text += f"\n\n💳 <b>Итого к оплате:</b> {final_total}₽"

    # 5. Клавиатура
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm_order_final")
    builder.button(text="❌ Отмена", callback_data="cancel_order_final")
    builder.adjust(2)
    
    # Отправляем чек (убираем Reply клавиатуру "Пропустить")
    await message.answer(text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    # Отправляем кнопки подтверждения
    await message.answer("Все верно?", reply_markup=builder.as_markup())


# Шаг 6: Финал (Сохранение в БД)
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

        # 1. Считаем суммы и собираем список товаров
        base_amount = 0
        receipt_lines = []
        admin_items_list = [] # Отдельный список для админа
        
        for item in items_list:
            var = await session.get(ProductVariant, item.variant_id)
            prod = await session.get(Product, var.product_id)
            subtotal = var.price * item.quantity
            base_amount += subtotal
            receipt_lines.append(f"• {prod.name} ({var.size}) x{item.quantity} = {subtotal}₽")
            admin_items_list.append(f"• {prod.name} ({var.size}) x{item.quantity}")

        # 2. Высчитываем скидку
        discount_val = data.get('discount_val', 0)
        discount_type = data.get('discount_type')
        promo_code_str = None
        
        discount_amount = 0
        if discount_type == 'percent':
            discount_amount = int(base_amount * (discount_val / 100))
        elif discount_type == 'rub':
            discount_amount = discount_val
        
        # Защита от отрицательной суммы
        if discount_amount > base_amount: discount_amount = base_amount
        
        total_amount = base_amount - discount_amount
        
        # Если был применен промокод, найдем его строку для админа
        if 'applied_promo_id' in data:
            promo_obj = await session.get(PromoCode, data['applied_promo_id'])
            if promo_obj:
                promo_code_str = promo_obj.code

        # 3. Создаем заказ
        import time
        temp_number = f"TEMP-{int(time.time())}" 
        
        order = Order(
            order_number=temp_number,
            user_id=user.id,
            total_amount=total_amount, # Сохраняем итоговую сумму
            status="new",
            customer_phone=data['phone'],
            shipping_address=data['address'],
            customer_name=user.first_name
        )
        session.add(order)
        await session.flush()
        
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
            await session.delete(item)

        # 5. Статистика и списание промокода
        user.orders_count += 1
        user.total_spent += total_amount
        
        if 'applied_promo_id' in data:
            promo = await session.get(PromoCode, data['applied_promo_id'])
            if promo:
                promo.is_used = True

        await session.commit()

    # 6. Чек для клиента
    receipt_text = (
        f"🎉 <b>Заказ оформлен!</b>\n"
        f"📝 Номер: <code>{real_order_number}</code>\n"
        f"📞 Телефон: {data['phone']}\n"
        f"📍 Адрес: {data['address']}\n\n"
        f"<b>Чек:</b>\n" + "\n".join(receipt_lines) +
        f"\n💰 Сумма: {base_amount}₽"
    )
    if discount_amount > 0:
        receipt_text += f"\n📉 Скидка: -{discount_amount}₽"
    receipt_text += f"\n\n💳 <b>Итого:</b> {total_amount}₽"

    try:
        await callback.message.delete()
        await callback.message.answer(receipt_text, parse_mode="HTML")
    except:
        await callback.message.answer(receipt_text, parse_mode="HTML")
    
    # 7. Уведомление для АДМИНА (Обновленное)
    admin_text = (
        f"🛍 <b>НОВЫЙ ЗАКАЗ!</b>\n\n"
        f"📝 <b>Номер:</b> <code>{real_order_number}</code>\n"
        f"👤 <b>Клиент:</b> {user.first_name} (@{user.username})\n"
        f"📞 <b>Телефон:</b> {data['phone']}\n"
        f"📍 <b>Адрес:</b> {data['address']}\n"
        f"📅 <b>Дата:</b> {order.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        f"<b>Состав заказа:</b>\n" + "\n".join(admin_items_list) + "\n\n"
        
        f"💰 <b>Сумма товаров:</b> {base_amount}₽"
    )
    
    if promo_code_str:
        admin_text += f"\n🏷 <b>Промокод:</b> <code>{promo_code_str}</code> (-{discount_amount}₽)"
    
    admin_text += f"\n\n💸 <b>ИТОГО к оплате:</b> <b>{total_amount}₽</b>"

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
        builder.button(text="🎁 Промокоды", callback_data="profile_promos")
        builder.button(text="👥 Пригласить друзей", callback_data="profile_referral")
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
        builder.button(text="🎁 Промокоды", callback_data="profile_promos")
        builder.button(text="👥 Пригласить друзей", callback_data="profile_referral")
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

@router.callback_query(F.data == "profile_referral")
async def profile_referral(callback: types.CallbackQuery):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        
        # Генерируем ссылку (с очисткой имени)
        clean_bot_name = BOT_NAME.replace("@", "").replace("https://t.me/", "").strip()
        ref_link = f"https://t.me/{clean_bot_name}?start={user.telegram_id}"
        
        # Считаем прогресс
        current_count = user.referral_count
        needed = 3 - (current_count % 3)
        if needed == 3: needed = 0 
        bonuses_earned = current_count // 3

        text = (
            f"👥 <b>Реферальная программа</b>\n\n"
            f"Приглашай друзей по ссылке ниже.\n"
            f"За каждые 3 друга — скидка 15%!\n\n"
            
            # Ссылка в тексте (на случай, если кнопка не сработает)
            f"🔗 <b>Ваша ссылка:</b>\n"
            f"<code>{ref_link}</code>\n\n"
            
            f"📊 <b>Статистика:</b>\n"
            f"👤 Приглашено: <b>{current_count}</b>\n"
            f"🎁 Бонусов получено: <b>{bonuses_earned}</b>\n"
            f"🚀 Осталось до скидки: <b>{needed}</b> чел."
        )
        
        builder = InlineKeyboardBuilder()
        
        # Кнопка, которая открывает бота по ссылке (это и есть переход по реф. ссылке)
        builder.button(text="🔗 Пригласить друга (Открыть)", url=ref_link)
        
        builder.button(text="🔙 Назад", callback_data="back_to_profile")
        builder.adjust(1)
        
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup(), disable_web_page_preview=True)

@router.callback_query(F.data == "profile_promos")
async def profile_promos(callback: types.CallbackQuery):
    async with async_session_maker() as session:
        # 1. Сначала находим пользователя, чтобы получить его ВНУТРЕННИЙ ID (из базы)
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        
        if not user:
            await callback.answer("Ошибка данных.", show_alert=True)
            return

        # 2. Ищем промокоды, привязанные к этому ВНУТРЕННЕМУ ID
        promos = await session.scalars(
            select(PromoCode)
            .where(PromoCode.owner_id == user.id, PromoCode.is_used == False)
        )
        promos_list = promos.all()

        if not promos_list:
            text = "🎁 <b>Ваши промокоды</b>\n\nУ вас пока нет активных промокодов."
        else:
            text = "🎁 <b>Ваши промокоды</b>\n\n"
            for p in promos_list:
                # Формируем строку скидки
                if p.discount_amount > 0:
                    disc = f"{p.discount_amount}₽"
                else:
                    disc = f"{p.discount_percent}%"
                
                text += (
                    f"🏷 <b>{p.description or 'Промокод'}</b>\n"
                    f"Код: <code>{p.code}</code>\n"
                    f"Скидка: {disc}\n\n"
                )

        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data="back_to_profile")
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())