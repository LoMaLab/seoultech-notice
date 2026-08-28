import os
import json
import smtplib
import re
import urllib.parse
import hashlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import requests
from bs4 import BeautifulSoup

NAVER_USER = os.environ.get("NAVER_USER")
NAVER_PASSWORD = os.environ.get("NAVER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

# 1. 일반 공지사항 게시판 (신규 게시글 감시)
TARGET_BOARDS = [
    {"name": "서울과기대 대학공지", "url": "https://www.seoultech.ac.kr/service/info/notice/"},
    {"name": "서울과기대 학사공지", "url": "https://www.seoultech.ac.kr/service/info/matters/"},
    {"name": "서울과기대 장학공지", "url": "https://www.seoultech.ac.kr/service/info/janghak/"},
    {"name": "지능형로봇전공 학부공지", "url": "https://ir.seoultech.ac.kr/bach/notice"},
    {"name": "지능형로봇전공 일반자료실", "url": "https://ir.seoultech.ac.kr/info/general_resources"}
]

# 2. MOAI 연구실 웹페이지 (내용/멤버/논문/갤러리 변경 감시)
TARGET_PAGES = [
    {"name": "MOAI 연구실 - Home", "url": "https://moai.seoultech.ac.kr/home"},
    {"name": "MOAI 연구실 - People", "url": "https://moai.seoultech.ac.kr/people"},
    {"name": "MOAI 연구실 - Publications", "url": "https://moai.seoultech.ac.kr/publications"},
    {"name": "MOAI 연구실 - Gallery", "url": "https://moai.seoultech.ac.kr/gallery"}
]

DB_FILE = "seen_notices.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ==========================================
# [기능 1] 일반 공지사항 게시판 크롤링
# ==========================================
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
                        "date": date_val,
                        "type": "board"
                    })
                    break
    except Exception as e:
        print(f"[{board['name']}] 수집 에러: {e}")
    return notices

# ==========================================
# [기능 2] MOAI 연구실 페이지 내용 변경 감시
# ==========================================
def fetch_page_changes(page, seen_set, is_first_run):
    """웹페이지의 본문 텍스트 및 링크 상태를 해시로 비교하여 변경 감지"""
    detected_changes = []
    prefix = f"PAGE_{page['name']}_"
    
    try:
        res = requests.get(page["url"], headers=HEADERS, timeout=12)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 불필요한 스크립트, 스타일 태그 제거
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        
        # 페이지 본문 텍스트 및 이미지/링크 주소 추출 후 고유 해시 생성
        page_text = " ".join(soup.stripped_strings)
        img_srcs = "".join([img.get("src", "") for img in soup.find_all("img")])
        a_hrefs = "".join([a.get("href", "") for a in soup.find_all("a")])
        combined_content = page_text + img_srcs + a_hrefs
        
        current_hash = hashlib.sha256(combined_content.encode("utf-8")).hexdigest()
        current_key = f"{prefix}{current_hash}"
        
        # 이전 해시 키 검색
        old_keys = [k for k in seen_set if k.startswith(prefix)]
        
        if not old_keys:
            # 최초 등록 시
            seen_set.add(current_key)
            print(f"[{page['name']}] 기준 상태 등록 완료.")
        elif current_key not in seen_set:
            # 해시가 변경됨 = 내용 수정/추가 발생!
            for old_k in old_keys:
                seen_set.remove(old_k)
            seen_set.add(current_key)
            
            if not is_first_run:
                detected_changes.append({
                    "id": current_key,
                    "board": page["name"],
                    "title": f"[{page['name'].replace('MOAI 연구실 - ', '')}] 페이지에 새로운 업데이트/내용 변경이 감지되었습니다.",
                    "link": page["url"],
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "type": "page"
                })
                print(f"[{page['name']}] 내용 변경 감지!")
    except Exception as e:
        print(f"[{page['name']}] 페이지 확인 중 오류: {e}")
        
    return detected_changes

# ==========================================
# [기능 3] 네이버 메일 알림 발송
# ==========================================
def send_alert(new_items):
    if not new_items or not NAVER_USER: return
    sender = f"{NAVER_USER}@naver.com"
    count = len(new_items)
    
    if count == 1:
        subject = f"[과기대/연구실] [{new_items[0]['board']}] {new_items[0]['title']}"
    else:
        subject = f"[과기대/연구실] 신규 공지 및 업데이트 {count}건이 감지되었습니다."

    # 1. 텍스트 본문 (일반 텍스트 뷰어용)
    plain_text = "🔔 서울과기대 & MOAI 연구실 실시간 업데이트 알림\n\n"
    for item in new_items:
        tag = "📌 [공지사항]" if item.get("type") == "board" else "🔬 [연구실 업데이트]"
        plain_text += f"{tag} [{item['board']}] {item['date']}\n"
        plain_text += f"제목/내용: {item['title']}\n"
        plain_text += f"바로가기: {item['link']}\n\n"

    # 2. HTML 본문 (모바일 최적화 및 터치 링크)
    html_items = ""
    for item in new_items:
        is_page = (item.get("type") == "page")
        badge_color = "#e67e22" if is_page else "#005bac"
        badge_text = "🔬 연구실 페이지 업데이트" if is_page else "📌 학교 공지사항"
        
        html_items += f"""
        <div style="border: 2px solid {badge_color}; background-color: #f8fafd; padding: 16px; margin-bottom: 18px; border-radius: 8px;">
            <div style="margin: 0 0 8px 0; font-size: 13px; font-weight: bold; color: {badge_color};">
                <span style="background-color: {badge_color}; color: #ffffff; padding: 2px 6px; border-radius: 4px; font-size: 11px;">{badge_text}</span>
                &nbsp; [{item['board']}] &nbsp;|&nbsp; 📅 {item['date']}
            </div>
            <div style="margin: 0 0 14px 0; font-size: 16px; font-weight: bold; line-height: 1.4;">
                <a href="{item['link']}" target="_blank" style="color: #111111; text-decoration: underline;">
                    {item['title']}
                </a>
            </div>
            <hr style="border: 0; border-top: 1px dashed #ced4da; margin: 12px 0;">
            <div style="margin: 0 0 6px 0;">
                <a href="{item['link']}" target="_blank" style="color: {badge_color}; font-weight: bold; font-size: 15px; text-decoration: underline;">
                    👉 [ 🔗 해당 페이지 바로가기 (터치) ]
                </a>
            </div>
            <div style="margin: 6px 0 0 0; font-size: 12px; color: #666666; word-break: break-all;">
                주소: <a href="{item['link']}" target="_blank" style="color: #0066cc;">{item['link']}</a>
            </div>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: 'Malgun Gothic', -apple-system, sans-serif; padding: 12px; margin: 0; background-color: #ffffff;">
        <div style="max-width: 600px; margin: 0 auto;">
            <h2 style="color: #005bac; margin-top: 0; border-bottom: 3px solid #005bac; padding-bottom: 8px;">
                🔔 서울과기대 & MOAI Lab 실시간 알림
            </h2>
            {html_items}
            <p style="font-size: 11px; color: #888888; text-align: center; margin-top: 20px; border-top: 1px solid #eeeeee; padding-top: 10px;">
                서울과기대 공지 및 MOAI 연구실 24시간 실시간 모니터링 시스템
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

# ==========================================
# [기능 4] 메인 통합 검사 루틴
# ==========================================
def main():
    seen_set = set()
    first_run = not os.path.exists(DB_FILE)
    if not first_run:
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                seen_set = set(json.load(f))
        except: pass

    new_alerts = []

    # 1. 5개 일반 공지사항 검사
    for b in TARGET_BOARDS:
        current_notices = fetch_board_notices(b)
        for item in current_notices:
            if item["id"] not in seen_set:
                seen_set.add(item["id"])
                if not first_run:
                    new_alerts.append(item)

    # 2. MOAI 연구실 4개 페이지 변경 검사
    for p in TARGET_PAGES:
        page_changes = fetch_page_changes(p, seen_set, first_run)
        new_alerts.extend(page_changes)

    # 3. 신규 글/변경사항 발견 시 메일 발송
    if new_alerts:
        send_alert(new_alerts)
    else:
        print("신규 공지사항 및 페이지 변경 없음.")

    # 4. 상태 저장
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_set), f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
