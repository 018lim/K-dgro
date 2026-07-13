# 파일명: kdgro_backtester.py
import os
import time
import platform
from datetime import datetime
import pandas as pd
import numpy as np
from tqdm import tqdm
from pykrx import stock
from dotenv import load_dotenv

# 무조건 pykrx를 부르기 전에 환경 변수(KRX_ID, KRX_PW)부터 장전!
load_dotenv()

from kdgro_scorer import calculate_universe_zscores
from kdgro_portfolio_builder import build_custom_portfolio

# 캐시 시스템: 주가를 저장할 전용 폴더 생성
CACHE_DIR = "price_cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def get_cached_price(ticker, start, end, is_index=False):
    """주가를 로컬에 저장해두고, 두 번째부터는 0.01초 만에 불러오는 마법의 함수"""
    prefix = "IDX" if is_index else "STK"
    file_path = os.path.join(CACHE_DIR, f"{prefix}_{ticker}_{start}_{end}.csv")
    
    if os.path.exists(file_path):
        return pd.read_csv(file_path, index_col=0, parse_dates=True)
        
    time.sleep(0.1)
    if is_index:
        df = stock.get_index_ohlcv(start, end, ticker)
    else:
        df = stock.get_market_ohlcv(start, end, ticker)
        
    if not df.empty:
        df.to_csv(file_path)
        
    return df

def get_trading_dates(start_date, end_date):
    """지정된 기간 내의 영업일 리스트를 반환합니다. (삼성전자 영업일 기준, 캐시 적용)"""
    df = get_cached_price("005930", start_date, end_date, is_index=False)
    if df.empty: return []
    return df.index.tolist()

def run_index_backtest(start_target_year, end_target_year, weights, top_n=30, weight_method='mcap', base_index=1000.0, df_db=None, df_univ=None):
    print("\n" + "="*80)
    print(f" 🚀 K-DGRO 백테스팅 엔진 가동 (지수화 모드)")
    print(f" 📅 기간: {start_target_year+1}년 5월 ~ {end_target_year+2}년 4월")
    print(f" ⚖️ 비중 방식: {weight_method.upper()}")
    print("="*80)

    if df_db is None or df_univ is None:
        print("⏳ 원천 데이터베이스 메모리 적재 중...")
        if not os.path.exists("kdgro_master_db.xlsx") or not os.path.exists("kdgro_universe_history.xlsx"):
            print("🚨 엑셀 파일이 없습니다. 데이터 수집기를 먼저 실행해 주세요.")
            return None, None # 💡 반환값이 2개가 되므로 None도 2개로 맞춤
        df_db = pd.read_excel("kdgro_master_db.xlsx")
        df_univ = pd.read_excel("kdgro_universe_history.xlsx")

    portfolio_index_series = pd.Series(dtype=float)
    current_index_value = base_index
    
    kospi_index_series = pd.Series(dtype=float)
    kospi_base_value = base_index
    
    # 💡 [핵심 추가 1] 매년 '비중이 반영된 기여도'를 모아둘 빈 딕셔너리 생성
    yearly_contributors = {}

    for target_year in range(start_target_year, end_target_year + 1):
        rebalance_year = target_year + 1
        print(f"\n🔄 [{rebalance_year}년 5월 리밸런싱] {target_year}년 결산 데이터 기준 포트폴리오 구성 중...")
        
        df_universe = calculate_universe_zscores(target_year=target_year, df_db=df_db, df_univ=df_univ, show_report=False)
        if df_universe is None or df_universe.empty:
            print(f"🚨 {target_year}년 데이터가 없어 해당 구간을 스킵합니다.")
            continue
            
        df_portfolio = build_custom_portfolio(df_universe, target_year=target_year, weights=weights, top_n=top_n, weighting_method=weight_method, show_report=False)
        if df_portfolio is None: continue
            
        tickers = df_portfolio['종목코드'].tolist()
        allocations = (df_portfolio['투자비중(%)'] / 100).tolist()
        ticker_weights = dict(zip(tickers, allocations))

        portfolio_div_yield = (df_portfolio['Div_Yield(%)'] * allocations).sum()
        print(f"💰 포트폴리오 예상 배당수익률: {portfolio_div_yield:.2f}% (기말 TR 지수에 반영됨)")
        
        start_date = f"{rebalance_year}0501"
        end_date = f"{rebalance_year + 1}0430"

        today_str = datetime.now().strftime("%Y%m%d")
        if end_date > today_str:
            end_date = today_str
            print(f"🕒 [현재 진행 중] 아직 {rebalance_year+1}년 4월이 오지 않아, 오늘({today_str})까지만 추적합니다.")
        
        trading_dates = get_trading_dates(start_date, end_date)
        if not trading_dates: continue
        
        df_kospi = get_cached_price("1001", start_date, end_date, is_index=True)
        if not df_kospi.empty:
            kospi_daily_pct = df_kospi['종가'].pct_change().fillna(0)
            kospi_period_index = kospi_base_value * (1 + kospi_daily_pct).cumprod()
            kospi_index_series = pd.concat([kospi_index_series, kospi_period_index])
            kospi_base_value = kospi_index_series.iloc[-1]
            
        print(f"📊 {rebalance_year}년도 편입 종목({len(tickers)}개) 일별 주가 수집 중...")
        daily_returns_df = pd.DataFrame(index=trading_dates)
        
        for tk in tqdm(tickers, desc="주가 파싱", leave=False):
            df_price = get_cached_price(tk, start_date, end_date, is_index=False)
            if not df_price.empty:
                daily_returns_df[tk] = df_price['종가'].pct_change().fillna(0)
            else:
                daily_returns_df[tk] = 0.0
            
        daily_returns_df.fillna(0, inplace=True)
        
        portfolio_daily_return = pd.Series(0.0, index=trading_dates)
        
        # 💡 [핵심 추가 2] 기여도 계산기
        ticker_contributions = {} 
        
        for tk, w in ticker_weights.items():
            if tk in daily_returns_df.columns:
                # 1. 포트폴리오 전체 일일 수익률 합산
                portfolio_daily_return += daily_returns_df[tk] * w
                
                # 2. 해당 종목의 1년(기간) 누적 수익률 계산
                tk_period_rtn = (1 + daily_returns_df[tk]).prod() - 1
                
                # 3. [기간 수익률 × 비중] = 진짜 기여도(%p)
                ticker_contributions[tk] = tk_period_rtn * w * 100
                
        period_index = current_index_value * (1 + portfolio_daily_return).cumprod()
        
        if end_date == f"{rebalance_year + 1}0430":
            period_index.iloc[-1] = period_index.iloc[-1] * (1 + (portfolio_div_yield / 100))
        
        portfolio_index_series = pd.concat([portfolio_index_series, period_index])
        
        period_port_rtn = (period_index.iloc[-1] / period_index.iloc[0] - 1) * 100
        period_kospi_rtn = (kospi_period_index.iloc[-1] / kospi_period_index.iloc[0] - 1) * 100
        
        # 💡 [핵심 추가 3] 기여도 순으로 정렬하고 yearly_contributors 에 저장
        ticker_to_name = dict(zip(df_portfolio['종목코드'], df_portfolio['종목명'])) 
        
        # 기여도(contribution)를 기준으로 내림차순 정렬
        sorted_contrib = sorted(ticker_contributions.items(), key=lambda x: x[1], reverse=True)
        
        # Streamlit 대시보드에서 쓸 수 있도록 Top 3, Bottom 3 저장
        yearly_contributors[rebalance_year] = {
            'top': [(ticker_to_name.get(tk, tk), c) for tk, c in sorted_contrib[:3]],
            'bottom': [(ticker_to_name.get(tk, tk), c) for tk, c in sorted_contrib[-3:][::-1]],
            'div_yield': portfolio_div_yield  # 💡 [핵심 추가] 기간별 예상 배당률 기록
        }
        
        print("\n" + "-"*60)
        print(f" 🗓️ [{rebalance_year}년도 매수 구간 결산 리포트]")
        print(f" 📈 K-DGRO 수익률 : {period_port_rtn:>6.2f}% (vs KOSPI: {period_kospi_rtn:>6.2f}%)")
        print(f" 💰 구간 배당수익률: {portfolio_div_yield:.2f}% (기말 TR 지수에 재투자 완료)") # 💡 이 줄을 추가!
        print("-" * 60)
        
        # 터미널 출력도 단순 수익률이 아닌 '기여도'로 변경
        print(" 🏆 [포트폴리오 기여 Top 3 종목]")
        for tk, c in sorted_contrib[:3]:
            print(f"    🔺 {ticker_to_name.get(tk, tk):<10} : +{c:.2f}%p")
            
        print(" 💔 [포트폴리오 기여 Bottom 3]")
        for tk, c in sorted_contrib[-3:][::-1]:
            print(f"    🔻 {ticker_to_name.get(tk, tk):<10} : {c:.2f}%p")
            
        print("-" * 60)
        
        current_index_value = portfolio_index_series.iloc[-1]
        print(f"✅ 구간 종료 K-DGRO 지수: {current_index_value:.2f}pt\n")

    if portfolio_index_series.empty: return None, None # 💡 여기도 None 2개로
        
    total_return = (portfolio_index_series.iloc[-1] / base_index - 1) * 100
    kospi_return = (kospi_index_series.iloc[-1] / base_index - 1) * 100
    
    years = len(portfolio_index_series) / 252 
    cagr = ((portfolio_index_series.iloc[-1] / base_index) ** (1 / years) - 1) * 100 if years > 0 else 0
    
    running_max = portfolio_index_series.cummax()
    drawdown = (portfolio_index_series - running_max) / running_max
    mdd = drawdown.min() * 100

    print("\n" + "="*80)
    print(" 🏆 K-DGRO 백테스팅 최종 성과 리포트")
    print("="*80)
    print(f" 📈 누적 수익률 : {total_return:>.2f}% (KOSPI: {kospi_return:>.2f}%)")
    print(f" 🚀 CAGR (폭발력) : {cagr:>.2f}%")
    print(f" 🛡️ MDD (내구도)   : {mdd:>.2f}%")
    print("="*80)

    df_result = pd.DataFrame({
        'K-DGRO_Index': portfolio_index_series,
        'KOSPI_Index': kospi_index_series
    })
    
    # 💡 [핵심 추가 4] 백테스트 지수 결과(df_result)와 기여도 명단(yearly_contributors)을 같이 반환!
    return df_result, yearly_contributors

if __name__ == "__main__":
    import matplotlib.pyplot as plt
    
    if platform.system() == 'Windows':
        plt.rc('font', family='Malgun Gothic') 
    elif platform.system() == 'Darwin': 
        plt.rc('font', family='AppleGothic') 
    plt.rcParams['axes.unicode_minus'] = False 

    my_weights = {"ROE": 0.20, "FCF": 0.40, "Div": 0.2, "DPS": 0.2}
    
    # 💡 테스트 실행부도 반환값 2개를 받도록 수정
    df_bt, yearly_contrib = run_index_backtest(
        start_target_year=2022, 
        end_target_year=2025, 
        weights=my_weights, 
        top_n=30, 
        weight_method='mcap'
    )
    
    if df_bt is not None:
        df_bt.to_excel("kdgro_backtest_result.xlsx")
        print("\n💾 'kdgro_backtest_result.xlsx' 파일로 일별 지수 데이터가 저장되었습니다.")
        
        print("📊 그래프 시각화 창을 띄웁니다...")
        plt.figure(figsize=(12, 6))
        
        plt.plot(df_bt.index, df_bt['K-DGRO_Index'], label='K-DGRO 포트폴리오 (TR)', color='crimson', linewidth=2)
        plt.plot(df_bt.index, df_bt['KOSPI_Index'], label='KOSPI 지수 (PR)', color='royalblue', alpha=0.6, linewidth=1.5)
        
        plt.title('K-DGRO vs KOSPI 누적 수익률 비교 (2023.05 ~ 현재)', fontsize=16, fontweight='bold')
        plt.xlabel('날짜', fontsize=12)
        plt.ylabel('지수 (Base = 1,000pt)', fontsize=12)
        plt.legend(fontsize=12, loc='upper left')
        plt.grid(True, linestyle='--', alpha=0.5)
        
        plt.tight_layout()
        plt.show()