import un_comtrade as uc
from env_setup import ensure_required_keys

ensure_required_keys()
_, key = uc.get_config()

years = ",".join(str(y) for y in range(2015, 2024))
df = uc.comtradeapicall.getFinalData(
    key, typeCode="C", freqCode="A", clCode="HS", period=years,
    reporterCode="840", cmdCode="190590", flowCode="M",
    partnerCode="0", partner2Code=None, customsCode=None, motCode=None,
    maxRecords=100, format_output="JSON", aggregateBy=None,
    breakdownMode="classic", countOnly=None, includeDesc=True,
)
print("2015~2023년 통째로 조회 결과:")
print(df)
