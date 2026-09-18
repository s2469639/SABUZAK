import json
import os
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

# .env 파일에서 환경변수 로드
load_dotenv()

# OpenAI API 클라이언트 초기화 (OPENAI_API_KEY 또는 LLM_API_KEY 지원)
api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
client = OpenAI(api_key=api_key)

# 1. 원본 데이터 로드
input_file = "원본.csv"
output_file = "clean.csv"

if not os.path.exists(input_file):
  raise FileNotFoundError(
      f"'{input_file}' 파일을 찾을 수 없습니다. 경로를 확인해주세요."
  )

df = pd.read_csv(input_file)

# 2. 새로운 5개 칼럼 초기화 (기존 내용 삭제/변경 방지)
new_columns = ["대륙", "food_yn", "규모", "거래고객 유형", "키워드"]
for col in new_columns:
  if col not in df.columns:
    df[col] = None


def classify_exhibition(row):
  """OpenAI API를 사용하여 각 박람회 정보를 조건에 맞게 분류"""
  prompt = f"""
    당신은 글로벌 박람회 데이터 분석 전문가입니다. 아래 박람회 정보를 바탕으로 5가지 항목을 정확히 분류해주세요.

    [박람회 정보]
    - 박람회명(name): {row.get('name', '')}
    - 국가(country): {row.get('country', '')}
    - 웹사이트(website): {row.get('website', '')}
    - 소개(intro): {row.get('intro', '')}

    [분류 조건]
    1) 대륙: 해당 국가가 속한 대륙 (예: 아시아, 유럽, 북미, 남미, 아프리카, 오세아니아 등)
    2) food_yn: 식품류 전시회 여부 (True 또는 False)
       - TRUE: 가공식품, 과자/스낵, 베이커리, 디저트, 음료, 주류, 유기농/비건, HORECA 식자재 등 사람이 섭취하는 완제품 및 식음료 원료 전시회
       - FALSE: 식품 가공기계, 포장 장비, 냉동·냉장 설비, 가구, 가전, 패션, 리빙, 농업 생산 설비 등
    3) 규모: '대', '중', '소', '미상' 중 택 1
       - 대: 참가기업 1,000개 사 이상 또는 방문객 30,000명 이상
       - 중: 참가기업 300 ~ 999개 사, 방문객 10,000 ~ 29,999명
       - 소: 참가기업 300개 사 미만, 방문객 10,000명 미만
       - 미상: 통계 미공개 또는 신생 행사
    4) 거래고객 유형: 'B2B', 'B2C' (둘 다 해당하면 'B2B, B2C')
    5) 키워드: 아래 표준 키워드 풀에서 가장 적절한 단어 정확히 5개를 골라 쉼표(,)로 구분하여 작성
       [표준 키워드 풀]
       - 산업/품목군: 식품/음료종합, 제과/베이커리, 가공식품, 건강/기능성, 주류/음료, 수산/해양식품, 축산/육가공, 식자재, 식품원료/소재
       - 라이프/트렌드: 웰니스/비건, 친환경/유기농, 호스피탈리티, 외식/HORECA, 프리미엄미식, 지역특산물
       - 비식품/설비: 식품가공/설비, 포장기술, 식품테크, 소비재종합, 라이프스타일, 가든/인테리어, 농업/스마트팜

    반드시 아래 JSON 형식으로만 응답해주세요:
    {{
      "대륙": "...",
      "food_yn": true,
      "규모": "...",
      "거래고객 유형": "...",
      "키워드": "키워드1, 키워드2, 키워드3, 키워드4, 키워드5"
    }}
    """

  try:
    response = client.chat.completions.create(
        model="gpt-4o",  # 또는 gpt-4o-mini
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    result = json.loads(response.choices[0].message.content)
    return pd.Series(result)
  except Exception as e:
    print(f"오류 발생 ({row.get('name', '알 수 없음')}): {e}")
    return pd.Series(
        {
            "대륙": "미상",
            "food_yn": False,
            "규모": "미상",
            "거래고객 유형": "B2B",
            "키워드": "",
        }
    )


# 3. 행별 반복 처리 및 새로운 칼럼 매핑
print("박람회 데이터 분류 및 전처리 작업을 시작합니다...")
results = df.apply(classify_exhibition, axis=1)
df[new_columns] = results

# 4. 결과 파일 저장 (기존 내용 유지, 새로운 칼럼 추가 완료)
df.to_csv(output_file, index=False, encoding="utf-8-sig")
print(f"전처리가 완료되었습니다. 결과 파일명: '{output_file}'")