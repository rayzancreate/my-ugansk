import asyncio
import logging
import aiohttp
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import re
import ssl
import certifi

# --- НАСТРОЙКИ ---
TG_TOKEN = "8650938057:AAHCYIsmS5LYdl25o2wZa93DO1Ak-L1l-c4"
USE_PROXY = False  # Измени на True, если нужен прокси
PROXY_URL = "http://user:password@ip:port"  # Заполни, если USE_PROXY = True
# --- Конец настроек ---

# Логирование
logging.basicConfig(level=logging.INFO)

# Создаем SSL контекст (решает многие проблемы с соединением)
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Настройки для сессии
connector = aiohttp.TCPConnector(ssl=ssl_context, force_close=True, enable_cleanup_closed=True)

# Инициализация бота с поддержкой прокси
if USE_PROXY:
    from aiohttp_socks import ProxyConnector

    connector = ProxyConnector.from_url(PROXY_URL, ssl=ssl_context)
    bot = Bot(token=TG_TOKEN, connector=connector)
else:
    bot = Bot(token=TG_TOKEN, connector=connector)

dp = Dispatcher()

# Источники новостей Нефтеюганска
SOURCES = [
    {
        'name': 'Яндекс.Новости',
        'url': 'https://yandex.ru/news/region/nefteyugansk',
        'type': 'yandex'
    },
    {
        'name': 'Администрация Нефтеюганска (официально)',
        'url': 'https://vk.com/nefteyugansk_adm',
        'type': 'vk'
    },
    {
        'name': 'Типичный Нефтеюганск',
        'url': 'https://vk.com/nefteyugansk_86',
        'type': 'vk'
    }
]


def check_credibility(title: str, text: str = "", source_type: str = "") -> tuple:
    """Проверка достоверности новости"""
    title_lower = title.lower()
    text_lower = text.lower()

    if "администрация" in source_type.lower() or "официально" in source_type.lower():
        return True, "официальный источник"

    fake_indicators = {
        'шок': 'кликбейт',
        'сенсация': 'кликбейт',
        'фейк': 'саморазоблачение',
        'вброс': 'саморазоблачение',
        'распродажа': 'реклама',
        'купить': 'реклама',
        'скандал': 'кликбейт',
        'ужас': 'кликбейт'
    }

    for word, reason in fake_indicators.items():
        if word in title_lower:
            return False, f"маркер '{word}'"

    return True, "достоверно"


async def fetch_html(session, url):
    """Получение HTML страницы"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Connection': 'keep-alive',
        }
        timeout = aiohttp.ClientTimeout(total=30)
        async with session.get(url, headers=headers, timeout=timeout, ssl=ssl_context) as response:
            if response.status == 200:
                return await response.text()
            else:
                logging.error(f"Статус {response.status} для {url}")
    except asyncio.TimeoutError:
        logging.error(f"Таймаут при загрузке {url}")
    except Exception as e:
        logging.error(f"Ошибка загрузки {url}: {e}")
    return None


async def parse_yandex_news(session, source):
    """Парсинг Яндекс.Новостей"""
    news_list = []
    html = await fetch_html(session, source['url'])
    if not html:
        return news_list

    soup = BeautifulSoup(html, 'html.parser')

    # Поиск новостей
    items = soup.find_all('a', class_='mg-card__link') or \
            soup.find_all('a', class_='news-card__link') or \
            soup.find_all('h2')

    for item in items[:5]:
        try:
            if item.name == 'a':
                title = item.get_text(strip=True)
                link = item.get('href')
            else:
                parent_link = item.find_parent('a')
                if not parent_link:
                    continue
                title = item.get_text(strip=True)
                link = parent_link.get('href')

            if link and not link.startswith('http'):
                link = 'https://yandex.ru' + link

            if title and len(title) > 10:
                is_credible, reason = check_credibility(title, source_type=source['name'])
                mark = "✅" if is_credible else "⚠️"

                news_list.append({
                    'title': title,
                    'link': link,
                    'source': source['name'],
                    'credible': is_credible,
                    'credibility_reason': reason,
                    'mark': mark
                })
        except Exception as e:
            logging.error(f"Ошибка парсинга: {e}")

    return news_list


async def parse_vk_news(session, source):
    """Парсинг новостей ВКонтакте"""
    news_list = []
    html = await fetch_html(session, source['url'])
    if not html:
        return news_list

    soup = BeautifulSoup(html, 'html.parser')

    # Поиск постов ВК
    posts = soup.find_all('div', class_='post') or \
            soup.find_all('div', class_='wall_post')

    for post in posts[:3]:
        try:
            text_elem = post.find('div', class_='wall_post_text') or \
                        post.find('div', class_='post_text')

            if not text_elem:
                continue

            full_text = text_elem.get_text(strip=True)
            if len(full_text) < 20:
                continue

            title = full_text[:150] + "..." if len(full_text) > 150 else full_text

            # Формируем ссылку
            post_link = source['url']

            is_credible, reason = check_credibility(title, full_text, source['name'])
            mark = "✅" if is_credible else "⚠️"

            news_list.append({
                'title': title,
                'link': post_link,
                'source': source['name'],
                'credible': is_credible,
                'credibility_reason': reason,
                'mark': mark
            })
        except Exception as e:
            logging.error(f"Ошибка парсинга ВК: {e}")

    return news_list


async def collect_news():
    """Сбор новостей"""
    all_news = []

    async with aiohttp.ClientSession(connector=connector) as session:
        for source in SOURCES:
            logging.info(f"Парсинг: {source['name']}")

            try:
                if source['type'] == 'yandex':
                    news = await parse_yandex_news(session, source)
                else:
                    news = await parse_vk_news(session, source)

                all_news.extend(news)
                await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Ошибка {source['name']}: {e}")

    # Убираем дубликаты
    unique_news = []
    seen_titles = set()

    for news in all_news:
        title_key = news['title'][:50]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_news.append(news)

    unique_news.sort(key=lambda x: x['credible'], reverse=True)
    return unique_news


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 *Бот новостей Нефтеюганска*\n\n"
        "Команды:\n"
        "/news - Получить свежие новости",
        parse_mode='Markdown'
    )


@dp.message(Command("news"))
async def cmd_news(message: types.Message):
    await message.answer("🔍 *Ищу новости...*", parse_mode='Markdown')

    try:
        news_items = await collect_news()

        if not news_items:
            await message.answer("😕 Новостей нет. Попробуй позже.")
            return

        credible = sum(1 for item in news_items if item['credible'])
        await message.answer(f"📊 Найдено: {len(news_items)} (✅ {credible} достоверных)")

        for i, item in enumerate(news_items[:7], 1):
            text = (
                f"{item['mark']} *{i}. {item['title']}*\n"
                f"📎 {item['source']}\n"
                f"[Ссылка]({item['link']})"
            )
            await message.answer(text, parse_mode='Markdown', disable_web_page_preview=True)
            await asyncio.sleep(0.5)

    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await message.answer("❌ Ошибка при получении новостей")


async def main():
    print("🤖 Бот запускается...")
    print("📡 Проверка соединения с Telegram...")

    try:
        # Проверяем соединение
        me = await bot.get_me()
        print(f"✅ Бот @{me.username} успешно подключен!")
        print("⚡ Жду команды /news...")
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        print("\n🔧 РЕШЕНИЕ:")
        print("1. Проверь интернет")
        print("2. Отключи антивирус/файрвол временно")
        print("3. Попробуй использовать VPN")
        print("4. Включи прокси в настройках (USE_PROXY = True)")


if __name__ == "__main__":
    asyncio.run(main())