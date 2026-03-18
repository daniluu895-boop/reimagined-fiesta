from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- Главное меню ---
def main_menu_kb():
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Каталог"), KeyboardButton(text="🛒 Корзина")],
        [KeyboardButton(text="🆘 Поддержка")], [KeyboardButton(text="👤 Профиль")]
    ], resize_keyboard=True)
    return kb

def admin_menu_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="➕ Добавить товар"), KeyboardButton(text="📦 Каталог")],
        [KeyboardButton(text="📦 Заказы"), KeyboardButton(text="📊 Склад")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🗑 Очистить БД")]
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
# --- Корзина с кнопками +/-
def cart_kb(items):
    builder = InlineKeyboardBuilder()
    
    for item in items:
        # Кнопки управления количеством: [-] [кол-во] [+]
        builder.row(
            InlineKeyboardButton(
                text=f"➖",
                callback_data=f"qty_minus_{item.id}"
            ),
            InlineKeyboardButton(
                text=f"{item.variant.product.name} ({item.variant.size}) x{item.quantity}",
                callback_data="cart_item_info"  # Заглушка, можно сделать просмотр товара
            ),
            InlineKeyboardButton(
                text=f"➕",
                callback_data=f"qty_plus_{item.id}"
            )
        )
        # Кнопка удаления под каждым товаром
        builder.row(
            InlineKeyboardButton(
                text=f"🗑 Удалить {item.variant.product.name[:15]}",
                callback_data=f"del_cart_{item.id}"
            )
        )
    
    # Общие кнопки внизу
    builder.row(
        InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout"),
        InlineKeyboardButton(text="🗑 Очистить всё", callback_data="clear_cart")
    )
    
    return builder.as_markup()

# --- АДМИН: УПРАВЛЕНИЕ ЗАКАЗАМИ ---

# Статусы заказов
ORDER_STATUSES = {
    "new": ("🟢 Новый", "processing"),
    "processing": ("🟡 В обработке", "shipped"),
    "shipped": ("🔵 Отправлен", "completed"),
    "completed": ("✅ Завершён", None),
    "cancelled": ("❌ Отменён", None)
}


def admin_orders_kb(orders: list, page: int = 0, per_page: int = 5):
    """Клавиатура списка заказов для админа"""
    builder = InlineKeyboardBuilder()
    
    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_orders = orders[start_idx:end_idx]
    
    for order in page_orders:
        status_name, _ = ORDER_STATUSES.get(order.status, ("❓ Неизвестно", None))
        text = f"{status_name} #{order.order_number} - {order.total_amount}₽"
        builder.button(text=text, callback_data=f"admin_order_{order.id}")
    
    # Пагинация
    total_pages = (len(orders) + per_page - 1) // per_page
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"admin_orders_page_{page - 1}")
        )
    
    nav_buttons.append(
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="admin_orders_info")
    )
    
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(text="➡️", callback_data=f"admin_orders_page_{page + 1}")
        )
    
    if nav_buttons:
        builder.row(*nav_buttons)
    
    # Фильтры по статусам
    builder.row(
        InlineKeyboardButton(text="🟢 Новые", callback_data="admin_orders_filter_new"),
        InlineKeyboardButton(text="📋 Все", callback_data="admin_orders_filter_all")
    )
    
    builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="admin_back_menu"))
    
    return builder.as_markup()


def admin_order_detail_kb(order_id: int, current_status: str):
    """Клавиатура действий над заказом"""
    builder = InlineKeyboardBuilder()
    
    status_name, next_status = ORDER_STATUSES.get(current_status, ("❓", None))
    
    # Кнопка перевода в следующий статус
    if next_status:
        next_name, _ = ORDER_STATUSES.get(next_status, (next_status, None))
        builder.button(
            text=f"➡️ {next_name}",
            callback_data=f"admin_order_next_{order_id}_{next_status}"
        )
    
    # Кнопки смены статуса вручную
    builder.row(
        InlineKeyboardButton(text="🔵 Отправлен", callback_data=f"admin_order_status_{order_id}_shipped"),
        InlineKeyboardButton(text="✅ Завершён", callback_data=f"admin_order_status_{order_id}_completed")
    )
    builder.row(
        InlineKeyboardButton(text="🟡 В обработке", callback_data=f"admin_order_status_{order_id}_processing"),
        InlineKeyboardButton(text="❌ Отменить", callback_data=f"admin_order_status_{order_id}_cancelled")
    )
    
    builder.row(InlineKeyboardButton(text="🔙 К списку", callback_data="admin_orders"))
    
    return builder.as_markup()


def admin_back_kb():
    """Кнопка назад в админ-меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В админ-меню", callback_data="admin_back_menu")]
    ])

# --- ТЕХПОДДЕРЖКА ---

def support_menu_kb():
    """Меню поддержки для пользователя"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Написать в поддержку", callback_data="support_new")
    builder.button(text="❓ Частые вопросы (FAQ)", callback_data="support_faq")
    builder.button(text="🔙 Назад", callback_data="back_to_profile")
    builder.adjust(1)
    return builder.as_markup()


def admin_support_kb(user_id: int, message_id: int):
    """Клавиатура для админа при получении сообщения"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✉️ Ответить",
        callback_data=f"admin_reply_{user_id}_{message_id}"
    )
    builder.button(
        text="⛔ Заблокировать пользователя",
        callback_data=f"admin_ban_{user_id}"
    )
    builder.adjust(1)
    return builder.as_markup()


def faq_kb():
    """Клавиатура FAQ"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🚚 Доставка", callback_data="faq_delivery")
    builder.button(text="💳 Оплата", callback_data="faq_payment")
    builder.button(text="🔄 Возврат и обмен", callback_data="faq_return")
    builder.button(text="📏 Размеры", callback_data="faq_sizes")
    builder.button(text="📞 Контакты", callback_data="faq_contacts")
    builder.button(text="🔙 Назад", callback_data="support_back")
    builder.adjust(2)
    return builder.as_markup()


def support_back_kb():
    """Кнопка назад в поддержке"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В меню поддержки", callback_data="support_back")]
    ])

