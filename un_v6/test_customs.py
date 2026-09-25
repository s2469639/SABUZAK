import os, requests
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.getcwd()), ".env"), override=True)
load_dotenv(override=False)
key = os.getenv("DATA_GO_KR_API_KEY")
print("키 읽힘:", bool(key))
r = requests.get(
    "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList",
    params={"serviceKey": key, "strtYymm": "202401", "endYymm": "202412",
            "hsSgn": "190590", "cntyCd": "US"},
    timeout=20,
)
print("상태코드:", r.status_code)
print(r.text[:1500])