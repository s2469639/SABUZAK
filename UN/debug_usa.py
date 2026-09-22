import un_comtrade as uc
from env_setup import ensure_required_keys

ensure_required_keys()
_, key = uc.get_config()

df = uc.comtradeapicall.getFinalData(
    key, typeCode="C", freqCode="A", clCode="HS", period="2023",
    reporterCode="840", cmdCode="190590", flowCode="M",
    partnerCode=None, partner2Code=None, customsCode=None, motCode=None,
    maxRecords=10, format_output="JSON", aggregateBy=None,
    breakdownMode="classic", countOnly=None, includeDesc=True,
)
print(df)
