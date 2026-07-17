#!/usr/bin/env python3
"""ТГ-дайджест госзакупок: t.me/s/<channel> -> Telegram.

Живёт на US-раннере GitHub, потому что с Windows и с VPS (российские IP)
недоступны и t.me, и api.telegram.org. Раннер достаёт до обоих.
Ни БД, ни avto, ни Windows в цепочке не участвуют.
"""
import datetime as dt
import os
import sys
import time

import requests
from bs4 import BeautifulSoup

# username, title, priority: 1 = официальные, 2 = новостные/эксперты, 3 = фон
CHANNELS = [
    ("gis_eiszakupki", "ЕИС Закупки (Казначейство)", 1),
    ("minfin", "Минфин России", 1),
    ("TreasuryofRussia", "Казначейство России", 1),
    ("fasrussia", "ФАС России", 1),
    ("minpromtorg_ru", "Минпромторг России", 1),
    ("consultant_plus", "КонсультантПлюс", 1),
    ("zakupki44fz", "Закупки и тендеры 44/223-ФЗ", 2),
    ("progoszakaz", "ПРО-ГОСЗАКАЗ.РУ", 2),
    ("cennyikontrakt", "Ценный контракт", 2),
    ("allzakupki", "allzakupki", 2),
    ("roszakupki", "roszakupki", 2),
    ("zak44fz", "zak44fz", 2),
    ("abusinessacademy", "A-Business Academy", 3),
    ("rosstatinfo", "Росстат", 3),
]

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124 Safari/537.36"
    )
}
MSK = dt.timezone(dt.timedelta(hours=3))
LABELS = {1: "🏛 ОФИЦИАЛЬНЫЕ", 2: "📰 НОВОСТНЫЕ / ЭКСПЕРТНЫЕ", 3: "📊 ФОН"}
CHUNK = 3500  # запас под лимит Telegram в 4096 символов
SNIPPET = 200


def fetch(username):
    r = requests.get("https://t.me/s/%s" % username, headers=UA, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for m in soup.select("div.tgme_widget_message"):
        stamp = m.select_one(".tgme_widget_message_date time")
        if not stamp or not stamp.get("datetime"):
            continue
        try:
            posted = dt.datetime.fromisoformat(stamp["datetime"])
        except ValueError:
            continue
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=dt.timezone.utc)
        body = m.select_one(".tgme_widget_message_text")
        views = m.select_one(".tgme_widget_message_views")
        link = m.select_one("a.tgme_widget_message_date")
        out.append(
            {
                "posted": posted,
                "text": body.get_text(" ", strip=True) if body else "[медиа без текста]",
                "views": views.get_text(strip=True) if views else "",
                "url": link.get("href", "") if link else "",
            }
        )
    return out


def send(token, chat, text):
    r = requests.post(
        "https://api.telegram.org/bot%s/sendMessage" % token,
        data={"chat_id": chat, "text": text, "disable_web_page_preview": "true"},
        timeout=30,
    )
    # тело ответа не печатаем — репозиторий публичный, логи видны всем
    if r.status_code != 200:
        raise RuntimeError("telegram http %s" % r.status_code)


def chunks(lines):
    buf = ""
    for line in lines:
        if buf and len(buf) + len(line) + 1 > CHUNK:
            yield buf
            buf = line
        else:
            buf = buf + "\n" + line if buf else line
    if buf:
        yield buf


def main():
    token = os.environ.get("TG_TOKEN", "")
    chat = os.environ.get("TG_CHAT", "")
    if not token or not chat:
        print("::error::no telegram secrets")
        return 1
    try:
        hours = int(os.environ.get("HOURS") or 24)
    except ValueError:
        hours = 24

    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=hours)

    posts, failed = [], []
    for username, title, priority in CHANNELS:
        try:
            for p in fetch(username):
                if p["posted"] >= cutoff:
                    p.update(username=username, title=title, priority=priority)
                    posts.append(p)
        except Exception as exc:  # канал не должен рушить весь дайджест
            failed.append("%s (%s)" % (username, type(exc).__name__))
        time.sleep(1.0)  # вежливость к t.me

    posts.sort(key=lambda p: (p["priority"], -p["posted"].timestamp()))

    head = "📋 ТГ-дайджест госзакупок — %s" % now.astimezone(MSK).strftime("%d.%m.%Y")
    head += "\nЗа %dч: %d постов, каналов ok %d/%d" % (
        hours,
        len(posts),
        len(CHANNELS) - len(failed),
        len(CHANNELS),
    )
    if failed:
        head += "\n⚠️ не ответили: " + ", ".join(failed)

    if not posts:
        send(token, chat, head + "\n\nНовых постов нет.")
        print("sent: empty digest, failed=%d" % len(failed))
        return 0

    lines, cur_priority, cur_channel = [], None, None
    for p in posts:
        if p["priority"] != cur_priority:
            cur_priority, cur_channel = p["priority"], None
            lines.append("")
            lines.append(LABELS[p["priority"]])
        if p["title"] != cur_channel:
            cur_channel = p["title"]
            lines.append("")
            lines.append("— %s" % cur_channel)
        snippet = " ".join(p["text"].split())
        if len(snippet) > SNIPPET:
            snippet = snippet[:SNIPPET] + "…"
        views = " 👁%s" % p["views"] if p["views"] else ""
        lines.append(
            "[%s]%s %s" % (p["posted"].astimezone(MSK).strftime("%d.%m %H:%M"), views, snippet)
        )
        if p["url"]:
            lines.append(p["url"])

    parts = list(chunks(lines))
    for i, part in enumerate(parts, 1):
        prefix = head + "\n" if i == 1 else "(%d/%d)\n" % (i, len(parts))
        send(token, chat, prefix + part)
        time.sleep(1.2)  # не упереться в rate-limit Telegram

    print("sent: %d posts in %d messages, failed=%d" % (len(posts), len(parts), len(failed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
