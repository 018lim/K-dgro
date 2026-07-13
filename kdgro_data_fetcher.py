# 파일명: kdgro_data_fetcher.py
import os
import time
import re
import pandas as pd
import OpenDartReader
from pykrx import stock
from tqdm import tqdm
from datetime import datetime
from dotenv import load_dotenv

# 단독 실행될 때를 대비한 안전장치
load_dotenv() 

# 💡 [수정 1 & 2] 파라미터에서 api_key를 없애고, 연도를 자동 계산하도록 변경!
def build_kdgro_data_lake(target_years=None):
    print("🚀 [Phase 1] K-DGRO 합집합 데이터 레이크 구축 가동...\n")
    
    # 스스로 환경변수에서 API KEY를 찾습니다.
    api_key = os.getenv("DART_API_KEY")
    if not api_key:
        print("🚨 .env 파일에 DART_API_KEY가 설정되지 않았습니다.")
        return

    # 연도가 안 들어오면 알아서 최근 3개년으로 세팅합니다.
    if target_years is None:
        current_year = datetime.now().year
        # 현재 연도 기준 작년, 재작년, 3년 전 결산 연도 (예: 2026년이면 [2023, 2024, 2025])
        target_years = [current_year - 3, current_year - 2, current_year - 1]
        
    all_tickers = set()
    universe_dict = {}
    price_dict = {}
    
    min_year = min(target_years) - 4
    max_year = max(target_years)
    print(f"📊 스캔 타임라인: {min_year}년 ~ {max_year}년 (총 {max_year - min_year + 1}개년)")
    
    print("⏳ 연도별 기준 주가 및 코스피 유니버스 스캔 중...")
    for y in range(min_year, max_year + 1):
        rebalance_year = y + 1
        start_date = f"{rebalance_year}0501"
        end_date = f"{rebalance_year}0515"
        
        df_ohlcv = stock.get_market_ohlcv(start_date, end_date, "005930")
        if df_ohlcv is not None and not df_ohlcv.empty:
            first_b_day = df_ohlcv.index[0].strftime("%Y%m%d")
            df_cap = stock.get_market_cap(first_b_day, market="KOSPI")
            
            if y in target_years:
                top_n = df_cap.sort_values(by="시가총액", ascending=False).head(200).index.tolist()
                universe_dict[y] = top_n
                all_tickers.update(top_n)
                print(f"✅ {y}결산 기준 상위 200 유니버스 확보 (기준일: {first_b_day})")
            
            for tk in df_cap.index:
                price_dict[(y, tk)] = df_cap.loc[tk, "종가"]
        
    print(f"\n🎯 최종 스캔 대상: 중복이 제거된 합집합 총 {len(all_tickers)}개 종목\n")

    dart = OpenDartReader(api_key)
    raw_db = []
    
    for ticker in tqdm(all_tickers, desc="합집합 로컬 DB 원장 스캐닝"):
        name = stock.get_market_ticker_name(ticker)
        actual_ticker = ticker[:-1] + '0' if ticker[-1] != '0' else ticker
        
        try: corp_info = dart.company(actual_ticker)
        except: corp_info = {}
        is_fin = str(corp_info.get('induty_code', '')).startswith(('64', '65', '66'))
        sector = "금융업" if is_fin else "일반기업"
        
        for scan_year in range(min_year, max_year + 1):
            roe, fcf_to_debt, div_yield, dps = None, None, None, None
            
            try:
                df_rep = dart.report(actual_ticker, '배당', scan_year)
                if df_rep is not None and not df_rep.empty:
                    df_rep['se'] = df_rep['se'].fillna('').astype(str).str.replace(' ', '')
                    df_rep['stock_knd'] = df_rep['stock_knd'].fillna('').astype(str).str.replace(' ', '') if 'stock_knd' in df_rep.columns else ''
                    target_rep = df_rep[(df_rep['se'].str.contains('주당') & df_rep['se'].str.contains('배당')) & (~df_rep['stock_knd'].str.contains('우선주'))]
                    if target_rep.empty: target_rep = df_rep[df_rep['se'].str.contains('현금배당금') & ~df_rep['se'].str.contains('총액|성향|수익률') & (~df_rep['stock_knd'].str.contains('우선주'))]
                    
                    if not target_rep.empty:
                        dps_clean = re.sub(r'[^0-9.]', '', str(target_rep.iloc[0]['thstrm']))
                        if dps_clean: 
                            dps = int(float(dps_clean))
                            rb_price = price_dict.get((scan_year, actual_ticker))
                            if rb_price and rb_price > 0:
                                div_yield = (dps / rb_price) * 100
            except: pass
            
            time.sleep(0.1)

            try:
                df_fin = dart.finstate_all(actual_ticker, scan_year, reprt_code="11011", fs_div="CFS")
                if df_fin is not None and not df_fin.empty:
                    df_fin['clean_acc'] = df_fin['account_nm'].astype(str).str.replace(' ', '')
                    df_fin['clean_sj'] = df_fin['sj_nm'].astype(str).str.replace(' ', '')

                    target_eq = df_fin[(df_fin['clean_sj'].str.contains('재무상태')) & (df_fin['clean_acc'].str.contains('지배기업|지배주주')) & (df_fin['clean_acc'].str.contains('자본|지분'))]
                    if target_eq.empty: target_eq = df_fin[(df_fin['clean_sj'].str.contains('재무상태')) & (df_fin['clean_acc'].str.contains('자본총계|자본합계|기말자본'))]
                    target_ni = df_fin[(df_fin['clean_sj'].str.contains('손익|포괄')) & (df_fin['clean_acc'].str.contains('지배기업|지배주주')) & (df_fin['clean_acc'].str.contains('당기순이익|순이익'))]
                    if target_ni.empty: target_ni = df_fin[(df_fin['clean_sj'].str.contains('손익|포괄')) & (df_fin['clean_acc'].str.contains('당기순') & ~df_fin['clean_acc'].str.contains('포괄|비지배'))]
                    
                    if not target_eq.empty and not target_ni.empty:
                        eq_end = float(str(target_eq.iloc[0]['thstrm_amount']).replace(',','').strip())
                        ni = float(str(target_ni.iloc[0]['thstrm_amount']).replace(',','').strip())
                        try: eq_begin = float(str(target_eq.iloc[0]['frmtrm_amount']).replace(',','').strip())
                        except: eq_begin = eq_end
                        if (eq_begin + eq_end) / 2 > 0: roe = (ni / ((eq_begin + eq_end) / 2)) * 100

                    if not is_fin:
                        target_debt = df_fin[(df_fin['clean_sj'].str.contains('재무상태')) & (df_fin['clean_acc'].str.contains('부채총계|부채합계'))]
                        target_cfo = df_fin[(df_fin['clean_sj'].str.contains('현금흐름')) & (df_fin['clean_acc'].str.contains('영업활동') & df_fin['clean_acc'].str.contains('현금흐름'))]
                        cond_ppe = (df_fin['clean_sj'].str.contains('현금흐름')) & (df_fin['clean_acc'].str.contains('유형자산') & df_fin['clean_acc'].str.contains('취득|증가|지출') & ~df_fin['clean_acc'].str.contains('처분|감소'))
                        cond_int = (df_fin['clean_sj'].str.contains('현금흐름')) & (df_fin['clean_acc'].str.contains('무형자산') & df_fin['clean_acc'].str.contains('취득|증가|지출') & ~df_fin['clean_acc'].str.contains('처분|감소'))
                        
                        if not target_debt.empty and not target_cfo.empty:
                            td = float(str(target_debt.iloc[0]['thstrm_amount']).replace(',','').strip())
                            cf = float(str(target_cfo.iloc[0]['thstrm_amount']).replace(',','').strip())
                            cx_p = abs(float(str(df_fin[cond_ppe].iloc[0]['thstrm_amount']).replace(',','').strip())) if not df_fin[cond_ppe].empty else 0.0
                            cx_i = abs(float(str(df_fin[cond_int].iloc[0]['thstrm_amount']).replace(',','').strip())) if not df_fin[cond_int].empty else 0.0
                            if td > 0: fcf_to_debt = ((cf - (cx_p + cx_i)) / td) * 100
            except: pass
            time.sleep(0.1)

            raw_db.append({
                "종목명": name, "종목코드": ticker, "섹터": sector, "회계연도": scan_year,
                "단년도_ROE(%)": roe, "단년도_FCF_to_Debt(%)": fcf_to_debt,
                "단년도_Div_Yield(%)": div_yield, "단년도_DPS(원)": dps
            })

    df_new = pd.DataFrame(raw_db)
    if os.path.exists("kdgro_master_db.xlsx"):
        print("\n💾 기존 데이터베이스 파일 발견. 수동 편집본 보존 병합을 시작합니다...")
        df_old = pd.read_excel("kdgro_master_db.xlsx")
        df_old['종목코드'] = df_old['종목코드'].astype(str).str.zfill(6)
        df_new['종목코드'] = df_new['종목코드'].astype(str).str.zfill(6)
        
        df_merged = pd.merge(df_old, df_new, on=['종목명', '종목코드', '섹터', '회계연도'], how='outer', suffixes=('_old', '_new'))
        
        for col in ["단년도_ROE(%)", "단년도_FCF_to_Debt(%)", "단년도_Div_Yield(%)", "단년도_DPS(원)"]:
            df_merged[col] = df_merged[f"{col}_old"].combine_first(df_merged[f"{col}_new"])
            df_merged.drop(columns=[f"{col}_old", f"{col}_new"], inplace=True)
        df_db = df_merged
    else:
        df_db = df_new

    df_db.to_excel("kdgro_master_db.xlsx", index=False)
    df_univ = pd.DataFrame(dict([(k, pd.Series(v)) for k, v in universe_dict.items()]))
    df_univ.to_excel("kdgro_universe_history.xlsx", index=False)

    print("\n" + "="*80)
    print("💾 원장 DB 및 유니버스 명단 기록 완료")
    print("="*80)

# 💡 [수정 3] 단독 실행 모드 추가
if __name__ == "__main__":
    build_kdgro_data_lake()