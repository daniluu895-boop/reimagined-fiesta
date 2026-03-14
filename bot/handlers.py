from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from database.database import async_session_maker
from database.models import User, Category, Product, ProductVariant, CartItem
from config import ADMIN_ID
from utils.logger import logger

# Импортируем клавиатуры и состояния из соседних файлов
from bot.keyboards.keyboards import (
    main_menu_kb, admin_menu_kb, categories_kb, variants_kb, 
    product_actions_kb, cart_kb, admin_cancel_kb, admin_confirm_kb
)
from bot.states import AddProductState, OrderState

router = Router()

# --- 1. СТАРТ И РОЛИ ---
@router.message(CommandStart())
async def cmd_start(message: types.Message):
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if not user:
            new_user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                is_admin=(message.from_user.id == ADMIN_ID)
            )
            session.add(new_user)
            await session.commit()
            logger.info(f"New user: {message.from_user.id}")

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
        builder = types.InlineKeyboardBuilder()
        for p in prods:
            builder.button(text=p.name, callback_data=f"prod_{p.id}")
        builder.button(text="🔙 Назад", callback_data="back_to_cats")
        builder.adjust(1)
        await callback.message.edit_text("Товары:", reply_markup=builder.as_markup())

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
        if not variants.all():
            await callback.answer("Нет доступных вариантов")
            return
        # Перезапрос т.к. all() "съедает" результат
        variants = await session.scalars(select(ProductVariant).where(ProductVariant.product_id == prod_id))
        await callback.message.edit_text("Выберите вариант:", reply_markup=variants_kb(variants.all(), prod_id))

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
        items = await session.scalars(select(CartItem).where(CartItem.user_id == user.id))
        items_list = items.all()
        
        if not items_list:
            await message.answer("Корзина пуста")
            return

        # Подгружаем данные для отображения
        text = "<b>Корзина:</b>\n"
        total = 0
        for item in items_list:
            # Явно подгружаем связанные объекты (в реальном проекте лучше selectinload)
            var = await session.get(ProductVariant, item.variant_id)
            prod = await session.get(Product, var.product_id)
            subtotal = var.price * item.quantity
            total += subtotal
            text += f"- {prod.name} ({var.size}) x{item.quantity} = {subtotal}₽\n"
        
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
        builder = types.InlineKeyboardBuilder()
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