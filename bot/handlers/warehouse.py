from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import async_session_maker
from database.models import ProductVariant
from bot.states import EditStockState
from bot.keyboards.keyboards import admin_cancel_kb
from config import ADMIN_ID

warehouse_router = Router()

# === СКЛАДСКОЙ УЧЁТ ===

@warehouse_router.message(F.text == "📊 Склад")
async def admin_warehouse(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    async with async_session_maker() as session:
        variants = await session.scalars(
            select(ProductVariant)
            .options(selectinload(ProductVariant.product))
            .order_by(ProductVariant.stock_quantity.asc())
        )
        variants_list = variants.all()
        
        if not variants_list:
            await message.answer("Нет товаров на складе")
            return
        
        total_items = sum(v.stock_quantity for v in variants_list)
        low_stock = [v for v in variants_list if v.stock_quantity <= 5]
        
        text = (
            f"📊 <b>Складская статистика</b>\n\n"
            f"📦 Всего единиц: <b>{total_items}</b>\n"
            f"👎 Мало на складе (≤5): <b>{len(low_stock)}</b>\n\n"
            f"<b>Остатки по товарам:</b>\n"
        )
        
        builder = InlineKeyboardBuilder()
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

@warehouse_router.callback_query(F.data.startswith("edit_stock_"))
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

@warehouse_router.message(EditStockState.quantity)
async def edit_stock_save(message: types.Message, state: FSMContext):
    try:
        new_quantity = int(message.text)
        if new_quantity < 0: raise ValueError
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
        
        await message.answer(f"✅ Остаток обновлен!\nБыло: {old_qty} → Стало: {new_quantity}")
    
    await state.clear()