import os
import json
import smtplib
import re
import urllib.parse
import hashlib
import urllib3
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# SSL 인증서 경고 숨김 처리
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

NAVER_USER = os.environ.get("NAVER_USER")
NAVER_PASSWORD = os.environ.get("NAVER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

# 1. [원래 코드 유지] 서울과기대 5대 공지사항 게시판
TARGET_BOARDS = [
    {"name": "서울과기대 대학공지", "url": "https://www.seoultech.ac.kr/service/info/notice/"},
    {"name": "서울과기대 학사공지", "url": "https://www.seoultech.ac.kr/service/info/matters/"},
    {"name": "서울과기대 장학공지", "url": "https://www.seoultech.ac.kr/service/info/janghak/"},
    {"name": "지능형로봇전공 학부공지", "url": "https://ir.seoultech.ac.kr/bach/notice"},
    {"name": "지능형로봇전공 일반자료실", "url": "https://ir.seoultech.ac.kr/info/general_resources"}
]

# 2. [새 글자/사진 감지] MOAI 연구실 웹페이지
TARGET_PAGES = [
    {"name": "MOAI 연구실 - Home", "url": "https://moai.seoultech.ac.kr/home"},
    {"name": "MOAI 연구실 - People", "url": "https://moai.seoultech.ac.kr/people"},
    {"name": "MOAI 연구실 - Publications", "url": "https://moai.seoultech.ac.kr/publications"},
    {"name": "MOAI 연구실 - Gallery", "url": "https://moai.seoultech.ac.kr/gallery"}
]

# 구글 사이트 기본 메뉴/시스템 문구 필터링 (노이즈 방지)
GOOGLE_SITE_BOILERPLATE = {
    "search this site", "embedded files", "skip to main content", "skip to navigation",
    "report abuse", "page updated", "terms", "privacy", "more", "home", "people",
    "publications", "gallery", "motion & action intelligence lab"
}

DB_FILE = "seen_notices.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ==========================================================
# [기능 1] 서울과기대 공지사항 크롤러 (기존 방식 100% 유지)
# ==========================================================
def fetch_board_notices(board):
    notices = []
    try:
        res = requests.get(board["url"], headers=HEADERS, timeout=15, verify=False)
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

# ==========================================================
# [기능 2] MOAI 연구실: '실제 새 글자/새 사진'만 족집게 감지
# ==========================================================
def check_moai_page_items(page, seen_set):
    """실제 화면에 표시되는 텍스트 문장과 이미지 파일만 추출하여 새 항목 감지"""
    new_items_found = []
    page_name = page["name"]
    init_flag = f"INIT_MOAI_{page_name}"
    is_page_first_run = (init_flag not in seen_set)
    
    try:
        res = requests.get(page["url"], headers=HEADERS, timeout=15, verify=False)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        # 1. 구글 시스템/스크립트/스타일 태그 완전 제거
        for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "aside", "meta", "input", "form", "button"]):
            tag.decompose()
            
        # 2. 눈에 보이는 실제 텍스트 문장 추출 (길이 3자 이상)
        visible_sentences = []
        for text in soup.stripped_strings:
            cleaned = re.sub(r'\s+', ' ', text).strip()
            if len(cleaned) >= 3 and cleaned.lower() not in GOOGLE_SITE_BOILERPLATE:
                visible_sentences.append(cleaned)
                
        # 3. 실제 이미지(사진) 파일 추출
        visible_images = []
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if src:
                # 구글 시스템 아이콘 제외, 실제 업로드된 이미지 식별
                clean_path = urllib.parse.urlparse(src).path
                if not any(icon in clean_path.lower() for icon in ["cleardot", "transparent", "icon"]):
                    visible_images.append(src)

        # 4. 새로 생긴 텍스트 문장 검사
        new_texts = []
        for sentence in visible_sentences:
            sentence_hash = hashlib.md5(sentence.encode("utf-8")).hexdigest()
            item_id = f"MOAI_TXT_{page_name}_{sentence_hash}"
            if item_id not in seen_set:
                seen_set.add(item_id)
                if not is_page_first_run:
                    new_texts.append(sentence)
                    
        # 5. 새로 생긴 사진 검사
        new_imgs = []
        for img_url in visible_images:
            img_hash = hashlib.md5(img_url.encode("utf-8")).hexdigest()
            item_id = f"MOAI_IMG_{page_name}_{img_hash}"
            if item_id not in seen_set:
                seen_set.add(item_id)
                if not is_page_first_run:
                    new_imgs.append(img_url)

        # 최초 실행 시 기준 데이터 저장 완료 표시
        if is_page_first_run:
            seen_set.add(init_flag)
            print(f"[{page_name}] 기존 글자({len(visible_sentences)}개) 및 사진({len(visible_images)}개) 등록 완료 (첫 알림 생략).")
            return []

        # 새로 추가된 실제 글자나 사진이 있을 때만 알림 목록 생성
        if new_texts or new_imgs:
            summary_parts = []
            if new_texts:
                preview = new_texts[0] if len(new_texts[0]) <= 35 else new_texts[0][:35] + "..."
                summary_parts.append(f"새 텍스트 {len(new_texts)}개 (예: \"{preview}\")")
            if new_imgs:
                summary_parts.append(f"새 사진 {len(new_imgs)}장")
                
            summary_title = " / ".join(summary_parts)
            
            new_items_found.append({
                "id": f"ALERT_{page_name}_{datetime.now().timestamp()}",
                "board": page_name,
                "title": f"[{page_name.replace('MOAI 연구실 - ', '')}] {summary_title} 추가 감지",
                "link": page["url"],
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "type": "page",
                "details": new_texts
            })
            print(f"[{page_name}] 실제 새 글자/사진 발견: {summary_title}")

    except Exception as e:
        print(f"[{page_name}] 확인 중 에러: {e}")
        
    return new_items_found

# ==========================================================
# [기능 3] 네이버 메일 알림 발송 (가독성 및 링크 최적화)
# ==========================================================
def send_alert(new_items):
    if not new_items or not NAVER_USER: return
    sender = f"{NAVER_USER}@naver.com"
    count = len(new_items)
    
    if count == 1:
        subject = f"[과기대/연구실] [{new_items[0]['board']}] {new_items[0]['title']}"
    else:
        subject = f"[과기대/연구실] 신규 공지 및 업데이트 {count}건이 감지되었습니다."

    # 1. 텍스트 본문
    plain_text = "🔔 서울과기대 & MOAI 연구실 실시간 업데이트 알림\n\n"
    for item in new_items:
        tag = "📌 [학교 공지]" if item.get("type") == "board" else "🔬 [연구실 새 글/사진]"
        plain_text += f"{tag} [{item['board']}] {item['date']}\n"
        plain_text += f"내용: {item['title']}\n"
        plain_text += f"바로가기: {item['link']}\n\n"

    # 2. HTML 본문
    html_items = ""
    for item in new_items:
        is_page = (item.get("type") == "page")
        badge_color = "#e67e22" if is_page else "#005bac"
        badge_text = "🔬 연구실 새 글/사진 추가" if is_page else "📌 학교 공지사항"
        
        detail_html = ""
        if item.get("details"):
            detail_list = "".join([f"<li style='margin-bottom: 4px;'>{d}</li>" for d in item["details"][:5]])
            detail_html = f"<div style='background: #ffffff; border: 1px solid #dee2e6; padding: 10px 14px; border-radius: 4px; font-size: 13px; color: #333; margin: 10px 0;'><strong>새로 추가된 내용:</strong><ul style='margin: 6px 0 0 0; padding-left: 20px;'>{detail_list}</ul></div>"

        html_items += f"""
        <div style="border: 2px solid {badge_color}; background-color: #f8fafd; padding: 16px; margin-bottom: 18px; border-radius: 8px;">
            <div style="margin: 0 0 8px 0; font-size: 13px; font-weight: bold; color: {badge_color};">
                <span style="background-color: {badge_color}; color: #ffffff; padding: 2px 6px; border-radius: 4px; font-size: 11px;">{badge_text}</span>
                &nbsp; [{item['board']}] &nbsp;|&nbsp; 📅 {item['date']}
            </div>
            <div style="margin: 0 0 10px 0; font-size: 16px; font-weight: bold; line-height: 1.4;">
                <a href="{item['link']}" target="_blank" style="color: #111111; text-decoration: underline;">
                    {item['title']}
                </a>
            </div>
            {detail_html}
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

# ==========================================================
# [기능 4] 메인 실행 루틴
# ==========================================================
def main():
    seen_set = set()
    first_run = not os.path.exists(DB_FILE)
    if not first_run:
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                seen_set = set(json.load(f))
        except: pass

    new_alerts = []

    # 1. 학교 공지사항 5개 게시판 검사 (기존 그대로)
    for b in TARGET_BOARDS:
        current_notices = fetch_board_notices(b)
        for item in current_notices:
            if item["id"] not in seen_set:
                seen_set.add(item["id"])
                if not first_run:
                    new_alerts.append(item)

    # 2. MOAI 연구실 4개 페이지: 실제 새 글자/사진만 검사
    for p in TARGET_PAGES:
        page_alerts = check_moai_page_items(p, seen_set)
        new_alerts.extend(page_alerts)

    # 3. 신규 항목 발견 시에만 메일 발송
    if new_alerts:
        send_alert(new_alerts)
    else:
        print("신규 공지사항 및 새 텍스트/사진 없음 (정상 대기 중).")

    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_set), f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
