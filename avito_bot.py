import asyncio
import time
import logging
from typing import Dict, List, Set, TypedDict, Optional

from bs4 import BeautifulSoup
from selenium.common.exceptions import WebDriverException
from telegram import Bot
import undetected_chromedriver as uc
from urllib.parse import urlparse
from datetime import datetime

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
# Глобальный словарь для хранения окон браузера и их URL
window_manager: Dict[str, str] = {}  # Ключ - URL, значение - window handle

# === ФУНКЦИИ ===

def create_driver() -> uc.Chrome:
	print(datetime.now(),'Создаем драйвер')
	options = uc.ChromeOptions()
	options.headless = True
	options.add_argument("--disable-blink-features=AutomationControlled")
	options.add_argument("--window-size=390,844")
	options.add_argument("--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1")
	print(datetime.now(),"Драйвер создан")
	return uc.Chrome(options=options)

def get_ads_from_page(driver: uc.Chrome, entry: AvitoEntry, retry_count: int = 0) -> Set[str]:
	try:
		print(datetime.now(),f"Обрабатываем URL: {entry['name']}")

		# Проверяем, есть ли уже окно для этого URL
		if entry['url'] in window_manager:
			window_handle = window_manager[entry['url']]
			try:
				# Переключаемся на существующее окно
				driver.switch_to.window(window_handle)
				print(datetime.now(),f"Перезагружаем существующее окно для {entry['name']}")
				driver.refresh()
			except:
				# Если окно было закрыто, создаем новое
				print(datetime.now(),f"Окно было закрыто, создаем новое для {entry['name']}")
				driver.switch_to.new_window('tab')
				driver.get(entry['url'])
				window_manager[entry['url']] = driver.current_window_handle
		else:
			# Создаем новое окно для нового URL
			print(datetime.now(),f"Создаем новое окно для {entry['name']}")
			driver.switch_to.new_window('tab')
			driver.get(entry['url'])
			window_manager[entry['url']] = driver.current_window_handle

		time.sleep(5)
		html = driver.page_source
		print(datetime.now(),f"Распарсили переданный урл {entry['name']}")

		if "Доступ ограничен" in html or 'items/list' not in html:
			print(datetime.now(),f"[BLOCKED] Попытка {retry_count + 1}")
			bot.send_message(chat_id=CHAT_ID, text=f"[BLOCKED] Попытка {retry_count + 1}")
			if retry_count < MAX_RETRIES:
				time.sleep(900)
				return get_ads_from_page(driver, entry, retry_count + 1)
			else:
				return set()

		soup = BeautifulSoup(html, 'html.parser')
		items_list = soup.find('div', attrs={"data-marker": "items/list"})
		print(datetime.now(),f"Извлекли элементы {entry['name']}")

		if not items_list:
			return set()

		ad_links: Set[str] = set()
		printExample: bool = True
		wrappers = items_list.find_all('div', attrs={"data-marker": lambda x: x and x.startswith("item-wrapper(")})
		for wrapper in wrappers:
			a_tag = wrapper.find('a', attrs={"data-marker": "item/link"})
			if a_tag and a_tag.has_attr("href"):
				raw_link = f"https://m.avito.ru{a_tag['href']}"
				clean_link = urlparse(raw_link)._replace(query="").geturl()
				if printExample:
					print(datetime.now(),f"Пример ссылки: {clean_link}")
					printExample = False
				ad_links.add(clean_link)

		return ad_links

	except WebDriverException as e:
		bot.send_message(chat_id=CHAT_ID, text="Почини меня 1")
		print(datetime.now(),f"[ERROR] Selenium: {e}")
		driver.quit()
		return set()

# === TELEGRAM ===

async def get_chat_id() -> None:
	global CHAT_ID
	updates = await bot.get_updates()
	if updates:
		CHAT_ID = updates[-1].message.chat.id
		print(datetime.now(),f"✅ Чат ID: {CHAT_ID}")
	else:
		print(datetime.now(),"❗ Отправь сообщение боту в Telegram")

async def check_one_url(driver: uc.Chrome, entry: AvitoEntry) -> None:
	current_links = get_ads_from_page(driver, entry)

	if not current_links:
		print(datetime.now(),f"⚠️ Прогрев кэша не удался: пустой список объявлений для {entry['name']}")
	else:
		seen_links_by_url[entry['url']] = current_links
		print(datetime.now(),f"✅ Кэш прогрет для {entry['name']} — {len(current_links)} объявлений")

async def check_one_url_fully(driver: uc.Chrome, entry: AvitoEntry) -> None:
	current_links = get_ads_from_page(driver, entry)
	new_links = current_links - seen_links_by_url.get(entry['url'], set())

	if new_links:
		for link in new_links:
			await bot.send_message(chat_id=CHAT_ID, text=f"🆕 Новое объявление:\n{link} ({entry['name']})")
			print(datetime.now(),f"📨 Новое объявление: {link} ({entry['name']})")
		seen_links_by_url[entry['url']].update(new_links)
	else:
		print(datetime.now(),f"[{entry['name']}] — без новых объявлений")

async def check_new_ads(driver: uc.Chrome) -> None:
	print(datetime.now(),"🔁 Инициализируем кэш...")
	for entry in AVITO_URLS:
		await check_one_url(driver, entry)

	print(datetime.now(),"🔁 Начинается цикл отслеживания...")

	while True:
		try:
			for entry in AVITO_URLS:
				await check_one_url_fully(driver, entry)
		except Exception as e:
			bot.send_message(chat_id=CHAT_ID, text="Почини меня 2")
			print(datetime.now(),"❗ Ошибка в цикле:", e)

		# await asyncio.sleep(CHECK_INTERVAL)

async def main() -> None:
	global CHAT_ID
	print(datetime.now(),"🤖 Бот запускается...")
	driver = create_driver()

	try:
		while CHAT_ID is None:
			await get_chat_id()
			await asyncio.sleep(5)

		await check_new_ads(driver)
	finally:
		bot.send_message(chat_id=CHAT_ID, text="Почини меня 3")
		print(datetime.now(),"🛑 Завершаем работу и закрываем браузер...")
		driver.quit()

if __name__ == "__main__":
	logging.basicConfig(level=logging.INFO)
	asyncio.run(main())
