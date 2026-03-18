from aiogram.fsm.state import State, StatesGroup

class AddProductState(StatesGroup):
    name = State()
    description = State()
    category = State()
    photo = State()
    variants = State()
    confirm = State()

class OrderState(StatesGroup):
    phone = State()
    address = State()
    promo = State()
    confirm = State()

class ProfileState(StatesGroup):
    phone = State()
    address = State()

class SupportState(StatesGroup):
    user_message = State()
    admin_reply = State() 
    user_reply = State()

class EditStockState(StatesGroup):
    quantity = State()

class BroadcastState(StatesGroup):
    text = State()
    confirm = State()

class PromoState(StatesGroup):
    type = State()
    value = State()
    description = State()  # Состояние для текста от админа
    confirm = State()

class AdminReplyState(StatesGroup):
    text = State()