import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(HERE, "results")


def load_booth_result(job_id: str) -> dict:
    """results/<job_id>.json 파일에서 결과 데이터를 안전하게 로드"""
    file_path = os.path.join(RESULTS_DIR, f"{job_id}.json")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"결과 파일을 찾을 수 없습니다: {file_path}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_3d_prompt(job_id: str) -> dict:
    """
    저장된 결과 데이터에서 3D 렌더링에 필요한 요소를 추출하여
    3D 부스 컨셉용 프롬프트 및 파라미터를 생성합니다.
    (API 토큰 소모 없음 - 파이썬 텍스트 합성 로직)
    """
    data = load_booth_result(job_id)
    booth = data.get("booth", {})
    sections = booth.get("sections", {})
    inputs = data.get("inputs", {})

    # 1. 대상 3개 항목 추출
    main_visual = sections.get("main_visual", {})
    merchandising = sections.get("merchandising", {})
    demonstration = sections.get("demonstration", {})

    # 2. 텍스트 세부 항목 정제
    product_name = inputs.get("name", "Product")
    visual_concept = main_visual.get("concept_en") or main_visual.get("concept_ko") or "Modern and clean exhibition booth"
    
    # 진열 존(Zone) 구성 텍스트화
    zones = merchandising.get("zones", [])
    display_desc = ", ".join([f"{z.get('name')}: {z.get('purpose')}" for z in zones if z.get('name')])
    if not display_desc:
        display_desc = "Standard product showcase shelves and counter"

    # 시연 존 구성
    demo_title = demonstration.get("title") or "Interactive demonstration area"

    # 3. 3D 렌더링용 영문 메인 프롬프트 합성 (Midjourney / 3D CAD 생성용)
    prompt_en = (
        f"Professional 3D trade show booth design for '{product_name}', "
        f"exhibition interior design, commercial architectural visualization. "
        f"Key visual and structure: {visual_concept}. "
        f"Showcase & Merchandising: {display_desc}. "
        f"Demonstration & Activity zone: {demo_title}. "
        f"Photorealistic, 8k resolution, ambient studio lighting, octane render, architectural photography style --ar 16:9"
    )

    return {
        "job_id": job_id,
        "product_name": product_name,
        "extracted_elements": {
            "main_visual": main_visual,
            "merchandising": merchandising,
            "demonstration": demonstration
        },
        "prompt_en": prompt_en
    }