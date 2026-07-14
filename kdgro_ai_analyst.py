# 파일명: kdgro_ai_analyst.py
import os
import time
import pandas as pd
from dotenv import load_dotenv

# 💡 [2026 모던 패키지] 완전히 새로워진 google-genai 임포트
from google import genai
from google.genai import types

load_dotenv()
gemini_api_key = os.getenv("GEMINI_API_KEY")

from kdgro_scorer import calculate_universe_zscores
from kdgro_portfolio_builder import build_custom_portfolio

def generate_ai_report(name, ticker):
    """Gemini 2.5과 신형 SDK를 활용하여 퀀타멘탈 리포트를 생성합니다."""
    if not gemini_api_key:
        return "\n🚨 .env 파일에 GEMINI_API_KEY가 설정되지 않아 AI 분석을 실행할 수 없습니다."

    print(f"\n🌐 [AI 애널리스트] Gemini가 구글 실시간 검색을 통해 '{name}'의 최신 동향을 파악 중입니다...")
    time.sleep(0.5)
    
    prompt = f"""
    너는 '기업의 펀더멘탈(기반)을 매우 엄격하게 평가한다는 시니어 퀀타멘탈 펀드매니저다.
    

    반드시 [구글 실시간 검색]을 활용하여 '{name} ({ticker})'의 가장 최신 뉴스, 실적 발표, 시장 이슈를 수집한 뒤,
    Z-Score 기반 배당성장 포트폴리오 편입 관점에서 아래 4가지 항목을 각각 3~4줄로 요약해라.
    특히 이익 성장성을 '폭발력'으로, 현금흐름 안정성 및 낙폭(MDD) 방어를 '내구도'라는 스탯 관점으로 비유하여 분석에 녹여내라.

    1️⃣ 핵심 비즈니스 모델 (어디서 돈을 버는가?)
    2️⃣ 경제적 해자 (비즈니스의 내구도 및 경쟁 우위)
    3️⃣ 잠재적 리스크 (붕괴를 유발할 수 있는 약점, 최근 악재 포함)
    4️⃣ 배당 지속가능성 (현금흐름 기반 주주환원 퀄리티)
    """

    try:
        # 💡 1. 최신 통합 클라이언트 생성
        client = genai.Client(api_key=gemini_api_key)
        
        # 💡 2. 제미나이 2.5 모델 호출 및 실시간 구글 검색(Tool) 연동
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}], # 구글 검색 엔진 연결
                temperature=0.3 # 분석 리포트의 논리성을 위해 온도를 살짝 낮춤
            )
        )
        return response.text
    except Exception as e:
        return f"\n🚨 API 호출 오류 발생: {e}"

def run_ai_analyst(df_latest_port):
    """K-DGRO 포트폴리오 편입 종목 AI 퀀타멘탈 분석기"""
    print("\n" + "="*80)
    print(" 🤖 K-DGRO AI 퀀타멘탈 애널리스트 가동 (Gemini 2.5 Flash )")
    print("="*80)

    port_list = df_latest_port[['종목코드', '종목명', '투자비중(%)']].reset_index(drop=True)

    while True:
        print("\n📋 [현재 기준 K-DGRO 편입 종목 TOP 30]")
        print("-" * 80)
        for i in range(0, len(port_list), 3):
            row_str = ""
            for j in range(3):
                if i + j < len(port_list):
                    item = port_list.iloc[i+j]
                    row_str += f"[{i+j+1:2d}] {item['종목명']:<10} ({item['투자비중(%)']:>5.2f}%)  |  "
            print(row_str)
        print("-" * 80)

        choice = input("\n💡 정성 분석을 원하는 종목의 번호를 입력하세요 (종료하려면 'q' 입력): ")

        if choice.lower() == 'q':
            print("\n👋 AI 퀀타멘탈 분석을 종료합니다. 성공적인 투자를 기원합니다!\n")
            break

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(port_list):
                target = port_list.iloc[idx]
                name = target['종목명']
                ticker = target['종목코드']

                report = generate_ai_report(name, ticker)

                print("\n" + "=*="*26 + "=")
                print(f" 📑 K-DGRO 실시간 AI 정성분석 리포트 : {name} ({ticker})")
                print("=*="*26 + "=")
                print(report)
                print("=" * 80)
            else:
                print("\n⚠️ 목록에 없는 번호입니다. 1~30 사이의 숫자를 입력해 주세요.")
        except ValueError:
            print("\n⚠️ 올바른 숫자나 'q'를 입력해 주세요.")

if __name__ == "__main__":
    print("⏳ 실시간 최신 포트폴리오 데이터를 가져옵니다...")
    if not os.path.exists("kdgro_master_db.xlsx") or not os.path.exists("kdgro_universe_history.xlsx"):
        print("🚨 엑셀 파일이 없습니다. 데이터 수집기를 먼저 실행해 주세요.")
    else:
        df_db_memory = pd.read_excel("kdgro_master_db.xlsx")
        df_univ_memory = pd.read_excel("kdgro_universe_history.xlsx")
        my_weights = {"ROE": 0.25, "FCF": 0.25, "Div": 0.25, "DPS": 0.25}
        target_year = 2025  
        
        df_univ = calculate_universe_zscores(target_year=target_year, df_db=df_db_memory, df_univ=df_univ_memory, show_report=False)
        if df_univ is not None:
            df_port = build_custom_portfolio(df_univ, target_year=target_year, weights=my_weights, top_n=30, weighting_method='mcap', show_report=False)
            if df_port is not None:
                run_ai_analyst(df_port)
            else:
                print("🚨 포트폴리오 빌드 과정에서 오류가 발생했습니다.")
        else:
            print("🚨 스코어링 연산에 실패했습니다.")