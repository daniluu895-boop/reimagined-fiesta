from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- Главное меню ---
def main_menu_kb():
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Каталог"), KeyboardButton(text="🛒 Корзина")],
        [KeyboardButton(text="👤 Профиль")]
    ], resize_keyboard=True)
    return kb

def admin_menu_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="➕ Добавить товар"), KeyboardButton(text="📦 Каталог")],
        [KeyboardButton(text="🗑 Очистить БД")]
    ], resize_keyboard=True)

# --- Админ: Добавление товара ---
def admin_cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
    ])

def admin_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Сохранить", callback_data="admin_save_product"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
    ])

# --- Каталог ---
def categories_kb(categories):
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.button(text=cat.name, callback_data=f"cat_{cat.id}")
    builder.adjust(2)
    return builder.as_markup()

def back_to_cats_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_cats")]
    ])

# --- Товары ---
def variants_kb(variants, product_id):
    builder = InlineKeyboardBuilder()
    for var in variants:
        text = f"{var.size} / {var.color} - {var.price}₽"
        builder.button(text=text, callback_data=f"var_{var.id}")
    builder.button(text="🔙 Назад", callback_data="back_to_cats")
    builder.adjust(2)
    return builder.as_markup()

def product_actions_kb(product_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 В корзину", callback_data=f"add_cart_{product_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_cats")]
    ])

# --- Корзина ---
def cart_kb(items):
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(text=f"❌ {item.variant.product.name} ({item.variant.size})", callback_data=f"del_cart_{item.id}")
    builder.button(text="✅ Оформить заказ", callback_data="checkout")
    builder.button(text="🗑 Очистить", callback_data="clear_cart")
    builder.adjust(1)
    return builder.as_markup()