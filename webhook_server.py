import uvicorn
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from datetime import datetime
import sqlite3
import logging
import json
from models import ArkhamPayload, InflowEvent, SkippedEvent
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI()
# Database setup
DB_FILE = "inflows.db"
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=WAL;')
    c.execute('''
        CREATE TABLE IF NOT EXISTS inflows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            currency TEXT,
            amount REAL,
            amount_usd REAL,
            destination TEXT,
            transaction_hash TEXT,
            raw_data TEXT
        )
    ''')
    # Create Skipped Inflows Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS skipped_inflows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME,
            reason TEXT,
            raw_data TEXT
        )
    ''')
    conn.commit()
    conn.close()
init_db()
def save_skipped_event(skipped: SkippedEvent, conn=None):
    """
    Saves a SkippedEvent object to the database.
    """
    should_close = False
    try:
        if conn is None:
            conn = sqlite3.connect(DB_FILE, timeout=30.0)
            should_close = True
            
        c = conn.cursor()
        c.execute('''
            INSERT INTO skipped_inflows (timestamp, reason, raw_data)
            VALUES (?, ?, ?)
        ''', (skipped.timestamp, skipped.reason, skipped.raw_data))
        conn.commit()
        
    except Exception as e:
        logger.error(f"Error saving skipped event: {e}")
    finally:
        if should_close and conn:
            conn.close()
def save_inflow_event(inflow: InflowEvent, conn=None):
    """
    Saves an InflowEvent object to the database.
    """
    should_close = False
    try:
        if conn is None:
            conn = sqlite3.connect(DB_FILE, timeout=30.0)
            should_close = True
            
        c = conn.cursor()
        c.execute('''
            INSERT INTO inflows (timestamp, currency, amount, amount_usd, destination, transaction_hash, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (inflow.timestamp, inflow.currency, inflow.amount, inflow.amount_usd, inflow.destination, inflow.transaction_hash, inflow.raw_data))
        conn.commit()
        
        logger.info(f"Saved Inflow: {inflow.currency} ({inflow.amount_usd} USD) -> {inflow.destination}")
    except Exception as e:
        error_msg = f"DB Insert Failed: {e}"
        logger.error(error_msg)
        
        # Rollback the failed transaction so we can use the connection to save the skipped event
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
                
        # Try to save skipped event using SAME connection to respect lock ownership
        save_skipped_event(SkippedEvent(
            timestamp=datetime.utcnow(),
            reason=error_msg,
            raw_data=inflow.raw_data
        ), conn=conn)
    finally:
        if should_close and conn:
            conn.close()
def process_event(payload: dict):
    """
    Parses Arkham webhook payload based on 'alertName'.
    Handles both single 'transfer' and batch 'transfers'.
    Uses a single DB connection for the entire batch.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE, timeout=30.0)
        
        alert_name = payload.get('alertName', '')
        
        # 1. Determine Currency based on Alert Name
        name_lower = alert_name.lower()
        if name_lower.startswith("btc"):
            currency = 'BTC'
        else:
            reason = f"Alert '{alert_name}' does not match 'BTC_inFlow'"
            logger.info(f"Skipping: {reason}")
            save_skipped_event(SkippedEvent(
                timestamp=datetime.utcnow(),
                reason=reason,
                raw_data=json.dumps(payload)
            ), conn=conn)
            return None
        # 2. Determine Items to Process (Batch vs Single)
        items_to_process = []
        if 'transfers' in payload and isinstance(payload['transfers'], list):
            items_to_process = payload['transfers']
            logger.info(f"Processing BATCH of {len(items_to_process)} transfers for {alert_name}")
        else:
            # Single transfer or flat payload
            items_to_process = [payload.get('transfer') or payload]

        # 3. Iterate and Save
        for i, event_data in enumerate(items_to_process):
            try:
                # CRITICAL: Inject alertName into the event data so it is saved in raw_data
                event_data['alertName'] = alert_name
                
                tx_ref = event_data.get('txid') or event_data.get('transactionHash', 'N/A')
                logger.info(f" -> Processing Item {i+1}/{len(items_to_process)}: Tx={tx_ref}")
                
                # -- Amount Extraction --
                amount_usd = event_data.get('historicalUSD')
                if amount_usd is None:
                    amount_usd = event_data.get('valueUSD')
                    
                if amount_usd is None:
                     unit_val = event_data.get('unitValue')
                     token_amt = event_data.get('toValue') or event_data.get('value')
                     if unit_val and token_amt:
                         try:
                             amount_usd = float(unit_val) * float(token_amt)
                         except (ValueError, TypeError):
                             amount_usd = 0.0
                
                if amount_usd is None:
                    amount_usd = 0.0
                else:
                    try:
                        amount_usd = float(amount_usd)
                    except (ValueError, TypeError):
                        amount_usd = 0.0
                # -- Destination Extraction --
                to_label = event_data.get('toAddressLabel')
                if not to_label:
                    to_addr_obj = event_data.get('toAddress')
                    if isinstance(to_addr_obj, dict):
                        entity = to_addr_obj.get('arkhamEntity', {})
                        to_label = entity.get('name') or to_addr_obj.get('arkhamLabel', {}).get('name')
                    
                    if not to_label:
                        to_addrs_list = event_data.get('toAddresses')
                        if isinstance(to_addrs_list, list):
                            for item in to_addrs_list:
                                addr_obj = item.get('address') or item
                                if isinstance(addr_obj, dict):
                                     entity = addr_obj.get('arkhamEntity', {})
                                     candidate_label = entity.get('name') or addr_obj.get('arkhamLabel', {}).get('name')
                                     if candidate_label:
                                         to_label = candidate_label
                                         break
                
                final_destination = to_label if to_label else "Unknown Destination"
                # -- Timestamp Extraction --
                block_timestamp_str = event_data.get('blockTimestamp')
                if block_timestamp_str:
                    try:
                        timestamp = datetime.fromisoformat(block_timestamp_str.replace('Z', '+00:00'))
                    except ValueError:
                        timestamp = datetime.utcnow()
                else:
                    timestamp = datetime.utcnow()
                # -- Token Amount --
                token_amount = event_data.get('tokenAmount', 0)
                try:
                    token_amount = float(token_amount)
                except (ValueError, TypeError):
                    token_amount = 0.0
                inflow = InflowEvent(
                    timestamp=timestamp,
                    currency=currency,
                    amount=token_amount,
                    amount_usd=amount_usd,
                    destination=final_destination,
                    transaction_hash=event_data.get('txid') or event_data.get('transactionHash', 'N/A'),
                    raw_data=json.dumps(event_data)
                )
                
                # Use shared connection
                save_inflow_event(inflow, conn=conn)
            except Exception as e_inner:
                # Catch individual event failure in batch
                if conn:
                    try:
                        conn.rollback() 
                    except Exception:
                        pass
                
                err = f"Error processing ITEM in batch: {e_inner}"
                logger.error(err)
                save_skipped_event(SkippedEvent(timestamp=datetime.utcnow(), reason=err, raw_data=json.dumps(event_data)), conn=conn)
        return None
    except Exception as e:
        error_msg = f"Error processing payload wrapper: {e}"
        logger.error(error_msg)
        try:
            raw_str = json.dumps(payload)
        except Exception:
            raw_str = str(payload)
            
        save_skipped_event(SkippedEvent(
            timestamp=datetime.utcnow(),
            reason=error_msg,
            raw_data=raw_str
        ), conn=conn)
        return None
    finally:
        if conn:
            conn.close()
@app.get("/")
async def health_check():
    return {"status": "online"}

@app.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
        alert_name = payload.get('alertName', 'Unknown')
        logger.info(f"📥 WEBHOOK RECEIVED: {alert_name}")
        
        # Process in background to respond quickly to Arkham
        background_tasks.add_task(process_event, payload)
        
        return {"status": "received"}
    except Exception as e:
        logger.error(f"Error receiving webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
