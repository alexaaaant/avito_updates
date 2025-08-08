import asyncio
import time
import logging
from typing import Dict, List, Set, TypedDict, Optional

from bs4 import BeautifulSoup
from selenium.common.exceptions import WebDriverException
from telegram import Bot
import undetected_chromedriver as uc
from urllib.parse import urlparse

# === Типизация ===

class AvitoEntry(TypedDict):
	url: str
	name: str

# === НАСТРОЙКИ ===

AVITO_URLS: List[AvitoEntry] = [
	{
		"url": "https://m.avito.ru/voronezh/kvartiry/prodam-ASgBAgICAUSSA8YQ?context=H4sIAAAAAAAA_wE9AML_YToyOntzOjg6ImZyb21QYWdlIjtzOjU6InNzZmF2IjtzOjk6ImZyb21fcGFnZSI7czo1OiJzc2ZhdiI7fQMFMC09AAAA&drawId=168979684a93259dc3ea6fe6b0f6d430&f=ASgBAgECBUSSA8YQ5geMUuYW5vwBrL4NpMc1qt8VAgJFkC4UeyJmcm9tIjo2LCJ0byI6bnVsbH3GmgwXeyJmcm9tIjowLCJ0byI6NjAwMDAwMH0&map=e30%3D&s=104",
		"name": "Центр"
	},
	{
		"url": "https://m.avito.ru/voronezh/kvartiry/prodam-ASgBAgICAUSSA8YQ?context=H4sIAAAAAAAA_wE9AML_YToyOntzOjg6ImZyb21QYWdlIjtzOjU6InNzZmF2IjtzOjk6ImZyb21fcGFnZSI7czo1OiJzc2ZhdiI7fQMFMC09AAAA&drawId=e1a1dd8bf19ed639227b69a8a8eec84e&f=ASgBAgECBUSSA8YQ5geMUuYW5vwBrL4NpMc1qt8VAgJFkC4UeyJmcm9tIjo2LCJ0byI6bnVsbH3GmgwXeyJmcm9tIjowLCJ0byI6NjAwMDAwMH0&map=e30%3D&s=104",
		"name": "Северный"
	},
]

TELEGRAM_TOKEN: str = '1048191428:AAE9Jn95v7z68Q5Nx-VxHXbPCejG1wn-Ypg'
CHECK_INTERVAL: int = 60  # В секундах
MAX_RETRIES: int = 3

# === СОСТОЯНИЕ ===

seen_links_by_url: Dict[str, Set[str]] = {}
bot: Bot = Bot(token=TELEGRAM_TOKEN)
CHAT_ID: Optional[int] = None

# === ФУНКЦИИ ===

def create_driver() -> uc.Chrome:
	print('Создаем драйвер')
	options = uc.ChromeOptions()
	options.headless = True
	options.add_argument("--disable-blink-features=AutomationControlled")
	options.add_argument("--window-size=390,844")
	options.add_argument("--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1")
	print("Драйвер создан")
	return uc.Chrome(options=options)

def get_ads_from_page(driver: uc.Chrome, entry: AvitoEntry, retry_count: int = 0) -> Set[str]:
	try:
		print(f"Передали урл в драйвер {entry['name']}")
		driver.get(entry['url'])
		time.sleep(5)
		html = driver.page_source
		print(f"Распарсили переданный урл {entry['name']}")

		if "Доступ ограничен" in html or 'items/list' not in html:
			print(f"[BLOCKED] Попытка {retry_count + 1}")
			bot.send_message(chat_id=CHAT_ID, text=f"[BLOCKED] Попытка {retry_count + 1}")
			if retry_count < MAX_RETRIES:
				time.sleep(900)
				return get_ads_from_page(driver, entry, retry_count + 1)
			else:
				return set()

		soup = BeautifulSoup(html, 'html.parser')
		items_list = soup.find('div', attrs={"data-marker": "items/list"})
		print(f"Извлекли элементы {entry['name']}")

		if not items_list:
			return set()

		ad_links: Set[str] = set()
		wrappers = items_list.find_all('div', attrs={"data-marker": lambda x: x and x.startswith("item-wrapper(")})
		for wrapper in wrappers:
			a_tag = wrapper.find('a', attrs={"data-marker": "item/link"})
			if a_tag and a_tag.has_attr("href"):
				raw_link = f"https://m.avito.ru{a_tag['href']}"
				clean_link = urlparse(raw_link)._replace(query="").geturl()
				ad_links.add(clean_link)

		if ad_links:
			print(f"Пример ссылки: {next(iter(ad_links))}")

		return ad_links

	except WebDriverException as e:
		print(f"[ERROR] Selenium: {e}")
		return set()

# === TELEGRAM ===

async def get_chat_id() -> None:
	global CHAT_ID
	updates = await bot.get_updates()
	if updates:
		CHAT_ID = updates[-1].message.chat.id
		print(f"✅ Чат ID: {CHAT_ID}")
	else:
		print("❗ Отправь сообщение боту в Telegram")

async def check_one_url(driver: uc.Chrome, entry: AvitoEntry) -> None:
	current_links = get_ads_from_page(driver, entry)

	if not current_links:
		print(f"⚠️ Прогрев кэша не удался: пустой список объявлений для {entry['name']}")
	else:
		seen_links_by_url[entry['url']] = current_links
		print(f"✅ Кэш прогрет для {entry['name']} — {len(current_links)} объявлений")

async def check_one_url_fully(driver: uc.Chrome, entry: AvitoEntry) -> None:
	current_links = get_ads_from_page(driver, entry)
	new_links = current_links - seen_links_by_url.get(entry['url'], set())

	if new_links:
		for link in new_links:
			await bot.send_message(chat_id=CHAT_ID, text=f"🆕 Новое объявление:\n{link} ({entry['name']})")
			print(f"📨 Новое объявление: {link} ({entry['name']})")
		seen_links_by_url[entry['url']].update(new_links)
	else:
		print(f"[{entry['name']}] — без новых объявлений")

async def check_new_ads(driver: uc.Chrome) -> None:
	print("🔁 Инициализируем кэш...")
	for entry in AVITO_URLS:
		await check_one_url(driver, entry)
		await asyncio.sleep(CHECK_INTERVAL)

	print("🔁 Начинается цикл отслеживания...")

	while True:
		try:
			for entry in AVITO_URLS:
				await check_one_url_fully(driver, entry)
				await asyncio.sleep(CHECK_INTERVAL)
		except Exception as e:
			print("❗ Ошибка в цикле:", e)

		await asyncio.sleep(CHECK_INTERVAL)

async def main() -> None:
	global CHAT_ID
	print("🤖 Бот запускается...")
	driver = create_driver()

	try:
		while CHAT_ID is None:
			await get_chat_id()
			await asyncio.sleep(5)

		await check_new_ads(driver)
	finally:
		print("🛑 Завершаем работу и закрываем браузер...")
		driver.quit()

if __name__ == "__main__":
	logging.basicConfig(level=logging.INFO)
	asyncio.run(main())
