import os
import json
import smtplib
import re
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import requests
from bs4 import BeautifulSoup

NAVER_USER = os.environ.get("NAVER_USER")
NAVER_PASSWORD = os.environ.get("NAVER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

TARGET_BOARDS = [
    {"name": "서울과기대 대학공지", "url": "https://www.seoultech.ac.kr/service/info/notice/"},
    {"name": "서울과기대 학사공지", "url": "https://www.seoultech.ac.kr/service/info/matters/"},
    {"name": "서울과기대 장학공지", "url": "https://www.seoultech.ac.kr/service/info/janghak/"},
    {"name": "지능형로봇전공 학부공지", "url": "https://ir.seoultech.ac.kr/bach/notice"},
    {"name": "지능형로봇전공 일반자료실", "url": "https://ir.seoultech.ac.kr/info/general_resources"}
]

DB_FILE = "seen_notices.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def fetch_board_notices(board):
    notices = []
    try:
        res = requests.get(board["url"], headers=HEADERS, timeout=12)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        for row in soup.find_all("tr"):
            if row.find("th"): continue
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
    if not new_items or not NAVER_USER: return
    sender = f"{NAVER_USER}@naver.com"
    count = len(new_items)
    subject = f"[과기대 공지] [{new_items[0]['board']}] {new_items[0]['title']}" if count == 1 else f"[과기대 공지] 신규 공지사항 {count}건이 등록되었습니다."

    # 1. 텍스트 버전 (가장 확실한 보험용 백업)
    plain_text = "🔔 서울과기대 새 공지사항\n\n"
    for item in new_items:
        plain_text += f"[{item['board']}] {item['title']}\n"
        plain_text += f"{item['link']}\n\n"

    # 2. HTML 버전 (디자인 코드를 단 하나도 넣지 않은 순수 링크 태그)
    html_body = "🔔 서울과기대 새 공지사항"
    for item in new_items:
        html_body += f"""
        ■ 게시판: [{item['board']}]
        ■ 일  자: {item['date']}
        ■ 제  목: {item['title']}
        👉 아래 링크를 터치하세요:
        {item['link']}
        
        """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = RECEIVER_EMAIL
    
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.naver.com", 465, timeout=10) as s:
        s.login(NAVER_USER, NAVER_PASSWORD)
        s.sendmail(sender, RECEIVER_EMAIL, msg.as_string())
    print(f"알림 메일 발송 완료 ({count}건)")

def main():
    seen = set()
    first_run = not os.path.exists(DB_FILE)
    if not first_run:
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                seen = set(json.load(f))
        except: pass

    all_current = []
    for b in TARGET_BOARDS:
        all_current.extend(fetch_board_notices(b))

    new_items = []
    for item in all_current:
        if item["id"] not in seen:
            seen.add(item["id"])
            if not first_run:
                new_items.append(item)

    if new_items:
        send_alert(new_items)
    else:
        print("새로운 공지사항 없음.")

    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
