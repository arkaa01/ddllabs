from datetime import date, timedelta
from calendar import monthrange
from zoneinfo import ZoneInfo
from sqlalchemy import func, case
from sqlalchemy.orm import Session
from .db import Order, OrderItem, Product, Category, Customer

def revenue_expr():
    return (OrderItem.quantity * OrderItem.unit_price - OrderItem.discount_amount)

def base_query(db: Session, start: date, end: date):
    return db.query(Order, OrderItem, Product, Category).join(OrderItem, Order.id==OrderItem.order_id).join(Product, Product.id==OrderItem.product_id).join(Category, Category.id==Product.category_id).filter(Order.order_date>=start, Order.order_date<=end, Order.status=="completed")

def metrics(db: Session, start: date, end: date):
    rows = base_query(db,start,end).all()
    order_ids = {o.id for o, *_ in rows}
    revenue = sum(float(q.quantity*q.unit_price-q.discount_amount) for _,q,_,_ in rows)
    for oid in order_ids:
        o = next(x[0] for x in rows if x[0].id==oid)
        revenue += float(o.shipping_amount + o.tax_amount - o.discount_amount)
    return {"revenue": round(revenue,2), "orders": len(order_ids), "customers": db.query(Customer).count(), "aov": round(revenue/len(order_ids),2) if order_ids else 0}

def monthly(db: Session, start: date, end: date):
    vals = {}
    for o,q,p,c in base_query(db,start,end).all():
        key=o.order_date.strftime("%Y-%m")
        vals[key]=vals.get(key,0)+float(q.quantity*q.unit_price-q.discount_amount)
    return [{"month": k, "revenue": round(v,2)} for k,v in sorted(vals.items())]

def category_revenue(db: Session, start: date, end: date):
    vals={}
    for o,q,p,c in base_query(db,start,end).all(): vals[c.name]=vals.get(c.name,0)+float(q.quantity*q.unit_price-q.discount_amount)
    return [{"category":k,"revenue":round(v,2)} for k,v in sorted(vals.items(), key=lambda x:x[1], reverse=True)]

def top_products(db: Session, start: date, end: date, limit=10):
    vals={}
    for o,q,p,c in base_query(db,start,end).all():
        item=vals.setdefault(p.id,{"product":p.name,"revenue":0,"quantity":0})
        item["revenue"]+=float(q.quantity*q.unit_price-q.discount_amount); item["quantity"]+=q.quantity
    return [{**x,"revenue":round(x["revenue"],2)} for x in sorted(vals.values(), key=lambda x:x["revenue"], reverse=True)[:limit]]

def top_customers(db: Session, start: date, end: date, limit=10):
    vals={}
    for o,q,p,c in base_query(db,start,end).all():
        item=vals.setdefault(o.customer_id,{"customer":o.customer.name,"revenue":0,"orders":set()}); item["revenue"]+=float(q.quantity*q.unit_price-q.discount_amount); item["orders"].add(o.id)
    return [{"customer":x["customer"],"revenue":round(x["revenue"],2),"orders":len(x["orders"])} for x in sorted(vals.values(),key=lambda x:x["revenue"],reverse=True)[:limit]]

def completed_month_periods(as_of: date | None = None):
    today = as_of or date.today()
    first_current = today.replace(day=1)
    current_end = first_current - timedelta(days=1)
    current_start = current_end.replace(day=1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end.replace(day=1)
    return current_start, current_end, previous_start, previous_end

def _pct(current, previous):
    if previous in (None, 0): return None
    return round((current - previous) / previous * 100, 2)

def decline_analysis(db: Session, start: date | None = None, end: date | None = None):
    # Chat uses completed calendar months. Explicit ranges remain supported for API callers.
    if start is None or end is None:
        current_start, current_end, previous_start, previous_end = completed_month_periods()
    else:
        days=(end-start).days+1; current_start, current_end=start,end; previous_end=start-timedelta(days=1); previous_start=previous_end-timedelta(days=days-1)
    current=metrics(db,current_start,current_end); previous=metrics(db,previous_start,previous_end)
    revenue_difference=round(current["revenue"]-previous["revenue"],2)
    revenue_change_pct=_pct(current["revenue"],previous["revenue"])
    order_change_pct=_pct(current["orders"],previous["orders"])
    aov_change_pct=_pct(current["aov"],previous["aov"])
    current_products={x["product"]:x for x in top_products(db,current_start,current_end,50)}
    previous_products={x["product"]:x for x in top_products(db,previous_start,previous_end,50)}
    product_changes=[]
    for name in sorted(set(current_products)|set(previous_products)):
        cur=current_products.get(name,{"revenue":0,"quantity":0}); old=previous_products.get(name,{"revenue":0,"quantity":0})
        product_changes.append({"product":name,"current_revenue":cur["revenue"],"previous_revenue":old["revenue"],"difference":round(cur["revenue"]-old["revenue"],2),"change_pct":_pct(cur["revenue"],old["revenue"])})
    product_changes.sort(key=lambda x:x["difference"])
    current_categories={x["category"]:x["revenue"] for x in category_revenue(db,current_start,current_end)}
    previous_categories={x["category"]:x["revenue"] for x in category_revenue(db,previous_start,previous_end)}
    category_changes=[{"category":name,"current_revenue":round(current_categories.get(name,0),2),"previous_revenue":round(previous_categories.get(name,0),2),"difference":round(current_categories.get(name,0)-previous_categories.get(name,0),2),"change_pct":_pct(current_categories.get(name,0),previous_categories.get(name,0))} for name in sorted(set(current_categories)|set(previous_categories))]
    category_changes.sort(key=lambda x:x["difference"])
    current_customers=customer_metrics(db,current_start,current_end); previous_customers=customer_metrics(db,previous_start,previous_end)
    if revenue_change_pct is None:
        interpretation="The comparison period has zero revenue, so a percentage change cannot be calculated. Absolute revenue and order values are shown instead."
    elif revenue_change_pct < 0:
        interpretation=f"Revenue decreased {abs(revenue_change_pct)}% versus the previous completed calendar month. The observed change is associated with order volume and basket-value movements; the data does not establish causation."
    elif revenue_change_pct > 0:
        interpretation=f"Revenue increased {revenue_change_pct}% versus the previous completed calendar month. The observed change is associated with order volume and basket-value movements; the data does not establish causation."
    else: interpretation="Revenue was unchanged versus the previous completed calendar month."
    return {"current_period":{"start":current_start.isoformat(),"end":current_end.isoformat(),**current},"previous_period":{"start":previous_start.isoformat(),"end":previous_end.isoformat(),**previous},"revenue_difference":revenue_difference,"revenue_change_pct":revenue_change_pct,"order_change_pct":order_change_pct,"aov_change_pct":aov_change_pct,"order_analysis":{"previous_orders":previous["orders"],"current_orders":current["orders"],"previous_aov":previous["aov"],"current_aov":current["aov"]},"product_analysis":{"declining":product_changes[:10],"growing":list(reversed(product_changes[-10:]))},"category_analysis":category_changes,"customer_analysis":{"previous":previous_customers,"current":current_customers,"repeat_change":current_customers["repeat_customers"]-previous_customers["repeat_customers"],"active_change":current_customers["active_customers"]-previous_customers["active_customers"]},"interpretation":interpretation,"insufficient_data":previous["revenue"]==0 and current["revenue"]==0}

def daily(db: Session, start: date, end: date):
    vals={}
    for o,q,p,c in base_query(db,start,end).all(): vals[o.order_date.isoformat()]=vals.get(o.order_date.isoformat(),0)+float(q.quantity*q.unit_price-q.discount_amount)
    return [{"date":k,"revenue":round(v,2)} for k,v in sorted(vals.items())]

def inactive_customers(db: Session, as_of: date, days: int):
    cutoff=as_of-timedelta(days=days)
    completed={o.customer_id:o.order_date for o in db.query(Order).filter(Order.status=="completed").all()}
    return [{"customer":c.name,"email":c.email,"last_purchase":completed.get(c.id).isoformat() if completed.get(c.id) else None} for c in db.query(Customer).all() if not completed.get(c.id) or completed[c.id] < cutoff]

def customer_metrics(db: Session, start: date, end: date):
    orders={}
    for o,q,p,c in base_query(db,start,end).all(): orders.setdefault(o.customer_id,set()).add(o.id)
    completed=db.query(Order).filter(Order.status=="completed").all(); first={}
    for o in completed: first[o.customer_id]=min(first.get(o.customer_id,o.order_date),o.order_date)
    new=sum(1 for d in first.values() if start<=d<=end)
    lifetime_revenue=0
    for o in completed:
        for item in db.query(OrderItem).filter(OrderItem.order_id==o.id).all(): lifetime_revenue += float(item.quantity*item.unit_price-item.discount_amount)
    total_customers=db.query(Customer).count()
    return {"total_customers":total_customers,"new_customers":new,"repeat_customers":sum(1 for ids in orders.values() if len(ids)>=2),"active_customers":len(orders),"purchase_frequency":round(sum(len(x) for x in orders.values())/len(orders),2) if orders else 0,"average_customer_lifetime_revenue":round(lifetime_revenue/total_customers,2) if total_customers else 0}

def product_metrics(db: Session, start: date, end: date):
    rows=top_products(db,start,end,50)
    total_units=sum(x["quantity"] for x in rows); total_revenue=round(sum(x["revenue"] for x in rows),2); top=rows[0] if rows else None
    return {"total_products":db.query(Product).count(),"total_units_sold":total_units,"total_product_revenue":total_revenue,"average_selling_price":round(total_revenue/total_units,2) if total_units else 0,"top_revenue_product":top,"low_stock_products":db.query(Product).filter(Product.stock_quantity<10).count(),"top_selling":sorted(rows,key=lambda x:x["quantity"],reverse=True)[:10],"highest_revenue":rows,"low_performing":sorted(rows,key=lambda x:x["revenue"])[:10]}

def product_rows(db: Session, start: date, end: date, search: str | None = None, category_id: int | None = None, stock: str | None = None):
    sales={}
    for o,q,p,c in base_query(db,start,end).all():
        item=sales.setdefault(p.id,{"units_sold":0,"revenue":0,"orders":set()}); item["units_sold"]+=q.quantity; item["revenue"]+=float(q.quantity*q.unit_price-q.discount_amount); item["orders"].add(o.id)
    rows=[]
    for p in db.query(Product).all():
        if category_id and p.category_id!=category_id: continue
        if search and search.lower() not in f"{p.name} {p.product_code}".lower(): continue
        if stock=="low" and p.stock_quantity>=10: continue
        if stock=="in_stock" and p.stock_quantity<10: continue
        s=sales.get(p.id,{"units_sold":0,"revenue":0,"orders":set()}); revenue=round(s["revenue"],2); units=s["units_sold"]
        status="low_sales" if units==0 or revenue==0 else ("low_stock" if p.stock_quantity<10 else "performing")
        rows.append({"id":p.id,"product_code":p.product_code,"name":p.name,"category":p.category.name,"category_id":p.category_id,"selling_price":float(p.price),"cost_price":None,"stock_quantity":p.stock_quantity,"units_sold":units,"revenue":revenue,"completed_orders":len(s["orders"]),"average_selling_price":round(revenue/units,2) if units else 0,"performance_status":status})
    return rows

def product_detail(db: Session, product_id: int, start: date, end: date):
    p=db.query(Product).filter(Product.id==product_id).first()
    if not p: return None
    row=next(x for x in product_rows(db,start,end) if x["id"]==product_id)
    trend={}
    for o,q,_,_ in base_query(db,start,end).filter(OrderItem.product_id==product_id).all(): trend[o.order_date.strftime("%Y-%m")]=trend.get(o.order_date.strftime("%Y-%m"),0)+float(q.quantity*q.unit_price-q.discount_amount)
    row["revenue_trend"]=[{"month":k,"revenue":round(v,2)} for k,v in sorted(trend.items())]; return row

def category_rows(db: Session, start: date, end: date, search: str | None = None):
    totals={}
    for o,q,p,c in base_query(db,start,end).all():
        x=totals.setdefault(c.id,{"orders":set(),"units":0,"revenue":0}); x["orders"].add(o.id); x["units"]+=q.quantity; x["revenue"]+=float(q.quantity*q.unit_price-q.discount_amount)
    total_revenue=sum(x["revenue"] for x in totals.values()); rows=[]
    for c in db.query(Category).all():
        if search and search.lower() not in c.name.lower(): continue
        x=totals.get(c.id,{"orders":set(),"units":0,"revenue":0}); products=db.query(Product).filter(Product.category_id==c.id).count(); revenue=round(x["revenue"],2)
        rows.append({"id":c.id,"name":c.name,"product_count":products,"total_orders":len(x["orders"]),"units_sold":x["units"],"revenue":revenue,"contribution_pct":round(revenue/total_revenue*100,2) if total_revenue else 0,"average_selling_price":round(revenue/x["units"],2) if x["units"] else 0})
    for rank,row in enumerate(sorted(rows,key=lambda x:x["revenue"],reverse=True),1): row["performance_rank"]=rank
    return sorted(rows,key=lambda x:x["performance_rank"])

def category_detail(db: Session, category_id: int, start: date, end: date):
    c=db.query(Category).filter(Category.id==category_id).first()
    if not c: return None
    rows=category_rows(db,start,end); row=next(x for x in rows if x["id"]==category_id)
    products=product_rows(db,start,end); products=[x for x in products if x["category_id"]==category_id]
    trend={}
    for o,q,p,_ in base_query(db,start,end).filter(Product.category_id==category_id).all(): trend[o.order_date.strftime("%Y-%m")]=trend.get(o.order_date.strftime("%Y-%m"),0)+float(q.quantity*q.unit_price-q.discount_amount)
    return {"category":{"id":c.id,"name":c.name,"description":c.description},**row,"products":products,"top_products":sorted(products,key=lambda x:x["revenue"],reverse=True)[:10],"monthly_revenue":[{"month":k,"revenue":round(v,2)} for k,v in sorted(trend.items())]}

def comparison(db: Session, start: date, end: date):
    days=(end-start).days+1; prev_end=start-timedelta(days=1); prev_start=prev_end-timedelta(days=days-1); cur=metrics(db,start,end); prev=metrics(db,prev_start,prev_end)
    def pct(a,b): return round((a-b)/b*100,2) if b else None
    return {"current":cur,"previous":prev,"changes":{"revenue_pct":pct(cur["revenue"],prev["revenue"]),"orders_pct":pct(cur["orders"],prev["orders"]),"aov_pct":pct(cur["aov"],prev["aov"])},"previous_period":{"start":prev_start,"end":prev_end}}

def insights(db: Session, start: date, end: date):
    c=comparison(db,start,end); out=[]
    change=c["changes"]["revenue_pct"]
    if change is not None: out.append({"title":"Revenue movement","description":f"Revenue changed {change}% versus the previous equivalent period.","metric":"revenue","value":c["current"]["revenue"],"comparison_value":c["previous"]["revenue"],"period":{"start":start,"end":end},"evidence":c["changes"],"suggested_action":"Review category and order-volume changes."})
    cats=category_revenue(db,start,end)
    if cats: out.append({"title":"Leading category","description":f"{cats[0]['category']} generated the most revenue.","metric":"category_revenue","value":cats[0]["revenue"],"comparison_value":None,"period":{"start":start,"end":end},"evidence":cats[:3],"suggested_action":"Protect availability and test ways to increase basket size."})
    return out

def customer_rows(db: Session, start: date | None = None, end: date | None = None, search: str | None = None, status: str | None = None, customer_type: str | None = None):
    completed=db.query(Order).filter(Order.status=="completed").all()
    by_customer={}
    for o in completed:
        if start and o.order_date < start: continue
        if end and o.order_date > end: continue
        by_customer.setdefault(o.customer_id,[]).append(o)
    now=date.today(); cutoff=now-timedelta(days=90); rows=[]
    for c in db.query(Customer).all():
        orders=by_customer.get(c.id,[]); all_orders=[o for o in completed if o.customer_id==c.id]
        first=min((o.order_date for o in all_orders),default=None); last=max((o.order_date for o in all_orders),default=None)
        revenue=0
        for o in orders:
            for item in db.query(OrderItem).filter(OrderItem.order_id==o.id).all(): revenue += float(item.quantity*item.unit_price-item.discount_amount)
        ctype="repeat" if len(all_orders)>=2 else ("new" if first and start and start<=first<=(end or now) else "one-time")
        cstatus="active" if last and last>=cutoff else "inactive"
        row={"id":c.id,"customer_code":c.customer_code,"name":c.name,"email":c.email,"city":c.city,"total_orders":len(orders),"total_revenue":round(revenue,2),"last_purchase_date":last.isoformat() if last else None,"first_purchase_date":first.isoformat() if first else None,"customer_type":ctype,"status":cstatus,"purchase_frequency":round(len(all_orders)/max((last-first).days/30,1),2) if first and last else len(all_orders)}
        if search and search.lower() not in f"{c.name} {c.email} {c.customer_code}".lower(): continue
        if status and status != cstatus: continue
        if customer_type and customer_type != ctype: continue
        rows.append(row)
    return rows

def customer_detail(db: Session, customer_id: int):
    c=db.query(Customer).filter(Customer.id==customer_id).first()
    if not c: return None
    orders=db.query(Order).filter(Order.customer_id==customer_id,Order.status=="completed").order_by(Order.order_date.desc()).all()
    history=[]; products=[]; revenue=0
    for o in orders:
        order_revenue=0
        for item in db.query(OrderItem).filter(OrderItem.order_id==o.id).all():
            value=float(item.quantity*item.unit_price-item.discount_amount); revenue+=value; order_revenue+=value; products.append({"product_id":item.product_id,"quantity":item.quantity,"revenue":round(value,2)})
        history.append({"order_number":o.order_number,"order_date":o.order_date.isoformat(),"revenue":round(order_revenue,2)})
    dates=[o.order_date for o in orders]
    return {"profile":{"id":c.id,"customer_code":c.customer_code,"name":c.name,"city":c.city},"total_revenue":round(revenue,2),"total_orders":len(orders),"average_order_value":round(revenue/len(orders),2) if orders else 0,"first_purchase":min(dates).isoformat() if dates else None,"last_purchase":max(dates).isoformat() if dates else None,"purchase_history":history,"purchased_products":products}

def customer_trends(db: Session, start: date, end: date):
    completed=db.query(Order).filter(Order.status=="completed",Order.order_date>=start,Order.order_date<=end).all(); months={}
    for o in completed:
        key=o.order_date.strftime("%Y-%m"); months.setdefault(key,set()).add(o.customer_id)
    return [{"month":k,"active_customers":len(v),"new_customers":sum(1 for cid in v if min(x.order_date for x in completed if x.customer_id==cid)==date.fromisoformat(k+'-01'))} for k,v in sorted(months.items())]
