# 파일명: kdgro_trader.py
import os
import time
import requests
import json
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
_cached_token = None
_token_issue_time = None
# 모의투자 전용 URL 및 정보
URL_BASE = "https://openapivts.koreainvestment.com:29443"
APP_KEY = os.getenv("HANTU_APP_KEY")
APP_SECRET = os.getenv("HANTU_APP_SECRET")
CANO = os.getenv("HANTU_CANO")
ACNT_PRDT_CD = os.getenv("HANTU_ACNT_PRDT_CD", "01")

def is_market_open():
    """현재 시간이 정규장 운영 시간(평일 09:00 ~ 15:20)인지 확인하는 함수"""
    now = datetime.now()
    
    # 💡 1. 주말 체크 (weekday가 5는 토요일, 6은 일요일)
    if now.weekday() >= 5:
        return False
        
    # 💡 2. 정규장 시간 체크 (오전 9시 ~ 오후 3시 20분)
    if 9 <= now.hour < 15 or (now.hour == 15 and now.minute < 20):
        return True
        
    return False

def get_access_token():
    global _cached_token, _token_issue_time
    now = datetime.now()
    
    # 💡 [핵심] 이미 발급받은 토큰이 있고, 발급된 지 23시간이 지나지 않았다면 서버에 묻지 않고 바로 재사용!
    if _cached_token and _token_issue_time and now < _token_issue_time + timedelta(hours=23):
        return _cached_token

    headers = {"content-type": "application/json"}
    body = {"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET}
    url = f"{URL_BASE}/oauth2/tokenP"
    res = requests.post(url, headers=headers, data=json.dumps(body))
    
    if res.status_code == 200:
        _cached_token = res.json()["access_token"]
        _token_issue_time = now # 토큰을 새로 받은 시간 기록
        return _cached_token
        
    print(f"🚨 토큰 발급 실패: {res.text}")
    return None

def get_current_price(ticker, token):
    url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
        "appkey": APP_KEY, "appsecret": APP_SECRET, "tr_id": "FHKST01010100"
    }
    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker}
    res = requests.get(url, headers=headers, params=params)
    if res.status_code == 200 and res.json()["rt_cd"] == "0":
        return int(res.json()["output"]["stck_prpr"])
    return 0

# 💡 [신규 부품 1] 계좌 잔고 조회 함수
def get_current_holdings(token):
    """현재 계좌에 보유 중인 종목코드와 수량을 딕셔너리로 반환합니다."""
    url = f"{URL_BASE}/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = {
        "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
        "appkey": APP_KEY, "appsecret": APP_SECRET, "tr_id": "VTTC8434R", "custtype": "P"
    }
    params = {
        "CANO": CANO, "ACNT_PRDT_CD": ACNT_PRDT_CD, "AFHR_FLPR_YN": "N", "OFL_YN": "",
        "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    res = requests.get(url, headers=headers, params=params)
    holdings = {}
    
    if res.status_code == 200 and res.json().get("rt_cd") == "0":
        for item in res.json().get("output1", []):
            ticker = item["pdno"]
            qty = int(item["hldg_qty"])
            if qty > 0:
                holdings[ticker] = qty
    else:
        # 💡 [핵심] 한투 서버가 조회를 거절한 '진짜 이유'를 터미널에 출력합니다!
        print(f"🚨 잔고 조회 API 에러: {res.text}")
        
    return holdings

def order_market_buy(ticker, qty, token):
    url = f"{URL_BASE}/uapi/domestic-stock/v1/trading/order-cash"
    headers = {
        "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
        "appkey": APP_KEY, "appsecret": APP_SECRET, "tr_id": "VTTC0802U", "custtype": "P"
    }
    body = {"CANO": CANO, "ACNT_PRDT_CD": ACNT_PRDT_CD, "PDNO": ticker, "ORD_DVSN": "01", "ORD_QTY": str(qty), "ORD_UNPR": "0"}
    res = requests.post(url, headers=headers, data=json.dumps(body))
    if res.status_code == 200 and res.json()["rt_cd"] == "0":
        print(f"✅ [매수 성공] {ticker} | {qty}주")
        return True
    print(f"❌ [매수 실패] {ticker}: {res.json().get('msg1')}")
    return False

# 💡 [신규 부품 2] 시장가 매도 함수
def order_market_sell(ticker, qty, token):
    url = f"{URL_BASE}/uapi/domestic-stock/v1/trading/order-cash"
    headers = {
        "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
        "appkey": APP_KEY, "appsecret": APP_SECRET, "tr_id": "VTTC0801U", "custtype": "P" # 모의투자 매도 TR_ID
    }
    body = {"CANO": CANO, "ACNT_PRDT_CD": ACNT_PRDT_CD, "PDNO": ticker, "ORD_DVSN": "01", "ORD_QTY": str(qty), "ORD_UNPR": "0"}
    res = requests.post(url, headers=headers, data=json.dumps(body))
    if res.status_code == 200 and res.json()["rt_cd"] == "0":
        print(f"✅ [매도 성공] {ticker} | {qty}주")
        return True
    print(f"❌ [매도 실패] {ticker}: {res.json().get('msg1')}")
    return False

def execute_rebalancing(df_portfolio, total_investment_krw):
    print("\n" + "="*80)
    print(" 💸 K-DGRO 한투 모의투자 자동매매 엔진 가동 (스마트 리밸런싱)")
    print("="*80)
    
    
    
    token = get_access_token()
    if not token: return
        
    print(f"🔹 총 운용 목표 금액: {total_investment_krw:,}원")
    
    # 💡 1. 내 계좌에 들어있는 종목 싹 다 가져오기
    holdings = get_current_holdings(token)
    print(f"📊 현재 보유 중인 종목 수: {len(holdings)}개\n")
    
    portfolio_tickers = df_portfolio['종목코드'].tolist()

    # 💡 2. [탈락 종목 청산] 이번 포트폴리오에 없는 녀석들은 가차 없이 전량 매도
    for ticker, current_qty in holdings.items():
        if ticker not in portfolio_tickers:
            print(f"🗑️ [포트폴리오 제외] 종목코드 {ticker} | {current_qty}주 전량 매도 진행")
            order_market_sell(ticker, current_qty, token)
            time.sleep(1)

    print("-" * 80)

    # 💡 3. [비중 조절 매매] 목표 수량과 현재 수량의 차이(Diff)만큼만 매매
    for _, row in df_portfolio.iterrows():
        ticker = row['종목코드']
        name = row['종목명']
        weight = row['투자비중(%)'] / 100.0
        
        target_amount = total_investment_krw * weight
        current_price = get_current_price(ticker, token)
        time.sleep(1) 
        
        if current_price > 0:
            target_qty = int(target_amount // current_price) # 내가 가져야 할 완벽한 수량
            current_qty = holdings.get(ticker, 0)            # 내 계좌에 지금 있는 수량
            diff_qty = target_qty - current_qty              # 사야 할까? 팔아야 할까?
            
            if diff_qty > 0:
                print(f"🛒 [{name}] 목표 {target_qty}주 | 현재 {current_qty}주 ➡️ {diff_qty}주 '추가 매수'")
                order_market_buy(ticker, diff_qty, token)
            elif diff_qty < 0:
                sell_qty = abs(diff_qty)
                print(f"📉 [{name}] 목표 {target_qty}주 | 현재 {current_qty}주 ➡️ {sell_qty}주 '비중 축소 매도'")
                order_market_sell(ticker, sell_qty, token)
            else:
                print(f"⚖️ [{name}] 목표 {target_qty}주 | 현재 {current_qty}주 ➡️ 비중 완벽 일치 (매매 패스)")
            
            time.sleep(1)
        else:
            print(f"🚨 [{name}] 현재가 조회 실패")