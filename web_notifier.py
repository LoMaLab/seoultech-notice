import os
import json
import smtplib
import re
import urllib.parse
import urllib3
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# SSL 인증서 경고 숨김
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

NAVER_USER = os.environ.get("NAVER_USER")
NAVER_PASSWORD = os.environ.get("NAVER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

# 서울과학기술대학교 5대 공지사항 게시판
TARGET_BOARDS = [
    {"name": "서울과기대 대학공지", "url": "https://www.seoultech.ac.kr/service/info/notice/"},
    {"name": "서울과기대 학사공지", "url": "https://www.seoultech.ac.kr/service/info/matters/"},
    {"name": "서울과기대 장학공지", "url": "https://www.seoultech.ac.kr/service/info/janghak/"},
    {"name": "지능형로봇전공 학부공지", "url": "https://ir.seoultech.ac.kr/bach/notice"},
    {"name": "지능형로봇전공 일반자료실", "url": "https://ir.seoultech.ac.kr/info/general_resources"}
]

DB_FILE = "seen_notices.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_board_notices(board):
    """각 공지사항 게시판에서 최신 글 목록 추출"""
    notices = []
    try:
        res = requests.get(board["url"], headers=HEADERS, timeout=15, verify=False)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        for row in soup.find_all("tr"):
            if row.find("th"): 
                continue
            for a in row.find_all("a"):
                href = a.get("href", "")
                title = a.get_text(strip=True)
                if ("bidx" in href or "commonview" in href or "view" in href) and len(title) > 2:
                    title = re.sub(r'\[새글\]|\[NEW\]|new', '', title, flags=re.IGNORECASE).strip()
                    full_link = urllib.parse.urljoin(board["url"], href)
                    
                    bidx_match = re.search(r'bidx=(\d+)', href)
                    post_id = f"{board['name']}_{bidx_match.group(1)}" if bidx_match else f"{board['name']}_{full_link}"
                    
                    date_val = datetime.now().strftime("%Y-%m-%d")
                    for td in row.find_all("td"):
                        text = td.get_text(strip=True)
                        if re.match(r'^\d{4}[-.]\d{2}[-.]\d{2}$', text):
                            date_val = text
                            break
                    
                    notices.append({
                        "id": post_id,
                        "board": board["name"],
                        "title": title,
                        "link": full_link,
                        "date": date_val
                    })
                    break
    except Exception as e:
        print(f"[{board['name']}] 수집 에러: {e}")
    return notices

def send_alert(new_items):
    """새 공지사항 알림 메일 발송"""
    if not new_items or not NAVER_USER: 
        return
    sender = f"{NAVER_USER}@naver.com"
    count = len(new_items)
    
    if count == 1:
        subject = f"[과기대 공지] [{new_items[0]['board']}] {new_items[0]['title']}"
    else:
        subject = f"[과기대 공지] 신규 공지사항 {count}건이 등록되었습니다."

    # 1. 텍스트 본문
    plain_text = "🔔 서울과기대 신규 공지사항 알림\n\n"
    for item in new_items:
        plain_text += f"■ [{item['board']}] {item['date']}\n"
        plain_text += f"제목: {item['title']}\n"
        plain_text += f"링크: {item['link']}\n\n"

    # 2. HTML 본문 (모바일 터치 최적화)
    html_items = ""
    for item in new_items:
        html_items += f"""
        <div style="border: 2px solid #005bac; background-color: #f4f8fb; padding: 16px; margin-bottom: 20px; border-radius: 8px;">
            <p style="margin: 0 0 8px 0; font-size: 14px; font-weight: bold; color: #005bac;">
                📌 [{item['board']}] &nbsp;|&nbsp; 📅 {item['date']}
            </p>
            <p style="margin: 0 0 14px 0; font-size: 17px; font-weight: bold; line-height: 1.4;">
                <a href="{item['link']}" target="_blank" style="color: #003366; text-decoration: underline;">
                    {item['title']}
                </a>
            </p>
            <hr style="border: 0; border-top: 1px dashed #b0c4de; margin: 12px 0;">
            <p style="margin: 0 0 6px 0; font-size: 15px;">
                <a href="{item['link']}" target="_blank" style="color: #005bac; font-weight: bold; font-size: 15px; text-decoration: underline;">
                    👉 [ 🔗 공지 본문 바로가기 (터치) ]
                </a>
            </p>
            <p style="margin: 6px 0 0 0; font-size: 12px; color: #555555; word-break: break-all;">
                바로가기 주소: <a href="{item['link']}" target="_blank" style="color: #0066cc;">{item['link']}</a>
            </p>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: 'Malgun Gothic', -apple-system, sans-serif; padding: 12px; margin: 0; background-color: #ffffff;">
        <div style="max-width: 600px; margin: 0 auto;">
            <h2 style="color: #005bac; margin-top: 0; border-bottom: 3px solid #005bac; padding-bottom: 8px;">
                🔔 서울과기대 신규 공지사항
            </h2>
            {html_items}
            <p style="font-size: 12px; color: #888888; text-align: center; margin-top: 20px; border-top: 1px solid #eeeeee; padding-top: 10px;">
                서울과학기술대학교 24시간 실시간 공지 알림 시스템
            </p>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = RECEIVER_EMAIL
    
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.naver.com", 465, timeout=10) as s:
        s.login(NAVER_USER, NAVER_PASSWORD)
        s.sendmail(sender, RECEIVER_EMAIL, msg.as_string())
    print(f"알림 메일 발송 완료 ({count}건)")

def main():
    seen_set = set()
    first_run = not os.path.exists(DB_FILE)
    if not first_run:
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                seen_set = set(json.load(f))
        except: 
            pass

    new_alerts = []

    # 5대 공지사항 게시판만 검사
    for b in TARGET_BOARDS:
        current_notices = fetch_board_notices(b)
        for item in current_notices:
            if item["id"] not in seen_set:
                seen_set.add(item["id"])
                if not first_run:
                    new_alerts.append(item)

    if new_alerts:
        send_alert(new_alerts)
    else:
        print("신규 공지사항 없음 (정상 대기 중).")

    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_set), f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
