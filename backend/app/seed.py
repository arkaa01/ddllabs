from datetime import date, timedelta
from random import Random
from .db import Base, engine, SessionLocal, Category, Customer, Product, Order, OrderItem, ensure_optional_datetime_columns

def seed():
    Base.metadata.create_all(engine)
    ensure_optional_datetime_columns()
    db = SessionLocal()
    if db.query(Customer).count(): db.close(); return
    rnd = Random(42)
    names=["Electronics","Home","Beauty","Sports","Fashion","Grocery","Books","Outdoors"]
    cats=[]
    for n in names:
        c=db.query(Category).filter(Category.name==n).first()
        if not c: c=Category(name=n, description=f"{n} merchandise"); db.add(c); db.flush()
        cats.append(c)
    customers = [Customer(customer_code=f"C{i:04d}", name=f"Customer {i}", email=f"customer{i}@example.com", city=rnd.choice(["Mumbai","Delhi","Bengaluru","Pune","Hyderabad"])) for i in range(1,501)]
    db.add_all(customers); db.flush()
    products = [Product(product_code=f"P{i:03d}", name=f"{cats[i%8].name} Product {i}", category_id=cats[i%8].id, price=round(rnd.uniform(250,25000),2), stock_quantity=rnd.randint(5,200)) for i in range(1,51)]
    db.add_all(products); db.flush()
    start = date.today() - timedelta(days=365)
    for i in range(1,2001):
        d = start + timedelta(days=rnd.randint(0,364))
        o = Order(order_number=f"ORD-{i:05d}", customer_id=rnd.choice(customers).id, order_date=d, status="completed" if rnd.random() > .04 else "cancelled", shipping_amount=round(rnd.choice([0,49,99]),2), discount_amount=round(rnd.uniform(0,300),2), tax_amount=0)
        db.add(o); db.flush()
        for _ in range(rnd.randint(1,3)):
            p = rnd.choice(products); qty = rnd.randint(1,4)
            db.add(OrderItem(order_id=o.id, product_id=p.id, quantity=qty, unit_price=p.price, discount_amount=round(rnd.uniform(0,100),2)))
    db.commit(); db.close()
