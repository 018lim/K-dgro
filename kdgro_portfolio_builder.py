# 파일명: kdgro_portfolio_builder.py
import os
import pandas as pd
import numpy as np
from scipy.stats import norm
from pykrx import stock

# 💡 [핵심 패치 1] 시가총액 데이터도 매번 KRX에 묻지 않도록 캐시 폴더를 설정합니다.
CACHE_DIR = "price_cache"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# 💡 [핵심 패치 2] show_report 스위치를 달아 백테스팅 중 불필요한 출력을 숨깁니다.
def build_custom_portfolio(df_universe, target_year, weights=None, top_n=30, weighting_method='equal', show_report=False):
    """
    weighting_method: 'equal' (동일가중), 'score' (점수가중), 'mcap' (리밸런싱 시총가중)
    """
    if df_universe is None or df_universe.empty:
        if show_report: print("🚨 입력된 유니버스 데이터가 비어있습니다.")
        return None
        
    if weights is None:
        weights = {"ROE": 0.25, "FCF": 0.25, "Div": 0.25, "DPS": 0.25}
    
    total_w = sum(weights.values())
    if not np.isclose(total_w, 1.0):
        raise ValueError(f"🚨 가중치 합계 오류: 합계가 정확히 1.0이 되도록 설정해주세요.")

    df_percentile = df_universe.copy()
    z_cols = ['Z_ROE', 'Z_FCF', 'Z_Div', 'Z_DPS']
    weight_map = {
        'Z_ROE': weights.get("ROE", 0), 'Z_FCF': weights.get("FCF", 0),
        'Z_Div': weights.get("Div", 0), 'Z_DPS': weights.get("DPS", 0)
    }

    # Z-Score -> Percentile 변환
    for col in z_cols:
        temp_col = df_percentile[col].fillna(0)
        df_percentile[col] = norm.cdf(temp_col)

    df_percentile['Custom_Score'] = 0.0
    df_percentile['Weight_Sum'] = 0.0
    
    for col in z_cols:
        w = weight_map[col]
        mask = df_universe[col].notnull()
        df_percentile.loc[mask, 'Custom_Score'] += df_percentile.loc[mask, col] * w
        df_percentile.loc[mask, 'Weight_Sum'] += w
        
    df_percentile['Custom_Score'] = (df_percentile['Custom_Score'] / df_percentile['Weight_Sum']) * 100
    
    # 👑 상위 Top N 추출
    df_portfolio = df_percentile.sort_values(by='Custom_Score', ascending=False).head(top_n).reset_index(drop=True)
    
    # 💡 3가지 포트폴리오 비중 구성 로직
    if weighting_method == 'equal':
        df_portfolio['투자비중(%)'] = 100.0 / len(df_portfolio)
        
    elif weighting_method == 'score':
        total_score = df_portfolio['Custom_Score'].sum()
        df_portfolio['투자비중(%)'] = (df_portfolio['Custom_Score'] / total_score) * 100
        
    elif weighting_method == 'mcap':
        rb_year = target_year + 1
        try:
            # 5월 첫 거래일 찾기
            df_ohlcv = stock.get_market_ohlcv(f"{rb_year}0501", f"{rb_year}0515", "005930")
            if not df_ohlcv.empty:
                first_b_day = df_ohlcv.index[0].strftime("%Y%m%d")
                
                # 💡 [핵심 패치 3] 시가총액 캐싱 로직 적용
                cache_file = os.path.join(CACHE_DIR, f"mcap_{first_b_day}.csv")
                
                if os.path.exists(cache_file):
                    # 이미 저장된 파일이 있으면 0.01초 만에 불러오기 (종목코드가 숫자로 변환되지 않게 dtype 지정)
                    df_cap = pd.read_csv(cache_file, dtype={'티커': str})
                    df_cap.set_index('티커', inplace=True)
                else:
                    # 파일이 없으면 KRX에서 다운로드 후 다음을 위해 저장
                    df_cap = stock.get_market_cap(first_b_day, market="KOSPI")
                    df_cap.index.name = '티커'
                    df_cap.to_csv(cache_file)
                
                # 뽑힌 Top N 종목들에 시가총액 매핑
                df_portfolio['리밸런싱_시총'] = df_portfolio['종목코드'].apply(
                    lambda x: df_cap.loc[x, '시가총액'] if x in df_cap.index else 0
                )
                
                total_mcap = df_portfolio['리밸런싱_시총'].sum()
                if total_mcap > 0:
                    df_portfolio['투자비중(%)'] = (df_portfolio['리밸런싱_시총'] / total_mcap) * 100
                else:
                    df_portfolio['투자비중(%)'] = 100.0 / len(df_portfolio) 
        except Exception as e:
            if show_report: print(f"🚨 시가총액 연동 실패 (동일가중으로 대체): {e}")
            df_portfolio['투자비중(%)'] = 100.0 / len(df_portfolio)
            
    else:
        raise ValueError("지원하지 않는 가중치 방식입니다. 'equal', 'score', 'mcap' 중 하나를 선택하세요.")

    df_portfolio.index = df_portfolio.index + 1
    df_portfolio['투자비중(%)'] = df_portfolio['투자비중(%)'].round(2)
    
    return df_portfolio.drop(columns=['Weight_Sum'])

if __name__ == "__main__":
    # 단독 테스트용 코드 (에러 방지용 가짜 데이터)
    mock_universe = pd.DataFrame({
        '종목코드': ['005930', '000660'], '종목명': ['삼성전자', 'SK하이닉스'],
        'Z_ROE': [1.0, 0.8], 'Z_FCF': [0.5, 0.9], 'Z_Div': [0.2, 0.1], 'Z_DPS': [0.1, 0.2]
    })
    
    port = build_custom_portfolio(mock_universe, target_year=2025, weighting_method='mcap', show_report=True)
    if port is not None:
        print(port[['종목명', 'Custom_Score', '투자비중(%)']])