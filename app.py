# 파일명: app.py
import os
import streamlit as st
import pandas as pd
import numpy as np 
import plotly.express as px

from kdgro_backtester import run_index_backtest
from kdgro_scorer import calculate_universe_zscores
from kdgro_portfolio_builder import build_custom_portfolio
from kdgro_ai_analyst import generate_ai_report 
from kdgro_trader import get_access_token, get_current_holdings, execute_rebalancing, is_market_open

st.set_page_config(page_title="K-DGRO 퀀타멘탈 시스템", page_icon="📈", layout="wide")

@st.cache_data
def load_data():
    df_db = pd.read_excel("kdgro_master_db.xlsx")
    df_univ = pd.read_excel("kdgro_universe_history.xlsx")
    return df_db, df_univ

st.title("🚀 K-DGRO 퀀타멘탈 통합 시스템")
st.markdown("---")

with st.sidebar:
    st.header("⚙️ 전략 튜닝")
    w_roe = st.slider("5년 평균 ROE 비중", 0.0, 1.0, 0.30, 0.05)
    w_fcf = st.slider("총부채 대비 FCF 비중", 0.0, 1.0, 0.30, 0.05)
    w_div = st.slider("Div (배당률) 비중", 0.0, 1.0, 0.20, 0.05)
    w_dps = st.slider("DPS (배당성장) 비중", 0.0, 1.0, 0.20, 0.05)
    
    st.markdown("---")
    # 💡 [핵심 패치] 종목 수를 커스텀할 수 있는 슬라이더 추가
    top_n = st.slider("포트폴리오 편입 종목 수 (Top N)", 10, 50, 30, 5)
    
    weight_method = st.selectbox(
        "포트폴리오 구성 방식",
        options=["mcap", "equal", "score"],
        format_func=lambda x: {"mcap": "시가총액 가중", "equal": "동일 가중", "score": "팩터 점수 가중"}[x]
    )
    
    run_btn = st.button("시뮬레이션 실행", type="primary", use_container_width=True)

try:
    df_db_memory, df_univ_memory = load_data()
except Exception as e:
    st.error("🚨 원천 데이터 엑셀 파일을 찾을 수 없습니다. 데이터 수집기를 먼저 실행해 주세요.")
    st.stop()

if run_btn:
    total = w_roe + w_fcf + w_div + w_dps
    if total == 0: total = 1.0
    weights = {"ROE": w_roe/total, "FCF": w_fcf/total, "Div": w_div/total, "DPS": w_dps/total}
    
    with st.spinner("과거 데이터를 바탕으로 백테스트를 진행 중입니다..."):
        # 💡 백테스트 함수에 커스텀된 top_n 값을 전달
        df_bt, yearly_contrib = run_index_backtest(
            start_target_year=2022, 
            end_target_year=2025, 
            weights=weights, 
            top_n=top_n, 
            weight_method=weight_method,
            df_db=df_db_memory,
            df_univ=df_univ_memory
        )
        st.session_state['df_bt'] = df_bt
        st.session_state['yearly_contrib'] = yearly_contrib

    with st.spinner("연도별 포트폴리오를 스크리닝 중입니다..."):
        portfolios = {}
        for t_year in range(2022, 2026):
            r_year = t_year + 1
            df_scored = calculate_universe_zscores(t_year, df_db_memory, df_univ_memory, show_report=False)
            # 💡 빌더 함수에도 커스텀된 top_n 값을 전달
            df_port = build_custom_portfolio(df_scored, t_year, weights, top_n=top_n, weighting_method=weight_method, show_report=False)
            if df_port is not None:
                portfolios[r_year] = df_port
        
        st.session_state['portfolios'] = portfolios
        st.session_state['selected_year'] = max(portfolios.keys()) if portfolios else 2026
        
        if 'ai_report' in st.session_state:
            del st.session_state['ai_report']

tab1, tab2, tab3, tab4 = st.tabs(["시뮬레이션 결과", "연도별 포트폴리오", "AI 리포트", "📈 실전 매매 & 잔고"])

# --- [Tab 1] 백테스트 결과 ---
with tab1:
    if 'df_bt' in st.session_state and st.session_state['df_bt'] is not None:
        df_bt = st.session_state['df_bt']
        
        fig_bt = px.line(
            df_bt, 
            x=df_bt.index, 
            y=['K-DGRO_Index', 'KOSPI_Index'],
            labels={'value': '지수 (Base=1,000)', 'index': '날짜', 'variable': '구분'},
            color_discrete_map={'K-DGRO_Index': 'crimson', 'KOSPI_Index': 'royalblue'}
        )
        fig_bt.update_layout(title="K-DGRO vs KOSPI 누적 수익률 비교", hovermode="x unified", legend_title_text='')
        st.plotly_chart(fig_bt, use_container_width=True)
        
        def calc_metrics(series):
            rets = series.pct_change().dropna()
            tot_ret = (series.iloc[-1] / series.iloc[0]) - 1 if len(series) > 0 else 0
            roll_max = series.cummax()
            mdd = (series / roll_max - 1.0).min() if len(series) > 0 else 0
            sharpe = (rets.mean() / rets.std() * np.sqrt(252)) if len(rets) > 0 and rets.std() != 0 else 0
            return tot_ret, mdd, sharpe

        def apply_thick_border(row):
            if row['종목명'] == 'KOSPI':
                return ['border-bottom: 2px solid #888888'] * len(row)
            return [''] * len(row)

        st.markdown("### 🗓️ 리밸런싱 구간별 성과 비교")
        
        start_year = df_bt.index.min().year
        if df_bt.index.min().month < 5:
            start_year -= 1
            
        end_year = df_bt.index.max().year
        
        annual_data = []
        for y in range(start_year, end_year + 1):
            start_dt = f"{y}-05-01"
            end_dt = f"{y+1}-04-30"
            
            df_y = df_bt.loc[start_dt:end_dt]
            if len(df_y) < 2: continue 
            
            actual_start = df_y.index[0].strftime("%Y.%m.%d")
            actual_end = df_y.index[-1].strftime("%Y.%m.%d")
            period_str = f"{actual_start} ~ {actual_end}"
            
            kdgro_ret, kdgro_mdd, kdgro_shr = calc_metrics(df_y['K-DGRO_Index'])
            kospi_ret, kospi_mdd, kospi_shr = calc_metrics(df_y['KOSPI_Index'])
            
            div_y = st.session_state.get('yearly_contrib', {}).get(y, {}).get('div_yield', 0)
            
            annual_data.append({
                "기간": period_str, 
                "종목명": "K-DGRO", 
                "수익률": f"{kdgro_ret*100:.2f}%", 
                "MDD": f"{kdgro_mdd*100:.2f}%", 
                "샤프지수": f"{kdgro_shr:.2f}",
                "배당수익률": f"{div_y:.2f}%"  # 💡 [추가] 배당 컬럼
            })
            annual_data.append({
                "기간": "", 
                "종목명": "KOSPI", 
                "수익률": f"{kospi_ret*100:.2f}%", 
                "MDD": f"{kospi_mdd*100:.2f}%", 
                "샤프지수": f"{kospi_shr:.2f}",
                "배당수익률": "-"            # 코스피는 공란 처리
            })
            
        df_annual = pd.DataFrame(annual_data)
        if not df_annual.empty:
            st.table(df_annual.style.apply(apply_thick_border, axis=1))
        
        st.markdown("### 🏆 전체 누적 성과 요약")
        tot_kdgro_ret, tot_kdgro_mdd, tot_kdgro_shr = calc_metrics(df_bt['K-DGRO_Index'])
        tot_kospi_ret, tot_kospi_mdd, tot_kospi_shr = calc_metrics(df_bt['KOSPI_Index'])
        
        total_data = [
            {"기간": "Final (전체)", "종목명": "K-DGRO", "수익률": f"{tot_kdgro_ret*100:.2f}%", "MDD": f"{tot_kdgro_mdd*100:.2f}%", "샤프지수": f"{tot_kdgro_shr:.2f}"},
            {"기간": "", "종목명": "KOSPI", "수익률": f"{tot_kospi_ret*100:.2f}%", "MDD": f"{tot_kospi_mdd*100:.2f}%", "샤프지수": f"{tot_kospi_shr:.2f}"}
        ]
        st.table(pd.DataFrame(total_data).style.apply(apply_thick_border, axis=1))

        st.markdown("---")
        st.markdown("### 🏅 리밸런싱 구간별 핵심 기여 종목 (비중 반영)")
        if 'yearly_contrib' in st.session_state and st.session_state['yearly_contrib']:
            contrib_data = st.session_state['yearly_contrib']
            for year, data in contrib_data.items():
                with st.expander(f"📍 {year}년 5월 편입 포트폴리오 기여도 스포트라이트", expanded=(year == max(contrib_data.keys()))):
                    col_t, col_b = st.columns(2)
                    with col_t:
                        st.success("##### 🚀 수익률에 크게 기여한 종목 (Top 3)")
                        for name, c in data['top']:
                            st.write(f"- **{name}** : 기여도 **+{c:.2f}%p**")
                    with col_b:
                        st.error("##### ⚓ 발목 잡은 종목 (Bottom 3)")
                        for name, c in data['bottom']:
                            st.write(f"- **{name}** : 기여도 **{c:.2f}%p**")
        
    else:
        st.info("👈 사이드바에서 '시뮬레이션 실행' 버튼을 눌러주세요.")

# --- [Tab 2] 포트폴리오 명단 ---
with tab2:
    if 'portfolios' in st.session_state and st.session_state['portfolios']:
        portfolios = st.session_state['portfolios']
        
        r_years = sorted(list(portfolios.keys()), reverse=True)
        options = {y: f"{y}년 5월 리밸런싱 ({y-1}년 결산 기준)" for y in r_years}
        
        selected_year = st.selectbox(
            "📅 조회할 리밸런싱 시기를 선택하세요:", 
            options=r_years, 
            format_func=lambda x: options[x],
            index=r_years.index(st.session_state.get('selected_year', max(r_years)))
        )
        
        st.session_state['selected_year'] = selected_year
        port_df = portfolios[selected_year]
        
        col1, col2 = st.columns([1, 1.5])
        
        with col1:
            st.markdown(f"#### 🎯 {selected_year}년 포트폴리오 비중")
            fig_pie = px.pie(
                port_df, values='투자비중(%)', names='종목명', hole=0.4, hover_data=['종목코드']
            )
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with col2:
            st.markdown(f"#### 📋 {selected_year}년 상세 편입 종목 및 스탯")
            st.dataframe(
                port_df[['종목코드', '종목명', '투자비중(%)', 'Z_ROE', 'Z_FCF', 'Z_Div', 'Z_DPS', 'Custom_Score']],
                use_container_width=True, hide_index=True, height=500
            )
    else:
        st.info("👈 사이드바에서 '시뮬레이션 실행' 버튼을 눌러주세요.")

# --- [Tab 3] AI 애널리스트 ---
with tab3:
    st.markdown("### 🔍 실시간 AI 정성 분석")
    if 'portfolios' in st.session_state and st.session_state['portfolios']:
        
        current_port_df = st.session_state['portfolios'][st.session_state.get('selected_year', max(st.session_state['portfolios'].keys()))]
        
        stock_options = [f"{row['종목명']} ({row['종목코드']})" for _, row in current_port_df.iterrows()]
        selected_stock = st.selectbox("분석할 종목을 선택하세요:", stock_options)
        
        if st.button("AI 리포트 생성 (Gemini-2.5-Flash)"):
            name = selected_stock.split(" (")[0]
            ticker = selected_stock.split("(")[1].replace(")", "")
            
            with st.spinner(f"'{name}'의 실시간 뉴스를 검색하고 리포트를 작성 중입니다..."):
                report = generate_ai_report(name, ticker)
                st.session_state['ai_report'] = {"name": name, "report": report}
        
        if 'ai_report' in st.session_state:
            st.success("분석 완료!")
            st.markdown(f"#### 📑 {st.session_state['ai_report']['name']} 분석 리포트")
            st.info(st.session_state['ai_report']['report'])
    else:
        st.info("👈 사이드바에서 '시뮬레이션 실행' 버튼을 눌러주세요.")
with tab4:
            st.header("💸 한투 모의투자 계좌 관리")
            st.markdown("---")
            
            col1, col2 = st.columns(2)
            
            # [좌측 화면] 현재 잔고 조회 기능
            with col1:
                st.subheader("📊 현재 보유 잔고")
                if st.button("🔄 잔고 새로고침"):
                    with st.spinner("한국투자증권 서버와 통신 중..."):
                        token = get_access_token()
                        if token:
                            holdings = get_current_holdings(token)
                            if holdings:
                                import pandas as pd

                                # 💡 1. 메모리에 있는 DB에서 '종목코드:종목명' 짝꿍 사전(Dictionary) 만들기
                                ticker_to_name = dict(zip(df_db_memory['종목코드'], df_db_memory['종목명']))
                                
                                holding_data = []
                                for ticker, qty in holdings.items():
                                    # 💡 2. 외부 통신 없이 로컬 사전에서 0.001초 만에 이름 찾기 (없으면 티커 그대로 표출)
                                    name = ticker_to_name.get(ticker, ticker)
                                        
                                    holding_data.append({
                                        "종목명": name,
                                        "종목코드": ticker,
                                        "보유수량(주)": qty
                                    })
                                
                                df_holdings = pd.DataFrame(holding_data)
                                st.dataframe(df_holdings, hide_index=True, width='stretch')
                            else:
                                st.info("텅~ 계좌가 비어있습니다. 새로운 포트폴리오를 담아보세요!")
                        else:
                            st.error("API 토큰 발급 실패. .env 파일을 확인해주세요.")
            
            # [우측 화면] 자동 리밸런싱 실행 기능
            with col2:
                st.subheader("🚀 K-DGRO 자동 매매 엔진")
                st.info("왼쪽 [연도별 포트폴리오] 탭에 생성된 최신 포트폴리오 기준으로 매매를 진행합니다.")
                
                # 운용 예산 입력기
                budget_input = st.number_input(
                    "💰 투입할 총 예산 (원)", 
                    min_value=1000000, 
                    value=50000000, 
                    step=1000000,
                    format="%d"
                )
                
                if st.button("🚨 스마트 리밸런싱 즉시 실행", type="primary"):
                    
                    # 💡 [핵심 가드] 버튼을 누르자마자 장중 시간인지부터 검사!
                    if not is_market_open():
                        st.error("❌ 현재는 정규장 운영 시간이 아닙니다! (정규장 시간: 평일 09:00 ~ 15:20)")
                    
                    else:
                        # 장중이 맞다면 기존 로직대로 안전하게 매매 진행
                        if 'portfolios' in st.session_state and st.session_state['portfolios']:
                            latest_year = max(st.session_state['portfolios'].keys())
                            df_target = st.session_state['portfolios'][latest_year]
                            
                            st.warning(f"⏳ 매매 엔진이 가동되었습니다... ({latest_year}년도 포트폴리오 기준)")
                            execute_rebalancing(df_target, budget_input)
                            st.success("✅ 리밸런싱 작업이 완료되었습니다!")
                        else:
                            st.error("⚠️ 포트폴리오 데이터가 없습니다. 먼저 좌측 사이드바에서 [시뮬레이션 실행] 버튼을 눌러주세요.")