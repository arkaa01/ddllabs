import io, json
from datetime import datetime
import pandas as pd
from sqlalchemy.orm import Session
from .db import Category, Product, Customer, Order, OrderItem, ImportBatch

DATASETS = {"categories": Category, "products": Product, "customers": Customer, "orders": Order, "order_items": OrderItem}
REQUIRED = {
    "categories": ["name"],
    "products": ["product_code", "name", "category_id", "price"],
    "customers": ["customer_code", "name", "email"],
    "orders": ["order_number", "customer_id", "order_date", "status"],
    "order_items": ["order_id", "product_id", "quantity", "unit_price"],
}

def import_csv(db: Session, dataset: str, filename: str, content: bytes) -> dict:
    if dataset not in DATASETS: raise ValueError("Unsupported dataset")
    if len(content) > 10 * 1024 * 1024: raise ValueError("CSV exceeds 10MB limit")
    try: frame = pd.read_csv(io.BytesIO(content))
    except Exception as exc: raise ValueError(f"Could not parse CSV: {exc}") from exc
    errors=[]; missing=[c for c in REQUIRED[dataset] if c not in frame.columns]
    if missing: raise ValueError(f"Missing required columns: {', '.join(missing)}")
    duplicate_rows=int(frame.duplicated().sum())
    frame=frame.drop_duplicates().copy()
    for col in REQUIRED[dataset]:
        nulls=frame[col].isna()
        if nulls.any(): errors.extend([{"row":int(i)+2,"field":col,"error":"required value missing"} for i in frame.index[nulls][:100]])
    date_columns={"customers":["created_at"],"products":["created_at"],"orders":["order_date","created_at"],"order_items":["created_at"]}.get(dataset,[])
    date_invalid_indices=set()
    for col in date_columns:
        if col not in frame: continue
        original=frame[col].copy()
        parsed=pd.to_datetime(original, errors="coerce", utc=True)
        invalid=parsed.isna() & original.notna() & original.astype(str).str.strip().ne("")
        date_invalid_indices.update(frame.index[invalid].tolist())
        errors.extend([{"row":int(i)+2,"field":col,"error":"invalid datetime value"} for i in frame.index[invalid][:100]])
        if col == "order_date":
            frame[col]=parsed.dt.date
        else:
            frame[col]=parsed.dt.tz_localize(None).apply(lambda value:value.to_pydatetime() if pd.notna(value) else None)
    for col in ["price","unit_price","quantity","discount_amount","shipping_amount","tax_amount","customer_id","product_id","order_id","category_id"]:
        if col in frame: frame[col]=pd.to_numeric(frame[col], errors="coerce")
    invalid=frame[frame[REQUIRED[dataset]].isna().any(axis=1) | frame.index.isin(date_invalid_indices)]
    batch=ImportBatch(filename=filename,dataset=dataset,total_rows=len(frame)+duplicate_rows,duplicate_rows=duplicate_rows)
    db.add(batch)
    try:
        if len(invalid):
            batch.errors_json=json.dumps(errors); batch.rejected_rows=len(invalid); batch.status="rejected"; db.commit()
            return batch_result(batch)
        records=frame.where(pd.notna(frame), None).to_dict(orient="records")
        unique_fields={"categories":"name","products":"product_code","customers":"customer_code","orders":"order_number"}
        unique_field="id" if "id" in frame.columns else unique_fields.get(dataset)
        existing=set()
        if unique_field:
            model=DATASETS[dataset]
            existing={getattr(row,unique_field) for row in db.query(model).all()} if unique_field != "id" else {row.id for row in db.query(model).all()}
        fresh=[]
        for row in records:
            if unique_field and row.get(unique_field) in existing:
                duplicate_rows += 1
            else:
                fresh.append(row)
                if unique_field: existing.add(row.get(unique_field))
        records=fresh
        batch.duplicate_rows=duplicate_rows
        allowed={"categories":{"id","name","description"},"products":{"id","product_code","name","category_id","price","stock_quantity","created_at"},"customers":{"id","customer_code","name","email","city","created_at"},"orders":{"id","order_number","customer_id","order_date","status","shipping_amount","discount_amount","tax_amount","created_at"},"order_items":{"id","order_id","product_id","quantity","unit_price","discount_amount","created_at"}}[dataset]
        for row in records:
            db.add(DATASETS[dataset](**{k:v for k,v in row.items() if k in allowed}))
        db.flush(); batch.imported_rows=len(records); batch.status="imported"; db.commit()
    except Exception as exc:
        db.rollback(); raise ValueError("Import failed due to database validation. Check required IDs and duplicate keys.") from exc
    return batch_result(batch)

def batch_result(batch):
    return {"import_id":batch.id,"dataset":batch.dataset,"filename":batch.filename,"status":batch.status,"total_rows":batch.total_rows,"imported_rows":batch.imported_rows,"rejected_rows":batch.rejected_rows,"duplicate_rows":batch.duplicate_rows,"errors":json.loads(batch.errors_json or "[]")}
