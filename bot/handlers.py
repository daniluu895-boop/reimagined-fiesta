from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func, desc
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

from bot.keyboards.keyboards import (
    main_menu_kb, admin_menu_kb, categories_kb, variants_kb,
    product_actions_kb, cart_kb, admin_cancel_kb, admin_confirm_kb,
    admin_orders_kb, admin_order_detail_kb, admin_back_kb, ORDER_STATUSES,
    support_menu_kb, admin_support_kb, faq_kb, support_back_kb
)
from bot.states import AddProductState, OrderState, ProfileState, SupportState, EditStockState

router = Router()


# --- 1. СТАРТ И РОЛИ ---
@router.message(CommandStart())
async def cmd_start(message: types.Message, command: Command):
    referrer_id = None
    if command.args:
        try:
            referrer_id = int(command.args)
            if referrer_id == message.from_user.id:
                referrer_id = None
        except ValueError:
            pass

    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        
        if not user:
            new_user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                language_code=message.from_user.language_code,
                is_admin=(message.from_user.id == ADMIN_ID),
                interaction_count=1,
                referrer_id=referrer_id
            )
            session.add(new_user)
            await session.flush()

            promo_str = "WELCOME-" + ''.join(random.choices(string.digits, k=6))
            welcome_promo = PromoCode(
                code=promo_str,
                discount_amount=200,
                discount_percent=0,
                description="🎁 Подарок за регистрацию (-200₽)",
                owner_id=new_user.id
            )
            session.add(welcome_promo)
            
            if referrer_id:
                referrer_user = await session.scalar(select(User).where(User.telegram_id == referrer_id))
                if referrer_user:
                    referrer_user.referral_count += 1
                    
                    if referrer_user.referral_count % 3 == 0:
                        ref_promo_str = "GIFT-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                        new_ref_promo = PromoCode(
                            code=ref_promo_str,
                            discount_percent=15,
                            discount_amount=0,
                            owner_id=referrer_user.id
                        )
                        session.add(new_ref_promo)
                        
                        try:
                            await message.bot.send_message(
                                referrer_id,
                                f"🎉 Ура! Вы пригласили 3 друзей!\n"
                                f"🎁 Ваш промокод на скидку 15%: <b><code>{ref_promo_str}</code></b>",
                                parse_mode="HTML"
                            )
                        except:
                            pass
                    else:
                        try:
                            await message.bot.send_message(
                                referrer_id,
                                f"🤝 По вашей ссылке перешел друг! Прогресс: {referrer_user.referral_count}/3"
                            )
                        except:
                            pass

            await session.commit()
            logger.info(f"New user: {message.from_user.id}")

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
        # Фильтруем: только товары с вариантами где есть остаток
        products = await session.scalars(
            select(Product)
            .options(selectinload(Product.variants))
            .where(Product.category_id == cat_id)
        )
        
        # Фильтруем: оставляем только те, где есть хотя бы 1 вариант в наличии
        available_products = [
            p for p in products.all() 
            if any(v.stock_quantity > 0 for v in p.variants)
        ]
        
        if not available_products:
            await callback.message.edit_text(
                "В этой категории нет товаров в наличии",
                reply_markup=back_to_cats_kb()
            )
            return
        
        builder = InlineKeyboardBuilder()
        for p in available_products:
            builder.button(text=p.name, callback_data=f"prod_{p.id}")
        builder.button(text="🔙 Назад", callback_data="back_to_cats")
        builder.adjust(1)
        
        try:
            await callback.message.edit_text(
                "Товары (в наличии):", 
                reply_markup=builder.as_markup()
            )
        except TelegramBadRequest:
            pass


@router.callback_query(F.data == "back_to_cats")
async def back_to_cats(callback: types.CallbackQuery):
    async with async_session_maker() as session:
        cats = await session.scalars(select(Category).where(Category.is_active == True))
        try:
            await callback.message.edit_text("Категории:", reply_markup=categories_kb(cats.all()))
        except TelegramBadRequest:
            pass
    await callback.answer()


@router.callback_query(F.data.startswith("prod_"))
async def show_product(callback: types.CallbackQuery):
    prod_id = int(callback.data.split("_")[1])
    async with async_session_maker() as session:
        product = await session.get(Product, prod_id)
        if not product:
            await callback.answer("Товар не найден")
            return
            
        text = f"<b>{product.name}</b>\n{product.description or 'Описание отсутствует'}"
        if product.main_photo_id:
            try:
                await callback.message.answer_photo(
                    photo=product.main_photo_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=product_actions_kb(prod_id)
                )
                await callback.message.delete()
            except TelegramBadRequest:
                await callback.message.edit_text(text, parse_mode="HTML", reply_markup=product_actions_kb(prod_id))
        else:
            try:
                await callback.message.edit_text(text, parse_mode="HTML", reply_markup=product_actions_kb(prod_id))
            except TelegramBadRequest:
                pass
    
    await callback.answer()


# --- 3. КОРЗИНА ---
@router.callback_query(F.data.startswith("add_cart_"))
async def select_variant(callback: types.CallbackQuery):
    prod_id = int(callback.data.split("_")[2])
    async with async_session_maker() as session:
        variants = await session.scalars(select(ProductVariant).where(ProductVariant.product_id == prod_id))
        variants_list = variants.all()
        
        if not variants_list:
            await callback.answer("Нет доступных вариантов", show_alert=True)
            return

        kb = variants_kb(variants_list, prod_id)
        
        try:
            if callback.message.photo:
                await callback.message.edit_caption(caption="Выберите вариант:", reply_markup=kb)
            elif callback.message.text:
                await callback.message.edit_text("Выберите вариант:", reply_markup=kb)
            else:
                await callback.message.answer("Выберите вариант:", reply_markup=kb)
        except TelegramBadRequest:
            pass
            
    await callback.answer()


@router.callback_query(F.data.startswith("var_"))
async def add_to_cart(callback: types.CallbackQuery):
    var_id = int(callback.data.split("_")[1])
    
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        variant = await session.get(ProductVariant, var_id)
        
        # 🚫 Проверка остатков
        if variant.stock_quantity <= 0:
            await callback.answer("❌ Нет в наличии", show_alert=True)
            return
        
        existing = await session.scalar(
            select(CartItem).where(
                CartItem.user_id == user.id, 
                CartItem.variant_id == var_id
            )
        )
        
        # Проверяем, чтобы не добавили больше чем есть
        current_in_cart = existing.quantity if existing else 0
        available = variant.stock_quantity - current_in_cart
        
        if available <= 0:
            await callback.answer("❌ Больше нет в наличии", show_alert=True)
            return
        
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
        
        items = await session.scalars(
            select(CartItem)
            .where(CartItem.user_id == user.id)
            .options(selectinload(CartItem.variant).selectinload(ProductVariant.product))
        )
        
        items_list = items.all()
        
        if not items_list:
            await message.answer("Корзина пуста")
            return

        text = "<b>Корзина:</b>\n"
        total = 0
        for item in items_list:
            subtotal = item.variant.price * item.quantity
            total += subtotal
            text += f"- {item.variant.product.name} ({item.variant.size}) x{item.quantity} = {subtotal}₽\n"
        
        text += f"\n<b>Итого: {total}₽</b>"
        await message.answer(text, parse_mode="HTML", reply_markup=cart_kb(items_list))


@router.callback_query(F.data.startswith("del_cart_"))
async def delete_cart_item(callback: types.CallbackQuery):
    item_id = int(callback.data.split("_")[2])
    async with async_session_maker() as session:
        item = await session.get(CartItem, item_id)
        if item:
            await session.delete(item)
            await session.commit()
            await callback.answer("Удалено")
        else:
            await callback.answer("Товар не найден")
    
    # Обновляем корзину
    await view_cart_callback(callback)


async def view_cart_callback(callback: types.CallbackQuery):
    """Вспомогательная функция для обновления корзины"""
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        
        items = await session.scalars(
            select(CartItem)
            .where(CartItem.user_id == user.id)
            .options(selectinload(CartItem.variant).selectinload(ProductVariant.product))
        )
        
        items_list = items.all()
        
        if not items_list:
            try:
                await callback.message.edit_text("Корзина пуста")
            except TelegramBadRequest:
                pass
            return

        text = "<b>Корзина:</b>\n"
        total = 0
        for item in items_list:
            subtotal = item.variant.price * item.quantity
            total += subtotal
            text += f"- {item.variant.product.name} ({item.variant.size}) x{item.quantity} = {subtotal}₽\n"
        
        text += f"\n<b>Итого: {total}₽</b>"
        
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=cart_kb(items_list))
        except TelegramBadRequest:
            pass


@router.callback_query(F.data == "clear_cart")
async def clear_cart(callback: types.CallbackQuery):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        await session.execute(
            select(CartItem).where(CartItem.user_id == user.id)
        )
        items = await session.scalars(select(CartItem).where(CartItem.user_id == user.id))
        for item in items.all():
            await session.delete(item)
        await session.commit()
    
    try:
        await callback.message.edit_text("Корзина очищена")
    except TelegramBadRequest:
        pass
    await callback.answer("Корзина очищена")

# --- ИЗМЕНЕНИЕ КОЛИЧЕСТВА В КОРЗИНЕ ---

@router.callback_query(F.data.startswith("qty_plus_"))
async def qty_plus(callback: types.CallbackQuery):
    """Увеличить количество товара"""
    item_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        item = await session.scalar(
            select(CartItem)
            .where(CartItem.id == item_id)
            .options(selectinload(CartItem.variant))
        )
        
        if not item:
            await callback.answer("Товар не найден", show_alert=True)
            return
        
        # Проверяем остаток на складе
        if item.quantity >= item.variant.stock_quantity:
            await callback.answer(f"❌ На складе только {item.variant.stock_quantity} шт.", show_alert=True)
            return
        
        item.quantity += 1
        await session.commit()
    
    await callback.answer("➕ +1")
    await view_cart_callback(callback)


@router.callback_query(F.data.startswith("qty_minus_"))
async def qty_minus(callback: types.CallbackQuery):
    """Уменьшить количество товара"""
    item_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        item = await session.scalar(
            select(CartItem)
            .where(CartItem.id == item_id)
            .options(selectinload(CartItem.variant).selectinload(ProductVariant.product))
        )
        
        if not item:
            await callback.answer("Товар не найден", show_alert=True)
            return
        
        if item.quantity <= 1:
            # Если кол-во = 1, удаляем товар
            await session.delete(item)
            await session.commit()
            await callback.answer("🗑 Товар удалён")
        else:
            item.quantity -= 1
            await session.commit()
            await callback.answer("➖ -1")
    
    await view_cart_callback(callback)


@router.callback_query(F.data == "cart_item_info")
async def cart_item_info(callback: types.CallbackQuery):
    """Заглушка для нажатия на название товара"""
    await callback.answer("Используйте ➕ и ➖ для изменения количества")

# --- 4. АДМИНКА: ДОБАВЛЕНИЕ ТОВАРА ---
@router.message(F.text == "➕ Добавить товар")
async def admin_add_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
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
    async with async_session_maker() as session:
        cats = await session.scalars(select(Category).where(Category.is_active == True))
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
    await callback.answer()


@router.message(AddProductState.photo, F.photo)
async def admin_add_photo(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(photo=file_id)
    await state.set_state(AddProductState.variants)
    await state.update_data(variants_list=[])
    await message.answer(
        "Фото принято. Теперь введите варианты в формате:\n"
        "`Размер,Цвет,Цена,Остаток`\n"
        "Например: `M,Черный,1500,10`\n\n"
        "Когда закончите — напишите **Готово**",
        parse_mode="Markdown"
    )


@router.message(AddProductState.variants)
async def admin_add_variant(message: types.Message, state: FSMContext):
    if message.text.lower() == "готово":
        data = await state.get_data()
        variants = data.get("variants_list", [])
        if not variants:
            await message.answer("❌ Добавьте хотя бы один вариант!")
            return
        text = f"Создаем товар: {data['name']}?\nВариантов: {len(variants)}"
        await state.set_state(AddProductState.confirm)
        await message.answer(text, reply_markup=admin_confirm_kb())
        return

    try:
        parts = message.text.split(',')
        if len(parts) != 4:
            raise ValueError
        size, color, price, qty = [p.strip() for p in parts]
        
        data = await state.get_data()
        variants = data.get("variants_list", [])
        variants.append({
            "size": size,
            "color": color,
            "price": int(price),
            "stock": int(qty)
        })
        await state.update_data(variants_list=variants)
        await message.answer(f"✅ Вариант добавлен ({len(variants)}). Введите следующий или напишите 'Готово'.")
    except ValueError:
        await message.answer("❌ Ошибка формата. Попробуйте: `M,Черный,1500,10`", parse_mode="Markdown")


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
        await session.flush()
        
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
    await callback.answer()


@router.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.answer()


# --- 5. ОФОРМЛЕНИЕ ЗАКАЗА (CHECKOUT) ---

@router.callback_query(F.data == "checkout")
async def start_checkout(callback: types.CallbackQuery, state: FSMContext):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        items = await session.scalars(select(CartItem).where(CartItem.user_id == user.id))
        
        if not items.all():
            await callback.answer("Корзина пуста!", show_alert=True)
            return

        saved_phone = user.phone

    await state.set_state(OrderState.phone)
    
    builder = ReplyKeyboardBuilder()
    if saved_phone:
        builder.add(KeyboardButton(text=f"Использовать {saved_phone}"))
    builder.add(KeyboardButton(text="📲 Отправить другой номер", request_contact=True))
    builder.add(KeyboardButton(text="❌ Отмена"))
    builder.adjust(1)
    
    await callback.message.answer("Введите номер телефона:", reply_markup=builder.as_markup())
    await callback.answer()


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
        async with async_session_maker() as session:
            u = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
            phone = u.phone
    else:
        phone = message.text

    await state.update_data(phone=phone)
    await state.set_state(OrderState.address)
    
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        saved_address = user.shipping_address
        
        builder = ReplyKeyboardBuilder()
        if saved_address:
            btn_text = f"Использовать {saved_address[:20]}..."
            builder.add(KeyboardButton(text=btn_text))
        builder.add(KeyboardButton(text="Ввести новый адрес"))
        builder.adjust(1)
        
        await message.answer("Отлично! Теперь адрес доставки:", reply_markup=builder.as_markup())


@router.message(OrderState.address)
async def process_address(message: types.Message, state: FSMContext):
    address = ""
    
    if message.text and message.text.startswith("Использовать"):
        async with async_session_maker() as session:
            u = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
            address = u.shipping_address
    elif message.text == "Ввести новый адрес":
        await message.answer("Хорошо, напишите адрес текстом:")
        return
    else:
        address = message.text

    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if not user.shipping_address and address:
            user.shipping_address = address
            await session.commit()

    await state.update_data(address=address)
    await state.set_state(OrderState.promo)
    
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Пропустить"))
    builder.adjust(1)
    
    await message.answer("🎁 У вас есть промокод? Введите его или нажмите 'Пропустить'.", reply_markup=builder.as_markup())


@router.message(OrderState.promo)
async def process_promo(message: types.Message, state: FSMContext):
    promo_code_input = message.text
    
    if promo_code_input == "Пропустить":
        await state.update_data(applied_promo_id=None, discount_val=0, discount_type=None)
        await show_confirmation(message, state)
        return

    async with async_session_maker() as session:
        promo_obj = await session.scalar(
            select(PromoCode).where(
                PromoCode.code == promo_code_input,
                PromoCode.is_used == False
            )
        )
        
        if promo_obj:
            discount_val = 0
            discount_type = ""
            
            if promo_obj.discount_amount > 0:
                discount_val = promo_obj.discount_amount
                discount_type = "rub"
                await message.answer(f"✅ Промокод принят! Скидка: {discount_val}₽")
            elif promo_obj.discount_percent > 0:
                discount_val = promo_obj.discount_percent
                discount_type = "percent"
                await message.answer(f"✅ Промокод принят! Скидка: {discount_val}%")
            else:
                await message.answer("❌ Ошибка промокода.")
                return

            await state.update_data(
                applied_promo_id=promo_obj.id,
                discount_val=discount_val,
                discount_type=discount_type
            )
            
            await show_confirmation(message, state)
        else:
            await message.answer("❌ Промокод не найден или уже использован. Попробуйте еще раз или нажмите 'Пропустить'.")


async def show_confirmation(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    
    discount_val = data.get('discount_val', 0)
    discount_type = data.get('discount_type')
    
    total = 0
    text_list = []
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        items = await session.scalars(
            select(CartItem)
            .where(CartItem.user_id == user.id)
            .options(selectinload(CartItem.variant).selectinload(ProductVariant.product))
        )
        
        for item in items.all():
            subtotal = item.variant.price * item.quantity
            total += subtotal
            text_list.append(f"• {item.variant.product.name} ({item.variant.size}) x{item.quantity} = {subtotal}₽")

    discount_amount = 0
    if discount_type == 'percent':
        discount_amount = int(total * (discount_val / 100))
    elif discount_type == 'rub':
        discount_amount = discount_val
    
    if discount_amount > total:
        discount_amount = total
    
    final_total = total - discount_amount

    text = (
        f"<b>Подтвердите заказ:</b>\n\n"
        f"📞 Телефон: {data['phone']}\n"
        f"🏠 Адрес: {data['address']}\n\n"
        f"<b>Ваши товары:</b>\n" + "\n".join(text_list) +
        f"\n\n💰 <b>Сумма товаров:</b> {total}₽"
    )
    
    if discount_amount > 0:
        text += f"\n📉 <b>Скидка:</b> -{discount_amount}₽"
    
    text += f"\n\n💳 <b>Итого к оплате:</b> {final_total}₽"

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm_order_final")
    builder.button(text="❌ Отмена", callback_data="cancel_order_final")
    builder.adjust(2)
    
    await message.answer(text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    await message.answer("Все верно?", reply_markup=builder.as_markup())


@router.callback_query(F.data == "confirm_order_final")
async def finish_order(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        items = await session.scalars(
            select(CartItem)
            .where(CartItem.user_id == user.id)
            .options(selectinload(CartItem.variant).selectinload(ProductVariant.product))
        )
        items_list = items.all()
        
        if not items_list:
            await callback.message.edit_text("Корзина пуста.")
            return

        base_amount = 0
        receipt_lines = []
        admin_items_list = []
        
        # === СКЛАДСКОЙ УЧЁТ: Проверка остатков ===
        for item in items_list:
            variant = await session.get(ProductVariant, item.variant_id)
            
            if variant.stock_quantity < item.quantity:
                await callback.message.answer(
                    f"❌ Недостаточно товара на складе: {item.variant.product.name} ({variant.size}/{variant.color})\n"
                    f"Доступно: {variant.stock_quantity} шт."
                )
                return
        
        # === СКЛАДСКОЙ УЧЁТ: Списание ===
        for item in items_list:
            variant = await session.get(ProductVariant, item.variant_id)
            
            # Списываем остаток
            variant.stock_quantity -= item.quantity
            
            subtotal = item.variant.price * item.quantity
            base_amount += subtotal
            receipt_lines.append(f"• {item.variant.product.name} ({item.variant.size}) x{item.quantity} = {subtotal}₽")
            admin_items_list.append(f"• {item.variant.product.name} ({item.variant.size}) x{item.quantity}")

        discount_val = data.get('discount_val', 0)
        discount_type = data.get('discount_type')
        promo_code_str = None
        
        discount_amount = 0
        if discount_type == 'percent':
            discount_amount = int(base_amount * (discount_val / 100))
        elif discount_type == 'rub':
            discount_amount = discount_val
        
        if discount_amount > base_amount:
            discount_amount = base_amount
        
        total_amount = base_amount - discount_amount
        
        if 'applied_promo_id' in data:
            promo_obj = await session.get(PromoCode, data['applied_promo_id'])
            if promo_obj:
                promo_code_str = promo_obj.code

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
        await session.flush()
        
        year = datetime.now().year
        real_order_number = f"ORD-{year}-{order.id}"
        order.order_number = real_order_number

        for item in items_list:
            order_item = OrderItem(
                order_id=order.id,
                variant_id=item.variant.id,
                product_name=item.variant.product.name,
                size=item.variant.size,
                color=item.variant.color,
                quantity=item.quantity,
                price_at_purchase=item.variant.price,
                subtotal=item.variant.price * item.quantity
            )
            session.add(order_item)
            await session.delete(item)

        user.orders_count += 1
        user.total_spent += total_amount
        
        if 'applied_promo_id' in data:
            promo = await session.get(PromoCode, data['applied_promo_id'])
            if promo:
                promo.is_used = True

        await session.commit()
        
        # === СКЛАДСКОЙ УЧЁТ: Уведомление о низком запасе ===
        for item in items_list:
            variant = await session.get(ProductVariant, item.variant_id)
            if variant.stock_quantity <= 5:
                try:
                    await callback.bot.send_message(
                        ADMIN_ID,
                        f"⚠️ <b>Заканчивается товар!</b>\n\n"
                        f"{item.variant.product.name} ({variant.size}/{variant.color})\n"
                        f"Остаток: <b>{variant.stock_quantity}</b> шт.",
                        parse_mode="HTML"
                    )
                except:
                    pass

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
    
    admin_text = (
        f"🛍 <b>НОВЫЙ ЗАКАЗ!</b>\n\n"
        f"📝 <b>Номер:</b> <code>{real_order_number}</code>\n"
        f"👤 <b>Клиент:</b> {user.first_name} (@{user.username or 'нет'})\n"
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


@router.callback_query(F.data == "cancel_order_final")
async def cancel_checkout(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("❌ Оформление отменено.")
    await callback.answer()


# --- ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ---

@router.message(F.text == "👤 Профиль")
async def show_profile(message: types.Message):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        
        if not user:
            await message.answer("Ошибка: пользователь не найден.")
            return

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

        await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())


# --- ИСТОРИЯ ЗАКАЗОВ ---

@router.callback_query(F.data == "profile_orders")
async def profile_orders(callback: types.CallbackQuery):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        
        orders = await session.scalars(
            select(Order)
            .where(Order.user_id == user.id)
            .order_by(Order.created_at.desc())
        )
        orders_list = orders.all()

        if not orders_list:
            await callback.answer("У вас пока нет заказов.", show_alert=True)
            return

        builder = InlineKeyboardBuilder()
        text = "<b>📦 Ваши заказы:</b>\n\n"
        
        for order in orders_list:
            status_emoji = {"new": "🟢", "processing": "🟡", "shipped": "🔵", "completed": "✅", "cancelled": "❌"}.get(order.status, "⚪")
            text += (
                f"{status_emoji} <b>Заказ #{order.order_number}</b>\n"
                f"   Сумма: {order.total_amount}₽ | Статус: {order.status}\n\n"
            )
            builder.button(text=f"Чек #{order.order_number}", callback_data=f"order_detail_{order.id}")
        
        builder.button(text="🔙 Назад", callback_data="back_to_profile")
        builder.adjust(1)
        
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        except TelegramBadRequest:
            pass
        
        await callback.answer()


# --- ПРОСМОТР ЧЕКА ---

@router.callback_query(F.data.startswith("order_detail_"))
async def order_detail(callback: types.CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    async with async_session_maker() as session:
        order = await session.scalar(
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.items))
        )
        
        if not order:
            await callback.answer("Заказ не найден")
            return

        text = f"🧾 <b>Чек по заказу #{order.order_number}</b>\n\n"
        subtotal = 0
        for item in order.items:
            item_total = item.price_at_purchase * item.quantity
            subtotal += item_total
            text += f"• {item.product_name} ({item.size}) x{item.quantity} = {item_total}₽\n"
        
        discount = subtotal - order.total_amount
        if discount < 0:
            discount = 0
        
        text += f"\n💰 <b>Сумма товаров:</b> {subtotal}₽\n"
        if discount > 0:
            text += f"📉 <b>Скидка:</b> -{discount}₽\n"
        text += f"💳 <b>Итого:</b> {order.total_amount}₽\n"
        
        text += (
            f"\n📍 Адрес: {order.shipping_address or 'Не указан'}\n"
            f"📞 Телефон: {order.customer_phone or 'Не указан'}\n"
            f"📅 Дата: {order.created_at.strftime('%d.%m.%Y %H:%M')}"
        )
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад к списку", callback_data="profile_orders")
        
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        except TelegramBadRequest:
            pass
        
        await callback.answer()


# --- НАВИГАЦИЯ ---

@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: types.CallbackQuery):
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
        
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        except TelegramBadRequest:
            pass
        
        await callback.answer()


# --- РЕДАКТИРОВАНИЕ ДАННЫХ ПРОФИЛЯ ---

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


@router.callback_query(F.data == "edit_phone_start")
async def edit_phone_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileState.phone)
    
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📲 Отправить свой номер", request_contact=True)],
        [KeyboardButton(text="❌ Отмена")]
    ], resize_keyboard=True)
    
    await callback.message.answer("Отправьте номер телефона или введите вручную:", reply_markup=kb)
    await callback.answer()


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

    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        user.phone = phone
        await session.commit()
    
    await state.clear()
    await message.answer(f"✅ Телефон обновлен: {phone}", reply_markup=ReplyKeyboardRemove())


@router.callback_query(F.data == "edit_address_start")
async def edit_address_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileState.address)
    await callback.message.answer("Введите новый адрес доставки:")
    await callback.answer()


@router.message(ProfileState.address)
async def save_profile_address(message: types.Message, state: FSMContext):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        user.shipping_address = message.text
        await session.commit()
    
    await state.clear()
    await message.answer(f"✅ Адрес обновлен: {message.text}")


# --- РЕФЕРАЛЬНАЯ СИСТЕМА ---

@router.callback_query(F.data == "profile_referral")
async def profile_referral(callback: types.CallbackQuery):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        
        clean_bot_name = BOT_NAME.replace("@", "").replace("https://t.me/", "").strip()
        ref_link = f"https://t.me/{clean_bot_name}?start={user.telegram_id}"
        
        current_count = user.referral_count
        needed = 3 - (current_count % 3)
        if needed == 3:
            needed = 0
        bonuses_earned = current_count // 3

        text = (
            f"👥 <b>Реферальная программа</b>\n\n"
            f"Приглашай друзей по ссылке ниже.\n"
            f"За каждые 3 друга — скидка 15%!\n\n"
            f"🔗 <b>Ваша ссылка:</b>\n"
            f"<code>{ref_link}</code>\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"👤 Приглашено: <b>{current_count}</b>\n"
            f"🎁 Бонусов получено: <b>{bonuses_earned}</b>\n"
            f"🚀 Осталось до скидки: <b>{needed}</b> чел."
        )
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔗 Пригласить друга (Открыть)", url=ref_link)
        builder.button(text="🔙 Назад", callback_data="back_to_profile")
        builder.adjust(1)
        
        try:
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=builder.as_markup(),
                disable_web_page_preview=True
            )
        except TelegramBadRequest:
            pass
        
        await callback.answer()


# --- МОИ ПРОМОКОДЫ ---

@router.callback_query(F.data == "profile_promos")
async def profile_promos(callback: types.CallbackQuery):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == callback.from_user.id))
        
        if not user:
            await callback.answer("Ошибка данных.", show_alert=True)
            return

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
        
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        except TelegramBadRequest:
            pass
        
        await callback.answer()

# ============================================================
# АДМИНКА: УПРАВЛЕНИЕ ЗАКАЗАМИ
# ============================================================

# Добавим кнопку "📦 Заказы" в админ-меню
# Для этого обновим admin_menu_kb в keyboards.py (см. ниже)


@router.message(F.text == "📦 Заказы")
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


@router.callback_query(F.data == "admin_orders")
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


@router.callback_query(F.data.startswith("admin_orders_page_"))
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


@router.callback_query(F.data.startswith("admin_orders_filter_"))
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


@router.callback_query(
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


@router.callback_query(F.data.startswith("admin_order_next_"))
async def admin_order_next_status(callback: types.CallbackQuery):
    """Перевести заказ в следующий статус"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа")
        return
    
    parts = callback.data.split("_")
    order_id = int(parts[3])
    new_status = parts[4]
    
    await change_order_status(order_id, new_status, callback)


@router.callback_query(F.data.startswith("admin_order_status_"))
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


@router.callback_query(F.data == "admin_back_menu")
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


@router.callback_query(F.data == "admin_orders_info")
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


@router.message(F.text == "🆘 Поддержка")
async def show_support_menu(message: types.Message):
    """Вход в меню поддержки из главного меню"""
    text = (
        "🆘 <b>Служба поддержки</b>\n\n"
        "Выберите действие или напишите нам:\n\n"
        "⏰ Среднее время ответа: 15 минут"
    )
    
    await message.answer(text, parse_mode="HTML", reply_markup=support_menu_kb())


# Оставьте callback-версию для навигации внутри поддержки:
@router.callback_query(F.data == "support_back")
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
@router.callback_query(F.data == "support_new")
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


@router.message(SupportState.user_message)
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
@router.callback_query(F.data == "support_cancel")
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
@router.callback_query(F.data == "support_back")
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
@router.callback_query(F.data == "support_faq")
async def support_faq(callback: types.CallbackQuery):
    """Меню FAQ"""
    text = "❓ <b>Частые вопросы</b>\n\nВыберите тему:"
    
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=faq_kb())
    except TelegramBadRequest:
        pass
    
    await callback.answer()


@router.callback_query(F.data.startswith("faq_"))
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

@router.callback_query(F.data.startswith("admin_reply_"))
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


@router.message(SupportState.admin_reply)
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


@router.callback_query(F.data.startswith("admin_ban_"))
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


# === СКЛАДСКОЙ УЧЁТ ===

@router.message(F.text == "📊 Склад")
async def admin_warehouse(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    async with async_session_maker() as session:
        variants = await session.scalars(
            select(ProductVariant)
            .options(selectinload(ProductVariant.product))
            .order_by(ProductVariant.stock_quantity.asc())  # Сначала мало
        )
        variants_list = variants.all()
        
        if not variants_list:
            await message.answer("Нет товаров на складе")
            return
        
        # Считаем статистику
        total_items = sum(v.stock_quantity for v in variants_list)
        low_stock = [v for v in variants_list if v.stock_quantity <= 5]
        
        text = (
            f"📊 <b>Складская статистика</b>\n\n"
            f"📦 Всего единиц: <b>{total_items}</b>\n"
            f"👎 Мало на складе (≤5): <b>{len(low_stock)}</b>\n\n"
            f"<b>Остатки по товарам:</b>\n"
        )
        
        builder = InlineKeyboardBuilder()
        
        # Показываем первые 20 позиций
        for v in variants_list[:20]:
            emoji = "🔴" if v.stock_quantity == 0 else "🟡" if v.stock_quantity <= 5 else "🟢"
            text += f"{emoji} {v.product.name} ({v.size}/{v.color}): <b>{v.stock_quantity}</b> шт.\n"
            builder.button(
                text=f"✏️ {v.product.name[:15]} ({v.size})", 
                callback_data=f"edit_stock_{v.id}"
            )
        
        if len(variants_list) > 20:
            text += f"\n... и ещё {len(variants_list) - 20} позиций"
        
        builder.button(text="🔙 Назад", callback_data="admin_back_menu")
        builder.adjust(2)
        
        await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

# Редактирование остатков
@router.callback_query(F.data.startswith("edit_stock_"))
async def edit_stock_start(callback: types.CallbackQuery, state: FSMContext):
    variant_id = int(callback.data.split("_")[2])
    
    async with async_session_maker() as session:
        variant = await session.scalar(
            select(ProductVariant)
            .options(selectinload(ProductVariant.product))
            .where(ProductVariant.id == variant_id)
        )
        
        text = (
            f"✏️ Редактирование остатков\n\n"
            f"<b>Товар:</b> {variant.product.name}\n"
            f"<b>Размер/Цвет:</b> {variant.size}/{variant.color}\n"
            f"<b>Текущий остаток:</b> {variant.stock_quantity} шт.\n\n"
            f"Введите новое количество:"
        )
        
        await state.update_data(edit_stock_variant_id=variant_id)
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_cancel_kb())
    
    await state.set_state(EditStockState.quantity)
    await callback.answer()

@router.message(EditStockState.quantity)
async def edit_stock_save(message: types.Message, state: FSMContext):
    try:
        new_quantity = int(message.text)
        if new_quantity < 0:
            raise ValueError
    except:
        await message.answer("Введите число больше 0")
        return
    
    data = await state.get_data()
    variant_id = data["edit_stock_variant_id"]
    
    async with async_session_maker() as session:
        variant = await session.get(ProductVariant, variant_id)
        old_qty = variant.stock_quantity
        variant.stock_quantity = new_quantity
        await session.commit()
        
        await message.answer(
            f"✅ Остаток обновлен!\n"
            f"Было: {old_qty} → Стало: {new_quantity}"
        )
    
    await state.clear()

# Уведомление о низком запасе (вызывается при заказе)
async def check_low_stock(variant_id: int, bot):
    """Проверяет остаток и отправляет уведомление если мало"""
    async with async_session_maker() as session:
        variant = await session.scalar(
            select(ProductVariant)
            .options(selectinload(ProductVariant.product))
            .where(ProductVariant.id == variant_id)
        )
        
        if variant.stock_quantity <= 5:
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"⚠️ <b>Заканчивается товар!</b>\n\n"
                    f"{variant.product.name} ({variant.size}/{variant.color})\n"
                    f"Остаток: <b>{variant.stock_quantity}</b> шт.",
                    parse_mode="HTML"
                )
            except:
                pass