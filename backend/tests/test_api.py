from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal, Customer
from app.ingestion import import_csv

client=TestClient(app)
client.__enter__()
def test_health():
    assert client.get('/api/v1/health').json()['status']=='ok'
def test_overview_has_real_shapes():
    r=client.get('/api/v1/dashboard/overview'); assert r.status_code==200; assert 'metrics' in r.json()
def test_chat_is_controlled():
    r=client.post('/api/v1/ai/chat',json={'message':'show top 5 products by revenue'}).json(); assert r['intent']=='top_products'; assert r['data']['rows']

def test_customer_iso_datetime_is_persisted():
    before=SessionLocal().query(Customer).count()
    db=SessionLocal(); result=import_csv(db,'customers','customers.csv',b'customer_code,name,email,city,created_at\nTEST-ISO,Test User,test-iso@example.com,Delhi,2026-08-27T00:00:00\n'); row=db.query(Customer).filter(Customer.customer_code=='TEST-ISO').one(); assert result['imported_rows']==1; assert row.created_at.year==2026; assert db.query(Customer).count()==before+1; db.close()

def test_invalid_datetime_is_rejected_without_sql_payload():
    db=SessionLocal(); result=import_csv(db,'customers','bad.csv',b'customer_code,name,email,city,created_at\nTEST-BAD,Bad User,test-bad@example.com,Delhi,not-a-date\n'); assert result['status']=='rejected'; assert result['rejected_rows']==1; assert result['errors'][0]['field']=='created_at'; db.close()

def test_revenue_decline_uses_completed_calendar_months():
    result=client.post('/api/v1/ai/chat',json={'message':'Why did revenue decline last month?'}).json(); analysis=result['data']['result']; assert result['intent']=='revenue_decline'; assert analysis['current_period']['start'].endswith('-01'); assert 'not calculable' not in result['message']['content'] or analysis['previous_period']['revenue']==0

def test_product_analytics_and_invalid_id():
    metrics_response=client.get('/api/v1/products/metrics').json(); assert metrics_response['total_products']==50; assert metrics_response['total_units_sold']>0
    listing=client.get('/api/v1/products?page=1&page_size=5&stock=low').json(); assert listing['page_size']==5
    assert client.get('/api/v1/products/1').status_code==200; assert client.get('/api/v1/products/999999').status_code==404

def test_category_analytics_and_invalid_id():
    metrics_response=client.get('/api/v1/categories/metrics').json(); assert metrics_response['total_categories']==8; assert metrics_response['total_category_revenue']>0; assert metrics_response['best_category']['performance_rank']==1
    assert client.get('/api/v1/categories?page=1&page_size=2').json()['total']==8; assert client.get('/api/v1/categories/1').status_code==200; assert client.get('/api/v1/categories/999999').status_code==404
