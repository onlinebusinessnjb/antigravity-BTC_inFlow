from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any
from datetime import datetime
class ArkhamEventData(BaseModel):
    """
    Sub-model for the 'event_data' field in Arkham payloads.
    Adjust fields based on actual Arkham payload inspection.
    """
    transactionHash: str
    tokenSymbol: str
    tokenAmount: float
    valueUSD: float
    fromAddressLabel: Optional[str] = None
    toAddressLabel: Optional[str] = None
    blockTimestamp: datetime
class ArkhamPayload(BaseModel):
    """
    Main payload model for Arkham Webhooks.
    """
    count: int
    event_data: ArkhamEventData
    
    # Custom validator if Arkham sends timestamp as string or different format
    @validator('event_data', pre=True)
    def parse_nested_data(cls, v):
        # Placeholder if pre-processing is needed
        return v
class InflowEvent(BaseModel):
    """
    Internal model for database storage.
    """
    timestamp: datetime
    currency: str
    amount: float
    amount_usd: float
    destination: str
    transaction_hash: str
    raw_data: str
class SkippedEvent(BaseModel):
    """
    Model for tracking skipped/ignored webhooks.
    """
    timestamp: datetime
    reason: str
    raw_data: str
