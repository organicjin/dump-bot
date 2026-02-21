import os
import logging
from datetime import datetime, timezone, timedelta

import anthropic
from dotenv import load_dotenv
from notion_client import Client as NotionClient
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
NOTION_API_KEY = (os.getenv("NOTION_API_KEY") or "").strip()
NOTION_DB_ID = (os.getenv("NOTION_DB_ID") or "").strip()
ANTHROPIC_API_KEY = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
CHAT_ID = (os.getenv("CHAT_ID") or "").strip()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

CATEGORIES = ["아이디어", "인사이트", "마케팅/업무", "기타"]

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
notion = NotionClient(auth=NOTION_API_KEY) if NOTION_API_KEY else None


# ───────────────────────────── Claude 분류 ─────────────────────────────

def classify(text: str) -> dict:
    """Claude API로 텍스트를 카테고리 분류하고 한줄요약 생성"""
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": (
                    f"다음 텍스트를 분류하고 한줄요약해줘.\n\n"
                    f"카테고리 목록: {', '.join(CATEGORIES)}\n"
                    f"텍스트: {text}\n\n"
                    f"반드시 아래 형식으로만 답변해. 다른 말 붙이지 마.\n"
                    f"카테고리: (카테고리명)\n"
                    f"한줄요약: (요약)"
                ),
            }
        ],
    )

    result_text = response.content[0].text.strip()
    category = "기타"
    summary = text[:50]

    for line in result_text.split("\n"):
        line = line.strip()
        if line.startswith("카테고리:"):
            parsed = line.replace("카테고리:", "").strip()
            if parsed in CATEGORIES:
                category = parsed
        elif line.startswith("한줄요약:"):
            summary = line.replace("한줄요약:", "").strip()

    return {"category": category, "summary": summary}


# ───────────────────────────── Notion 저장 ─────────────────────────────

def save_to_notion(text: str, category: str, summary: str):
    """Notion DB에 페이지 생성"""
    now_kst = datetime.now(KST).strftime("%Y-%m-%d")

    notion.pages.create(
        parent={"database_id": NOTION_DB_ID},
        properties={
            "내용": {
                "title": [{"text": {"content": text[:2000]}}]
            },
            "카테고리": {
                "select": {"name": category}
            },
            "날짜": {
                "date": {"start": now_kst}
            },
            "한줄요약": {
                "rich_text": [{"text": {"content": summary[:2000]}}]
            },
        },
    )


# ───────────────────────────── 핸들러 ─────────────────────────────

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"✅ 생각 덤프 봇 등록 완료!\n\n"
        f"당신의 chat_id: {chat_id}\n\n"
        f"Railway 배포 시 이 값을 CHAT_ID 환경변수에 입력하세요.",
    )


async def handle_message(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """텍스트 메시지 수신 → Claude 분류 → Notion 저장"""
    if CHAT_ID and str(update.effective_chat.id) != CHAT_ID:
        return

    text = update.message.text
    if not text:
        return

    if not claude:
        await update.message.reply_text("⚠️ ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        return
    if not notion:
        await update.message.reply_text("⚠️ NOTION_API_KEY가 설정되지 않았습니다.")
        return
    if not NOTION_DB_ID:
        await update.message.reply_text("⚠️ NOTION_DB_ID가 설정되지 않았습니다.")
        return

    try:
        result = classify(text)
        save_to_notion(text, result["category"], result["summary"])

        await update.message.reply_text(
            f"✅ 저장 완료!\n\n"
            f"📂 카테고리: {result['category']}\n"
            f"📝 한줄요약: {result['summary']}"
        )
        logger.info(f"저장 완료: [{result['category']}] {result['summary']}")
    except Exception as e:
        logger.error(f"처리 실패: {e}")
        await update.message.reply_text(f"❌ 처리 중 오류가 발생했습니다.\n{e}")


# ───────────────────────────── 메인 ─────────────────────────────

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("생각 덤프 봇 시작!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
