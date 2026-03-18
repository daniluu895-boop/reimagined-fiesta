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