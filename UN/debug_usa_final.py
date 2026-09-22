import un_comtrade as uc
from env_setup import ensure_required_keys

ensure_required_keys()
_, key = uc.get_config()


def check(label, **kwargs):
    df = uc.comtradeapicall.getFinalData(
        key, typeCode="C", freqCode="A", clCode="HS",
        partner2Code=None, customsCode=None, motCode=None,
        maxRecords=10, format_output="JSON", aggregateBy=None,
        breakdownMode="classic", countOnly=None, includeDesc=True,
        **kwargs,
    )
    n = 0 if df is None else len(df)
    print(f"[{label}] 결과 행 수: {n}")


# 1) 미국(840) TOTAL(전품목 합계) 수입 - 데이터가 없을 수가 없는 값
check("미국 TOTAL 수입 2022", period="2022", reporterCode="840", cmdCode="TOTAL",
      flowCode="M", partnerCode="0")

# 2) 미국(840) TOTAL 수출
check("미국 TOTAL 수출 2022", period="2022", reporterCode="840", cmdCode="TOTAL",
      flowCode="X", partnerCode="0")

# 3) 비교용: 중국(156) TOTAL 수입 (아까 190590은 됐으니 되는 게 정상)
check("중국 TOTAL 수입 2022", period="2022", reporterCode="156", cmdCode="TOTAL",
      flowCode="M", partnerCode="0")

# 4) 미국을 파트너(상대국)로 놓고, 중국이 보고한 "중국->미국" 거래 - 이건 중국이 보고하는 값이라 미국 API 문제와 무관
check("중국이 보고한 中->美 190590 수출 2022", period="2022", reporterCode="156", cmdCode="190590",
      flowCode="X", partnerCode="842")
