# 파일명: main.py
import os
import platform
import pandas as pd
from dotenv import load_dotenv

# 💡 1. 환경변수 최우선 로드
load_dotenv()

import matplotlib
# 백그라운드에서 차트가 뜨도록 설정
matplotlib.use('Qt5Agg') 
import matplotlib.pyplot as plt

# 💡 2. 분리해 둔 K-DGRO 엔진 모듈들을 하나로 조립
from kdgro_backtester import run_index_backtest
from kdgro_scorer import calculate_universe_zscores
from kdgro_portfolio_builder import build_custom_portfolio
from kdgro_ai_analyst import run_ai_analyst
from kdgro_trader import execute_rebalancing

def setup_plot_font():
    """운영체제별 한글 폰트 깨짐 방지 세팅"""
    if platform.system() == 'Windows':
        plt.rc('font', family='Malgun Gothic')
    elif platform.system() == 'Darwin': 
        plt.rc('font', family='AppleGothic')
    plt.rcParams['axes.unicode_minus'] = False

def get_user_settings():
    """터미널에서 사용자에게 팩터 비중과 전략을 묻는 인터페이스"""
    print("\n⚙️ [Step 1] K-DGRO 전략 튜닝")
    print("팩터별 중요도(비중)를 설정합니다. (엔터만 누르면 기본값으로 세팅됩니다)")
    
    try:
        w_roe = input(" - 5년 평균 ROE 비중 입력 (예: 0.3) [기본 0.3]: ")
        w_roe = float(w_roe) if w_roe.strip() else 0.3
        
        w_fcf = input(" - 총 부채 대비 FCF 비중 입력 (예: 0.3) [기본 0.3]: ")
        w_fcf = float(w_fcf) if w_fcf.strip() else 0.3
        
        w_div = input(" - Div (배당률) 비중 입력 (예: 0.2) [기본 0.2]: ")
        w_div = float(w_div) if w_div.strip() else 0.2
        
        w_dps = input(" - DPS (배당성장) 비중 입력 (예: 0.2) [기본 0.2]: ")
        w_dps = float(w_dps) if w_dps.strip() else 0.2
    except ValueError:
        print("⚠️ 숫자가 아닌 값이 입력되어 기본값으로 자동 설정됩니다.")
        w_roe, w_fcf, w_div, w_dps = 0.3, 0.3, 0.2, 0.2

    # 가중치 합계가 1.0이 되도록 정규화
    total = w_roe + w_fcf + w_div + w_dps
    if total == 0: total = 1.0
    weights = {"ROE": w_roe/total, "FCF": w_fcf/total, "Div": w_div/total, "DPS": w_dps/total}
    
    print("\n포트폴리오 자산 배분 방식을 선택하세요.")
    print(" [1] mcap  : 시가총액 가중 (대형주 위주 안정성)")
    print(" [2] equal : 동일 가중 (중소형주 위주 수익률)")
    print(" [3] score : 팩터 점수 가중 (Z-Score 극한 활용)")
    
    method_choice = input("번호 입력 (1/2/3) [기본값: 1]: ")
    if method_choice == '2': 
        weight_method = 'equal'
    elif method_choice == '3': 
        weight_method = 'score'
    else: 
        weight_method = 'mcap'
        
    return weights, weight_method

def main():
    print("="*80)
    print(" 🚀 K-DGRO 퀀타멘탈 통합 투자 시스템 가동")
    print("="*80)
    
    setup_plot_font()
    
    # 💡 하드디스크 I/O를 없애기 위해 엑셀을 메모리에 최초 1회만 올립니다.
    if not os.path.exists("kdgro_master_db.xlsx") or not os.path.exists("kdgro_universe_history.xlsx"):
        print("🚨 원천 데이터 엑셀 파일이 없습니다. 데이터 수집기를 먼저 실행해 주세요.")
        return

    print("⏳ 원천 데이터베이스 메모리 적재 중...")
    df_db_memory = pd.read_excel("kdgro_master_db.xlsx")
    df_univ_memory = pd.read_excel("kdgro_universe_history.xlsx")
    
    # 1. 사용자로부터 튜닝 전략 입력받기
    my_weights, weight_method = get_user_settings()
    
    # 2. 백테스트 시뮬레이션 돌리기
    print("\n📈 [Step 2] 전략 백테스팅 시뮬레이션 시작...")
    target_end = 2025 # 2026년 매수를 위한 가장 최신 결산 연도
    
    # 💡 df_bt 뒤에 ', yearly_contrib' 를 추가하여 두 개의 결과물을 각각 나눠 받습니다.
    df_bt, yearly_contrib = run_index_backtest(
        start_target_year=2022, 
        end_target_year=target_end, 
        weights=my_weights, 
        weight_method=weight_method,
        df_db=df_db_memory,      
        df_univ=df_univ_memory   
    )
    
    if df_bt is not None and not df_bt.empty:
        df_bt.to_excel("kdgro_backtest_result.xlsx")
        print("\n💾 'kdgro_backtest_result.xlsx' 파일로 백테스트 결과가 저장되었습니다.")
        
        # 차트 출력 (block=False 옵션으로 그래프를 띄워둔 채 다음 코드로 넘어갑니다)
        print("📊 차트를 띄웁니다. (창을 닫지 않아도 AI 분석기를 사용할 수 있습니다)")
        plt.figure(figsize=(12, 6))
        plt.plot(df_bt.index, df_bt['K-DGRO_Index'], label='K-DGRO 포트폴리오 (TR)', color='crimson', linewidth=2)
        plt.plot(df_bt.index, df_bt['KOSPI_Index'], label='KOSPI 지수', color='royalblue', alpha=0.6, linewidth=1.5)
        plt.title('K-DGRO vs KOSPI 누적 수익률 비교', fontsize=16, fontweight='bold')
        plt.xlabel('날짜', fontsize=12)
        plt.ylabel('지수 (Base = 1,000pt)', fontsize=12)
        plt.legend(fontsize=12, loc='upper left')
        plt.grid(True, linestyle='--', alpha=0.5)
        plt.tight_layout()
        plt.show(block=False) 
    
    # 3. 최신 명단(2025년 결산)만 뽑아서 AI 분석기로 넘기기
    print("\n🤖 [Step 3] 실시간 최신 포트폴리오 AI 분석 준비 중...")
    
    # 스코어러 연산
    df_scored = calculate_universe_zscores(
        target_year=target_end, 
        df_db=df_db_memory, 
        df_univ=df_univ_memory, 
        show_report=False
    )
    
    if df_scored is not None:
        # 빌더 연산
        df_latest_port = build_custom_portfolio(
            df_universe=df_scored, 
            target_year=target_end, 
            weights=my_weights, 
            weighting_method=weight_method, 
            show_report=False
        )
        
        if df_latest_port is not None:
            # AI 분석기 호출
            run_ai_analyst(df_latest_port)

        # 💡 [추가된 자동매매 로직]
        print("\n" + "="*80)
        trade_yn = input("🚀 한투 모의투자 계좌로 해당 포트폴리오를 매수하시겠습니까? (y/n): ")
        if trade_yn.lower() == 'y':
            budget_str = input("💰 투입할 총 자산(원)을 숫자로 입력하세요 (예: 10000000): ")
            try:
                budget = int(budget_str)
                execute_rebalancing(df_latest_port, budget)
            except ValueError:
                print("⚠️ 숫자가 잘못 입력되어 매매를 취소합니다.")

# 💡 [핵심] 이 스위치가 있어야 파이썬이 터미널에서 실행될 때 함수를 작동시킵니다!
if __name__ == "__main__":
    main()