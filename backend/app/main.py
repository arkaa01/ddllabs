from datetime import date, timedelta
from typing import Annotated
from fastapi import FastAPI, Depends, Query, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
import csv, io, time, uuid, httpx
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db, Customer, Product, Order, Category, ImportBatch
from .seed import seed
from .analytics import metrics, monthly, daily, category_revenue, top_products, top_customers, decline_analysis, inactive_customers, customer_metrics, product_metrics, comparison, insights, customer_rows, customer_detail, customer_trends, product_rows, product_detail, category_rows, category_detail
from .ingestion import import_csv, batch_result

app=FastAPI(title="InsightIQ API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url,"http://localhost:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
@app.on_event("startup")
def startup(): seed()

def range_params(start: date|None, end: date|None):
    e=end or date.today(); s=start or (e-timedelta(days=365))
    if s>e: raise HTTPException(400,"start_date must be before end_date")
    return s,e

@app.get("/api/v1/health")
def health(): return {"status":"ok","service":"insightiq"}
@app.get("/api/v1/health/database")
def health_db(db:Session=Depends(get_db)): return {"status":"ok","customers":db.query(Customer).count()}

@app.get("/api/v1/dashboard/overview")
def overview(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return {"metrics":metrics(db,s,e),"monthly_revenue":monthly(db,s,e),"category_revenue":category_revenue(db,s,e),"top_products":top_products(db,s,e),"period":{"start":s,"end":e}}
@app.get("/api/v1/sales/metrics")
def sales_metrics(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return metrics(db,s,e)
@app.get("/api/v1/sales/monthly-revenue")
def sales_monthly(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return monthly(db,s,e)
@app.get("/api/v1/sales/category-revenue")
def sales_category(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return category_revenue(db,s,e)
@app.get("/api/v1/products/top")
def products_top(limit:int=Query(10,ge=1,le=50),start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return top_products(db,s,e,limit)
@app.get("/api/v1/customers/top")
def customers_top(limit:int=Query(10,ge=1,le=50),start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return top_customers(db,s,e,limit)
@app.get("/api/v1/customers/metrics")
def customers_metrics(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return customer_metrics(db,s,e)

@app.get("/api/v1/sales/daily-revenue")
def sales_daily(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return daily(db,s,e)
@app.get("/api/v1/sales/comparison")
def sales_comparison(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return comparison(db,s,e)
@app.get("/api/v1/customers/inactive")
def customers_inactive(days:int=Query(settings.inactive_customer_days,ge=1,le=3650),db:Session=Depends(get_db)):
    return inactive_customers(db,date.today(),days)
@app.get("/api/v1/products/metrics")
def products_metrics(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return product_metrics(db,s,e)
@app.get("/api/v1/products/low-performing")
def products_low(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return product_metrics(db,s,e)["low_performing"]
@app.get("/api/v1/products")
def products(page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),search:str|None=None,category_id:int|None=None,stock:str|None=None,start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date) if start_date or end_date else (date.min,date.max); all_rows=product_rows(db,s,e,search,category_id,stock); return {"items":all_rows[(page-1)*page_size:page*page_size],"page":page,"page_size":page_size,"total":len(all_rows)}
@app.get("/api/v1/products/{product_id}")
def product_by_id(product_id:int,start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date) if start_date or end_date else (date.min,date.max); result=product_detail(db,product_id,s,e)
    if not result: raise HTTPException(404,"Product not found")
    return result
@app.get("/api/v1/customers")
def customers(page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),search:str|None=None,status:str|None=None,customer_type:str|None=None,start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date) if start_date or end_date else (None,None); all_rows=customer_rows(db,s,e,search,status,customer_type); return {"items":all_rows[(page-1)*page_size:page*page_size],"page":page,"page_size":page_size,"total":len(all_rows)}
@app.get("/api/v1/customers/trends")
def customer_growth(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return customer_trends(db,s,e)
@app.get("/api/v1/customers/{customer_id}")
def customer_by_id(customer_id:int,db:Session=Depends(get_db)):
    result=customer_detail(db,customer_id)
    if not result: raise HTTPException(404,"Customer not found")
    return result
@app.get("/api/v1/categories/metrics")
def categories_metrics(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); rows=category_rows(db,s,e); total_revenue=sum(x["revenue"] for x in rows); units=sum(x["units_sold"] for x in rows); return {"total_categories":db.query(Category).count(),"total_products":db.query(Product).count(),"total_category_revenue":round(total_revenue,2),"total_units_sold":units,"best_category":rows[0] if rows else None,"lowest_category":rows[-1] if rows else None,"categories":rows}
@app.get("/api/v1/categories")
def categories(page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),search:str|None=None,start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date) if start_date or end_date else (date.min,date.max); rows=category_rows(db,s,e,search); return {"items":rows[(page-1)*page_size:page*page_size],"page":page,"page_size":page_size,"total":len(rows)}
@app.get("/api/v1/categories/revenue")
def categories_revenue(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return category_rows(db,s,e)
@app.get("/api/v1/categories/{category_id}")
def category_by_id(category_id:int,start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date) if start_date or end_date else (date.min,date.max); result=category_detail(db,category_id,s,e)
    if not result: raise HTTPException(404,"Category not found")
    return result
@app.get("/api/v1/dashboard/trends")
def dashboard_trends(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return {"daily_revenue":daily(db,s,e),"monthly_revenue":monthly(db,s,e),"comparison":comparison(db,s,e)}

@app.get("/api/v1/insights")
def get_insights(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return insights(db,s,e)
@app.post("/api/v1/insights/generate")
def generate_insights(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return {"insights":insights(db,s,e),"generated_by":"deterministic analytics"}

def report_csv(rows, filename):
    buf=io.StringIO(); fields=list(rows[0].keys()) if rows else ["message"]; writer=csv.DictWriter(buf,fieldnames=fields); writer.writeheader(); writer.writerows(rows or [{"message":"No data for selected period"}]); buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]),media_type="text/csv",headers={"Content-Disposition":f"attachment; filename={filename}"})
@app.get("/api/v1/reports/sales")
def report_sales(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return report_csv(monthly(db,s,e),"sales-report.csv")
@app.get("/api/v1/reports/products")
def report_products(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return report_csv(top_products(db,s,e,50),"products-report.csv")
@app.get("/api/v1/reports/customers")
def report_customers(start_date:date|None=None,end_date:date|None=None,db:Session=Depends(get_db)):
    s,e=range_params(start_date,end_date); return report_csv(top_customers(db,s,e,50),"customers-report.csv")

class ChatRequest(BaseModel): message:str
TOOLS=[
 {"type":"function","function":{"name":"get_sales_metrics","description":"Get verified sales metrics","parameters":{"type":"object","properties":{"start_date":{"type":"string"},"end_date":{"type":"string"}},"required":[]}}},
 {"type":"function","function":{"name":"get_top_products","description":"Get top products by verified revenue","parameters":{"type":"object","properties":{"limit":{"type":"integer"}},"required":[]}}},
 {"type":"function","function":{"name":"get_monthly_revenue","description":"Get verified monthly revenue","parameters":{"type":"object","properties":{},"required":[]}}}
]
def openrouter_chat(question:str):
    if not (settings.openrouter_api_key and settings.llm_model): return None
    payload={"model":settings.llm_model,"messages":[{"role":"system","content":"You are an analytics router. Use a tool for numerical business questions. Never invent figures."},{"role":"user","content":question}],"tools":TOOLS,"tool_choice":"auto"}
    try:
        with httpx.Client(timeout=30) as client:
            res=client.post(f"{settings.llm_base_url.rstrip('/')}/chat/completions",headers={"Authorization":f"Bearer {settings.openrouter_api_key}","Content-Type":"application/json"},json=payload)
            res.raise_for_status(); choice=res.json()["choices"][0]["message"]
            return choice
    except Exception as exc:
        raise HTTPException(502,"LLM provider unavailable") from exc

@app.post("/api/v1/ai/chat")
def chat(req:ChatRequest,db:Session=Depends(get_db)):
    provider_message=openrouter_chat(req.message)
    text=req.message.lower().strip(); today=date.today(); s=today-timedelta(days=365); e=today; execution=[]; data=None; intent="unsupported"
    if provider_message and provider_message.get("tool_calls"):
        call=provider_message["tool_calls"][0]; intent=call["function"]["name"]; args=call["function"].get("arguments") or "{}"
        if isinstance(args,str):
            import json
            try: args=json.loads(args)
            except json.JSONDecodeError: raise HTTPException(502,"LLM returned invalid tool arguments")
        started=time.perf_counter()
        if intent=="get_sales_metrics": data={"type":"metrics","metrics":metrics(db,s,e)}
        elif intent=="get_top_products": data={"type":"table","columns":["product","revenue","quantity"],"rows":top_products(db,s,e,int(args.get("limit",5)))}
        elif intent=="get_monthly_revenue": data={"type":"chart","chart_type":"line","title":"Monthly Revenue","x_key":"month","series":[{"data_key":"revenue","label":"Revenue"}],"data":monthly(db,s,e)}
        else: raise HTTPException(400,"Model selected an unregistered tool")
        execution=[{"tool":intent,"status":"success","duration_ms":round((time.perf_counter()-started)*1000)}]
        return {"success":True,"conversation_id":str(uuid.uuid4()),"intent":intent,"message":{"role":"assistant","content":"The requested result was calculated from verified database records."},"tool_execution":execution,"data":data,"chart":data if data and data.get("type")=="chart" else None,"insights":[],"metadata":{"source":"database","generated_at":date.today().isoformat(),"llm_configured":True,"llm_used":True}}
    if "top" in text and "product" in text:
        intent="top_products"; data={"type":"table","columns":["product","revenue","quantity"],"rows":top_products(db,s,e,5)}; content="Here are the top 5 products by revenue from completed orders."
    elif "monthly" in text and "revenue" in text:
        intent="monthly_revenue"; rows=monthly(db,s,e); data={"type":"chart","chart_type":"line","title":"Monthly Revenue","x_key":"month","series":[{"data_key":"revenue","label":"Revenue"}],"data":rows}; content="Monthly revenue is calculated from completed orders in the selected demo period."
    elif "category" in text:
        intent="category_revenue"; data={"type":"table","columns":["category","revenue"],"rows":category_revenue(db,s,e)}; content="Category revenue is ranked below using verified order-item calculations."
    elif "decline" in text or "why did revenue" in text:
        intent="revenue_decline"; result=decline_analysis(db); data={"type":"analysis","result":result}; change=result["revenue_change_pct"]; cur=result["current_period"]; prev=result["previous_period"]; oa=result["order_analysis"]; drops=result["product_analysis"]["declining"][:3]; cats=result["category_analysis"][:3]; content="\n".join(["Revenue Comparison",f"Current completed month ({cur['start']} to {cur['end']}): {cur['revenue']:,.2f}",f"Previous completed month ({prev['start']} to {prev['end']}): {prev['revenue']:,.2f}",f"Difference: {result['revenue_difference']:,.2f}",f"Percentage change: {change if change is not None else 'not calculable because previous revenue is zero'}", "", "Order Analysis",f"Orders: {oa['previous_orders']} → {oa['current_orders']} ({result['order_change_pct'] if result['order_change_pct'] is not None else 'not calculable'}%)",f"Average order value: {oa['previous_aov']:,.2f} → {oa['current_aov']:,.2f} ({result['aov_change_pct'] if result['aov_change_pct'] is not None else 'not calculable'}%)", "", "Observed product changes",* [f"{x['product']}: {x['difference']:,.2f}" for x in drops], "", "Observed category changes",* [f"{x['category']}: {x['difference']:,.2f}" for x in cats], "", "Business interpretation",result["interpretation"]])
    elif "revenue" in text or "sales" in text:
        intent="sales_metrics"; m=metrics(db,s,e); data={"type":"metrics","metrics":m}; content=f"Completed-order revenue is {m['revenue']:,.2f} across {m['orders']:,} orders, with an average order value of {m['aov']:,.2f}."
    else: content="I can answer questions about revenue, monthly trends, categories, top products, customers, and revenue declines using the connected database."
    if intent!="unsupported": execution=[{"tool":intent,"status":"success","duration_ms":1}]
    return {"success":True,"conversation_id":str(uuid.uuid4()),"intent":intent,"message":{"role":"assistant","content":content},"tool_execution":execution,"data":data,"chart":data if data and data.get("type")=="chart" else None,"insights":[],"metadata":{"source":"database","generated_at":date.today().isoformat(),"llm_configured":bool(settings.openrouter_api_key and settings.llm_model),"llm_used":False}}

@app.post("/api/v1/data/upload")
async def upload(dataset:str=Form(...),file:UploadFile=File(...),db:Session=Depends(get_db)):
    if not file.filename.lower().endswith(".csv"): raise HTTPException(400,"Only CSV files are supported")
    try: return import_csv(db,dataset,file.filename,await file.read())
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
@app.get("/api/v1/data/imports")
def imports(db:Session=Depends(get_db)):
    return [batch_result(x) for x in db.query(ImportBatch).order_by(ImportBatch.created_at.desc()).all()]
@app.get("/api/v1/data/imports/{import_id}")
def import_detail(import_id:int,db:Session=Depends(get_db)):
    batch=db.query(ImportBatch).filter(ImportBatch.id==import_id).first()
    if not batch: raise HTTPException(404,"Import not found")
    return batch_result(batch)
