# 파일명: kdgro_scorer.py
import os
import numpy as np
import pandas as pd

# 💡 [핵심 최적화] 엑셀 파일 대신 DataFrame 객체(df_db, df_univ)를 직접 받을 수 있도록 파라미터 추가!
def calculate_universe_zscores(target_year, df_db=None, df_univ=None, db_file="kdgro_master_db.xlsx", univ_file="kdgro_universe_history.xlsx", show_report=False):
    
    # 1. 메모리(변수)로 전달받은 데이터가 없으면 그때만 엑셀 파일을 읽습니다 (최초 1회만 실행됨)
    if df_db is None or df_univ is None:
        if not os.path.exists(db_file) or not os.path.exists(univ_file):
            print("🚨 원천 데이터 엑셀 파일이 없습니다. Phase 1 수집기를 먼저 실행해 주세요.")
            return None
        df_db = pd.read_excel(db_file)
        df_univ = pd.read_excel(univ_file)
        
    # 원본 데이터 오염 방지를 위한 복사본 사용
    df_db = df_db.copy()
    df_db['종목코드'] = df_db['종목코드'].astype(str).str.zfill(6)
    
    # 유니버스 명단 확정
    str_target_year = f"{target_year}년" if isinstance(df_univ.columns[0], str) and "년" in df_univ.columns[0] else target_year
    if str_target_year not in df_univ.columns:
        str_target_year = int(str_target_year) if isinstance(str_target_year, str) and str_target_year.isdigit() else str(str_target_year)
        
    if str_target_year not in df_univ.columns:
        if show_report:
            print(f"🚨 유니버스 역사 기록에 {target_year}년 명단이 존재하지 않습니다.")
        return None
        
    target_tickers = df_univ[str_target_year].dropna().astype(str).str.zfill(6).tolist()

    # 5개년 윈도우 데이터 조립
    start_year = target_year - 4
    raw_factors = []
    
    for ticker in target_tickers:
        df_stock = df_db[(df_db['종목코드'] == ticker) & 
                         (df_db['회계연도'] >= start_year) & 
                         (df_db['회계연도'] <= target_year)].copy()
        
        if df_stock.empty:
            continue
            
        name = df_stock['종목명'].iloc[0]
        sector = df_stock['섹터'].iloc[0]
        
        # 5년 평균 이익 창출력 반영을 위해 mean(평균) 사용
        roe_5yr = df_stock['단년도_ROE(%)'].mean()
        
        df_current = df_stock[df_stock['회계연도'] == target_year]
        fcf_debt = df_current['단년도_FCF_to_Debt(%)'].values[0] if not df_current.empty else np.nan
        
        div_yield = df_current['단년도_Div_Yield(%)'].values[0] if not df_current.empty else np.nan
        if pd.isna(div_yield):
            div_yield = 0.0  
            
        dps_growth = 0.0     
        df_dps = df_stock.dropna(subset=['단년도_DPS(원)']).sort_values('회계연도')
        if len(df_dps) >= 2:
            y_diff = df_dps['회계연도'].iloc[-1] - df_dps['회계연도'].iloc[0]
            dps_old = df_dps['단년도_DPS(원)'].iloc[0]
            dps_new = df_dps['단년도_DPS(원)'].iloc[-1]
            if y_diff > 0 and dps_old > 0 and dps_new > 0:
                dps_growth = ((dps_new / dps_old) ** (1 / y_diff) - 1) * 100

        raw_factors.append({
            "종목코드": ticker, "종목명": name, "섹터": sector,
            "ROE_5yr(%)": roe_5yr, "FCF_to_Debt(%)": fcf_debt,
            "Div_Yield(%)": div_yield, "DPS_Growth(%)": dps_growth
        })

    df_calc = pd.DataFrame(raw_factors)
    if df_calc.empty:
        return None

    # 이상치 제어(윈저라이징) 및 Z-Score 통계적 표준화
    LIMIT_PCT = 0.025 
    winsorize_report = {} 

    for col in ['ROE_5yr(%)', 'Div_Yield(%)', 'DPS_Growth(%)']:
        valid = df_calc[col].dropna()
        lower_bound = valid.quantile(LIMIT_PCT)
        upper_bound = valid.quantile(1 - LIMIT_PCT)
        
        outliers_low = df_calc[df_calc[col] < lower_bound][['종목명', col]]
        outliers_high = df_calc[df_calc[col] > upper_bound][['종목명', col]]
        
        winsorize_report[col] = {
            'lower': lower_bound, 'upper': upper_bound,
            'low_list': outliers_low.values.tolist(),
            'high_list': outliers_high.values.tolist()
        }
        
        clipped_valid = valid.clip(lower=lower_bound, upper=upper_bound)
        std_v = clipped_valid.std(ddof=0)
        df_calc[f'Z_{col.split("_")[0]}'] = (clipped_valid - clipped_valid.mean()) / std_v if std_v != 0 else 0.0
            
    is_general = df_calc['섹터'] == '일반기업'
    valid_fcf = df_calc.loc[is_general, 'FCF_to_Debt(%)'].dropna()
    
    f_lower = valid_fcf.quantile(LIMIT_PCT)
    f_upper = valid_fcf.quantile(1 - LIMIT_PCT)
    
    outliers_fcf_low = df_calc[is_general & (df_calc['FCF_to_Debt(%)'] < f_lower)][['종목명', 'FCF_to_Debt(%)']]
    outliers_fcf_high = df_calc[is_general & (df_calc['FCF_to_Debt(%)'] > f_upper)][['종목명', 'FCF_to_Debt(%)']]
    
    winsorize_report['FCF_to_Debt(%)'] = {
        'lower': f_lower, 'upper': f_upper,
        'low_list': outliers_fcf_low.values.tolist(),
        'high_list': outliers_fcf_high.values.tolist()
    }
    
    clipped_fcf = valid_fcf.clip(lower=f_lower, upper=f_upper)
    fcf_std = clipped_fcf.std(ddof=0)
    df_calc.loc[is_general, 'Z_FCF'] = (clipped_fcf - clipped_fcf.mean()) / fcf_std if fcf_std != 0 else 0.0
    df_calc.loc[~is_general, 'Z_FCF'] = np.nan 

    # 💡 [출력물 정리] show_report가 True일 때만 결과를 터미널에 띄워 중복 로그를 방지합니다.
    if show_report:
        print(f"🎯 [K-DGRO Scorer] {target_year}년 결산 기준 유니버스 Z-Score 연산 완료")
        print("\n" + "-"*80)
        print(f" ✂️ [Winsorization Report] 극단치(상/하위 {LIMIT_PCT*100}%) 보정 내역")
        print("-"*80)
        for factor, data in winsorize_report.items():
            print(f"🔹 {factor}")
            low_str = ", ".join([f"{item[0]}({item[1]:.1f})" for item in data['low_list']]) if data['low_list'] else "없음"
            print(f"   🔻 하한선({data['lower']:>6.2f}) 미달 보정 : {low_str}")
            high_str = ", ".join([f"{item[0]}({item[1]:.1f})" for item in data['high_list']]) if data['high_list'] else "없음"
            print(f"   🔺 상한선({data['upper']:>6.2f}) 초과 보정 : {high_str}\n")
        print("="*80)
    
    return df_calc

if __name__ == "__main__":
    # 단독 실행 시에는 2025년을 기준으로 리포트를 켭니다.
    df_universe = calculate_universe_zscores(target_year=2025, show_report=True)
    if df_universe is not None:
        print(df_universe[['종목명', 'Z_ROE', 'Z_FCF', 'Z_Div', 'Z_DPS']].head(10))