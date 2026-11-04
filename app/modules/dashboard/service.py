from app.modules.users import service as users
from app.modules.products import service as products
from app.modules.orders import service as orders

def stats(db):
    order_stats=orders.stats(db)
    return {'totals':{'users':users.count(db),'products':products.count_products(db),'categories':products.count_categories(db),'orders':order_stats['orders']},**{k:v for k,v in order_stats.items() if k!='orders'}}
