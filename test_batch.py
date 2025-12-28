import requests
import json
url = "http://localhost:8000/webhook"
payload = {
    "alertName": "BTC_inFlow_TEST_BATCH",
    "transfers": [
        {"transactionHash": "0xTEST_BATCH_1", "blockTimestamp": "2024-01-01T12:00:00Z", "valueUSD": 111111, "tokenAmount": 1.1, "toAddressLabel": "Coinbase", "currency": "BTC"},
        {"transactionHash": "0xTEST_BATCH_2", "blockTimestamp": "2024-01-01T12:00:00Z", "valueUSD": 222222, "tokenAmount": 2.2, "toAddressLabel": "Binance", "currency": "BTC"}
    ]
}
print(f"Sending Batch Payload...")
try:
    r = requests.post(url, json=payload)
    print(f"Status Code: {r.status_code}")
except Exception as e:
    print(f"Failed to connect: {e}")
