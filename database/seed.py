# database/seed.py
from sqlalchemy import select
from database.database import async_session_maker
from database.models import Category, Product, ProductVariant, User
import random
import string

async def seed_database():
    """Заполняет БД начальными данными"""
    
    async with async_session_maker() as session:
        # Проверяем, есть ли уже категории
        existing_cats = await session.scalar(select(Category).limit(1))
        if existing_cats:
            print("⚠️ БД уже заполнена, пропускаем сид...")
            return
        
        print("🌱 Заполняем БД тестовыми данными...")
        
        # 1. КАТЕГОРИИ
        categories_data = [
            "👕 Футболки",
            "👖 Джинсы",
            "🧥 Куртки",
            "👗 Платья",
            "👟 Кроссовки"
        ]
        
        categories = []
        for cat_name in categories_data:
            cat = Category(name=cat_name)
            session.add(cat)
            categories.append(cat)
        
        await session.flush()
        
        # 2. ТОВАРЫ
        products_data = [
            # Футболки
            {
                "name": "Базовая хлопковая футболка",
                "description": "Удобная футболка из 100% хлопка. Отличный выбор на каждый день.",
                "category": categories[0],
                "variants": [
                    ("S", "Белый", 1200, 15),
                    ("M", "Белый", 1200, 20),
                    ("L", "Белый", 1200, 18),
                    ("XL", "Белый", 1200, 10),
                    ("S", "Черный", 1200, 12),
                    ("M", "Черный", 1200, 25),
                    ("L", "Черный", 1200, 15),
                ]
            },
            {
                "name": "Стильная поло",
                "description": "Классическая поло с воротником. Для офиса и прогулки.",
                "category": categories[0],
                "variants": [
                    ("M", "Синий", 2500, 8),
                    ("L", "Синий", 2500, 10),
                    ("XL", "Синий", 2500, 5),
                ]
            },
            # Джинсы
            {
                "name": "Классические джинсы",
                "description": "Прямые джинсы классического кроя. Качественный деним.",
                "category": categories[1],
                "variants": [
                    ("30", "Синий", 4500, 10),
                    ("32", "Синий", 4500, 15),
                    ("34", "Синий", 4500, 12),
                    ("36", "Синий", 4500, 8),
                ]
            },
            {
                "name": "Скини джинсы",
                "description": "Узкие джинсы-скини. Современный молодежный стиль.",
                "category": categories[1],
                "variants": [
                    ("28", "Черный", 3800, 7),
                    ("30", "Черный", 3800, 10),
                    ("32", "Черный", 3800, 8),
                ]
            },
            # Куртки
            {
                "name": "Зимняя пуховик",
                "description": "Теплый пуховик с капюшоном. До -30°C.",
                "category": categories[2],
                "variants": [
                    ("S", "Черный", 8500, 5),
                    ("M", "Черный", 8500, 8),
                    ("L", "Черный", 8500, 6),
                    ("XL", "Черный", 8500, 4),
                    ("M", "Хаки", 8800, 3),
                ]
            },
            {
                "name": "Ветровка",
                "description": "Легкая ветровка для межсезонья. Водоотталкивающая ткань.",
                "category": categories[2],
                "variants": [
                    ("M", "Белый", 3200, 12),
                    ("L", "Белый", 3200, 10),
                    ("XL", "Белый", 3200, 8),
                ]
            },
            # Платья
            {
                "name": "Летнее платье",
                "description": "Легкое платье для летних дней. Воздушный крой.",
                "category": categories[3],
                "variants": [
                    ("XS", "Цветочек", 2800, 6),
                    ("S", "Цветочек", 2800, 8),
                    ("M", "Цветочек", 2800, 10),
                    ("L", "Цветочек", 2800, 5),
                ]
            },
            # Кроссовки
            {
                "name": "Универсальные кроссовки",
                "description": "Удобные кроссовки для спорта и повседневной носки.",
                "category": categories[4],
                "variants": [
                    ("40", "Белый", 5500, 10),
                    ("41", "Белый", 5500, 12),
                    ("42", "Белый", 5500, 15),
                    ("43", "Белый", 5500, 10),
                    ("44", "Белый", 5500, 8),
                    ("42", "Черный", 5200, 6),
                ]
            },
        ]
        
        # Создаем товары и варианты
        for prod_data in products_data:
            product = Product(
                name=prod_data["name"],
                description=prod_data["description"],
                category_id=prod_data["category"].id,
                main_photo_id=None  # Фото можно добавить позже через админку
            )
            session.add(product)
            await session.flush()
            
            # Добавляем варианты
            for size, color, price, stock in prod_data["variants"]:
                variant = ProductVariant(
                    product_id=product.id,
                    size=size,
                    color=color,
                    price=price,
                    stock_quantity=stock
                )
                session.add(variant)
        
        await session.commit()
        print("✅ БД успешно заполнена!")
        print(f"   - Категорий: {len(categories_data)}")
        print(f"   - Товаров: {len(products_data)}")
